# Lab 6 SPEC：自建 MCP Server 接進 Antigravity

環境（實測基準，2026-08-26 本機）：`uv 0.12.3`、Python 3.13、`mcp[cli] 2.1.1`、`@modelcontextprotocol/inspector 2.3.0`、Node v26.7.0。

> ⚠️ 版本重點：投影片 p259 寫「官方 python-sdk（mcp 套件）v1.x 穩定」，但今天 `uv add "mcp[cli]"` 解到的是 **2.1.1**，`FastMCP` 已改名 `MCPServer`。本 Lab 以實際裝到的 2.x 為準，`pyproject.toml` 鎖 `mcp[cli]>=2,<3`（不鎖大版本，下一次改名會再炸一次）。要照投影片原文寫 `FastMCP` 就 `uv add "mcp[cli]<2"`（實測解到 1.29.1），兩種寫法差異見 §8。

## 1. 架構

```
┌──────────────────────── 你的機器 ────────────────────────┐
│                                                          │
│  Host（Antigravity / Claude Code / Inspector）           │
│    讀 ~/.gemini/config/mcp_config.json                   │
│    每台 server 配一個 MCP Client（1:1）                  │
│         │                                                │
│         │  ① stdio：spawn 子行程                         │
│         │     stdin  → JSON-RPC 2.0 請求                 │
│         │     stdout ← JSON-RPC 2.0 回應  ← 只有協定走這 │
│         │     stderr ← 你的 log         ← 人看的走這     │
│         ▼                                                │
│   ┌──────────────── server.py（子行程）────────────────┐ │
│   │ mcp = MCPServer("course-tools")                    │ │
│   │  @mcp.tool()      convert_currency  純運算         │ │
│   │  @mcp.tool()      get_weather ──── urllib ─────────┼─┼──→ api.open-meteo.com
│   │  @mcp.resource()  course://glossary/{term}         │ │   （免費、免 key）
│   │  @mcp.prompt()    daily_briefing                   │ │
│   └────────────────────────────────────────────────────┘ │
│                                                          │
│         │  ② streamable-http（加分題／Lab 10）           │
│         └─ POST http://127.0.0.1:8080/mcp（單一端點）    │
│            同一份 server.py，只換啟動參數                │
└──────────────────────────────────────────────────────────┘

驗收用的第二條路（不需要 host、不需要瀏覽器）：
  probe.py ──stdio──> uv run server.py     # 自己當 client，走真協定
  server.py --self-check                   # 連協定都不走，直接呼叫函式
```

資料流（步驟 5 的實戰測試，一句話兩個工具）：

```
使用者：「查台北現在天氣，順便把 100 美元換算成台幣」
  → host 開機時已做過 tools/list，把 2 個工具塞進模型的 function calling 清單
  → 模型決定 tools/call get_weather {lat:25.03, lon:121.56}
  → server 打 open-meteo → {"status":"success","temp_c":27.4,...}
  → 模型決定 tools/call convert_currency {amount:100}
  → server 純運算 → {"status":"success","twd":3200.0,...}
  → 模型把兩份結果合成一段中文回答
```

## 2. 元件與職責

| 元件 | 檔案／位置 | 職責 | 不負責 |
|---|---|---|---|
| MCP server | `server.py` | 宣告 tools／resource／prompt、參數防呆、呼叫外部 API、選 transport | 不管誰在呼叫、不管權限 |
| 協定層 | `mcp` 套件 | JSON-RPC 編解碼、schema 生成、錯誤包裝、stdio／HTTP 傳輸 | 不管你的商業邏輯 |
| Host | Antigravity（`mcp_config.json`） | 啟動子行程、tools/list、UX、**權限與 `disabledTools`** | 不管 server 內部怎麼實作 |
| Inspector | `uv run mcp dev server.py`（npx 起 node） | 人工手測 schema／呼叫／看原始回應 | 不能當自動化驗收 |
| 驗收 client | `probe.py` | 走真 stdio 驗三大 primitive，可貼進終端機、可放 CI | 不測 host 設定 |
| 離線檢查 | `server.py --self-check` | 驗工具函式的回傳與防呆，不連網 | 不驗協定層 |
| 外部 API | `api.open-meteo.com` | 即時天氣 | 匯率（本 Lab 匯率是參數，不查即時） |

## 3. 介面契約

### 3.1 Tools

