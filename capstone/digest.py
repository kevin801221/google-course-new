"""Phase 2 排程工作流：每日摘要（ADK Workflow / Graph）。純函式節點撈資料（零 token）、LLM 節點只寫作。

跑法：
  uv run digest.py --self-check          # 離線：真的跑一遍 Workflow 的 EMPTY 分支，不連網不花錢
  uv run digest.py --dry-run             # 同上，但把假資料換成「有新文件」，看路由走哪條（仍不呼叫 LLM）
  uv run digest.py --broken              # 故意重現投影片寫法的 ValidationError（教學用）
  uv run digest.py                       # 真的：查 Supabase + 呼叫 LLM 產日報

環境變數：DATABASE_URL（撈昨日新增）、GEMINI_API_KEY（寫作節點）
排程：Cloud Scheduler 每天 08:00 打 concierge 服務的 /run，或本機 Antigravity /schedule
"""

import asyncio
import os
import sys
from typing import Any

from google.adk import Agent, Event, Runner, Workflow
from google.adk.sessions import InMemorySessionService
from google.genai import types

import wiki_core

_FAKE_ROWS: list[dict] | None = None  # 只有 --dry-run / --self-check 會設它
STATE_FILE = os.path.expanduser("~/.capstone_last_digest_id")


def last_digest_id() -> int:
    """上次做到哪一筆。ponytail: 存在家目錄的一個檔案就夠；要多機共用再換成 DB 的 state 表。"""
    try:
        return int(open(STATE_FILE).read().strip())
    except (OSError, ValueError):
        return 0


def save_digest_id(doc_id: int) -> None:
    open(STATE_FILE, "w").write(str(doc_id))


async def fetch_new_docs(ctx, node_input: Any = None):
    """純函式節點：撈昨天之後新增的文件。沒有新東西就走 EMPTY 分支（省下一次 LLM 呼叫）。"""
    if _FAKE_ROWS is not None:
        rows = _FAKE_ROWS
    else:
        conn = await wiki_core._conn()
        try:
            rows = [dict(r) for r in await conn.fetch(wiki_core.NEW_DOCS_SQL, last_digest_id())]
        finally:
            await conn.close()
    if not rows:
        ctx.route = "EMPTY"
        return "（沒有新增文件）"  # 一定要給 output，下游節點的 node_input 才不會是 None
    ctx.route = "HAS_DOCS"
    if _FAKE_ROWS is None:
        save_digest_id(max(r["id"] for r in rows))
    return "\n---\n".join(f"[{r['source']}]\n{(r['content'] or '')[:1500]}" for r in rows)


def render_empty(node_input: str | None = None) -> str:
    """沒有新知識時的固定輸出。node_input 必須容許 None，見下方 broken 示範。"""
    return "# 今日日報\n\n今日無新增知識。"


digest_agent = Agent(  # single-turn 寫作節點：只做排版，不做決策
    model="gemini-3.7-flash",  # 型號名以課程投影片為準
    name="digest_writer",
    instruction=(
        "把使用者給的新增內容寫成繁體中文 Markdown 日報，固定三段："
        "「## 今日重點」（3 條，每條一行）、「## 值得深讀」（挑 1 篇並說明為什麼）、"
        "「## 待辦建議」（2 條可執行的動作）。每個重點後面用括號標出來源。"
    ),
)

daily_digest = Workflow(
    name="daily_digest",
    edges=[
        ("START", fetch_new_docs),
        (fetch_new_docs, {"EMPTY": render_empty, "HAS_DOCS": digest_agent}),
    ],
)


def broken_render(node_input: str) -> str:
    """投影片的寫法：node_input 標成 str。上游沒給 output 時 node_input 是 None → pydantic 攔在入口。"""
    return "# 今日日報\n\n今日無新增知識。"


def broken_render_docs(node_input: str) -> str:
    return "有新文件"


async def broken_fetch(node_input: Any = None):
    """投影片的寫法：回傳 Event(route=...) 但沒有 output。route 有效，但下游會炸。"""
    return Event(route="EMPTY")


broken_digest = Workflow(
    name="broken_digest",
    edges=[("START", broken_fetch), (broken_fetch, {"EMPTY": broken_render, "HAS_DOCS": broken_render_docs})],
)


