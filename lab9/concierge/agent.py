"""服務 A：旅遊管家 concierge，把訂房委派給 :8001 的遠端 agent。

跑法：
  uv run adk web                              # 在 lab9/ 執行，左上角選 concierge
  uv run concierge/agent.py --self-check      # 離線驗名片 URL 與 origin 規則，不連網

環境變數：
  HOTEL_SERVICE_URL=http://localhost:8001     服務 B 的 base URL
"""

import os
import sys

from google.adk.agents import Agent
from google.adk.agents.remote_a2a_agent import AGENT_CARD_WELL_KNOWN_PATH, RemoteA2aAgent


def card_url(base: str) -> str:
    """base URL 接上 /.well-known/agent-card.json，順手吃掉多餘的斜線。"""
    return base.rstrip("/") + AGENT_CARD_WELL_KNOWN_PATH


HOTEL_SERVICE_URL = os.getenv("HOTEL_SERVICE_URL", "http://localhost:8001")

hotel_agent = RemoteA2aAgent(
    name="hotel_agent",
    # description 是 root_agent 決定要不要委派的唯一依據（它看不到遠端的 instruction）
    description="訂房專員（遠端服務，跑在 :8001）。查旅館、比價、選飯店都交給它。",
    agent_card=card_url(HOTEL_SERVICE_URL),
    timeout=30.0,  # 預設 600 秒：對方掛掉你會傻等 10 分鐘
)

root_agent = Agent(
    model="gemini-3.7-flash",  # 型號名以課程投影片為準，若 404 用 client.models.list() 確認
    name="concierge",
    description="旅遊管家",
    instruction=(
        "你是旅遊管家。使用者問到旅館、住宿、房價，一律轉交 hotel_agent 處理，不要自己編價格。"
        "其他行程、交通、天氣問題自己用繁體中文回答。"
    ),
    sub_agents=[hotel_agent],
)


def _self_check() -> None:
    from urllib.parse import urlparse

    assert card_url("http://localhost:8001") == "http://localhost:8001/.well-known/agent-card.json"
    assert card_url("http://localhost:8001/") == card_url("http://localhost:8001")  # 尾斜線不能變成 //
    assert AGENT_CARD_WELL_KNOWN_PATH.startswith("/"), AGENT_CARD_WELL_KNOWN_PATH

    # ADK 會比對「抓名片的 origin」與「名片上宣告的 RPC origin」，不同就拒絕連線。
    # localhost 與 127.0.0.1 是不同的 origin —— 這是最常踩的一條。
    origin = lambda u: (lambda p: (p.scheme, p.hostname, p.port))(urlparse(u))
    assert origin("http://localhost:8001/") != origin("http://127.0.0.1:8001/")
    assert origin(card_url("http://localhost:8001")) == origin("http://localhost:8001/")

    assert hotel_agent.name == "hotel_agent"
    assert root_agent.sub_agents[0] is hotel_agent
    print("self-check ok")


if __name__ == "__main__":
    _self_check() if "--self-check" in sys.argv else print(__doc__)
