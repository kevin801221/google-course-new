# Capstone 走一遍：個人 LLM Wiki ＆ Assistant System

> 2-4 天（四個 Phase）｜綜合 M1-M10 全部：Gemini API ＋ NotebookLM ＋ MCP ＋ ADK multi-agent ＋ pgvector ＋ Toolbox ＋ A2A ＋ Cloud Run

做完你會有一個「會自己工作的系統」：問它知識庫、叫它研究並入庫、查自己的訂閱、每天收日報，而且手機瀏覽器打開就能用。

```
$ uv run acceptance.py --offline
[PASS] P1-1 知識層核心邏輯（切塊／向量／DSN 防呆）
[PASS] P1-2 ingest 管線可跑、dry-run 不寫 DB
[PASS] P2-1 團隊接線：root 禁答、google_search 獨占、模型分級
[PASS] P2-2 工具契約：docstring、上限夾住、DB 掛掉不拋例外
[PASS] P2-3 摘要工作流：EMPTY 分支不呼叫 LLM、路由字串正確
[PASS] P3-1 wiki-mcp 工具邏輯與權限閘（唯讀部署擋住 ingest）
[PASS] P3-2 Toolbox 設定檔是合法 YAML 且 toolset 有列到工具
[PASS] P4-2 部署腳本順序正確（工具→專員→入口）

離線驗收：8 通過 / 0 失敗
```

```
$ uv run adk web        # 瀏覽器問：我知識庫裡關於 A2A 的重點？
concierge → transfer_to_agent(wiki_agent) → search_knowledge("A2A 的重點")
wiki_agent：Agent Card 在 /.well-known/agent-card.json；Task 有狀態機（來源：notes/a2a.md）
```

**這個 Lab 不教新 API**。四個 Phase 都是把你做過的東西接上正確的線，難度全在接線處：委派邊界、權限邊界、成本邊界、失敗邊界。每一步都是「動手 → 為什麼 → 驗收」，驗收沒過不要往下走 —— 四層系統疊起來之後 debug 成本是指數的。

**建議節奏**：Phase 1 半天、Phase 2 一天、Phase 3 半天、Phase 4 一天。每個 Phase 結束都有可展示的中間成果，時間到就先交成果再往下。

---

## 步驟 0：前置檢查（15 分）

**動手**

```bash
cd capstone
uv sync                      # 讀 uv.lock 裝好依賴，不用 pip、不用 venv、不用 activate

export GEMINI_API_KEY="AIza..."                    # Lab 1 那把（AI Studio）
export DATABASE_URL='postgresql://postgres.xxx:PW@aws-0-ap-northeast-1.pooler.supabase.com:5432/postgres'
                                                    # Lab 8 那個 Supabase，Session pooler 5432
export PROJ=$(gcloud config get-value project)      # Lab 5 的專案（Phase 4 才要）
```

前十個 Lab 的產出對照表（哪個 Phase 要用哪一個）在 `PRD.md` §9.1。手邊要有的四樣：Lab 4 的 NotebookLM 筆記本、Lab 5 的 GCP 專案、Lab 8 的 Supabase、Lab 9 學過的 `to_a2a()`。

**為什麼**

- **為什麼一定 `uv run`**：這個目錄的依賴記在 `pyproject.toml` + `uv.lock`。用 `python digest.py` 會抓到系統 Python，第一行就 `ModuleNotFoundError: No module named 'google'`。
- **為什麼是 5432 不是 6543**：Supabase 給你兩個 pooler。6543（Transaction pooler）與 asyncpg 的 prepared statement 互斥，症狀是連上之後查詢隨機炸掉——最難 debug 的那種。本 repo 的 `wiki_core.dsn()` 直接在連線前擋掉 6543，這樣你會看到一句人話而不是 asyncpg 的內部錯誤。
- **為什麼 key 用 export 不寫進程式**：硬編碼 commit 上 GitHub 幾小時內就會被掃 key 的機器人撈走。Phase 4 上雲之後改吃 Secret Manager，程式碼一個字都不用改。

**驗收**

```bash
uv run acceptance.py --offline
```

期望最後一行是 `離線驗收：8 通過 / 0 失敗`。這 8 條不需要 key、不連網、不花錢——**現在就該全綠**，因為它們驗的是本 repo 的骨架邏輯。有紅的先修，不要往下走。

```bash
echo $GEMINI_API_KEY | cut -c1-4     # 要印出 AIza
echo $DATABASE_URL | grep -o ':[0-9]*/' # 要印出 :5432/
```

> 💡 **啊哈：這整個 Capstone 有 1,135 行程式，卻沒有一個你沒見過的套件**
> 四個第三方套件（`google.genai` / `google.adk` / `mcp` / `asyncpg`）分別在 Lab 1、7、6、8 見過；唯一算得上「新演算法」的是 `wiki_core.chunk()` 的 11 行。其餘 1,124 行全是接線：誰能呼叫誰、誰有什麼權限、失敗時回什麼字串。
> 接線 : 新邏輯 = 102 : 1 —— 這就是「系統的價值來自接線，不是來自單一元件」的字面意思。
> **動手看**：`uv run aha.py --parts` → 三張表：每個檔案來自哪個 Lab、每個套件第一次在哪個 Lab 見到、以及「其中前面 Lab 沒見過的：0」。

---

# Phase 1 — 知識層：NotebookLM ＋ pgvector 雙引擎

> 目標：兩個知識庫就緒、ingest 管線可用。中間成果＝`uv run ingest.py <url>` 真的把東西寫進 `documents`，而且兩邊各問同一題能看出「兩種 RAG 的個性」。

## 步驟 1.1：建表（`schema.sql`）（20 分）

**動手**：Supabase Dashboard → SQL Editor → 貼 `schema.sql` 整份 → Run。

```sql
-- 關鍵三行（完整版在 schema.sql）
alter table documents add column if not exists topic      text default '';
alter table documents add column if not exists created_at timestamptz default now();
create index if not exists documents_id_idx on documents (id);
```

**為什麼**

- **為什麼是 `alter table` 而不是 `create table`**：`documents` 是 Lab 8 建的，只有 `(id, source, content, embedding)`。Capstone 需要 `topic`（分類過濾）與 `created_at`（日報要知道「昨天新增的」）。直接 `create table` 你會得到 `relation "documents" already exists`；直接寫 insert 會得到 `column "topic" of relation "documents" does not exist`。
- **為什麼 `documents_id_idx`**：`daily_digest` 每天跑 `where id > $1`。沒索引時資料量小看不出來，長到幾萬列就變全表掃描——這種效能問題不會報錯，只會讓你的日報越來越慢。
- **為什麼 `notes` 與 `subscriptions` 要 unique constraint**：種資料的 SQL 你一定會重跑（貼錯、改欄位）。有 `on conflict ... do nothing` 才能重跑而不是變成兩倍資料。

**驗收**：`schema.sql` 最後三行 select 的輸出就是驗收條件。

```sql
select count(*) as doc_chunks, count(distinct source) as sources from documents;
select sum(monthly_twd) as monthly_total from subscriptions where active;  -- 期望 2309
select column_name from information_schema.columns
 where table_name = 'documents' and column_name in ('topic','created_at');  -- 期望兩列
```

第三個 query 回兩列才算成功。回 0 列＝`alter table` 沒跑到（你可能只貼了一半）。

> ⚠️ 未實測：我沒有 Supabase 實例，這幾段 SQL 沒有真的在 Postgres 上跑過。語法是照 Lab 8 已驗證的寫法延伸的。

## 步驟 1.2：ingest 管線先 dry-run（25 分）

**動手**：先寫一份本機筆記，再用 `--dry-run` 看它會怎麼切。

