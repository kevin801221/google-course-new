# Lab 6 走一遍：自建 MCP Server 接進 Antigravity

> 60–90 分鐘 ｜ 完整走一遍 server 開發循環：寫 → Inspector 測 → 接 host → agent 實用

做完你會有一台 `server.py`：兩個工具（匯率換算、查天氣）＋一個 resource（課程名詞表）＋一個 prompt。它同時能被 Antigravity、Claude Code、Cursor 和 M7 的 ADK agent 使用 —— 寫一次，處處用。

先看驗收長什麼樣（這是本機真實輸出）：

```
$ uv run probe.py
tools: ['convert_currency', 'get_weather']
  convert_currency {'amount': 'number', 'rate': 'number'} required=['amount']
  get_weather {'lat': 'number', 'lon': 'number'} required=['lat', 'lon']
convert_currency(100) -> {  "status": "success",  "usd": 100.0,  "twd": 3200.0,  "rate": 32.0}
convert_currency(-5) -> is_error = True | Error executing tool convert_currency: amount 必須 >= 0，收到的是 -5.0
resource templates: ['course://glossary/{term}']
course://glossary/mcp -> Model Context Protocol：AI 的 USB-C，統一工具的發 …
prompts: ['daily_briefing']
get_weather(台北) -> {  "status": "success",  "temp_c": 27.4,  "wind_kmh": 9.1,  "precipitation_mm": 0.0}
probe OK
```

然後在 Antigravity 裡對 agent 說一句「查台北現在天氣，順便把 100 美元換算成台幣」，它會自己呼叫兩個工具。

每一步都有「動手 → 為什麼 → 驗收」。**驗收沒過不要往下走** —— 這個 lab 後半段是 host 設定，帶著壞掉的 server 進去會分不清是誰的錯。

---

## 步驟 0：前置（5 分）

**動手**：這個 Lab **不需要 API key、不需要 GCP、不花錢**。要的只有 uv 和 Node。

```bash
uv --version                 # → uv 0.12.3 （或更新）
node --version               # → v20 以上（Inspector 是 node 寫的，用 npx 跑）
which uv                     # → /opt/homebrew/bin/uv  ← 記下來，步驟 4 要用絕對路徑
```

**驗收**：三個指令都有輸出。`node` 沒裝就先裝（p10），不然步驟 3 的 Inspector 起不來。

Antigravity 桌面版（Lab 3 裝過的）也要在 —— 步驟 4 之後都靠它。沒有 Antigravity 可以用 Claude Code 或 Cursor 代替，設定檔格式差異見步驟 4 的對照表。

---

## 步驟 1：選一個你真實會用的題目（5 分）

**動手**：照投影片建議的組合做 —— **匯率換算＋天氣查詢＋公司內部名詞表**（tool×2＋resource×1）。本 walkthrough 就照這組。

**為什麼是這三個而不是隨便三個**

| 能力 | 為什麼選它 |
|---|---|
| `convert_currency`（tool） | **純運算、零依賴**。第一個工具要能在 30 秒內驗對錯，這樣 schema 生成出問題時你知道不是網路的事 |
| `get_weather`（tool） | **會打外部 API**，逼你處理 timeout、上游錯誤、參數防呆 —— 真實工具的樣子。Lab 7 的 weather MCP 直接沿用這隻 |
| `course://glossary/{term}`（resource） | resource 是「應用讀取」而不是「模型呼叫」，要親手做一個才會記得差別（p254） |

換成你自己的題目也可以，但**保留這個形狀**：一個純運算、一個打 API、一個 resource。三種失敗模式各一個。

**驗收**：你能講出「這兩個工具為什麼不合併成一個」—— 因為 p262 原則②：一個工具做一件事，但常見組合要能被模型自己串起來（步驟 5 就是在驗這件事）。

---

## 步驟 2：實作 `server.py`（25 分）

### 2a. 建專案（並且先撞一次牆）

**動手**

```bash
mkdir -p lab6 && cd lab6
uv init --bare --name lab6-mcp
uv add "mcp[cli]"
```

現在**照投影片 p258 原文**寫一支 `hello.py`：

```python
# hello.py —— 投影片原文，2026-08 會炸
from mcp.server.fastmcp import FastMCP
mcp = FastMCP("course-tools")
```

```bash
uv run hello.py
```

它會這樣炸：

```
ModuleNotFoundError: No module named 'mcp.server.fastmcp'. This is mcp 2.x, where
FastMCP was renamed to MCPServer (from mcp.server.mcpserver import MCPServer) and
other APIs changed; see the migration guide at
https://py.sdk.modelcontextprotocol.io/v2/migration/#fastmcp-renamed-to-mcpserver
or pin 'mcp<2' to keep running v1 code.
```

**為什麼要故意先撞這一下**

投影片 p259 寫「官方 python-sdk（mcp 套件）v1.x 穩定」，但今天 `uv add "mcp[cli]"` 解到的是 **2.1.1**，`FastMCP` 已經改名 `MCPServer`。這是你這輩子會遇到最多次的 bug 類型：**教材寫的版本 ≠ 你裝到的版本**。SDK 這次很佛心，錯誤訊息直接告訴你改名前後和 migration guide —— 大部分套件不會。

兩條路都對，選一條：

```bash
# 路 A（本 Lab 走這條）：用新版，鎖住大版本
uv add "mcp[cli]>=2,<3"
# 路 B：要照投影片原文寫 FastMCP
uv add "mcp[cli]<2"          # 實測解到 1.29.1，FastMCP 還在
```

**不鎖大版本會怎樣**：下一次 3.x 出來，你的 `uv sync` 會安靜地換掉 SDK，然後某天 server 突然起不來。`>=2,<3` 一行解決。

```bash
rm hello.py                  # 撞完就刪
```

**驗收**

```bash
uv run python -c "from mcp.server.mcpserver import MCPServer; print('ok')"   # → ok
uv run mcp version                                                          # → MCP version 2.1.1
```

### 2b. 先寫一個「爛工具」，看它爛在哪

