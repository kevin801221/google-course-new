"""Phase 2：concierge 團隊（root＋三個專員）。Phase 4 設了 RESEARCH_A2A_URL 之後，研究員自動換成遠端 A2A 服務。

跑法：
  uv run python -m concierge.agent --self-check   # 離線驗團隊接線，不連網不花錢
  uv run adk web                                  # 在 capstone/ 執行，左上角選 concierge
  uv run adk eval concierge tests/capstone.evalset.json --print_detailed_results

環境變數：
  TOOLBOX_URL          MCP Toolbox 的 URL，預設 http://127.0.0.1:5000（本機）
  RESEARCH_A2A_URL     設了就用遠端研究員（Phase 4）；沒設就本機跑 google_search 版
  GOOGLE_API_KEY / GEMINI_API_KEY   模型呼叫用
"""

import os
import sys

from google.adk.agents import Agent
from google.adk.agents.remote_a2a_agent import AGENT_CARD_WELL_KNOWN_PATH, RemoteA2aAgent
from google.adk.tools import google_search
from google.adk.tools.toolbox_toolset import ToolboxToolset

from .tools import ingest_document, search_knowledge

FLASH = "gemini-3.7-flash"  # 型號名以課程投影片為準；若 404 用 client.models.list() 確認
LITE = "gemini-3.5-flash-lite"  # 查表這種雜活用最便宜的：一樣的答案品質，一半的帳單

RESEARCH_DESC = "研究員：上網深入調查一個主題、交叉驗證、整理成含來源的報告，並可存進知識庫。"


def build_research_agent():
    """本機版（google_search 獨占）與 Phase 4 的遠端 A2A 版，二選一。"""
    url = os.getenv("RESEARCH_A2A_URL", "").strip()
    if url:
        return RemoteA2aAgent(
            name="research_agent",
            description=RESEARCH_DESC + "（遠端 A2A 服務）",
            agent_card=url.rstrip("/") + AGENT_CARD_WELL_KNOWN_PATH,
            timeout=120.0,  # 預設 600 秒；研究任務久但也不該讓使用者等 10 分鐘
        )
    return Agent(
        model=FLASH,
        name="research_agent",
        description=RESEARCH_DESC,
        instruction=(
            "你是研究員。步驟：google_search 搜尋 → 交叉驗證至少兩個來源 → 輸出繁體中文報告，"
            "格式為「## 結論 / ## 細節 / ## 來源（附網址）」。查不到就說查不到，不要編。"
        ),
        # google_search 必須獨占一個 agent：跟其他工具同掛，執行時才會爆（見常見錯誤表）
        tools=[google_search],
    )


def build_team() -> Agent:
    wiki_agent = Agent(
        model=FLASH,
        name="wiki_agent",
        description="Wiki 管理員：回答個人知識庫裡的問題，並負責把新資料存進知識庫。",
        instruction=(
            "你是知識庫管理員。任何知識問題都必須先呼叫 search_knowledge，"
            "回答只能用工具回傳的 snippet，並在每個重點後標出 source。"
            "工具回 status=empty 就直說「知識庫裡沒有這個」，禁止用你自己的記憶補答案。"
            "使用者要求儲存網頁時用 ingest_document。"
        ),
        tools=[search_knowledge, ingest_document],
    )
    data_agent = Agent(
        model=LITE,
        name="data_agent",
        description="資料助理：查詢訂閱、書單、專案清單等個人結構化資料（SQL）。",
        instruction="一律用資料庫工具查詢後回答，不得臆測數字。金額請加總後給總計。",
        # 模組頂層同步建立：改成 async 建立會在 Cloud Run 部署時爆掉（附錄 D ⑥）
        tools=[ToolboxToolset(server_url=os.getenv("TOOLBOX_URL", "http://127.0.0.1:5000"), toolset_name="personal-data")],
    )
    return Agent(
        model=FLASH,
        name="concierge",
        description="個人助理總管：理解需求、委派給專員、彙整回覆。",
        instruction=(
            "你是個人助理總管，只做三件事：理解需求、委派、彙整。"
            "知識問題→wiki_agent；需要新研究或上網→research_agent；訂閱／書單／專案等個人資料→data_agent。"
            "你不得自己回答任何知識性問題，也不得自己編數字 —— 沒有專員回報就說明還在查。"
            "最後用繁體中文彙整，保留專員給的來源與數字。"
        ),
        sub_agents=[build_research_agent(), wiki_agent, data_agent],
    )


root_agent = build_team()  # adk web / adk deploy 找的就是這個名字


def _self_check() -> None:
    names = [a.name for a in root_agent.sub_agents]
    assert root_agent.name == "concierge" and len(names) == 3, names
    assert names == ["research_agent", "wiki_agent", "data_agent"], names

    by = {a.name: a for a in root_agent.sub_agents}
    # google_search 只能獨占 research_agent，且它身上不能有第二個工具
    assert by["research_agent"].tools == [google_search], by["research_agent"].tools
    for other in ("wiki_agent", "data_agent"):
        assert google_search not in (by[other].tools or []), other
    # 模型分級：查表用 lite，其他用 flash（帳單一半的關鍵）
    assert by["data_agent"].model == LITE and by["wiki_agent"].model == FLASH
    # 委派靠 description，root 靠禁答規則；兩個都缺 agent 就會自己亂答
    assert all(a.description for a in root_agent.sub_agents)
    assert "不得自己回答" in root_agent.instruction
    assert "status=empty" in by["wiki_agent"].instruction  # 不腦補的規則要寫進 instruction

    # Phase 4：設了 RESEARCH_A2A_URL 就要換成遠端 agent，且名片路徑要對
    os.environ["RESEARCH_A2A_URL"] = "https://research-a2a-xxx.run.app/"
    try:
        remote = build_research_agent()
        assert isinstance(remote, RemoteA2aAgent), type(remote)
        assert build_team().sub_agents[0].name == "research_agent"
    finally:
        del os.environ["RESEARCH_A2A_URL"]
    assert AGENT_CARD_WELL_KNOWN_PATH == "/.well-known/agent-card.json", AGENT_CARD_WELL_KNOWN_PATH

    print("concierge self-check OK", file=sys.stderr)


if __name__ == "__main__":
    if "--self-check" in sys.argv:
        _self_check()
