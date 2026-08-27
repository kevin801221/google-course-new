# Lab 7 走一遍：多 Agent 旅遊助理

> 90–120 分鐘 ｜ 綜合 7.1-7.9：multi-agent ＋ workflow ＋ state ＋ MCP ＋ eval 一次到位

做完你會有一個 `travel_planner/` 目錄——一個目錄就是一個可部署的 agent app。裡面是三個專員、一個主管、一段 writer→critic pipeline，跟一組能當回歸測試跑的 evalset：

```
$ uv run adk web
INFO:     Uvicorn running on http://127.0.0.1:8000

# 瀏覽器裡選 travel_planner，貼：預算 3 萬、11 月去東京三天，怕下雨
#
# Events 分頁（這才是重點）：
#   ▸ set_budget            {"total_twd": 30000}
#   ▸ weather_agent         {"request": "查東京 11 月的天氣"}   ← 委派＝一次 function call
#   ▸   get_weather         {"lat": 35.68, "lon": 139.77}      ← 走 Lab 6 的 MCP server
#   ▸ booking_agent         {"request": "東京住三晚，找預算內的旅館"}
#   ▸   search_hotels       {"city": "東京", "nights": 3, "max_price": 0}
#   ▸ itinerary_pipeline    → itinerary_writer → itinerary_critic
#
# State 分頁：user:budget = 30000 ／ itinerary_md = "# 東京三天…" ／ itinerary_final = …
```

```
$ uv run adk eval travel_planner tests/travel.evalset.json \
      --config_file_path=tests/criteria.json
Eval Run Summary
  Tests passed: 3
  Tests failed: 0
```

> 上面兩段是**示意**：Events 的欄位名與 eval 的輸出格式是實測的，但實際對話內容我沒有 API key 跑不出來（每一步的 ⚠️ 會標清楚哪些驗過、哪些沒有）。

每一步都有「動手 → 為什麼 → 驗收」。驗收沒過不要往下走——multi-agent 的 bug 疊起來會非常難拆。

---

## 步驟 0：前置（5 分）

**動手**

```bash
# 1) API key：Lab 1 那把還在就直接用
open https://aistudio.google.com/apikey     # 免費、不用信用卡

# 2) Lab 6 的天氣 MCP server：開一個新的終端機視窗，讓它一直開著
cd ~/Antigravity-teach/lab6
MCP_TRANSPORT=http uv run server.py
# → INFO: Uvicorn running on http://0.0.0.0:8080
```

**為什麼**：這個 Lab 的 `weather_agent` 不自己寫天氣工具，直接吃 Lab 6 你自己寫的 MCP server（步驟 2 的重點）。M6 和 M7 不是兩堂沒關係的課，`McpToolset` 就是那條縫線。

server 要跑在**另一個視窗**，因為它是另一個 process——這也是為什麼它可以用 mcp 2.x 而 ADK 這邊用 mcp 1.x，兩邊靠協定講話，不靠套件版本。

**驗收**

```bash
curl -s --max-time 5 -o /dev/null -w '%{http_code}\n' -X POST http://localhost:8080/mcp \
  -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2026-07-28","capabilities":{},"clientInfo":{"name":"c","version":"1"}}}'
# → 200   server 活著
# → 000   沒開起來（或 port 不對），回去看那個視窗的錯誤
```

別用 `curl http://localhost:8080/mcp` 直接 GET —— Streamable HTTP 的 GET 是 SSE 通道，它會把連線**掛住**不回應，看起來像壞掉其實是正常的。要一行版就 `nc -z localhost 8080`。

`[Errno 48] address already in use`？8080 被別的東西占了。改 port，並記得整個 Lab 的 `MCP_URL` 都要跟著改：

```bash
PORT=8099 MCP_TRANSPORT=http uv run server.py
```

---

## 步驟 1：建骨架（10 分）

**動手**

```bash
cd ~/Antigravity-teach
uv init --bare --name lab7 --python 3.13 lab7 && cd lab7
uv add "google-adk[eval,mcp]"
uv run adk --version                      # → 2.7.1（2.7.x 都行）

uv run adk create travel_planner --model gemini-3.7-flash
```

不帶 `--model` / `--api_key` 的話 `adk create` 會互動式問你模型與路線（選 Developer API＝AI Studio key）；上面這行給了 `--model` 就只問 key。（查原始碼 `cli/cli_create.py`：`--model` 缺就 `_prompt_for_model()`、key 與 project 都缺就 `prompt_to_choose_backend()`；`--type` 有預設 `CODE` 所以不會再問第三題。）跑完得到：

```
travel_planner/
  __init__.py     ← from . import agent
  agent.py        ← 必須定義 root_agent
  .env            ← GOOGLE_GENAI_USE_ENTERPRISE=0 / GOOGLE_API_KEY=...
  .gitignore      ← 已經幫你排除 .env 與 .adk/
```

然後把 key 填好（或直接抄本目錄的 `.env.example`）：

```bash
cp travel_planner/.env.example travel_planner/.env
$EDITOR travel_planner/.env               # 填 GOOGLE_API_KEY，MCP_URL 照你步驟 0 的 port
```

**為什麼**

- **為什麼 `uv add "google-adk[eval,mcp]"` 而不是 `uv add google-adk`**：`eval` 和 `mcp` 都是 extra。不加 `eval`，步驟 7 會直接被打回：
  ```
  Error: Eval module is not installed, please install via `pip install "google-adk[eval]"`.
  ```
  （它叫你跑 pip，**別聽**——這門課一律 `uv add`。）不加 `mcp`，步驟 2 會 `ModuleNotFoundError: No module named 'mcp'`。而且 `mcp` 這個 extra 會幫你解出 ADK 要的 `mcp>=1.24,<2`；你自己手動 `uv add mcp` 很可能裝到 2.x，然後噴 `ModuleNotFoundError: No module named 'mcp.shared.session'`。
- **為什麼 `--bare`**：我們不打包成套件發佈，只要一個 `pyproject.toml` 管依賴。
- **為什麼 `.env` 要在 `travel_planner/` 裡而不是專案根目錄**：ADK 啟動時載入的是 **agent 目錄**的 `.env`。放錯地方的症狀是 `ValueError: No API key was provided.`，而你的 `.env` 明明就在——只是在上一層。這也是「一個目錄＝一個獨立 app」的實際意義：同一個專案裡兩個 agent 可以用不同的 key 和不同的路線。
- **為什麼 `uv.lock` 要進版控**：CI 用 `uv sync --frozen` 才裝得出一模一樣的環境。`adk` 這種版本迭代很快的套件，沒 lock 檔下週的 CI 就跟你今天跑的不是同一件事。

**驗收**

```bash
uv run python -c "import travel_planner; print(travel_planner.agent.root_agent.name)"
# → root_agent          （adk create 的預設骨架，等下會被我們改掉）
```

印不出來、噴 `ModuleNotFoundError: No module named 'travel_planner'`？你不在 `lab7/` 目錄裡。
噴 `ModuleNotFoundError: No module named 'google'`？你用了 `python` 而不是 `uv run python`。

---