```bash
mkdir -p notes
cat > notes/a2a.md <<'EOF'
# A2A 1.0 筆記
Agent Card 放在 /.well-known/agent-card.json，是 agent 的名片。
Task 有生命週期狀態機：submitted / working / completed / failed。
跨框架委派用 SendMessage；ADK 端用 to_a2a() 曝露、RemoteA2aAgent 消費。
EOF

uv run ingest.py notes/a2a.md --dry-run
```

期望輸出：

```
來源：notes/a2a.md｜topic：(無)｜字數：182｜切成 1 塊
--- chunk 0 (181 字) ---
# A2A 1.0 筆記 …
dry-run：沒有呼叫 embedding、沒有寫入 DB、沒有花錢
```

（最後那行走 stderr，實際終端機上可能先印出來——順序不一樣不代表壞了。）

然後真的入庫（這一步開始花錢，但少於 $0.01）：

```bash
uv run ingest.py notes/a2a.md --topic protocol
uv run ingest.py https://a2a-protocol.org --topic protocol
```

**為什麼**

- **為什麼 fetch 網頁用 `url_context` 而不是 `httpx` + BeautifulSoup**：現代網頁的正文藏在 JS 裡，抓回來的 HTML 一半是導覽列跟廣告。丟給 `gemini-3.5-flash-lite` 配 `tools=[{"type": "url_context"}]` 讓它抽正文，一行搞定而且結果乾淨。這種高頻雜活永遠用最便宜的模型（$0.30/1M），差別在帳單不在品質。
- **為什麼要有 `overlap`**：切塊邊界會把句子切兩半，兩塊都失去語意，兩塊都查不到。150 字重疊是保險。反過來，最後一塊如果整塊都落在 overlap 區裡就是純重複，`chunk()` 會把它丟掉——不丟的話同一段內容會在檢索結果裡出現兩次，佔掉 top_k 的名額。
- **為什麼 `--dry-run` 是必要的而不是「加分功能」**：ingest 一跑就是「呼叫 API + 寫 DB」兩個副作用。第一次跑就對著 50 篇文章跑，切壞了你要清 DB。先 dry-run 看塊數與內容，是這整個 Lab 裡最划算的一個 flag。
- **為什麼向量要轉成字串**：pgvector 的 literal 是 `'[0.1,0.2]'`。直接把 Python list 丟給 asyncpg 會是型別錯誤；SQL 那邊也一定要 `$4::vector` 做顯式轉換。

**驗收**

```bash
uv run wiki_core.py --self-check     # → wiki_core self-check OK
uv run ingest.py --self-check        # → ingest self-check OK
```

真的入庫之後，回 Supabase 查：

```sql
select source, topic, length(content) as len, created_at from documents order by id desc limit 5;
```

看得到剛剛那兩個 source、`topic` 是 `protocol`、`embedding` 不是 null。

> ⚠️ 未實測：`uv run ingest.py notes/a2a.md --topic protocol` 這條要 API key ＋ Supabase，我沒有跑過。兩個 `--self-check` 是實測通過的（它們把 fetch／embed／DB 全換成假物件）。

## 步驟 1.3：雙庫對照（20 分）

**動手**：把同一份內容也放進 NotebookLM（Lab 4 那個筆記本），然後兩邊問同一題。

```bash
uv run ingest.py notes/a2a.md --topic protocol   # 輸出最後會印「給 NotebookLM 的摘要」
# 把那段摘要貼進 NotebookLM 的筆記本（或用本機的 notebooklm-mcp 存）
```

兩邊問同一題：「A2A 的 Agent Card 放在哪裡？」

**為什麼**

- **為什麼要兩個庫**：它們的個性不同。NotebookLM 是人工策展、答案帶引用卡、可以生播客與心智圖，適合「重要文件」；pgvector 是程式自動餵、毫秒檢索、可以 `where topic = 'protocol'` 條件過濾，適合「高頻雜資料」。用錯邊的代價是：把 500 篇網頁剪藏塞進 NotebookLM，它的策展價值就沒了；把讀書筆記只放 pgvector，你就失去引用與多媒體。
- **為什麼摘要進 NotebookLM、全文進 pgvector**：全文對 NotebookLM 是雜訊（來源上限 50 筆），摘要對 pgvector 是資訊損失（檢索需要原文細節）。同一份輸入寫兩邊，各給它們要的粒度。
- **為什麼 notebooklm-mcp 不上雲**：它靠 cookie 認證。cookie 放進 Cloud Run 容器＝把你的 Google 帳號權限交給一個公開服務，而且 cookie 會過期，服務會在你不知道的時候壞掉。雲端的知識查詢一律走 pgvector。

**驗收**：對照表自己填一次（這是 Phase 1 的真正產出）。

| | NotebookLM | pgvector（wiki_agent） |
|---|---|---|
| 答案內容 | | |
| 引用長什麼樣 | | |
| 查不到時的行為 | | |
| 回應時間 | | |

pgvector 側可以先用一行驗（不用等 Phase 2）：

```bash
uv run python -c "
import asyncio, wiki_core
print(asyncio.run(wiki_core.search_impl('Agent Card 放在哪裡', 3)))"
```

期望 `status='success'`，`hits[0]['source']` 是 `notes/a2a.md`，`score` > 0.5。

> ⚠️ 未實測：這條要 API key ＋ Supabase。

> 💡 **啊哈：「知識庫裡沒有」不是資料庫告訴你的，是你用一個數字造出來的**
> `order by embedding <=> $1::vector limit $2` 永遠會回滿 `top_k` 列。就算庫裡只有滷肉飯食譜，它也會排出「最像」的五段給你。`status="empty"` 這個狀態完全來自 `wiki_core.format_hits()` 的 `min_sim=0.25`——把它拿掉，`wiki_agent` 就會拿相似度 0.03 的雜訊當來源引用，語氣一樣自信。
> 也就是說：Phase 2 那條「查不到就要說查不到」的規則，真正的實作位置在 Phase 1 的一個浮點數。
> **動手看**：`uv run aha.py --threshold` → 同一批四列結果，min_sim 0.0 / 0.25 / 0.5 / 0.9 分別留下 4 / 2 / 1 / 0 筆，只有最後一列的 status 是 `empty`。

---

# Phase 2 — Agent 團隊：ADK Multi-Agent

> 目標：四個 agent 本機跑通＋evalset 全綠。中間成果＝`adk web` 裡問三種問題，三種都委派給正確的專員。

## 步驟 2.1：組隊（`concierge/agent.py`）（40 分）

**動手**

```bash
uv run python -m concierge.agent --self-check     # 先驗接線
uv run adk web                                     # 瀏覽器 http://localhost:8000，左上角選 concierge
```

團隊長這樣（完整版在 `concierge/agent.py`）：

| agent | 模型 | 工具 | 一句話職責 |
|---|---|---|---|
| `concierge`（root） | `gemini-3.7-flash` | 無（只委派） | 理解、委派、彙整 |
| `research_agent` | `gemini-3.7-flash` | `google_search`（獨占） | 上網研究、交叉驗證、寫報告 |
| `wiki_agent` | `gemini-3.7-flash` | `search_knowledge`, `ingest_document` | 查知識庫、入庫 |
| `data_agent` | `gemini-3.5-flash-lite` | `ToolboxToolset(personal-data)` | 查訂閱／筆記 |

**為什麼**