先故意寫沒有型別註記、沒有 docstring 的版本：

```python
# server.py —— 第一版，故意寫壞
from mcp.server.mcpserver import MCPServer

mcp = MCPServer("course-tools")

@mcp.tool()
def convert_currency(amount, rate=32.0):
    return {"twd": amount * rate}

if __name__ == "__main__":
    mcp.run()
```

看 SDK 幫你生成出什麼 schema：

```bash
uv run python -c "
import asyncio, json, server
async def m():
    for t in await server.mcp.list_tools():
        print(t.name, '| desc:', repr(t.description), '|', json.dumps(t.input_schema))
asyncio.run(m())"
```

實際輸出：

```
convert_currency | desc: '' | {"properties": {"amount": {"title": "amount", "type": "string"},
 "rate": {"default": 32.0, "title": "rate", "type": "string"}}, "required": ["amount"],
 "title": "convert_currencyArguments", "type": "object"}
```

**為什麼這是災難**

1. `description` 是空字串 —— 模型完全不知道這個工具是幹什麼的，只能從名字猜。p262 原則①：**模型選錯工具幾乎都是描述寫太爛**。
2. 沒有型別註記 → 參數 schema 變成 `"type": "string"`。模型會乖乖照 schema 傳字串 `"100"` 進來，然後 `"100" * 32.0` 在 Python 裡直接爆 `TypeError`。
3. 而且爆掉之後，模型只會看到 `Error executing tool convert_currency` —— **沒有任何原因**（下面 2c 解釋）。

這就是 p261 的「工具沒出現／行為怪 → docstring/型別缺失」。它**不報錯**，只是安靜地變爛。

### 2c. 補齊型別、docstring 與 `ToolError`

```python
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

mcp = MCPServer("course-tools")   # 變數名只能是 mcp / server / app

@mcp.tool()
def convert_currency(amount: float, rate: float = 32.0) -> dict:
    """把美元金額換算成新台幣（TWD）。

    什麼時候用我：使用者提到美元、USD、匯率換算，或要把報價換成台幣時。
    參數：amount 是美元金額（必須 >= 0）；rate 是 1 美元兌台幣的匯率（必須 > 0，預設 32.0）。
    回傳：{"status": "success", "usd": 原金額, "twd": 換算結果, "rate": 使用的匯率}。
    注意：本工具不查即時匯率，rate 沒給就用預設值 32.0，需要精準數字請自行帶入 rate。
    """
    if amount < 0:
        raise ToolError("amount 必須 >= 0，收到的是 %r" % amount)
    if rate <= 0:
        raise ToolError("rate 必須 > 0（1 美元兌台幣），收到的是 %r" % rate)
    return {"status": "success", "usd": amount, "twd": round(amount * rate, 2), "rate": rate}
```

**為什麼 docstring 要寫成這種格式**

docstring 就是**模型看到的 API 文件**，不是給人看的註解。四段固定寫：什麼時候用我／參數意義與界線／回傳什麼／有什麼陷阱。少了「什麼時候用我」，模型在有 10 個工具時會亂挑；少了「不查即時匯率」，模型會理所當然拿 32.0 當今天的匯率報給使用者。

**為什麼一定要用 `ToolError` 而不是 `ValueError`**

投影片 p259 寫「raise 例外會變成協定層錯誤回報給模型 —— 訊息寫清楚，模型會自己重試」。**在 mcp 2.x 這句話只有一半對。** 直接讀 SDK 原始碼（`mcp/server/mcpserver/tools/base.py`）：

```python
except (ToolError, ResourceError) as exc:
    # 你刻意 raise 的：訊息會帶給 client
    raise ToolError(f"Error executing tool {self.name}: {exc}") from exc
except Exception as exc:
    # 其他例外＝crash：例外自己的文字留在 server 端
    raise UnexpectedToolError(f"Error executing tool {self.name}") from exc
```

實測差別：

| 你寫的 | 模型看到的 |
|---|---|
| `raise ToolError("amount 必須 >= 0，收到的是 -5.0")` | `Error executing tool convert_currency: amount 必須 >= 0，收到的是 -5.0` ← 它知道怎麼修 |
| `raise ValueError("amount 必須 >= 0")` | `Error executing tool convert_currency` ← 它只知道壞了，會原地重試同樣的參數 |

**不寫防呆會怎樣**：模型一定會傳你想不到的參數（p262 原則④）。沒有 `if amount < 0`，負數會安靜地算出負台幣，然後模型把它當事實講給使用者。

### 2d. 加打外部 API 的工具

投影片 p263 用 `httpx` ＋ `async def`。這裡改用 stdlib 的 `urllib`：

```python
import contextlib, json, urllib.parse, urllib.request

WEATHER_API = "https://api.open-meteo.com/v1/forecast"

def _get_json(url: str, params: dict) -> dict:
    req = urllib.request.Request(f"{url}?{urllib.parse.urlencode(params)}",
                                headers={"User-Agent": "lab6-mcp/0.1"})
    # ponytail: 同步阻塞 I/O；SDK 會把同步 tool 丟到 worker thread 跑，單人開發夠用。
    # 要並發打十幾個 API 再換成 async def ＋ httpx.AsyncClient。
    with contextlib.closing(urllib.request.urlopen(req, timeout=10)) as r:
        return json.loads(r.read())

@mcp.tool()
def get_weather(lat: float, lon: float) -> dict:
    """查詢指定經緯度的即時天氣：氣溫、風速、降雨量。

    什麼時候用我：使用者問某地「現在」的天氣、氣溫、要不要帶傘時。
    參數：lat 緯度 -90~90，lon 經度 -180~180。台北約 lat=25.03, lon=121.56；…
    回傳：{"status": "success", "temp_c": …, "wind_kmh": …, "precipitation_mm": …}。
    """
    if not -90 <= lat <= 90:
        raise ToolError("lat 必須在 -90~90 之間，收到的是 %r（別把經緯度寫反）" % lat)
    if not -180 <= lon <= 180:
        raise ToolError("lon 必須在 -180~180 之間，收到的是 %r" % lon)
    try:
        payload = _get_json(WEATHER_API, {"latitude": lat, "longitude": lon,
                                          "current": "temperature_2m,wind_speed_10m,precipitation"})
    except Exception as e:
        raise ToolError("open-meteo 查詢失敗（%s: %s），請稍後重試或換一組經緯度" % (type(e).__name__, e))
    cur = payload.get("current")
    if not cur:
        raise ToolError("open-meteo 回應沒有 current 欄位：%s" % json.dumps(payload)[:200])
    return {"status": "success", "temp_c": cur["temperature_2m"],
            "wind_kmh": cur["wind_speed_10m"], "precipitation_mm": cur["precipitation"]}
```

