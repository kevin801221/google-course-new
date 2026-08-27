# Lab 9 SPEC：跨服務 Agent 協作（A2A）

驗證環境：`google-adk 2.7.1`、`a2a-sdk 1.1.2`、Python 3.13、macOS。以下所有欄位名與錯誤訊息都是在這個組合上實際跑出來的。

## 1. 架構

```
    你的瀏覽器
        │  http://localhost:8000（adk web UI）
        ▼
┌───────────────────────────────────────────┐   行程 A（終端機分頁 1）
│ 服務 A：concierge          uv run adk web │   $ cd lab9 && uv run adk web
│                                           │
│  root_agent = Agent(name="concierge")     │
│    model  gemini-3.7-flash  ← 要 API key  │
│    sub_agents=[ hotel_agent ]             │
│                    │                      │
│                    ▼                      │
│  RemoteA2aAgent(name="hotel_agent")       │
│    agent_card = $HOTEL_SERVICE_URL        │
│                 + AGENT_CARD_WELL_KNOWN…  │
└──────────┬────────────────────────────────┘
           │ ① GET /.well-known/agent-card.json      （第一次 invocation 解析後就快取）
           │ ② origin 檢查：名片上的 RPC url 必須與 ① 的 origin 完全相同
           │ ③ POST /  JSON-RPC SendMessage
           │ ④ ← Task(SUBMITTED) → TaskStatusUpdate(WORKING) → TaskArtifactUpdate → COMPLETED
           ▼
┌───────────────────────────────────────────┐   行程 B（終端機分頁 2）
│ 服務 B：hotel_service                     │   $ uv run uvicorn \
│   a2a_app = to_a2a(root_agent, port=8001) │       hotel_service.agent:a2a_app --port 8001
│   （Starlette ASGI app）                  │
│                                           │
│   路由（在 lifespan startup 才掛上）：     │
│     GET  /.well-known/agent-card.json     │
│     POST /                （JSON-RPC）    │
│                                           │
│   A2aAgentExecutor → ADK Runner           │
│     root_agent = Agent(name="hotel_agent")│
│       model  gemini-3.7-flash ← 要 API key│
│       tools=[ search_hotels ]  ← 假資料   │
│       InMemory{Session,Artifact,Memory}   │
│       InMemoryTaskStore                   │
└───────────────────────────────────────────┘

離線驗證路徑（不用 key、不連網）：

  smoke_test.py
    ├─ 背景 thread 起「假訂房服務」:8099（純 a2a-sdk，AgentExecutor 回罐頭字串，無 LLM）
    └─ RemoteA2aAgent ──①②③④──▶ 假服務      ← 走完全一樣的協定路徑
         └─ ADK Runner（agent=遠端 agent 本身，所以完全不呼叫 LLM）

  check_card.py（只用標準庫）
    └─ GET 名片 → 列 skills → 自己重跑一遍 ② 的 origin 檢查 → exit 0/1
```

程序邊界就是 `③` 那條線。左邊看不到右邊的 Python 物件，只看得到 JSON。

## 2. 元件與職責

| 元件 | 檔案 | 職責 | 需要 API key |
|---|---|---|---|
| `search_hotels` | `hotel_service/agent.py` | 純函式：依城市＋預算過濾 `HOTELS`，由便宜到貴排序。`HOTEL_SLOW_SECONDS` 可讓它變慢 | 否 |
| `hotel_agent`（root_agent B） | `hotel_service/agent.py` | ADK LlmAgent，決定何時呼叫 `search_hotels` 並整理成人話 | 是 |
| `a2a_app` | `hotel_service/agent.py` | `to_a2a()` 產出的 Starlette ASGI app，被 uvicorn 掛起來 | 否（建立時） |
| `_card(port)` | `hotel_service/agent.py` | 用 `AgentCardBuilder` 生一張 `capabilities.streaming=true` 的名片（自動名片是 `false`） | 否 |
| `hotel_agent`（remote） | `concierge/agent.py` | `RemoteA2aAgent`：名片解析、httpx client、A2A ↔ ADK event 轉換 | 否 |
| `concierge`（root_agent A） | `concierge/agent.py` | ADK LlmAgent，判斷是否委派給 `hotel_agent` | 是 |
| `card_url()` | `concierge/agent.py` | base URL 接 well-known 路徑，吃掉多餘斜線 | 否 |
| `check_card.py` | 同名 | 標準庫工具：抓名片、列 skills、預跑 origin 檢查、非零 exit | 否 |
| `smoke_test.py` | 同名 | 假 A2A 服務 ＋ 端到端跑一遍 ＋ assert 罐頭答案 | 否 |