```python
convert_currency(amount: float, rate: float = 32.0) -> dict
# 產生的 inputSchema（實測 tools/list 原文）：
# {"properties": {"amount": {"title": "Amount", "type": "number"},
#                 "rate": {"default": 32.0, "title": "Rate", "type": "number"}},
#  "required": ["amount"], "type": "object", "title": "convert_currencyArguments"}
# 回傳：{"status": "success", "usd": float, "twd": float, "rate": float}
# 錯誤：amount < 0 或 rate <= 0 → ToolError("amount 必須 >= 0，收到的是 -5.0")

get_weather(lat: float, lon: float) -> dict
# inputSchema：lat/lon 皆 number，required=["lat","lon"]
# 回傳：{"status": "success", "temp_c": float, "wind_kmh": float, "precipitation_mm": float}
# 錯誤：經緯度超界 → ToolError（連網前就擋）；上游失敗 → ToolError("open-meteo 查詢失敗（HTTPError: ...）")
```

工具的回傳 dict 會被 SDK 序列化成一個 text content block（JSON 字串）。**不要**加 `structured_output=True` 搭配 `-> dict`：實測直接在啟動時炸 `InvalidSignature: Function ...: return type <class 'dict'> is not serializable for structured output`；要結構化輸出得改用 TypedDict／pydantic model 當回傳型別。

### 3.2 Resource

```
URI 模板：course://glossary/{term}
讀取：resources/read → contents[0].text
term 支援 mcp / a2a / adk / skill / antigravity / grounding（大小寫與前後空白會被吃掉）
查不到 → 回「查無此名詞：xxx（可用：mcp、a2a、…）」而不是空字串或例外
```

### 3.3 Prompt

```
daily_briefing(city: str = "台北", usd: float = 100.0) -> str
→ 回一段引導模型「先 get_weather、再 convert_currency、最後三行摘要」的中文 prompt
→ host 端會出現在 slash 選單
```

### 3.4 Host 設定契約（Antigravity）

```json
{ "mcpServers": { "course-tools": {
    "command": "/opt/homebrew/bin/uv",
    "args": ["run", "--directory", "/絕對路徑/lab6", "server.py"],
    "env": {},
    "disabledTools": []
} } }
```

| 欄位 | 值 | 為什麼 |
|---|---|---|
| `command` | `uv` 的**絕對路徑**（`which uv`） | host 的 PATH 不等於你的 shell PATH，寫 `"uv"` 有機會 spawn 失敗 |
| `args` | `["run","--directory","<專案絕對路徑>","server.py"]` | `--directory` 讓 uv 找到 `pyproject.toml`／`.venv`，否則沒有相依環境 |
| `serverUrl` | 遠端才用（加分題 `http://127.0.0.1:8080/mcp`） | **Antigravity 叫 `serverUrl`，Claude／Cursor 叫 `url`**（p273／p462 坑④） |
| `disabledTools` | 工具名陣列 | host 端煞車，步驟 6 用它 |

### 3.5 Streamable HTTP（加分題／Lab 10）

```
POST http://127.0.0.1:8080/mcp
Content-Type: application/json
Accept: application/json, text/event-stream
{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}
→ 200 {"jsonrpc":"2.0","id":1,"result":{"tools":[{...inputSchema...}]}}
```

## 4. 資料模型

沒有 DB、沒有 session state。名詞表是模組層的 `GLOSSARY: dict[str, str]`，改了要重啟 server（host 端 Refresh）才生效。2026-07-28 規格本身也是無狀態的：沒有 `initialize` 握手、沒有 `Mcp-Session-Id`，所以 `stateless_http=True` 是 HTTP 模式的預設選擇。

## 5. 檔案結構

```
lab6/
├── server.py                # MCP server 本體：2 tools + 1 resource + 1 prompt + --self-check
├── probe.py                 # 驗收用 MCP client：spawn server.py 走真 stdio，驗三大 primitive
├── mcp_config.sample.json   # Antigravity mcp_config.json 範本（stdio ＋ serverUrl 兩種都給）
├── pyproject.toml           # uv 產生；相依只有 mcp[cli]>=2,<3
├── uv.lock                  # 鎖版本（p271 防護清單：鎖定版本、看 lockfile）
├── PRD.md / SPEC.md / walkthrough.md
└── .venv/                   # uv 自動建立，別 commit
```

## 6. 環境變數與設定