**為什麼不用 httpx 和 async**

- **不加依賴**：`urllib` 是 stdlib，一個 GET 不值得多一個套件。少一個依賴＝少一個供應鏈風險（p270 攻擊③），而且 Lab 10 上雲時 image 更小。
- **同步不會拖慢 server**：實測 SDK 的 `func_metadata.call_fn` 對非 async 函式走 `anyio.to_thread.run_sync(...)` —— 同步工具是在 worker thread 跑的，不會卡住 event loop。要並發打十幾個 API 再換 async。
- **`timeout=10` 不能省**：省掉的話上游卡住，host 那邊就是永久轉圈，使用者只看到 agent 沒反應。
- **`raise_for_status` 的替代**：`urlopen` 對 4xx/5xx 本來就 raise `HTTPError`，所以直接被我們的 `except Exception` 接住，包成看得懂的 `ToolError`。

**為什麼參數驗證要放在連網之前**

經緯度寫反（`lat=121.56`）是最常見的錯。先擋掉的話模型立刻拿到「別把經緯度寫反」，省一次網路往返；不擋的話 open-meteo 回 400，模型只看到一句「查詢失敗」，可能就放棄了。

### 2e. 加 resource 與 prompt

```python
GLOSSARY = {
    "mcp": "Model Context Protocol：AI 的 USB-C，統一工具的發現、描述與傳輸（M6）",
    "a2a": "Agent2Agent：agent 之間互相發現與委派任務的協定，與 MCP 互補（M9）",
    # …
}

@mcp.resource("course://glossary/{term}")
def glossary(term: str) -> str:
    """課程名詞解釋：把 term 換成 mcp / a2a / adk / skill / antigravity / grounding。"""
    return GLOSSARY.get(term.strip().lower(), "查無此名詞：%s（可用：%s）" % (term, "、".join(GLOSSARY)))

@mcp.prompt()
def daily_briefing(city: str = "台北", usd: float = 100.0) -> str:
    """產生每日簡報提示：同時用到天氣與匯率兩個工具。"""
    return (f"請用 get_weather 查 {city} 現在的天氣，再用 convert_currency 把 {usd} 美元換成台幣，"
            "最後用三行繁體中文摘要：天氣一行、匯率一行、今天適不適合出門一行。")
```

**為什麼 resource 不做成 tool**

Tools 是「模型決定何時呼叫」，resources 是「應用（host）拉進上下文」（p254）。名詞表這種靜態查表做成 resource，模型就不會為了查一個詞浪費一次 tool call；而且 host 可以快取（`ttlMs`）。

**為什麼 `term.strip().lower()`**

URI 裡的參數是使用者／模型手打的，`"MCP"`、`" mcp "` 都會來。不正規化就會查不到 —— 而且回傳空字串比報錯更糟，模型會以為「這個詞不存在」。所以查不到也要回一句話，並且**列出可用的 key**，讓模型自己修正。

### 2f. transport 開關與 `--self-check`

```python
if __name__ == "__main__":
    if "--self-check" in sys.argv:
        _self_check()
    elif os.getenv("MCP_TRANSPORT") == "http":
        # 2026-07-28 規格是無狀態的：stateless_http=True 才能在 Cloud Run 水平擴展
        mcp.run(transport="streamable-http", host="0.0.0.0",
                port=int(os.getenv("PORT", 8080)), json_response=True, stateless_http=True)
    else:
        mcp.run()   # 預設 stdio
```

**為什麼用環境變數切而不是兩個檔案**

transport 是啟動參數，不影響工具邏輯（p260）。兩個檔案＝工具邏輯要維護兩份，改一邊忘一邊。Lab 10 上 Cloud Run 時只要在部署設定裡加 `MCP_TRANSPORT=http`，程式碼一行都不用改。

**為什麼 `port` 讀 `PORT` 環境變數**：Cloud Run 會注入 `PORT`（p260 慣例）。寫死 8080 的話有天 Cloud Run 給你 8081，容器就啟動失敗。

**為什麼 `host="0.0.0.0"`**：容器內綁 `127.0.0.1` 的話外面的流量進不來。代價是本機測試時同網段的人也連得到 —— 測完就關。

> ⚠️ 投影片 p260 的 `mcp = FastMCP("course-tools", json_response=True)` 在 2.x 會炸 `TypeError: MCPServer.__init__() got an unexpected keyword argument 'json_response'`；反過來，`mcp.run(transport=..., host=..., port=...)` 在 1.x 會炸 `TypeError: FastMCP.run() got an unexpected keyword argument 'host'`（1.x 要把 host/port 放建構子）。兩個都實測過。

`_self_check()` 的重點是**不連網**：把 `urllib.request.urlopen` 換成 `SimpleNamespace` 假物件。完整內容看 `server.py`。

**驗收**

```bash
uv run server.py --self-check
```

```
self-check OK
```

---

## 步驟 3：Inspector 驗證（15 分）

### 3a. 先用可貼的指令驗（比 Inspector 快）

**動手**

```bash
uv run probe.py --offline
```

