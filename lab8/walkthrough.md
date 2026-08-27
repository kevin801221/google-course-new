# Lab 8 走一遍：旅館查詢 Agent（三層整合）

> 90–120 分鐘 ｜ 綜合 Supabase 資料＋Toolbox 工具層＋ADK agent＋持久 sessions 一次串起來

做完你會有一個問價格會去查資料庫、重啟之後還記得你預算的 agent：

```
$ curl -s http://127.0.0.1:5000/api/toolset/hotel-tools | uv run python -m json.tool | head -5
{
    "serverVersion": "1.9.0",
    "tools": {
        "search-hotels-by-city": {

# adk web → 選 hotel_agent
你：東京三千元以內有什麼旅館？我預算就 3000。
🔧 search-hotels-by-city(city="Tokyo", max_price=3000)
agent：資料庫裡符合的有兩間：Sakura Inn NT$2,800（★4.3，近車站/含早餐）、
       Ueno Capsule NT$1,200（★3.8，背包客）。

（Ctrl-C 停掉 adk web，重新啟動，開新對話）
你：我剛說的預算是多少？
agent：3000 元台幣（東京）。要我用這個預算再找一次嗎？
```

> ⚠️ 上面這段是**示意**輸出，不是實跑紀錄。這個 Lab 需要 Supabase 專案、Toolbox 執行檔與 API key，我沒有這些，所以線上部分我一步都沒實際跑過 —— 每個步驟會標出哪些是我實測過的（離線檢查）、哪些沒有。

每一步都是「動手 → 為什麼 → 驗收」。驗收沒過不要往下走 —— 這個 Lab 有三個程序、一個資料庫，錯誤往下滾會很難拆。

---

## 步驟 0：前置（10 分）

**動手**

1. 到 <https://supabase.com> 建一個免費專案（`New project`）。**記下兩件事**：資料庫密碼、網址裡那串 project ref（像 `abcd1234efgh5678`）。
2. Dashboard 右上 `Connect` → 選 **Session pooler**（5432）那條，複製起來。
3. 建專案與相依：

```bash
uv init --bare lab8 && cd lab8
uv add "google-adk[toolbox]" google-genai asyncpg
# preflight.py 自帶 PEP 723 檔頭（pyyaml），不用加進專案相依
export GEMINI_API_KEY="Lab 1 那把 key"
export DB_PASSWORD='你的資料庫密碼'
```

**為什麼**

- **為什麼是 Session pooler（5432）不是 Transaction pooler（6543）**：6543 那條是 transaction 模式的連線池，每個 SQL 可能落在不同後端連線上 —— asyncpg 會先 `PREPARE` 再 `EXECUTE`，兩者跑到不同連線就會噴 `prepared statement "__asyncpg_stmt_1__" does not exist`。要命的是它不是每次都錯，是**間歇性**錯：你本機測十次都過，上線之後隨機爆。這是投影片 8.4 踩坑清單第一條，也是全課十大易錯坑第③名。
- **為什麼密碼要 `export` 而不是寫進 `.env`**：等一下的 Toolbox 是一個 Go 執行檔，它讀環境變數、**不讀 `.env`**。只寫 `.env` 的話 `adk web` 會過、Toolbox 會連不上，然後你會以為是連線字串錯。
- **為什麼用單引號**：密碼常有 `$` `!` 這種字元，雙引號會被 shell 展開成空字串或 history 展開，然後你看到的是 authentication failed 而不是「密碼被吃掉了」。

**驗收**

```bash
uv run python -c "from google.adk.agents import Agent; import asyncpg; print('deps ok')"
echo "${GEMINI_API_KEY:0:6}… / DB_PASSWORD 長度=${#DB_PASSWORD}"
```

第一條要印 `deps ok`；第二條的長度不能是 0。

> ⚠️ 未實測：我這台機器沒裝 google-adk（課程環境沒有），上面第一條指令我沒跑過。

---

## 步驟 1：資料就緒（15 分）

**動手**：Supabase Dashboard → SQL Editor → New query，把本目錄的 `schema.sql` 整份貼進去按 Run。

核心就這幾行（完整版含 10 筆種資料在 `schema.sql`）：

```sql
create extension if not exists vector;

create table if not exists hotels (
  id          bigserial primary key,
  name        text not null,
  city        text not null,
  price_twd   integer not null check (price_twd > 0),
  rating      numeric(2,1) default 4.0 check (rating >= 0 and rating <= 5),
  tags        text[] default '{}',
  description text,                      -- 語意搜尋要吃的原文（加分題 A）
  embedding   vector(1536),              -- gemini-embedding-2 截斷至 1536 維
  created_at  timestamptz default now(),
  constraint hotels_name_city_key unique (name, city)
);

create index if not exists hotels_city_price_idx  on hotels (city, price_twd);
create index if not exists hotels_embedding_idx   on hotels using hnsw (embedding vector_cosine_ops);
```

**為什麼**

