# Google AI Agent 生態系 — 完整實戰課程教材包

這個 repo 是《Google AI Agent 生態系完整實戰課程》（講義 v2.0，資訊基準日 2026-08-25）的 **13 個 Lab 教材包**。每個 lab 一個目錄，裡面都有 `PRD.md`（這個 Lab 要解決什麼、學習目標、功能需求、前置依賴）、`SPEC.md`（技術規格、資料形狀、已知限制、未實測清單）、`walkthrough.md`（照著打就會動的分步驟操作＋驗收＋常見錯誤＋清理），以及一份**可以直接跑的程式骨架**。從第一支 Gemini API CLI 一路到 multi-agent 系統部署上 Cloud Run／Agent Engine。


---

## 怎麼開始

```bash
# 1) uv —— 本課唯一的 Python 工作流（取代 pip / venv）
curl -LsSf https://astral.sh/uv/install.sh | sh

# 2) Gemini API key（Lab 1 立刻用到，免費層即可）
#    https://aistudio.google.com/apikey
export GEMINI_API_KEY="..."

# 3) 進任一 lab 目錄，一律用 uv run
cd lab1 && uv run ask.py "2026 年最新的 Gemini 模型是哪個？"
```

> **不要用 `python ask.py`／`pip install`。** 全課一律 `uv run <script>`、`uv add <package>`、`uv tool install <cli>`。`uv run` 會自己讀 `pyproject.toml` 建好環境；直接 `python xxx.py` 會用到系統 Python、找不到套件，錯誤訊息還會很難懂。
> 少數 lab 額外需要 Node.js ≥ 20（`npx` 型 MCP server）、`gcloud`（Lab 5／10）、`jq`、`ffmpeg`——各 lab 的 `PRD.md` §9 有完整清單。

---

## Lab 總覽

時間與付費欄位抄自講義附錄 E「全課 Lab 總覽」（p.464），未自行調整。

