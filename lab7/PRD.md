# Lab 7 PRD：多 Agent 旅遊助理

## 1. 這個 Lab 要解決什麼問題

前面六個 Lab 累積出的能力是散的：M1 會呼叫模型、M6 有一台自己的 MCP server，但「一支腳本掛十個工具」在真實需求前會崩——模型工具選錯、狀態記不住、改壞了沒人知道。這個 Lab 用 ADK 2.x 把散件組成一個系統：三個各司其職的專員 agent、一個只負責派工的主管、一段確定性的 writer→critic pipeline、一個跨 session 的預算 state，最後用 evalset 把「它到底有沒有變笨」變成可以跑的指令。做完你手上是一個能上雲（Lab 10）的 agent app，而不是一支 demo 腳本。

## 2. 學習目標

做完學生會：

1. **拆**出符合 ADK 慣例的 multi-agent 專案骨架（`adk create` → `agent.py` 定義 `root_agent` → 一個目錄一個 app）。
2. **寫**出讓主管派對人的 `description`，並用 `adk web` 的 Events 看出主管把哪一題派給了哪個專員（`mode` 決定委派是 `transfer_to_agent` 還是以專員命名的 function call）——說得出委派其實只是一個參數叫 `request` 的 function call，不是一個協調器。
3. **接**Lab 6 的 MCP server 當 agent 工具（`McpToolset` + `StreamableHTTPConnectionParams` + `tool_filter` 白名單），並看出本地 python 函式與遠端 MCP tool 在模型眼裡是同一份 `FunctionDeclaration`——這條線往下是 Lab 9 的 A2A skill、Lab 10 的 Cloud Run 端點。
4. **用**`user:` 前綴 state 在工具內讀寫跨 session 的使用者偏好（`tool_context.state["user:budget"]`），並分得出四種前綴（無／`user:`／`app:`／`temp:`）各自的保存期限。
5. **組**一段 `SequentialAgent`（writer→critic），並用 `output_key` / `{placeholder}` 讓資料在 state 上流動。
6. **跑**`adk eval` 把三個案例（含一個預算超標 edge case）變成 agent 的回歸測試。

## 3. 使用者故事

- 身為學生，我想**看到主管把問題丟給哪個專員**，以便知道 agent 不聽話時該修 instruction 還是修 description。
- 身為學生，我想**把 Lab 6 自己寫的 MCP server 接進 agent**，以便確認 M6 和 M7 是同一條路而不是兩堂沒關係的課。
- 身為學生，我想**讓 agent 記得我的預算**，以便理解 session state 的前綴作用域到底差在哪。
- 身為學生，我想**在改 instruction 之後跑一條指令就知道有沒有退步**，以便不用每次手動聊十輪。
- 身為講師，我想**有一個不需要 API key 也能驗證的離線檢查**，以便學生沒 key 或配額用完時課還能繼續上。

## 4. 功能需求

| 編號 | 需求 | 對應投影片步驟 | 必要／加分 |
|---|---|---|---|
| FR-1 | 用 `uv run adk create travel_planner` 產生骨架；`.env` 走 Developer API 路線（`GOOGLE_API_KEY`） | P326 步驟 1 | 必要 |
| FR-2 | `search_agent`：`tools=[google_search]`，且 google_search 是它唯一的工具 | P326 步驟 2 ／ P290-291 | 必要 |
| FR-3 | `weather_agent`：透過 `McpToolset` 接 Lab 6 的天氣 MCP server，`tool_filter=["get_weather"]` | P326 步驟 2 ／ P320 | 必要 |
| FR-4 | `booking_agent`：`search_hotels` 假資料工具，超出預算要說明而不是編旅館 | P326 步驟 2 ／ P289 | 必要 |
| FR-5 | `root_agent`：`sub_agents` 掛三專員，instruction 要求最後彙整成三天行程表 | P326 步驟 3 ／ P296 | 必要 |
| FR-6 | `SequentialAgent(writer→critic)`：writer 產 Markdown 行程、critic 檢查預算與時間衝突 | P326 步驟 4 ／ P301-302 | 必要 |
| FR-7 | 預算存在 `user:budget`；`booking_agent` 的工具從 `tool_context.state` 讀取 | P326 步驟 5 ／ P309 | 必要 |
| FR-8 | `adk web` 觀察 Events：委派給了誰、工具參數對不對、State 分頁看得到 `user:budget` | P326 步驟 6 ／ P286 | 必要 |
| FR-9 | `tests/travel.evalset.json` 三個案例（含預算超標 edge case）＋ `tests/criteria.json` 門檻 | P326 步驟 7 ／ P323-324 | 必要 |
| FR-10 | 驗收題「預算 3 萬、11 月去東京三天，怕下雨」產出含天氣建議的行程 | P326 步驟 8 | 必要 |
| FR-11 | `--self-check`：離線 assert 驗假資料過濾、state 讀寫、委派接線、instruction 佔位符 | 投影片沒有（教學補充） | 必要 |
| FR-12 | `--aha`：四張離線對照表（委派的帳單、被 ADK 改寫的 description、工具的兩種包裝、state 前綴的壽命） | 投影片沒有（教學補充） | 加分 |
| FR-12 | 專員設 `mode`（`single_turn` / `task`），讓子 agent 答完自動返回主管 | P297 ／ P298 | 加分 |
| FR-13 | `adk api_server` 建 session 時直接帶初始 state（`{"user:budget": 30000}`） | P325 | 加分 |
| FR-14 | `to_mcp_server(root_agent)`：把整個旅遊助理變成 MCP server 掛回 Antigravity | P321 | 加分 |

## 5. 非功能需求