- **為什麼第一行是 `create extension`**：pgvector 在 Supabase 是內建但**預設沒啟用**的。少了這行，`vector(1536)` 那個欄位會讓整份 SQL 停在 `ERROR: type "vector" does not exist (SQLSTATE 42704)` —— 而且是整個 transaction 一起失敗，表根本沒建出來，你會以為是 SQL 打錯。
- **為什麼要 `unique (name, city)` 加 `on conflict do nothing`**：投影片 8.2 的 `insert` 沒有這個。學生一定會重跑一次 SQL（改個東西、再 Run），資料就變兩倍 —— 然後步驟 3 的 `get-price-stats` 平均房價全錯，而且錯得很像對的，你查半天查不到原因。約束放在資料庫，因為之後有三個程序會寫這張表。
- **為什麼 `embedding` 允許 NULL**：資料先進來、向量後補（步驟 7）。代價是檢索 SQL 一定要加 `where embedding is not null`，否則沒嵌入的列距離算不出來，會亂排。
- **為什麼是 `vector(1536)` 不是 3072**：`gemini-embedding-2` 預設 3072 維，但支援 Matryoshka 截斷 —— 存 1536 維省一半空間、精度損失極小（8.5）。**這個數字之後在程式裡要一致**，不一致的下場是 `ERROR: expected 1536 dimensions, not 3072`。
- **為什麼 HNSW 要配 `vector_cosine_ops`**：查詢用 `<=>`（餘弦距離）就得建餘弦的 ops class。配錯的懲罰最陰險：**不會報錯**，只是索引不會被用到，資料量小的時候你完全看不出差別，資料長大才發現每次查詢都是全表掃。
- **為什麼多一個 `hotels_city_price_idx`**：步驟 2 的工具永遠是 `where city = ? and price_twd <= ?`。這是 Lab 9／10 累積資料後唯一會被用到的索引。
- **為什麼 `numeric(2,1)` 要再加 `check <= 5`**：`numeric(2,1)` 只擋到 9.9。Lab 9 讓另一個 agent 寫資料時，評分 `48` 會被存成…等等，其實會直接溢出報錯，但 `4.8` 打成 `9.9` 就進去了。約束寫清楚，之後省事。

**驗收**：`schema.sql` 最後三行就是驗收查詢，Run 完往下滑看結果。

```
total
-----
10
```

```
city     | n | avg_price
---------+---+----------
Taipei   | 1 | 2200
Osaka    | 2 | 2750
Sapporo  | 1 | 3100
Tokyo    | 4 | 3750
Kyoto    | 2 | 3800
```

（`order by avg_price` 是**升冪**，所以 Taipei 在最上面。這五個數字是 `schema.sql` 那 10 筆種資料算出來的，對不上就是資料種了兩次或少種。）

第三個查詢（東京 3000 以內）要回**兩列**：Sakura Inn 2800、Ueno Capsule 1200。**把這兩列記住**，步驟 4 要拿 agent 的回答跟它對。

離線也能先驗語法（我實測過的）：

```bash
uv run --with sqlglot python -c \
  "import sqlglot;sqlglot.parse(open('schema.sql').read(),read='postgres');print('SQL 語法 OK')"
```

會看到一行 `'create extension if not exists vector' contains unsupported syntax. Falling back to parsing as a 'Command'.` 然後印 `SQL 語法 OK` —— 那行警告是 sqlglot 不認識 `create extension`，不是你的 SQL 有問題。

順便：Dashboard 會在 `hotels` 旁邊掛一個紅色的 **RLS Disabled** 警告。這個 Lab 裡是**預期的** —— 我們用 Postgres 連線直連（`postgres` 使用者），RLS policy 對這條路不生效。別花時間去關它。

> ⚠️ 未實測：我沒有 Supabase 專案，SQL Editor 的實際輸出我沒看過。上面的語法檢查是實測通過的。

---

## 步驟 2：寫 tools.yaml（20 分）

**動手**：把本目錄的 `tools.yaml` 的 `host` 與 `user` 換成你自己的（從步驟 0 複製的連線字串裡撈）。結構長這樣：

```yaml
kind: source
name: course-db
type: postgres
host: aws-0-ap-northeast-1.pooler.supabase.com   # ← 換成你的 region
port: 5432
database: postgres
user: postgres.abcd1234                          # ← 換成你的 project ref
password: ${DB_PASSWORD}
---
kind: tool
name: search-hotels-by-city
type: postgres-sql
source: course-db
description: 依城市與每晚預算上限搜尋旅館，回傳名稱、價格、評分、標籤，依評分高到低排序。
parameters:
  - name: city
    type: string
    description: 城市英文名，如 Tokyo、Osaka、Kyoto、Sapporo、Taipei
  - name: max_price
    type: integer
    description: 每晚台幣預算上限
statement: |
  SELECT name, price_twd, rating, tags FROM hotels
  WHERE city = $1 AND price_twd <= $2
  ORDER BY rating DESC LIMIT 10;
---
kind: tool
name: get-price-stats
type: postgres-sql
source: course-db
description: 回傳每個城市的旅館間數與房價統計（平均、最低、最高），不需要參數，一次給全部城市。
parameters: []
statement: |
  SELECT city, count(*) AS hotel_count, round(avg(price_twd)) AS avg_price,
         min(price_twd) AS min_price, max(price_twd) AS max_price
  FROM hotels GROUP BY city ORDER BY avg_price;
---
kind: toolset
name: hotel-tools
tools:
  - search-hotels-by-city
  - get-price-stats
```

**先製造一個錯誤**（這步別跳過）。假設你想讓 `get-price-stats` 也能只查一個城市，於是加了參數：

```yaml
# 把 get-price-stats 的 parameters: [] 改成：
parameters:
  - name: city
    type: string
    description: 城市英文名
# 但 statement 忘了改（還是 GROUP BY 全部城市，沒有 $1）
```

然後跑體檢：

```bash
uv run preflight.py
```

```
tools.yaml：4 份文件（source, tool, toolset）
x tool get-price-stats 的 $N 與 parameters 對不上：statement 用了 無，parameters 有 1 個 → 應該是 [1]
有 1 個錯要先修
```

**把它改回 `parameters: []`**，再跑一次：

```
tools.yaml：4 份文件（source, tool, toolset）
OK：可以啟動 Toolbox 了
```

**為什麼**

