# Lab 8 SPEC：旅館查詢 Agent（三層整合）

## 1. 架構

三個程序、一個資料庫。箭頭是真實資料流，虛線框是程序邊界。

```
┌─ 你的終端機 / 瀏覽器 ────────────────────────────────────────────────┐
│  http://localhost:8000  (adk web UI)                                 │
└───────────────┬──────────────────────────────────────────────────────┘
                │ HTTP
┌───────────────▼─ 程序 A：adk web（uv run adk web ...）───────────────┐
│  Runner                                                              │
│   ├─ root_agent (gemini-3.7-flash)  hotel_agent/agent.py             │
│   │    ├─ ToolboxToolset("hotel-tools") ──────┐  HTTP :5000          │
│   │    └─ search_hotels_semantic()  ──────┐   │  （加分題 A）        │
│   └─ DatabaseSessionService ───────┐      │   │                      │
│        (postgresql+asyncpg://)     │      │   │                      │
└────────────────────────────────────┼──────┼───┼──────────────────────┘
                                     │      │   │
┌────────────────────────────────────┼──────┼───▼─ 程序 B：toolbox ────┐
│  ./toolbox --config tools.yaml     │      │   MCP server :5000       │
│   ├─ source: course-db（連線池）   │      │                          │
│   ├─ tool: search-hotels-by-city   │      │   SQL 寫死在 yaml，       │
│   └─ tool: get-price-stats         │      │   模型只能給參數          │
└────────────────────────────────────┼──────┼───┬──────────────────────┘
                                     │      │   │ postgres 5432
┌────────────────────────────────────▼──────▼───▼─ Supabase Postgres ──┐
│  sessions / events / app_states…   hotels（含 embedding vector(1536)）│
│  ← ADK 自動建表 →                  ← schema.sql 建 →                 │
└──────────────────────────────────────────────────────────────────────┘
                     ▲
                     │ 加分題 B：Antigravity → https://mcp.supabase.com/mcp
                     │            ?read_only=true&project_ref=...（唯讀、自由 SQL）
```

三條路徑都連同一個 Supabase 專案，但角色不同：

- **Toolbox（程序 B）** —— 業務查詢。SQL 固定、參數開放，正式流量走這條。
- **DatabaseSessionService（程序 A 內）** —— 對話狀態。ADK 自己建表、自己讀寫，你不碰 SQL。
- **`search_hotels_semantic`（程序 A 內，加分）** —— 語意搜尋。要現算 query 向量，所以直接 asyncpg 連線，不經 Toolbox。

## 2. 元件與職責

| 元件 | 檔案 | 職責 | 不負責什麼 |
|---|---|---|---|
| Schema | `schema.sql` | 建 `hotels`＋兩個索引＋種 10 筆資料；建選配的 `documents` | 不建 sessions／events（ADK 自動建） |
| 工具契約 | `tools.yaml` | 定義 source、兩個 SQL 工具、一個 toolset | 不放密碼（走 `${DB_PASSWORD}`） |
| 設定體檢 | `preflight.py` | 啟動前抓 `$N`／source／toolset／env 的錯 | 不連資料庫、不驗 SQL 語意 |
| Agent | `hotel_agent/agent.py` | 掛 toolset、寫 instruction、組 `root_agent` | 不自己連資料庫、不自己寫 SQL |
| 語意搜尋工具 | `hotel_agent/rag_tool.py` | query→向量→pgvector top-5，型別轉成可 JSON | 不負責種向量 |
| 向量種資料 | `seed_embeddings.py` | 批次嵌入 `description` 寫回 `embedding`；`--search` 驗收 | 不切塊（描述本來就短） |
| Sessions | ADK `DatabaseSessionService` | 對話與 state 落地 | 不是 Memory（跨 session 記憶是 M7 的 Memory Bank） |

## 3. 介面契約

### 3.1 Toolbox 工具（模型看到的工具面）

| 工具 | 參數 | 回傳欄位 | SQL |
|---|---|---|---|
| `search-hotels-by-city` | `city: string`、`max_price: integer` | `name, price_twd, rating, tags` | `SELECT ... WHERE city = $1 AND price_twd <= $2 ORDER BY rating DESC LIMIT 10` |
| `get-price-stats` | 無 | `city, hotel_count, avg_price, min_price, max_price` | `SELECT ... GROUP BY city ORDER BY avg_price` |

規則：`statement` 裡的 `$N` 依 `parameters` 的**順序**對應（`$1` = 第一個參數）。名稱對不上不會報錯，只會查錯 —— 這是 `preflight.py` 檢查的第一件事。

### 3.2 ADK FunctionTool（加分題 A）