| 項目 | 要求 |
|---|---|
| 時間盒 | 90–120 分（投影片標示）。步驟 1–5 約 60 分，6–8 約 40 分 |
| 費用上限 | $0。全程 AI Studio 免費層；`gemini-3.7-flash` 輸入 $0.75/1M tokens，這個 Lab 全部對話加 eval 三案例約 5 萬 tokens 以內 |
| 離線可測 | `uv run travel_planner/agent.py --self-check` 不連網、不需要 key、不花錢；`McpToolset` 的連線可在只開 Lab 6 server（也不需要 key）的情況下單獨驗 |
| 跨平台 | macOS / Linux / WSL2。指令一律 `uv run`，不出現 `pip` / `venv` / `activate` |
| 版本 | google-adk 2.7.x（本 Lab 實測 2.7.1）、Python 3.10+（建議 3.13）、mcp 客戶端 1.24–1.x（ADK 的 `[mcp]` extra 自己會裝對） |

## 6. 驗收標準

- [ ] `uv run adk --version` 印出 `2.7.x`
- [ ] `uv run travel_planner/agent.py --self-check` → `self-check ok（12 組 assert：…）`
- [ ] Lab 6 server 開著時，`MCP tools = ['get_weather']`（walkthrough 步驟 2 的離線驗收指令）
- [ ] `uv run adk web` → 選 `travel_planner`，問「東京 11 月會下雨嗎？」→ Events 出現名為 `weather_agent` 的 function call（`mode=single_turn` 的專員是以 AgentTool 形式被呼叫，不是 `transfer_to_agent`，見 SPEC 3.3）
- [ ] 說「預算三萬」→ adk web 的 **State** 分頁出現 `user:budget: 30000`
- [ ] 問旅館但**沒說預算** → agent 回頭問預算（不是瞎編旅館）——這是 FR-4 的反面驗收
- [ ] 說「預算 6000 元，東京住三晚」→ agent 明確說每晚只有 2000、最便宜 2800、共 8400 超出預算
- [ ] `uv run adk eval travel_planner tests/travel.evalset.json --config_file_path=tests/criteria.json --print_detailed_results` → `Tests passed: 3` / `Tests failed: 0`
- [ ] 最終驗收題：`預算 3 萬、11 月去東京三天，怕下雨` → 產出 Markdown 三天行程表，內含天氣建議、旅館與預估花費，結尾有 critic 的 `✅ 已通過預算與時間檢查`
- [ ] 你能說出「把 `search_agent` 的 `tools` 改成 `[google_search, search_hotels]` 會發生什麼事」，而且真的試過

## 7. 範圍外

- **不做 Graph Workflow**（P303-304）。ADK 2.7.1 已把 `SequentialAgent` 標為 deprecated 並推 `Workflow`，但 `Workflow` **還不能當 LlmAgent 的 sub-agent**（deprecation 訊息原文就這樣寫）——這個 Lab 的主管是 LlmAgent，所以留在 Template 三兄弟。想玩 Graph 去看「想再往下玩」。
- **不做部署**。`adk deploy cloud_run` / `agent_engine` 是 Lab 10。
- **不做資料庫 session**。`DatabaseSessionService`（Supabase）是 Lab 8；本 Lab 用 `InMemorySessionService`（`adk web` 預設），重啟就失憶，這是刻意的。
- **不做 Memory**（`VertexAiMemoryBankService`）、**不做 Artifacts**、**不做 A2A**。
- **不接真的訂房 API**。`search_hotels` 是假資料，重點是委派與 state，不是爬蟲。
- **不做 guardrail callbacks**。六個 callbacks（P314-315）看得懂就好，這個 Lab 不掛。

## 8. 費用與風險

| 項目 | 費用 | 說明 |
|---|---|---|
| AI Studio API key | $0 | 免費層每 5 小時刷新配額；這個 Lab 的量遠低於上限 |
| Gemini 3.7 Flash / 3.5 Flash-Lite | $0（免費層） | 付費層 3.7 Flash 輸入 $0.75/1M tokens |
| Google Search grounding | $0 | 每月前 5,000 次查詢免費；這個 Lab 大概用掉 10 次以內 |
| Lab 6 MCP server | $0 | 跑在本機 |
| 雲端資源 | 無 | 這個 Lab **沒有**建任何 GCP 資源，沒有東西要清 |

風險：

- **免費層的輸入可能被用於產品改進**（附錄 D ⑨）。不要把公司資料貼進這個 agent；要用真資料走付費層或 Enterprise。
- **`.env` 有 key**。`adk create` 產生的 `.gitignore` 已經排除 `.env`，但如果你手動建 `.env` 又蓋掉 `.gitignore`，就會把 key push 上去。
- **`adk eval` 全部失敗時 exit code 仍是 0**（本 Lab 實測 2.7.1）。CI 裡只看 exit code 會全綠但其實全掛——要 grep `Tests failed:`。

## 9. 前置依賴

| 依賴 | 從哪來 | 沒有的話 |
|---|---|---|
| AI Studio API key | Lab 1 那把還在就直接用；<https://aistudio.google.com/apikey> | 主管與專員都動不了，只剩 `--self-check` 能跑 |
| **Lab 6 的 MCP server**（`lab6/server.py`，有 `get_weather`） | Lab 6 的產出 | `weather_agent` 會噴 `ConnectionError: Failed to create MCP session`；walkthrough 步驟 2 有備案 |
| uv | 課程 M0 環境準備 | 所有指令都不能跑 |
| Node.js 20+ | M0 | 這個 Lab 用不到（沒有 npx 型 MCP server） |
| GCP 專案 / 信用卡 | — | **不需要**。這個 Lab 全程走 Developer API 路線 |
