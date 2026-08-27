# Capstone SPEC：個人 LLM Wiki ＆ Assistant System

> 對應投影片 428-448。四個 Phase 的技術契約都在這裡；步驟怎麼走看 `walkthrough.md`。

## 1. 架構

```
                        ┌──────────────────────────────────────────┐
 手機／瀏覽器 ───────────▶│ concierge-svc（Cloud Run，公開或 IAM）      │
                        │ adk deploy cloud_run --with_ui           │
                        │  process: root_agent = concierge         │
                        └───┬────────────┬───────────────┬─────────┘
                            │ 委派        │ 委派           │ 委派
                 ┌──────────▼──┐  ┌──────▼──────┐  ┌─────▼────────┐
                 │ wiki_agent  │  │ data_agent  │  │ research_agent│
                 │ (同一程序)   │  │ (同一程序)   │  │ RemoteA2aAgent│
                 └──────┬──────┘  └──────┬──────┘  └─────┬────────┘
      function tool 直呼  │                │ MCP/HTTP      │ A2A over HTTPS
                 ┌──────▼───────┐  ┌──────▼───────┐  ┌───▼──────────────────┐
                 │ wiki_core.py │  │ toolbox-svc  │  │ research-a2a-svc     │
                 │ (in-process) │  │ 官方 image    │  │ to_a2a(research)     │
                 └──────┬───────┘  │ tools.yaml   │  │ google_search 獨占    │
                        │          └──────┬───────┘  └───┬──────────────────┘
                        │                 │              │ 研究完呼叫 ingest
                        ▼                 ▼              ▼
                 ┌─────────────────────────────────────────────────┐
                 │ Supabase PostgreSQL（Session pooler:5432）        │
                 │  documents(+embedding vector) │ notes │ subs     │
                 │  adk sessions/events（session 持久化）            │
                 └─────────────────────────────────────────────────┘

  另一條消費路線（同一份能力，三個消費者）：
   Antigravity / Claude ──stdio 或 streamable-http──▶ wiki-mcp-svc ──▶ wiki_core.py ──▶ Supabase
   Cloud Scheduler 08:00 ──POST──▶ daily_digest（Workflow：純函式節點 → LLM 節點）──▶ Markdown 日報
   NotebookLM（策展側）◀── 人工貼摘要／notebooklm-mcp（只在本機）
```

程序邊界（誰跟誰是同一個 process）：

- `concierge` / `wiki_agent` / `data_agent` 在**同一個 process**（同一個 Cloud Run 服務）；`wiki_agent` 的工具是本地 function call，`data_agent` 的工具走 HTTP 到 toolbox-svc。
- `research_agent` 在**另一個 process**（research-a2a-svc）：研究任務重、要獨立擴展，而且 `google_search` 必須獨占一個 agent。
- `wiki-mcp-svc` 是**第三個 process**，服務的是「外部 host」（Antigravity／同事的 Claude），不是給 concierge 用的——concierge 直接呼 `wiki_core.py` 省一跳網路。
- `daily_digest` 是**非對話型**：由排程觸發，不經過 concierge。

## 2. 元件與職責

