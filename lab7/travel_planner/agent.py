"""Lab 7：多 Agent 旅遊助理（三專員 + 主管 + Sequential 行程 pipeline + user:budget state）。

跑法（都在 lab7/ 目錄下）：
  uv run adk web                                  # 開發 UI，選 travel_planner
  uv run adk run travel_planner                   # 終端機互動
  uv run adk api_server                           # REST（可帶初始 state 建 session）
  uv run travel_planner/agent.py --self-check     # 離線檢查：不連網、不花錢、不需要 key
  uv run travel_planner/agent.py --aha 2>/dev/null  # 四張對照表：委派的帳單、被改寫的 description、
                                                    # 工具的兩種包裝、state 前綴的壽命

天氣走 Lab 6 的 MCP server，跑之前先在 lab6/ 開起來：
  MCP_TRANSPORT=http uv run server.py
"""

import os
import re
import sys

from google.adk.agents import Agent, SequentialAgent
from google.adk.tools import AgentTool, ToolContext, google_search
from google.adk.tools.mcp_tool.mcp_session_manager import StreamableHTTPConnectionParams
from google.adk.tools.mcp_tool.mcp_toolset import McpToolset

MODEL = os.getenv("ADK_MODEL", "gemini-3.7-flash")  # 型號名以課程投影片為準；404 就用 client.models.list() 查
MODEL_LITE = os.getenv("ADK_MODEL_LITE", "gemini-3.5-flash-lite")
MCP_URL = os.getenv("MCP_URL", "http://localhost:8080/mcp")

# ── 假資料：booking_agent 的旅館庫（要真資料就換成 Booking/Agoda API，回傳格式不用改）──
HOTELS = {
    "東京": [
        {"name": "上野膠囊旅館", "price": 2800, "area": "上野"},
        {"name": "淺草和風旅館", "price": 4200, "area": "淺草"},
        {"name": "新宿商務飯店", "price": 6500, "area": "新宿"},
        {"name": "銀座柏悅", "price": 18000, "area": "銀座"},
    ],
    "大阪": [
        {"name": "難波青年旅舍", "price": 1900, "area": "難波"},
        {"name": "梅田車站飯店", "price": 5200, "area": "梅田"},
    ],
    "台北": [
        {"name": "西門町背包客棧", "price": 1200, "area": "萬華"},
        {"name": "信義商旅", "price": 4800, "area": "信義"},
    ],
}

# 天氣 MCP 只吃 lat/lon，這裡給主要城市的座標讓模型不用亂猜
CITY_LATLON = {"東京": (35.68, 139.77), "大阪": (34.69, 135.50), "台北": (25.03, 121.57)}


def set_budget(total_twd: int, tool_context: ToolContext) -> dict:
    """記下使用者這趟旅程的總預算（新台幣），之後同一個使用者的所有對話都讀得到。

    Args:
        total_twd: 總預算，新台幣整數，例如 30000。
    """
    if total_twd <= 0:
        return {"status": "error", "message": "預算要是正整數"}
    tool_context.state["user:budget"] = total_twd  # user: 前綴＝跨 session 保留
    return {"status": "success", "budget_twd": total_twd}