## 步驟 2：三個專員（25 分）

這步最長，分三小段做，每段做完都能單獨驗。

### 2a. `search_agent` —— 順便撞一下鐵律

**動手**：打開 `travel_planner/agent.py`，先寫這一段：

```python
from google.adk.agents import Agent
from google.adk.tools import google_search

search_agent = Agent(
    model="gemini-3.7-flash", name="search_agent", mode="single_turn",
    description="即時網路搜尋專員：查景點、營業時間、票價、時事。不查天氣、不查旅館。",
    instruction="用 google_search 查證後回答，並附上來源網址。",
    tools=[google_search],
)
```

**為什麼**

- **為什麼 `google_search` 只能一個人掛**：ADK 的鐵律——`google_search` 必須是該 agent 唯一的工具。這不是風格建議，是硬限制（走 Gemini 原生能力）。**想混用只能拆 sub-agent**——換句話說，multi-agent 這個架構有一部分是被這條限制逼出來的，不是為了漂亮。
- **為什麼 `description` 要寫「不查天氣、不查旅館」**：`description` 是給**其他 agent**看的（`instruction` 才是給自己看的）。主管完全靠讀三份 `description` 決定派誰。兩個專員的職責描述一重疊，主管就開始亂派，而且 Events 裡看起來完全合法——沒有錯誤訊息，只有錯的答案。把它當**職缺描述**寫，還要把「這不是我的活」明寫進去。
- **為什麼 `mode="single_turn"`**：搜尋是一問一答、不需要跟使用者互動的純查詢型子任務，`single_turn` 讓它答完直接回主管。留預設的 `chat` 模式，它會把對話留在自己手上——症狀就是「子 agent 答完不回來」，接下來你問旅館，回你的還是 `search_agent`。
  > 投影片 P297 那張表寫 `single-turn`（連字號），**實際的字串是底線** `single_turn`。寫錯會被 pydantic 當場打回：
  > `ValidationError … mode Input should be 'chat', 'task' or 'single_turn' [type=literal_error, input_value='single-turn']`

**驗收**

```bash
uv run python -c "
from travel_planner.agent import search_agent
assert len(search_agent.tools) == 1, '鐵律：google_search 必須獨占'
print('search_agent ok', search_agent.mode)"
# → search_agent ok single_turn
```

想親眼看鐵律被執行？把 `tools=[google_search, set_budget]` 硬塞進去跑一次對話——這是本 Lab 的最終檢查清單裡那條「你真的試過嗎」。

### 2b. `weather_agent` —— 接 Lab 6 的 MCP server（先讓它壞一次）

**動手**：先**故意不開** Lab 6 的 server（把步驟 0 那個視窗 Ctrl-C），然後寫：

```python
import os
from google.adk.tools.mcp_tool.mcp_session_manager import StreamableHTTPConnectionParams
from google.adk.tools.mcp_tool.mcp_toolset import McpToolset

MCP_URL = os.getenv("MCP_URL", "http://localhost:8080/mcp")
CITY_LATLON = {"東京": (35.68, 139.77), "大阪": (34.69, 135.50), "台北": (25.03, 121.57)}

weather_agent = Agent(
    model="gemini-3.5-flash-lite", name="weather_agent", mode="single_turn",
    description="天氣預報專員：查指定城市未來幾天的氣溫與降雨機率。不查景點、不查旅館。",
    instruction=("用 get_weather 查天氣，參數是緯度與經度。已知座標："
                 + "；".join(f"{c}=({la},{lo})" for c, (la, lo) in CITY_LATLON.items())
                 + "。表格裡沒有的城市自己推估座標，並在回答裡說明是推估的。"),
    tools=[McpToolset(
        connection_params=StreamableHTTPConnectionParams(url=MCP_URL),
        tool_filter=["get_weather"],
    )],
)
```

跑這行看它壞：

```bash
uv run python -c "
import asyncio; from travel_planner.agent import weather_agent
print('MCP tools =', [t.name for t in asyncio.run(weather_agent.tools[0].get_tools())])"
```

```
ConnectionError: Failed to create MCP session: Failed to create MCP session: Session terminated
```

**現在把 Lab 6 的 server 開回來**，同一行再跑一次：

```
MCP tools = ['get_weather']
```

**為什麼**

- **為什麼要先看它壞**：`McpToolset` 的建構是**同步且 lazy** 的——server 沒開，`import` 完全不會報錯，一切看起來正常，直到模型真的想查天氣。這個 `ConnectionError` 你會在課堂上看到很多次，先認得它，才不會在 `adk web` 裡以為是模型笨。
- **為什麼 `McpToolset(...)` 要寫在模組頂層、用同步寫法**：部署鐵則。用 `async` 方式建構（2025 教學常見的 `await MCPToolset.from_server()`）只在 `adk web` 下能跑，上雲會炸；而且那個 `from_server()` API **已經被移除**了。
- **為什麼要 `tool_filter`**：Lab 6 的 server 還有 `convert_currency`。不設白名單，天氣專員手上會多一個換匯工具——工具越多選錯率越高，而且違反最小權限（附錄 D ⑩：agent 的權限就是 prompt injection 的災害半徑）。
- **為什麼要把經緯度寫進 instruction**：Lab 6 的 `get_weather(lat, lon)` 吃座標不吃城市名。不給表，模型會自己編一組經緯度——然後你拿到某個太平洋上的降雨機率，而且**不會有任何錯誤訊息**。
- **為什麼用 Flash-Lite**：查天氣是雜活，不需要推理。模型分級是 multi-agent 最直接的省錢手段（主管 Flash、難子任務 Pro、雜活 Flash-Lite）。

**驗收**：上面那行 `MCP tools = ['get_weather']`。注意這條驗收**不需要 API key**（只是 MCP 的 tools/list，沒碰模型）——所以這是整個步驟 2 唯一能離線驗到底的一段，卡住時先確定它是綠的。

> ⚠️ 未實測：模型真的呼叫 `get_weather` 並解讀回傳值那一段需要 API key。`MCP tools = ['get_weather']` 是實測通過的（ADK 端 mcp 1.29.1 客戶端 ↔ Lab 6 端 mcp 2.1.1 server，跨大版本可以互通）。

> 💡 **啊哈：模型分不出「你寫的 python 函式」和「另一台機器上的 MCP server」——送到它面前的都是同一個 `FunctionDeclaration`。**
> `search_hotels` 在 `travel_planner/agent.py` 裡；`get_weather` 在 `lab6/server.py` 裡，另一個 process、跨 mcp 大版本、走 HTTP。ADK 端型別不同（`FunctionTool` / `MCPTool`），轉成模型看得到的東西之後完全同構。
> 這條線還沒走完：`get_weather` 在 Lab 6 是 MCP tool、這裡是 `MCPTool`、Lab 10 會是 Cloud Run 上有 IAM policy 的網址；`search_hotels` 這裡是本地函式，Lab 9 會變成 agent card 上的 `AgentSkill(id="search_hotels")`。**換包裝，不換函式。**
> **動手看**：`uv run travel_planner/agent.py --aha 2>/dev/null` 的第 ③ 段 → 最後一列兩邊都是 `FunctionDeclaration`。