| 元件 | 檔案 | 職責 | 不做什麼 |
|---|---|---|---|
| 知識層核心 | `wiki_core.py` | chunk／embed／pgvector 寫入與檢索／DSN 正規化／結果格式化 | 不管誰在呼叫它（沒有 agent、沒有 MCP 概念） |
| ingest CLI | `ingest.py` | 網址或檔案 → 切塊入庫 ＋ 產出給 NotebookLM 的摘要 | 不自動寫 NotebookLM（cookie 認證留本機） |
| concierge | `concierge/agent.py` | 理解、委派、彙整 | 不自答知識問題、不編數字 |
| wiki_agent | 同上 | 先 `search_knowledge` 再回答；使用者要求時 `ingest_document` | 沒查到不腦補 |
| data_agent | 同上 | 用 Toolbox 的四個工具查 subscriptions／notes | 不自己寫 SQL（SQL 在 `tools.yaml`） |
| research_agent | `research_service/agent.py` | google_search 搜尋 → 交叉驗證 → 固定格式報告 | 不掛第二個工具（google_search 獨占） |
| 每日摘要 | `digest.py` | Graph workflow：純函式撈資料 → 路由 → LLM 寫作 | 沒有新文件時不呼叫 LLM |
| wiki-mcp | `wiki_mcp/server.py` | 把 `wiki_search`／`wiki_ingest`／`wiki://stats` 曝露給任何 host | 不做認證（認證交給 Cloud Run IAM） |
| Toolbox 契約 | `tools.yaml` | 四個寫死的 SQL 工具＋兩個 toolset（讀寫／唯讀） | 不接受模型給的 SQL |
| 驗收矩陣 | `acceptance.py` / `ACCEPTANCE.md` | 20 條驗收，8 條可離線執行 | 不假裝驗過雲端的部分 |
| 部署 | `deploy.sh` / `Dockerfile` | 依賴順序部署＋IAM 綁定＋smoke test 指令 | 預設 dry-run，不會偷偷花錢 |

## 3. 介面契約

### 3.1 `wiki_core.py`（三個消費者共用）

```python
def chunk(text: str, size: int = 1200, overlap: int = 150) -> list[str]
def to_vector(values) -> str                      # [0.1,0.2] 的字串 literal
def embed(texts: list[str]) -> list[str]          # 回傳 vector literal 清單（截斷到 EMBED_DIM=1536）
def dsn(url: str | None = None) -> str            # 正規化＋擋 6543
def fetch_text(source: str) -> str                # http → url_context；否則讀檔
def summarize(text: str) -> str
def format_hits(rows, min_sim: float = 0.25) -> dict
async def search_impl(query: str, top_k: int = 5) -> dict
async def ingest_impl(source: str, topic: str = "") -> dict
async def stats_impl() -> str
```

`format_hits` / `search_impl` 的回傳（agent 與 MCP 共用這個 schema）：

```python
{"status": "success", "hits": [{"source": str, "topic": str, "snippet": str(<=500), "score": float}], "note": str}
{"status": "empty",   "hits": [], "note": "知識庫沒有相關內容。請直接告訴使用者查無資料，不要自行補答案。"}
{"status": "error",   "hits": [], "message": "知識庫查詢失敗（OSError: ...）"}
```

### 3.2 Agent 工具 schema（ADK 從 docstring ＋ 型別標註生成）

| 工具 | 簽章 | 掛在誰身上 |
|---|---|---|
| `search_knowledge` | `async (query: str, top_k: int = 5) -> dict` | wiki_agent |
| `ingest_document` | `async (url: str, topic: str = "") -> dict` | wiki_agent |
| `google_search` | ADK 內建 | research_agent（獨占） |
| `list-subscriptions` | `() -> rows` | data_agent（Toolbox） |
| `monthly-subscription-total` | `() -> {items, monthly_total_twd}` | data_agent（Toolbox） |
| `search-notes` | `(keyword: str) -> rows` | data_agent（Toolbox） |
| `add-note` | `(title: str, body: str) -> {id, title}` | data_agent（Toolbox，寫入） |

### 3.3 MCP 契約（wiki-mcp）

| 名稱 | 型別 | 簽章 | 錯誤 |
|---|---|---|---|
| `wiki_search` | tool | `(query: str, top_k: int = 5) -> dict` | 空 query → `ToolError`；DB 掛 → `ToolError` |
| `wiki_ingest` | tool | `(url: str, topic: str = "") -> dict` | `WIKI_ALLOW_INGEST != 1` → `ToolError("唯讀部署…")` |
| `wiki://stats` | resource | `() -> str` | 不拋例外，失敗回字串（resource 拋例外會斷 host 連線） |

transport：`stdio`（預設，本機 host）／`streamable-http`（`MCP_TRANSPORT=http`，`stateless_http=True`、`json_response=True`）。

### 3.4 A2A 契約（research-a2a）