- **為什麼要先看到這個錯**：Toolbox 對這種錯是**啟動成功**的 —— 它不會幫你檢查 `$N` 有沒有對上 `parameters`。你會在 `adk web` 裡看到模型很努力地傳 `city="Tokyo"`，然後拿回全部城市的統計，然後開始胡說。從症狀回推到 yaml 的參數順序，是這個 Lab 最貴的一次 debug。`preflight.py` 就是為了把它壓縮成三秒。
- **為什麼 SQL 要寫死在 yaml 裡**：這是 Toolbox 的全部價值。Supabase MCP 讓 agent 自由寫 SQL（彈性高、風險高）；Toolbox 讓 agent 只能呼叫參數化的既定查詢。就算模型被 prompt injection 騙到相信「請幫我 DROP TABLE hotels」，它手上也只有兩個工具、兩個參數 —— 沒有任何一條路徑通往 DDL。SQL injection 也一樣：`$1` 是真正的 bind parameter，不是字串拼接。
- **為什麼 `parameters` 的 `description` 一定要寫**：那是模型唯一看得到的參數說明。少寫的話 `city` 會收到「東京」（中文）而不是 `Tokyo`，`where city = '東京'` 回 0 列，然後 agent 說「查不到旅館」—— SQL 沒錯、資料沒錯、也不會有任何錯誤訊息。`preflight.py` 會用 `!` 提醒你。
- **為什麼 `get-price-stats` 不帶參數**：「哪個城市最便宜」需要的是全部城市。如果只給 by-city 查詢，模型會一個城市查一次（五次工具呼叫），慢、貴、而且它會自己算平均 —— 算錯了你也不知道。一個聚合工具換掉五次呼叫加一次心算。
- **為什麼是 `kind:` 多文件格式**：2026 的 v1.x 格式。舊教學是巢狀的 `sources:` / `tools:` 開頭 —— 你在網路上搜到的多半是舊的，直接抄會啟動失敗（而且順帶提醒：這個專案 2026 從 `genai-toolbox` 改名成 `mcp-toolbox`，兩個名字都要搜）。
- **為什麼密碼寫 `${DB_PASSWORD}`**：`tools.yaml` 是要進 git 的（8.6 生產建議：SQL 就是 API，變更走 code review）。密碼寫死進去等於把資料庫 root 密碼 commit 上去。

**驗收**

```bash
uv run preflight.py            # → OK：可以啟動 Toolbox 了（exit 0）
uv run preflight.py --self-check   # → self-check ok
```

`--self-check` 驗的是六種真的會發生的設定錯（`$N` 多／少、source 指錯、toolset 列到不存在的工具、`kind` 拼錯、缺 `statement`）。這兩條我都實測通過。

> 💡 **啊哈：「安全」在這裡不是形容詞，是一個可以數出來的數字 —— 模型可控的 SQL 字元數＝0**
> 你的工具面是 2 個工具、2 個參數、0 個能改到 SQL 文字的位元。加分題 B 的 Supabase MCP 是
> 1 個工具、1 個參數，而那個參數就是整句 SQL —— 可控字元數無上限。同一個資料庫，攻擊面差在
> 「模型能寫幾個字的 SQL」這一個數字上，不是差在有沒有小心。
> **動手看**：`uv run preflight.py --aha` → 同一發 injection 打下去，兩邊的
> 「模型可控 SQL 字元數」量出來是 **29** 對 **0**，語句數 **2** 對 **1**。

---

## 步驟 3：啟動 Toolbox（15 分）

**動手**

```bash
# macOS Apple Silicon：
export VERSION=1.9.0
curl -L -o toolbox \
  "https://storage.googleapis.com/mcp-toolbox-for-databases/v$VERSION/darwin/arm64/toolbox"
chmod +x toolbox
# Linux x86 換成 linux/amd64（投影片 8.6 的網址）；也可以 brew install mcp-toolbox

export DB_PASSWORD='你的資料庫密碼'      # 沒 export 就白跑
./toolbox --config tools.yaml
```

看到 listen 在 `127.0.0.1:5000` 之後，**開另一個終端機**：

```bash
curl -s http://127.0.0.1:5000/api/toolset/hotel-tools | uv run python -m json.tool
```

**為什麼**

- **為什麼要單獨起一個程序**：Toolbox 是一個 MCP server，不是 Python library。它自己管連線池、認證、OpenTelemetry。一個 Toolbox 可以同時服務多個 agent（Lab 9 就會用到），這也是它跟「在 agent 裡直接寫 SQLAlchemy」的根本差別：資料團隊管 `tools.yaml`，agent 團隊只管用。
- **為什麼要先 curl 才開 agent**：如果 Toolbox 沒起來，`ToolboxToolset` 在 `adk web` 裡的症狀是「工具清單空的」或呼叫時連線被拒 —— 但 agent 還是會回答你（用它自己編的資料）。先用 curl 確認，你就不會把「工具層沒起來」誤判成「模型不聽話」。
- **macOS 的 5000 埠**：系統設定裡的 AirPlay Receiver 預設佔用 5000。症狀是啟動失敗（address already in use），或更糟 —— curl 回一個 403 加 `Server: AirTunes`，看起來像 Toolbox 有起來但路由錯了。解法：`./toolbox --config tools.yaml --port 5001`，然後 `export TOOLBOX_URL=http://127.0.0.1:5001`。
- **為什麼不用 `--prebuilt`**：`--prebuilt postgres` 給的是通用的「探索 schema／執行任意查詢」工具，等於 Supabase MCP 的角色。這個 Lab 要的是相反的東西：固定 SQL。

**驗收**：curl 的 JSON 裡要同時出現 `search-hotels-by-city` 與 `get-price-stats`，而且每個工具的 parameters 名稱與說明都在。

```bash
curl -s http://127.0.0.1:5000/api/toolset/hotel-tools | grep -o 'search-hotels-by-city\|get-price-stats'
# 兩個名字都要出現
```

如果 404，先試 `curl -s http://127.0.0.1:5000/api/toolset`（全部工具），並用 `--log-level debug` 啟動看它印出來的路由。