def search_hotels(city: str, nights: int = 1, max_price: int = 0,
                  tool_context: ToolContext = None) -> dict:
    """搜尋城市的旅館，並用預算過濾。

    Args:
        city: 城市名稱，例如 "東京"。
        nights: 住幾晚，用來把總預算換算成每晚上限。
        max_price: 每晚上限（新台幣）。給 0 表示改用 state 裡的 user:budget 自動換算。
    """
    nights = max(1, nights)
    cap = max_price
    if cap <= 0:
        budget = (tool_context.state if tool_context else {}).get("user:budget")
        if not budget:
            return {"status": "error",
                    "message": "還不知道預算。請先問使用者總預算並呼叫 set_budget，或直接給 max_price。"}
        cap = int(budget) // nights

    rooms = HOTELS.get(city)
    if not rooms:
        return {"status": "error", "message": f"沒有 {city} 的旅館資料，目前只有：{'、'.join(HOTELS)}"}

    hits = sorted([h for h in rooms if h["price"] <= cap], key=lambda h: h["price"])
    if not hits:
        cheapest = min(rooms, key=lambda h: h["price"])
        return {"status": "error", "cap_per_night": cap, "cheapest": cheapest,
                "message": (f"{city} 每晚 {cap} 元以下沒有房間。最便宜的是 {cheapest['name']} "
                            f"{cheapest['price']} 元/晚，{nights} 晚共 {cheapest['price'] * nights} 元，"
                            f"已超出預算，請提高預算或減少天數。")}
    return {"status": "success", "cap_per_night": cap, "count": len(hits), "hotels": hits,
            "total_twd": [{"name": h["name"], "total": h["price"] * nights} for h in hits]}


# ── 三個專員 ──────────────────────────────────────────────────────────
search_agent = Agent(
    model=MODEL, name="search_agent", mode="single_turn",
    description="即時網路搜尋專員：查景點、營業時間、票價、時事。不查天氣、不查旅館。",
    instruction="用 google_search 查證後回答，並附上來源網址。",
    tools=[google_search],  # 鐵律：google_search 必須是這個 agent 唯一的工具
)

weather_agent = Agent(
    model=MODEL_LITE, name="weather_agent", mode="single_turn",
    description="天氣預報專員：查指定城市未來幾天的氣溫與降雨機率。不查景點、不查旅館。",
    instruction=("用 get_weather 查天氣，參數是緯度與經度。已知座標："
                 + "；".join(f"{c}=({la},{lo})" for c, (la, lo) in CITY_LATLON.items())
                 + "。表格裡沒有的城市自己推估座標，並在回答裡說明是推估的。"),
    tools=[McpToolset(  # 頂層同步建立：async 建構在 adk web 下能跑，上雲會炸
        connection_params=StreamableHTTPConnectionParams(url=MCP_URL),
        tool_filter=["get_weather"],  # 最小權限：Lab 6 的 convert_currency 不放行
    )],
)

booking_agent = Agent(
    model=MODEL, name="booking_agent", mode="task",
    description="旅館專員：搜尋與比較旅館，處理預算限制。不查天氣、不查景點。",
    instruction=("用 search_hotels 查旅館。max_price 留 0，讓工具自己從 user:budget 換算每晚上限，"
                 "並把 nights 填成實際住幾晚。工具回 status=error 就照 message 說明為什麼訂不到，"
                 "不要自己編旅館名字。"),
    tools=[search_hotels],
)

# ── 行程 pipeline：writer → critic（Sequential 的資料匯流排就是 session state）──
writer = Agent(
    model=MODEL, name="itinerary_writer",
    description="把確定的資訊寫成 Markdown 三天行程表。",
    instruction=("把對話中已確認的天氣、旅館、景點資訊，寫成 Markdown 三天行程表。"
                 "每天分上午／下午／晚上，最後一列出住宿與預估花費。總預算：{user:budget?} 元。"
                 "資訊不足的欄位寫「待確認」，不要編造。"),
    output_key="itinerary_md",  # 寫進 state["itinerary_md"]
)

critic = Agent(
    model=MODEL, name="itinerary_critic",
    description="審查行程草稿的預算與時間衝突。",
    instruction=("嚴格審查這份行程草稿：\n{itinerary_md}\n\n"
                 "總預算 {user:budget?} 元。檢查三件事：(1) 預估花費是否超出預算 "
                 "(2) 同一天的行程是否地理上跑不完或時間重疊 (3) 有沒有「待確認」還沒補。"
                 "有問題就直接輸出修好的完整行程表；沒問題就原封不動輸出行程表並在最後加一行「✅ 已通過預算與時間檢查」。"),
    output_key="itinerary_final",
)

itinerary_pipeline = SequentialAgent(
    name="itinerary_pipeline",
    description="產生並審核 Markdown 三天行程表。收集完天氣、旅館、景點資訊之後呼叫。",
    sub_agents=[writer, critic],
)

