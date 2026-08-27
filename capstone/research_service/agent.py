"""Phase 4：把 research_agent 獨立成 A2A 服務（研究任務重、要獨立擴展）。

跑法（在 capstone/ 執行）：
  uv run research_service/agent.py --self-check                          # 離線，不連網不花錢
  uv run uvicorn research_service.agent:a2a_app --port 8001              # 本機起服務
  curl -s localhost:8001/.well-known/agent-card.json | uv run python -m json.tool

環境變數：
  A2A_PORT=8001                    名片上要寫的 port，必須跟 uvicorn --port 一致
  A2A_PUBLIC_URL                   上 Cloud Run 後填服務網址，名片才不會寫 localhost
"""

import os
import sys

from google.adk.agents import Agent
from google.adk.tools import google_search

PORT = int(os.getenv("A2A_PORT", "8001"))

root_agent = Agent(
    model="gemini-3.7-flash",  # 型號名以課程投影片為準；若 404 用 client.models.list() 確認
    name="research_agent",
    # description 會被抄進 agent card 的 skill description —— 別人的 agent 靠這段決定要不要委託你
    description="研究員：上網深入調查一個主題、交叉驗證多個來源，整理成含來源網址的繁體中文報告。",
    instruction=(
        "你是研究員。步驟：google_search 搜尋 → 交叉驗證至少兩個來源 → 輸出報告，"
        "格式固定為「## 結論 / ## 細節 / ## 來源（附網址）」。"
        "查不到就說查不到，不要用訓練記憶補。報告要能直接被存進知識庫，所以不要寫寒暄。"
    ),
    tools=[google_search],  # google_search 必須獨占；這也是把研究員拆成獨立服務的原因之一
)


def build_app():
    """to_a2a 會自動生 /.well-known/agent-card.json。上雲要給 public URL，不然名片寫 localhost 沒人連得上。"""
    from google.adk.a2a.utils.agent_to_a2a import to_a2a

    public = os.getenv("A2A_PUBLIC_URL", "").strip()
    if public:
        from urllib.parse import urlparse

        u = urlparse(public)
        return to_a2a(root_agent, host=u.hostname or "0.0.0.0", port=u.port or 443, protocol=u.scheme or "https")
    return to_a2a(root_agent, host="0.0.0.0", port=PORT)


def _self_check() -> None:
    assert root_agent.tools == [google_search], root_agent.tools  # 只能有 google_search
    assert root_agent.description and "研究" in root_agent.description
    assert "## 來源" in root_agent.instruction  # 報告格式要能被 ingest 直接吃
    assert PORT == int(os.getenv("A2A_PORT", "8001"))
    # 名片路徑是協定寫死的，別自己拼
    from google.adk.agents.remote_a2a_agent import AGENT_CARD_WELL_KNOWN_PATH

    assert AGENT_CARD_WELL_KNOWN_PATH == "/.well-known/agent-card.json", AGENT_CARD_WELL_KNOWN_PATH
    print("research_service self-check OK", file=sys.stderr)


if __name__ == "__main__":
    if "--self-check" in sys.argv:
        _self_check()
    else:
        print(__doc__)
else:
    # uvicorn 匯入時才建 app：--self-check 不需要它，省掉一次 experimental warning
    a2a_app = build_app() if os.getenv("A2A_SKIP_APP") != "1" else None