async def silent_fetch(node_input: Any = None):
    """更陰險的寫法：Event 帶了 author。author 不等於節點名 → route 被靜靜丟掉，整條分支直接結束。"""
    return Event(author="fetch", route="EMPTY")  # 節點名是 silent_fetch，author 卻是 fetch


def silent_render(node_input: Any = None) -> str:
    return "永遠不會被執行到"


def silent_render_docs(node_input: Any = None) -> str:
    return "也不會"


silent_digest = Workflow(
    name="silent_digest",
    edges=[("START", silent_fetch), (silent_fetch, {"EMPTY": silent_render, "HAS_DOCS": silent_render_docs})],
)


async def run_workflow(wf: Workflow, text: str = "產生今日日報") -> list[str]:
    """跑一次 workflow，回傳各節點的 output（純函式節點不花錢，LLM 節點才會計費）。"""
    ss = InMemorySessionService()
    runner = Runner(app_name="capstone", agent=wf, session_service=ss)
    await ss.create_session(app_name="capstone", user_id="me", session_id="digest")
    outs = []
    async for ev in runner.run_async(
        user_id="me",
        session_id="digest",
        new_message=types.Content(role="user", parts=[types.Part(text=text)]),
    ):
        if ev.output:
            outs.append(str(ev.output))
        elif ev.content and ev.content.parts and ev.content.parts[0].text:
            outs.append(ev.content.parts[0].text)
    return outs


def _self_check() -> None:
    global _FAKE_ROWS
    _FAKE_ROWS = []  # 沒有新文件 → EMPTY 分支，LLM 節點不會被叫到
    try:
        outs = asyncio.run(run_workflow(daily_digest))
        assert any("今日無新增知識" in o for o in outs), outs
        assert not any("今日重點" in o for o in outs), "EMPTY 分支不該叫到 LLM 節點"
    finally:
        _FAKE_ROWS = None

    # 投影片寫法必炸：上游只回 Event(route=...) 沒有 output + 下游標 str → pydantic 攔在節點入口
    try:
        asyncio.run(run_workflow(broken_digest))
        raise AssertionError("broken 版本應該要炸")
    except AssertionError:
        raise
    except Exception as e:
        assert "valid string" in str(e), e

    # 更陰險：Event(author=...) 的 author 不等於節點名 → route 被丟掉，沒有例外、沒有輸出
    assert asyncio.run(run_workflow(silent_digest)) == [], "author 不符時 route 應該被丟掉"

    # 路由字串要跟 edges 的 key 完全一致，打錯字不會報錯、只會安靜地什麼都不做
    keys = set()
    for edge in daily_digest.edges:
        if isinstance(edge[1], dict):
            keys |= set(edge[1])
    assert keys == {"EMPTY", "HAS_DOCS"}, keys

    assert last_digest_id() >= 0
    print("digest self-check OK", file=sys.stderr)


def main(argv: list[str]) -> int:
    global _FAKE_ROWS
    if "--broken" in argv:
        print("① 靜默失敗：Event(author=...) 的 author 不等於節點名 → route 被丟掉")
        print("   輸出 =", asyncio.run(run_workflow(silent_digest)), "（空的，而且沒有任何例外）")
        print("② 明顯失敗：下游 node_input 標成 str，上游沒給 output → 下面這個 traceback")
        asyncio.run(run_workflow(broken_digest))  # 一定會拋例外，這就是教學重點
        return 1
    if "--dry-run" in argv:
        _FAKE_ROWS = [
            {"id": 1, "source": "https://a2a-protocol.org", "content": "A2A 1.0 的 Task 生命週期…"},
            {"id": 2, "source": "notes/cloudrun.md", "content": "Cloud Run GPU 定價筆記…"},
        ]
        print("dry-run：假資料兩筆 → 應走 HAS_DOCS（LLM 節點需要 key，這裡只印路由）")
        try:
            for o in asyncio.run(run_workflow(daily_digest)):
                print("---\n" + o[:400])
        except Exception as e:
            print(f"路由 → HAS_DOCS，卡在 LLM 寫作節點（正常，需要 key）：{type(e).__name__}", file=sys.stderr)
        return 0
    for o in asyncio.run(run_workflow(daily_digest)):
        print(o)
    return 0


if __name__ == "__main__":
    if "--self-check" in sys.argv:
        _self_check()
    else:
        raise SystemExit(main(sys.argv[1:]))