> ⚠️ 未實測：Toolbox 執行檔我沒有下載、沒有啟動過，`darwin/arm64` 的下載網址與 `/api/toolset/<name>` 這個路徑都是照投影片 8.6 與慣例推的，不是實跑確認。版本號 1.9.0 抄投影片。

---

## 步驟 4：ADK agent 接上（20 分）

**動手（先做壞的版本）**：把 `hotel_agent/agent.py` 裡的 `tools=tools` 暫時改成 `tools=[]`，然後：

```bash
uv run adk web
```

瀏覽器開 <http://localhost:8000>，選 `hotel_agent`，問：

```
東京三千元以內有什麼旅館？
```

它會給你一份看起來很專業的清單 —— 旅館名稱、價格、評分都有，語氣充滿自信。**跟步驟 1 記下來的那兩列比對**：Sakura Inn 2800 / Ueno Capsule 1200。它答的大概是「東急 Stay 新宿 NT$3,000」之類 —— 完全編的。這就是「沒有資料層的 agent 只是聊天玩具」的實物。

**再做好的版本**：把 `tools=[]` 改回 `tools=tools`，重啟 `adk web`，問同一句。

```python
# hotel_agent/agent.py 的關鍵三段
toolset = ToolboxToolset(                                   # ← 模組頂層、同步建立
    server_url=os.environ.get("TOOLBOX_URL", "http://127.0.0.1:5000"),
    toolset_name="hotel-tools",
)

INSTRUCTION = """你是旅館顧問，只根據資料庫回答。
1. 任何價格、評分、間數、統計數字，一律先呼叫資料庫工具取得。資料庫查不到就說查不到，
   絕對不准憑記憶、常識或推測報價 —— 編一個價格比說「沒有資料」嚴重得多。
2. 城市要用英文餵工具（Tokyo / Osaka / Kyoto / Sapporo / Taipei）。
..."""

root_agent = Agent(model="gemini-3.7-flash", name="hotel_agent",
                   instruction=INSTRUCTION, tools=tools)
```

**為什麼**

- **為什麼要先看它編一次**：instruction 裡「不准憑空報價」那句話，在你沒看過它憑空報價之前只是一句廢話。看過之後你會知道：模型不會說「我不知道旅館價格」，它會給你一個很合理的數字。這是資料層存在的唯一理由。
- **為什麼 instruction 要寫「查不到就說查不到」**：只寫「用工具查」的話，模型會查一次、拿到 0 列、然後補一句「不過根據我的了解，這個價位在東京大概…」—— 前半段對、後半段又開始編。要把「沒有資料」明確定義成合法答案。
- **為什麼 `toolset_name="hotel-tools"`**：不指定就是載入整個 Toolbox 的所有工具。工具越多，模型選錯的機率越高、每次請求的 token 也越多。最小工具面同時省錢跟省錯。
- **為什麼 `ToolboxToolset` 要在模組頂層同步建立**：包在 `async def` 裡或用 async 方式建立，本機 `adk web` 可能還會過，但部署（Lab 10）會炸 —— 這是全課十大易錯坑第⑥名。`agent.py` 的模組頂層就是 ADK 期望的位置。
- **為什麼城市要指定用英文**：資料庫裡是 `'Tokyo'`。使用者打「東京」，模型如果直接轉手傳「東京」，`where city = '東京'` 回 0 列 —— 沒有錯誤訊息，只有一句「查不到」。這種錯最貴，因為每一層看起來都正常。
- **為什麼 `instruction` 裡要教它用 `get-price-stats`**：模型天生偏好它先看到的工具。不明講的話「哪個城市最便宜」它會把 by-city 呼叫五次。

**驗收**：問三句，每句都看 `adk web` 左邊的 trace（工具呼叫與參數都看得到）。

| 問題 | 該呼叫什麼 | 該回什麼 |
|---|---|---|
| 東京三千元以內有什麼旅館？ | `search-hotels-by-city(city="Tokyo", max_price=3000)` | Sakura Inn 2800、Ueno Capsule 1200（**兩間，跟步驟 1 一致**） |
| 哪個城市平均房價最低？ | `get-price-stats()` 一次 | Taipei（2200）；不是五次 by-city |
| 紐約有什麼旅館？ | `search-hotels-by-city(city="New York", ...)` | 「資料庫裡沒有紐約的資料」，**不准給價格** |

第三題是重點：它必須承認沒有。開始講「紐約的旅館通常…」就是 instruction 還不夠硬。

> 💡 **啊哈：`tools=[toolset]` 裡一個 Python 函式都沒有 —— 這個工具的實作在另一個程序、另一個語言、另一個檔案**
> 同一個「工具」概念的第四種包裝：python 函式（Lab 7 `../lab7/travel_planner/agent.py:62`）→ MCP tool
> （Lab 6 `../lab6/server.py`）→ 這裡的 YAML＋Go 執行檔 → A2A skill（Lab 9 `../lab9/hotel_service/agent.py:33`）
> —— 模型看到的 schema 四次都長一樣，它分不出來，所以你可以不改 agent 就換掉整個資料來源。
> **動手看**：`grep -n "def search_hotels" ../lab7/travel_planner/agent.py ../lab9/hotel_service/agent.py`
> → lab9 是 `(city, max_price)`，跟 `tools.yaml` 一字不差；lab7 多了 `nights` 與 `tool_context`。

> ⚠️ 未實測：`adk web` 我沒跑過（沒裝 google-adk、沒有 key）。`agent.py` 只做過 `ast.parse` 語法檢查。

---

## 步驟 5：Sessions 落地（10 分）

**動手**：Session pooler 那條字串，前綴換成 `postgresql+asyncpg://`：

```bash
export ADK_SESSION_URI='postgresql+asyncpg://postgres.abcd1234:你的密碼@aws-0-ap-northeast-1.pooler.supabase.com:5432/postgres'
uv run adk web --session_service_uri "$ADK_SESSION_URI"
```