| 端點 | 內容 |
|---|---|
| `GET /.well-known/agent-card.json` | `name=research_agent`；`skills[0].description` 來自 agent 的 `description` |
| A2A `SendMessage` | 由 `RemoteA2aAgent` 呼叫；`timeout=120s`（預設 600 太久） |

concierge 端：`RESEARCH_A2A_URL` 有值 → `RemoteA2aAgent(agent_card=URL + "/.well-known/agent-card.json")`；沒值 → 本機 `Agent(tools=[google_search])`。同一份 `concierge/agent.py`，不用改程式碼切換。

### 3.5 Workflow 契約（daily_digest）

| 節點 | 型別 | 進 | 出 | 路由 |
|---|---|---|---|---|
| `fetch_new_docs` | 純函式（async, 收 `ctx`） | `node_input: Any = None` | 新文件的拼接文字 | `ctx.route = "EMPTY" \| "HAS_DOCS"` |
| `render_empty` | 純函式 | `node_input: str \| None = None` | 「今日無新增知識」 | — |
| `digest_writer` | LLM Agent（`gemini-3.7-flash`） | 上游 output | Markdown 日報 | — |

**兩個一定要照做的細節**（都在本 repo 實測過，見 §8）：路由用 `ctx.route = ...` 設，不要靠 `Event(author=..., route=...)`；下游節點的 `node_input` 一定要容許 `None`。

## 4. 資料模型

`schema.sql`（Supabase SQL Editor 貼整份，可重複執行）：

| 表 | 欄位 | 用途 |
|---|---|---|
| `documents` | `id bigserial`, `source text`, `content text`, `embedding vector(1536)`, `topic text`（Capstone 新增）, `created_at timestamptz`（新增） | 知識庫。Lab 8 建的表只有前四欄，Capstone 用 `alter table ... add column if not exists` 補 |
| `notes` | `id`, `title text unique`, `body`, `tags text[]`, `created_at` | 個人筆記（Toolbox 讀寫） |
| `subscriptions` | `id`, `name text unique`, `monthly_twd int`, `category`, `renews_on date`, `active bool` | 示範業務表（「這個月訂閱花多少」） |
| ADK sessions／events | 由 `DatabaseSessionService` 自動建 | session 持久化（重啟不失憶） |

索引：`documents_embedding_idx`（hnsw, vector_cosine_ops）、`documents_topic_idx`、`documents_id_idx`（`daily_digest` 的 `where id > $1` 要用）。

state key 命名：`last_digest_id` 存在 `~/.capstone_last_digest_id`（單機夠用；多機共用要改成 DB 的 state 表，見 §10）。

## 5. 檔案結構

```
capstone/
├── PRD.md / SPEC.md / walkthrough.md   # 文件三件套
├── ACCEPTANCE.md                       # 驗收矩陣（由 acceptance.py --matrix 產生）
├── pyproject.toml / uv.lock            # uv 專案（google-genai, google-adk[toolbox], mcp[cli], a2a-sdk, asyncpg）
├── schema.sql                          # Phase 1：documents 補欄位 + notes + subscriptions + 種資料
├── wiki_core.py                        # Phase 1：知識層唯一實作（--self-check）
├── ingest.py                           # Phase 1：ingest CLI（--dry-run / --self-check）
├── concierge/
│   ├── __init__.py                     #   adk 靠這行找到 root_agent
│   ├── agent.py                        # Phase 2：團隊組裝（--self-check）
│   └── tools.py                        # Phase 2：search_knowledge / ingest_document（--self-check）
├── digest.py                           # Phase 2：daily_digest workflow（--dry-run / --broken / --self-check）
├── tests/capstone.evalset.json         # Phase 2：四個 eval case（含「不該亂答」）
├── wiki_mcp/server.py                  # Phase 3：自建 MCP server（--self-check）
├── tools.yaml                          # Phase 3：Toolbox 的 SQL 契約（personal-data / -readonly）
├── mcp_config.sample.json              # Phase 3：Antigravity 端設定範本
├── research_service/agent.py           # Phase 4：A2A 服務（--self-check）
├── Dockerfile / .dockerignore          # Phase 4：wiki-mcp 與 research-a2a 共用（⚠️ 未實測 build）
├── deploy.sh                           # Phase 4：部署 runbook（預設 --dry-run）
└── acceptance.py                       # 驗收矩陣＋離線驗收 runner（--offline / --matrix / --self-check）
```