| 變數 | 用途 | 從哪來 | 預設 |
|---|---|---|---|
| `MCP_TRANSPORT` | `http` → streamable-http；其他（含未設）→ stdio | 你自己 export，或 host 設定的 `env` | 未設＝stdio |
| `PORT` | HTTP 模式綁的埠 | Cloud Run 會自動注入（p260 慣例，Lab 10 直接沿用） | `8080` |
| — | 本 Lab **不需要** 任何 API key | — | — |

`host` 在 HTTP 模式固定 `0.0.0.0`：容器內綁 `127.0.0.1` 的話 Cloud Run 的流量進不來（Lab 10 會踩）。本機測試完記得關掉。

## 7. 執行流程

```bash
# 0) 建專案
mkdir -p lab6 && cd lab6
uv init --bare --name lab6-mcp
uv add "mcp[cli]>=2,<3"

# 1) 離線檢查（不連網、不起 server）
uv run server.py --self-check          # → self-check OK

# 2) 走真協定的檢查（自己當 client）
uv run probe.py                        # → probe OK（會打一次 open-meteo）
uv run probe.py --offline              # → 完全不連網

# 3) Inspector 手測
uv run mcp dev server.py               # 開它印出來的帶 token 的 URL

# 4) 接 host
which uv                               # 拿絕對路徑填進設定檔
cp mcp_config.sample.json ~/.gemini/config/mcp_config.json   # 已有檔案就合併，不要覆蓋
#   Antigravity → MCP 面板 → Refresh

# 5) 加分題：HTTP 模式
MCP_TRANSPORT=http PORT=8080 uv run server.py
curl -sS -X POST http://127.0.0.1:8080/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'
```

## 8. 錯誤處理與邊界

| 情境 | 症狀（實測原文） | 處理方式 |
|---|---|---|
| 照投影片寫 `from mcp.server.fastmcp import FastMCP`，但裝到 2.x | `ModuleNotFoundError: No module named 'mcp.server.fastmcp'. This is mcp 2.x, where FastMCP was renamed to MCPServer (from mcp.server.mcpserver import MCPServer) …` | 改 `MCPServer`，或 `uv add "mcp[cli]<2"` 鎖 v1 |
| 2.x 照投影片 p260 寫 `MCPServer("x", json_response=True)` | `TypeError: MCPServer.__init__() got an unexpected keyword argument 'json_response'` | 2.x 的 `json_response` 移到 `mcp.run(...)` 的 kwargs |
| 1.x 照投影片 p260 寫 `mcp.run(transport="streamable-http", host=..., port=...)` | `TypeError: FastMCP.run() got an unexpected keyword argument 'host'` | 1.x 要 `FastMCP("x", host=..., port=...)` 放建構子；2.x 才能放 `run()` |
| stdio 模式用 `print()` 除錯（mcp 2.x） | 連線不死：SDK 服務期間把 fd 1 轉去 stderr、fd 0 轉去 `/dev/null`（`mcp/server/stdio.py` 的 `stdio_server()`）。但行程收尾才 flush 的緩衝內容會真的上線 → client 端 `Failed to parse JSONRPC message from server` ＋ `ValidationError: … Invalid JSON: expected value at line 1 column 1 [type=json_invalid, input_value='DEBUG amount= 100.0', …]` | log 一律 `print(..., file=sys.stderr)` 或 `logging`；別靠 SDK 的護欄 |
| stdio 模式用 `print()` 除錯（mcp 1.x） | 沒有護欄，**呼叫進行中**就噴同一個 `ValidationError`（實測 1.29.1：`input_value='DEBUG 1.0'`） | 同上。這才是投影片 p260／p462 坑⑤ 描述的版本 |
| 工具裡讀 stdin | `sys.stdin.read(5)` 回 `''`（EOF，實測）—— fd 0 被指到 `/dev/null` | 工具不要跟使用者互動；反問是 elicitation 的事（p254） |
| 工具沒寫型別註記 | 不報錯，但 schema 變成 `{"amount": {"type": "string"}}`、`description` 是 `''`；模型傳字串進來，`amount*rate` 炸掉 | 每個參數都標型別、每個工具都寫 docstring |
| 工具內部 raise 非 `ToolError` 的例外 | 模型只看到 `Error executing tool get_weather`，**訊息被留在 server 端** | 預期得到的失敗一律 `raise ToolError("怎麼修")`（修正投影片 p259「raise 例外會回報訊息給模型」） |
| server 物件變數不叫 `mcp`／`server`／`app` | `No server object found in server.py. Please either: 1. Use a standard variable name (mcp, server, or app) 2. Specify the object name with file:object syntax…` | 變數命名為 `mcp`，或用 `mcp dev server.py:srv` |
| host 設定用 `"command": "python"` | server 起不來，log 是 `ModuleNotFoundError: No module named 'mcp'` | 用 `uv run --directory <專案> server.py` |
| Antigravity 遠端設定寫 `url` | server 一直是離線／不出現 | 欄位名是 `serverUrl`（p462 坑④） |
| 上游 API 掛掉／網路不通 | `ToolError("open-meteo 查詢失敗（URLError: …）")` | 已包起來；模型會轉述而不是硬掰數字 |
| 經緯度寫反（`lat=121.56`） | `ToolError("lat 必須在 -90~90 之間，收到的是 121.56（別把經緯度寫反）")` | 連網前先驗參數，省一次往返 |
| 改了程式碼但 host 還是舊行為 | 工具清單／行為沒變 | host 端 Refresh（子行程要重啟才會重新載入） |