密碼有 `@ : / ? # %` 這些字元的先編碼：

```bash
uv run python -c "import urllib.parse,sys;print(urllib.parse.quote(sys.argv[1],safe=''))" '你的密碼'
```

（在程式裡做同一件事就是投影片 8.4 的寫法：`DatabaseSessionService(db_url=DB_URL)`，然後傳給 `Runner`。`adk web` 吃 `--session_service_uri` 是同一條路的 CLI 版，不必改任何程式碼。）

**為什麼**

- **為什麼一定要 `+asyncpg`**：`postgresql://` 會讓 SQLAlchemy 去找同步 driver，直接噴 `sqlalchemy.exc.InvalidRequestError: The asyncio extension requires an async driver to be used.`；寫成 `postgres://`（少了 `ql`）更慘：`Can't load plugin: sqlalchemy.dialects:postgres`。這是十大易錯坑第②名，而且錯誤訊息離「你的字串前綴打錯了」有點距離。
- **為什麼密碼要 percent-encode**：連線字串是 URL。密碼裡有 `@` 的話，URL parser 會把最後一個 `@` 之前全當成使用者資訊，於是 host 變成密碼的後半段 —— 報錯會是 DNS 解析失敗（`nodename nor servname provided`）或 port 解析失敗，完全不會提到密碼。
- **為什麼不用自己建表**：`DatabaseSessionService` 首次啟動會自動建 `sessions` / `events` / `app_states` / `user_states`。手動建的 schema 對不上 ADK 版本會出現各種奇怪的欄位錯誤 —— 讓它自己建。
- **為什麼跟 `hotels` 同一個資料庫**：一個免費層專案就夠了，而且備份、權限、連線設定共用一套。這也是 8.5 那句「資料與向量同庫」的同一個道理往上推一層。

**驗收**：Supabase Dashboard → Table Editor，refresh 之後左邊的表清單要多出 `sessions`、`events`（跟 `app_states`、`user_states`）。還是空的沒關係 —— 下一步才有資料。

> ⚠️ 未實測：自動建表這件事我沒有實際跑過，表名以投影片 8.4 為準。

---

## 步驟 6：驗證持久化（10 分）

**動手**

1. 在 `adk web` 裡開一輪對話，明確說出預算：

```
我預算 3000，想去東京。
```

2. 等它查完、回答完。**Ctrl-C 停掉 `adk web`**（就是模擬服務重啟／換一個實例）。
3. 用**同一條** `--session_service_uri` 重新啟動，回到 UI 的 session 清單，點回剛剛那個 session，追問：

```
我剛說的預算是多少？
```

**為什麼**

- **為什麼要真的殺掉程序**：重整瀏覽器不算 —— 記憶體裡的 session 還在。只有把 Python 程序殺掉，你才知道狀態是真的落地了還是只是還沒被清掉。這也是 Cloud Run 的日常：scale-to-zero、換實例，記憶體裡的東西一律消失。
- **不這樣寫會怎樣（對照組）**：把 `--session_service_uri` 拿掉再走一次同樣的流程 —— 重啟之後 session 清單是空的，你連那段對話都找不回來（`InMemorySessionService` 的資料跟程序一起死）。**這個對照組請真的做一次**，它是「為什麼需要資料庫」最短的證明。
- **為什麼追問要在同一個 session 裡**：sessions 存的是這一條對話的歷史。開新 session 追問是問錯問題 —— 那需要的是 Memory（跨 session 記憶，8.1 的場景②、M7 的 Memory Bank），不是 Sessions。這兩個概念混在一起是這章最常見的誤解。

**驗收**

1. agent 答得出「3000」。
2. Supabase Table Editor → `events` 表：看得到剛剛那幾輪的列（`author` 是 `user` / agent 名稱）。→ `sessions` 表：看得到一列，`state` 是 JSON。
3. 反例確認過：不帶 `--session_service_uri` 重啟後，session 清單是空的。

```sql
-- SQL Editor 裡直接數
select count(*) from events;
select id, app_name, user_id, update_time from sessions order by update_time desc limit 3;
```

> 💡 **啊哈：它記得的「3000」不存在任何一個預算欄位裡 —— `events` 存的是整段對話，模型重讀一次就想起來了**
> Sessions 不是「記憶」，是「對話重放」。這就是為什麼 Lab 7 要另外做一個 `set_budget` 把預算寫進
> `tool_context.state`（`../lab7/travel_planner/agent.py:58`）：對話會越來越長、context 會被截斷，
> 而 `state` 是一個明確的欄位。記憶與狀態的四種存法在這裡分岔成兩條。
> **動手看**：`select author, count(*) from events group by author;` 對照 `select state from sessions;`
> → ⚠️ 未實測，但你應該會看到 events 有每一輪的列，而 `state` 幾乎是空的 `{}`。

> ⚠️ 未實測：需要跑起來的 `adk web` 與真的 Supabase。`sessions` / `events` 的欄位名以投影片 8.4 的說法為準，實際欄位請以 Table Editor 看到的為真。

---

## 步驟 7：加分題 A —— 掛上 pgvector 語意搜尋（20 分）

**動手**

```bash
export DB_URL_RAW='postgresql://postgres.abcd1234:你的密碼@aws-0-ap-northeast-1.pooler.supabase.com:5432/postgres'
uv run seed_embeddings.py                       # 把 description 變向量寫回 embedding
uv run seed_embeddings.py --search "想泡溫泉又安靜"
LAB8_RAG=1 uv run adk web --session_service_uri "$ADK_SESSION_URI"
```

核心邏輯（`seed_embeddings.py`）：