### 2c. `booking_agent` —— 假資料工具

**動手**

```python
HOTELS = {
    "東京": [
        {"name": "上野膠囊旅館", "price": 2800, "area": "上野"},
        {"name": "淺草和風旅館", "price": 4200, "area": "淺草"},
        {"name": "新宿商務飯店", "price": 6500, "area": "新宿"},
        {"name": "銀座柏悅", "price": 18000, "area": "銀座"},
    ],
    # 大阪、台北見 travel_planner/agent.py
}

def search_hotels(city: str, nights: int = 1, max_price: int = 5000) -> dict:
    """搜尋城市的旅館，並用預算過濾。

    Args:
        city: 城市名稱，例如 "東京"。
        nights: 住幾晚。
        max_price: 每晚上限（新台幣）。
    """
    rooms = HOTELS.get(city)
    if not rooms:
        return {"status": "error", "message": f"沒有 {city} 的旅館資料，目前只有：{'、'.join(HOTELS)}"}
    hits = sorted([h for h in rooms if h["price"] <= max_price], key=lambda h: h["price"])
    return {"status": "success", "count": len(hits), "hotels": hits}

booking_agent = Agent(
    model="gemini-3.7-flash", name="booking_agent", mode="task",
    description="旅館專員：搜尋與比較旅館，處理預算限制。不查天氣、不查景點。",
    instruction="用 search_hotels 查旅館，超出預算要說明。",
    tools=[search_hotels],
)
```

**這個版本是刻意留洞的**（`max_price` 有預設值 5000、沒有 state），步驟 5 會修。

**為什麼**

- **為什麼要 `-> dict` 加 `status`**：慣例是 `{"status": "success", ...}` / `{"status": "error", "message": ...}`。模型讀 `status` 決定下一步。回傳一個裸 list，模型分不出「查到 0 間」和「城市不存在」，就會開始編。
- **為什麼型別註記和 docstring 的 `Args` 每個參數都要寫**：ADK 用函式簽章＋docstring 自動生成模型看得懂的 schema。沒有型別註記就沒有 schema；`Args` 少寫一個參數，模型就會亂填那個參數——「模型用錯工具」幾乎都是文件爛，不是模型笨。
- **為什麼 `mode="task"`**：訂房是「有始有終」的任務，可能需要反問澄清（住幾晚？），完成後自動返回主管。這是三種模式裡最適合訂位／填單的一種。
- **為什麼查不到要回 error 而不是空 list**：`{"count": 0, "hotels": []}` 對模型來說跟「這個城市沒有旅館」長得一樣。給它一句人話的 `message`，它才講得出「差 2400 元」這種有用的話。

**驗收**

```bash
uv run python -c "
from travel_planner.agent import search_hotels
r = search_hotels('東京', nights=3, max_price=5000)
print(r['count'], [h['name'] for h in r['hotels']])
print(search_hotels('冰島', max_price=9999)['message'])"
# → 2 ['上野膠囊旅館', '淺草和風旅館']
# → 沒有 冰島 的旅館資料，目前只有：東京、大阪、台北
```

---

## 步驟 3：主管 agent（12 分）

**動手**：先寫一個**偷懶版**的主管，跑一次，看它出包：

```python
root_agent = Agent(
    model="gemini-3.7-flash", name="travel_planner",
    instruction="你是旅遊總管。幫使用者規劃行程。",       # ← 太模糊，故意的
    sub_agents=[search_agent, weather_agent, booking_agent],
)
```

```bash
uv run adk web        # → http://localhost:8000，選 travel_planner
# 問：東京 11 月會下雨嗎？
```

看 **Events** 分頁。很可能一個 function call 都沒有——主管憑訓練資料自己答了「東京 11 月大概 15 度、偶有陣雨」。聽起來很對，但它**根本沒查**。

現在改成明確版：

```python
root_agent = Agent(
    model="gemini-3.7-flash", name="travel_planner",
    description="旅遊總管：理解需求、派工給專員、彙整成行程表。",
    instruction=(
        "你是旅遊總管。你自己不查資料、不編資料，一律委派：\n"
        "- 景點／票價／營業時間 → search_agent\n"
        "- 天氣、下雨 → weather_agent\n"
        "- 旅館、住宿、預算 → booking_agent\n"
        "使用者一提到預算（例如「預算三萬」）就立刻呼叫 set_budget 記下來，再往下委派。\n"
        "三個專員的資訊都收齊之後，彙整成一份三天行程表。"
    ),
    sub_agents=[search_agent, weather_agent, booking_agent],
)
```

同一個問題再問一次，Events 裡要出現：

```
▸ weather_agent   {"request": "查東京 11 月的天氣"}
▸   get_weather   {"lat": 35.68, "lon": 139.77}
```

### 委派在 Events 裡到底長什麼樣？（這裡跟很多教學不一樣）

投影片 P298 說「看 Events 的 `transfer` 事件」。**在 ADK 2.7.1 上，只有 `mode='chat'`（預設）的 sub-agent 才會這樣。**我們的三個專員都設了 `single_turn` / `task`，實際機制是：

```python
# google/adk/agents/llm_agent.py::model_post_init — 原始碼就寫在這
if mode == 'single_turn':  self.tools.append(_SingleTurnAgentTool(sub_agent))
elif mode == 'task':       self.tools.append(_TaskAgentTool(sub_agent))
```

也就是 **ADK 把 `single_turn` / `task` 的 sub-agent 自動包成 AgentTool 接到 `tools` 後面**，模型看到的是一個名叫 `weather_agent` 的普通工具（參數只有一個 `request: str`）。所以 Events 裡是 `weather_agent {"request": "…"}`，**沒有** `transfer_to_agent` 這一行。

自己驗一次（不需要 key）：

```bash
uv run python -c "
from google.adk.flows.llm_flows.agent_transfer import _get_transfer_targets
from travel_planner.agent import root_agent
print('transfer 目標 =', [a.name for a in _get_transfer_targets(root_agent)])
print('模型看到的工具 =', [getattr(t, 'name', None) or t.__name__ for t in root_agent.tools])" 2>/dev/null
# → transfer 目標 = []
# → 模型看到的工具 = ['set_budget', 'itinerary_pipeline', 'search_agent', 'weather_agent', 'booking_agent']
```

`transfer 目標 = []` 就是「這個主管根本沒有 `transfer_to_agent` 工具可用」。想看 `transfer_to_agent {"agent_name": …}` 長什麼樣，把某個專員的 `mode` 拿掉（回到預設 `chat`）再跑上面那行，它就會出現在 transfer 目標裡、同時從 `tools` 消失——兩種委派機制是**互斥**的。

**為什麼**

