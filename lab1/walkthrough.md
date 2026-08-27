# Lab 1 走一遍：會查資料的 CLI 問答工具

> 30–45 分鐘 ｜ 綜合 Interactions API ＋ Search grounding ＋ 結構化輸出 ＋ streaming

做完你會有一支 `ask.py`，在終端機問它 2026 年的時事，它會**先上網搜、逐字吐答案、最後列出引用連結**：

```
$ uv run ask.py "2026 年最新的 Gemini 模型是？"
🔍 搜尋中…
根據 Google 官方文件，目前最新的是 Gemini 3.7 系列…

來源
- Gemini models | Google AI https://ai.google.dev/gemini-api/docs/models
```

> ⚠️ 未實測：上面這段是**版面示意**（照程式的輸出格式寫的），不是真跑出來的畫面 —— 寫這份教材時沒有 API key。全 Lab 唯一貼出真實輸出的地方是步驟 4 的 `--self-check`。

每一步都有「動手 → 為什麼 → 驗收」。驗收沒過不要往下走，後面會更難debug。

---

## 步驟 0：拿 API key（3 分）

**動手**：到 <https://aistudio.google.com/apikey> 建一把（免費、不用信用卡），然後：

```bash
export GEMINI_API_KEY="貼上你的 key"
```

**為什麼**：SDK 會自己讀 `GEMINI_API_KEY`，所以程式裡一個字的 key 都不用寫。硬編碼再 commit 上 GitHub 的話，幾小時內就會被掃 key 的機器人撈走，別人花你的配額。關掉終端機 export 就沒了 —— 想長期留著寫進 `~/.zshrc`，但**永遠不要**寫進程式碼。正式環境改用 Secret Manager（M5）。

**驗收**

```bash
echo $GEMINI_API_KEY      # 要印出 AIza... 開頭的字串，空白就是沒設成功
env | grep API_KEY        # 只該有一行。若 GOOGLE_API_KEY 也在，它會蓋掉上面那把
```

（SDK 讀 key 的順序是 `GOOGLE_API_KEY` 先、`GEMINI_API_KEY` 後 —— 兩個都設它會用前者並印一行 warning。以前的專案留了一把舊的 `GOOGLE_API_KEY` 在 `~/.zshrc`，就是「我明明 export 了新 key 卻還是 403」的標準原因。）

---

## 步驟 1：建立專案（3 分）

**動手**

```bash
uv init --bare lab1 && cd lab1
uv add google-genai
```

**為什麼**
- `--bare` 只生一個 `pyproject.toml`，不建 `src/` 目錄。我們只要一支腳本，不需要打包成套件（要發佈到 PyPI 才用 `--package`）。投影片第 56 頁寫的是 `uv init lab1 --package` —— 那會多生一個 `src/lab1/__init__.py`，然後你的 `ask.py` 該放哪就開始糾結。這裡刻意用 `--bare`。
- 依賴記在 `pyproject.toml` + `uv.lock`，之後**這個資料夾裡任何 `.py` 都直接 `uv run` 就有環境**，不用 venv、不用 `pip install`、不用 `activate`。

**驗收**

```bash
uv run python -c "from google import genai; print('ok')"     # → ok
```

> 踩到 `ModuleNotFoundError: No module named 'google'`？你用的是 `python ask.py`。這個 lab 一律用 `uv run ask.py`。
> 踩到 `uv sync` 說找不到 pyproject.toml？你不在 `lab1/` 裡面。

---

## 步驟 2：`ask.py` 收命令列問題（7 分）

**動手**：先做最小可跑版本 —— 還沒有搜尋、沒有串流，就是「問一句、答一句」。

```python
# ask.py
import sys
from google import genai

with genai.Client() as client:
    it = client.interactions.create(
        model="gemini-3.7-flash",
        system_instruction="以繁體中文回答，語氣精確。",
        input=" ".join(sys.argv[1:]),
    )
print(it.output_text)
```

**為什麼**
- `client.interactions.create()` 是新的統一入口：文字、圖片、影片、agent 都走它，只是換參數。
- `input=` 直接吃字串，這是最單純的形式（多模態才需要 content 物件，見 `../google-slide/test1.py`）。
- `with genai.Client()` 一定要綁變數或用 `with`。寫成 `genai.Client().interactions.create(...)` 的話 Client 是暫時物件，請求還沒送出就被 GC 關掉 → `RuntimeError: Cannot send a request, as the client has been closed.`

**驗收**

```bash
uv run ask.py "用一句話說明什麼是 serverless"
```

然後故意問一個它不可能知道的：