## 6. 環境變數與設定

| 變數 | 用途 | 從哪來 | 預設 |
|---|---|---|---|
| `GEMINI_API_KEY` | Gemini API（ingest／agent／digest） | AI Studio | 無，缺了會 `ValueError: No API key was provided.` |
| `DATABASE_URL` | asyncpg 直連 Supabase | Supabase → Connect → **Session pooler 5432** | 無，缺了會 `RuntimeError: 沒有 DATABASE_URL` |
| `TOOLBOX_URL` | data_agent 連 Toolbox | 本機 `./toolbox` 或 Cloud Run URL | `http://127.0.0.1:5000` |
| `RESEARCH_A2A_URL` | 有值就用遠端研究員 | Phase 4 部署後的服務 URL | 未設＝本機版 |
| `WIKI_ALLOW_INGEST` | wiki-mcp 是否允許寫入 | 部署參數 | `0`（唯讀） |
| `MCP_TRANSPORT` | `http`＝streamable-http；其他＝stdio | 部署參數 | 未設＝stdio |
| `PORT` | Cloud Run 注入 | Cloud Run | `8080` |
| `A2A_PORT` / `A2A_PUBLIC_URL` | agent card 上要寫的 host/port | 本機 8001／部署後 URL | `8001` |
| `DB_PASSWORD` | Toolbox 連 DB | Supabase | 無 |
| `PROJ` / `REGION` | 部署目標 | Lab 5 的專案 | `YOUR_PROJECT_ID` / `us-central1` |
| `SUPABASE_URL` | `deploy.sh` 拿去做 session-db-url secret 與 `--session_service_uri` | Supabase（Session pooler 5432） | 無，`--apply` 會擋 |
| `TOOLBOX_IMAGE` | Toolbox 的官方容器 image | mcp-toolbox.dev 文件 | `us-central1-docker.pkg.dev/database-toolbox/toolbox/toolbox:latest`（⚠️ 未實測） |

`GOOGLE_GENAI_USE_ENTERPRISE`（2026 改名，舊名 `GOOGLE_GENAI_USE_VERTEXAI`）只有走 Vertex 才要設，本 Lab 用 API key 路線。

## 7. 執行流程

```bash
# 0) 環境（一次）
cd capstone
uv sync                                     # 讀 uv.lock，不用 pip、不用 venv
export GEMINI_API_KEY=...  DATABASE_URL='postgresql://...:5432/postgres'

# 0.5) 先跑離線驗收：8 條全綠再開始（不花錢）
uv run acceptance.py --offline

# Phase 1 知識層
# Supabase SQL Editor 貼 schema.sql 執行
uv run ingest.py notes/a2a.md --dry-run     # 看切幾塊，不寫 DB
uv run ingest.py https://a2a-protocol.org --topic protocol

# Phase 2 Agent 團隊
uv run python -m concierge.agent --self-check
uv run adk web                              # 瀏覽器 :8000，左上選 concierge
uv run digest.py --dry-run                  # 看路由，不呼叫 LLM
uv run adk eval concierge tests/capstone.evalset.json --print_detailed_results

# Phase 3 工具層
uv run wiki_mcp/server.py --self-check
uv run mcp dev wiki_mcp/server.py           # Inspector :6274
export DB_PASSWORD=...; ./toolbox --config tools.yaml --port 5000

# Phase 4 串聯部署
uv run uvicorn research_service.agent:a2a_app --port 8001   # 本機先驗 A2A
./deploy.sh --dry-run                       # 先看指令
./deploy.sh --apply                         # 真的部署（會花錢）
export RESEARCH_A2A_URL=https://research-a2a-xxx.run.app
uv run acceptance.py                        # 對照矩陣把 cloud/manual 那幾條走完
```

