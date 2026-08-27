# Lab 9 走一遍：跨服務 Agent 協作（A2A）

> 60–90 分鐘 ｜ 兩個獨立行程的 ADK agent 經 A2A 協作——M10 雲端部署的本機預演

做完你會有**兩個各自獨立、各自能單獨啟動的服務**。服務 A 的 `concierge` 完全不知道訂房邏輯長什麼樣，只知道 `http://localhost:8001` 有一張名片：

```
$ uv run check_card.py
名片來源  http://localhost:8001/.well-known/agent-card.json
agent     hotel_agent  v0.0.1
描述      訂房專員：依城市與每晚預算搜尋旅館、比價並給推薦。
streaming False   push False
RPC       http://localhost:8001
  - skill hotel_agent  [llm]  訂房專員：依城市與每晚預算搜尋旅館、比價並給推薦。
  - skill hotel_agent-search_hotels  [llm,tools]  依城市與每晚預算上限（TWD）搜尋旅館，由便宜到貴排序。
✓ 名片可用
```

以及一支不用 API key、不連網、不花錢就能驗完整條 A2A 鏈的 smoke test：

```
$ uv run smoke_test.py
搜尋中…
淺草和風旅館 2400 TWD
smoke ok（3 個 event，罐頭答案有回來）
```

每一步都有「動手 → 為什麼 → 驗收」。驗收沒過不要往下走 —— A2A 的失敗訊息都很像，堆在一起就分不出是哪一層壞了。

**這個 Lab 有三處故意讓你先失敗**（步驟 1、步驟 3、步驟 5）。看到錯誤訊息不要跳過，那三段錯誤訊息就是 Lab 10 上雲時你會再遇到一次的東西。

**需要兩個終端機分頁。** 分頁 1 從步驟 2 起就一直被 uvicorn 佔著，其他指令都在分頁 2。

---

## 步驟 0：前置（5 分）

**動手**

```bash
# Lab 7 的 ADK 基礎要先會（Agent、sub_agents、adk web 的 Events 面板）
# Lab 8 不是硬依賴 —— 本 Lab 的 search_hotels 自帶假資料

mkdir -p lab9 && cd lab9
uv init --bare --name lab9 --python 3.13
```

拿一把 AI Studio key（<https://aistudio.google.com/apikey>，免費、不用信用卡）。**沒有 key 也可以做完這個 Lab 的 8 條離線驗收**，只有步驟 4、5 的真實對話會停住。

**為什麼**：兩個服務要各自吃自己的 key。ADK 會自動讀 **agent 目錄下**的 `.env`（`hotel_service/.env`、`concierge/.env`），不是專案根目錄。放錯地方的症狀是「明明 export 過了還是說沒有 key」——因為 `adk web` 的子行程環境跟你的 shell 不一定一致，`.env` 才是 ADK 保證會讀的地方。

**驗收**

```bash
ls pyproject.toml && uv run python -V     # → pyproject.toml / Python 3.13.x
```

---

## 步驟 1：服務 B —— 把 hotel_agent 用 `to_a2a()` 曝露（15 分）

### 1a. 先裝錯，看它怎麼炸

**動手**：先只裝基本的 ADK（**故意的**）：

```bash
uv add google-adk
uv run python -c "from google.adk.a2a.utils.agent_to_a2a import to_a2a"
```

實際輸出：

```
ModuleNotFoundError: No module named 'a2a'
```

**為什麼**：`google-adk` 的 A2A 支援是一個 **extra**（`Requires-Dist: a2a-sdk>=0.3.4,<2 ; extra == "a2a"`）。基本安裝連 `a2a-sdk` 都沒有，所以 `to_a2a` 這支模組頂端的 `from a2a.server.tasks import ...`（traceback 指的那一行是 `InMemoryPushNotificationConfigStore`）直接死在 import。這個錯誤很好認，但下一個不好認：

```bash
uv add "google-adk[a2a]"
```

現在 import 過了。但等你真的啟動服務（步驟 2）才會看到第二層（實測，只裝 `google-adk[a2a]` 的隔離環境）：

```
routes 0
INFO:     Started server process [72964]
INFO:     Waiting for application startup.
ERROR:    Traceback (most recent call last):
  ...
  File ".../a2a/compat/v0_3/jsonrpc_adapter.py", line 6, in <module>
    from sse_starlette.sse import EventSourceResponse
ModuleNotFoundError: No module named 'sse_starlette'
ERROR:    Application startup failed. Exiting.
```

而且 **`to_a2a()` 本身完全不報錯**。因為 `to_a2a` 只是建了一個空的 Starlette app（`len(app.routes) == 0`，上面第一行就是印出來的），真正掛路由的 `attach_a2a_routes_to_app()` 是在 **lifespan startup** 才跑的——那時候才會 import 到 `a2a.server.routes`，才會需要 `sse_starlette`。`setup_a2a()` 沒有 try/except，所以 startup 一失敗 uvicorn 就 `Exiting`，**行程直接死掉**：你去 `curl` 會是 connection refused（`curl -w %{http_code}` 印 `000`），不是 404。

所以症狀是「程式匯入很正常、`uv run python -c "import ..."` 也很正常，uvicorn 一啟動就噴一堆紅字然後自己關掉」。這是本 Lab 最難自己 debug 的一條：錯誤訊息裡沒有 `google-adk`、沒有 `a2a-sdk`，只有一個你從沒裝過的 `sse_starlette`。

一次裝好兩個 extra：

```bash
uv add "google-adk[a2a]" "a2a-sdk[http-server]"
```

**驗收**

```bash
uv run python -c "
from google.adk.a2a.utils.agent_to_a2a import to_a2a
from a2a.server.routes import create_jsonrpc_routes
import importlib.metadata as m
print('adk', m.version('google-adk'), '/ a2a-sdk', m.version('a2a-sdk'))
" 2>&1 | tail -1
```

實測輸出：

```
adk 2.7.1 / a2a-sdk 1.1.2
```

（版號會隨時間變。`a2a-sdk 1.1.x` 對得上投影片第 366 頁。）

### 1b. 寫服務 B

**動手**