- **為什麼 root 的 instruction 要寫「不得自己回答任何知識性問題」**：不寫的話 root 會自己答。它是 LLM，看到問題的本能是回答，而且答得很流暢——你會以為系統在工作，其實 `wiki_agent` 從來沒被叫到，答案全是幻覺。這條禁令是整個系統可信度的地基。
- **為什麼 description 要寫具體**：root 決定委派給誰，唯一依據是 sub-agent 的 `description`（它看不到別人的 instruction）。寫「處理資料相關問題」這種模糊描述，你會看到投影片 447 頁那個症狀：agent 不委派、自己亂答。寫「查詢訂閱、書單、專案清單等個人結構化資料」它就知道什麼時候該叫你。
- **為什麼 `google_search` 必須獨占一個 agent**：ADK 的硬限制（附錄 D ①）。跟其他工具同掛，**建構的時候不會報錯**，執行時才炸——所以 `concierge/agent.py` 的 `--self-check` 直接 assert `research_agent.tools == [google_search]`，把這條規則變成會失敗的測試。
- **為什麼 `data_agent` 用 flash-lite**：它的工作是「把自然語言變成一次工具呼叫，再把 rows 唸成人話」。這件事 flash-lite 做得跟 3.7-flash 一樣好，價錢一半以下。模型分級是這套系統從 $15/月 變成 $2/月 的主要原因。
- **為什麼 `ToolboxToolset` 在模組頂層同步建立**：附錄 D ⑥ —— 用 async 方式建立在部署時會炸。而且它在建構時不連線（本機實測 2 秒內回來，即使 URL 指向不存在的 port），所以 `TOOLBOX_URL` 還沒起來也 import 得動。

**驗收**

```bash
uv run python -m concierge.agent --self-check
# → concierge self-check OK
```

（會先印一行 `RuntimeWarning: 'concierge.agent' found in sys.modules...`，那是 `__init__.py` 先 import 過 agent 造成的，無害。）

在 `adk web` 問三題，看左邊的 trace 面板確認委派對象：

| 問題 | 期望委派 | 期望行為 |
|---|---|---|
| 我知識庫裡關於 A2A 的重點？ | `wiki_agent` | 呼叫 `search_knowledge`，答案帶 source |
| 幫我研究 Cloud Run GPU 定價 | `research_agent` | 呼叫 `google_search` |
| 我這個月訂閱花多少？ | `data_agent` | 呼叫 `monthly-subscription-total`，數字 2309 |

> ⚠️ 未實測：`adk web` 需要 API key，我沒有跑過。`--self-check`（團隊接線、工具獨占、模型分級）是實測通過的。

> 💡 **啊哈：ADK 的「委派」不是框架能力，是一段自動生成的 prompt ＋ 一個工具**
> root agent 裡沒有委派引擎。ADK 在送出請求前做兩件事：把每個 sub-agent 的 `description` **原文**貼進 root 的 system instruction，再掛一個 `transfer_to_agent` 工具。所以「委派」跟「呼叫工具」在機制上是同一件事——description 寫得模糊，等於你的 prompt 寫得模糊，後面沒有第二層保護。
> 原始碼：`google/adk/flows/llm_flows/agent_transfer.py::_build_transfer_instruction_body`。
> **動手看**：`uv run aha.py --delegation` → 印出 ADK 實際塞進去的那段英文 prompt 原文，你寫的三段中文 description 逐字出現在裡面。

## 步驟 2.2：兩個工具的契約（`concierge/tools.py`）（25 分）

**動手**

```bash
uv run python -m concierge.tools --self-check     # → tools self-check OK
```

工具的 docstring 就是它的規格書：

```python
async def search_knowledge(query: str, top_k: int = 5) -> dict:
    """搜尋個人知識庫（pgvector），回傳最相關的段落與來源。

    什麼時候用我：使用者問「我知識庫裡…」「我之前存的…」時，一律先用我。
    參數：query 是使用者的問題原文（不要自己改寫成關鍵字）；top_k 要幾段，預設 5，最多 20。
    回傳：{"status": "success"|"empty"|"error", "hits": [...], "note": ...}
    status 是 empty 代表知識庫真的沒有 —— 直接告訴使用者查無資料，不要用你自己的記憶回答。
    """
```

**為什麼**

- **為什麼 docstring 要寫「什麼時候用我」**：ADK 只把 docstring ＋ 型別標註送進工具 schema，模型看不到你的程式碼。docstring 寫「Search the knowledge base.」它就會亂用（該查的時候不查、不該查的時候查）。這是投影片 447 頁「MCP 工具沒出現／模型不用工具」的真正原因之一。
- **為什麼 `top_k` 要在程式裡夾上限**：模型會填 `top_k=100`（它以為越多越好）。100 段 × 500 字塞進 context，下一輪對話的成本直接翻倍，還可能超過 context 上限。`max(1, min(top_k, 20))` 一行防住。
- **為什麼 DB 掛掉要回 `{"status":"error"}` 而不是讓 exception 冒出去**：exception 冒到 ADK 的 tool runner，模型收到的是「工具執行失敗」這種沒有資訊的訊號，它會**原封不動重試**，重試三次三倍的錢。回一個帶錯誤字串的 dict，模型會照著它跟使用者說「知識庫連不上」然後停手。
- **為什麼 `status=empty` 要在 note 裡寫「不要自行補答案」**：模型看到空結果的本能是「那我用自己知道的講一下」。工具回傳的 note ＋ agent instruction 兩邊都寫這條規則，才擋得住。這也是 evalset 裡 `case4_not_in_wiki_must_say_no` 要驗的東西。

**驗收**

```bash
uv run python -m concierge.tools --self-check
```

自我檢查裡有四個 assert 對應上面四段理由：docstring 有「什麼時候用我」、`top_k=99` 被夾成 20、DB 炸掉回 `status=error`、非 http 的 url 被擋。

## 步驟 2.3：每日摘要 workflow —— 先讓它壞掉（40 分）

**動手**：照投影片 438 頁的寫法做一個 workflow，然後跑它。本 repo 已經把那個寫法留在 `digest.py` 裡：

```bash
uv run digest.py --broken
```

你會看到**兩種失敗**（ADK 的 warning 與 traceback 走 stderr，所以終端機上會跟下面兩行 print 交錯）：

```
① 靜默失敗：Event(author=...) 的 author 不等於節點名 → route 被丟掉
Node 'silent_fetch' has conditional/DEFAULT edges but none were matched by the emitted route(s): None. The branch will end.
   輸出 = [] （空的，而且沒有任何例外）
② 明顯失敗：下游 node_input 標成 str，上游沒給 output → 下面這個 traceback
pydantic_core._pydantic_core.ValidationError: 1 validation error for str
  Input should be a valid string [type=string_type, input_value=None, input_type=NoneType]
```

現在看修好的版本（`fetch_new_docs` ＋ `render_empty`）：

```python
async def fetch_new_docs(ctx, node_input: Any = None):      # 收 ctx
    rows = ...                                              # 純函式撈資料，零 token
    if not rows:
        ctx.route = "EMPTY"                                 # ← 用 ctx.route，不是 Event(route=...)
        return "（沒有新增文件）"                              # ← 一定要給 output
    ctx.route = "HAS_DOCS"
    return "\n---\n".join(...)

def render_empty(node_input: str | None = None) -> str:      # ← 容許 None
    return "# 今日日報\n\n今日無新增知識。"

daily_digest = Workflow(name="daily_digest", edges=[
    ("START", fetch_new_docs),
    (fetch_new_docs, {"EMPTY": render_empty, "HAS_DOCS": digest_agent}),
])
```

```bash
uv run digest.py --self-check     # → digest self-check OK
uv run digest.py --dry-run        # 假資料兩筆 → 路由 → HAS_DOCS
```

**為什麼**