## 8. 錯誤處理與邊界

| 情境 | 症狀 | 處理方式 |
|---|---|---|
| 用 `python xxx.py` | `ModuleNotFoundError: No module named 'google'` | 一律 `uv run` |
| 沒設 `DATABASE_URL` | `RuntimeError: 沒有 DATABASE_URL。Supabase → …` | `dsn()` 在連線前就擋，訊息直接指路 |
| 用了 6543 pooler | `RuntimeError: 6543 是 Transaction pooler…`（本 repo 主動擋）；沒擋的話是 asyncpg prepared statement 錯 | 改 Session pooler 5432 |
| DSN 前綴混用 | `asyncpg.exceptions...` 或 `invalid dsn` | `dsn()` 自動把 `postgresql+asyncpg://` 換成 `postgresql://`（SQLAlchemy 要 `+asyncpg`，asyncpg 直連不要） |
| documents 沒有 topic 欄 | `column "topic" of relation "documents" does not exist` | 跑 `schema.sql` 的 `alter table ... add column if not exists` |
| 向量傳 list | asyncpg 型別錯誤 | `to_vector()` 轉成 `'[…]'` 字串，SQL 加 `$1::vector` |
| embedding 維度不合 | pgvector：`expected 1536 dimensions, not 3072` | `embed()` 一定要給 `config={"output_dimensionality": EMBED_DIM}`；`wiki_core.py --self-check` 會 assert `EMBED_DIM` 等於 `schema.sql` 的 `vector(N)` |
| DB 掛掉 | agent 工具回 `{"status":"error", ...}`；MCP 端拋 `ToolError` | 不讓 exception 冒到 runner，模型才不會無限重試 |
| 查無資料 | `status=empty` ＋ note 明講「不要自行補答案」 | wiki_agent 的 instruction 對應這個 status |
| `top_k` 被模型亂填 | context 被撐爆 | 程式端 `max(1, min(top_k, 20))` 夾住 |
| workflow 路由沒中 | log：`Node 'x' has conditional/DEFAULT edges but none were matched by the emitted route(s): None. The branch will end.` → 沒輸出、沒例外 | 用 `ctx.route = "..."`；不要在 `Event()` 帶 `author`（ADK 只採納 `author` 為空或等於節點名的事件，見 `_node_runner.py::_track_event_in_context`） |
| 下游節點吃到 None | `pydantic_core._pydantic_core.ValidationError: 1 validation error for str / Input should be a valid string [type=string_type, input_value=None, input_type=NoneType]` | 下游 `node_input: str \| None = None`，或上游節點一定要 return output |
| 沒裝 toolbox extra | `ImportError: ToolboxToolset requires the 'toolbox-adk' package. Please install it using 'pip install google-adk[toolbox]'` | `uv add "google-adk[toolbox]"`（本課不用 pip） |
| mcp 2.x API | `ModuleNotFoundError: No module named 'mcp.server.fastmcp'` | 投影片寫 `FastMCP`，mcp 2.x 改名 `MCPServer`（`from mcp.server.mcpserver import MCPServer`） |
| stdio server 用 print | host 連線壞掉、看不到工具 | log 一律 `file=sys.stderr` |
| 內部服務 403 | `curl` 回 403 | 這是**正確**的（未授權就該 403）；要通就帶 `gcloud auth print-identity-token`，且 audience 必須等於服務 URL |
| agent 不委派自己答 | 回答沒引用、數字是編的 | sub-agent 的 description 寫具體職責＋root instruction 加禁答規則 |
| 部署後 session 不持久 | 重整就失憶，Supabase 沒有 events 表的列，**沒有任何錯誤訊息** | `adk deploy cloud_run` 要帶 `--session_service_uri postgresql+asyncpg://…`（少了就是記憶體 session）。`deploy.sh` 第 5 段已經帶 |
| 部署後 data_agent 查不到表 | concierge 打 `http://127.0.0.1:5000` 連線被拒 | `adk deploy cloud_run` **沒有** `--set-env-vars`，下游 URL 只能部署完用 `gcloud run services update --update-env-vars TOOLBOX_URL=…,RESEARCH_A2A_URL=…` 回填。`deploy.sh` 第 5 段已經做 |
| A2A 名片寫 localhost | 別的 agent 抓到卡片連不上，也沒有錯誤 | research-a2a 部署完回填 `A2A_PUBLIC_URL=<自己的服務 URL>`。`deploy.sh` 第 3 段已經做 |

