"""Lab 8 旅館查詢 agent：Toolbox 工具層（＋加分題 A 的 pgvector 語意搜尋）。

跑法（在 lab8/ 目錄）：
  ./toolbox --config tools.yaml &                       # 先起工具層
  uv run adk web                                        # sessions 在記憶體，重啟就忘
  uv run adk web --session_service_uri "$ADK_SESSION_URI"   # sessions 落地 Supabase
"""
import os

from google.adk.agents import Agent
from google.adk.tools.toolbox_toolset import ToolboxToolset

from .rag_tool import search_hotels_semantic

INSTRUCTION = """你是旅館顧問，只根據資料庫回答。

規則：
1. 任何價格、評分、間數、統計數字，一律先呼叫資料庫工具取得。資料庫查不到就說查不到，
   絕對不准憑記憶、常識或推測報價 —— 編一個價格比說「沒有資料」嚴重得多。
2. 城市要用英文餵工具（Tokyo / Osaka / Kyoto / Sapporo / Taipei）。
3. 使用者說過的預算與城市要記住，後續追問直接沿用，不要重複問。
4. 回答時列出旅館名稱、每晚台幣價格、評分，並說明數字來自資料庫查詢。
5. 問「哪個城市比較便宜」這種比較題，用 get-price-stats，不要自己一個一個城市查。"""

# 模組頂層、同步建立 —— 寫成 async 建立（或包在 async def 裡）部署到 Cloud Run 會炸（M12 易錯坑⑥）
toolset = ToolboxToolset(
    server_url=os.environ.get("TOOLBOX_URL", "http://127.0.0.1:5000"),
    toolset_name="hotel-tools",       # 只載這組，不要把整個 Toolbox 的工具全塞給模型
)

# 加分題 A：export LAB8_RAG=1 才掛語意搜尋，主線步驟不受影響
tools = [toolset] + ([search_hotels_semantic] if os.environ.get("LAB8_RAG") == "1" else [])

root_agent = Agent(
    model="gemini-3.7-flash",         # 型號名以課程投影片為準；若 404 用 client.models.list() 確認
    name="hotel_agent",
    instruction=INSTRUCTION,
    tools=tools,
)