| Lab | 主題 | 模組 | 預估時間 | 需要付費？ | 前置依賴 | 目錄 |
|---|---|---|---|---|---|---|
| Lab 1 | 會查資料的 CLI 問答工具（grounding＋串流） | M1 Gemini 模型家族與 Gemini API | 30-45 分 | 免費層 | 無（全課第一個）＋`GEMINI_API_KEY` | [lab1/](lab1/) |
| Lab 2 | Build 一個 App 並部署上 Cloud Run | M2 Google AI Studio | 40-60 分 | 免費 | Lab 1（建議）、Antigravity 桌面版（步驟 6） | [lab2/](lab2/) |
| Lab 3 | 讓 Agent 工程化你的 Lab 2 專案 | M3 Antigravity：Agent-First 開發平台 | 60-90 分 | 免費層 | **Lab 2 的專案資料夾**、Antigravity 桌面版、Chrome、Node ≥ 20、GitHub PAT | [lab3/](lab3/) |
| Lab 3.5 | 兩個 Agent 共用一份會長大的記憶（CivicGuard） | M3.5 Gemini CLI × Antigravity 記憶協作 | 90 分 | 免費層＊ | Gemini CLI、`GEMINI_API_KEY`、`jq`、`CWA_API_KEY`（選）、Antigravity（選） | [lab3.5/](lab3.5/) |
| Lab 4 | 課程知識庫 × Agent 查詢 | M4 NotebookLM 與個人 LLM Wiki | 45-60 分 | 免費 | Lab 3（Antigravity 已裝並登入、MCP 設定概念）；**不需要** API key | [lab4/](lab4/) |
| Lab 4.5 | 讓它自己出一集（AI 日報電台） | M4.5 把 NotebookLM 變成每日內容產線 | 150 分 | 免費層＋ | **Lab 4**（同一本筆記本）、Lab 3／3.5、`ffmpeg`、YouTube Data API OAuth client、YouTube 頻道（選） | [lab4.5/](lab4.5/) |
| Lab 5 | 課程專用 GCP 專案完整設置 | M5 Google Cloud 基礎 | 30-40 分 | **需綁卡** | 信用卡、`gcloud` CLI、`GEMINI_API_KEY`（步驟 6） | [lab5/](lab5/) |
| Lab 6 | 自建 MCP Server 接進 Antigravity | M6 MCP：Model Context Protocol 深入 | 60-90 分 | 免費 | Antigravity 桌面版（Lab 3）、Node ≥ 20；**不需要** key／綁卡 | [lab6/](lab6/) |
| Lab 7 | 多 Agent 旅遊助理 | M7 ADK：Agent Development Kit | 90-120 分 | 免費層 | **Lab 6 的 `server.py`**（`get_weather`）、AI Studio API key | [lab7/](lab7/) |
| Lab 8 | 旅館查詢 Agent（三層整合） | M8 資料庫整合：Supabase × MCP Toolbox | 90-120 分 | 免費層 | Supabase 專案（Session pooler 5432）、`GEMINI_API_KEY`、**Lab 7**（ADK 基本操作） | [lab8/](lab8/) |
| Lab 9 | 跨服務 Agent 協作（A2A） | M9 A2A：Agent2Agent Protocol | 60-90 分 | 免費層 | **Lab 7**（必要）、Lab 8（選配，可用自帶假資料）、兩個終端機分頁 | [lab9/](lab9/) |
| Lab 10 | 整套系統上雲 | M10 部署：Agent Engine × Agent Garden × Cloud Run | 120-150 分 | ~$0-5 | **Lab 5＋Lab 6＋Lab 8＋Lab 9 的產物**（路徑寫在 `config.sh`） | [lab10/](lab10/) |
| Capstone | 個人 LLM Wiki ＆ Assistant System | M11 Capstone | 2-4 天 | ~$0-10 | **M1-M10 全部**（Lab 4 的筆記本、Lab 6 骨架、Lab 7 委派結構、Lab 8 的表、Lab 9 雙服務、Lab 10 部署鏈） | [capstone/](capstone/) |

＊Lab 3.5：Gemini API 免費層即可，CWA open data 免費申請。個人 Google 帳號登入 Gemini CLI 已於 2026/06/18 停止，全程用 API key。
＋Lab 4.5：Notebook 免費層每日 Audio／Video 各 3 次配額；YouTube API 專案未稽核前會被鎖私人。

---

## 依賴關係圖

```
                    GEMINI_API_KEY（Lab 1 拿的那把，之後全課共用）
                     │
Lab 1 ──► Lab 2 ──► Lab 3 ──► Lab 3.5
(API)     (App)     專案+       AGENTS.md /
                    AGENTS.md   rules 共用
                        │
                        ▼
                     Lab 4 ──► Lab 4.5
                  （筆記本）   （同一本筆記本 → 日報產線）
                        │
Lab 6 ──────────────────┼───────────────────────┐
(MCP server)            │                       │
  │  server.py          │                       │
  ▼                     │                       │
Lab 7 ──► Lab 9 ──► Lab 10 ◄── Lab 5（GCP 專案／綁卡／ADC／Secrets）
(ADK)     (A2A)      (上雲)      ▲
  ▲         ▲                    │
  │         │                    │
Lab 8 ──────┴────────────────────┘
(Supabase / Toolbox / pgvector)

Lab 4 ┐
Lab 6 ┤
Lab 7 ┼──► Capstone（不教新 API，只負責把全部接上正確的線）
Lab 8 ┤
Lab 9 ┤
Lab 10┘
```

