# Lab 10 SPEC：整套系統上雲

## 1. 架構

```
你的瀏覽器                          你的終端機
    │ https + ID token                  │ gcloud run services proxy
    │ (adk web UI)                      │ (本機 3000/3001 → 帶 IAM 認證的通道)
    ▼                                   ▼
┌───────────────────────────────────────────────────────────────────────┐
│ Cloud Run: concierge-agent          （私有 --no-allow-unauthenticated）│
│   容器 = adk deploy 產的 image（python:3.11-slim，內含 google-adk[a2a]）│
│   程序 = adk api_server --with_ui  監聽 $PORT=8000                     │
│   身分 = agent-sa@PROJ.iam.gserviceaccount.com                        │
│   環境 = MCP_URL / TOOLBOX_URL / A2A_URL（--set-env-vars）             │
│          SESSION_DB_URL（--set-secrets，容器啟動時才展開）              │
└───┬────────────────────┬─────────────────────┬───────────────┬────────┘
    │ ① streamable-http  │ ② HTTP              │ ③ A2A/JSON-RPC│ ⑤ asyncpg
    │  + Bearer id-token │  + Bearer id-token  │  (名片公開)    │
    │  audience=MCP_URL  │  audience=TBOX_URL  │               │
    ▼                    ▼                     ▼               ▼
┌──────────────┐  ┌──────────────┐  ┌──────────────────┐  ┌──────────────┐
│ Cloud Run    │  │ Cloud Run    │  │ Cloud Run        │  │ Supabase     │
│ mcp-tools    │  │ toolbox      │  │ hotel-a2a        │  │ PostgreSQL   │
│ 私有         │  │ 私有         │  │ 公開（讀名片）    │  │ Session      │
│ FastMCP      │  │ toolbox      │  │ uvicorn          │  │ pooler:5432  │
│ /mcp         │  │ /api/toolset │  │ /.well-known/... │  │              │
│ (lab6)       │  │ (lab8 yaml)  │  │ (lab9 to_a2a)    │  │ (lab8)       │
└──────────────┘  └──────┬───────┘  └────────┬─────────┘  └──────────────┘
                         │ postgres          │ Gemini API
                         ▼ :5432             ▼
                  ┌──────────────┐    ┌──────────────┐
                  │ Supabase     │    │ Vertex AI    │
                  │ hotels 表    │    │ gemini-3.7   │
                  └──────────────┘    └──────────────┘

對照組（步驟 ⑦，同一份 concierge 程式碼）
┌───────────────────────────────────────────────────────────┐
│ Agent Engine (Agent Runtime)：reasoningEngines/RESOURCE_ID │
│   sessions / traces / metrics 內建，不用自己接              │
│   ⚠️ 它要連 ① ② 這兩個私有服務，需要另外綁 run.invoker      │
└───────────────────────────────────────────────────────────┘
```

`concierge/agent.py` 用的型號是 `gemini-3.7-flash`，**型號名以課程投影片為準**；若 404 用 `client.models.list()` 或 `gcloud ai models list` 確認目前可用的名字。

程序邊界（重點）：**四個 Cloud Run service = 四個獨立容器 = 四次冷啟動**。第一次問問題會慢（每一跳都要冷啟），第二次就快。這不是 bug。

## 2. 元件與職責

| 元件 | 來自 | 在雲上的形態 | 存取控制 | 職責 |
|---|---|---|---|---|
| `mcp-tools` | lab6/server.py | Cloud Run，FastMCP streamable-http | 私有 + `run.invoker` 白名單 | 匯率換算等通用工具 |
| `toolbox` | lab8/tools.yaml | Cloud Run，官方 toolbox image | 私有 + `run.invoker` 白名單 | 把 SQL 包成工具，連 Supabase |
| `hotel-a2a` | lab9/hotel_service | Cloud Run，uvicorn ASGI | **公開**（名片要讀得到） | A2A 訂房專員 |
| `concierge-agent` | lab10/concierge | Cloud Run，`adk api_server --with_ui` | 私有 | 主 agent：路由、換算、查庫、委派 |
| Agent Engine 實例 | lab10/concierge（同一份） | 託管 runtime | IAM（Vertex AI） | 對照組 |
| `agent-sa` | 這個 Lab 建 | service account | — | 四個服務共用的執行身分 |
| Secret Manager | 這個 Lab 建 | `session-db-url` / `db-password` | `secretAccessor` | 機密不進 image / git |
| `deploy.sh` | 本目錄 | 本機腳本 | — | 9 個階段，可單跑、可 dry-run |
| `verify.sh` | 本目錄 | 本機腳本 | — | 12 項檢查，含 403 行為 |
| `teardown.sh` | 本目錄 | 本機腳本 | — | 刪光 + 帳單提醒 |