```
tools: ['convert_currency', 'get_weather']
  convert_currency {'amount': 'number', 'rate': 'number'} required=['amount']
  get_weather {'lat': 'number', 'lon': 'number'} required=['lat', 'lon']
convert_currency(100) -> {  "status": "success",  "usd": 100.0,  "twd": 3200.0,  "rate": 32.0}
convert_currency(-5) -> is_error = True | Error executing tool convert_currency: amount 必須 >= 0，收到的是 -5.0
resource templates: ['course://glossary/{term}']
course://glossary/mcp -> Model Context Protocol：AI 的 USB-C，統一工具的發 …
prompts: ['daily_briefing']
skip get_weather（--offline）
probe OK
```

`probe.py` 就是一支 40 幾行的 MCP client：它用 `uv run --directory <專案> server.py` 把 server 當子行程 spawn 起來（**跟 host 做的事一模一樣**），然後跑 `tools/list`、`tools/call`、`resources/read`、`prompts/get`。

**為什麼要有這一支，Inspector 不夠嗎**

Inspector 是給人點的（p261 說它是「MCP 的 Postman」），沒辦法貼在 walkthrough 裡當驗收指令，也不能放進 CI。`probe.py` 會 assert 三件最容易安靜壞掉的事：description 非空、參數型別不是 `string`、錯誤訊息真的傳到 client 手上。p466 建議每季跑一遍 Lab 6 的程式碼當 API 相容性金絲雀 —— 就是跑這支。

> 💡 **啊哈：JSON Schema 你一個字都沒敲，模型收到的規格卻比手寫版還長**
> M1 的 function calling 要你自己手寫 declaration（`probe.py` 裡附了等價的一份，**689 字元**），每加一個工具敲一份、每接一個 host 再敲一份。這裡你敲的 schema 是 **0 字元**，模型卻收到 **910**：其中 388 是 SDK 從型別註記生出來的，另外 **522 是你 docstring 的原文**。你為模型敲的每個字都是散文，一個括號都沒有。
> **動手看**：`uv run probe.py --aha` → 第 ① 張表「你敲的 declaration 字元」：手寫 689 vs `@mcp.tool()` 0。

### 3b. 再開 Inspector 手測

```bash
uv run mcp dev server.py
```

實際輸出（Inspector 2.3.0）：

```
Starting MCP inspector...

MCP Inspector Web is up and running at:
   http://127.0.0.1:6274?MCP_INSPECTOR_API_TOKEN=6f372aac016dad3224e9c20ce225a66d…

   Sandbox (MCP Apps): http://127.0.0.1:6275/sandbox

   Auth token: 6f372aac016dad3224e9c20ce225a66d…

Opening browser...
```

> **投影片 p261 寫「瀏覽器開啟 http://localhost:6274」—— 現在不行了。** Inspector 2.x 帶 token，要開它印出來的**完整 URL**；直接開 `localhost:6274` 會卡在要你貼 token。

三頁都要手動測過：

| 頁 | 做什麼 | 要看到什麼 |
|---|---|---|
| Tools | 點 `convert_currency`，填 `amount=100` 送出 | 參數欄位是數字型別；回應 `"twd": 3200.0` |
| Tools | 填 `amount=-5` 送出 | 紅色錯誤，訊息含「amount 必須 >= 0，收到的是 -5.0」 |
| Tools | 點 `get_weather`，填台北經緯度 | 真的回當下溫度 |
| Resources | 讀 `course://glossary/mcp` | 回「Model Context Protocol：AI 的 USB-C…」 |
| Prompts | 點 `daily_briefing`，city 填「高雄」 | 產出的 prompt 裡有 `get_weather` 和 `convert_currency` |

> ⚠️ 未實測：上面這五列是 Inspector 頁面裡的手動點擊結果 —— 這台機器沒有瀏覽器可點。已實測的是 `mcp dev` 起得來（Inspector 2.3.0）、`curl http://127.0.0.1:6274` 回 200，以及同樣這五件事在 `probe.py` 走真協定時的結果（tools/call 成功與 `is_error`、resource、prompt 都驗過）。

> 💡 **啊哈：模型讀到的工具說明，是逐字從你的 docstring 搬過去的**
> Inspector 那一欄不是「參考」你的 docstring，就是 `server.py` L52 那個字串本身（SDK 只多補一個結尾換行，`strip()` 後完全相等）。模型沒有第二個資訊源可以判斷何時該叫這個工具。而且這 1,286 字元的 `tools/list` payload，每開一個新對話就整份進 context —— 工具越多，每一輪都在付這個錢。
> **動手看**：`uv run probe.py --aha` → 第 ② 段印出 `docstring == 模型收到的 description ？ True`。

### 3c. 故意弄壞 stdout（一定要做這個實驗）

在 `convert_currency` 第一行插一句：

```python
    print("DEBUG amount=", amount)     # ← 故意的
```

重跑 `uv run probe.py --offline`。實測（mcp 2.1.1）**probe 還是 OK**，但最後多噴一段：

```
Failed to parse JSONRPC message from server
...
pydantic_core._pydantic_core.ValidationError: 1 validation error for
union[JSONRPCRequest,JSONRPCNotification,JSONRPCResponse,JSONRPCError]
  Invalid JSON: expected value at line 1 column 1
  [type=json_invalid, input_value='DEBUG amount= 100.0', input_type=str]
...
probe OK
```

**為什麼只是「多噴一段」而不是死掉 —— 這才是 2026 年的正確版本**

投影片 p260／p462 坑⑤ 說「stdio server 用 print() 會弄壞連線」。**在 mcp 2.x 這件事已經被 SDK 擋住了。** 讀 `mcp/server/stdio.py` 的 `stdio_server()` docstring：

```
While serving, fd 0 points at the null device and fd 1 at stderr, so handlers
and children read EOF and their stray output misses the wire; both descriptors
are restored on exit.
```

也就是說：server 一開始服務，SDK 就把 **fd 1 轉去 stderr**（`os.dup(2)`），協定本身改用一份私有的 fd 複本走。你的 `print` 因此落到 stderr，碰不到協定通道。實測兩件事：

```python
    print("DEBUG amount=", amount, flush=True)   # 立刻寫出
```