| 這條線 | 傳過去的是什麼 | 沒有的話 |
|---|---|---|
| Lab 2 → Lab 3 | AI Studio Build 匯出的 React+TS 專案資料夾 | 用 `npm create vite` 生一個替代品，步驟照走（Lab 3 PRD §9 有指令） |
| Lab 3 → Lab 3.5 | `AGENTS.md` ＋ `.agents/rules/` 的寫法 | Lab 3.5 自帶完整樣板，可獨立做 |
| Lab 4 → Lab 4.5 → Capstone | 同一本 NotebookLM 筆記本（策展品質直接決定 Capstone 回答品質） | 做完不要刪 |
| Lab 6 → Lab 7 | `lab6/server.py` 的 `get_weather`（`McpToolset` 接進來） | `weather_agent` 噴 `ConnectionError: Failed to create MCP session`，walkthrough 步驟 2 有備案 |
| Lab 7 → Lab 9 | ADK `Agent(...)` / `sub_agents=` / Events 面板的理解 | Lab 9 不重講 ADK 基礎 |
| Lab 8 → Lab 9 | 真資料版 `hotel_agent`（**非硬依賴**，Lab 9 自帶假資料） | 主線照樣完成，之後把 `tools=` 換掉即可 |
| Lab 5 → Lab 10 | 已綁帳單、已開 API、已設 ADC／SA／預算的 GCP 專案 | `gcloud run deploy` 直接失敗 |
| Lab 6／8／9 → Lab 10 | `server.py`、`tools.yaml`、`to_a2a` 服務（路徑在 `lab10/config.sh` 三行） | 對應階段全斷 |

---

## 建議上課路線

| 路線 | 內容 | 時間 | 綁卡 |
|---|---|---|---|
| **最短：只想學 API** | Lab 1 → Lab 6 → Lab 7 | 約 3-4 小時 | 不用 |
| **不綁卡的最大範圍**（約 60% 內容） | Lab 1 → 2 → 3 →（3.5）→ 4 →（4.5）→ 6 → 7 → 8 → 9 | 約 2 天 | 不用 |
| **完整路線** | Lab 1 → 2 → 3 → 3.5 → 4 → 4.5 → **Lab 5（綁卡分界點）** → 6 → 7 → 8 → 9 → 10 → Capstone | 11 週課／3 天工作坊 | Lab 5 起需要 |
| **只想看 agent 框架** | Lab 6 → 7 → 8 → 9（Lab 8 需 Supabase 免費帳號） | 約 1.5 天 | 不用 |

- **綁卡分界點就是 Lab 5。** Lab 1-4.5、6、7、8、9 全部在免費層（Lab 8 只需 Supabase 免費帳號）；Lab 5、10、Capstone 需要已綁卡的 GCP 專案（新帳號有 $300／90 天試用）。
- 順序彈性：M1→M2→M3 建議照順序；**Lab 6 與 Lab 7 可對調**（但 Lab 7 的 `weather_agent` 要吃 Lab 6 的 server，對調時走 walkthrough 步驟 2 的備案）。Lab 3.5 與 Lab 4.5 是加深章節，時間不夠可跳。

---

## 費用與清理