root_agent = Agent(
    model=MODEL, name="travel_planner",
    description="旅遊總管：理解需求、派工給專員、彙整成行程表。",
    instruction=(
        "你是旅遊總管。你自己不查資料、不編資料，一律委派：\n"
        "- 景點／票價／營業時間 → search_agent\n"
        "- 天氣、下雨 → weather_agent\n"
        "- 旅館、住宿、預算 → booking_agent\n"
        "使用者一提到預算（例如「預算三萬」）就立刻呼叫 set_budget 記下來，再往下委派。\n"
        "三個專員的資訊都收齊之後，呼叫 itinerary_pipeline 工具產出並審核行程表，"
        "把它的輸出原文回給使用者。"
    ),
    sub_agents=[search_agent, weather_agent, booking_agent],
    tools=[set_budget, AgentTool(agent=itinerary_pipeline)],  # AgentTool＝借用能力，主管保留控制權
)


def _self_check():
    """離線驗證假資料工具、state 讀寫、委派接線與 instruction 佔位符。"""
    from types import SimpleNamespace

    def ctx(state=None):
        return SimpleNamespace(state=state if state is not None else {})

    # 1) 明確 max_price：只留 <= 上限的，且照價格排序
    r = search_hotels("東京", nights=3, max_price=5000, tool_context=ctx())
    assert r["status"] == "success" and r["count"] == 2, r
    assert [h["name"] for h in r["hotels"]] == ["上野膠囊旅館", "淺草和風旅館"], r
    assert r["total_twd"][0] == {"name": "上野膠囊旅館", "total": 8400}, r

    # 2) max_price=0 → 從 user:budget 換算每晚上限（3 萬 / 3 晚 = 10000）
    r = search_hotels("東京", nights=3, tool_context=ctx({"user:budget": 30000}))
    assert r["cap_per_night"] == 10000 and r["count"] == 3, r
    assert all(h["price"] <= 10000 for h in r["hotels"]), r

    # 3) state 沒有預算 → 不要瞎猜，回 error 叫模型先問
    r = search_hotels("東京", nights=3, tool_context=ctx())
    assert r["status"] == "error" and "set_budget" in r["message"], r

    # 4) 預算太低（evalset 的 edge case）→ error + 最便宜方案
    r = search_hotels("東京", nights=3, tool_context=ctx({"user:budget": 6000}))
    assert r["status"] == "error" and r["cheapest"]["price"] == 2800, r
    assert "8400" in r["message"], r

    # 5) 沒有的城市 → error 且列出有哪些
    assert search_hotels("冰島", tool_context=ctx({"user:budget": 99999}))["status"] == "error"

    # 6) set_budget 寫的是帶 user: 前綴的 key（不然換一條 session 就忘了）
    c = ctx()
    assert set_budget(30000, c)["status"] == "success"
    assert c.state == {"user:budget": 30000}, c.state
    assert set_budget(0, ctx())["status"] == "error"

    # 7) 委派接線：主管掛三個專員，順序與名字要對得上 adk web 的 Events
    assert [a.name for a in root_agent.sub_agents] == ["search_agent", "weather_agent", "booking_agent"]
    assert [a.name for a in itinerary_pipeline.sub_agents] == ["itinerary_writer", "itinerary_critic"]

    # 7b) ADK 2.7.1 把 single_turn/task 的 sub_agent 包成 AgentTool 接到 tools 後面，
    #     所以 Events 裡是名為專員的 function call，沒有 transfer_to_agent。這條在守那個事實。
    from google.adk.flows.llm_flows.agent_transfer import _get_transfer_targets
    assert _get_transfer_targets(root_agent) == [], "有 chat 模式的專員了？Events 會改走 transfer_to_agent"
    assert [getattr(t, "name", None) or t.__name__ for t in root_agent.tools] == [
        "set_budget", "itinerary_pipeline", "search_agent", "weather_agent", "booking_agent"]

    # 8) 鐵律：google_search 必須獨占一個 agent
    assert len(search_agent.tools) == 1 and search_agent.tools[0] is google_search

    # 9) 模式字串是底線版（'single-turn' 會被 pydantic 打回）
    assert {a.name: a.mode for a in root_agent.sub_agents} == {
        "search_agent": "single_turn", "weather_agent": "single_turn", "booking_agent": "task"}

    # 10) instruction 的 {placeholder} 一定要有人寫進 state，不然執行期會 KeyError
    written = {"itinerary_md", "itinerary_final", "user:budget"}
    for a in (writer, critic):
        for key in re.findall(r"\{([^{}]+)\}", a.instruction):
            assert key.rstrip("?") in written, f"{a.name} 讀了沒人寫的 state key: {key}"
    assert writer.output_key == "itinerary_md" and "{itinerary_md}" in critic.instruction

    # 11) 專員的 description 不能互相重疊，主管才派得對人
    assert all("不查" in a.description for a in root_agent.sub_agents)

    print("self-check ok（12 組 assert：假資料過濾、預算 state、委派接線與委派機制、instruction 佔位符）")