- **不寫「你自己不查資料」會怎樣**：主管是一個有訓練資料的 LLM，它「會」回答天氣問題。委派對它來說是額外動作，模糊的 instruction 下它會選最省事的路——自己講。這是委派除錯的第一症狀（「主管自己亂答不委派」），解法就是**明說「你不直接回答 X，一律交給 Y」**。而且注意：這種失敗**沒有錯誤訊息**，只有 Events 裡少了那一行委派的 function call。
- **為什麼把專員名字直接寫進 instruction**：`description` 負責讓主管「認識」專員，instruction 裡的明確對應負責在職責邊界模糊時壓過模型的猶豫。兩層都要有。
- **為什麼主管不掛 `google_search`**：它掛了就違反鐵律（而且會擠掉 `set_budget`）。主管的工作是派工與彙整，`root_agent` 自己盡量不做事——這是組織隱喻，也是省 token 的設計。
- **專員幾個最好**：3–7 個最甜；再多要分層（主管的主管）。這個 Lab 剛好 3 個。

**驗收**

```bash
uv run python -c "
from travel_planner.agent import root_agent
print([a.name for a in root_agent.sub_agents])
assert '不查資料' in root_agent.instruction"
# → ['search_agent', 'weather_agent', 'booking_agent']
```

在 `adk web` 裡三個問題各問一次，Events 裡要看到三個不同的委派 function call：

| 問題 | 期望 Events 裡出現的 function call |
|---|---|
| 東京 11 月會下雨嗎？ | `weather_agent {"request": …}` |
| 淺草寺幾點開門？ | `search_agent {"request": …}` |
| 東京有什麼旅館？ | `booking_agent {"request": …}` |

派錯人？回去改那個專員的 `description`——兩份描述不能重疊模糊。`description` 就是這個工具的 description，模型只憑它選人。

> ⚠️ 未實測：`adk web` 的對話與 Events 需要 API key，我沒有 key。**委派機制本身是實測的**：`_get_transfer_targets(root_agent)` 回 `[]`、三個專員以 `_SingleTurnAgentTool` / `_TaskAgentTool` 出現在 `root_agent.tools`、declaration 的參數只有 `request`（ADK 2.7.1，原始碼 `google/adk/agents/llm_agent.py` 與 `google/adk/flows/llm_flows/agent_transfer.py`）。

> 💡 **啊哈：multi-agent 沒有協調器——你寫的委派只有 4 處設定，剩下 691 行是 ADK 的。**
> 你手寫的是三個 `mode=` 加主管一個 `sub_agents=[...]`。ADK 那邊是 `tools/agent_tool.py`（470 行）＋ `flows/llm_flows/agent_transfer.py`（221 行），172 倍。
> 而模型收到的委派介面只有三個 `request: string`——沒有 DAG、沒有訊息佇列、沒有狀態機。學生想像的那個協調器不存在。
> **動手看**：`uv run travel_planner/agent.py --aha 2>/dev/null` 的第 ① 段 → `委派設定 4 處 ／ ADK 生成 691 行 ／ 172×`。

---

## 步驟 4：加一段 Sequential（15 分）

**動手**

```python
from google.adk.agents import SequentialAgent
from google.adk.tools import AgentTool

writer = Agent(
    model="gemini-3.7-flash", name="itinerary_writer",
    description="把確定的資訊寫成 Markdown 三天行程表。",
    instruction=("把對話中已確認的天氣、旅館、景點資訊，寫成 Markdown 三天行程表。"
                 "每天分上午／下午／晚上，最後一列出住宿與預估花費。總預算：{user:budget?} 元。"
                 "資訊不足的欄位寫「待確認」，不要編造。"),
    output_key="itinerary_md",              # 輸出自動寫進 state["itinerary_md"]
)

critic = Agent(
    model="gemini-3.7-flash", name="itinerary_critic",
    description="審查行程草稿的預算與時間衝突。",
    instruction=("嚴格審查這份行程草稿：\n{itinerary_md}\n\n"      # ← {key} 讀 state
                 "總預算 {user:budget?} 元。檢查三件事：(1) 預估花費是否超出預算 "
                 "(2) 同一天的行程是否地理上跑不完或時間重疊 (3) 有沒有「待確認」還沒補。"
                 "有問題就直接輸出修好的完整行程表；沒問題就原封不動輸出行程表並在最後加一行"
                 "「✅ 已通過預算與時間檢查」。"),
    output_key="itinerary_final",
)

itinerary_pipeline = SequentialAgent(
    name="itinerary_pipeline",
    description="產生並審核 Markdown 三天行程表。收集完天氣、旅館、景點資訊之後呼叫。",
    sub_agents=[writer, critic],
)
```

然後把它掛到主管上——注意**掛在 `tools` 不是 `sub_agents`**：

```python
root_agent = Agent(
    ...,
    sub_agents=[search_agent, weather_agent, booking_agent],
    tools=[set_budget, AgentTool(agent=itinerary_pipeline)],
)
```

instruction 最後一句也跟著改：

```
"三個專員的資訊都收齊之後，呼叫 itinerary_pipeline 工具產出並審核行程表，把它的輸出原文回給使用者。"
```

**為什麼**

- **為什麼行程表要用 Sequential 而不是叫主管自己寫**：「寫草稿 → 審預算與衝突」是步驟固定、可枚舉的流程。步驟可枚舉就不要讓 LLM 即興——同一件事讓主管在一次回覆裡「寫完順便檢查」，它會兩件事都做一半（尤其會漏掉預算加總）。拆成兩個 agent，critic 面對的是**已經寫好的草稿**，它的注意力全在挑錯上。
- **為什麼用 `AgentTool` 而不是塞進 `sub_agents`**：`sub_agents` 是「**轉交對話**」——控制權交出去就在那邊了，你會看到 critic 直接對使用者講話，主管再也沒機會彙整。`AgentTool` 是「**借用能力**」，像呼叫函式一樣呼叫，回傳值回到主管手上。行程表要由主管收尾，所以用 `AgentTool`。
- **`output_key` 和 `{placeholder}` 是同一條匯流排**：`SequentialAgent` 不會神奇地把上一個的輸出餵給下一個——它的資料匯流排就是 **session state**。writer 的 `output_key="itinerary_md"` 寫進去，critic 的 `{itinerary_md}` 讀出來。少了 `output_key`，critic 的 `{itinerary_md}` 會直接炸：
  ```
  KeyError: Context variable not found: `itinerary_md`.
  ```
- **為什麼 `{user:budget?}` 有問號**：使用者還沒講預算時，state 裡沒這個 key，`{user:budget}` 會是同一個 `KeyError`。問號版是「可選佔位符」，找不到就代成空字串。**實測三種寫法**：`{user:budget}` 正常代入、`{missing}` → KeyError、`{missing?}` → 空字串。
- **`SequentialAgent` 會印 deprecation warning**：ADK 2.7.1 開始推 `Workflow`（Graph），訊息原文是 `SequentialAgent is deprecated in favor of Workflow and will be removed in a future version. Workflow cannot yet be used as an LlmAgent sub-agent.` 後半句就是我們現在還用 Template 三兄弟的理由——我們的主管是 LlmAgent。

**驗收**