## 3. 介面契約

### 3.1 HTTP 端點

| 服務 | 方法 + 路徑 | 未帶 token | 帶合法 ID token | 備註 |
|---|---|---|---|---|
| mcp-tools | `POST /mcp` | 403 | 200 | MCP streamable-http；JSON-RPC body |
| mcp-tools | `GET /mcp` | 403 | **406** | 406 = IAM 過了但 HTTP 方法不對 → `verify.sh` 判定為 PASS |
| toolbox | `GET /api/toolset` | 403 | 200 + 工具清單 JSON | |
| toolbox | `GET /api/toolset/hotel-tools` | 403 | 200 | Lab 8 定義的 toolset 名 |
| hotel-a2a | `GET /.well-known/agent-card.json` | **200** | 200 | 這個服務是公開的 |
| hotel-a2a | `POST /` | 200 | 200 | A2A JSON-RPC（`SendMessage`） |
| concierge-agent | `GET /list-apps` | 403 | `["concierge"]` | |
| concierge-agent | `POST /apps/concierge/users/{u}/sessions/{s}` | 403 | 200 | 建 session |
| concierge-agent | `POST /run_sse` | 403 | SSE | 與 M7 的 `adk api_server` 端點完全一樣 |
| concierge-agent | `GET /dev-ui/` | 403 | HTML | `--with_ui` 才有 |

403 vs 401 的分工（背下來，這是這個 Lab 最值錢的一句）：

- **403 Forbidden** = Cloud Run 前端擋掉。你這個身分沒有 `run.invoker`（或完全沒帶 token）。回應是 Google Frontend 的 HTML，不是你的 app 產生的。
- **401 Unauthorized** = token 本身無效。九成是 **audience 不等於目標服務 URL**（附錄 D ⑦）。
- **404** = IAM 過了，是你路徑打錯。

### 3.2 Python 介面（concierge）

```python
# concierge/auth.py —— 只用標準庫，可離線 self-check
audience(url: str) -> str          # "https://x.run.app/mcp" -> "https://x.run.app"
endpoint(base: str) -> str         # 補上（且只補一個）/mcp
auth_headers(url, fetch=None) -> dict[str, str]
#   localhost / 127.0.0.1（走 proxy）→ {}
#   其他 → {"Authorization": "Bearer <id-token>"}；audience 用 audience(url) 算
```

```python
# concierge/agent.py 的三個工具來源（參數名以 google-adk 2.7.1 原始碼為準）
McpToolset(
    connection_params=StreamableHTTPConnectionParams(url=..., timeout=30.0),
    header_provider=lambda ctx: {...},   # 每次呼叫前算，token 過期會自動換新
)
ToolboxToolset(
    server_url=...,
    toolset_name="hotel-tools",
    additional_headers={...},            # 靜態 Mapping，沒有 provider 版本
)
RemoteA2aAgent(
    name="hotel_agent",
    description="...",
    agent_card=A2A_URL + AGENT_CARD_WELL_KNOWN_PATH,   # "/.well-known/agent-card.json"
)
```

### 3.3 腳本介面

```
./deploy.sh [--dry-run] [階段...]
  階段：apis sa secrets mcp toolbox a2a iam agent engine（不給 = 全跑）
  離開碼：0 成功；1 前置缺失（找不到 lab6/8/9、依賴服務沒網址）；2 旗標或階段名寫錯

./verify.sh [--self-check | --verbose]
  離開碼：0 全過；1 有 FAIL；2 本機沒裝 gcloud（--self-check 不需要 gcloud）

./teardown.sh [--dry-run] [--keep-secrets]
  離開碼：一律 0（每一項 || true，清理腳本最重要的是跑完）
```

## 4. 資料模型

沒有新的資料表 —— 沿用 Lab 8 的 `hotels`。新的是 **session 落地**：

ADK 的 `DatabaseSessionService` 由 `session_service_uri` 觸發，第一次啟動會自己 `CREATE TABLE`（`sessions` / `events` / `app_states` / `user_states`，實際名稱由 ADK 版本決定）。所以這個 Lab 不需要手寫 DDL，但要注意：

