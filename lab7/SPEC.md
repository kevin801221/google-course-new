# Lab 7 SPEC：多 Agent 旅遊助理

## 1. 架構

```
                    ┌──────────────────────── 你的終端機 ────────────────────────┐
                    │  uv run adk web            → http://localhost:8000        │
                    │  uv run adk run  …         → 終端機互動                    │
                    │  uv run adk api_server     → POST /run, /run_sse          │
                    └───────────────────────────┬───────────────────────────────┘
                                                │  同一個 process 內
┌───────────────────────────────────────────────▼──────────────────────────────────────┐
│ travel_planner/  (一個目錄＝一個 app，啟動時自動載入本目錄的 .env)                       │
│                                                                                      │
│   root_agent  travel_planner  (LlmAgent, gemini-3.7-flash)                           │
│   ├─ tools ── set_budget(total_twd)         ── 寫 state["user:budget"]                │
│   ├─ tools ── AgentTool(itinerary_pipeline) ── 借用能力，主管保留控制權                 │
│   │             │                                                                    │
│   │             └── SequentialAgent  itinerary_pipeline                               │
│   │                   ├─ itinerary_writer  output_key="itinerary_md"  ──┐            │
│   │                   └─ itinerary_critic  instruction 讀 {itinerary_md} ◄┘          │
│   │                        output_key="itinerary_final"                              │
│   │                                                                                  │
│   └─ sub_agents ── mode=single_turn/task → ADK 自動包成 AgentTool 接進 tools           │
│        ├── search_agent   mode=single_turn  tools=[google_search]  ← 必須獨占         │
│        ├── weather_agent  mode=single_turn  tools=[McpToolset(...)]                  │
│        └── booking_agent  mode=task         tools=[search_hotels]                    │
│                                                    │                                 │
│   session state（InMemorySessionService，重啟消失）  │ 讀 tool_context.state           │
│     user:budget   ← set_budget 寫，search_hotels 讀 ┘                                │
│     itinerary_md      ← writer 寫，critic 讀                                          │
│     itinerary_final   ← critic 寫                                                    │
└──────────────┬────────────────────────────────────────────┬──────────────────────────┘
               │ Streamable HTTP (MCP)                      │ HTTPS
               ▼                                            ▼
   ┌───────────────────────────────┐          ┌──────────────────────────────┐
   │ lab6/server.py  (另一個 process)│          │ Gemini API (Developer 路線)   │
   │ MCP_TRANSPORT=http :8080/mcp  │          │ generativelanguage.googleapis │
   │ tools: get_weather(lat,lon)   │          │ google_search grounding       │
   │        convert_currency ← 被  │          └──────────────────────────────┘
   │        tool_filter 擋掉        │
   └───────────────────────────────┘
```

程序邊界只有兩條：**ADK app（含所有 agent）是一個 process**，Lab 6 的 MCP server 是**另一個 process**（所以它可以用 mcp 2.x，ADK 這邊用 mcp 1.x，靠協定溝通不靠套件版本）。

## 2. 元件與職責

| 元件 | 型別 | 模型 | 工具 | 職責 |
|---|---|---|---|---|
| `travel_planner` | `Agent`（root） | 3.7-flash | `set_budget`, `AgentTool(itinerary_pipeline)` | 理解需求、記預算、派工、呼叫 pipeline 收尾。**自己不查資料** |
| `search_agent` | `Agent` sub | 3.7-flash | `google_search`（唯一） | 景點、票價、營業時間、時事 |
| `weather_agent` | `Agent` sub | 3.5-flash-lite | `McpToolset` → `get_weather` | 城市天氣；城市→經緯度寫在 instruction 裡 |
| `booking_agent` | `Agent` sub | 3.7-flash | `search_hotels` | 旅館搜尋＋預算過濾；查不到就說明，不編 |
| `itinerary_pipeline` | `SequentialAgent` | — | — | 容器：writer 跑完換 critic |
| `itinerary_writer` | `Agent` | 3.7-flash | 無 | 把已確認資訊寫成 Markdown 三天行程 |
| `itinerary_critic` | `Agent` | 3.7-flash | 無 | 審預算超支、時間／地理衝突、未補的「待確認」 |
| `set_budget` | FunctionTool | — | — | 寫 `state["user:budget"]`（跨 session） |
| `search_hotels` | FunctionTool | — | — | 假資料過濾；`max_price=0` 時從 state 換算每晚上限 |