| Lab | 會產生的計費／配額資源 | 清理指令在哪 |
|---|---|---|
| Lab 1 | 無（API 呼叫走免費層配額） | `lab1/walkthrough.md` §清理（刪 API key） |
| Lab 2 | Cloud Run 服務（若做 FR-9 上雲）、本機 docker image | `lab2/walkthrough.md` §清理（`gcloud run services delete`、`docker rmi`） |
| Lab 3 / 3.5 | 無雲端資源（GitHub repo、本機檔案） | `lab3/walkthrough.md`、`lab3.5/walkthrough.md` §清理 |
| Lab 4 | NotebookLM 筆記本（免費層 100 本／50 來源）、本機 session 檔 | `lab4/walkthrough.md` §清理（⚠️ session 檔路徑依版本而異，先看再刪） |
| Lab 4.5 | Notebook Audio／Video 每日配額、YouTube 影片、GCP OAuth client | `lab4.5/walkthrough.md` §清理 |
| Lab 5 | **GCP 專案本體**（帳單、budget、SA、Secret Manager） | `lab5/teardown.sh`＋`lab5/walkthrough.md` §清理（`projects delete` 有 30 天 undelete 緩衝） |
| Lab 6 | 無（本機 stdio／HTTP server） | `lab6/walkthrough.md` §清理 |
| Lab 7 | 無雲端資源（API 呼叫配額） | `lab7/walkthrough.md` §清理 |
| Lab 8 | Supabase 免費層 DB（500MB）、embedding API 呼叫 | `lab8/walkthrough.md` §清理 |
| Lab 9 | 無雲端資源（兩個本機 uvicorn 行程） | `lab9/walkthrough.md` §清理 |
| Lab 10 | **5 個 Cloud Run 服務、Artifact Registry image、Secret、Agent Engine** | `lab10/teardown.sh`（`--keep-secrets` 可留給 Capstone）＋`lab10/walkthrough.md` §步驟 8／§清理 |
| Capstone | **5 個 Cloud Run 服務、Cloud Scheduler、Supabase、Secrets** | `capstone/walkthrough.md` §清理 |

- 成本紀律：**先設預算告警再開始**（Lab 5 步驟 2 建三段門檻），Lab 5／10／Capstone 做完立刻跑 teardown，並到帳單頁面確認歸零。
- Cloud Run 是 scale-to-zero，閒置費用為 0，但 Artifact Registry 的 image 與 Cloud Scheduler 會持續計費。

---

## 教材現況（上課前請自己先跑這幾段）

**全部教材的程式碼骨架、離線 `--self-check`、語法／結構檢查都實測過。** 但撰寫環境沒有 API key、沒有 GCP 帳號、沒有 Antigravity 桌面版、沒有 `gcloud`／`gemini`／`nlm`／`ffmpeg`——所有需要憑證或 GUI 的步驟在文件裡都標了 `⚠️ 未實測`，沒有偽裝成實測。

### 需要先補齊的環境（決定你能驗多少）

| 缺什麼 | 影響的 Lab |
|---|---|
| `GEMINI_API_KEY` / `GOOGLE_API_KEY` | 1、2、3.5、5（步驟 6）、7、8、9、Capstone |
| Antigravity 桌面版（含登入） | 2（步驟 6）、3、4、6、8（加分題） |
| `gcloud` ＋ 已綁卡 GCP 專案 | 2（FR-9）、5、10、Capstone |
| Gemini CLI (`gemini`) | 3.5、4.5 |
| `notebooklm-mcp-cli` (`nlm`) ＋ Google 帳號登入 | 4、4.5 |
| Supabase 專案 | 8、10、Capstone |
| Docker／`ffmpeg`／YouTube OAuth | 2（本機 image 已驗）、4.5 |

### 逐 Lab 未實測重點