```bash
uv run ask.py "2026 年最新的 Gemini 模型是？"
```

它會講得很像真的但講錯（大概會說 Gemini 2.x 或 3 Pro）—— **這就是下一步要修的問題**。訓練資料有截止日，模型不會主動承認自己不知道，只會把最後看過的東西講得很有把握。這個「先看到它答錯」的動作不要跳過，下一步掛上工具之後你才有對照組。

> ⚠️ 未實測：這一步會真的呼叫 Gemini API，需要 API key 與網路。我沒有 key，無法替你確認實際輸出長什麼樣。

---

## 步驟 3：掛上 `google_search` 並串流輸出（12 分）

**動手**：兩個改動 —— `tools=` 讓它能上網，`stream=True` 讓字一個一個出來。

```python
stream = client.interactions.create(
    model="gemini-3.7-flash",
    system_instruction="以繁體中文回答，只根據搜尋到的資料回答，並附上來源。",
    input=question,
    tools=[{"type": "google_search"}],   # ← 新增
    stream=True,                          # ← 新增
)

for ev in stream:
    if ev.event_type == "step.delta" and ev.delta.type == "text":
        print(ev.delta.text, end="", flush=True)   # flush 很重要，不然會卡成一整塊
```

**為什麼**

- **為什麼要 `tools`**：不掛工具，模型只能從訓練資料裡撈 —— 就是步驟 2 那個答錯的版本。掛上 `google_search` 之後答案綁定即時搜尋結果，幻覺率直接掉下來，而且有來源可查。這是「模型 + 工具」這個組合最短的示範。
- **為什麼要串流**：搜尋 + 生成常常 10 秒以上。不串流的話使用者盯著空白畫面，會以為程式當掉然後 Ctrl-C；串流是體感差異最大、成本最低的一個改動。
- **為什麼 `flush=True`**：stdout 導到非終端機時是 block-buffered，少了 `flush` 你的「串流」會攢滿一個 buffer 才吐一次 —— 看起來跟不串流一模一樣，而且不會有任何錯誤訊息告訴你。

**事件只有這幾種**（背下來，寫錯名字不會報錯、只會安靜地什麼都不做）：

| `event_type` | 什麼時候來 | 身上有什麼 |
|---|---|---|
| `interaction.created` | 一開始 | `interaction` |
| `step.start` | 每個步驟開始 | `step`（`step.type` 可以是 `google_search_call` / `thought` / `model_output`…） |
| `step.delta` | 內容一塊一塊來 | `delta`：`type=="text"` → `delta.text`；`type=="text_annotation_delta"` → `delta.annotations` |
| `step.stop` | 每個步驟結束 | `index`、`usage`、`step_usage`。**沒有 `step`** |
| `interaction.status_update` | 狀態變化 | `interaction_id`、`status`。**沒有 `interaction`**（只有 id，不含內容） |
| `interaction.completed` | 全部結束 | `interaction`（含完整 `steps`、`usage`） |
| `error` | 出錯 | `error` |

（不用背，這張表是查 SDK 原始碼抄下來的。自己複查一遍 —— 在 `lab1/` 底下貼這行，會印出剛好七行，不多不少：）

```bash
grep -rhoE '^ *event_type: Literal\["[a-z_.]+"\]' "$(uv run python -c 'import google.genai,os;print(os.path.dirname(google.genai.__file__))')"/_gaos/types/interactions/ | sort -u
```

> ⚠️ 沒有 `step.complete` 這個事件。寫成 `step.complete` 那段 `if` 永遠不成立，來源就會永遠是空的 —— 而且不會有任何錯誤訊息。

想讓學生「看到」它在工作，加這行就有 🔍 提示：

```python
    if ev.event_type == "step.start" and ev.step.type == "google_search_call":
        print("🔍 搜尋中…", file=sys.stderr)   # 印到 stderr，不會污染答案本文
```

**驗收**：同一個問題再問一次 —— 跟步驟 2 那個錯答案並排看，這是這個 Lab 最重要的一個對照。

```bash
uv run ask.py "2026 年最新的 Gemini 模型是？"
```

三件事都要成立：先出現 `🔍 搜尋中…`（證明真的觸發了 `google_search_call`）、答案內容變成 2026 年的、字是一個一個出現而不是等 10 秒噴一整塊。

> ⚠️ 未實測：需要 API key 與網路才跑得起來，我沒有 key。事件名稱與欄位是查 SDK 型別定義確認的，但實際回應內容我沒看過。