模型分級照 P295：主管與需要推理的專員用 Flash，天氣這種純查詢用 Flash-Lite。

## 3. 介面契約

### 3.1 工具簽章（送給模型的 schema 由 docstring + 型別註記自動生成）

```python
def set_budget(total_twd: int, tool_context: ToolContext) -> dict
# 回傳 {"status": "success", "budget_twd": int}
#   或 {"status": "error", "message": str}

def search_hotels(city: str, nights: int = 1, max_price: int = 0,
                  tool_context: ToolContext = None) -> dict
# 成功 {"status": "success", "cap_per_night": int, "count": int,
#       "hotels": [{"name": str, "price": int, "area": str}, ...],
#       "total_twd": [{"name": str, "total": int}, ...]}
# 失敗 {"status": "error", "message": str,
#       "cap_per_night"?: int, "cheapest"?: {...}}
```

`tool_context` **不會**出現在模型看到的 schema 裡（ADK 會剝掉）。實測 `search_hotels` 產生的 declaration：

```json
{
 "name": "search_hotels",
 "description": "搜尋城市的旅館，並用預算過濾。\nArgs:\n    city: …\n    nights: …\n    max_price: …",
 "parameters_json_schema": {
   "type": "object",
   "properties": {"city": {"type": "string"}, "nights": {"type": "integer", "default": 1},
                  "max_price": {"type": "integer", "default": 0}},
   "required": ["city"]
 }
}
```

### 3.2 MCP 契約（Lab 6 → weather_agent）

| 項目 | 值 |
|---|---|
| transport | Streamable HTTP |
| url | `MCP_URL`，預設 `http://localhost:8080/mcp` |
| 連線參數 | `StreamableHTTPConnectionParams(url=...)`（欄位：`url`, `headers`, `timeout`, `sse_read_timeout`, `terminate_on_close`, `httpx_client_factory`） |
| 白名單 | `tool_filter=["get_weather"]` |
| 工具簽章 | `get_weather(lat: float, lon: float) -> dict`（Lab 6 定義，走 Open-Meteo） |

### 3.3 委派契約（Events 裡看得到的東西）

ADK 2.7.1 有**兩套互斥的委派機制**，由 sub-agent 的 `mode` 決定（原始碼：`agents/llm_agent.py::model_post_init` 與 `flows/llm_flows/agent_transfer.py::_get_transfer_targets`）：

| sub-agent 的 `mode` | 機制 | Events 裡看到什麼 |
|---|---|---|
| `chat`（預設） | 留在 transfer 目標清單，主管拿到 `transfer_to_agent` 工具 | `transfer_to_agent`，`args={"agent_name": "weather_agent"}` |
| `single_turn` | 被包成 `_SingleTurnAgentTool` 接到 `root_agent.tools` | function call 名字＝**專員名**，`args={"request": "<模型生成的文字>"}` |
| `task` | 被包成 `_TaskAgentTool`（declaration 會多一句 "Do NOT call this tool in parallel"） | 同上 |

**本 Lab 三個專員都設了 `single_turn` / `task`，所以 Events 裡沒有 `transfer_to_agent`**——實測 `_get_transfer_targets(root_agent)` 回 `[]`，`root_agent.tools` 是 `['set_budget', 'itinerary_pipeline', 'search_agent', 'weather_agent', 'booking_agent']`。投影片 P298 說的「看 transfer 事件」只適用 `chat` 模式。

另外，`mode='task'` 的 agent 自己也會被塞一個 `FinishTaskTool`（實測 `booking_agent.tools` = `[search_hotels, FinishTaskTool]`），這是它「做完自動返回主管」的實作。