| Lab | 上課前最該自己先跑一遍的 | 其他未實測項 |
|---|---|---|
| Lab 1 | 六處 `⚠️`：步驟 2 答錯對照組、步驟 3/4 串流與來源、步驟 5 `--json`、步驟 6 三個時事問題 | `response_mime_type` 必填只驗到 SDK docstring 層級；`interaction.status_update` 何時出現是推論 |
| Lab 2 | `gcloud run deploy` 上線＋三個部署錯誤（403 Forbidden／雲端 500／port 寫死的 rollback 原文）；真實 `summarize()` 與 paywall 回 `status=paywall` | AI Studio Build mode 全部 UI（步驟 1/3/4/5a/6）、Export to Antigravity；欄位形狀已對 google-genai 2.20.0 原始碼查過 |
| Lab 3 | Antigravity UI 全部：Project 匯入、`/codesearch`、`/grill-me`、Plan 留言吸收、Artifacts 錄影、MCP refresh、`/permissions`；`mcp_config.json` 的 `$ENV_VAR` 到底會不會展開 | GitHub MCP 套件名與工具名、遠端端點 `api.githubcopilot.com/mcp/`、真專案上的 `npm run dev`／`lint`／`tsc`。**待人類拍板**：GitHub MCP 要不要從已 deprecated 的 npm stdio server 換成官方遠端 server |
| Lab 3.5 | `gemini` CLI 全部：`/memory list|show|reload|inbox`、`-p`、`--output-format json`、exit code 42/53、`.toml` 與 subagent front matter 是否解析得動 | Antigravity 是否展開 `AGENTS.md` 的 `@import`（官方未文件化，已用 rules 再引一份保險）；CWA 回應結構與 dataset id `W-C0033-001`；GitHub Actions 實際執行；Auto Memory 觸發條件。**需要人跑一次** `git commit -m "init civicguard"` 才過得了驗收① |
| Lab 4 | `nlm` CLI 全部指令與旗標（先 `nlm --help` 對名字）、MCP 工具的參數 schema（`notebook_query` 吃 `notebook_id` 還是 `id`） | NotebookLM 2026-08 版 UI 按鈕名；`scan_sources` 的狀態關鍵字是推測；`citations()` 只認裸 http(s) 連結，若 `nlm` 只吐 `[1]` 會誤判零引用 |
| Lab 4.5 | `nlm login/doctor/setup add`、`audio|video create --json` 的實際欄位名、`studio status` 的 state 值域、`nlm download` 落地行為 | `gemini -p --output-format json` 結構、三條 `ffmpeg` 指令（本機沒裝）、YouTube `videos.insert`／OAuth Testing 7 天失效、launchd 隔天 06:00 是否觸發。**課程設計待決**：投影片「全文來源至少佔一半」在 24 小時窗口內做不到 |
| Lab 5 | 整支 `setup.sh`／`verify.sh` 對真帳號跑一輪——特別是 budget 那項與 `get-iam-policy --flatten` 的輸出格式是否對得上 grep 樣式 | ADC 檔是否真有 `quota_project_id` 鍵名；「重跑 `budgets create` 會沉默地多一個同名 budget」是推論；`gcloud billing budgets` 是否要另外啟用 Budget API（沒驗證，刻意沒寫進錯誤表） |
| Lab 6 | Antigravity 端：MCP 面板／Refresh／工具清單、agent 一句話串兩個工具、`disabledTools` 的實際擋法、`serverUrl` 重接 HTTP 模式 | stdio 協定本身已用 `probe.py` 實測、HTTP 端點已用 curl 驗過 `tools/list`／`tools/call`；步驟 7 的實測是在 8123 做的（本機 8080 被佔） |
| Lab 7 | `adk web` 的 Events／State／Trace、`adk eval` 的 `Tests passed: 3`、`adk api_server` 兩條 curl、模型是否真的呼叫 MCP 的 `get_weather` | evalset 的 tool_uses 軌跡是推的，跑之前先用 Eval 分頁重錄；`criteria.json` 的 `IN_ORDER` 只驗到 config 解析。**待人類決定**：文件三處引用 ADK 自己印的 `pip install "google-adk[eval]"` 錯誤原文（每處都緊接「一律 uv add」） |
| Lab 8 | `schema.sql` 在真 Supabase 上執行（hnsw／`vector` 型別）、Toolbox binary 啟動與 `/api/toolset/<name>`、`adk web` 三題驗收 | `DatabaseSessionService` 自動建表與重啟後追問、`gemini-embedding-2` 的實際維度、Toolbox darwin/arm64 下載網址（由 linux/amd64 推得）、加分題 B 的 Supabase MCP OAuth |
| Lab 9 | 步驟 4b／5 的 `adk web` 對話、Events 面板、6 秒慢查詢下 UI 是否真的出現 `WORKING` | `adk web` 是否同時列出兩個 agent 是推論；加分題匯率 agent 只給改法。純 a2a-sdk 假服務被 `RemoteA2aAgent` 呼通已由 `smoke_test.py` 實測 |
| Lab 10 | 整條 `deploy.sh`／`verify.sh` 對真專案跑 `--apply`；未授權請求真的回 403；`GET /mcp` 帶 token 回 406（verify.sh 把 406 判 PASS，依規格推得） | 三個 Dockerfile 沒 build 過；官方 toolbox image 路徑與旗標名沿用 Lab 8；Agent Engine 執行身分能否連私有 Cloud Run（步驟 ⑦「失敗本身就是資訊」）。**待人類決定**：lab9 名片的 `url` 回填要不要真的改進 `lab9/`（目前只動 lab10） |
| Capstone | `deploy.sh --apply` 全部 gcloud 路徑、`schema.sql` 在真 DB（`vector(1536)` 收不收得下 embedding）、`acceptance.py` 全綠 | 所有真呼叫 Gemini 的路徑（embed／url_context／summarize／digest／`adk web`／`adk eval`）、Toolbox image 路徑與 CLI 參數名、`docker build`、MCP Inspector／Antigravity `/mcp` 畫面 |