→ 終端機上看得到 `DEBUG amount= 100.0`（走 stderr），`probe OK`，**沒有任何 parse 錯誤**。

不加 `flush=True` 的版本，字串卡在 Python 的使用者層緩衝區裡；行程結束時 SDK 已經把 fd 1 還原成真的管線了，這時才 flush → 那一行真的上了線 → 就是你上面看到的那個 ValidationError。**它出現在連線收尾，所以不影響這次的呼叫結果。**

**那為什麼還是不准 print**

1. **舊版真的會炸**：走路 B（`uv add "mcp[cli]<2"`）就沒有這道護欄。實測 mcp 1.29.1 的同一個 print（加 `flush=True` 立刻寫出），client 在**呼叫進行中**就噴 `Invalid JSON: expected value at line 1 column 1 [type=json_invalid, input_value='DEBUG 1.0', input_type=str]`。
2. **這是 Python SDK 的好心，不是協定保證**：TypeScript／Go 的 server、或你自己 fork 出去的 transport 都不見得有。
3. **你的 debug 會「消失」**：print 出來的東西安靜地跑去 stderr，你在 host 的 log 面板裡找不到 stdout —— 只會覺得「怎麼沒印」。
4. **順帶一個更陰的**：fd 0 被指到 `/dev/null`。實測在工具裡 `sys.stdin.read(5)` 直接回 `''`（EOF）—— 想在工具裡 `input()` 問使用者話的人省省吧，那是 elicitation 的工作（p254）。

所以規則不變，只是理由變了：

```python
    print("DEBUG amount=", amount, file=sys.stderr)   # 明確寫 stderr，不靠 SDK 幫你轉
```

**驗收**：把 debug 行刪掉或改成 `file=sys.stderr`，`uv run probe.py --offline` 印出 `probe OK` 且**沒有** `Failed to parse JSONRPC message from server`。

---

## 步驟 4：接進 Antigravity（15 分）

**動手**

```bash
which uv           # 例：/opt/homebrew/bin/uv
pwd                # 例：/Users/你的帳號/Antigravity-teach/lab6
```

編輯 `~/.gemini/config/mcp_config.json`（沒有就建；**已經有內容的話是加一個 key，不要整檔覆蓋**）：

```json
{
  "mcpServers": {
    "course-tools": {
      "command": "/opt/homebrew/bin/uv",
      "args": ["run", "--directory", "/Users/你的帳號/Antigravity-teach/lab6", "server.py"]
    }
  }
}
```

然後在 Antigravity 的 MCP 面板按 **Refresh**（M3 教過）。

**為什麼每個欄位都要這樣寫**

| 寫法 | 不這樣寫會怎樣 |
|---|---|
| `command` 用 `uv` 的**絕對路徑** | host 是 GUI app，它的 PATH 不等於你 shell 的 PATH。寫 `"uv"` 有機會 spawn 不到，面板只顯示紅點不給你原因 |
| `args` 帶 `--directory <專案>` | 少了它，uv 從 host 的工作目錄找 `pyproject.toml`，找不到就沒有 `mcp` 套件 → server 立刻死掉 |
| **不要**寫 `"command": "python"` | 投影片 p460 範本裡的 `"command": "python"` 用在本 Lab 會 `ModuleNotFoundError: No module named 'mcp'`（實測），因為系統 python 沒有你 `uv add` 的相依 |
| server 名稱 `course-tools` | 這名字會出現在工具清單前綴，取得跟功能有關才找得到 |

其他 host 的同一件事（p273）：

| Host | 設定位置 | 遠端 URL 欄位 |
|---|---|---|
| Antigravity（全域） | `~/.gemini/config/mcp_config.json` | `serverUrl` |
| Antigravity（專案） | `.agents/mcp_config.json` | `serverUrl` |
| Claude Code | `claude mcp add` ／ `.mcp.json` | `url` |
| Cursor | `.cursor/mcp.json` | `url` |

> **最常見的跨工具地雷**：Antigravity 用 `serverUrl`，其他家用 `url`（p462 坑④）。從 Cursor 抄設定必踩。

**驗收**

- [ ] MCP 面板裡 `course-tools` 是連上的狀態（綠燈／Connected）
- [ ] 工具清單看得到 `convert_currency` 與 `get_weather`
- [ ] 對 agent 說「你現在有哪些工具？」，它把這兩個唸出來

沒出現的話，**先回步驟 3 跑一次 `uv run probe.py --offline`**：過了就是設定檔的錯（路徑、Refresh），沒過就是 server 的錯。這就是 p261 說的「先 Inspector 再接 host，除錯時間砍半」。

> ⚠️ 未實測：Antigravity 的 MCP 面板 UI、Refresh 行為與工具清單顯示 —— 這台機器上沒有 Antigravity 桌面版可驗。stdio 這條路本身已用 `probe.py`（同樣的 `uv run --directory … server.py` spawn 方式）走真協定驗過。

---

## 步驟 5：實戰測試（10 分）

**動手**：在 Antigravity 的 agent 對話裡貼：

```
查台北現在天氣，順便把 100 美元換算成台幣
```

**要觀察什麼**

1. 它呼叫了**兩個**工具（面板／對話裡會顯示 tool call 記錄）。
2. `get_weather` 的參數是 `lat=25.03, lon=121.56` 左右 —— 這是它從**你的 docstring** 裡讀到的（docstring 沒寫台北經緯度，它就得瞎猜或反問）。
3. 回答把兩份結果合成一段話，而不是貼兩坨 JSON。

再試 prompt：在對話框輸入 `/` 找到 `daily_briefing`，選它、city 填「高雄」。

**為什麼這一步是整個 Lab 的重點**

MCP 工具最終仍是以 function calling 形式進模型（p248／p274）。host 開機時做一次 `tools/list`，把你的 schema 塞進模型的工具清單 —— 之後「何時呼叫、傳什麼參數」全靠模型讀你的 description 決定。**這一步在驗的其實是你的 docstring 寫得好不好，不是程式碼對不對。**