| 項目 | 值 | 錯了會怎樣 |
|---|---|---|
| driver | `postgresql+asyncpg://`（**不是** `postgresql://`） | `InvalidRequestError: The asyncio extension requires an async driver` |
| port | Supabase **Session** pooler `5432` | 用 `6543` 的 transaction pooler → asyncpg 的 prepared statement 衝突（附錄 D ③） |
| 套件 | `asyncpg`（`google-adk[db]` 只給 sqlalchemy） | `ModuleNotFoundError: No module named 'asyncpg'` |
| 存放 | Secret Manager `session-db-url` | 寫進 `.env` 就會進 git，寫進 `--set-env-vars` 就會出現在 Console 的服務詳情頁 |

Secret Manager 的兩個 key：

| Secret | 內容 | 誰用 |
|---|---|---|
| `session-db-url` | `postgresql+asyncpg://postgres.<ref>:<pw>@aws-0-<region>.pooler.supabase.com:5432/postgres` | concierge-agent |
| `db-password` | Supabase 資料庫密碼（純密碼） | toolbox（`tools.yaml` 裡的 `${DB_PASSWORD}`） |

## 5. 檔案結構

```
lab10/
├── PRD.md                      需求、驗收清單、費用
├── SPEC.md                     本檔
├── walkthrough.md              一步一步教學（最重要）
├── config.sh                   唯一設定檔：專案、region、四個服務名、三個 lab 路徑
├── deploy.sh                   9 階段部署，--dry-run 只印指令
├── verify.sh                   12 項驗收，--self-check 離線驗判定邏輯
├── teardown.sh                 刪光，--dry-run / --keep-secrets
├── pyproject.toml              google-adk[a2a,mcp,toolbox,db,gcp] + asyncpg
├── uv.lock                     鎖定版本，進 git（相依的真實來源之一）
├── .gitignore                  .build/、concierge/.env、產出的 requirements.txt
├── dockerfiles/
│   ├── mcp.Dockerfile          lab6 → uv sync + MCP_TRANSPORT=http
│   ├── toolbox.Dockerfile      官方 toolbox image + COPY tools.yaml
│   └── a2a.Dockerfile          lab9 → uvicorn hotel_service.agent:a2a_app
├── concierge/                  ← adk deploy 的 agent 目錄
│   ├── __init__.py             from . import agent（少了它 /list-apps 是空的）
│   ├── agent.py                root_agent：MCP + Toolbox + RemoteA2aAgent
│   ├── auth.py                 audience / endpoint / auth_headers（可離線 self-check）
│   ├── .env.sample             複製成 .env：本機 adk web 與 adk deploy agent_engine 都讀它
│   └── requirements.txt        ← deploy.sh 用 uv export 產生，不進 git
└── .build/                     ← deploy.sh 產生的打包暫存區，不進 git
    ├── mcp/                    lab6 的副本 + Dockerfile
    ├── toolbox/                lab8 的副本 + Dockerfile
    └── a2a/                    lab9 的副本 + Dockerfile
```

為什麼要 `.build/`：`gcloud run deploy --source X` 會把 `X` 整包上傳給 Cloud Build。直接指 `../lab6` 有兩個問題 —— 得把 Dockerfile 寫進別人的 Lab 目錄，而且 `.venv`（幾百 MB）會一起上傳。複製一份、刪掉 `.venv`、蓋上 Dockerfile，最乾淨。

## 6. 環境變數與設定

| 變數 | 用途 | 從哪來 | 預設 |
|---|---|---|---|
| `GOOGLE_CLOUD_PROJECT` | GCP 專案 | Lab 5 | config.sh 退成 `agent-course-2026` |
| `GOOGLE_CLOUD_LOCATION` | region | Lab 5 | `us-central1` |
| `GOOGLE_GENAI_USE_ENTERPRISE` | 走 Vertex AI 而非 AI Studio key | adk 產的 Dockerfile 已寫死 `=1` | 本機要自己 export |
| `SESSION_DB_URL` | session 落地連線字串 | Supabase Dashboard → Connect → Session pooler | 無（`deploy.sh secrets` 會要求） |
| `DB_PASSWORD` | Supabase 密碼，toolbox 用 | 同上 | 無 |
| `MCP_URL` | MCP 服務根網址 | `gcloud run services describe` | 無（`--set-env-vars` 注入） |
| `TOOLBOX_URL` | toolbox 根網址 | 同上 | 無 |
| `A2A_URL` | A2A 服務根網址 | 同上 | 無 |
| `MCP_TRANSPORT` | 讓 lab6 的 server 用 streamable-http | `mcp.Dockerfile` 的 `ENV` | lab6 預設 stdio |
| `PORT` | 容器要 listen 的埠 | **Cloud Run 自動注入** | 8080（`adk deploy` 用 8000） |
| `MCP_SVC` / `TOOLBOX_SVC` / `A2A_SVC` / `AGENT_SVC` | 服務名 | config.sh | mcp-tools / toolbox / hotel-a2a / concierge-agent |
| `LAB6_DIR` / `LAB8_DIR` / `LAB9_DIR` | 前面 Lab 的路徑 | config.sh | `../lab6` / `../lab8` / `../lab9` |