> 💡 **啊哈：模型的思考、搜尋、講話，在 SSE 上是同一條流的不同 `step.type`**
> 你寫的 `for ev in stream:` 已經是 agent 迴圈的最小版 —— 沒有「先想、再搜、再答」三個階段，只有一條事件流和一串 `if`。你沒接的事件不會報錯，它們只是安靜地掉出 `elif` 鏈（`step.complete` 那個 bug 就是這樣長出來的）。Lab 7 的 ADK 幫你自動化的，就是這個迴圈。
> **動手看**：`uv run ask.py --aha` → 第 `[1]` 段把每個事件的 `event_type`、身上是什麼、你的 `render()` 有沒有接住並排印出；`interaction.created` 與兩個 `step.stop` 會標「掉出 elif 鏈」。

---

## 步驟 4：結尾列出引用來源（10 分）

**動手**：搜尋來的內容會帶 `url_citation` 標註。兩個地方可以撈，**都要撈**：

```python
sources = []

def collect(annotations):
    for a in annotations or []:
        if a.type == "url_citation":
            sources.append((a.title or a.url, a.url))

for ev in stream:
    ...
    elif ev.event_type == "step.delta" and ev.delta.type == "text_annotation_delta":
        collect(ev.delta.annotations)                       # 串流中途
    elif ev.event_type == "interaction.completed":
        for step in ev.interaction.steps or []:            # 收尾補齊
            for block in getattr(step, "content", None) or []:
                collect(getattr(block, "annotations", None))

for title, url in dict.fromkeys(sources):                   # 去重、保留順序
    print(f"- {title} {url}")
```

**為什麼這樣寫**
- **兩邊都撈是因為兩邊都不保證完整。** SDK 對 `interaction.completed` 帶的那顆 interaction 的原話是 “Partial interaction resource emitted by interaction lifecycle SSE events. Streaming lifecycle payloads may omit fields that are only available on full non-streaming Interaction responses.”（`interactionsseeventinteraction.py`）—— `steps` 的型別就是 `Optional[List[Step]]`，串流時可能整個沒有。反過來，串流中途的 annotation delta 也只是增量。所以：兩邊都收、最後去重，最省事也最不會漏。
- `dict.fromkeys` 是 stdlib 版的「去重但保順序」，比 `set()` 好（`set` 會把來源順序打亂）。
- `getattr(step, "content", None) or []` 兩層防護都要：`GoogleSearchCallStep` 這個型別**連 `content` 屬性都沒有**（它只有 `arguments` / `id` / `search_type` / `signature`），所以要 `getattr` 給預設；`ModelOutputStep` 有 `content` 但是 `Optional`，所以還要 `or []`。少了任一層就是 `AttributeError` 或 `TypeError: 'NoneType' object is not iterable`。
- `a.title` 在 SDK 裡是 `Optional[str]`，真的會是 `None`。沒有 `a.title or a.url` 的話你的來源清單會出現一行 `- None https://...`。

**驗收**

先跑離線的（不需要 key、不花錢、不連網）：

```bash
uv run ask.py --self-check
```

預期輸出（前兩行是 `render()` 真的處理了假事件的證據，`🔍` 那行走 stderr）：

```
🔍 搜尋中…
答案在此self-check ok
```

再跑真的：

```bash
uv run ask.py "2026 年最新的 Gemini 模型是？"
```

來源那幾行的連結**點得開**、而且內容真的跟答案有關。點不開 = 模型在編（很少，但要抓）。

> ⚠️ 未實測：上面那條真的呼叫 API 的指令我沒有跑過（沒有 key）。`--self-check` 是實測通過的。

> 💡 **啊哈：`tools=` 那一行買到的不是「答案更好」，是「答案第一次帶著證據」**
> 掛與不掛，答案字數可能差不多；差的是事件流本身 —— 多了 `google_search_call` 這個 step、多了 `text_annotation_delta`、來源從 0 變成 2。沒有 annotation 的答案，你沒有任何辦法分辨它是查到的還是編的。
> **動手看**：`uv run ask.py --aha` → 第 `[2]` 段（離線假事件流）：SSE 事件數 6 → 10、step 種類 1 → 3、`url_citation` 標註 0 → 2、列出的來源 0 → 2。

---

## 步驟 5：加分題 —— `--json` 模式（8 分）

**動手**：要把答案接進別的程式，就不能吐自由文字。用 `response_format` 鎖住結構：

```python
SCHEMA = {
    "type": "object",
    "properties": {
        "answer": {"type": "string"},
        "sources": {"type": "array", "items": {"type": "string"}},
        "confidence": {"type": "number", "description": "0~1"},
    },
    "required": ["answer", "sources", "confidence"],
}

it = client.interactions.create(
    model="gemini-3.7-flash",
    input=question,
    tools=[{"type": "google_search"}],
    response_mime_type="application/json",     # 有 response_format 就必填
    response_format={"type": "text", "mime_type": "application/json",
                     "schema": SCHEMA},
)
data = json.loads(it.output_text)              # 保證 parse 得動
```