- **為什麼 `Event(author="fetch", route="EMPTY")` 會靜默失效**：ADK 只採納「author 為空或等於節點名」的事件所帶的決策。原始碼寫得很清楚（`google/adk/workflow/_node_runner.py::_track_event_in_context`）：

  ```python
  is_native_node_event = not event.author or event.author == self._node.name
  if event.actions and is_native_node_event:
      if event.actions.route is not None: ctx.route = event.actions.route
  ```

  author 一填錯，route 被丟掉、沒有例外、沒有輸出，log 只有一行 warning。這是這個 Lab 最貴的一個坑：你會以為是 prompt 寫壞了，然後花兩小時調 instruction。**用 `ctx.route = ...` 就完全不會遇到**，所以本 repo 一律這樣寫。
- **為什麼下游節點的 `node_input` 一定要容許 `None`**：投影片的 `render_empty(node_input: str)` 配上「只回 `Event(route=...)` 不給 output」的上游，`node_input` 就是 `None`，pydantic 在節點入口就攔下來（上面那個 ValidationError）。兩個修法都可以：上游一定 return 東西，或下游標 `str | None = None`。本 repo 兩個都做，因為這種錯誤發生在排程裡（凌晨 8 點沒人看）。
- **為什麼撈資料要用純函式節點**：撈 DB 這件事不需要智慧。做成 LLM 節點的話每天燒 token 去做一件 SQL 就能做完的事，而且模型還可能「創意地」改寫你的 query。純函式節點零 token、行為確定——這就是投影片 438 頁「Graph workflow 的成本紀律」。
- **為什麼「沒有新文件」要有獨立分支**：不分支的話，空的內容也會送進 LLM，它會很努力地幫你「寫一篇沒有內容的日報」。一天一次不痛，但這是無意義支出的典型長相。
- **為什麼路由字串要跟 edges 的 key 完全一致**：`"HAS_DOC"` 少一個 S 不會報錯，只會走到那句 `The branch will end.`。`--self-check` 裡的 assert 就是在守這件事。

**驗收**

```bash
uv run digest.py --self-check
```

期望 `digest self-check OK`。這個 self-check 會**真的跑一遍 ADK Runner**（EMPTY 分支，不呼叫 LLM、不花錢），並且 assert：

- EMPTY 分支輸出含「今日無新增知識」
- EMPTY 分支**沒有**跑到 LLM 節點（輸出裡不該出現「今日重點」）
- 投影片寫法會拋 ValidationError
- author 不符的版本輸出是 `[]`

真的產日報（要 key ＋ DB）：

```bash
uv run digest.py
```

期望輸出是 Markdown，有「## 今日重點 / ## 值得深讀 / ## 待辦建議」三段。

> ⚠️ 未實測：`uv run digest.py`（真的查 DB ＋ 呼叫 LLM）我沒有跑過。`--self-check`、`--dry-run`、`--broken` 三個都是實測通過的。

## 步驟 2.4：evalset（20 分）

**動手**

```bash
uv run adk eval concierge tests/capstone.evalset.json --print_detailed_results
```

四個 case：知識問答委派、研究後入庫、訂閱加總、**知識庫沒有時必須說沒有**。

**為什麼**

- **為什麼要有第四個 case**：前三個測「有沒有做對」，第四個測「有沒有亂做」。agent 系統的失敗模式九成是後者——它不會沉默，它會編。沒有這個 case，你的 evalset 全綠也不代表系統可信。
- **為什麼 eval 要在改 instruction 後重跑**：instruction 是這套系統唯一沒有型別檢查的地方。你為了修 A 行為改了一句話，B 行為就悄悄壞了。evalset 是唯一能抓到這件事的東西（投影片 449-2：evalset 進 CI）。
- **為什麼 `intermediate_data.tool_uses` 要寫進去**：只比對最終回答，模型「用錯工具但講對答案」也會過。把期望的工具呼叫序列寫進去，才驗到委派本身。

**驗收**：四個 case 都 `PASSED`。有 case 紅的話，先看它實際委派給誰——通常是某個 `description` 寫得太模糊。

> ⚠️ 未實測：`adk eval` 要 API key，我沒有跑過。evalset 的 JSON 格式與 Lab 7 的 `travel.evalset.json` 一致，並用 `json.load` 驗過是合法 JSON。

---

# Phase 3 — 工具層：自建 wiki-mcp ＋ Toolbox

> 目標：wiki-mcp 與 Toolbox 都能起來、被 host 看見。中間成果＝你的 Antigravity 裡出現 `wiki_search` 這個工具，同一份能力有了第三個消費者。

## 步驟 3.1：照投影片寫 wiki-mcp —— 它會炸（30 分）

**動手**：先照投影片 440 頁原封不動貼：

```python
# _slide440.py
from mcp.server.fastmcp import FastMCP
mcp = FastMCP("personal-wiki", json_response=True)
```

```bash
uv run _slide440.py
```

實際輸出（本機實測）：

```
ModuleNotFoundError: No module named 'mcp.server.fastmcp'. This is mcp 2.x, where FastMCP was
renamed to MCPServer (from mcp.server.mcpserver import MCPServer) and other APIs changed; see the
migration guide at https://py.sdk.modelcontextprotocol.io/v2/migration/#fastmcp-renamed-to-mcpserver
or pin 'mcp<2' to keep running v1 code.
```

改成 `MCPServer` 之後還有兩個地雷，一次看完：

```bash
uv run python -c "
from mcp.server.mcpserver import MCPServer
try: MCPServer('personal-wiki', json_response=True)
except TypeError as e: print('①', e)
m = MCPServer('personal-wiki')
try: m.run_async(transport='streamable-http')
except AttributeError as e: print('②', e)"
```

```
① MCPServer.__init__() got an unexpected keyword argument 'json_response'
② 'MCPServer' object has no attribute 'run_async'
```

正確寫法（`wiki_mcp/server.py` 就是這樣）：

```python
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

mcp = MCPServer("personal-wiki")          # json_response 不在這裡

if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="0.0.0.0",
            port=int(os.getenv("PORT", 8080)),
            json_response=True, stateless_http=True)   # 在這裡
```

**為什麼**

- **為什麼投影片會錯**：`FastMCP` 是 mcp 1.x 的名字，2.x 改名 `MCPServer`（Lab 6 已經用新名字）。這種改名在 2026 年的 Google／MCP 生態系一年會發生好幾次——附錄 C 的改名對照表就是為此存在。遇到 `ModuleNotFoundError` 先看套件版本，不要先懷疑自己。
- **為什麼 `stateless_http=True`**：MCP 2026-07-28 規格是無狀態的。Cloud Run 會水平擴展，第二個請求打到另一個實例；有狀態的 server 會找不到 session 然後回錯。這個參數少了，本機測都對、上雲隨機失敗。
- **為什麼 `json_response=True`**：讓回應是單一 JSON 而不是 SSE 串流，對 Cloud Run 這種請求／回應模型的平台友善得多。
- **為什麼 log 要走 stderr**：stdio 模式下 stdout 是協定通道，一個 `print()` 就把 JSON-RPC 訊息弄壞，host 直接斷線（附錄 D ⑤）。

**驗收**

```bash
rm _slide440.py
uv run wiki_mcp/server.py --self-check      # → wiki-mcp self-check OK
uv run mcp dev wiki_mcp/server.py           # Inspector：http://localhost:6274
```

Inspector 裡要看到：Tools 有 `wiki_search`、`wiki_ingest`；Resources 有 `wiki://stats`。點 `wiki_search` 填一個 query 送出——沒設 `DATABASE_URL` 的話會拿到 `ToolError: 知識庫查詢失敗（…）—— 檢查 DATABASE_URL 與 documents 表`，那也算驗收通過（證明工具真的被呼叫到了，錯誤訊息也真的看得懂）。