# ── --aha：四張對照表（離線、不需要 key；第 ③ 段要 Lab 6 的 server 才跑）────
import unicodedata  # noqa: E402  （只有 --aha 的表格對齊用得到）

_C = (("\033[1m", "\033[2m", "\033[36m", "\033[0m") if sys.stdout.isatty() else ("",) * 4)
BOLD, DIM, CYAN, RESET = _C
ADK_DELEGATION_SRC = [("tools/agent_tool.py", 470), ("flows/llm_flows/agent_transfer.py", 221)]


def _w(s):
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in str(s))


def _pad(s, n):
    return str(s) + " " * max(0, n - _w(s))


def _table(title, header, rows):
    """欄寬自動算（中文算 2 格），非 tty 自動退成純文字。"""
    cols = [max(_w(header[i]), *(_w(r[i]) for r in rows)) + 2 for i in range(len(header))]
    print(f"\n{CYAN}{BOLD}{title}{RESET}")
    print(BOLD + "".join(_pad(h, w) for h, w in zip(header, cols)).rstrip() + RESET)
    print(DIM + "─" * (sum(cols) - 2) + RESET)
    for r in rows:
        print("".join(_pad(c, w) for c, w in zip(r, cols)).rstrip())


def _aha1_delegation_bill():
    """委派沒有協調器：你手寫的設定處數 vs ADK 替你接的行數。"""
    mine = len(root_agent.sub_agents) + 1  # 每個專員一個 mode= ＋ 主管一個 sub_agents=
    adk = sum(n for _, n in ADK_DELEGATION_SRC)
    handwritten = [t for t in root_agent.tools if not hasattr(t, "agent") and callable(t)]
    _table("① 委派的帳單：你寫了幾行，ADK 接了幾行",
           ["項目", "你手寫", "ADK 生成", "倍數"],
           [["委派設定（agent.py）", f"{mine} 處", f"{adk} 行", f"{adk // mine}×"],
            ["主管手上的工具", f"{len(handwritten) + 1} 個",
             f"{len(root_agent.tools) - len(handwritten) - 1} 個", "—"],
            ["委派介面的參數", "0 個", f"{len(root_agent.sub_agents)} 個 request: string", "—"]])
    print(DIM + "  ADK 那 %d 行：%s" % (adk, "／".join(f"{f} {n}" for f, n in ADK_DELEGATION_SRC)) + RESET)


def _aha2_description_rewritten():
    """你寫的 description 不是模型看到的 description。"""
    rows, injected = [], ""
    for a in root_agent.sub_agents:
        seen = next(t for t in root_agent.tools
                    if getattr(t, "name", None) == a.name)._get_declaration().description
        delta = len(seen) - len(a.description)
        if delta:
            injected = seen[len(a.description):].strip()
        rows.append([a.name, a.mode, len(a.description), len(seen), f"+{delta}" if delta else "0"])
    _table("② 你寫的 description ≠ 模型看到的 description",
           ["專員", "mode", "你寫的字數", "模型看到的字數", "差"], rows)
    print(DIM + f"  ADK 塞的那句（agent_tool.py:447）：{injected}" + RESET)