```python
def to_vector(values, dim=1536):
    """float 陣列 → pgvector 吃的文字格式 '[0.1,0.2,...]'，順手擋維度不對。"""
    values = list(values)
    if len(values) != dim:
        raise ValueError(f"維度是 {len(values)}，但 schema 是 vector({dim})："
                         f"config 少給 output_dimensionality 就會拿到 3072 維")
    return "[" + ",".join(repr(float(v)) for v in values) + "]"

res = embed([embed_text(r) for r in rows])       # 一次 API 呼叫嵌完全部
await conn.executemany("update hotels set embedding = $2::vector where id = $1",
                       build_updates(rows, res))
```

**為什麼**

- **為什麼是 `update` 而不是投影片 8.5 的 `insert`**：8.5 是「把一份文件切塊灌進 documents」；這裡的資料已經在 `hotels` 裡了。用 `insert` 會種出重複的旅館。而且只撈 `embedding is null` 的列，重跑不會重複付錢。
- **為什麼 `$2::vector` 的 cast 不能省**：`vector` 是 pgvector 的自訂型別，asyncpg 不認得它 —— 沒有 cast，你傳字串進去會拿到型別相關的錯誤（訊息依 asyncpg 版本不同）。加上 `::vector` 就變成「傳文字、由 Postgres 轉型」，投影片 8.5 的檢索 SQL 也是這樣寫的（`embedding <=> $1::vector`）。
- **為什麼要 `to_vector` 這個維度守衛**：忘記 `config={"output_dimensionality": 1536}` 的話會拿到 3072 維，然後在 Postgres 端炸 `ERROR: expected 1536 dimensions, not 3072`。在 Python 端先擋下來，錯誤訊息可以直接告訴你原因是哪個 config 少給了 —— 而且不用等到已經寫進去一半的資料。
- **為什麼 `embed_text` 要把名稱、城市、價格、標籤一起嵌進去**：只嵌 `description` 的話，「東京便宜的旅館」這種混合查詢的向量會落在很遠的地方。語意搜尋搜的是你嵌進去的那段文字，不是整列資料。
- **為什麼批次嵌入**：`contents` 一次帶多段，一個 API 呼叫搞定整份資料（8.5）。十筆各叫一次是十倍的往返延遲。
- **為什麼 `rag_tool.py` 要有 `jsonable()`**：`rating` 是 `numeric`，asyncpg 回傳 `decimal.Decimal`。直接丟給 ADK 會炸 `TypeError: Object of type Decimal is not JSON serializable`。Toolbox 幫你處理掉了這一層，自己寫 FunctionTool 就得自己處理 —— 這也順便說明了為什麼工具層值錢。
- **為什麼檢索 SQL 有 `where embedding is not null`**：NULL 的列距離算不出來，但排序時不會被丟掉，會污染 top-5。

**驗收**

離線的先跑（我實測過的，不連網不花錢）：

```bash
uv run seed_embeddings.py --self-check              # → self-check ok
uv run python hotel_agent/rag_tool.py --self-check  # → self-check ok
```

線上的：

```bash
uv run seed_embeddings.py
# 預期：寫回 10 筆向量：Sakura Inn、Shibuya Stay、…
#       尚未嵌入的列： 0

uv run seed_embeddings.py --search "想泡溫泉"
# 預期第一名是 Ginza Grand（描述裡有「頂樓有溫泉大浴場」），sim 明顯高於後兩名
```

再回 `adk web` 問「我想找安靜、能泡湯的地方」—— trace 裡該出現 `search_hotels_semantic`，而不是 `search-hotels-by-city`（因為「安靜」不是 SQL 的 `WHERE` 表達得出來的條件）。這兩個工具的分工就是這個加分題的重點：結構化條件走 Toolbox，說不清的需求走向量。

> 💡 **啊哈：RAG 不需要向量資料庫產品 —— 一句 `order by embedding <=> $1` 的 SQL 就是 RAG**
> pgvector 把「語意搜尋」降級成 Postgres 的一個運算子。而且「資料與向量同庫」不只是省事：
> 向量在別的服務、`city`／`price` 在資料庫時，你只能先向量排序、撈回應用層再過濾 —— 這會**漏答案**。
> **動手看**：`uv run seed_embeddings.py --aha`（離線、示意向量）→ 問「東京 3000 以內＋想泡溫泉又安靜」，
> 兩段式的 top-3 過濾完剩 **0 筆**（漏掉 Sakura Inn），同庫一句 SQL 回 **2 筆**；k 要開到 **4** 才第一次
> 撈到合格的 —— 而這張表**才 10 筆**。

> ⚠️ 未實測：`seed_embeddings.py` 與 `--search` 的線上執行需要 key 與資料庫，我沒跑過。`gemini-embedding-2` 這個型號名抄投影片；若 404 用 `client.models.list()` 確認。兩支 `--self-check` 是實測通過的。

---

## 步驟 8：加分題 B —— Antigravity 掛 Supabase MCP（10 分）

**動手**：編輯 `~/.gemini/config/mcp_config.json`：

```json
{
  "mcpServers": {
    "supabase": {
      "serverUrl": "https://mcp.supabase.com/mcp?read_only=true&project_ref=abcd1234&features=database%2Cdocs%2Cdebugging"
    }
  }
}
```

Refresh MCP，首次使用會跳 OAuth 瀏覽器授權。然後在 Antigravity 裡問：

```
看一下 hotels 表的索引，我的查詢都是 where city = ? and price_twd <= ?
再加上向量搜尋，現在的索引夠嗎？有沒有多餘的？
```

**為什麼**