> ⚠️ 未實測：Inspector 畫面我沒有開過（要瀏覽器）。`--self-check` 與上面三個錯誤訊息都是本機實測的原文。

## 步驟 3.2：權限矩陣（20 分）

**動手**

```bash
# 唯讀部署（預設）：ingest 被擋
uv run python -c "
import asyncio, sys; sys.path.insert(0,'wiki_mcp')
import importlib; s = importlib.import_module('server')
try: asyncio.run(s.wiki_ingest('https://example.com'))
except Exception as e: print(type(e).__name__, e)"
```

期望 `ToolError 這個 wiki-mcp 是唯讀部署（WIKI_ALLOW_INGEST=0）。入庫請走 concierge 的 wiki_agent`。

`tools.yaml` 那一側也是兩個 toolset：

```yaml
kind: toolset
name: personal-data            # 給 concierge 的 SA：含 add-note（可寫）
---
kind: toolset
name: personal-data-readonly   # 給外部 host：只有讀
```

**為什麼**

- **為什麼要有唯讀部署**：`wiki_search` 給誰用都沒差（就是你自己的知識），`wiki_ingest` 是寫入——被 prompt injection 誘導的話，別人的 agent 可以把垃圾寫進你的知識庫，而且下次問答時你會引用到那些垃圾。這是投影片 441-4 權限矩陣的真正理由。
- **為什麼用環境變數而不是在程式裡判斷呼叫者身分**：MCP 協定層沒有「呼叫者身分」這件事，認證是傳輸層（Cloud Run IAM）的責任。所以最省事又不會錯的做法是：部署兩份服務，一份 `WIKI_ALLOW_INGEST=0` 給大家用，一份 `=1` 只綁 concierge 的 SA。程式碼一份、行為兩種。
- **為什麼 Toolbox 的 SQL 要寫死在 yaml**：模型只能給參數，不能給 SQL。這樣 prompt injection 最多讓它「用你允許的 SQL 查不該查的參數」，不可能變成 `drop table`。這也是為什麼 `add-note` 用 `ON CONFLICT DO NOTHING`——重複標題不會覆蓋既有筆記。

**驗收**

```bash
uv run --with pyyaml python -c "
import yaml; d=[x for x in yaml.safe_load_all(open('tools.yaml')) if x]
print(len(d), [x['name'] for x in d if x['kind']=='toolset'])"
```

期望 `7 ['personal-data', 'personal-data-readonly']`（本機實測通過）。

起 Toolbox 之後（Lab 8 下載的那顆 binary）：

```bash
export DB_PASSWORD='...'
./toolbox --config tools.yaml --port 5000
curl -s localhost:5000/api/toolset/personal-data | uv run python -m json.tool
```

期望看到四個工具的 name 與 description。

> ⚠️ 未實測：Toolbox binary 我沒有跑過（需要 DB）。YAML 的合法性與 toolset 內容是實測的。

## 步驟 3.3：接回 Antigravity（15 分）

**動手**：把 `mcp_config.sample.json` 裡的 `personal-wiki-local` 那段抄進 `~/.gemini/config/mcp_config.json`，改成你的絕對路徑，然後在 Antigravity 裡 Refresh、`/mcp` 看列表。

```json
"personal-wiki-local": {
  "command": "uv",
  "args": ["run", "--directory", "/絕對路徑/capstone", "wiki_mcp/server.py"],
  "env": { "DATABASE_URL": "postgresql://...:5432/postgres" },
  "disabledTools": ["wiki_ingest"]
}
```

**為什麼**

- **為什麼遠端要用 `serverUrl` 而不是 `url`**：Antigravity 的欄位名是 `serverUrl`（附錄 D ④）。抄 Cursor 的設定檔必踩，寫錯的症狀是 server 完全不出現，而且沒有錯誤訊息。
- **為什麼要 `--directory`**：`uv run` 要在專案目錄裡才找得到 `pyproject.toml`／`uv.lock`。Antigravity 啟動子行程時的工作目錄不是你的專案，少了這個參數會 `ModuleNotFoundError`。
- **為什麼在 host 這一側 `disabledTools` 掉 `wiki_ingest`**：開發時你的 Antigravity 有一堆 agent 在跑，不小心讓它自動入庫會污染知識庫。要入庫就手動跑 `ingest.py`。
- **為什麼這一步值得做**：這就是投影片 440 頁那句「MCP 的複利」——你今天蓋的能力，現在有三個消費者（Capstone 的 wiki_agent、你的 Antigravity、同事的 host），而你只寫了一份 `wiki_core.py`。

**驗收**：Antigravity 的 `/mcp` 列表裡有 `personal-wiki-local`，展開看得到 `wiki_search`（`wiki_ingest` 應該是灰的）。在對話裡問「用 wiki_search 查 A2A」，它會呼叫工具並回結果。

> ⚠️ 未實測：Antigravity 的畫面我沒辦法驗（要 GUI）。JSON 是實測合法的。

> 💡 **啊哈：你只寫了一份 docstring，它同時是四個生態系層級的規格書**
> 同一個「查知識庫」能力：① `concierge/tools.py` 的 Python 函式 → ② ADK 的 `FunctionDeclaration`（Lab 7）→ ③ MCP 的 `tools/list`（Lab 6，`wiki_mcp/server.py`）→ ④ A2A agent card 的 skill（Lab 9，`research_service/agent.py`）。②③ 的機器可讀規格從你的 docstring ＋ 型別標註自動生成，④ 從 agent 的 `description` 生成——你沒有為任何一層多維護一份。
> ② 與 ③ 的 JSON schema 逐字相同（只差 `title` 欄位）——ADK 跟 MCP 是兩個互不相干的框架，卻長出同一個 JSON。這就是為什麼「一個 python 函式」能一路包裝到 Cloud Run 服務。
> **動手看**：`uv run aha.py --wrappers` → 四層並排，最後一行印 `② 與 ③ 的 JSON schema 逐字相同（除了 title）：True`。

---

# Phase 4 — A2A 串聯與部署

> 目標：五個服務上雲、IAM 串好、六條端到端驗收過關。中間成果＝手機瀏覽器打開 concierge 就能用。

## 步驟 4.1：研究員拆成 A2A 服務（30 分）

**動手**：本機先驗，再上雲。

```bash
uv run research_service/agent.py --self-check      # → research_service self-check OK
uv run uvicorn research_service.agent:a2a_app --port 8001
# 另一個終端機：
curl -s localhost:8001/.well-known/agent-card.json | uv run python -m json.tool | head -20
```

然後讓 concierge 改用遠端研究員——**不用改任何程式碼**，只要設環境變數：

```bash
export RESEARCH_A2A_URL=http://localhost:8001
uv run adk web        # 現在 research_agent 是 RemoteA2aAgent
```

**為什麼**

- **為什麼研究員要獨立成服務**：三個理由。① 研究任務又慢又重，跟聊天流量的擴展曲線完全不同，混在一起會讓對話跟著卡；② `google_search` 必須獨占一個 agent，拆開最乾淨；③ 拆成 A2A 之後，別人的 agent 也能委派研究任務給它——你的能力進入別人的系統（投影片 449-4）。
- **為什麼用 `RESEARCH_A2A_URL` 有值才切換**：本機開發不想每次都起兩個服務。同一份 `concierge/agent.py`，沒設變數就是本機 `Agent(tools=[google_search])`，設了就是 `RemoteA2aAgent`——這比維護兩份 agent.py 省事，而且 `--self-check` 兩條路徑都驗。
- **為什麼 `timeout=120` 而不是預設**：`RemoteA2aAgent` 的預設是 600 秒。對方掛掉你會傻等 10 分鐘（Lab 9 學過的教訓）。研究任務確實久，但 2 分鐘還沒回就是有問題。
- **為什麼上雲要設 `A2A_PUBLIC_URL`**：`to_a2a()` 生的 agent card 會把 host／port 寫進去。不設的話卡片上寫 `localhost:8001`，別人抓到卡片也連不上你——而且沒有錯誤訊息，只是連不到。