## 3. 介面契約

### 3.1 Python 函式簽章（實際驗證過的）

```python
# google.adk.a2a.utils.agent_to_a2a
def to_a2a(agent, *, host="localhost", port=8000, protocol="http",
           rpc_path="", agent_card: AgentCard | str | None = None,
           push_config_store=None, task_store=None, runner=None,
           lifespan=None, agent_executor_factory=None) -> starlette.applications.Starlette
```
- `host`／`port`／`protocol` **只決定名片上寫的 RPC URL**，不會叫任何人去 listen。listen 的是 uvicorn。
- 回傳的 app 在 import 時 `len(app.routes) == 0`；路由是在 lifespan startup 才 `attach_a2a_routes_to_app()` 掛上去的。

```python
# google.adk.agents.remote_a2a_agent
class RemoteA2aAgent(BaseAgent):
    def __init__(self, name: str, agent_card: AgentCard | str, *,
                 description: str = "", httpx_client=None,
                 timeout: float = DEFAULT_TIMEOUT,   # DEFAULT_TIMEOUT = 600.0
                 a2a_client_factory=None, full_history_when_stateless=False,
                 config=None, use_legacy=True, **kwargs) -> None
                 # 這裡略掉三個本 Lab 沒用到的參數：genai_part_converter /
                 # a2a_part_converter / a2a_request_meta_provider
    async def cleanup(self) -> None      # 關掉自己建的 httpx client

AGENT_CARD_WELL_KNOWN_PATH = "/.well-known/agent-card.json"
```

### 3.2 工具 schema（服務 B 對外的能力）

```python
def search_hotels(city: str, max_price: int) -> dict
# 回傳 {"city": str, "max_price": int, "count": int,
#       "hotels": [{"name","city","price","rating","breakfast"}, ...]}
```
docstring 的第一行會被抄進 agent card 的 skill description，**連 `Args:` 那幾行都會抄進去**——名片是公開文件，docstring 寫得爛等於對外文件寫得爛。

### 3.3 HTTP 端點（服務 B）

| 方法 | 路徑 | 用途 | 實測 |
|---|---|---|---|
| GET | `/.well-known/agent-card.json` | Agent Card 發現 | 200 |
| POST | `/` | JSON-RPC：`SendMessage` / `SendStreamingMessage` / `GetTask` / `CancelTask` … | 200（`smoke_test.py` 走過） |

### 3.4 Agent Card JSON（`to_a2a` 自動生成，實測輸出）

```json
{
  "name": "hotel_agent",
  "description": "訂房專員：依城市與每晚預算搜尋旅館、比價並給推薦。",
  "supportedInterfaces": [
    { "url": "http://localhost:8001", "protocolBinding": "JSONRPC", "protocolVersion": "1.0" }
  ],
  "version": "0.0.1",
  "capabilities": { "streaming": false, "pushNotifications": false },
  "defaultInputModes": ["text/plain"],
  "defaultOutputModes": ["text/plain"],
  "skills": [
    { "id": "hotel_agent", "name": "model", "description": "<agent.description>", "tags": ["llm"] },
    { "id": "hotel_agent-search_hotels", "name": "search_hotels",
      "description": "<工具 docstring>", "tags": ["llm", "tools"] }
  ]
}
```

**四個容易寫錯的地方**

1. **JSON 是 camelCase**（`supportedInterfaces`、`defaultInputModes`、`pushNotifications`），投影片 370 的範例用 snake_case——那是 Python 的欄位名。抓下來當 dict 讀請用 camelCase，否則 `KeyError: 'supported_interfaces'`。
2. `version` 固定 `"0.0.1"`（`AgentCardBuilder` 的預設值），不是你的專案版本。
3. `capabilities.streaming` 是 **`false`**。要 `true` 得自己傳 `agent_card=`（本 Lab 的 `A2A_STREAMING=1`）。
4. proto3 的 `false` 欄位可能整個不出現在 JSON 裡（自訂名片那版就沒有 `pushNotifications`）。讀的時候一律 `.get(key, False)`。