**為什麼**
- `response_mime_type` 與 `response_format` 是一組，少了會被打回。投影片沒明講，但 SDK 的參數說明白紙黑字寫著 `response_mime_type: The mime type of the response. This is required if response_format is set.`（自己查：`grep -n "required if response_format" "$(uv run python -c 'import google.genai,os;print(os.path.dirname(google.genai.__file__))')"/_gaos/interactions.py`）。
- `required` 一定要寫。沒寫的欄位模型可能整個省略，你的 `data["sources"]` 就 `KeyError: 'sources'`。
- `description` 是給模型看的，`"0~1"` 這種提示會直接影響它填的值。
- JSON 模式先別串流：一段一段的 JSON 片段中途都不是合法 JSON，parse 不了。等會走了再研究增量解析。

**驗收**

```bash
uv run ask.py --json "2026 年 Gemini 3 系列有哪些型號？" | uv run python -m json.tool
```

`json.tool` 沒有抱怨就是合法 JSON。順手看一下 `confidence` 是不是落在 0~1 —— 那個 `description` 就是為了讓它填對範圍。

> ⚠️ 未實測：需要 API key。`json.tool` 這段 pipe 之所以不會被 ANSI 色碼弄壞，是因為 `ask.py` 用 `sys.stdout.isatty()` 在非終端機時把色碼關掉。

> 💡 **啊哈：schema 保證 JSON 合法，不保證欄位裡的東西是真的**
> `--json` 的 `sources` 是模型「照著 schema 填」的字串，跟步驟 4 那份 `url_citation` annotation 走的是完全不同的來路 —— 前者模型可以編，後者不行。`confidence` 更只是模型自己寫的一個數字，schema 只保證它是 number，沒有任何機制讓它跟真實正確率對齊，拿它當閾值做自動決策是最容易踩的坑。
> **動手看**：`grep -n '"sources"\|a.url' ask.py` → 第 18 行是 schema 叫模型自己填的字串陣列，第 40 行是從 `url_citation` annotation 撈出來的 `a.url`。同一個欄位名，兩種可信度。

---

## 步驟 6：驗收（5 分）

問三個 2026 年的時事問題，三個都要過：

```bash
uv run ask.py "2026 年 Google I/O 發表了什麼 AI 產品？"
uv run ask.py "現在 Gemini API 的免費額度是多少？"
uv run ask.py "Nano Banana 2 是什麼？"
```

檢查清單：

- [ ] 答案內容正確（不是 2024 年的舊資訊）
- [ ] 有印出 🔍，代表它真的去搜了
- [ ] 每題都列出至少一個來源，連結點得開
- [ ] `--json` 模式吐得出合法 JSON，`confidence` 在 0~1 之間
- [ ] `uv run ask.py --self-check` 通過（唯一一條不用 key、不花錢的）
- [ ] 你能說出「把 `tools=` 那行註解掉會發生什麼事」，而且真的試過

> ⚠️ 未實測：這三題都要 API key 才跑得起來，我沒有 key。全 Lab 我實際跑過的只有 `uv run ask.py --self-check`。

> 💡 **啊哈：`tools=` 收的是一個只有九種變體的 union —— `google_search`、你自己的函式、MCP server 是同一個位置的兄弟**
> SDK 的 `ToolParam` 裡，`GoogleSearchParam`（你現在用的）、`FunctionParam`（投影片 38 頁那個 `schedule_meeting` dict）、`MCPServerParam`（`{"type": "mcp_server", "url": ...}`）並排躺在同一個 union。所以 Lab 6 你寫的 `lab6/server.py:52` 的 `convert_currency` 是塞回**同一個 `tools=` list**；`lab7/travel_planner/agent.py:60` 的 `search_hotels` 換成 ADK tool（ADK 的 `tools=` 是它自己的參數，不是這個 union）；`lab9/hotel_service/agent.py:32` 那個同名函式再被包成 A2A agent card 上的 skill。一個「工具」概念，三個 lab 換三種包裝。
> **動手看**：`grep -A11 "^ToolParam" "$(uv run python -c 'import google.genai,os;print(os.path.dirname(google.genai.__file__))')"/_gaos/types/interactions/tool.py` → 九行 `*Param`，`MCPServerParam` 就在 `GoogleSearchParam` 下面五行。

---

## 常見錯誤對照表