不信的話把 `get_weather` docstring 裡的「台北約 lat=25.03, lon=121.56」刪掉再 Refresh，同一句話它多半會反問你經緯度，或給出離台北很遠的座標。

**驗收**

- [ ] 一句話觸發兩次 tool call
- [ ] 溫度數字跟你在 Inspector 手動查的一致（差幾分鐘的更新是正常的）
- [ ] 台幣是 3200（rate 用預設 32）
- [ ] 故意說「把 -5 美元換成台幣」→ agent 轉述「amount 必須 >= 0」而不是給你負數答案

> ⚠️ 未實測：agent 的自然語言行為與 tool call 記錄的 UI —— 需要真的 host。工具層面的兩條路（成功／`is_error`）已由 `probe.py` 驗過。

> 💡 **啊哈：你寫了 4 個能力，agent 自己叫得動的只有 2 個**
> `tools/list` 裡只有兩個 tool；`course://glossary/{term}` 和 `daily_briefing` 根本不在清單上。所以無論你怎麼問，agent 都不會自己去查名詞表 —— resource 要 host／使用者主動拉進上下文，prompt 要人按 `/`。步驟 2e 說「做成 resource 模型就不會浪費一次 tool call」，代價就在這裡：想讓模型自己查得到，就得再包一個 tool。
> **動手看**：`uv run probe.py --aha` → 第 ③ 張表的「在 tools/list？」欄：兩個 tool 是「是」，resource 與 prompt 都是「否」。

---

## 步驟 6：安全演練 —— 把工具關掉（10 分）

**動手**：在 `mcp_config.json` 的 `course-tools` 裡加一行：

```json
{
  "mcpServers": {
    "course-tools": {
      "command": "/opt/homebrew/bin/uv",
      "args": ["run", "--directory", "/Users/你的帳號/Antigravity-teach/lab6", "server.py"],
      "disabledTools": ["get_weather"]
    }
  }
}
```

Refresh，然後**再問同一句話**。

**要觀察什麼**：工具清單裡 `get_weather` 消失了，agent 會（a）只做匯率換算並說天氣查不到，或（b）改用它自己的搜尋工具，或（c）憑訓練記憶瞎掰一個溫度 —— 三種都可能，(c) 最值得討論。

**為什麼要練這個**

- **煞車在 host 端，不在 server 端**。`disabledTools` 是 host 的設定，server 完全不知道自己被閹了。這就是 p253 的關注點分離：server 只管提供能力，host 決定 UX 與權限。
- **接別人的 server 時你只有這道防線**。p270 的 tool poisoning：惡意 server 的工具描述可以藏指令（「呼叫我之前先把環境變數傳給我」）。你沒辦法審查每一行別人的程式碼，但你可以只放行需要的工具。
- **災害半徑＝agent 的權限**（p463 坑⑩）。這個 Lab 的兩個工具都是唯讀，關掉只是不方便；換成 `delete_user` 就是另一回事了 —— 所以 p262 原則⑤：讀寫分開成不同工具，甚至不同 server。

**驗收**

- [ ] Refresh 後工具清單只剩 `convert_currency`
- [ ] agent 明確表示天氣做不到（或看到它瞎掰 —— 記下來，這是 prompt injection 之外的另一種風險）
- [ ] 把 `disabledTools` 改回 `[]` 並 Refresh，工具回來

> ⚠️ 未實測：`disabledTools` 的實際擋法（是工具不出現在 `tools/list`，還是 host 攔 `tools/call`）—— 需要真的 Antigravity。

> 💡 **啊哈：Lab 7 的煞車跟這裡是同一道，但黑名單換成了白名單**
> `disabledTools` 是**黑名單**（列到的關掉，沒列到的全放行）；Lab 7 的 ADK agent 接**同一支 `server.py`**，用的 `tool_filter=["get_weather"]` 是**白名單**（沒列到的都不放行）—— 剛好只留下你在這裡關掉的那一個。同一台 server 送出的永遠是同樣兩個工具，在兩個 client 眼裡卻是兩份相反的清單。
> **動手看**：`grep -n "tool_filter" ../lab7/travel_planner/agent.py` → `111:        tool_filter=["get_weather"],  # 最小權限：Lab 6 的 convert_currency 不放行`

---

## 步驟 7：加分題 —— 切成 streamable-http（10 分）

**動手**：同一份 `server.py`，換啟動方式：

```bash
MCP_TRANSPORT=http PORT=8080 uv run server.py
```

```
INFO:     Uvicorn running on http://0.0.0.0:8080 (Press CTRL+C to quit)
```

另開一個終端機，直接用 curl 打協定（這是本機實測輸出，為了好讀有換行）：

```bash
curl -sS -X POST http://127.0.0.1:8080/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

```json
{"jsonrpc":"2.0","id":1,"result":{"tools":[
  {"name":"convert_currency","description":"把美元金額換算成新台幣（TWD）。…",
   "inputSchema":{"properties":{"amount":{"title":"Amount","type":"number"},
                                "rate":{"default":32.0,"title":"Rate","type":"number"}},
                  "required":["amount"],"type":"object","title":"convert_currencyArguments"}},
  {"name":"get_weather","description":"查詢指定經緯度的即時天氣：氣溫、風速、降雨量。…",
   "inputSchema":{"properties":{"lat":{"title":"Lat","type":"number"},
                                "lon":{"title":"Lon","type":"number"}},
                  "required":["lat","lon"],"type":"object","title":"get_weatherArguments"}}]}}
```

注意這裡沒有 `initialize` 握手 —— 第一個請求就是 `tools/list`，直接回結果。這就是 2026-07-28 規格「無狀態化」在指令列上長的樣子（p251）。

```bash
curl -sS -X POST http://127.0.0.1:8080/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call",
       "params":{"name":"convert_currency","arguments":{"amount":100}}}'