## 9. 驗證方式

| 層次 | 指令 | 驗什麼 | 需要什麼 |
|---|---|---|---|
| 函式邏輯 | `uv run server.py --self-check` | 匯率計算、防呆分支、天氣 JSON 解析（用 `SimpleNamespace` 假 response）、名詞表大小寫 | 不連網 |
| 協定層 | `uv run probe.py --offline` | tools/list 的 description 非空、參數型別不是 string、`tools/call` 成功與 `is_error` 兩條路、resource 模板、prompt 參數 | 不連網 |
| 真 API | `uv run probe.py` | `get_weather` 真的打得到 open-meteo | 網路 |
| HTTP transport | `curl -X POST …/mcp`（見 §7） | 同一份 server 換 transport 後 `tools/list` 一樣 | 網路（本機） |
| 人工手測 | `uv run mcp dev server.py` | schema 長相、原始回應、Resources／Prompts 頁 | Node ≥ 20、瀏覽器 |
| host 整合 | Antigravity MCP 面板 ＋ 步驟 5 的實戰 prompt | 工具出現、agent 會串兩個工具、`disabledTools` 生效 | Antigravity（**無法離線自動驗**） |

**沒辦法離線驗的**：Antigravity 的 UI 面板、Refresh 行為、`disabledTools` 的實際擋法、agent 串工具的自然語言行為、用 `serverUrl` 重接 host 的那一側、Inspector 頁面內的手動點擊 —— 這些在 walkthrough 裡都標了 `> ⚠️ 未實測`。已用真協定驗過的是 stdio 與 streamable-http 兩條路本身，host 只是這兩條路的另一端。

## 10. 已知限制與升級路徑

| 限制 | 現況 | 升級路徑 |
|---|---|---|
| `# ponytail: 同步阻塞 I/O` | `get_weather` 是 `def` 不是 `async def`；SDK 會把同步工具丟到 worker thread（實測 `func_metadata.call_fn`：`anyio.to_thread.run_sync`），單人用沒差 | 要並發打多個 API 就改 `async def` ＋ `httpx.AsyncClient`（投影片 p263 的寫法） |
| 匯率是參數不是即時 | `rate` 預設 32.0，docstring 已告知模型「本工具不查即時匯率」 | 加第三個工具打匯率 API；或把 rate 做成 resource 讓 host 快取 |
| 回傳沒有 output schema | `-> dict` 只產生 text content block，`structured_content` 是 `None` | 回傳型別改 TypedDict／pydantic model 並開 `structured_output=True` |
| 名詞表寫死在程式裡 | 改內容要重啟 server | 換成讀 JSON 檔或接 Lab 8 的 Supabase |
| 沒有認證 | stdio 靠行程邊界；HTTP 模式綁 `0.0.0.0` 且**無認證** | Lab 10 上 Cloud Run 時關掉公開存取，走 IAM ＋ ID token（p458 `gcloud auth print-identity-token`） |
| 沒有稽核 log | 只有 SDK 的預設 log | p271 要求自建 server 記錄每次 `tools/call` 的參數與來源：加一行 `logging` 寫進 stderr／檔案 |
| 版本鎖到 `<3` | 大版本改名會炸（這次 1.x→2.x 就是） | 每季跑一次 `uv lock --upgrade` ＋ `uv run probe.py`（p466 建議把 Lab 6 當金絲雀） |