### 3.5 客戶端的 origin 契約（ADK 強制執行，這是本 Lab 最大的坑）

`RemoteA2aAgent._validate_card_rpc_targets()` 對名片上**每一個** RPC URL 檢查兩件事：

| 規則 | 不合就噴 |
|---|---|
| scheme 是 `https`，或 host 是 loopback（`localhost` / `*.localhost` / `127.0.0.0/8` / `::1`）才准用 http | `Agent card RPC URL must use https, or http on a loopback host: <url>` |
| `(scheme, hostname, port)` 必須與「抓到名片的那個 URL」完全相同 | `Agent card RPC URL must have the same origin as the location the card was fetched from (<來源>): <名片上的 url>` |

推論：`localhost` 與 `127.0.0.1` 是**不同的 origin**，即使它們指向同一台機器。`to_a2a` 預設 `host="localhost"`，所以客戶端也只能用 `localhost`。

### 3.6 事件型別（穿過 `③` 那條線的東西）

A2A 端（投影片 373、381）：`Task`、`Message`、`TaskStatusUpdateEvent`、`TaskArtifactUpdateEvent`。
Task 狀態（`a2a.types.TaskState`，protobuf enum，實測 keys）：
`TASK_STATE_UNSPECIFIED / SUBMITTED / WORKING / COMPLETED / FAILED / CANCELED / INPUT_REQUIRED / REJECTED / AUTH_REQUIRED`。

ADK 端：`RemoteA2aAgent` 把上面那些轉成 ADK `Event`。實測 `smoke_test.py` 一輪拿到 3 個 event（`WORKING` 的 status message 文字、artifact 文字、一個空的）。**status 事件沒有 `content`**，所以任何取文字的程式碼都要能吃 `content is None`。

## 4. 資料模型

沒有資料庫。三個記憶體狀態：

| 狀態 | 存在哪 | 生命週期 | key |
|---|---|---|---|
| `HOTELS` | `hotel_service/agent.py` 模組常數 | 永久（寫死） | `name` / `city` / `price` / `rating` / `breakfast` |
| A2A task | `InMemoryTaskStore`（`to_a2a` 預設） | 服務 B 行程存活期間 | `task.id`、`task.context_id` |
| ADK session | `InMemorySessionService`（兩邊各一份） | 各自行程存活期間 | `app_name` / `user_id` / `session_id` |

**兩邊的 session 是分開的**：服務 A 的 concierge session 與服務 B 的 hotel_agent session 沒有共用記憶。跨 task 的脈絡靠 A2A 的 `contextId`（投影片 372 第 4 點）串，不是靠 ADK session。

## 5. 檔案結構

```
lab9/
├── pyproject.toml               uv 專案：google-adk[a2a] + a2a-sdk[http-server]
├── uv.lock                      鎖定版本（adk 2.7.1 / a2a-sdk 1.1.2）
├── hotel_service/               ── 服務 B：被呼叫的那個
│   ├── __init__.py              空檔，讓 uvicorn 找得到 hotel_service.agent
│   ├── agent.py                 search_hotels + hotel_agent + a2a_app（含 --self-check）
│   └── .env.example             GOOGLE_API_KEY / HOTEL_SLOW_SECONDS / A2A_STREAMING
├── concierge/                   ── 服務 A：發起呼叫的那個
│   ├── __init__.py              空檔，讓 adk web 認得這是一個 agent 目錄
│   ├── agent.py                 RemoteA2aAgent + concierge root_agent（含 --self-check）
│   └── .env.example             GOOGLE_API_KEY / HOTEL_SERVICE_URL
├── check_card.py                名片檢查工具，只用標準庫（含 --self-check）
├── smoke_test.py                假 A2A 服務 + 端到端驗證（含 --self-check）
├── PRD.md / SPEC.md / walkthrough.md
```