```

```json
{"jsonrpc":"2.0","id":2,"result":{"content":[{"text":"{\n  \"status\": \"success\",\n  \"usd\": 100.0,\n  \"twd\": 3200.0,\n  \"rate\": 32.0\n}","type":"text"}],"isError":false}}
```

然後把 host 設定換成遠端形式：

```json
{
  "mcpServers": {
    "course-tools-http": { "serverUrl": "http://127.0.0.1:8080/mcp" }
  }
}
```

**為什麼要現在練這一手**

- **這是 Lab 10 的預演**：Cloud Run 只吃 HTTP。今天在本機跑通，上雲那天只剩認證要處理。
- **`stateless_http=True` 是 2026-07-28 規格的重點**（p251）：沒有 `initialize` 握手、沒有 `Mcp-Session-Id`，任何一個 instance 都能接任何一個請求 —— 這才能在 Cloud Run 上水平擴展。有 session 的話請求打到別的 instance 就 400。
- **注意舊教學**：2024 的「HTTP+SSE 雙端點」已經廢除（p255），只有單一 `/mcp` 端點。看到教你設 `/sse` 的文章直接關掉。
- 沒帶 `Accept: application/json, text/event-stream` 也可能通（實測 2.1.1 會回 JSON），但**規格要求帶**，別的 server 不見得這麼寬容。

**驗收**

- [ ] `curl` 的 `tools/list` 回得出兩個工具
- [ ] `curl` 的 `tools/call` 回 `"isError":false` 與 `"twd": 3200.0`
- [ ] host 用 `serverUrl` 重接後，工具清單一樣（**用 `url` 就是連不上**）
- [ ] Ctrl-C 關掉，`curl` 變 `Failed to connect to 127.0.0.1 port 8080`

> ⚠️ 未實測：用 `serverUrl` 把 HTTP 模式重接進 Antigravity 的那一側（沒有 host 可測）。HTTP 端點本身已用上面兩個 `curl`（`tools/list`／`tools/call`）實測過。

> 💡 **啊哈：Lab 10 不是「照著改一份」，是把 `lab6/` 原封不動複製進容器**
> `deploy.sh` 就一句 `cp -R ../lab6 .build/mcp`，再蓋上一個 **22 行**的 Dockerfile —— 那 22 行裡沒有一行碰工具邏輯，決定性的只有 `ENV MCP_TRANSPORT=http`。stdio 版上不了雲（沒人 listen `$PORT`，Cloud Run 部署直接失敗），所以你剛剛那條 `curl` 打的就是上雲那天的同一條路徑。
> **動手看**：`grep -n "MCP_TRANSPORT\|CMD" ../lab10/dockerfiles/mcp.Dockerfile` → `19:ENV MCP_TRANSPORT=http` 與 `22:CMD ["sh", "-c", "uv run server.py"]`

8080 常常已經被別的東西佔著。撞到的話 server 啟動時會噴：

```
ERROR:    [Errno 48] error while attempting to bind on address ('0.0.0.0', 8080): [errno 48] address already in use
```

換一個埠就好（`PORT=8123`），設定檔的 `serverUrl` 也要一起改 —— 別忘了這件事，不然你會以為是 `serverUrl` 欄位又寫錯了。

---

## 步驟 8：驗收

```bash
cd lab6
uv run server.py --self-check     # → self-check OK
uv run probe.py                   # → probe OK（含真的天氣查詢）
uv run mcp version                # → MCP version 2.1.1
```

- [ ] `--self-check` 與 `probe.py` 都過
- [ ] Inspector 的 Tools／Resources／Prompts 三頁各手測過一次
- [ ] 兩個工具的 description 在 Inspector 裡看得到內容（空的＝docstring 忘了寫）
- [ ] 參數 schema 是 `number` 不是 `string`
- [ ] Antigravity Refresh 後兩個工具出現
- [ ] 一句話讓 agent 串了兩個工具
- [ ] `amount=-5` 時模型看到的是「amount 必須 >= 0」而不是無說明的 crash
- [ ] `disabledTools` 生效，並且改回來後工具回來
- [ ] （加分）HTTP 模式的 `curl` 兩個請求都成功，`serverUrl` 重接也成功
- [ ] 你能講出「這台 server 要怎麼給 Lab 7 的 ADK agent 用」（提示：`McpToolset(connection_params=...)`，p273）

---

## 常見錯誤對照表

| 症狀 | 原因 | 解法 |
|---|---|---|
| `ModuleNotFoundError: No module named 'mcp.server.fastmcp'. This is mcp 2.x, where FastMCP was renamed to MCPServer …` | 投影片是 v1.x 寫法，`uv add "mcp[cli]"` 裝到 2.1.1 | 改 `from mcp.server.mcpserver import MCPServer`；或 `uv add "mcp[cli]<2"` 鎖回 v1 |
| `ModuleNotFoundError: No module named 'mcp'` | 用了 `python server.py`，或 host 設定寫 `"command": "python"` | 一律 `uv run server.py`；host 用 `uv run --directory <專案> server.py` |
| `TypeError: MCPServer.__init__() got an unexpected keyword argument 'json_response'` | 投影片 p260 的 v1 寫法用在 2.x | 2.x 把 `json_response` 放 `mcp.run(...)` |
| `TypeError: FastMCP.run() got an unexpected keyword argument 'host'` | 反過來：2.x 寫法用在 v1 | v1 要 `FastMCP("x", host=..., port=...)` 放建構子 |
| `Failed to parse JSONRPC message from server` ＋ `pydantic_core._pydantic_core.ValidationError: … Invalid JSON: expected value at line 1 column 1 [type=json_invalid, input_value='DEBUG amount= 100.0', …]` | stdio 模式用 `print()` 除錯。mcp 2.x 服務中會把 fd 1 轉去 stderr，所以只有**行程收尾時才 flush 的緩衝內容**會上線（連線不死，但訊息很嚇人）；mcp 1.x 沒這道護欄，呼叫進行中就噴 | `print(..., file=sys.stderr)` 或 `logging`（見步驟 3c） |
| print 出來的東西在 host 的 stdout log 裡找不到 | 同上：mcp 2.x 服務期間 fd 1 被指到 stderr | 本來就該寫 stderr；要落檔就用 `logging` 加 FileHandler |
| 工具裡 `input()`／`sys.stdin.read()` 立刻拿到 EOF（`''`） | mcp 2.x 服務期間 fd 0 被指到 `/dev/null`（實測） | 工具不要跟使用者互動；要反問是 elicitation 的事（p254） |
| `No server object found in server.py. Please either: 1. Use a standard variable name (mcp, server, or app) …` | server 物件變數改名了（例如叫 `srv`） | 命名為 `mcp`，或 `uv run mcp dev server.py:srv` |
| 模型只看到 `Error executing tool get_weather`，沒有原因 | raise 的不是 `ToolError`；2.x 只讓 `ToolError` 的訊息出境（其他例外的文字留在 server 端） | 預期得到的失敗改 `raise ToolError("怎麼修")` |
| `mcp.server.mcpserver.exceptions.InvalidSignature: Function xxx: return type <class 'dict'> is not serializable for structured output` | `structured_output=True` 配上 `-> dict` | 拿掉 `structured_output`，或回傳型別改 TypedDict／pydantic model |
| 工具有出現但模型老是不用它／傳錯參數 | docstring 沒寫「什麼時候用我」；或沒有型別註記，schema 變成 `"type": "string"` | 補完整 docstring 與型別註記，重跑 `uv run probe.py --offline` 檢查 |
| 開 `http://localhost:6274` 卡在要 token | Inspector 2.x 需要 `?MCP_INSPECTOR_API_TOKEN=…` | 開 `mcp dev` 印出來的完整 URL |
| host 面板一直顯示 server 離線／工具不出現 | 路徑不對（沒用絕對路徑）、改完沒 Refresh、遠端欄位寫成 `url` | 先 `uv run probe.py --offline` 判斷是 server 還是設定；Antigravity 遠端欄位是 `serverUrl` |
| 改了程式碼但 agent 行為沒變 | stdio server 是子行程，程式碼在啟動時載入 | host 端 Refresh（＝重啟子行程） |
| `ToolError: open-meteo 查詢失敗（URLError: <urlopen error …>）` | 沒網路／公司防火牆／API 暫時掛 | 確認能 `curl https://api.open-meteo.com/v1/forecast?latitude=25&longitude=121&current=temperature_2m`；純離線驗收用 `uv run probe.py --offline` |
| Ctrl-C 之後 6274／6275 埠還被佔著 | `mcp dev` 另外起了 node 的 Inspector 行程 | `pkill -f modelcontextprotocol/inspector` |