```bash
mkdir -p hotel_service && touch hotel_service/__init__.py
```

`hotel_service/agent.py`（完整版在本目錄，這裡只列骨架）：

```python
HOTELS = [
    {"name": "淺草和風旅館", "city": "東京", "price": 2400, "rating": 4.1, "breakfast": False},
    {"name": "上野站前商旅", "city": "東京", "price": 2900, "rating": 4.3, "breakfast": True},
    # …共 6 筆
]

def search_hotels(city: str, max_price: int) -> dict:
    """依城市與每晚預算上限（TWD）搜尋旅館，由便宜到貴排序。

    Args:
        city: 城市名，例如「東京」「大阪」。
        max_price: 每晚預算上限（TWD）。
    """
    slow = float(os.getenv("HOTEL_SLOW_SECONDS", "0"))
    if slow:
        time.sleep(slow)                       # 步驟 5 要用
    hits = sorted((h for h in HOTELS if h["city"] == city and h["price"] <= max_price),
                  key=lambda h: h["price"])
    return {"city": city, "max_price": max_price, "count": len(hits), "hotels": hits}

root_agent = Agent(
    model="gemini-3.7-flash",
    name="hotel_agent",
    description="訂房專員：依城市與每晚預算搜尋旅館、比價並給推薦。",   # ← 會變成名片
    instruction="你是訂房專員。收到旅館需求就呼叫 search_hotels…",
    tools=[search_hotels],
)

A2A_PORT = int(os.getenv("A2A_PORT", "8001"))
a2a_app = to_a2a(root_agent, port=A2A_PORT)      # ← 一行變成 A2A 服務
```

**為什麼**

- **`description` 不是給你自己看的。** 它會被抄成 agent card 的 skill description，而那是「別人的 agent」決定要不要委託你的唯一依據（投影片 370 那句「文件品質＝被使用率」）。`description=""` 的話 `AgentCardBuilder` 會退成字串 `"An ADK Agent"`——名片上寫「一個 ADK agent」，沒有任何 agent 會想呼叫它。
- **工具的 docstring 也會上名片。** 而且是整段抄，`Args:` 那幾行也會出現在公開的 `agent-card.json` 裡（步驟 2 你會親眼看到）。所以 docstring 裡不要寫內部 TODO、不要寫資料庫連線字串。
- **`instruction` 不會上名片。** ADK 的 `AgentCardBuilder` 刻意只抄 `description`，因為名片是不用認證就能抓的公開文件，把 system prompt 放上去等於送給別人做 prompt injection 的地圖。
- **`to_a2a` 的 `port=` 不會叫任何人去 listen。** 它只決定名片上那行 `"url": "http://localhost:8001"`。真正 listen 的是 uvicorn 的 `--port`。兩邊不一致的後果在步驟 3 會炸給你看，而且錯誤訊息完全不會提到 port。
- **`model="gemini-3.7-flash"` 是投影片（第 383、384 頁）給的型號名，照抄。** 型號名以課程投影片為準；如果跑起來 404，用 `client.models.list()` 確認現行型號再換掉（附錄 D 第 ⑧ 條：model ID 進設定檔，不要寫死在程式裡）。這個 Lab 的離線驗收完全不碰模型，所以型號寫錯不會影響前 8 條驗收。
- **`a2a_app` 要在模組頂層。** uvicorn 是用 `hotel_service.agent:a2a_app` 這種「模組:變數」的字串去找它的。寫在 `if __name__ == "__main__":` 裡面 uvicorn 找不到；寫在函式裡就要改成 factory 模式。附錄 D 第 ⑥ 條講的「agent.py 模組頂層同步定義」是同一個道理。

**驗收**：離線的自我檢查，不連網、不用 key、不花錢。

```bash
uv run hotel_service/agent.py --self-check
```

實測輸出：

```
self-check ok
```

它 assert 的是四件實際會錯的事：東京 3000 內剛好 2 筆且順序是便宜的在前、預算 1 元回**空清單而不是 `None`**、查一個資料裡沒有的城市回 `count: 0` 而不是 `KeyError`、`root_agent.description` 不是空字串。

> 踩到 `ModuleNotFoundError: No module named 'google'`？你打的是 `python hotel_service/agent.py`。這個 Lab 一律 `uv run`。

---

## 步驟 2：啟動並驗證名片（10 分）

**動手**（**分頁 1**，這個分頁之後就一直被佔住）：

```bash
export ADK_SUPPRESS_A2A_EXPERIMENTAL_FEATURE_WARNINGS=1
uv run uvicorn hotel_service.agent:a2a_app --port 8001
```

實測輸出：

```
INFO:     Started server process [55041]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://127.0.0.1:8001 (Press CTRL+C to quit)
```

**分頁 2**：

```bash
curl -s http://localhost:8001/.well-known/agent-card.json | python3 -m json.tool
uv run check_card.py
```

**為什麼**

- **`--port 8001` 這個數字必須跟程式裡的 `A2A_PORT` 一樣。** 不一樣的話：名片抓得到（uvicorn 在 8002 聽）、內容也正常（名片上寫 8001），但客戶端會在步驟 3 拒絕連線。這是本 Lab 最貴的一個坑，所以 `check_card.py` 先幫你抓。
- **慣例 8000 給 `adk web`、A2A 服務走 8001+**（投影片 384）。你等一下要在分頁 2 開 `adk web`，如果服務 B 也用 8000，`adk web` 會噴 `[Errno 48] address already in use`。
- **為什麼要那個 `ADK_SUPPRESS_...` 環境變數**：不設的話每一次 A2A 相關的物件建立都會噴一大段 `UserWarning: [EXPERIMENTAL] to_a2a: ADK Implementation for A2A support ... is in experimental mode and is subject to breaking changes.`，一輪對話能刷五、六段，把真正的 log 蓋掉。這個變數名是 ADK 原始碼裡的 `bypass_env_var`，不是我編的。警告本身沒錯——ADK 的 A2A 實作真的標了 EXPERIMENTAL，所以升 ADK 大版本時要重跑 `smoke_test.py`。
- **為什麼要用 `check_card.py` 而不只是 `curl`**：`curl` 只告訴你「名片抓得到」。但 ADK 的客戶端在用這張名片之前會再做兩個檢查（scheme 與 origin），`curl` 完全看不出來。`check_card.py` 就是把那兩個檢查抄出來先跑一遍，而且**不通就 exit 1**，可以塞進 CI。它只用標準庫（`urllib` + `json`），連 a2a-sdk 都不需要。