```bash
uv run python -c "
from travel_planner.agent import writer, critic, itinerary_pipeline, root_agent
assert writer.output_key == 'itinerary_md'
assert '{itinerary_md}' in critic.instruction
print([a.name for a in itinerary_pipeline.sub_agents])
print([getattr(t, 'name', None) or t.__name__ for t in root_agent.tools])" 2>/dev/null
# → ['itinerary_writer', 'itinerary_critic']
# → ['set_budget', 'itinerary_pipeline', 'search_agent', 'weather_agent', 'booking_agent']
```

後三個是 ADK 自己接上去的（上一步那段「委派在 Events 裡長什麼樣」解釋過）。你手寫的只有前兩個。

> `2>/dev/null` 是為了吃掉 `SequentialAgent is deprecated …` 和 `[EXPERIMENTAL] feature …` 兩種 warning。想看 warning 就拿掉它。

---

## 步驟 5：state 練習（15 分）—— 本 Lab 的核心失敗示範

**動手（先看它壞）**：現在的 `search_hotels` 有 `max_price: int = 5000`。到 `adk web` 說：

```
預算 3 萬，東京住三晚，有什麼旅館？
```

看 Events 裡 `search_hotels` 的參數。你會看到兩種壞法之一：

1. `{"city": "東京", "nights": 3}` —— 用了預設值 5000，於是「3 萬預算」被完全忽略，回你兩間便宜的，銀座柏悅（18000/晚，三晚 54000）被莫名擋掉。
2. `{"city": "東京", "nights": 3, "max_price": 30000}` —— 模型把**總預算**當成**每晚上限**塞進去，於是四間全上，其中三晚要 54000 的那間也「符合預算」。

而且**換一條 session**（adk web 左上角 New Session），預算就完全消失了——它只活在剛剛那段對話的文字裡。

**動手（修好）**：把預算從「對話裡的一句話」變成「state 裡的一個值」。加一個寫的工具、改一個讀的工具：

```python
from google.adk.tools import ToolContext

def set_budget(total_twd: int, tool_context: ToolContext) -> dict:
    """記下使用者這趟旅程的總預算（新台幣），之後同一個使用者的所有對話都讀得到。

    Args:
        total_twd: 總預算，新台幣整數，例如 30000。
    """
    if total_twd <= 0:
        return {"status": "error", "message": "預算要是正整數"}
    tool_context.state["user:budget"] = total_twd      # user: 前綴＝跨 session
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
        cap = int(budget) // nights                    # 總預算 ÷ 晚數 = 每晚上限

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
```

`set_budget` 掛在**主管**身上（`tools=[set_budget, AgentTool(...)]`），`search_hotels` 留在 `booking_agent`。`booking_agent` 的 instruction 也要跟著明確化：

```python
instruction=("用 search_hotels 查旅館。max_price 留 0，讓工具自己從 user:budget 換算每晚上限，"
             "並把 nights 填成實際住幾晚。工具回 status=error 就照 message 說明為什麼訂不到，"
             "不要自己編旅館名字。")
```

**為什麼**

- **為什麼一定要 `user:` 前綴**：預算是**使用者的屬性**，不是這輪對話的屬性。前綴決定作用域：無前綴＝本 session、`user:`＝同一使用者的所有 session、`app:`＝全應用、`temp:`＝本輪不持久化。寫成 `budget`（無前綴）的症狀就是上面那個「換 session 就忘了」，而且**不會有任何錯誤**——只有使用者覺得這個 agent 很失智。
- **為什麼把換算放在工具裡而不是叫模型算**：模型會把 30000 直接當每晚上限（上面壞法 2）。`總預算 ÷ 晚數` 是**確定性的算術**，這種東西放進 Python 就永遠對；留給 LLM 就是每次擲骰子。這也是「函式節點不花 token」那條原則的最小版。
- **為什麼 `tool_context` 不用出現在 instruction 裡**：ADK 看到 `tool_context: ToolContext` 這個註記就自己注入，而且**會從送給模型的 schema 裡剝掉**。實測 `search_hotels` 的 declaration 只有 `city` / `nights` / `max_price` 三個參數，模型看不到也填不到 `tool_context`。
- **為什麼沒預算要回 error 而不是給個預設值**：預設值 5000 就是上面壞法 1 的元凶——它讓錯誤變成沉默。回一句「請先問使用者總預算」，模型就會反問使用者，這是正確行為。
- **為什麼超預算要附 `cheapest` 和總價**：模型手上有 `2800/晚、三晚 8400` 這兩個數字，才講得出「請提高預算到 8400 元以上，或改成住兩晚」。只回 `count: 0` 的話它只能說「找不到」，然後使用者不知道差多少。

**驗收**

離線先驗（不需要 key、不連網）：

```bash
uv run travel_planner/agent.py --self-check
```

```
self-check ok（12 組 assert：假資料過濾、預算 state、委派接線與委派機制、instruction 佔位符）
```

再回 `adk web`，**開一條新 session**，走這三輪：

```
1) 東京住三晚，有什麼旅館？          → agent 應該「反問你預算」（不是編一個）
2) 預算 3 萬                          → Events: set_budget {"total_twd": 30000}
                                        State 分頁: user:budget = 30000
3) 那旅館呢？                          → Events: search_hotels {"city":"東京","nights":3,"max_price":0}
                                        回三間（2800/4200/6500），銀座柏悅 18000 被排除
```

第 3 輪的關鍵是 `max_price` 必須是 **0**（讓工具自己算），而不是 30000。是 30000 的話回去把 `booking_agent` 的 instruction 那句「max_price 留 0」講得更死。

> ⚠️ 未實測：`adk web` 的三輪對話需要 API key。`--self-check` 的 12 組 assert 是實測通過的，`tool_context` 被剝出 schema 這件事也是實測的。

> 💡 **啊哈：`temp:` 不是「短命」，是根本沒被存下來——但你手上那個 session 物件還看得到它。**
> `append_event` 先把 `temp:` 寫進手上的 session 物件，再把它從「要存的 delta」剝掉（ADK 2.7.1 `sessions/base_session_service.py:195` `_trim_temp_delta_state`）。所以同一輪內讀 `temp:` 是通的，重新 `get_session` 就是空的。
> 意思是這種錯**在你眼前會是綠的**：你 print 手上的 state 看到值、以為存好了，下一輪才發現沒了。無前綴 / `user:` / `app:` 的界線也一樣是量出來的，不用花 key。
> **動手看**：`uv run travel_planner/agent.py --aha 2>/dev/null` 的第 ④ 段 → `temp:budget` 一整列都是 ✗，但下面那行印「手上那個 session 物件還看得到 temp:budget：True」。

---

## 步驟 6：`adk web` 除錯（10 分）

**動手**

```bash
uv run adk web              # 或 uv run adk web --port 8080
```

貼最終驗收題，然後四個分頁各看一遍：

| 分頁 | 看什麼 | 壞掉長什麼樣 |
|---|---|---|
| **Events** | 委派的 function call（`weather_agent` / `booking_agent` / `search_agent`）；每個 function call 的 `args` | 沒有委派的 call → 主管自己答了（步驟 3 的病）；args 錯 → docstring 沒寫清楚 |
| **State** | `user:budget` / `itinerary_md` / `itinerary_final` | `budget` 沒前綴 → 換 session 消失；`itinerary_md` 空的 → writer 少了 `output_key` |
| **Trace** | 延遲瀑布圖：哪個工具慢、模型呼叫幾次 | `get_weather` 卡 10 秒 → Lab 6 的 server 在等 Open-Meteo |
| **Eval** | 把這次滿意的互動存成測試案例 | 步驟 7 要用 |

