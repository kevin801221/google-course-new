"""端到端 smoke test：用「假的訂房服務」驗 A2A 這條線，不連網、不花錢、不用 API key。

起一個純 a2a-sdk 寫的假服務（回罐頭答案，裡面沒有 LLM），
再用 concierge 的 RemoteA2aAgent 透過 ADK Runner 呼它，assert 罐頭字串真的跑回來。
驗到的是：名片發現 → origin 檢查 → JSON-RPC 送訊息 → task/artifact 轉回 ADK event。
沒驗到的是真的 hotel_agent（那需要 Gemini API key，見 walkthrough 步驟 4）。

跑法：
  uv run smoke_test.py
  uv run smoke_test.py --self-check     # 只驗事件解析邏輯，連 server 都不起
  SMOKE_PORT=8098 uv run smoke_test.py  # 8099 被別的東西佔住時換 port
"""

import asyncio
import contextlib
import os
import sys
import threading
import urllib.request

CANNED = "淺草和風旅館 2400 TWD"
PORT = int(os.getenv("SMOKE_PORT", "8099"))  # 故意不是 8001，避免撞到你手動開的服務 B；被佔就 SMOKE_PORT=8098


# ── 假的 A2A 服務（投影片 9.3 的骨架，把 LLM 換成罐頭字串）─────────────
def build_app(port: int):
    import uvicorn  # noqa: F401  確認裝了 http-server 那組相依
    from a2a.helpers import new_task_from_user_message, new_text_message, new_text_part
    from a2a.server.agent_execution import AgentExecutor
    from a2a.server.request_handlers import DefaultRequestHandler
    from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
    from a2a.server.tasks import InMemoryTaskStore, TaskUpdater
    from a2a.types import AgentCapabilities, AgentCard, AgentInterface, AgentSkill, TaskState
    from starlette.applications import Starlette

    card = AgentCard(
        name="fake_hotel_agent",
        description="假的訂房服務，只會回罐頭答案。",
        version="0.0.1",
        default_input_modes=["text/plain"],
        default_output_modes=["text/plain"],
        capabilities=AgentCapabilities(streaming=True),
        supported_interfaces=[
            AgentInterface(
                protocol_binding="JSONRPC",
                url=f"http://localhost:{port}/",  # 必須跟抓名片的 origin 一致
                protocol_version="1.0",
            )
        ],
        skills=[
            AgentSkill(
                id="search_hotels",
                name="Hotel Search",
                description="依城市與預算搜尋旅館。",
                tags=["travel"],
                examples=["東京 3000 內"],
            )
        ],
    )

    class FakeExecutor(AgentExecutor):
        async def execute(self, context, event_queue) -> None:
            task = context.current_task or new_task_from_user_message(context.message)
            if not context.current_task:
                await event_queue.enqueue_event(task)
            up = TaskUpdater(event_queue=event_queue, task_id=task.id, context_id=task.context_id)
            await up.update_status(
                state=TaskState.TASK_STATE_WORKING,
                message=new_text_message("搜尋中…"),
            )
            await up.add_artifact(parts=[new_text_part(text=CANNED, media_type="text/plain")])
            await up.update_status(state=TaskState.TASK_STATE_COMPLETED)

        async def cancel(self, context, event_queue) -> None:
            raise NotImplementedError

    handler = DefaultRequestHandler(
        agent_executor=FakeExecutor(), task_store=InMemoryTaskStore(), agent_card=card
    )
    routes = [*create_agent_card_routes(card), *create_jsonrpc_routes(handler, "/")]
    return Starlette(routes=routes)


@contextlib.contextmanager
def serving(port: int):
    """背景 thread 跑 uvicorn，等名片抓得到才 yield。"""
    import uvicorn

    server = uvicorn.Server(uvicorn.Config(build_app(port), host="localhost", port=port, log_level="warning"))
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    url = f"http://localhost:{port}/.well-known/agent-card.json"
    for _ in range(100):  # ponytail: 輪詢 10 秒；要更漂亮就用 server.started 事件
        try:
            urllib.request.urlopen(url, timeout=1).read()
            break
        except OSError:
            threading.Event().wait(0.1)
    else:
        raise RuntimeError(f"假服務起不來：{url}（port 被佔？換 SMOKE_PORT=8098 再試）")
    try:
        yield f"http://localhost:{port}"
    finally:
        server.should_exit = True
        t.join(timeout=5)


# ── 事件解析（這段是 --self-check 真正在驗的邏輯）────────────────────
def text_of(event) -> str:
    """把一個 ADK event 身上所有 text part 串起來。欄位隨時可能是 None。"""
    content = getattr(event, "content", None)
    return "".join(getattr(p, "text", None) or "" for p in (getattr(content, "parts", None) or []))


async def ask_remote(base: str, question: str) -> list:
    """走完 RemoteA2aAgent 的完整路徑，回傳每個 event 的文字。"""
    from google.adk.artifacts.in_memory_artifact_service import InMemoryArtifactService
    from google.adk.runners import Runner
    from google.adk.sessions.in_memory_session_service import InMemorySessionService
    from google.genai import types

    import concierge.agent as ca

    remote = ca.RemoteA2aAgent(
        name="hotel_agent",
        description="假的訂房服務",
        agent_card=ca.card_url(base),
        timeout=30.0,
    )
    session_service = InMemorySessionService()
    runner = Runner(
        app_name="smoke",
        agent=remote,  # 直接跑遠端 agent：不經過 LLM，所以不用 API key
        session_service=session_service,
        artifact_service=InMemoryArtifactService(),
    )
    await session_service.create_session(app_name="smoke", user_id="u", session_id="s")
    msg = types.Content(role="user", parts=[types.Part(text=question)])
    out = []
    async for ev in runner.run_async(user_id="u", session_id="s", new_message=msg):
        out.append(text_of(ev))
    await remote.cleanup()  # 不關就會留一個 httpx client，程式結束時噴 unclosed session 警告
    return out


def _self_check() -> None:
    from types import SimpleNamespace as NS

    part = lambda t: NS(text=t)
    assert text_of(NS(content=NS(parts=[part("淺草"), part("和風旅館")]))) == "淺草和風旅館"
    assert text_of(NS(content=NS(parts=[part(None), part("x")]))) == "x"   # text=None 不能炸
    assert text_of(NS(content=NS(parts=None))) == ""                       # parts=None 不能炸
    assert text_of(NS(content=None)) == ""                                 # 狀態事件沒有 content
    assert text_of(NS()) == ""                                             # 連 content 屬性都沒有
    assert CANNED not in "".join(["", ""])                                 # 空回應不該被判成過關
    print("self-check ok")


def main() -> int:
    with serving(PORT) as base:
        texts = asyncio.run(ask_remote(base, "東京 3000 以內的旅館"))
    joined = "\n".join(t for t in texts if t)
    print(joined or "(沒有任何文字事件)")
    assert CANNED in joined, f"罐頭答案沒回來，收到的是：{texts!r}"
    print(f"smoke ok（{len(texts)} 個 event，罐頭答案有回來）")
    return 0


if __name__ == "__main__":
    if "--self-check" in sys.argv:
        _self_check()
        sys.exit(0)
    sys.exit(main())