`.env` 的讀取者只有兩個：本機 `adk web`、以及 `adk deploy agent_engine`（它沒有 `--set-env-vars`，adk 是把 agent 目錄的 `.env` 帶上雲）。Cloud Run 那條路不讀 `.env`，環境變數一律由 `deploy.sh` 的 `--set-env-vars` / `--set-secrets` 注入。

`$PORT` 是唯一「你不能寫死」的變數：Cloud Run 保證會注入，但不保證是 8080。Dockerfile 的 `CMD` 一律用 shell form（`["sh","-c","… $PORT"]`）才展開得到。

## 7. 執行流程

```bash
cd lab10

# 0) 離線先驗，不花錢
./verify.sh --self-check
uv run --no-project concierge/auth.py --self-check
./deploy.sh --dry-run                    # 讀一遍要跑什麼

# 1) 一次性前置
export GOOGLE_CLOUD_PROJECT=<你的專案>
export SESSION_DB_URL='postgresql+asyncpg://...:5432/postgres'
export DB_PASSWORD='...'
./deploy.sh apis sa secrets

# 2) 三個下游服務（各 3-5 分，Cloud Build 在建 image）
./deploy.sh mcp
./deploy.sh toolbox
./deploy.sh a2a

# 3) 故意先不綁 IAM，讓 403 發生一次（教學節奏，見 walkthrough 步驟 4）
./deploy.sh agent
#    → UI 問一句 → 工具呼叫 403 → 看 log 確認 → 再修
./deploy.sh iam
#    → 重問一次，通了

# 4) 驗收
./verify.sh

# 5) 對照組
./deploy.sh engine

# 6) 收工（一定要做）
./teardown.sh --dry-run
./teardown.sh
```

## 8. 錯誤處理與邊界

| 情境 | 症狀 | 處理方式 |
|---|---|---|
| 容器沒 listen `$PORT` | `Revision 'xxx-00001-abc' is not ready and cannot serve traffic. The user-provided container failed to start and listen on the port defined provided by the PORT=8080 environment variable` | Dockerfile 的 CMD 要用 `$PORT`；MCP 要 `MCP_TRANSPORT=http`；toolbox 要 `--address 0.0.0.0` |
| 沒帶 token 打私有服務 | 403 + Google Frontend 的 HTML | 正確行為。要進去就 `gcloud run services proxy` 或帶 ID token |
| SA 沒綁 `run.invoker` | agent 回「工具呼叫失敗」，Cloud Logging 裡是 `403` | `./deploy.sh iam` |
| audience 帶了路徑 | `401 Unauthorized`，訊息不說原因 | audience 只到 host，不含 `/mcp`（`auth.py` 的 `audience()` 就是為這件事存在的） |
| 容器缺 `toolbox-adk` | 開機就掛：`ImportError: ToolboxToolset requires the 'toolbox-adk' package.` | `uv export` 產 `concierge/requirements.txt`；**且不能把它寫進 `concierge/.gitignore`**（adk deploy 會讀該目錄的 .gitignore 並排除符合的檔案） |
| `postgresql://` 少了 asyncpg | `sqlalchemy.exc.InvalidRequestError: The asyncio extension requires an async driver to be used.` | 連線字串改 `postgresql+asyncpg://`，並在 pyproject 加 `asyncpg` |
| 用 6543 的 transaction pooler | 連得上但查詢隨機失敗（prepared statement 衝突） | 換 Session pooler 5432（附錄 D ③） |
| A2A 名片抓不到 | RemoteA2aAgent 在**第一次被呼叫時**才炸，不是啟動時 | 部署完先 `curl` 名片端點（`verify.sh` 有這一項） |
| A2A 名片寫著 localhost | 主 agent 連到 `http://localhost:8001` → 連線被拒 | Lab 9 的 `A2A_PORT` 只影響名片上的網址，上雲要改成公開網址 |
| Agent Engine 連私有 Cloud Run | 403 | Agent Engine 的執行身分不是 `agent-sa`，要另外綁 `run.invoker`（⚠️ 未實測） |
| 冷啟動超時 | 第一次工具呼叫 timeout | `StreamableHTTPConnectionParams(timeout=...)` 預設 5 秒，改 30 |
| `deploy.sh` 重跑 | `ALREADY_EXISTS` | 已處理：SA 用 `|| true`，secret 用 `create || versions add` |
| `adk deploy cloud_run` 帶 gcloud 旗標沒加 `--` | `Error: No such option '--no-allow-unauthenticated'.`（click 直接拒絕，還沒碰到 gcloud） | gcloud 的旗標一律放在 agent 路徑後面的 `--` 之後：`... concierge -- --no-allow-unauthenticated --service-account=…`（實測過，見第 9 節） |
| `adk deploy agent_engine` 少了 `concierge/.env` | 部署成功但一被呼叫就 `KeyError: 'MCP_URL'` | Agent Engine 沒有 `--set-env-vars`：adk 讀 agent 目錄的 `.env` 當環境變數。`deploy.sh engine` 會先擋下來並印出要填的三行 |
| 本機 `adk web` 直接連私有服務 | `google.auth.exceptions.DefaultCredentialsError: Neither metadata server or valid service account credentials are found.` | 使用者帳號的 ADC 不能簽任意 audience 的 ID token。開 `gcloud run services proxy`，`.env` 填 `http://localhost:3000`（`auth_headers()` 看到 localhost 就不帶 header） |