```python
async def search_hotels_semantic(query: str) -> dict
# 回傳 {"status": "success",
#       "hotels": [{"name", "city", "price_twd", "rating", "description", "sim"}, ...]}  # 最多 5 筆
```

`query` 的參數說明寫在 docstring 的 `Args:` 裡 —— ADK 是拿 docstring 給模型看的，docstring 寫爛等於工具說明寫爛。

### 3.3 本地函式簽章（`seed_embeddings.py`）

```python
to_vector(values, dim=1536) -> str          # [0.1,0.2,...]；長度不符丟 ValueError
embed_text(row) -> str                      # 名稱＋城市＋價格＋標籤＋描述，一起嵌入
build_updates(rows, res) -> list[tuple]     # [(id, vector_str), ...]；數量不符丟 ValueError
embed(contents)                             # google-genai embed_content，dim=1536
```

### 3.4 HTTP 端點

| 端點 | 用途 |
|---|---|
| `http://127.0.0.1:5000/mcp` | Toolbox 的 MCP endpoint（給 MCP host 用） |
| `http://127.0.0.1:5000/api/toolset/hotel-tools` | 工具清單 JSON（給 curl 驗收與 `ToolboxToolset` 用） |
| `http://localhost:8000` | `adk web` UI |

> ⚠️ 未實測：Toolbox 的 HTTP 路徑（`/api/toolset/...`）我沒有實際跑過 v1.9.0 確認，本機起不了 Toolbox（需要下載執行檔與真的資料庫）。curl 404 的話用 `./toolbox --config tools.yaml --log-level debug` 看它印出來的路由。

## 4. 資料模型

```sql
create table hotels (
  id          bigserial primary key,
  name        text not null,
  city        text not null,
  price_twd   integer not null check (price_twd > 0),
  rating      numeric(2,1) default 4.0 check (rating >= 0 and rating <= 5),
  tags        text[] default '{}',
  description text,                    -- 語意搜尋原文
  embedding   vector(1536),            -- gemini-embedding-2 截斷至 1536
  created_at  timestamptz default now(),
  constraint hotels_name_city_key unique (name, city)
);
create index hotels_city_price_idx  on hotels (city, price_twd);
create index hotels_embedding_idx   on hotels using hnsw (embedding vector_cosine_ops);
```

設計理由（這張表 Lab 9／10／Capstone 都吃，所以一次定對）：

| 決定 | 為什麼 |
|---|---|
| `unique (name, city)` | 種資料要能重跑。沒有它，`schema.sql` 執行兩次資料就變兩倍，之後查出來的平均房價全錯 |
| `check (price_twd > 0)` | Lab 9 會有另一個 agent 寫資料進來。約束放在資料庫，不放在應用程式 —— 應用程式有三個，資料庫只有一個 |
| `numeric(2,1)` | 抄投影片 8.2。注意它最大只到 9.9，配上 `check <= 5` 才擋得住 `48` 這種手殘 |
| `embedding` 可為 NULL | 資料先進來、向量後補（`seed_embeddings.py` 只處理 `embedding is null` 的列）。檢索 SQL 因此必須加 `where embedding is not null` |
| `vector(1536)` 不是 3072 | 投影片 8.5：Matryoshka 截斷省一半空間、精度損失極小。程式端 `output_dimensionality: 1536` 必須跟這裡一致 |
| HNSW + `vector_cosine_ops` | 十萬級以下無腦選 HNSW；`gemini-embedding` 配餘弦距離 `<=>`，運算子跟索引的 ops class 必須成對，寫錯索引不會被用到（只是變慢，不會報錯） |
| `created_at` | 投影片沒有。Lab 10 要看「哪些資料是 agent 寫進來的」時會需要 |

ADK 自動建的表（不要自己建、不要改）：`sessions`、`events`、`app_states`、`user_states`。首次帶 `--session_service_uri` 啟動時建立。

state key 命名（`sessions.state` JSON 欄位）：Lab 8 不手動寫 state，預算等資訊由模型記在對話歷史（`events`）裡。要在 Lab 9 之後跨 agent 共用，再用 `user:budget_twd` 這種 `user:` 前綴的 key。

## 5. 檔案結構

```
lab8/
├── PRD.md                    需求、學習目標、驗收清單
├── SPEC.md                   本檔：架構與契約
├── walkthrough.md            一步一步教學（先讀這個）
├── schema.sql                hotels＋索引＋種資料（Supabase SQL Editor 貼）
├── tools.yaml                Toolbox 工具契約（會進 git，不放密碼）
├── preflight.py              tools.yaml 離線體檢（--self-check）
├── seed_embeddings.py        description→embedding；--search 驗收（--self-check）
├── .env.example              環境變數範本（cp 成 .env，.env 別進 git）
└── hotel_agent/
    ├── __init__.py           from . import agent（ADK 靠這行找 agent）
    ├── agent.py              ToolboxToolset＋instruction＋root_agent
    └── rag_tool.py           加分題 A：pgvector 語意搜尋 FunctionTool（--self-check）
```