def _aha3_two_wrappings():
    """同一個「工具」概念的兩種包裝：本地 python 函式 vs Lab 6 的 MCP server。"""
    import asyncio
    from google.adk.tools import FunctionTool

    local = FunctionTool(search_hotels)._get_declaration()

    async def remote():
        return {t.name: t for t in await weather_agent.tools[0].get_tools()}

    try:
        mcp = asyncio.run(remote())["get_weather"]._get_declaration()
    except Exception as e:  # server 沒開就跳過，不要讓整個 --aha 掛掉
        print(f"\n{CYAN}{BOLD}③ 同一個「工具」的兩種包裝{RESET}\n"
              f"  跳過：Lab 6 的 server 沒開（{type(e).__name__}）。到 lab6/ 跑 "
              f"MCP_TRANSPORT=http uv run server.py 再試。")
        return
    param = lambda d: "/".join(d.parameters_json_schema["properties"])
    _table("③ 同一個「工具」的兩種包裝",
           ["", "search_hotels", "get_weather"],
           [["寫在哪", "lab7/travel_planner/agent.py", "lab6/server.py"],
            ["跑在哪", "同一個 python 行程", "另一個 process（HTTP）"],
            ["ADK 端型別", "FunctionTool", "MCPTool"],
            ["模型看到的參數", param(local), param(mcp)],
            ["模型看到的型別", type(local).__name__, type(mcp).__name__]])
    print(DIM + "  最後一列一樣＝模型分不出本地函式與遠端 MCP server。" + RESET)


def _aha4_state_lifespan():
    """state 前綴的壽命：用真的 InMemorySessionService 量，不需要 key。"""
    import asyncio

    from google.adk.events import Event, EventActions
    from google.adk.sessions import InMemorySessionService

    keys = ["temp:budget", "budget", "user:budget", "app:promo"]

    async def probe():
        svc = InMemorySessionService()
        s1 = await svc.create_session(app_name="travel_planner", user_id="u1", session_id="s1")
        await svc.append_event(session=s1, event=Event(
            author="tool", actions=EventActions(state_delta=dict.fromkeys(keys, 30000))))
        after = [dict(x.state) for x in (
            await svc.get_session(app_name="travel_planner", user_id="u1", session_id="s1"),
            await svc.create_session(app_name="travel_planner", user_id="u1", session_id="s2"),
            await svc.create_session(app_name="travel_planner", user_id="u2", session_id="s3"))]
        return after, dict(s1.state)   # s1 是「你手上那個物件」，跟重讀出來的不一樣

    (same, new_session, new_user), in_hand = asyncio.run(probe())
    _table("④ state 前綴決定資料活多久（真的 InMemorySessionService 量出來的）",
           ["key", "重新取同一條 session", "換 session（同使用者）", "換使用者"],
           [[k] + ["✓" if k in st else "✗" for st in (same, new_session, new_user)] for k in keys])
    print(DIM + f"  但你手上那個 session 物件還看得到 temp:budget："
          f"{'temp:budget' in in_hand} —— append_event 只把它從「要存的 delta」剝掉"
          "（sessions/base_session_service.py:195 _trim_temp_delta_state），物件本身沒清。\n"
          "  set_budget 寫的是 user:budget —— 上面第三列就是它為什麼要有前綴。" + RESET)


def _aha():
    for f in (_aha1_delegation_bill, _aha2_description_rewritten,
              _aha3_two_wrappings, _aha4_state_lifespan):
        f()
    print()


if __name__ == "__main__":
    if "--self-check" in sys.argv:
        _self_check()
    elif "--aha" in sys.argv:
        _aha()
    else:
        print(__doc__)