| 其他事件 | 什麼時候 | 關鍵欄位 |
|---|---|---|
| function call / response 對 | 專員呼叫工具 | `name`, `args`；回應是工具的 dict |
| state delta | `output_key` 或 `tool_context.state[...]` 寫入 | adk web 的 **State** 分頁 |

`mode` 只能是 `'chat'` / `'task'` / `'single_turn'`（**底線**，投影片 P297 寫成 `single-turn` 是筆誤）。

### 3.4 REST 端點（`adk api_server`，P325）

```
POST /apps/travel_planner/users/u1/sessions/s1     # body 為初始 state
POST /run          # {"appName","userId","sessionId","newMessage":{...}}
POST /run_sse      # 加 "streaming": true
```

## 4. 資料模型（session state）

| key | 作用域 | 誰寫 | 誰讀 | 型別 |
|---|---|---|---|---|
| `user:budget` | 同一 `user_id` 的所有 session | `set_budget` | `search_hotels`、writer/critic 的 `{user:budget?}` | int（新台幣總額） |
| `itinerary_md` | 本 session | `itinerary_writer` 的 `output_key` | `itinerary_critic` 的 `{itinerary_md}` | str（Markdown） |
| `itinerary_final` | 本 session | `itinerary_critic` 的 `output_key` | 主管彙整 | str（Markdown） |

前綴規則（P309）：無前綴＝本 session、`user:`＝跨 session 同使用者、`app:`＝全應用、`temp:`＝本輪不持久化。**預算是使用者屬性不是這輪對話的屬性，所以必須是 `user:budget`**；寫成 `budget` 的話換一條 session 就忘了。

instruction 的佔位符解析實測行為：

| 寫法 | 結果 |
|---|---|
| `{user:budget}` | 正常代入（前綴不影響解析） |
| `{missing}` | `KeyError: Context variable not found: \`missing\`.` |
| `{missing?}` | 代成空字串（可選佔位符） |

所以 writer / critic 讀 `{user:budget?}` 加問號——使用者還沒講預算時不該炸掉。

## 5. 檔案結構

```
lab7/
├── PRD.md                          需求、學習目標、驗收清單
├── SPEC.md                         本檔
├── walkthrough.md                  ★ 一步一步教學
├── pyproject.toml                  uv 專案；deps: google-adk[eval,mcp]
├── uv.lock                         可重現安裝（進版控，CI 用 uv sync --frozen）
├── travel_planner/                 ← 一個目錄＝一個 agent app
│   ├── __init__.py                 `from . import agent`（adk 靠這行找到 agent 模組）
│   ├── agent.py                    所有 agent、兩個工具、HOTELS 假資料、--self-check
│   ├── .env.example                複製成 .env 填 GOOGLE_API_KEY
│   ├── .env                         ← 你自己建，已被 .gitignore 排除
│   └── .gitignore                  .env / .adk/ / .venv/ / __pycache__/
└── tests/
    ├── travel.evalset.json         3 個案例（含預算超標 edge case）
    └── criteria.json               門檻：tool_trajectory 1.0、response_match 0.5
```

`adk eval` 跑完會在 `travel_planner/.adk/eval_history/*.evalset_result.json` 留紀錄——已 gitignore。

## 6. 環境變數與設定

| 變數 | 用途 | 從哪來 | 預設 |
|---|---|---|---|
| `GOOGLE_API_KEY` | Developer API 路線的金鑰 | <https://aistudio.google.com/apikey> | 無（缺了直接 `ValueError: No API key was provided.`） |
| `GOOGLE_GENAI_USE_ENTERPRISE` | 走 Vertex/Enterprise 還是 Developer API | `adk create` 產生 | `0`（Developer API） |
| `GOOGLE_CLOUD_PROJECT` / `_LOCATION` | Enterprise 路線才要 | M5 | 無 |
| `MCP_URL` | Lab 6 天氣 MCP server 的位址 | 你自己（`.env`） | `http://localhost:8080/mcp` |
| `ADK_MODEL` | 主力模型覆寫 | 你自己 | `gemini-3.7-flash` |
| `ADK_MODEL_LITE` | 雜活模型覆寫 | 你自己 | `gemini-3.5-flash-lite` |