- **為什麼三個參數都要帶**：`read_only=true` 讓查詢跑在唯讀 PG 使用者（第一防線）；`project_ref` 鎖定單一專案，不然你是把整個帳號交出去；`features` 決定工具面 —— 沒列的工具不存在。三個是三層保險，少一個就少一層。
- **為什麼欄位叫 `serverUrl` 不是 `url`**：Antigravity 遠端 MCP 的欄位名就是 `serverUrl`。抄 Cursor 的設定檔必踩（十大易錯坑第④名），而且症狀是 server 靜靜地不出現，不會有錯誤。
- **為什麼這題放在最後**：這是 Toolbox 的對照組。Supabase MCP 讓 agent 自由寫 SQL —— 探索與 debug 超好用（它可以自己 `explain analyze`），但你不會想讓正式流量走這條。同一個資料庫、兩種工具層、兩種風險等級，這就是 8.6 那句「開發探索用 Supabase MCP、正式流量用 Toolbox」的實感。
- **風險提醒**：把 `read_only` 關掉只該發生在開發環境。「查資料」被 prompt injection 變成「刪資料」不是玩笑（M6）。

**驗收**：Antigravity 列得出 `hotels_city_price_idx` 與 `hotels_embedding_idx`，並且能說出「`(city, price_twd)` 這個複合索引的順序對你的查詢是對的」。它若建議加索引，追問「這個索引在 10 筆資料的表上會被用到嗎？」—— 正確答案是不會（Postgres 小表直接 seq scan）。

> ⚠️ 未實測：需要 Antigravity 與 Supabase 帳號的 OAuth，我沒有跑過。設定檔內容抄投影片 8.3 與附錄 B。

---

## 步驟 9：驗收（5 分）

主線十條，全部要過：

- [ ] `select count(*) from hotels` ≥ 10，`create extension` 沒報錯
- [ ] `uv run preflight.py` → `OK：可以啟動 Toolbox 了`
- [ ] `curl -s http://127.0.0.1:5000/api/toolset/hotel-tools` 看得到兩個工具名
- [ ] agent 回答「東京 3000 以內」的旅館名稱與價格，跟 SQL Editor 查出來的**完全一致**
- [ ] 問「哪個城市平均房價最低」時 trace 只有一次 `get-price-stats`
- [ ] 問紐約時它說「資料庫裡沒有」，一個價格都不編
- [ ] 說預算 3000 → 殺掉 `adk web` → 同一條 URI 重啟 → 追問，答得出 3000；`events` 表有列
- [ ] 你做過 `tools=[]` 的對照組，看過它編價格
- [ ] 你做過不帶 `--session_service_uri` 的對照組，看過它失憶
- [ ] 三支 `--self-check` 都印 `self-check ok`

加分：

- [ ] `select count(*) from hotels where embedding is null` = 0
- [ ] `--search "想泡溫泉"` 第一名是 Ginza Grand
- [ ] Antigravity 讀得到 `hotels` 的索引清單

---

## 常見錯誤對照表

| 症狀 | 原因 | 解法 |
|---|---|---|
| `ModuleNotFoundError: No module named 'google'` | 用了 `python xxx.py` | 一律 `uv run xxx.py`（這個 Lab 的所有指令都是） |
| SQL Editor：`ERROR: type "vector" does not exist (SQLSTATE 42704)` | pgvector 沒啟用，整份 SQL 一起失敗、表根本沒建 | 先跑 `create extension if not exists vector;`（`schema.sql` 第一行） |
| 平均房價、間數都怪怪的，但每筆資料看起來都對 | `schema.sql` 跑了兩次，資料變兩倍 | `unique (name, city)` ＋ `on conflict do nothing`；已經重複的用 `delete from hotels where id not in (select min(id) from hotels group by name, city)` |
| 間歇性 `asyncpg.exceptions.InvalidSQLStatementNameError: prepared statement "__asyncpg_stmt_1__" does not exist` | 用了 Transaction pooler（6543），prepared statement 跟連線對不上 | 換 Session pooler（5432）。本機測十次可能十次都過，這錯是隨機的 |
| `sqlalchemy.exc.InvalidRequestError: The asyncio extension requires an async driver to be used.` | 連線字串前綴是 `postgresql://`，少了 async driver | `postgresql+asyncpg://`（十大易錯坑②） |
| `Can't load plugin: sqlalchemy.dialects:postgres` | 前綴寫成 `postgres://`（少了 `ql`） | `postgresql+asyncpg://` |
| 連線報 `nodename nor servname provided, or not known`，但 host 明明是對的 | 密碼裡有 `@`／`:`／`/`，URL 被切錯，host 變成密碼的一段 | percent-encode 密碼：`uv run python -c "import urllib.parse,sys;print(urllib.parse.quote(sys.argv[1],safe=''))" '密碼'` |
| Toolbox 啟動時報 password authentication failed（密碼明明對） | 密碼只寫進 `.env`，沒有 `export` —— Toolbox 是 Go 執行檔，不讀 `.env` | `export DB_PASSWORD='...'` 之後再啟動；`uv run preflight.py` 會先用 `!` 提醒你 |
| macOS：Toolbox 起不來（address already in use），或 curl 回 403 帶 `Server: AirTunes` | 5000 埠被 AirPlay Receiver 佔用 | `./toolbox --config tools.yaml --port 5001` ＋ `export TOOLBOX_URL=http://127.0.0.1:5001`（或關掉系統設定裡的 AirPlay 接收器） |
| 模型有傳 `city="Tokyo"`，回來的資料卻是全部城市（或參數對不上） | `tools.yaml` 的 `$N` 與 `parameters` 順序／數量不符。Toolbox **不會**因此啟動失敗 | `uv run preflight.py`；`$1` 對應第一個 parameter |
| agent 說「查不到旅館」，但 SQL Editor 查得到 | 模型把「東京」原封不動傳進 `city` | `parameters` 的 `description` 寫明「城市英文名，如 Tokyo」，instruction 再強調一次 |
| `adk web` 的 agent 下拉選單是空的 | 不在 `lab8/` 裡執行，或 `hotel_agent/__init__.py` 少了 `from . import agent` | `cd lab8` 再跑；確認 `__init__.py` 內容 |
| 工具呼叫時連線被拒（httpx 連線錯誤），但 agent 還是給了你答案 | Toolbox 沒起來，模型改用自己編的資料 | 先 `curl` 確認 :5000 通；答案要拿去跟 SQL Editor 對 |
| `TypeError: Object of type Decimal is not JSON serializable` | `numeric` 欄位（`rating`）回來是 `Decimal`，自寫的 FunctionTool 直接丟給 ADK | `rag_tool.jsonable()`：`float(v) if isinstance(v, decimal.Decimal) else v` |
| `ERROR: expected 1536 dimensions, not 3072` | 嵌入時忘了 `config={"output_dimensionality": 1536}` | 補上；`to_vector()` 會在寫進 DB 之前先擋下來 |
| 重啟 `adk web` 之後 session 清單空的 | 忘了帶 `--session_service_uri`，用的是 `InMemorySessionService` | 帶上 `--session_service_uri "$ADK_SESSION_URI"`（這也是步驟 6 的對照組） |
| Dashboard 在 `hotels` 旁邊顯示紅色 `RLS Disabled` | 這不是錯 —— 我們走 Postgres 直連，RLS 對這條路不生效 | 這個 Lab 不用處理。要開放 anon key 存取才需要 RLS policy |