### 全課通用的兩個保留事項

| 事項 | 現況 |
|---|---|
| 模型 ID `gemini-3.7-flash` / `gemini-3.5-flash-lite` / `gemini-embedding-2` | 全部照投影片抄，沒有實際呼叫確認存在。所有文件都註明「型號名以投影片為準，若 404 用 `client.models.list()` 確認」；Lab 7 另留 `ADK_MODEL` / `ADK_MODEL_LITE` 可覆寫 |
| 定價與配額數字 | 照講義 p.12／p.22 抄（3.7 Flash $0.75/1M 輸入、Search Grounding 每月 5,000 次免費、免費層資料存 1 天／付費層 55 天、Supabase 免費 500MB），未向官方查證；沒給的數字（如 embedding 單價）刻意不寫 |

---

## 每個 lab 目錄的檔案慣例

| 檔案 | 是什麼 | 誰該看 |
|---|---|---|
| `PRD.md` | 這個 Lab 要解決什麼問題、學習目標、使用者故事、功能需求表（FR-n 對應投影片頁）、非功能需求、**§9 前置依賴** | 備課、決定要不要教這個 Lab、確認學生環境 |
| `SPEC.md` | 技術規格：檔案結構、資料形狀、介面、錯誤處理、**§9/§10 未實測與已知限制** | 改教材、debug、判斷「這是 bug 還是設計」 |
| `walkthrough.md` | 分步驟操作（含真實輸出）、每步驟驗收、常見錯誤表（錯誤訊息原文 → 原因 → 解法）、**§清理** | 上課現場照著走；學生自學的主文件 |
| 程式骨架 | 可直接 `uv run` 的實作（`ask.py`、`server.py`、`agent.py`、`setup.sh`…） | 學生的起點／參考解法 |
| `pyproject.toml` + `uv.lock` | 該 lab 的相依，`uv run` 會自動用 | — |
| `--self-check` 旗標 | 多數腳本都有：不連網、不花錢、純 assert 的離線檢查 | **沒有 API key 的教室裡用它驗學生邏輯** |
| `templates/`、`*.sample.json`、`env.example`、`.env.example` | 給學生複製的樣板（AGENTS.md、rules、mcp_config、環境變數） | 直接 `cp` 後改 |
| `verify.sh` / `teardown.sh`（Lab 5、10） | 逐項印綠勾紅叉的驗收；一鍵刪光計費資源 | 上雲的 Lab 必用 |
| `ACCEPTANCE.md` + `acceptance.py`（Capstone） | 可執行的驗收矩陣 | 打分數 |

其他：課程投影片（467 頁 PDF）不在這個 repo，向講師索取；`google-slide/` 是投影片裡的零散示範腳本。改名對照（2025 → 2026）、十大易錯坑、`mcp_config.json` 完整範本都在投影片附錄 A-E。