`adk web` 應該會把 `hotel_service` 與 `concierge` **兩個**都列成可選 agent（兩邊都有 `root_agent`）。

> ⚠️ 未實測：我沒開過 UI，這是從「ADK 掃當前目錄下有 `root_agent` 的資料夾」推的。
步驟 4 要選 `concierge`；選到 `hotel_service` 你會發現它自己就能答旅館問題，完全沒有跨服務——那不是這個 Lab 要看的東西。

## 6. 環境變數與設定

| 變數 | 用途 | 從哪來 | 預設 |
|---|---|---|---|
| `GOOGLE_API_KEY` | 兩邊的 `gemini-3.7-flash` 都要 | <https://aistudio.google.com/apikey> | 無。缺了步驟 4／5 跑不動，離線驗收不受影響 |
| `GOOGLE_GENAI_USE_ENTERPRISE` | `0` = 用 AI Studio key；`TRUE` = 走 Vertex | 附錄 C（2025 叫 `GOOGLE_GENAI_USE_VERTEXAI`） | `0` |
| `A2A_PORT` | 寫進**名片**的 port。必須與 `uvicorn --port` 一致 | 你自己 | `8001` |
| `HOTEL_SLOW_SECONDS` | `search_hotels` 睡幾秒（步驟 5） | 你自己 | `0` |
| `A2A_STREAMING` | `1` = 換成宣告 `streaming=true` 的自訂名片 | 你自己 | 未設（用自動名片，`streaming=false`） |
| `HOTEL_SERVICE_URL` | 服務 A 去哪抓名片 | 你自己 | `http://localhost:8001` |
| `SMOKE_PORT` | `smoke_test.py` 假服務的 port（被別的 lab 佔住時改） | 你自己 | `8099` |
| `ADK_SUPPRESS_A2A_EXPERIMENTAL_FEATURE_WARNINGS` | `1` = 關掉 `[EXPERIMENTAL]` 警告轟炸 | ADK 原始碼的 `bypass_env_var` | 未設 |

ADK 會自動讀 agent 目錄下的 `.env`（`hotel_service/.env`、`concierge/.env`）。`.env.example` 各複製一份改名即可。

## 7. 執行流程

```bash
# ── 一次性 ──────────────────────────────────────────
cd /Users/awesomeartengineer01/Antigravity-teach/lab9      # 或你自己的路徑
uv init --bare --name lab9 --python 3.13                   # 已經有 pyproject.toml 就跳過
uv add "google-adk[a2a]" "a2a-sdk[http-server]"
cp hotel_service/.env.example hotel_service/.env && $EDITOR hotel_service/.env
cp concierge/.env.example     concierge/.env     && $EDITOR concierge/.env

# ── 離線驗收（不用 key、不連網）─────────────────────
uv run hotel_service/agent.py --self-check
uv run concierge/agent.py --self-check
uv run check_card.py --self-check
uv run smoke_test.py --self-check
uv run smoke_test.py                                       # 端到端，最後一行 smoke ok

# ── 分頁 1：服務 B ──────────────────────────────────
export ADK_SUPPRESS_A2A_EXPERIMENTAL_FEATURE_WARNINGS=1
uv run uvicorn hotel_service.agent:a2a_app --port 8001

# ── 分頁 2：驗名片 ──────────────────────────────────
uv run check_card.py                                       # ✓ 名片可用
uv run check_card.py http://127.0.0.1:8001                 # ✗ origin 不一致（故意的）
curl -s http://localhost:8001/.well-known/agent-card.json | python3 -m json.tool

# ── 分頁 2：服務 A ──────────────────────────────────
uv run adk web                                             # 開 http://localhost:8000，選 concierge

# ── 步驟 5：慢查詢 ──────────────────────────────────
# 分頁 1 Ctrl-C，然後：
HOTEL_SLOW_SECONDS=6 A2A_STREAMING=1 \
  uv run uvicorn hotel_service.agent:a2a_app --port 8001
# 分頁 2 的 adk web 也要重啟：名片解析結果有快取（見 8. 錯誤處理表）
```

## 8. 錯誤處理與邊界