**驗收**：agent card 的 `name` 是 `research_agent`，`skills[0].description` 是「研究員：上網深入調查…」那段。

```bash
uv run python -c "import research_service.agent as m; print(type(m.a2a_app).__name__)"
# → Starlette（本機實測：app 組得起來，不用連網）
```

> ⚠️ 未實測：`uvicorn` 起服務與 `curl` 抓卡片我沒有跑過（會用到 API key 初始化模型）。`--self-check` 與 `a2a_app` 組裝是實測的。

## 步驟 4.2：部署（`deploy.sh`）（45 分）

**動手**：先 dry-run，看清楚要花什麼錢再 apply。

```bash
./deploy.sh --dry-run          # 預設就是 dry-run，只印指令
export PROJ=你的專案 SUPABASE_URL='postgresql://...' DB_PASSWORD='...'
./deploy.sh --apply            # 真的部署
```

部署順序（＝依賴順序）：

```
0) secrets → 1) wiki-mcp → 2) toolbox → 3) research-a2a → 4) IAM 綁定 → 5) concierge 入口
```

**為什麼**

- **為什麼順序是「先工具、再專員、最後入口」**：入口需要知道下游的 URL。反過來部署，concierge 起來時 `TOOLBOX_URL` 還不存在，它會在第一次查表時才失敗——而且是使用者幫你發現的。照依賴順序部署，每一步都能獨立 smoke test（`deploy.sh` 最後一段就是那些 curl）。
- **為什麼 dry-run 是預設**：`gcloud run deploy` 打錯一個參數就是一個新服務在跑、開始計費，而且 `--source .` 會把整個目錄 build 成 image（幾分鐘）。dry-run 當預設值，`--apply` 才動真的——這個順序讓你不可能「手滑部署」。
- **為什麼內部服務全部 `--no-allow-unauthenticated`**：wiki-mcp 能讀你的全部知識、toolbox 能查你的訂閱。公開等於把個人資料放在網路上。IAM 只綁 `roles/run.invoker` 給 `agent-sa`，是投影片 463 頁第 ⑩ 條「prompt injection 的災害半徑＝agent 的權限」的具體做法。
- **為什麼機密走 Secret Manager 而不是 `--set-env-vars`**：env vars 在 Cloud Console 上任何有 Viewer 權限的人都看得到，也會出現在部署歷史裡。`--set-secrets DATABASE_URL=session-db-url:latest` 是同樣的一行成本。
- **為什麼 `adk deploy cloud_run` 一定要帶 `--session_service_uri`**：這是「重整不失憶」（驗收 446-4）的唯一開關。不帶的話 session 存在記憶體，冷啟動或水平擴展一次就全沒了——而且**不會報錯**，你只會發現使用者抱怨它忘記事情。前綴要 `postgresql+asyncpg://`（SQLAlchemy 的 async 引擎），`deploy.sh` 會自動幫你把 `postgresql://` 換掉。
- **為什麼 concierge 部署完還要 `gcloud run services update`**：`adk deploy cloud_run` **沒有** `--set-env-vars` 這個參數（`--help` 查得到）。所以 `TOOLBOX_URL` / `RESEARCH_A2A_URL` 只能部署完回填。不回填的話 concierge 在雲端還是打 `http://127.0.0.1:5000`，`data_agent` 每次查表都連線被拒。同理 `research-a2a` 要回填 `A2A_PUBLIC_URL`，不然名片上寫 localhost。
- **為什麼 toolbox 不能照投影片的 `--source toolbox/`**：Toolbox 是官方 image，本 repo 也沒有 `toolbox/` 目錄——照抄會得到 `ERROR: Source directory does not exist`。`deploy.sh` 改用 `--image "$TOOLBOX_IMAGE"`，並把 `tools.yaml` 存成 secret 掛成檔案（改設定不用重 build）。⚠️ 未實測：image 路徑與 Toolbox 的 CLI 參數名請以 mcp-toolbox.dev 的文件為準。
- **為什麼 `gcloud secrets create --data-file=-` 一定要有人餵 stdin**：投影片 444 的 `echo -n "$SUPABASE_URL" | gcloud secrets create …` 那個 pipe 不是裝飾。少了它，`--data-file=-` 會停在那裡等你從鍵盤打字（看起來像卡住）。`deploy.sh` 的 `secret()` 函式就是在做這件事，而且第二次跑會自動改成 `versions add` 而不是失敗。
- **為什麼 `research-a2a` 用 `--command`/`--args` 覆寫入口**：同一份 `Dockerfile` 服務兩個部署（wiki-mcp 與 research-a2a），差別只有啟動指令。維護兩份 Dockerfile 是雙倍的更新負擔。

**驗收**

```bash
bash -n deploy.sh                 # 語法檢查（本機實測 OK）
./deploy.sh --dry-run | tail -1
# → dry-run OK：6 段、順序 secrets → wiki-mcp → toolbox → research-a2a → IAM → concierge（沒有碰任何雲端資源）
```

部署完的 smoke test（`deploy.sh` 第 6 段會印給你）：

```bash
WIKI_MCP_URL=$(gcloud run services describe wiki-mcp --region us-central1 --format='value(status.url)')
curl -s -o /dev/null -w '%{http_code}\n' $WIKI_MCP_URL/mcp                          # 期望 403
curl -H "Authorization: Bearer $(gcloud auth print-identity-token)" $WIKI_MCP_URL/mcp  # 期望 200/406
```

**403 是正確答案**，不是錯誤——它證明未授權的人進不來。帶 token 之後如果變成 401，看 audience：ID token 的 audience 必須**全等於**目標服務 URL，差一個字元就 401（附錄 D ⑦）。

> ⚠️ 未實測：所有 `gcloud` 指令、`docker build`、以及部署後的 curl，我都沒有跑過（沒有 GCP 專案）。`bash -n` 與 `--dry-run` 是實測的。

## 步驟 4.3：排程日報（15 分）

**動手**

```bash
gcloud scheduler jobs create http daily-digest \
  --schedule "0 8 * * *" --time-zone "Asia/Taipei" \
  --uri "$CONCIERGE_URL/run" --http-method POST \
  --oidc-service-account-email "agent-sa@$PROJ.iam.gserviceaccount.com" \
  --message-body '{"app_name":"capstone","user_id":"me","new_message":{"role":"user","parts":[{"text":"產生今日日報"}]}}'
```

開發階段先用本機：`uv run digest.py`，或 Antigravity 的 `/schedule`。

**為什麼**

- **為什麼用 `--oidc-service-account-email`**：concierge 如果是私有服務，Scheduler 必須自己帶 ID token。少了這個參數，Scheduler 每天準時打一次 403，而且它不會告訴你——你只會發現日報「就是沒來」。
- **為什麼一天一次**：Cloud Scheduler 的免費額度只夠少數幾個 job（⚠️ 投影片沒給數字，請查 GCP 定價頁）。而且日報的價值來自「累積一天的量」，每小時跑一次是 24 倍的錢換更差的內容。
- **為什麼時區要寫 `Asia/Taipei`**：預設是 UTC。你會在下午 4 點收到「今日日報」。

**驗收**