**為什麼**

- **為什麼不用 print debug**：多 agent 的執行是巢狀的（主管 → 專員 → 工具 → pipeline → writer → critic），`print` 只給你一條扁平的線，看不出誰把控制權交給誰。`adk web` 的 Events 是唯一能一眼看出「委派拓樸」的地方。
- **心法**：「agent 不聽話」先看 Events，九成是 **instruction 模糊**或**工具 docstring 寫爛**——不是模型笨，也不是框架 bug。這兩件事你都能改。
- **為什麼要看 Trace**：token 和延遲是 multi-agent 最容易失控的兩件事。主管每次派工都是一次完整的 LLM 呼叫，一輪對話跑掉 6 次模型呼叫很正常。看不到就不會想去優化（該優化時就是換 Graph workflow，官方基準省 ~50% tokens）。
- **`adk web` 只能開發用**：正式環境走 `api_server` 或部署（Lab 10）。

**驗收**：Events 裡數得出三個專員各被呼叫幾次（function call 的 `name` 就是專員名字）、State 分頁三個 key 都有值。

順手驗一下 `api_server` 這條路（部署形態的本機預演），它可以在建 session 時**直接塞初始 state**：

```bash
uv run adk api_server &                    # :8000
curl -s -X POST localhost:8000/apps/travel_planner/users/u1/sessions/s1 \
  -H "Content-Type: application/json" -d '{"user:budget": 30000}'

curl -s -X POST localhost:8000/run -H "Content-Type: application/json" -d '{
  "appName": "travel_planner", "userId": "u1", "sessionId": "s1",
  "newMessage": {"role": "user", "parts": [{"text": "東京住三晚有什麼旅館？"}]}}'
```

這次不用先講預算——state 是建 session 時給的。這就是 Lab 10 上 Cloud Run 之後的正式介面。

> ⚠️ 未實測：`adk web` 的四個分頁與這兩條 curl 都需要 API key，我沒有 key。端點路徑與 payload 欄位名（`appName` / `userId` / `sessionId` / `newMessage`）照投影片 P325。

> 💡 **啊哈：Events 裡那個工具的 description 不是你寫的那份——ADK 在 `task` 模式的專員後面偷加了一句英文 prompt。**
> `booking_agent` 你寫 30 字，模型看到 151 字：ADK 接上了 `IMPORTANT: This tool delegates execution to a specialized agent. Do NOT call this tool in parallel with any other tools.`（原始碼 `tools/agent_tool.py:447`）。兩個 `single_turn` 專員沒有這句。
> 也就是說「task 模式不能平行」是**一句 prompt 在管**，不是排程器擋的。除錯時你在讀的 description，跟模型讀的不是同一份。
> **動手看**：`uv run travel_planner/agent.py --aha 2>/dev/null` 的第 ② 段 → `booking_agent ／ 你寫 30 ／ 模型看到 151 ／ +121`。

---

## 步驟 7：建立 evalset（15 分）

**動手（正式做法）**：在 `adk web` 裡把三次滿意的互動用 **Eval 分頁**存成案例——不要手寫 JSON，錄的比寫的準（錄下來的軌跡才是這個模型版本真正走的路）。

三個案例要包含：

| eval_id | 問什麼 | 測什麼 |
|---|---|---|
| `case1_budget_then_hotel` | 預算 3 萬，11 月去東京三天，有哪些旅館？ | `set_budget` → `booking_agent` → `search_hotels(max_price=0)` 的完整軌跡 |
| `case2_weather_delegation` | 東京 11 月會下雨嗎？ | 派給 `weather_agent` 且真的呼叫 MCP 的 `get_weather` |
| `case3_budget_exceeded_edge` | **預算 6000 元**，東京住三晚 | edge case：每晚只有 2000，最便宜 2800，要說明超支多少 |

本目錄的 `tests/travel.evalset.json` 是同樣三個案例的手寫版（給沒 key 的人有東西可讀），結構長這樣：

```json
{
  "eval_set_id": "travel",
  "eval_cases": [{
    "eval_id": "case3_budget_exceeded_edge",
    "session_input": { "app_name": "travel_planner", "user_id": "u2", "state": {} },
    "conversation": [{
      "invocation_id": "c3-i1",
      "user_content": { "role": "user", "parts": [{ "text": "預算 6000 元，東京住三晚，幫我找旅館" }] },
      "intermediate_data": { "tool_uses": [
        { "name": "set_budget", "args": { "total_twd": 6000 } },
        { "name": "booking_agent", "args": { "request": "東京住三晚，預算 6000 元，找旅館" } },
        { "name": "search_hotels", "args": { "city": "東京", "nights": 3, "max_price": 0 } }
      ]},
      "final_response": { "role": "model", "parts": [{ "text": "6000 元分三晚，每晚只有 2000 元…最便宜的上野膠囊旅館 2800 元/晚，三晚共 8400 元，已超出預算。" }] }
    }]
  }]
}
```

門檻寫在 `tests/criteria.json`：

```json
{ "criteria": { "tool_trajectory_avg_score": 1.0, "response_match_score": 0.5 } }
```

跑：

```bash
uv run adk eval travel_planner tests/travel.evalset.json \
    --config_file_path=tests/criteria.json --print_detailed_results
```

**為什麼**

- **為什麼要有 `session_input.state`**：`case2` 的 state 預設了 `{"user:budget": 30000}`——這是在測「已經知道預算的使用者」這條路徑。沒有 `session_input`，每個案例都從空白 state 開始，你永遠測不到跨 session 的預算是否真的被讀到。
- **為什麼 `tool_trajectory_avg_score` 門檻是 1.0**：軌跡指標要求**工具呼叫序列與預期完全一致**才給分。這很嚴格，但這正是你要的——「改 instruction 之後它還會不會派給同一個人」就是這條在守。
- **⚠️ 這個門檻對「委派」那一行非常不友善**：ADK 2.7.1 的比對是 `actual.name != expected.name or actual.args != expected.args`（原始碼 `evaluation/trajectory_evaluator.py`），**連 args 都要一字不差**，而預設 `match_type` 是 `EXACT`（連數量都要一樣）。委派 call 的 `args` 是 `{"request": "<模型自己生成的一段中文>"}`——這段字每次都不一樣，所以**手寫的軌跡在這一行必定掛**。兩條路：
  1. 用 `adk web` 的 Eval 分頁**錄**一次（錄下來的 `request` 至少是這個模型當下真的送的），但下一次跑仍可能飄。
  2. 放寬比對：`criteria.json` 改成 `{"tool_trajectory_avg_score": {"threshold": 1.0, "match_type": "IN_ORDER"}}`，只要求關鍵工具**依序出現**、容許多出來的呼叫。
     > ⚠️ 未實測：這個寫法被 2.7.1 的 config 解析吃下去了（`adk eval` 沒噴 config 錯誤），但實際比對行為要有 API key 才驗得到。本目錄 `tests/criteria.json` 留的是實測過能解析的純數字版。