**驗收**

```bash
uv run check_card.py; echo "exit=$?"
```

實測輸出（最後兩行是重點）：

```
名片來源  http://localhost:8001/.well-known/agent-card.json
agent     hotel_agent  v0.0.1
描述      訂房專員：依城市與每晚預算搜尋旅館、比價並給推薦。
streaming False   push False
RPC       http://localhost:8001
  - skill hotel_agent  [llm]  訂房專員：依城市與每晚預算搜尋旅館、比價並給推薦。
  - skill hotel_agent-search_hotels  [llm,tools]  依城市與每晚預算上限（TWD）搜尋旅館，由便宜到貴排序。

Args:
    city: 城市名，例如「東京」「大阪」。
    max_price: 每晚預算上限（TWD）。
✓ 名片可用
exit=0
```

順手確認 skill 數量對：

```bash
curl -s http://localhost:8001/.well-known/agent-card.json | grep -c search_hotels    # → 1
```

**這張名片有三個地方值得你停下來看**：

| 你看到的 | 為什麼是這樣 |
|---|---|
| JSON 的 key 是 `supportedInterfaces`、`defaultInputModes`、`protocolBinding`（camelCase） | 投影片 370 的範例寫 snake_case，那是 **Python 的欄位名**；上線的 JSON 是 camelCase。拿它當 dict 讀請用 camelCase，寫 `card["supported_interfaces"]` 會 `KeyError` |
| `version` 是 `0.0.1` | `AgentCardBuilder` 的預設值，不是你的專案版本。要自訂就得傳 `agent_card=` |
| `streaming` 是 **False** | 自動生的名片 `capabilities.streaming` 就是 `false`。步驟 5 會回來處理這件事 |
| 工具的 `Args:` 也印出來了 | docstring 整段被抄進公開名片，如前所述 |

> 💡 **啊哈：Lab 7 那個 `tools=[search_hotels]` 的 python 函式，現在有 URL 了 —— 名片上的 `hotel_agent-search_hotels` 就是它。**
> ADK 的每個 tool 會 1:1 變成名片上的一個 A2A skill，id 是 `<agent 名>-<函式名>`。同一個「工具」概念在這門課換了五種包裝：python 函式 → MCP tool（Lab 6 `server.py` 的 `@mcp.tool()`）→ ADK tool（Lab 7 `travel_planner/agent.py:121`）→ **A2A skill（就是你現在看到的）** → Cloud Run 端點（Lab 10）。函式本體一行都沒改，換的只有外面那層殼。
> **動手看**：`grep -n "tools=\[search_hotels\]" ../lab7/travel_planner/agent.py` → `121:    tools=[search_hotels],`；接著 `curl -s http://localhost:8001/.well-known/agent-card.json | grep -o '"id":"[^"]*"'` → `"id":"hotel_agent"` 與 `"id":"hotel_agent-search_hotels"`

> ⚠️ 未實測：如果你的系統把 `localhost` 解析到 `::1`，`curl http://localhost:8001` 會 connection refused（uvicorn 預設只綁 `127.0.0.1`）。我在 macOS 上沒重現這個問題。真的碰到就加 `--host localhost`。

---

## 步驟 3：服務 A —— `RemoteA2aAgent` 當 sub-agent（15 分）

### 3a. 先寫錯的那個 host，看它怎麼炸

**動手**

```bash
mkdir -p concierge && touch concierge/__init__.py
```

`concierge/agent.py`，先**故意**用 `127.0.0.1`（很多人的反射動作）：

```python
hotel_agent = RemoteA2aAgent(
    name="hotel_agent",
    description="訂房專員（遠端服務，跑在 :8001）。查旅館、比價、選飯店都交給它。",
    agent_card="http://127.0.0.1:8001" + AGENT_CARD_WELL_KNOWN_PATH,   # ← 故意錯
    timeout=30.0,
)
```

不用開 `adk web`，用 `check_card.py` 就能看到同一個判斷：

```bash
uv run check_card.py http://127.0.0.1:8001; echo "exit=$?"
```

實測輸出（尾巴）：

```
✗ origin 不一致：名片寫 http://localhost:8001（('http', 'localhost', 8001)），但你是從 ('http', '127.0.0.1', 8001) 抓到名片的
✗ ADK 會用 AgentCardResolutionError 拒絕這張名片
exit=1
```

ADK 自己噴的原話（我用 `smoke_test.ask_remote()` 對真實服務跑出來的）：

```
Failed to resolve remote A2A agent hotel_agent: Agent card RPC URL must have the same origin as the location the card was fetched from (http://127.0.0.1:8001/.well-known/agent-card.json): http://localhost:8001
```

**為什麼會這樣**：`RemoteA2aAgent` 抓到名片之後會跑 `_validate_card_rpc_targets()`，對名片上**每一個** RPC URL 檢查兩件事——

1. scheme 必須是 `https`，除非 host 是 loopback（`localhost` / `*.localhost` / `127.0.0.0/8` / `::1`）；
2. `(scheme, hostname, port)` 三件套必須與「你抓到名片的那個 URL」**完全相同**。

`localhost` 與 `127.0.0.1` 指向同一台機器，但字串不同 → origin 不同 → 拒絕。這不是 bug，是防「拿一張名片把你的請求導去別的主機」的安全設計。而 `to_a2a` 的 `host` 預設就是 `"localhost"`，所以客戶端也只能用 `localhost`。

**同一個錯誤還有另外兩種穿法**，症狀一模一樣：

- `A2A_PORT=8001` 但 `uvicorn --port 8002` → 從 8002 抓到一張寫 8001 的名片。
- 上雲之後名片寫 `http://` 而不是 `https://` → `Agent card RPC URL must use https, or http on a loopback host: http://...`（Lab 10 會踩，所以 `to_a2a(host=..., protocol="https")` 兩個都要傳）。