型號名以課程投影片為準；若 404 用 `client.models.list()` 確認現行 ID。`ADK_MODEL` 這個開關就是附錄 D ⑧「preview 模型不要寫死」的最小版實作。

## 7. 執行流程

```bash
# 0) Lab 6 的天氣 MCP server（另一個終端機視窗，讓它一直開著）
cd ../lab6 && MCP_TRANSPORT=http uv run server.py       # 綁 0.0.0.0:8080

# 1) 建專案 + 裝套件
uv init --bare --name lab7 --python 3.13
uv add "google-adk[eval,mcp]"                            # eval 與 mcp 都是 extra，不加會缺
uv run adk --version                                     # 2.7.x

# 2) 骨架（本 repo 已經有成品，這行是給從零開始的人）
uv run adk create travel_planner --model gemini-3.7-flash

# 3) 金鑰
cp travel_planner/.env.example travel_planner/.env && $EDITOR travel_planner/.env

# 4) 離線檢查（不連網、不花錢）
uv run travel_planner/agent.py --self-check

# 5) 開發 UI
uv run adk web                                           # → http://localhost:8000

# 6) 回歸測試
uv run adk eval travel_planner tests/travel.evalset.json \
    --config_file_path=tests/criteria.json --print_detailed_results
```

## 8. 錯誤處理與邊界

| 情境 | 症狀（實際訊息） | 處理方式 |
|---|---|---|
| 沒 API key | `ValueError: No API key was provided. Please pass a valid API key.` | `travel_planner/.env` 填 `GOOGLE_API_KEY`；注意是 agent 目錄的 `.env`，不是專案根目錄 |
| 沒裝 eval extra | `Error: Eval module is not installed, please install via pip install "google-adk[eval]".` | `uv add "google-adk[eval,mcp]"`（**不要**照它說的跑 pip） |
| Lab 6 server 沒開 | `ConnectionError: Failed to create MCP session: … Session terminated` | 開 server；或臨時把 `weather_agent` 的 tools 換成本機假函式 |
| MCP 客戶端版本不合 | `ModuleNotFoundError: No module named 'mcp.shared.session'` 或 `ImportError: cannot import name 'SamplingCapability' from 'mcp'` | ADK 2.7.1 要 `mcp>=1.24,<2`；用 `uv add "google-adk[mcp]"` 讓它自己解，不要手動釘 mcp 版本 |
| `mode` 寫錯 | `ValidationError … mode Input should be 'chat', 'task' or 'single_turn'` | 底線不是連字號 |
| instruction 讀了沒人寫的 state | `KeyError: Context variable not found: \`xxx\`.` | 改 `{xxx?}` 或確認上游有 `output_key` 寫它 |
| `google_search` 混掛其他工具 | ADK 拒絕（P291） | 拆成獨立 sub-agent 或 `AgentTool` |
| 沒給預算就問旅館 | 工具回 `{"status":"error","message":"還不知道預算…請先呼叫 set_budget"}` | 刻意設計：讓模型回頭問使用者，而不是猜一個預算 |
| 預算低於最便宜房價 | 工具回 error 附 `cheapest` 與總價 | 模型照 message 說明差多少，這是 evalset 的 case3 |
| 城市不在假資料裡 | `{"status":"error","message":"沒有 冰島 的旅館資料，目前只有：東京、大阪、台北"}` | 讓模型講實話而不是編一間旅館 |
| eval 全掛但 exit code 0 | `Tests passed: 0 / Tests failed: 3`，`echo $?` 卻是 0 | CI 要 grep 輸出的 `Tests failed:`，不能只看 exit code |
| port 8080 被占 | `[Errno 48] error while attempting to bind on address ('0.0.0.0', 8080): address already in use` | `PORT=8099 MCP_TRANSPORT=http uv run server.py` 並同步改 `MCP_URL` |

## 9. 驗證方式

**離線可驗（實測通過）**

```bash
uv run travel_planner/agent.py --self-check
# → self-check ok（12 組 assert：假資料過濾、預算 state、委派接線與委派機制、instruction 佔位符）
```