- **為什麼 `response_match_score` 只給 0.5**：這是 ROUGE 字面重疊，對中文長行程表非常不友善（同義改寫就掉分）。門檻設 1.0 只會逼你把 `final_response` 抄死。要真的評品質改用 LLM 評審型指標（`final_response_match_v2`、rubric、hallucinations 檢測）。
- **為什麼 edge case 一定要有**：happy path 三題全綠不代表什麼——`search_hotels` 回 error 那條路徑是模型最容易亂編的地方（編一間 2000 元的東京旅館）。回歸測試的價值全在 edge case 上。
- **什麼時候跑**：改 instruction、換模型、加工具之後。eval 就是 agent 的回歸測試；模型從 3.6 升 3.7 時跑一輪，行為飄移立刻現形。

**驗收**

```
Eval Run Summary
  Tests passed: 3
  Tests failed: 0
```

evalset 的 JSON 結構本身可以離線驗（不呼叫模型、不用 key）：

```bash
uv run python -c "
from google.adk.evaluation.eval_set import EvalSet
es = EvalSet.model_validate_json(open('tests/travel.evalset.json').read())
print('ok', es.eval_set_id, [c.eval_id for c in es.eval_cases])"
# → ok travel ['case1_budget_then_hotel', 'case2_weather_delegation', 'case3_budget_exceeded_edge']
```

**CI 的坑**：`adk eval` 全部失敗時 **exit code 還是 0**（實測 2.7.1：三個案例全掛，`echo $?` 是 0）。放進 CI 要 grep 輸出：

```bash
uv run adk eval travel_planner tests/travel.evalset.json \
    --config_file_path=tests/criteria.json 2>&1 | tee /tmp/eval.log
grep -q "Tests failed: 0" /tmp/eval.log || { echo "EVAL FAILED"; exit 1; }
```

> ⚠️ 未實測：`Tests passed: 3` 需要 API key。我實測到的是「沒 key 時每個案例都噴 `ValueError: No API key was provided.`，summary 印 `Tests passed: 0 / Tests failed: 3`，而 exit code 是 0」。
>
> `tests/travel.evalset.json` 的 `tool_uses` 軌跡是照 ADK 2.7.1 的委派機制寫的（委派＝以專員命名的 function call，這一點是實測的），但**委派 call 的 `request` 字串是我編的**，`EXACT` 比對必定對不上——**跑之前一定要用 `adk web` 的 Eval 分頁重錄**，或把 `match_type` 放寬（見上面那條）。JSON 結構本身已用 ADK 的 `EvalSet` pydantic 模型驗過。

---

## 步驟 8：驗收（8 分）

**動手**：新開一條 session，一句話丟進去：

```
預算 3 萬、11 月去東京三天，怕下雨
```

**驗收清單**

- [ ] Events 裡有 `set_budget {"total_twd": 30000}`
- [ ] State 分頁有 `user:budget: 30000`
- [ ] Events 裡有 `weather_agent {"request": …}` 且接著 `get_weather {"lat": 35.68, "lon": 139.77}`（走 Lab 6 的 MCP server）
- [ ] Events 裡有 `booking_agent {"request": …}` 且 `search_hotels` 的 `max_price` 是 **0**、`nights` 是 **3**
- [ ] 最終回覆是 **Markdown 三天行程表**，每天分上午／下午／晚上
- [ ] 行程表裡有**天氣建議**（因為使用者說「怕下雨」——降雨機率高的那天要排室內行程）
- [ ] 行程表裡有住宿與**預估花費**，總額不超過 30000
- [ ] 結尾有 critic 的 `✅ 已通過預算與時間檢查`（或 critic 指出的問題已經被修進行程表）
- [ ] `uv run travel_planner/agent.py --self-check` 通過（唯一一條不用 key、不花錢的）
- [ ] `uv run adk eval …` → `Tests passed: 3`
- [ ] 你能說出「把 `search_agent` 的 `tools` 改成 `[google_search, search_hotels]` 會發生什麼事」，而且真的試過
- [ ] 你能說出「把 `user:budget` 改成 `budget` 會發生什麼事」，而且真的在 New Session 後試過

> ⚠️ 未實測：整份清單除了 `--self-check` 那條之外都需要 API key 與網路，我沒有 key。

---

## 常見錯誤對照表