## 6. 環境變數與設定

| 變數 | 用途 | 從哪來 | 預設 |
|---|---|---|---|
| `GEMINI_API_KEY` | agent 與 embedding 呼叫 | aistudio.google.com/apikey | 無，必填 |
| `DB_PASSWORD` | Toolbox 連 Supabase（`tools.yaml` 的 `${DB_PASSWORD}`） | Supabase 建專案時設的密碼 | 無，必填；**必須 export，Toolbox 不讀 .env** |
| `DB_URL_RAW` | `seed_embeddings.py` 與 `rag_tool.py` 的 asyncpg 原生連線 | Dashboard → Connect → Session pooler，前綴 `postgresql://` | 無，加分題 A 必填 |
| `ADK_SESSION_URI` | `adk web --session_service_uri` 用 | 同上，但前綴 `postgresql+asyncpg://` | 無，步驟 5 必填 |
| `TOOLBOX_URL` | agent 要連的 Toolbox 位址 | 本機自己起的 | `http://127.0.0.1:5000` |
| `LAB8_RAG` | `=1` 才掛語意搜尋工具 | 加分題 A 自己 export | 未設 = 不掛 |

兩條連線字串**只差前綴**（`postgresql://` vs `postgresql+asyncpg://`）：前者給 asyncpg 直接用，後者是 SQLAlchemy 的 dialect+driver 寫法。密碼有 `@ : / ? # %` 這些字元的要 percent-encode（`uv run python -c "import urllib.parse,sys;print(urllib.parse.quote(sys.argv[1],safe=''))" '你的密碼'`）。

## 7. 執行流程

```bash
# 0) 專案與相依
uv init --bare lab8 && cd lab8
uv add "google-adk[toolbox]" google-genai asyncpg   # preflight.py 的 pyyaml 走 PEP 723 檔頭

# 1) schema：Supabase Dashboard → SQL Editor → 貼 schema.sql → Run
uv run --with sqlglot python -c \
  "import sqlglot;sqlglot.parse(open('schema.sql').read(),read='postgres');print('SQL 語法 OK')"

# 2-3) 工具層
uv run preflight.py                       # 先體檢設定檔
export DB_PASSWORD='...'                  # Toolbox 只讀環境變數
./toolbox --config tools.yaml             # :5000（macOS 若被 AirPlay 佔用加 --port 5001）
curl -s http://127.0.0.1:5000/api/toolset/hotel-tools | uv run python -m json.tool

# 4) agent（另一個終端機）
uv run adk web                            # sessions 在記憶體 —— 先體驗會失憶的版本

# 5-6) sessions 落地
export ADK_SESSION_URI='postgresql+asyncpg://postgres.<ref>:<pw>@aws-0-<region>.pooler.supabase.com:5432/postgres'
uv run adk web --session_service_uri "$ADK_SESSION_URI"

# 7) 加分題 A
uv run seed_embeddings.py
uv run seed_embeddings.py --search "想泡溫泉又安靜"
LAB8_RAG=1 uv run adk web --session_service_uri "$ADK_SESSION_URI"
```

## 8. 錯誤處理與邊界