**驗收（這一步的「成功」就是失敗）**

```bash
uv run check_card.py http://127.0.0.1:8001 | tail -2; echo "exit=${PIPESTATUS[0]}"
```

實測輸出：

```
✗ origin 不一致：名片寫 http://localhost:8001（('http', 'localhost', 8001)），但你是從 ('http', '127.0.0.1', 8001) 抓到名片的
✗ ADK 會用 AgentCardResolutionError 拒絕這張名片
exit=1
```

看到 `exit=1` 才往下走。看到 `✓ 名片可用` 代表你的 `to_a2a` 用的不是預設 `host="localhost"`——那 3b 你要反過來改。

### 3b. 修好

**動手**：把 host 改回 `localhost`，並抽成一個看得懂的函式：

```python
def card_url(base: str) -> str:
    """base URL 接上 /.well-known/agent-card.json，順手吃掉多餘的斜線。"""
    return base.rstrip("/") + AGENT_CARD_WELL_KNOWN_PATH

HOTEL_SERVICE_URL = os.getenv("HOTEL_SERVICE_URL", "http://localhost:8001")

hotel_agent = RemoteA2aAgent(
    name="hotel_agent",
    description="訂房專員（遠端服務，跑在 :8001）。查旅館、比價、選飯店都交給它。",
    agent_card=card_url(HOTEL_SERVICE_URL),
    timeout=30.0,
)

root_agent = Agent(
    model="gemini-3.7-flash",
    name="concierge",
    description="旅遊管家",
    instruction="你是旅遊管家。使用者問到旅館、住宿、房價，一律轉交 hotel_agent 處理，"
                "不要自己編價格。其他行程、交通、天氣問題自己用繁體中文回答。",
    sub_agents=[hotel_agent],      # ← 跟本地 sub-agent 一模一樣的寫法
)
```

**為什麼**

- **`sub_agents=[hotel_agent]` 這一行是這個 Lab 的重點。** 把它跟 Lab 7 的本地 sub-agent 並排看：一個字都沒變。網路邊界被協定抹平了——差別只在 `hotel_agent` 的建構子從 `Agent(...)` 換成 `RemoteA2aAgent(...)`。
- **`rstrip("/")` 不是龜毛。** `HOTEL_SERVICE_URL` 從環境變數來，人打 URL 十次有三次會多一個尾斜線。少了它你會去抓 `http://localhost:8001//.well-known/agent-card.json`——多一個斜線，Starlette 回 404，而錯誤訊息只會說「Failed to resolve AgentCard」，不會指出是斜線的問題。
- **`timeout=30.0` 是刻意覆寫的。** `RemoteA2aAgent` 的預設是 **600 秒**。對方是黑盒子，掛掉的時候你會在 `adk web` 前面傻等十分鐘，然後以為是自己的程式當了（投影片 381 第 5 點：「設定 timeout…是禮貌也是自保」）。
- **`description` 是 root_agent 唯一的委派依據。** concierge 看不到遠端的 `instruction`、看不到 `search_hotels`，只看得到你在這裡寫的這句話。寫成「訂房 agent」它就會猶豫，然後自己編一堆假旅館價格給使用者。`instruction` 裡那句「不要自己編價格」是第二層保險。

**驗收**

```bash
uv run concierge/agent.py --self-check
```

實測輸出：

```
self-check ok
```

它 assert 的東西就是上面講的坑：`card_url` 對尾斜線是不是 idempotent、`localhost` 與 `127.0.0.1` 的 origin 是不是真的不同（用 `urlparse` 現算，不是背的）、`root_agent.sub_agents[0]` 是不是那個遠端 agent。

再跑一次名片檢查，這次用對的 host：

```bash
uv run check_card.py; echo "exit=$?"        # → ✓ 名片可用 / exit=0
```

> 💡 **啊哈：多開一個行程聽起來是成本，實際上是把耦合面積砍掉四個數量級。**
> `sub_agents=[hotel_agent]` 這行寫法沒變，但代價變了：本地掛法要 `import hotel_service.agent`，B 拉進來的 743 個模組、12 MB python 原始碼就得跟服務 A 鎖在同一個 venv、同一組版本；A2A 掛法服務 A 對服務 B 的全部認識是 788 bytes 的 JSON 加一個 URL —— 所以服務 B 可以是 Go 寫的，也可以自己升 ADK 大版本。
> 貴的**不是**行程記憶體：A 自己就是 ADK agent，本來就載了大半，實測 B 只多帶 8 個模組進來。貴的是版本被綁死。
> **動手看**：`uv run hotel_service/agent.py --aha` → [1] 表最後一行 `耦合面積差 15,241×`（鎖在一起的 12.0 MB 原始碼 ÷ 788 bytes 名片；模組數與 MB 會隨你裝的版本浮動）

---

## 步驟 4：端到端測試（20 分）

### 4a. 先跑不用 key 的那條（**這條我實測過**）

**動手**

```bash
uv run smoke_test.py
```

實測輸出：

```
搜尋中…
淺草和風旅館 2400 TWD
smoke ok（3 個 event，罐頭答案有回來）
```

**為什麼要先跑這個**：`smoke_test.py` 起了一個**假的訂房服務**在 `:8099`——用投影片 9.3 那套純 a2a-sdk 的骨架寫的（`AgentCard` + `AgentExecutor` + `TaskUpdater` + `create_jsonrpc_routes`），裡面**沒有 LLM**，只回一句罐頭字串 `淺草和風旅館 2400 TWD`。然後用 `RemoteA2aAgent` 透過 ADK `Runner` 去呼它，assert 那句罐頭字串真的跑回來。

它驗到的是整條協定鏈：名片發現 → origin 檢查 → JSON-RPC `SendMessage` → `TASK_STATE_WORKING` → artifact → `TASK_STATE_COMPLETED` → 轉回 ADK `Event`。**完全不需要 API key、不需要網路、不花一毛錢。**