```bash
gcloud scheduler jobs run daily-digest      # 手動觸發一次，不用等到明天早上
gcloud run services logs read concierge --region us-central1 --limit 50 | grep digest
```

> ⚠️ 未實測：需要 GCP 專案。

## 步驟 4.4：驗收（30 分）

**動手**

```bash
uv run acceptance.py            # 看完整矩陣（20 條，顏色分 offline/cloud/manual）
uv run acceptance.py --offline  # 8 條離線的，全綠才有資格談雲端
```

然後照 `ACCEPTANCE.md` 把投影片 446 頁那六條走完：

- [ ] **446-1 知識問答**：「我知識庫裡關於 A2A 的重點？」→ 答案的 source 真的在 `documents` 表裡（回去 SQL 查一次）
- [ ] **446-2 研究入庫**：「研究 Cloud Run GPU 定價並存起來」→ 跨 A2A 服務 → ingest →**再問一次**答得出來（這條驗的是整條鏈）
- [ ] **446-3 資料查詢**：「我這個月的訂閱總花費？」→ 數字等於 `select sum(monthly_twd) from subscriptions where active`
- [ ] **446-4 持久化**：對話 → 重新整理瀏覽器 → 追問「剛剛那筆」接得上；Supabase 的 events 表有列
- [ ] **446-5 摘要工作流**：手動觸發 `daily_digest`，Markdown 有三段
- [ ] **446-6 權限＋品質**：未授權 curl 內部服務 → 403；`adk eval` 四個 case 全綠
- [ ] 手機瀏覽器打開 concierge URL，問一題，答得出來（這是「全雲端運行」的真正驗收）

**為什麼**

- **為什麼 446-2 要「再問一次」**：研究完有輸出很容易，寫進 DB 也不難，但兩件事之間有一個很容易斷的接點（ingest 的 embed 沒寫成功、topic 沒帶、chunk 是空的）。「再問一次答得出來」是唯一能同時驗到寫入與檢索的動作。
- **為什麼 446-3 要自己下 SQL 對答案**：模型會把 5 筆數字加錯，而且加錯的結果看起來很合理。用 `monthly-subscription-total` 這個把 `sum()` 寫死在 yaml 裡的工具，就是為了讓模型不必加總——但你要驗它真的用了那個工具，不是自己算的。
- **為什麼要用手機驗**：`--with_ui` 的介面是 responsive 的，但 session 持久化、CORS、冷啟動這些問題在手機上才會現形（尤其冷啟動：第一次點進去要等 5-10 秒）。
- **為什麼驗收矩陣要能執行**：勾選清單放在文件裡會爛掉（改了程式碼沒改文件）。`acceptance.py` 的 20 條裡有 8 條會真的執行並回 exit code，可以放進 CI；剩下的 12 條老實標成 `cloud`／`manual`。

**驗收**：`uv run acceptance.py --offline` 回 exit 0，六條主線全部勾起來。

> ⚠️ 未實測：六條主線全部需要雲端與 key。離線那 8 條是實測的（`離線驗收：8 通過 / 0 失敗`）。

> 💡 **啊哈：整個系統的依賴方向是單向朝內的——最中間那 236 行不知道外面有四層框架**
> `wiki_core.py` 被 ADK 工具、MCP server、CLI、排程四個地方 import，它自己的 module-level import 只有 `os` / `sys` / `types`：ADK、MCP、A2A、asyncpg、`google.genai` 一個都不在（後兩個是函式內延後 import）。
> 兩個後果：換掉任何一層包裝紙（明年的新 host、新 agent 框架）這 236 行不用改一個字；也因為這樣，`uv run wiki_core.py --self-check` 才能不連網、不用 key 跑完——核心邏輯根本不需要它們在場。
> **動手看**：`grep -n "^import \|^from " wiki_core.py`（只有三行、全是標準庫）＋ `uv run aha.py --map`（看它在圖的正中央）。

---

## 常見錯誤對照表

| 症狀 | 原因 | 解法 |
|---|---|---|
| `ModuleNotFoundError: No module named 'google'` | 用了 `python digest.py` | 一律 `uv run digest.py`（本課不用 pip／venv） |
| `ModuleNotFoundError: No module named 'mcp.server.fastmcp'. This is mcp 2.x, where FastMCP was renamed to MCPServer…`（本機實測原文） | 投影片 440 用的是 mcp 1.x 的類別名 | `from mcp.server.mcpserver import MCPServer` |
| `TypeError: MCPServer.__init__() got an unexpected keyword argument 'json_response'`（本機實測） | 投影片把 `json_response` 放在建構子 | 放到 `mcp.run(transport=..., json_response=True, stateless_http=True)` |
| `AttributeError: 'MCPServer' object has no attribute 'run_async'`（本機實測） | 投影片寫 `asyncio.run(mcp.run_async(...))` | 直接 `mcp.run(...)`（同步進入點，內部自己開 loop） |
| `pydantic_core._pydantic_core.ValidationError: 1 validation error for str / Input should be a valid string [type=string_type, input_value=None, input_type=NoneType]`（本機實測） | 上游節點只回 `Event(route=...)` 沒給 output，下游 `node_input` 標成 `str` | 下游標 `node_input: str \| None = None`，或上游一定 return 東西。`uv run digest.py --broken` 可重現 |
| log 只有 `Node 'x' has conditional/DEFAULT edges but none were matched by the emitted route(s): None. The branch will end.`，沒輸出也沒例外（本機實測） | `Event(author=..., route=...)` 的 author 不等於節點名 → ADK 丟掉 route | 用 `ctx.route = "EMPTY"`；別自己填 `author` |
| `pydantic ... Graph validation failed. Duplicate edge found: from=fetch, to=render`（本機實測） | 兩個路由指到同一個函式節點 | 每個分支給不同函式（要共用邏輯就包兩層薄殼） |
| `ImportError: ToolboxToolset requires the 'toolbox-adk' package. Please install it using 'pip install google-adk[toolbox]'`（本機實測） | 只裝了 `google-adk`，沒裝 toolbox extra | `uv add "google-adk[toolbox]"`（**不要**照錯誤訊息用 pip） |
| `ModuleNotFoundError: No module named 'a2a'`（本機實測） | 匯入 `google.adk.a2a.utils.agent_to_a2a` 但沒裝 a2a-sdk | `uv add a2a-sdk` |
| `ValueError: No API key was provided. Please pass a valid API key.`（本機實測） | 沒 export `GEMINI_API_KEY` | `export GEMINI_API_KEY=...`；或先跑 `--self-check`／`--dry-run` 這些不用 key 的路徑 |
| `RuntimeError: Cannot send a request, as the client has been closed.` | `genai.Client()` 沒綁變數，請求送出前被 GC | `with genai.Client() as client:` |
| `RuntimeError: 6543 是 Transaction pooler…`（本 repo 主動擋） | 複製了 Supabase 的 Transaction pooler 連線字串 | 改用 Session pooler 5432（附錄 D ③） |
| `expected 1536 dimensions, not 3072`（pgvector 的錯） | `embed_content` 沒給 `config={"output_dimensionality": 1536}`，預設是 3072 維 | `wiki_core.EMBED_DIM` 要等於 `schema.sql` 的 `vector(N)`；`wiki_core.py --self-check` 會 assert 這兩個一致 |
| 部署完重整就失憶，Supabase 沒有 events 表的列，而且**沒有錯誤訊息** | `adk deploy cloud_run` 少了 `--session_service_uri`，session 存在記憶體 | 帶 `--session_service_uri postgresql+asyncpg://…`（`deploy.sh` 第 5 段已經帶） |
| 部署完 `data_agent` 查表連線被拒（打到 127.0.0.1:5000） | `adk deploy cloud_run` 沒有 `--set-env-vars`，下游 URL 沒回填 | 部署完 `gcloud run services update concierge --update-env-vars TOOLBOX_URL=…,RESEARCH_A2A_URL=…` |
| `ERROR: Source directory does not exist`（部署 toolbox） | 照抄投影片 444 的 `--source toolbox/`，但 Toolbox 是官方 image，repo 也沒這個目錄 | 用 `--image "$TOOLBOX_IMAGE"` ＋ 把 `tools.yaml` 掛成 secret 檔案 |
| `gcloud secrets create` 停在那裡不動 | `--data-file=-` 在等 stdin，你忘了 pipe | `printf '%s' "$SUPABASE_URL" \| gcloud secrets create …`（`deploy.sh` 的 `secret()` 已經處理） |
| `column "topic" of relation "documents" does not exist` | Lab 8 建的 `documents` 沒有 Capstone 要的欄位 | 跑 `schema.sql` 的 `alter table ... add column if not exists` |
| 呼叫內部服務回 `403` | 沒帶 ID token，或 SA 沒綁 `roles/run.invoker` | 這在驗收裡是**正確**結果；要通就帶 `gcloud auth print-identity-token` |
| 帶了 token 還是 `401` | ID token 的 audience 不等於服務 URL | audience 必須全等於目標服務 URL，差一字元就 401（附錄 D ⑦） |
| agent 不委派、自己流暢地亂答 | sub-agent 的 `description` 模糊；root 沒有禁答規則 | description 寫具體職責；root instruction 加「不得自己回答任何知識問題」 |
| session 沒存、重整就失憶 | 用了 6543 pooler 或 driver 前綴錯 | Session pooler 5432 ＋ `postgresql+asyncpg://`（ADK 的 SQLAlchemy 要 `+asyncpg`；`wiki_core` 的 asyncpg 直連不要，`dsn()` 會自動處理） |
| MCP 工具在 host 裡沒出現 | docstring／型別標註缺，或設定改完沒 Refresh；遠端欄位寫成 `url` | 先用 Inspector 驗工具在不在，再回 host Refresh；遠端欄位是 `serverUrl` |
| `RuntimeWarning: 'concierge.agent' found in sys.modules after import of package 'concierge'` | `__init__.py` 先 import 過 agent，`python -m` 再載一次 | 無害，可忽略（ADK 需要 `__init__.py` 那行 import） |
| 帳單比預期高 | `thinking_level` 一律 high／research 排太密／迴圈失控 | 分級模型（flash-lite 做雜活）＋`LoopAgent max_iterations`＋GCP 預算告警 |