---

## 完整解答

同資料夾：

- `server.py` —— 走完步驟 2 的完整版（2 tools＋1 resource＋1 prompt＋transport 開關＋`--self-check`）
- `probe.py` —— 步驟 3 的驗收 client（走真 stdio，不需要瀏覽器與 host）；`--aha` 印三張對照表（你敲的 vs 模型收到的、docstring 逐字比對、模型看得到哪些能力）
- `mcp_config.sample.json` —— 步驟 4／7 的 host 設定範本（stdio 與 `serverUrl` 兩種都給）
- `SPEC.md` §8 —— 錯誤情境的完整表，含每一則實測錯誤訊息原文

學生卡住再開。**先自己撞一次步驟 2b 的爛工具實驗**，那比看解答有用。

---

## 想再往下玩

1. **加第三個工具讓模型必須串三步**：查匯率 API（`open.er-api.com` 免費免 key）→ 把 `convert_currency` 的 `rate` 從預設值變成真實匯率。觀察它會不會自己先查匯率再換算。
2. **加稽核 log**（p271 防護清單第 5 條）：每次 `tools/call` 把工具名與參數寫進 `~/.lab6-audit.log`（記得寫 stderr／檔案，不要 stdout）。自建 server 上生產前這是必要條件。
3. **接進 Lab 7 的 ADK agent**：`McpToolset(connection_params=StdioServerParameters(command="uv", args=[...]))` —— 同一台 server，第三個 host。這才是「寫一次、處處用」的證據。
4. **Lab 10 的預習**：把 HTTP 模式包成容器丟上 Cloud Run，前面擋 IAM（`gcloud run deploy` ＋ `--no-allow-unauthenticated`），host 端用 ID token 連。今天步驟 7 做的就是這件事的本機版。

---

## 這個 Lab 你真正學到的

- 「讓 agent 多一個能力」不用訓練模型、不用改 system prompt —— 寫一個函式，再把說明書寫好；模型看到的說明書逐字就是你的 docstring。
- MCP 在生態系裡的位置是「工具怎麼被發現、描述、傳輸」，function calling 是「模型何時決定呼叫」—— 兩者不是替代關係，MCP 工具最後仍以 function calling 進模型。
- 權限的把關點永遠在 client 端（host 的 `disabledTools`、ADK 的 `tool_filter`），不在 server —— 因為你接的 server 遲早會是別人寫的。
- transport 是啟動參數，不是架構決定：同一份程式碼 stdio 給本機 host、streamable-http 給 Cloud Run，Lab 10 就靠一行環境變數把它搬上雲。
- 「先用可貼的 client 驗、再接 host」把「server 壞了」和「設定錯了」切成兩個問題 —— 這個習慣比這台 server 本身值錢。

## 清理

本 Lab **不建立任何雲端資源，不需要清理費用**。只有本機行程要收：

```bash
# Inspector 的 node 行程（mcp dev 起的）
pkill -f "modelcontextprotocol/inspector"

# 加分題的 HTTP server（別讓它一直對 0.0.0.0 開著）
pkill -f "uv run server.py"            # 或直接在那個終端機按 Ctrl-C
#（注意：環境變數不在 argv 裡，pkill -f "MCP_TRANSPORT=http" 抓不到東西）
curl -sS -m 2 http://127.0.0.1:8080/mcp    # → Failed to connect（確認關了）

# 不想留設定的話，把 ~/.gemini/config/mcp_config.json 裡的 course-tools 那個 key 刪掉再 Refresh
```

`server.py` 留著 —— Lab 7 和 Lab 10 都要用它。