| 情境 | 症狀（原文） | 處理方式 |
|---|---|---|
| 只裝了 `google-adk`，沒有 `[a2a]` extra | `ModuleNotFoundError: No module named 'a2a'` | `uv add "google-adk[a2a]"` |
| 有 `[a2a]` 但沒有 `a2a-sdk[http-server]` | uvicorn **startup 階段**噴 `ModuleNotFoundError: No module named 'sse_starlette'` 然後 `ERROR: Application startup failed. Exiting.`（行程結束，curl 是 connection refused 不是 404）；`to_a2a()` 本身不會報錯（`len(app.routes)==0`） | `uv add "a2a-sdk[http-server]"` |
| 服務 B 沒起來 | `Failed to resolve AgentCard from URL http://localhost:8001/.well-known/agent-card.json: Network communication error fetching agent card from ...: All connection attempts failed` | 起服務 B；`check_card.py` 會先講人話 |
| `A2A_PORT` 與 `--port` 不一致 | `Agent card RPC URL must have the same origin as the location the card was fetched from (...)` | 兩邊改成同一個數字 |
| 客戶端用 `127.0.0.1`、名片寫 `localhost` | 同上 | 一律用 `localhost`（或 `to_a2a(host="127.0.0.1")` 兩邊都改） |
| 上雲後名片寫 http | `Agent card RPC URL must use https, or http on a loopback host: http://...` | `to_a2a(host=<網域>, protocol="https")`（M10） |
| 8001 被佔 | `ERROR: [Errno 48] error while attempting to bind on address ('127.0.0.1', 8001): [errno 48] address already in use` | `pkill -f "uvicorn hotel_service"` 或換 port（**名片與 `--port` 一起改**） |
| 遠端掛掉／變慢 | 服務 A 傻等 | `RemoteA2aAgent(timeout=30.0)`；預設是 **600 秒** |
| 名片解析失敗（任何原因） | ADK **不會拋出例外到 adk web**，而是 log 一行 `ERROR ... Failed to resolve remote A2A agent hotel_agent: <原因>` 並吐一個空 event | 看服務 A 的終端機 log，不要只看 UI |
| 改了服務 B 的名片（例如加 `A2A_STREAMING=1`）但服務 A 沒重啟 | 還是舊行為。`RemoteA2aAgent._ensure_resolved()` 解析成功後把 card 與 client 存在 `self._is_resolved`／`self._a2a_client`，**不會每輪重抓**（只有設了 `card_request_interceptors` 才 per-invocation 解析） | 名片改了就把 `adk web`（服務 A）也重啟 |
| status 事件沒有 content | 取文字時 `AttributeError` / `TypeError: 'NoneType' object is not iterable` | `getattr(...) or []`（`smoke_test.text_of()` 的做法） |
| root_agent 不肯委派 | 自己編了一堆假旅館 | `RemoteA2aAgent` 的 `description` 要寫清楚做什麼；root 的 `instruction` 明寫「不要自己編價格」 |
| `[EXPERIMENTAL]` 警告蓋掉輸出 | `UserWarning: [EXPERIMENTAL] to_a2a: ADK Implementation for A2A support ...` | `export ADK_SUPPRESS_A2A_EXPERIMENTAL_FEATURE_WARNINGS=1` |

## 9. 驗證方式

**實測通過（在本機真的跑過）**

| 指令 | 實際輸出 |
|---|---|
| `uv run hotel_service/agent.py --self-check` | `self-check ok` |
| `uv run concierge/agent.py --self-check` | `self-check ok` |
| `uv run check_card.py --self-check` | 印一張假名片報告 ＋ `self-check ok` |
| `uv run smoke_test.py --self-check` | `self-check ok` |
| `uv run smoke_test.py` | `搜尋中…` / `淺草和風旅館 2400 TWD` / `smoke ok（3 個 event，罐頭答案有回來）` |
| `uv run uvicorn hotel_service.agent:a2a_app --port 8001` ＋ `uv run check_card.py` | 列出 2 個 skill ＋ `✓ 名片可用`，exit 0 |
| `uv run check_card.py http://127.0.0.1:8001` | `✗ origin 不一致…` ＋ exit 1 |
| `curl -s http://localhost:8001/.well-known/agent-card.json` | 上面 3.4 那份 JSON |
| `A2A_STREAMING=1 … uvicorn …` ＋ `uv run check_card.py \| grep streaming` | `streaming True   push False`（自訂名片那條路真的改到 `capabilities`） |
| 把 `smoke_test.py` 假名片的 `AgentCapabilities(streaming=True)` 改成 `False` 再跑 | `搜尋中…` 消失、`smoke ok（1 個 event…）`（原本 3 個）——名片一個布林值決定客戶端走不走 SSE |
| `curl -s -o /dev/null -w %{http_code} http://localhost:8001//.well-known/agent-card.json` | `404`（多一個斜線就打不到路由，所以 `card_url()` 要 `rstrip("/")`） |

