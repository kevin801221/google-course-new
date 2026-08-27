"""Lab 10 主 agent：concierge。三個工具來源全部指向雲端。

  MCP server（私有 Cloud Run） → McpToolset + streamable-http + ID token
  Toolbox（私有 Cloud Run）     → ToolboxToolset + Authorization header
  hotel agent（A2A Cloud Run）  → RemoteA2aAgent 讀公開名片

跑法（都在 lab10/ 執行）：
  本機接雲端服務：  cp concierge/.env.sample concierge/.env 填三個網址後 uv run adk web
  部署：            ./deploy.sh agent
  離線驗認證邏輯：  uv run --no-project concierge/auth.py --self-check

環境變數（Cloud Run 由 deploy.sh 用 --set-env-vars 注入；
          本機與 Agent Engine 都是讀 concierge/.env）：
  MCP_URL / TOOLBOX_URL / A2A_URL —— 三個服務的根網址
"""

import os

from google.adk.agents import Agent
from google.adk.agents.remote_a2a_agent import (
    AGENT_CARD_WELL_KNOWN_PATH,
    RemoteA2aAgent,
)
from google.adk.tools.mcp_tool.mcp_session_manager import (
    StreamableHTTPConnectionParams,
)
from google.adk.tools.mcp_tool.mcp_toolset import McpToolset
from google.adk.tools.toolbox_toolset import ToolboxToolset

from . import auth

MCP_URL = os.environ["MCP_URL"]
TOOLBOX_URL = os.environ["TOOLBOX_URL"]
A2A_URL = os.environ["A2A_URL"]

# ① MCP：header_provider 是「每次呼叫前才算 header」的鉤子。
#    寫成 headers={...} 也能通，但那是模組載入時算一次的靜態值 ——
#    ID token 一小時就過期，之後每個工具呼叫都 401，而且要等一小時才會發現。
mcp_tools = McpToolset(
    connection_params=StreamableHTTPConnectionParams(
        url=auth.endpoint(MCP_URL),
        timeout=30.0,  # 預設 5 秒；Cloud Run 冷啟動會超過
    ),
    header_provider=lambda ctx: auth.auth_headers(auth.endpoint(MCP_URL)),
)

# ② Toolbox：additional_headers 是靜態 Mapping，沒有 provider 版本。
# ponytail: token 在模組載入時算一次，一小時後會過期。
#   課程 demo 的實例活不到一小時（scale-to-zero 會重啟＝重新算），夠用。
#   要撐長連線就改成自訂 ToolboxToolset 子類，在 get_tools 時重算 header。
db_tools = ToolboxToolset(
    server_url=TOOLBOX_URL,
    toolset_name="hotel-tools",  # Lab 8 tools.yaml 裡定義的 toolset 名
    additional_headers=auth.auth_headers(TOOLBOX_URL),
)

# ③ A2A：名片公開可讀，所以這裡不用帶 token。
#    名片抓不到的話 RemoteA2aAgent 會在「第一次被呼叫時」才炸，不是啟動時 ——
#    所以部署完一定要用 verify.sh 打一次名片端點，不能只看 revision 是綠的。
hotel_agent = RemoteA2aAgent(
    name="hotel_agent",
    description="訂房專員（雲端 A2A 服務）：依城市與預算搜尋旅館並推薦。",
    agent_card=A2A_URL.rstrip("/") + AGENT_CARD_WELL_KNOWN_PATH,
)

root_agent = Agent(
    model="gemini-3.7-flash",  # 型號名以課程投影片為準，若 404 用 client.models.list() 確認
    name="concierge",
    description="旅遊總管：換算幣別、查旅館資料庫、必要時委派訂房專員。",
    instruction=(
        "你是旅遊總管，全程用繁體中文。\n"
        "- 使用者提到金額換算 → 用 MCP 的 convert_currency\n"
        "- 要查旅館的價格或統計 → 用資料庫工具（search-hotels-by-city / get-price-stats）\n"
        "- 要「推薦哪一間、幫我決定」→ 委派給 hotel_agent\n"
        "最後給一個結論，並說明你用了哪些工具與服務。"
    ),
    tools=[mcp_tools, db_tools],
    sub_agents=[hotel_agent],
)