| 情境 | 症狀 | 處理方式 |
|---|---|---|
| `tools.yaml` 的 `$N` 與 parameters 不符 | Toolbox 啟動成功，但工具查出錯的結果或呼叫時報參數錯 | `preflight.py` 在啟動前擋下來（exit 1） |
| `DB_PASSWORD` 沒 export | Toolbox 啟動時 source 初始化失敗，訊息含 password authentication failed | `preflight.py` 會印 `! 環境變數 DB_PASSWORD 目前是空的` |
| pgvector 沒啟用 | `ERROR: type "vector" does not exist` | `create extension if not exists vector;`（`schema.sql` 第一行就是） |
| embedding 維度不符 | `ERROR: expected 1536 dimensions, not 3072` | `config={"output_dimensionality": 1536}`；`to_vector()` 會先在 Python 端擋下並說明原因 |
| 向量參數沒加 `::vector` | asyncpg 不認得 pgvector 自訂型別，丟型別相關錯誤（訊息依版本不同） | SQL 一律寫 `$1::vector` |
| 用 Transaction pooler（6543） | 連得上，但間歇性 `prepared statement "__asyncpg_stmt_x__" does not exist` | 改用 Session pooler（5432） |
| driver 前綴寫成 `postgres://` | `sqlalchemy.exc.InvalidRequestError: The asyncio extension requires an async driver to be used.` | `postgresql+asyncpg://` |
| 密碼含特殊字元未編碼 | 連線字串被切錯，報 host／port 解析失敗（`nodename nor servname provided` 之類） | percent-encode 密碼 |
| Toolbox 沒起來就開 agent | 工具清單是空的；呼叫時連線被拒（httpx 連線錯誤） | 先確認 curl 通，再開 `adk web` |
| `numeric` 欄位直接回傳給模型 | `TypeError: Object of type Decimal is not JSON serializable` | `rag_tool.jsonable()` 轉 float（Toolbox 已幫你處理，自寫工具要自己處理） |
| 種資料重跑 | 資料變兩倍、統計全錯 | `unique (name, city)` ＋ `on conflict do nothing` |
| 免費層連線吃滿 | 連線被拒或 timeout | 關掉沒用的連線；Cloud Run 場景把 pool_size 設 2–5（8.4 踩坑清單） |

邊界條件：`tags` 可能是 NULL（`embed_text` 用 `row["tags"] or []`）；`embedding` 為 NULL 的列不能進檢索結果（`where embedding is not null`）；`get-price-stats` 在空表時回 0 列（不是 0 值）。

## 9. 驗證方式

**離線自我檢查（我實際跑過的）**

```bash
uv run preflight.py --self-check                    # → self-check ok
uv run seed_embeddings.py --self-check              # → self-check ok
uv run python hotel_agent/rag_tool.py --self-check  # → self-check ok
uv run preflight.py                                 # → OK：可以啟動 Toolbox 了
uv run --with sqlglot python -c "import sqlglot;sqlglot.parse(open('schema.sql').read(),read='postgres')"
```

`preflight.py --self-check` 驗的是六種真的會發生的設定錯（`$N` 多一個、少一個、source 指錯、toolset 列到不存在的工具、`kind` 拼錯、缺 `statement`）；`seed_embeddings.py --self-check` 用 `SimpleNamespace` 假的 embedding 回應驗維度守衛與 `rows→params` 對位；`rag_tool.py --self-check` 驗 Decimal→float 與 SQL 裡的 `::vector`。三者都不連網、不需要 key、不花錢。

**線上驗收**：見 PRD 第 6 節的勾選清單。核心兩條是「agent 報的價格與 SQL 查出來的一致」與「重啟後追問答得出預算」。

**沒辦法離線驗的**（需要 Supabase 專案／Toolbox 執行檔／API key）：

- `schema.sql` 能不能在真的 Postgres＋pgvector 上跑（sqlglot 只驗語法樹，不驗 `hnsw` 這個 access method 存不存在）
- Toolbox v1.9.0 的下載網址、`--config` 行為、HTTP 路由
- `ToolboxToolset` 與 Toolbox 的實際握手
- `DatabaseSessionService` 自動建表與 `--session_service_uri` 的持久化行為
- `gemini-embedding-2` 的實際回傳維度與 `models.embed_content` 的參數
- Supabase MCP 的 OAuth 流程（加分題 B）

## 10. 已知限制與升級路徑

| 限制 | 現況（`ponytail:` 註解位置） | 升級路徑 |
|---|---|---|
| 嵌入一次全撈 | `seed_embeddings.py: seed()` | 上千筆要分批（一次 100），避免單次 payload 過大 |
| 每次工具呼叫都開新連線 | `rag_tool.search_hotels_semantic` | 換成 `asyncpg.create_pool()` 的全域 pool；免費層連線少的時候更有感 |
| 語意搜尋沒有 metadata 過濾 | `rag_tool.SEARCH_SQL` | 加 `and city = $2 and price_twd <= $3` —— 這正是「資料與向量同庫」的價值（8.5） |
| `preflight.py` 不驗 SQL 語意 | `preflight.check()` | 要驗 SQL 就得連 DB 做 `prepare`；目前刻意只做離線純文字檢查 |
| Toolbox 跑在本機 | 步驟 3 | Lab 10 部署上 Cloud Run，`server_url` 換服務網址＋ID token header，多 agent 共用一個工具層 |
| Toolbox 用 `postgres` 使用者 | `tools.yaml` 的 source | 正式環境開一個只有 `SELECT` 權限的 DB 帳號（8.6 生產建議） |
| 沒有 Memory | —— | sessions 只在同一個 session 內記得；跨 session 的偏好要 Memory Bank 或自建表（8.1 場景②） |