為什麼不用 key 也跑得起來？因為 `Runner(agent=<RemoteA2aAgent>)` 的 agent 本身就是個轉發器，它不呼叫模型。LLM 只在「有一個 root LlmAgent 要決定要不要委派」的時候才登場——那是 4b。

順便一提：這個假服務是純 a2a-sdk 寫的、不是 ADK 寫的，卻被 ADK 的 `RemoteA2aAgent` 呼通了。**投影片 387 的加分題（步驟 6）「證明跨框架互通」在這裡已經先驗過一半了。**

3 個 event 分別是：`WORKING` 狀態附帶的訊息（`搜尋中…`）、artifact 的文字、一個沒有 content 的空 event。這也是為什麼 `text_of()` 一定要能吃 `content is None`——status 事件身上沒有 content，直接 `event.content.parts` 就是 `AttributeError`。

**驗收**

```bash
uv run smoke_test.py --self-check      # → self-check ok（連 server 都不起，只驗事件解析）
uv run smoke_test.py                   # → 最後一行 smoke ok（…）
```

> 💡 **啊哈：Lab 10 的雲端版 concierge 跟你剛寫的這支，差別可以用 `diff` 看完。**
> A2A 把「服務在哪」壓縮成一個字串，所以「本機兩個行程」與「雲端兩個 Cloud Run 服務」在程式碼上是同一個位置 —— 上雲改的是網址與憑證，不是架構。
> **動手看**：`diff <(sed -n '/= RemoteA2aAgent(/,/^)/p' concierge/agent.py) <(sed -n '/= RemoteA2aAgent(/,/^)/p' ../lab10/concierge/agent.py)` → 只差三件事：`description` 的措辭、URL 來源（`HOTEL_SERVICE_URL` → `A2A_URL`）、Lab 10 沒傳 `timeout`

### 4b. 再跑真的（需要 API key）

**動手**：兩個 `.env` 都填好 key。

```bash
cp hotel_service/.env.example hotel_service/.env
cp concierge/.env.example     concierge/.env
# 兩個檔案裡的 GOOGLE_API_KEY 都換成你的 key
```

分頁 1 重啟服務 B（讓它讀到新的 `.env`）：

```bash
uv run uvicorn hotel_service.agent:a2a_app --port 8001
```

分頁 2：

```bash
uv run adk web
```

開 <http://localhost:8000>，**左上角選 `concierge`**，問：

```
東京 3000 以內的旅館
```

**為什麼**

- **為什麼要選 `concierge` 而不是 `hotel_service`**：`adk web` 會掃當前目錄下所有有 `root_agent` 的資料夾，所以清單裡兩個都在。選到 `hotel_service` 你會發現它自己就答得出來——完全沒有跨服務，也就沒有這個 Lab 要看的東西。
- **為什麼要重啟服務 B**：`.env` 是行程啟動時讀的。key 填完不重啟，服務 B 那邊會在 LLM 呼叫時失敗，而你在服務 A 的 UI 上看到的只會是一個含糊的錯誤——真正的原因在**分頁 1 的 log 裡**。A2A 的 debug 原則：兩個分頁的 log 都要看。

**驗收**：三件事同時成立才算過。

1. **答案內容**：出現 `淺草和風旅館`（2400）與 `上野站前商旅`（2900），沒有第三間（3600 那間超預算）。價格是我寫死的假資料——如果它給你別的旅館，那是模型在編，代表委派沒成功。
2. **Events 面板**：展開左側 Events，要看到 `hotel_agent` 這個 sub-agent 的事件，不是只有 `concierge` 自己在講話。
3. **分頁 1 的 log**：要多出一行 POST 記錄，像這樣：

```
INFO:     127.0.0.1:57291 - "POST / HTTP/1.1" 200 OK
```

**這一行是唯一的鐵證**——它證明請求真的跨了行程邊界。前兩件事都可以被一個很會編故事的模型假造出來，這一行不行。

> ⚠️ 未實測：4b 全部需要 API key，我沒有 key，沒有跑過。上面的旅館名稱與價格是從 `HOTELS` 假資料推出來的（`--self-check` 驗過過濾邏輯），但模型實際怎麼組句子我沒看過。`adk web` 的 UI 佈局與 Events 面板長相也沒實際確認。
> ⚠️ 未實測：`adk web` 是否真的同時列出 `hotel_service` 與 `concierge`。這是從「兩個目錄都有 `root_agent`」推的。

---

## 步驟 5：觀察狀態流 —— 慢查詢與 WORKING 串流（10 分）

### 5a. 先照投影片做，然後發現看不到串流

**動手**：分頁 1 `Ctrl-C`，加上 6 秒延遲重啟：

```bash
HOTEL_SLOW_SECONDS=6 uv run uvicorn hotel_service.agent:a2a_app --port 8001
```

回 `adk web` 問同一個問題。你會等大約 6 秒，然後答案**一次全部出現**。

投影片 371 講的 `SUBMITTED → WORKING → COMPLETED` 狀態機、投影片 380 講的「WORKING 進度、artifact、COMPLETED 依序到達」——你**看不到中間那段**。

**為什麼**：回去看步驟 2 的名片：

```
streaming False   push False
```

`to_a2a()` 自動生的名片，`capabilities.streaming` 是 **`false`**（`AgentCardBuilder` 的預設 `AgentCapabilities()` 就是全 false）。A2A 的 binding 是**協商**出來的，決定權在名片。a2a-sdk 的客戶端裡就這一行（`a2a/client/base_client.py`）：

```python
if not self._config.streaming or not self._card.capabilities.streaming:
```

兩邊都要 true 才走 SSE；名片說 false，客戶端就退回一次性的 `SendMessage`——`WORKING` 那些中間狀態根本不會送出來。

這是投影片沒講的一層：**`to_a2a()` 一行上網是真的，但一行上網的東西不會串流。**

**驗收（這一步也是「成功地失敗」）**

```bash
uv run check_card.py | grep streaming        # → streaming False   push False
```

名片是 `False`，就不用再懷疑是不是 UI 沒顯示——是協定層根本沒送。

### 5b. 修好：給它一張宣告 streaming 的名片