| 症狀 | 原因 | 解法 |
|---|---|---|
| `ModuleNotFoundError: No module named 'google'` | 用了 `python ask.py` | 改用 `uv run ask.py` |
| `uv sync` 說找不到 pyproject.toml | 不在專案資料夾裡 | `cd lab1` |
| `ValueError: No API key was provided. Please pass a valid API key.` | 沒 export（`genai.Client()` 當下就炸，還沒連網） | `export GEMINI_API_KEY=...` 再重跑 |
| 明明 export 了新 key 還是 401／403 | `GOOGLE_API_KEY` 也有值，而它的優先度高於 `GEMINI_API_KEY` | `env \| grep API_KEY` 找出多的那把，`unset GOOGLE_API_KEY` |
| `RuntimeError: ... client has been closed` | `genai.Client()` 沒綁變數，被 GC 關掉 | 用 `with genai.Client() as client:` |
| 來源永遠是空的 | 寫成 `step.complete`（不存在的事件） | 改 `step.delta` 的 `text_annotation_delta` ＋ `interaction.completed` |
| `AttributeError: 'StepStop' object has no attribute 'step'` | `step.stop` 身上沒有 `step` | 要看步驟內容請用 `step.start` 或 `interaction.completed` |
| 答案卡成一整塊才出來 | `print` 沒 `flush=True` | 加上 `flush=True` |
| 傳圖片時模型說看不到圖 | `input` 放 dict 會被 SDK 當 UNKNOWN 靜默丟掉 | 用 `TextContent` / `ImageContent` 物件，見 `../google-slide/test1.py` |
| `TypeError: a bytes-like object is required` | 回傳的圖片 `data` 是 base64 字串 | `base64.b64decode(data)` 再寫檔 |

---

## 完整解答

`ask.py`（同資料夾）就是走完六步的版本，含 `--json`、`--self-check` 與 `--aha`（離線對照表，不用 key）。學生卡住時再開。

想看設計理由與完整的事件／欄位契約：同資料夾的 `SPEC.md`（架構圖、七種 SSE 事件、錯誤處理表、已知限制）與 `PRD.md`（學習目標、需求對照投影片步驟、費用）。

## 想再往下玩

- `stream=True` ＋ `--json`：研究怎麼邊收邊 parse（提示：先累積字串，最後才 `json.loads`）
- 換成 `agent="deep-research-preview-04-2026"` ＋ `background=True`：同一個問題差多少？`../google-slide/test5.py` 有並排比較的現成腳本
- 把 `tools` 加上 `url_context`，讓它能讀你指定的網頁
- **接下去是 Lab 2**：同一把 key 換到 AI Studio 的 Build mode，不寫後端做出一個 App 並部署到 Cloud Run

---

## 這個 Lab 你真正學到的

- 我學會「工具」在 Google 生態系裡的位置：`tools=` 是一個九選一的 union，`google_search` 只是其中最省事的那個；Lab 6 的 MCP server 是這個 union 裡的另一個選項，Lab 7 的 ADK tool 與 Lab 9 的 A2A skill 是同一個概念換掉包裝。
- 我學會 grounding 換到的不是「比較聰明的答案」，而是 `url_citation` 這種可以點開查證的證據 —— 沒有來源的正確答案，跟幻覺在程式裡長得一模一樣。
- 我學會串流不是 UI 糖：SSE 事件流就是模型的行為紀錄，`step.start` / `step.delta` / `interaction.completed` 讓「模型做了什麼」變成可以 debug 的東西。
- 我學會結構化輸出管的是形狀不是真假 —— schema 讓下游 parse 得動，不讓內容變成事實。
- 我學會這 30 行的 `for ev in stream:` 就是 agent 迴圈的原型，之後 ADK 做的是把這個迴圈自動化，不是換一套新東西。

---

## 清理

這個 Lab **沒有任何雲端資源要刪** —— 沒建 GCP 專案、沒開服務、沒上傳檔案。全程在免費層內，費用約 $0（`gemini-3.7-flash` 輸入 $0.75/1M tokens、Search Grounding 每月前 5,000 次查詢免費，你這輪大概用掉 10 次以內）。

要收乾淨只有三件事：

```bash
unset GEMINI_API_KEY        # 清掉這個 shell 的 key
# 這把 key 不會再用 → 到 https://aistudio.google.com/apikey 按 Delete
rm -rf .venv                # 只是本機環境，下次 uv run 會自動重建
```

`~/.zshrc` 裡如果寫了 `export GEMINI_API_KEY=...`，記得也一起刪 —— 不然 M2 之後你會忘記自己有一把在跑。