| 症狀 | 原因 | 解法 |
|---|---|---|
| `ModuleNotFoundError: No module named 'google'` | 用了 `python agent.py` | 一律 `uv run travel_planner/agent.py` |
| `ModuleNotFoundError: No module named 'travel_planner'` | 不在 `lab7/` 目錄裡 | `cd lab7` |
| `ValueError: No API key was provided. Please pass a valid API key.` | `.env` 沒填，或**放在專案根目錄而不是 `travel_planner/` 裡** | key 要在 **agent 目錄**的 `.env`；ADK 只載入那一份 |
| `Error: Eval module is not installed, please install via pip install "google-adk[eval]".` | 只 `uv add google-adk`，沒裝 eval extra | `uv add "google-adk[eval,mcp]"`（別照它說的跑 pip） |
| `ModuleNotFoundError: No module named 'mcp'` | 沒裝 mcp extra | 同上 |
| `ModuleNotFoundError: No module named 'mcp.shared.session'` ／ `ImportError: cannot import name 'SamplingCapability' from 'mcp'` | 手動 `uv add mcp` 裝到 2.x（或釘到太舊的 1.x）。ADK 2.7.1 要 `mcp>=1.24,<2` | 移掉手動的 mcp，改用 `uv add "google-adk[mcp]"` 讓它自己解版本 |
| `ConnectionError: Failed to create MCP session: … Session terminated` | Lab 6 的 server 沒開，或 `MCP_URL` 的 port 不對 | 開 server；`curl -o /dev/null -w '%{http_code}' $MCP_URL` 確認活著 |
| `curl http://localhost:8080/mcp` 一直掛著不回應 | Streamable HTTP 的 GET 是 SSE 通道，正常行為就是不關 | 用 `POST` + `initialize`（步驟 0 的驗收指令），或 `nc -z localhost 8080` |
| `[Errno 48] error while attempting to bind on address ('0.0.0.0', 8080): address already in use` | 8080 被別的東西占了 | `PORT=8099 MCP_TRANSPORT=http uv run server.py`，並同步改 `.env` 的 `MCP_URL` |
| `ValidationError … mode Input should be 'chat', 'task' or 'single_turn' [type=literal_error, input_value='single-turn']` | 照投影片 P297 抄了連字號版 | `single_turn`（**底線**） |
| `KeyError: Context variable not found: \`itinerary_md\`.` | critic 讀 `{itinerary_md}` 但 writer 沒設 `output_key`；或 key 拼錯 | 補 `output_key="itinerary_md"`；「可能不存在」的 key 寫 `{key?}` |
| `KeyError: Context variable not found: \`user:budget\`.` | 使用者還沒講預算就跑到 writer | 寫成 `{user:budget?}`（可選佔位符） |
| `DeprecationWarning: SequentialAgent is deprecated in favor of Workflow …` | ADK 2.7.1 推 Graph workflow 了 | 現階段照用：同一句話後半說 `Workflow cannot yet be used as an LlmAgent sub-agent`，我們的主管是 LlmAgent |
| 主管自己答天氣，Events 裡沒有任何委派的 function call | instruction 太模糊，委派對模型來說是額外動作 | instruction 明說「你不直接回答 X，一律交給 Y」 |
| Events 裡找不到 `transfer_to_agent`，只有名為 `weather_agent` 的 function call | **這是正常的**。ADK 2.7.1 把 `mode='single_turn'`／`'task'` 的 sub-agent 包成 AgentTool 接到 `tools`，只有 `mode='chat'` 才走 `transfer_to_agent` | 照著看 function call 的 `name`；要驗機制跑步驟 3 那行 `_get_transfer_targets(root_agent)` → `[]` |
| `adk eval` 的 `tool_trajectory_avg_score` 永遠 0 分，明明看起來派對人了 | 預設 `match_type` 是 `EXACT`，連 args 都要一字不差；委派 call 的 `{"request": "…"}` 每次都不同 | 用 Eval 分頁重錄，或 `criteria.json` 改 `{"threshold":1.0,"match_type":"IN_ORDER"}` |
| 派錯專員（問旅館派給 search_agent） | 兩份 `description` 職責重疊 | 改 `description`，把「不查天氣、不查旅館」這種排除句寫進去 |
| 子 agent 答完不回主管，接下來都是它在講話 | `chat` 模式（預設）的已知特性 | 專員設 `mode="task"` 或 `"single_turn"` |
| `search_hotels` 的 `max_price` 被填成 30000（總預算當每晚上限） | instruction 沒說「留 0」，模型自己算 | instruction 明寫 `max_price 留 0`；換算放 Python 不放 LLM |
| 換一條 session 之後預算不見了 | state key 沒有 `user:` 前綴 | `tool_context.state["user:budget"]`；`user:`＝同使用者所有 session |
| `adk eval` 三個全掛但 `echo $?` 是 0 | 2.7.1 的 exit code 不反映結果 | CI 裡 grep `Tests failed: 0` |
| 模型編出一間不存在的旅館 | 工具回 `count: 0` 空 list，模型分不出「沒有」與「城市不存在」 | 回 `status: error` + 人話 `message` + `cheapest` |
| 天氣回了太平洋上某處的資料 | `get_weather(lat, lon)` 吃座標，模型自己編了經緯度 | 把已知城市座標寫進 instruction |
| `weather_agent` 手上多一個換匯工具 | `McpToolset` 沒設白名單 | `tool_filter=["get_weather"]` |

---

## 完整解答

- `travel_planner/agent.py` —— 走完八步的版本：三專員、主管、`itinerary_pipeline`、`set_budget` / `search_hotels`、`--self-check`、`--aha`（四張對照表，離線可跑）。
- `travel_planner/.env.example` —— 兩條路線的 `.env` 範本（複製成 `.env`）。
- `tests/travel.evalset.json` ＋ `tests/criteria.json` —— 三個案例與門檻。
- `SPEC.md` —— 架構圖、state key 表、工具 schema 實測輸出、錯誤處理表、已知限制與升級路徑。
- `PRD.md` —— 學習目標、FR 對照投影片步驟、驗收清單、費用。

學生卡住再開 `agent.py`；先自己撞完步驟 3 和步驟 5 那兩個失敗示範，價值全在那裡。

## 想再往下玩

- **改成 Graph Workflow**：`Workflow` + `edges` + `Event(route=...)`，讓「收資訊 → 寫 → 審 → 通過就發佈／不通過回頭改」變成一張確定性的圖（P303-304）。純函式節點不花 token，官方基準省 ~50%。注意 `Workflow` 現在還不能當 LlmAgent 的 sub-agent，所以主管也要一起改。
- **換掉 InMemory session**：`DatabaseSessionService(db_url="sqlite+aiosqlite:///./travel.db")`，重啟之後 `user:budget` 還在。**async driver 不能少**，`sqlite+aiosqlite` 寫成 `sqlite` 直接報錯。這是 **Lab 8** 的暖身（那邊會換成 Supabase 的 `postgresql+asyncpg`）。
- **掛一個 guardrail**：`before_model_callback` 擋掉輸入裡的身分證字號／信用卡號，回傳 `LlmResponse` 就略過模型（P315）。
- **`to_mcp_server(root_agent)`**：把整個旅遊助理變成一台 MCP server，掛回 Lab 3 的 Antigravity——你的 agent 變成同事 IDE 裡的一個工具（P321）。
- **接下去是 Lab 8**：把 session、memory 和 RAG 都接到 Supabase PostgreSQL + pgvector，agent 開始處理真實資料。

## 這個 Lab 你真正學到的

- 「委派」在 Google 生態系裡的實作位置是 `sub_agents` ＋ `mode`：我寫 4 處設定，ADK 用 691 行把它變成模型眼中一個參數叫 `request` 的普通函式——多 agent 的難點從來不是協調，是邊界怎麼寫清楚。
- 「工具」是一個會換包裝的概念：`get_weather` 從 python 函式 → MCP tool（Lab 6）→ `MCPTool`（這裡）→ Cloud Run 端點（Lab 10），`search_hotels` 從本地函式 → A2A skill（Lab 9）；模型每次收到的都是同一份 `FunctionDeclaration`。
- 「記憶」在 ADK 裡有保存期限：前綴（無／`user:`／`app:`／`temp:`）決定資料活多久，選錯不會報錯，只會讓 agent 看起來失智。
- 「確定性」是我自己決定要放多少的：能枚舉的步驟交給 Sequential、能算的數學交給 Python，剩下才給 LLM——每把一件事從 LLM 搬到程式碼，就少擲一次骰子。
- agent 也是軟體，所以要有回歸測試：evalset 就是它的測試檔，而價值全在 edge case，不在 happy path。

## 清理

這個 Lab **沒有任何雲端資源要刪**——沒建 GCP 專案、沒開服務、沒上傳檔案。全程 AI Studio 免費層，費用 $0。

```bash
# 1) 關掉 Lab 6 的 MCP server（那個視窗 Ctrl-C），或
pkill -f "lab6/server.py"

# 2) eval 跑過的紀錄（已 gitignore，純本機）
rm -rf travel_planner/.adk

# 3) 這把 key 不會再用 → https://aistudio.google.com/apikey 按 Delete
#    然後清掉 .env（裡面有 key，別留在硬碟上）
rm travel_planner/.env

# 4) 本機環境，下次 uv run 會自己重建
rm -rf .venv
```

`travel_planner/` 這個目錄留著——**Lab 10 的 `adk deploy cloud_run` 就是拿這個形狀的 agent 套件上雲**（Lab 10 那邊實際部署的是它自己的 `concierge/`，接的是 Lab 6/8/9 的雲端版本）。