## 9. 驗證方式

| 層次 | 怎麼跑 | 這台機器實測 |
|---|---|---|
| 單支程式 | `uv run <檔案> --self-check` | ✅ `wiki_core.py`／`ingest.py`／`concierge.agent`／`concierge.tools`／`digest.py`／`wiki_mcp/server.py`／`research_service/agent.py`／`acceptance.py` 全部通過 |
| 一次全跑 | `uv run acceptance.py --offline` | ✅ 8 通過 / 0 失敗 |
| workflow 真的跑 | `uv run digest.py --self-check`（跑真的 ADK Runner，EMPTY 分支不呼叫 LLM） | ✅ |
| 故意失敗 | `uv run digest.py --broken` | ✅ 印出靜默失敗的空輸出＋pydantic ValidationError |
| 部署腳本 | `bash -n deploy.sh` ＋ `./deploy.sh --dry-run` | ✅ |
| 設定檔 | `uv run --with pyyaml python -c "..."`（tools.yaml 7 個文件）、`json.load`（evalset、mcp_config） | ✅ |
| A2A app 組裝 | `uv run python -c "import research_service.agent as m; print(type(m.a2a_app))"` → `Starlette` | ✅ |
| 雲端 | `deploy.sh --apply` ＋ `acceptance.py` 的 cloud/manual 條目 | ⚠️ 未實測：沒有 GCP 專案、沒有 Supabase 實例、沒有 API key |

> ⚠️ 未實測（本文件與 walkthrough 對應處都有標記）：所有真的呼叫 Gemini API 的路徑（embed／fetch_text／summarize／LLM 節點）、Supabase 連線與 SQL 執行、`gcloud` 部署與 IAM、`docker build`、MCP Inspector 畫面、`adk eval` 的實際評分。型別與事件欄位是查已安裝 SDK（google-adk 2.7.1、google-genai 2.20.0、mcp 2.x）確認的。

## 10. 已知限制與升級路徑

| 位置 | 天花板 | 升級路徑 |
|---|---|---|
| `digest.py` 的 `last_digest_id`（`# ponytail:`） | 進度存在家目錄的一個檔案，多機／多實例會各自為政 | 換成 DB 的 `state` 表，或用 ADK session state |
| `wiki_core.chunk` | 固定長度切塊，會切斷語意邊界 | 換成按標題／段落切（Markdown heading split），或用語意切塊 |
| `format_hits` 的 `min_sim=0.25` | 門檻是猜的，跟 embedding 模型綁在一起 | 用你自己的 20 題問答集掃一遍找最佳門檻 |
| 檢索只有向量 | 專有名詞（型號、指令名）向量檢索容易漏 | 加 `ILIKE` 關鍵字檢索做混合檢索，再 rerank |
| `wiki_mcp` 的 `WIKI_ALLOW_INGEST` | 用環境變數當權限開關，粒度只有「整個服務」 | 走 MCP 的 OAuth（投影片 449-4）或部署兩份服務（讀／寫各一） |
| `concierge` 沒有記憶 | 只有 session 內記憶，換 session 就忘了偏好 | 接 Agent Engine 的 Memory Bank（M10）或自建 `user:` state |
| ingest 只吃文字 | PDF／YouTube／圖片進不來 | `fetch_text` 加 `document`／`video` content block（M1 的多模態） |
| 沒有 CI | 改 instruction 後靠人記得跑 eval | evalset 進 CI（投影片 449-2） |
| `Dockerfile` | 沒 build 過，也沒瘦身 | 先 `docker build .` 驗，再看冷啟動要不要換 slim base／拆依賴 |