**動手**：`to_a2a` 的 `agent_card=` 參數吃一個 `AgentCard` 物件（或一個 JSON 檔路徑）。本 Lab 的 `hotel_service/agent.py` 已經用 `A2A_STREAMING=1` 把這條路開好了：

```python
def _card(port: int):
    """streaming=true 的自訂名片。to_a2a 自動生的名片 capabilities.streaming 是 false。"""
    from a2a.types import AgentCapabilities
    from google.adk.a2a.utils.agent_card_builder import AgentCardBuilder

    builder = AgentCardBuilder(
        agent=root_agent,
        rpc_url=f"http://localhost:{port}/",                 # ← origin 要對得上，見步驟 3
        capabilities=AgentCapabilities(streaming=True),
    )
    return asyncio.run(builder.build())      # 模組載入時還沒有 event loop，可以 asyncio.run

a2a_app = to_a2a(root_agent, port=A2A_PORT,
                 agent_card=_card(A2A_PORT) if os.getenv("A2A_STREAMING") == "1" else None)
```

```bash
# 分頁 1：換名片重啟服務 B
HOTEL_SLOW_SECONDS=6 A2A_STREAMING=1 uv run uvicorn hotel_service.agent:a2a_app --port 8001
```

**分頁 2 的 `adk web` 也要 Ctrl-C 重開。** `RemoteA2aAgent` 解析名片成功之後就把 card 與 client 快取在 `self._is_resolved` / `self._a2a_client` 裡（原始碼 `_ensure_resolved()`），不會每輪重抓——服務 B 換了名片、服務 A 沒重啟，你看到的還是舊的 `streaming=false` 行為。

**為什麼這樣寫**

- **借 `AgentCardBuilder` 而不是手刻 `AgentCard(...)`**：手刻的話 `name`／`description`／每個 tool 的 skill 都要自己填一遍，而且以後加工具還得記得同步。借 builder 就只有 `capabilities` 這一個欄位是我改的，其他照樣自動生成。投影片 376 那種手刻寫法在「我要完全控制名片」時才值得。
- **`rpc_url=f"http://localhost:{port}/"` 不能寫死。** 自訂名片的 URL **`to_a2a` 不會幫你改寫**（原始碼註解寫得很明白：a caller-provided agent_card's advertised url is not rewritten）。寫死 8001 然後用 `--port 8002` 跑，就回到步驟 3 那個 origin 錯誤。
- **`asyncio.run()` 在模組頂層是安全的。** `AgentCardBuilder.build()` 是 async，但 uvicorn 是先 import 模組、後開 event loop，所以 import 時沒有 running loop，`asyncio.run` 不會噴 `RuntimeError: asyncio.run() cannot be called from a running event loop`。如果你把這段搬進 lifespan 或任何 async 函式裡，就得改成 `await`。

**驗收**

```bash
uv run check_card.py | grep streaming
```

實測輸出：

```
streaming True   push False
```

（`A2A_STREAMING=1 HOTEL_SLOW_SECONDS=6 uv run uvicorn hotel_service.agent:a2a_app --port 8001` 起來之後直接檢查名片，`capabilities` 確實變成 `{'streaming': True}`。）

**「streaming=true 真的會多送 WORKING 事件」這件事其實已經有離線證據**：`smoke_test.py` 的假服務名片就是 `capabilities=AgentCapabilities(streaming=True)`，而它的輸出第一行就是 `WORKING` 狀態帶的訊息：

```
搜尋中…                       ← TASK_STATE_WORKING 的 status message
淺草和風旅館 2400 TWD         ← artifact
smoke ok（3 個 event，罐頭答案有回來）
```

把那張假名片的 `AgentCapabilities(streaming=True)` 改成 `False` 再跑一次，實測輸出變成：

```
淺草和風旅館 2400 TWD
smoke ok（1 個 event，罐頭答案有回來）
```

`搜尋中…` 消失了，event 從 3 個變 1 個——**同一個 server、同一段 executor，只改名片一個布林值**。這就是「名片決定協商結果」的離線證據，不用 API key 就能自己驗一次。

然後回 `adk web` 問同一題，觀察是否在等待的 6 秒內先看到中間狀態。

> 💡 **啊哈：名片不是伺服器狀態，是 python 反射出來的靜態契約 —— 服務關掉也生得出來。**
> 你剛才那張自訂名片是 `AgentCardBuilder` 從 `root_agent` 物件算出來的，跟有沒有 uvicorn 在跑無關。所以它可以當 `openapi.json` 用：進版控、在 CI 裡 diff。「有人改了工具的 docstring」＝「公開契約變了」，這件事在 code review 就攔得到，不用等對方的 agent 在生產環境呼叫失敗。
> **動手看**：分頁 1 `Ctrl-C`，然後 `lsof -i :8001`（什麼都不印）再 `uv run hotel_service/agent.py --aha` → 8001 上沒有任何東西在跑，名片照樣算出 `788 bytes，skills 2 個`

> ⚠️ 未實測：`adk web` UI 上「6 秒延遲期間是否真的出現 WORKING 中間狀態」我沒有跑過（需要 API key）。名片欄位從 `false` 變 `true` 是實測的；`streaming=true` 之後 ADK 客戶端與 UI 會怎麼呈現中間狀態，我只能從協定推論。

---

## 步驟 6：加分題 —— 第三個非 ADK agent（15 分，選做）

**動手**：`smoke_test.py` 裡的 `build_app()` 就是一個完整的、純 a2a-sdk 寫的 A2A 服務（投影片 376–378 的三個 Step 都在裡面）。把它抄出來改成匯率 agent：

```python
def convert(text: str) -> str:
    # ponytail: 寫死匯率，要真的就接 API
    amount = float(next(t for t in text.split() if t.replace(".", "").isdigit()))
    return f"{amount} JPY ≈ {amount * 0.21:.1f} TWD"
```

把 `FakeExecutor.execute()` 裡的罐頭字串換成 `convert(get_message_text(context.message))`，`AgentCard` 的 `name`／`skills` 改成匯率，port 換 8002，然後在 `concierge/agent.py` 多掛一個：