12 組 assert 覆蓋：`max_price` 過濾與排序、從 `user:budget` 換算每晚上限、缺預算回 error、預算太低回 cheapest、未知城市、`set_budget` 寫的 key 帶 `user:` 前綴、主管的 sub_agents 名單與順序、**委派機制**（`_get_transfer_targets(root_agent) == []` 且三專員以 AgentTool 出現在 `root_agent.tools`）、`google_search` 獨占、三個 `mode` 值、writer/critic 的 `{placeholder}` 都有人寫、專員 description 不重疊。用 `types.SimpleNamespace(state={})` 假冒 `ToolContext`。

MCP 接線也能離線驗（只要 Lab 6 server 開著，不需要 API key）：

```bash
MCP_URL=http://localhost:8080/mcp uv run python -c "
import asyncio; from travel_planner.agent import weather_agent
print([t.name for t in asyncio.run(weather_agent.tools[0].get_tools())])"
# → ['get_weather']
```

evalset 的 JSON 結構也能離線驗（不呼叫模型）：

```bash
uv run python -c "
from google.adk.evaluation.eval_set import EvalSet
es = EvalSet.model_validate_json(open('tests/travel.evalset.json').read())
print(es.eval_set_id, [c.eval_id for c in es.eval_cases])"
```

**要 API key 才能驗（本文件未實測）**

> ⚠️ 未實測：`adk web` 的實際對話、Events 內容、`adk eval` 的 `Tests passed: 3`、最終驗收題的輸出——全部需要 `GOOGLE_API_KEY` 與網路。撰寫本文件時沒有 key，只驗到「沒 key 時噴 `ValueError: No API key was provided.`、summary 印 `Tests failed: 3`」。evalset 裡的 `tool_uses` 軌跡是照 ADK 的委派機制推的，**正式做法請照 P323 用 `adk web` 的 Eval 分頁錄製**，錄下來的軌跡才是這個模型版本真正走的路。

## 10. 已知限制與升級路徑

| 限制 | 現況 | 升級路徑 |
|---|---|---|
| `HOTELS` 是寫死的假資料 | 3 個城市共 8 間房 | 換成訂房 API；回傳格式（`status`/`hotels`/`total_twd`）不用改，模型端零改動 |
| `CITY_LATLON` 只有三個城市 | 表格外要模型自己推估經緯度 | 加一個 geocoding 工具，或 Lab 6 的 server 加 `geocode` |
| `SequentialAgent` 已被標 deprecated | ADK 2.7.1 會印 `DeprecationWarning: SequentialAgent is deprecated in favor of Workflow` | 等 `Workflow` 支援當 LlmAgent 的 sub-agent（deprecation 訊息說目前還不行）；或把主管也改成 Workflow 節點 |
| `InMemorySessionService` | `adk web` 預設，重啟就忘記 `user:budget` | `DatabaseSessionService(db_url="sqlite+aiosqlite:///./travel.db")`，Lab 8 換 Supabase（`postgresql+asyncpg`） |
| 沒有 guardrail | 使用者貼身分證字號也照收 | `before_model_callback` 擋輸入（P315） |
| 沒有 Memory | 換 session 只記得 `user:budget`，不記得聊過什麼 | `VertexAiMemoryBankService` + `after_agent_callback` 呼叫 `add_session_to_memory()`（Lab 10） |
| 主管靠 LLM 判斷派誰 | 確定性最低的一種 workflow | 需求收斂之後改 Graph `Workflow` + `Event(route=...)`，官方基準省 ~50% tokens |
| eval 門檻 `response_match_score: 0.5` | ROUGE 對中文長文很鬆 | 改用 `final_response_match_v2`（LLM 評審）或 rubric 品質指標 |
| `tool_trajectory_avg_score` 預設 `match_type=EXACT` | 連 args 都要一字不差；委派 call 的 `{"request": …}` 是模型生成的自由文字，手寫軌跡必掛 | 用 `adk web` 的 Eval 分頁錄；或 criteria 改 `{"threshold":1.0,"match_type":"IN_ORDER"}`（config 解析實測可行，比對行為未實測） |