---

## 完整解答

本目錄就是走完九步的版本：

| 檔案 | 內容 |
|---|---|
| `schema.sql` | `hotels`＋兩個索引＋10 筆種資料＋驗收查詢＋（選配）`documents` |
| `tools.yaml` | source ＋ `search-hotels-by-city` ＋ `get-price-stats` ＋ `hotel-tools` toolset |
| `preflight.py` | `tools.yaml` 離線體檢（`--self-check`／`--aha` 實測通過） |
| `hotel_agent/agent.py` | `ToolboxToolset` ＋ instruction ＋ `root_agent` |
| `hotel_agent/rag_tool.py` | 加分題 A 的語意搜尋工具（`--self-check` 實測通過） |
| `seed_embeddings.py` | 批次嵌入寫回 `embedding`；`--search` 驗收；`--aha` 同庫對照（離線，實測通過） |
| `.env.example` | 六個環境變數的範本（含 `LAB8_RAG` 開關） |

設計理由與完整契約看 `SPEC.md`（三程序架構圖、工具 schema、schema 的每一個決定為什麼這樣定、十一條錯誤處理）；學習目標與驗收清單看 `PRD.md`。

## 想再往下玩

- **給語意搜尋加上 metadata 過濾**：`SEARCH_SQL` 加 `and city = $2 and price_twd <= $3`。一個 SQL 同時做「語意排序」與「硬條件過濾」—— 這正是 8.5 說的「資料與向量同庫」的價值，專用向量庫做這件事要兩次查詢再自己 join。
- **開一個只有 SELECT 權限的 DB 帳號**給 Toolbox 用（8.6 生產建議②）。`tools.yaml` 只換 `user`／`password`，agent 完全不用改 —— 順手體會工具層的解耦。
- **把 `documents` 表用起來**：`schema.sql` 最後留了 8.5 的 `documents`。把課程講義切塊灌進去（800 字重疊 100），旅館資料＋知識庫雙引擎。
- **接下去是 Lab 9（A2A）**：這個 Toolbox 就是「一個工具層、多個 agent」的第一個實例 —— Lab 9 的另一個 agent 會連同一個 `:5000`，`tools.yaml` 一行都不用改。Lab 10 再把 Toolbox 部署上 Cloud Run，`server_url` 換成服務網址＋ID token。

---

## 這個 Lab 你真正學到的

- **「工具」在 Google 生態系裡是一份 schema，不是一段程式**：同一件「依城市與預算查旅館」
  可以是 python 函式、MCP tool、tools.yaml、A2A skill —— 換包裝不用改 agent。
- **安全是一個可以數的數字**：讓模型填參數而不是寫 SQL，攻擊面就從「無限」變成「兩個欄位」。
- **RAG 是一個 `order by`，不是一個產品**：pgvector 讓語意搜尋住進你本來就有的 Postgres，
  而且能跟 `where` 在同一句 SQL 裡 —— 分開兩段式會漏答案。
- **Sessions 是對話重放、不是記憶**：落地 `events` 表換到的是「重啟不失憶」，
  想要「記得這個人的偏好」是另一個機制（state／Memory）。
- **資料層決定 agent 能不能上線**：同一個 agent，接上工具層之前它會編價格，接上之後它會說「查不到」。

---

## 清理

**不要刪 Supabase 專案** —— `hotels` 這張表 Lab 9、Lab 10、M11 Capstone 都要用。

跑完這輪要收乾淨的只有這些：

```bash
# 1) 停掉兩個程序
#    Ctrl-C 停掉 adk web；Toolbox 那個終端機也 Ctrl-C
pkill -f "toolbox --config tools.yaml"     # 背景跑的話用這個

# 2) Toolbox 執行檔（要用再抓，20MB 級）
rm -f toolbox

# 3) 清掉這個 shell 的機密
unset DB_PASSWORD DB_URL_RAW ADK_SESSION_URI

# 4) 確認密碼沒進 git
grep -rn "$DB_PASSWORD" . 2>/dev/null | grep -v Binary   # 應該什麼都不印
printf '.env\ntoolbox\n' >> .gitignore
```

想把 sessions 資料清掉（`hotels` 留著）：

```sql
-- Supabase SQL Editor
delete from events;
delete from sessions;
```

費用結算：Supabase 免費層（500MB）＋ Gemini 免費層，主線 $0。加分題 A 多一次 embedding 呼叫（10 筆短描述，用量極小；單價請看官方定價頁，本教材不編數字）。免費層專案閒置太久會被暫停，Lab 9 之前回去點一下就會醒。