```python
fx_agent = RemoteA2aAgent(name="fx_agent", description="日圓台幣換算（遠端服務 :8002）。",
                          agent_card=card_url("http://localhost:8002"), timeout=30.0)
root_agent = Agent(..., sub_agents=[hotel_agent, fx_agent])
```

**為什麼這證明了跨框架**：`fx_agent` 那支服務裡沒有一行 ADK、沒有 LLM、沒有 Gemini。concierge 呼它跟呼 `hotel_agent` 用的是同一段程式碼路徑。這就是投影片 374 那句「雙方都是黑盒子」的實測版——同理，對方換成 Go 或 LangGraph 寫的也一樣通。

**驗收**

```bash
uv run check_card.py http://localhost:8002        # → ✓ 名片可用
```

> ⚠️ 未實測：這個加分題我沒有實作成檔案。不過 `smoke_test.py` 的假服務就是「純 a2a-sdk 服務被 `RemoteA2aAgent` 呼通」的實測案例（`uv run smoke_test.py` 通過），所以跨框架這件事的機制已經驗過了，剩下的只是把罐頭字串換成匯率換算。

---

## 步驟 7：驗收

不需要 API key 的（**這些我全部實測過**）：

- [ ] `uv run hotel_service/agent.py --self-check` → `self-check ok`
- [ ] `uv run concierge/agent.py --self-check` → `self-check ok`
- [ ] `uv run check_card.py --self-check` → `self-check ok`
- [ ] `uv run smoke_test.py --self-check` → `self-check ok`
- [ ] `uv run smoke_test.py` → `smoke ok（3 個 event，罐頭答案有回來）`
- [ ] 服務 B 起來後 `uv run check_card.py; echo $?` → `✓ 名片可用` / `0`
- [ ] `uv run check_card.py http://127.0.0.1:8001; echo $?` → `✗ origin 不一致…` / `1`
- [ ] `curl -s http://localhost:8001/.well-known/agent-card.json | grep -c search_hotels` → `1`
- [ ] `uv run hotel_service/agent.py --aha` → 印出耦合面積對照表（服務不用起來也能跑）

需要 API key 的：

- [ ] `adk web` 選 `concierge`，問「東京 3000 以內的旅館」，答案含 `淺草和風旅館` 與 `2400`
- [ ] Events 面板有 `hotel_agent` 的事件
- [ ] 分頁 1 出現 `"POST / HTTP/1.1" 200 OK`
- [ ] `HOTEL_SLOW_SECONDS=6` 後同一題會等約 6 秒

觀念題（答不出來就回去看對應的「為什麼」）：

- [ ] 你能說出「`to_a2a(port=8001)` 但 `uvicorn --port 8002`」會噴什麼錯，而且真的試過
- [ ] 你能說出「為什麼 `instruction` 不會上名片，但 `description` 會」
- [ ] 你能說出「什麼時候本地 `sub_agents` 就夠、不用 A2A」（投影片 386）

---

## 常見錯誤對照表

| 症狀 | 原因 | 解法 |
|---|---|---|
| `ModuleNotFoundError: No module named 'google'` | 用了 `python xxx.py` | 一律 `uv run xxx.py` |
| `ModuleNotFoundError: No module named 'a2a'` | 只裝了 `google-adk`，A2A 支援是 extra | `uv add "google-adk[a2a]"` |
| uvicorn 噴 `ModuleNotFoundError: No module named 'sse_starlette'` ＋ `ERROR: Application startup failed. Exiting.`，`to_a2a()` 本身卻不報錯，curl 得到 connection refused | 缺 `a2a-sdk` 的 http-server 相依。路由是在 lifespan startup 才掛的，所以 import 階段看不出來；startup 失敗行程就結束 | `uv add "a2a-sdk[http-server]"` |
| `Failed to resolve remote A2A agent hotel_agent: Agent card RPC URL must have the same origin as the location the card was fetched from (http://127.0.0.1:8001/.well-known/agent-card.json): http://localhost:8001` | 客戶端用 `127.0.0.1`，名片寫 `localhost`（或 `A2A_PORT` 與 `--port` 不一致） | 兩邊統一。`to_a2a` 預設 `host="localhost"`，所以客戶端也用 `localhost`；port 兩邊同一個數字 |
| `Failed to resolve AgentCard from URL http://localhost:8001/.well-known/agent-card.json: Network communication error fetching agent card from ...: All connection attempts failed` | 服務 B 沒在跑，或 port 打錯 | 分頁 1 起 uvicorn；`uv run check_card.py` 會講人話 |
| `Agent card RPC URL must use https, or http on a loopback host: http://booking.example.com` | 非 loopback 的 host 用 http。ADK 只在 loopback 放行 http | `to_a2a(host=<網域>, protocol="https")`——兩個參數都要傳（Lab 10） |
| `ERROR: [Errno 48] error while attempting to bind on address ('127.0.0.1', 8001): [errno 48] address already in use` | 上一輪的 uvicorn 還活著，或 8000/8001 撞到 `adk web` | `pkill -f "uvicorn hotel_service"`；換 port 時**名片與 `--port` 要一起改** |
| `KeyError: 'supported_interfaces'` | 名片 JSON 是 camelCase，投影片 370 的範例是 Python 欄位名 | 讀 `card["supportedInterfaces"]`；`false` 欄位可能整個不存在，一律 `.get(k, False)` |
| 名片上 skill 的 description 是 `An ADK Agent` | `Agent(description=...)` 是空的，`AgentCardBuilder` 用了 fallback | 補 `description`。這是別人決定要不要呼叫你的唯一依據 |
| concierge 自己編了一堆假旅館價格，沒有委派 | `RemoteA2aAgent` 的 `description` 太模糊；root 的 `instruction` 沒禁止 | `description` 寫清楚能做什麼；`instruction` 明寫「不要自己編價格」 |
| concierge 卡住十分鐘 | `RemoteA2aAgent` 的 `timeout` 預設 **600 秒** | 傳 `timeout=30.0` |
| 輸出被 `UserWarning: [EXPERIMENTAL] to_a2a: ADK Implementation for A2A support ...` 洗掉 | ADK 的 A2A 實作標記 EXPERIMENTAL，每次建物件都警告一次 | `export ADK_SUPPRESS_A2A_EXPERIMENTAL_FEATURE_WARNINGS=1` |
| `adk web` UI 上只看到含糊的錯誤，看不出哪裡壞 | 名片解析失敗時 ADK **不拋例外到 UI**，只 log 一行 ERROR 然後吐空 event | 看**兩個分頁**的終端機 log，不要只看 UI |
| `AttributeError` / `TypeError: 'NoneType' object is not iterable` 在取 event 文字時 | `WORKING` 狀態事件身上沒有 `content` | `getattr(ev, "content", None)` ＋ `or []`，見 `smoke_test.text_of()` |
| `RuntimeError: asyncio.run() cannot be called from a running event loop` | 把 `_card()` 搬到 async 函式或 lifespan 裡了 | 留在模組頂層（import 時還沒有 loop），或改成 `await builder.build()` |
| 明明 `export` 過 key 還是說沒有 key | ADK 讀的是 **agent 目錄下**的 `.env`，不是專案根目錄 | `hotel_service/.env` 與 `concierge/.env` 各放一份 |
| 改完 `.env` 沒生效 | `.env` 是行程啟動時讀的 | 兩個服務都重啟 |
| `RuntimeError: 假服務起不來：http://localhost:8099/...` | 8099 被別的東西佔住（前面的 lab 也用這個 port） | `SMOKE_PORT=8098 uv run smoke_test.py` |
| 服務 B 加了 `A2A_STREAMING=1` 重啟了，服務 A 那邊行為卻沒變 | `RemoteA2aAgent` 名片解析成功後會快取 card 與 client（`_ensure_resolved()` 的 `self._is_resolved`），**不會每輪重抓名片** | 名片改了就連 `adk web`（服務 A）一起重啟 |