streaming 那條的機制在 a2a-sdk 客戶端 `a2a/client/base_client.py`：`if not self._config.streaming or not self._card.capabilities.streaming:` —— 兩邊都 true 才走 `send_message_streaming`，否則退回一次性 `SendMessage`。

`smoke_test.py` 是**唯一一個真的把 A2A 協定跑完整圈**的離線驗證：名片發現 → origin 檢查 → JSON-RPC `SendMessage` → `WORKING` → artifact → `COMPLETED` → 轉成 ADK event。它不呼叫 LLM，因為 `Runner(agent=<RemoteA2aAgent>)` 的 agent 本身就是轉發器；LLM 只在「有 root LlmAgent 決定要不要委派」時才登場。

**沒辦法離線驗的**

> ⚠️ 未實測：`adk web` 的 UI 操作與 Events 面板（步驟 4）。需要 API key，我沒有。
> ⚠️ 未實測：真的 `hotel_agent`（帶 LLM 的服務 B）回應內容與 `HOTEL_SLOW_SECONDS` 下的 `WORKING` 串流表現（步驟 5）。需要 API key。
> ⚠️ 未實測：`adk web` 是否同時列出 `hotel_service` 與 `concierge`。這是從「兩個目錄都有 `root_agent`」推論的，我沒開過 UI。
> ⚠️ 未實測：加分題（步驟 6）的純 a2a-sdk 第三方 agent 被 ADK 消費——不過 `smoke_test.py` 的假服務就是純 a2a-sdk 寫的、也真的被 `RemoteA2aAgent` 呼通了，所以跨框架互通這件事**已經間接驗過**。

## 10. 已知限制與升級路徑

| 程式碼位置 | `ponytail:` 註解 | 天花板 | 升級路徑 |
|---|---|---|---|
| `hotel_service/agent.py` `HOTELS` | 旅館資料寫死 | 6 筆假資料、2 個城市 | 換成 Lab 8 的 `McpToolset`（MCP Toolbox + Supabase），`tools=` 那一行以外都不用改 |
| `smoke_test.py` `serving()` | 輪詢等 server 起來 | 最多等 10 秒 | 改用 `uvicorn.Server.started` 事件 |
| `to_a2a` 預設 | `InMemoryTaskStore` | 重啟服務 B 就忘記所有 task | `task_store=DatabaseTaskStore(engine=...)` ＋ `lifespan=` 收 engine（`to_a2a` docstring 有範例） |
| `to_a2a(host="localhost")` | 只綁本機 | 外部連不到，且非 loopback 的 http 會被客戶端擋 | `to_a2a(host=<Cloud Run 網域>, protocol="https")`（Lab 10） |
| 無認證 | loopback 純 http | 誰都能呼叫 | Agent Card 宣告 security schemes；Cloud Run 用 IAM ID token（`audience` 必須全等於服務 URL，附錄 D ⑦） |
| `A2A_STREAMING` 二選一 | 只有「自動名片」與「streaming 名片」兩種 | 不能細調 provider／security schemes | 直接自己組 `AgentCard(...)` 傳給 `to_a2a(agent_card=...)`（投影片 376 的寫法） |
| 沒有 `INPUT_REQUIRED` | 遠端不會反問 | 少了 A2A 與工具最本質的差異 | `TaskState.TASK_STATE_INPUT_REQUIRED` ＋ HITL 迴圈（Capstone） |