## 9. 驗證方式

**離線（我實際跑過的）**

```bash
./verify.sh --self-check                            # → self-check ok
uv run --no-project concierge/auth.py --self-check  # → self-check ok
bash -n config.sh deploy.sh verify.sh teardown.sh   # 語法檢查，無輸出 = 過
./deploy.sh --dry-run                               # 印出 31 條指令，一條都沒執行（dry-run 不需要真的機密）
./teardown.sh --dry-run

# 依賴解得開、且該有的套件都在（不用 GCP 帳號）
uv export --no-hashes --no-dev --no-emit-project -o concierge/requirements.txt
grep -E '^(toolbox-adk|asyncpg|google-cloud-aiplatform)' concierge/requirements.txt
# → toolbox-adk==1.3.1 / asyncpg==0.31.0 / google-cloud-aiplatform==1.165.1 三行都要有
```

**離線但需要一份裝好的 google-adk 才驗得到（我用 `lab9/.venv` 裡的 2.7.1 實測）**

| 驗了什麼 | 怎麼驗 | 結果 |
|---|---|---|
| `adk deploy cloud_run` 的旗標分界 | 少了 `--` 直接跑一次 | `Error: No such option '--no-allow-unauthenticated'.`；加上 `--` 之後一路走到 `Deploy failed: [Errno 2] No such file or directory: 'gcloud'`（本機沒裝 gcloud，表示旗標全部吃下去了） |
| 產出的 Dockerfile `CMD` 是 shell form | 直接呼叫 `cli_deploy.to_cloud_run()` 把 temp folder 留下來讀 | `CMD adk api_server --with_ui --port=8000 --host=0.0.0.0 --session_service_uri=$SESSION_DB_URL --artifact_service_uri=memory:// --trace_to_cloud "/app/agents"` —— `$SESSION_DB_URL` 是字面值，容器啟動才展開 |
| `requirements.txt` 有無的兩個分支 | 同上，跑兩次 | 有檔案 → `RUN pip install -r "/app/agents/concierge/requirements.txt"`；沒有 → `# No requirements.txt found.` |
| agent 目錄的 `.gitignore` 會排除檔案 | 在 `concierge/` 放一個寫著 `requirements.txt` 的 `.gitignore` 再跑一次 | 印出 `Reading ignore patterns from .gitignore...`，且 Dockerfile 變回 `# No requirements.txt found.` —— 陷阱成立，測完已刪掉那個檔 |
| `concierge/agent.py` 的三種接法真的 import 得起來 | `uv sync` 之後帶三個環境變數 import | `root_agent: concierge gemini-3.7-flash` / `tools: ['McpToolset', 'ToolboxToolset']` / `sub_agents: ['RemoteA2aAgent']`（會印兩行 `[EXPERIMENTAL]` 警告，正常） |
| 本機沒有 metadata server 時會怎樣 | 把 `TOOLBOX_URL` 換成真的 `https://…run.app` 再 import | `google.auth.exceptions.DefaultCredentialsError: Neither metadata server or valid service account credentials are found.` —— 所以本機一定走 proxy 的 localhost 網址 |