---

## 完整解答

本目錄的四支程式就是走完七步的版本：

| 檔案 | 是什麼 |
|---|---|
| `hotel_service/agent.py` | 服務 B。`search_hotels` ＋ `hotel_agent` ＋ `a2a_app`，含 `A2A_STREAMING` 自訂名片、`--self-check`、`--aha`（離線耦合面積對照） |
| `concierge/agent.py` | 服務 A。`RemoteA2aAgent` ＋ `concierge` root agent，含 `--self-check` |
| `check_card.py` | 名片檢查工具。只用標準庫，不通就 exit 1，可以塞 CI |
| `smoke_test.py` | 假 A2A 服務 ＋ 端到端驗證。不用 key、不連網、不花錢 |

想看設計理由與完整契約：同目錄的 `SPEC.md`（架構圖、`to_a2a`／`RemoteA2aAgent` 實際簽章、名片 JSON 全文、origin 檢查規則、13 條錯誤處理）與 `PRD.md`（學習目標、11 條需求對照投影片步驟、費用、前置依賴）。

---

## 想再往下玩

- **把假資料換成真的**：`tools=[search_hotels]` 換成 Lab 8 的 `McpToolset`（MCP Toolbox + Supabase pgvector）。`hotel_service/agent.py` 其他部分一行都不用改——這就是把 agent 包成服務的好處。
- **加一個會反問的 task**：讓 `hotel_agent` 在預算不明時回 `TaskState.TASK_STATE_INPUT_REQUIRED`（投影片 371）。這是 A2A 與「工具呼叫」的分水嶺，工具永遠不會反問。
- **換掉 task store**：`to_a2a(task_store=DatabaseTaskStore(engine=...), lifespan=...)`，讓服務 B 重啟之後還記得沒做完的 task。`to_a2a` 的 docstring 裡有現成範例。注意附錄 D 第 ② 條：DB driver 要 async（`postgresql+asyncpg`）。
- **接下去是 Lab 10**：把服務 B 原封不動部署到 Cloud Run。你只要改三件事——`to_a2a(host=<Cloud Run 網域>, protocol="https")`、`HOTEL_SERVICE_URL` 指向新網址、加上 IAM ID token（`audience` 必須全等於服務 URL，差一字元就 401，附錄 D 第 ⑦ 條）。步驟 3 那個 origin 錯誤與「http 只准 loopback」的規則，你會在那裡再遇到一次。

---

## 這個 Lab 你真正學到的

- **A2A 在 Google 生態系裡的位置**：MCP 是 agent 往下拿工具（垂直），A2A 是 agent 往旁邊叫同事（水平）；同一份訂房能力兩條路都包得出來，差別在「控制權交不交出去」。
- **agent 之間的介面是協定，不是 import**：服務 A 對服務 B 的知識上限就是那 788 bytes 的名片 —— 這是限制，也正是隔離的來源（跨語言、跨團隊、各自升版）。
- **名片是公開 API，不是註解**：`description` 與工具 docstring 會被抄到不用認證就抓得到的檔案上，`instruction` 與實作不會。寫這兩段時就是在寫對外契約。
- **能力是協商出來的，不是程式碼決定的**：`capabilities.streaming` 一個布林值就決定客戶端走 SSE 還是一次性回應——同一個 server、同一段 executor，行為完全不同。
- **本機的 `localhost:8001` 與雲端的 `*.run.app` 在程式碼上是同一個位置**：Lab 10 改的是 URL、scheme 與憑證，不是架構。

---

## 清理

**沒有任何雲端資源要刪**——沒建 GCP 專案、沒開服務、沒上傳檔案。費用 $0（步驟 4、5 那十幾輪 `gemini-3.7-flash` 對話都在免費層額度內）。

要收乾淨三件事：

```bash
# 1) 關掉背景的服務（8001 被佔住的話下次啟動會 Errno 48）
pkill -f "uvicorn hotel_service"
lsof -i :8001 -i :8000 -i :8099        # 應該什麼都不印

# 2) 清掉 key（.env 不要進版控）
rm -f hotel_service/.env concierge/.env

# 3) 本機環境，下次 uv run 會自己重建
rm -rf .venv __pycache__ */__pycache__
```

那把 AI Studio key 如果之後還要用（Lab 10 會用），留著；不用了就到 <https://aistudio.google.com/apikey> 按 Delete。