---

## 完整解答

| 檔案 | 內容 |
|---|---|
| `wiki_core.py` | Phase 1 知識層唯一實作（chunk／embed／search／ingest／stats），`--self-check` |
| `ingest.py` | Phase 1 CLI，`--dry-run`／`--self-check` |
| `schema.sql` | Phase 1 建表與種資料，最後三行是驗收 query |
| `concierge/agent.py`、`concierge/tools.py` | Phase 2 團隊與工具，各有 `--self-check` |
| `digest.py` | Phase 2 workflow，`--self-check`／`--dry-run`／`--broken`（故意壞掉的版本） |
| `tests/capstone.evalset.json` | Phase 2 四個 eval case |
| `wiki_mcp/server.py`、`tools.yaml`、`mcp_config.sample.json` | Phase 3 工具層 |
| `research_service/agent.py` | Phase 4 A2A 服務 |
| `deploy.sh`、`Dockerfile` | Phase 4 部署（預設 dry-run） |
| `acceptance.py`、`ACCEPTANCE.md` | 驗收矩陣（20 條，8 條可離線執行） |
| `aha.py` | 五個離線對照 demo：`--parts`／`--map`／`--wrappers`／`--delegation`／`--threshold` |
| `PRD.md` | 需求規格（含投影片 428／430 的元件 × 模組 × Phase 對照表）、費用與風險 |
| `SPEC.md` | 架構圖、介面契約、環境變數、錯誤邊界、已知限制與升級路徑 |

## 想再往下玩

- **記憶升級**（投影片 449-1）：把 concierge 也部署一份到 Agent Engine，用託管 Memory Bank 讓它記住你的偏好，跟 Cloud Run 版並排比較。
- **evalset 進 CI**（449-2）：`adk eval` 的 exit code 接進 GitHub Actions，每次改 instruction 自動跑回歸——`acceptance.py --offline` 也可以一起進去。
- **多模態入庫**（449-3）：`wiki_core.fetch_text` 加上 PDF（`document` content block）與 YouTube，ingest 就能吃簡報與影片。
- **對外開放**（449-4）：wiki-mcp 加 OAuth、把 research 的 agent card 掛上 Agent Registry——你的能力進入別人的 agent。
- **語音介面**（449-5）：Live API 前端，對著手機說「幫我研究…」。
- **混合檢索**：`wiki_core` 的向量檢索加一路 `ILIKE` 關鍵字檢索再合併——專有名詞（型號、指令名）的召回率會明顯變好。

## 這個 Lab 你真正學到的

- 我學會 multi-agent 委派在 ADK 裡的位置是「一段自動生成的 prompt ＋ 一個 `transfer_to_agent` 工具」，所以要調的是 description，不是框架。
- 我學會同一個能力在 Google 生態系裡有四種包裝紙（Python 函式／ADK tool／MCP tool／A2A skill），而它們共用我寫的那一份 docstring。
- 我學會 RAG 的「查不到」是我自己用一個門檻造出來的產品決定，不是資料庫給的事實。
- 我學會系統的難度不在元件而在邊界：誰能寫入、誰只能讀、誰付錢、失敗時回什麼字串——四個 Phase 的坑全部長在這四種邊界上。
- 我學會這 1,135 行裡只有 11 行是新邏輯，剩下的是接線能力——而接線能力才是走完十個模組真正的產出。

## 清理

Phase 1-3 是本機的，沒有雲端資源；Phase 4 有五個服務要收。

```bash
# 1) Cloud Run 服務（scale-to-zero 時不算錢，但別留著忘記）
for SVC in concierge wiki-mcp toolbox research-a2a; do
  gcloud run services delete $SVC --region us-central1 --quiet
done

# 2) 排程
gcloud scheduler jobs delete daily-digest --quiet

# 3) 機密（版本會累積；免費額度投影片沒講，請查 GCP 定價頁）
gcloud secrets delete session-db-url --quiet
gcloud secrets delete db-password --quiet

# 4) 容器 image（Artifact Registry 會一直佔空間算錢）
gcloud artifacts docker images list us-central1-docker.pkg.dev/$PROJ/cloud-run-source-deploy --format='value(IMAGE)' \
  | xargs -I{} gcloud artifacts docker images delete {} --quiet --delete-tags

# 5) Agent Engine（有做加分題才要）
gcloud ai agent-engines list --region us-central1     # 找到 ID 再 delete

# 6) 本機
unset GEMINI_API_KEY DATABASE_URL DB_PASSWORD RESEARCH_A2A_URL
rm -f ~/.capstone_last_digest_id
rm -rf .venv          # 下次 uv run 會自動重建
```

Supabase 的表**建議留著**——這是你的知識庫，是這整個 Capstone 唯一會越用越有價值的東西。真的要清：`drop table documents, notes, subscriptions;`（ADK 的 sessions／events 表也可以一起 drop）。

費用回顧：全程走完約 $0-10（投影片 448）。閒置成本 $0，因為所有服務都 scale-to-zero。唯一會持續產生費用的是 `min-instances=1`（別設）與 Artifact Registry 的 image 空間（記得清第 4 條）。