```bash
# 上面兩條自己重現（要先 uv sync）
MCP_URL=https://mcp-tools-x-uc.a.run.app TOOLBOX_URL=http://localhost:3001 \
A2A_URL=https://hotel-a2a-x-uc.a.run.app \
uv run python -c "import concierge.agent as m; print(m.root_agent.name, [type(t).__name__ for t in m.root_agent.tools])"
# → concierge ['McpToolset', 'ToolboxToolset']
```

`verify.sh --self-check` 驗的是 `judge()` 這個判定函式 —— 它決定「403 算不算過」。這條邏輯如果寫反，整份驗收會把「服務其實是公開的」判成 PASS，比沒驗更糟。所以用 13 個 assert 把三種期望值 × 各種實際回應碼釘住。

`auth.py --self-check` 驗的是 `audience()` —— 401 最常見的原因。用 `SimpleNamespace` 當假的 token fetcher，記下它被要求的 audience，證明我們沒把 `/mcp` 一起送出去，也證明 localhost（proxy）不會去換 token。

**雲端**

```bash
./verify.sh            # 12 項，看 PASS/FAIL
./verify.sh --verbose  # 順便印回應前 200 字，debug 用
```

**沒辦法離線驗的（要 GCP 帳號 / 真的 host）**

| 項目 | 為什麼驗不了 |
|---|---|
| 所有 `gcloud` 指令是否成功 | 沒有 GCP 專案、沒綁卡 |
| Dockerfile 是否 build 得起來 | 沒有 Docker / Cloud Build |
| 官方 toolbox image 的路徑與旗標 | 要能 pull image 才知道 |
| Cloud Run 對未授權請求真的回 403 | 需要真的部署一個私有服務 |
| `GET /mcp` 帶合法 token 回 406 | 依 MCP streamable-http 規格推得，`verify.sh` 因此把 406 判為 PASS，但沒實際打過 |
| Agent Engine 能否連私有 Cloud Run | 需要真的部署。它的執行身分不是 `agent-sa`，大概要另外綁 `run.invoker` |
| ADK 自動建的 session 表名 | 要真的連上 Postgres 跑一次才知道 |
| lab9 名片 `url` 回填後是否被消費端正確採用 | 改法是讀 `to_a2a(host=…, protocol=…)` 的原始碼推得（`rpc_url = f"{protocol}://{host}:{port}{prefix}/"`），沒有真的跑起來對打 |

## 10. 已知限制與升級路徑

| 位置 | 偷懶的地方 | 天花板 | 升級路徑 |
|---|---|---|---|
| `config.sh` | 四個服務共用一個 `agent-sa` | 任一服務被打穿，四個服務的權限全丟 | 一個服務一個 SA，`run.invoker` 只綁到需要的那一對 |
| `concierge/agent.py` | ToolboxToolset 的 `additional_headers` 是模組載入時算一次的靜態 header | ID token 一小時過期；實例活過一小時就 401 | 自訂 `ToolboxToolset` 子類，在 `get_tools()` 時重算 header（MCP 那邊用 `header_provider` 已經沒這問題） |
| `deploy.sh` | `--dry-run` 用 `printf '%s' "$*"` 印 argv | 含空白的參數印出來的引號不對，不能無腦複製貼上 | 換 `printf '%q '`（但那是 bash-only） |
| `teardown.sh` | Agent Engine 只列出 resource name，要人工貼進 delete | 忘記貼就漏刪，而且它閒置也計費 | 用 `--format='value(name)'` 接 `xargs`，但誤刪風險高，課程刻意保留人工確認 |
| `dockerfiles/toolbox.Dockerfile` | 官方 image `:latest` | image 換路徑或 flag 改名就掛 | 釘版本號；備案（下載 binary）已寫在同檔註解裡 |
| `deploy.sh` 全域 | `--max-instances 3` 寫死 | 真的有流量會被限流 | 上線前依 QPS 調，但**永遠要設**（附錄 D 的成本紀律） |
| 觀測 | 只開 `--trace_to_cloud` | 沒有 alert、沒有第三方整合 | M5 的預算告警 + `adk.dev/integrations`（Arize / AgentOps / Datadog） |
