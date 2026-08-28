# Lab 1 SPEC：會查資料的 CLI 問答工具

> 型號名以課程投影片為準（`gemini-3.7-flash`）；若 404 請用 `client.models.list()` 確認。
> 事件與欄位名稱是**實際查 google-genai 2.20.0 原始碼**得到的（路徑見 §9），不是憑印象寫。

## 1. 架構

```
  終端機                        本機 process（uv run ask.py）                    Google
┌──────────┐   argv    ┌───────────────────────────────────────────┐
│ 使用者    │──────────▶│ __main__                                  │
│          │           │  ├─ "--self-check" ─▶ self_check()  ← 不出網、不用 key
│          │           │  ├─ "--json"       ─▶ ask_json()
│          │           │  └─ 其他            ─▶ ask()
│          │           │                                           │
│          │           │  ask(question)                            │
│          │           │   with genai.Client() as client:  ◀── GEMINI_API_KEY（env）
│          │           │     interactions.create(               ──────── HTTPS ────▶ ┌──────────────┐
│          │           │       model=MODEL,                     POST /v1beta/        │ Gemini API    │
│          │           │       tools=[{"type":"google_search"}], interactions         │ 3.7 Flash     │
│          │           │       stream=True)                                          │  ├ thought    │
│          │           │                                        ◀─── SSE 事件流 ───── │  ├ google_    │
│          │           │     render(events) ─┐                                       │  │ search_call│
│  stdout  │◀──────────│       逐字 print ────┘                                       │  └ model_    │
│  (答案)   │  flush=T  │       收 url_citation → sources                              │    output    │
│  stderr  │◀──────────│                                                             └───────┬──────┘
│ (🔍提示) │           │   print 來源清單（去重、保序）                                      │
└──────────┘           └───────────────────────────────────────────┘                        │
                                                                                    google.com 搜尋
```

程序邊界只有兩個：**本機 process** 與 **Gemini API**。沒有本地 server、沒有 DB、沒有雲端資源。搜尋是模型端做的（`google_search` 是內建工具），我們的程式從來不自己發 HTTP 去搜。

`--self-check` 完全不跨越右邊那條邊界 —— 它把假事件直接餵進 `render()`。

## 2. 元件與職責

| 元件 | 位置 | 職責 | 不負責 |
|---|---|---|---|
| `__main__` | `ask.py` 底部 | 解析 argv、分派三種模式、沒問題時印 docstring 當 usage | 不做 argparse（三個 flag 用不到） |
| `ask(question)` | `ask.py` | 開 client、發串流請求、印答案本文與來源清單 | 不解析事件（委給 `render`） |
| `render(events)` | `ask.py` | **唯一的非 trivial 邏輯**：吃 SSE 事件流 → 逐字輸出 + 收集去重來源 | 不碰網路、不建 client（所以可離線測） |
| `ask_json(question)` | `ask.py` | 非串流、掛 `response_format`、`json.loads` 後 pretty print | 不做 schema 驗證（Schema 由伺服器端強制） |
| `self_check()` | `ask.py` | 用 `SimpleNamespace` 假事件對 `render()` 下 assert | 不驗 `ask` / `ask_json`（那兩支只是黏膠，動了必然打 API 才看得出來） |
| 常數 `MODEL` / `SYSTEM` / `SCHEMA` | `ask.py` 頂部 | model ID 與 system instruction 集中一處（模型退役時只改一行） | — |

## 3. 介面契約

### 3.1 CLI

```
uv run ask.py <question...>          # 串流 + grounding + 來源清單，答案走 stdout、🔍 提示走 stderr
uv run ask.py --json <question...>   # 一次吐 {answer, sources[], confidence} 的 pretty JSON
uv run ask.py --self-check           # 離線自我檢查，成功印 "self-check ok"，exit 0
uv run ask.py                        # 沒給問題 → 印 docstring、exit 非 0
```

`question` 由所有非 `--` 開頭的 argv 以空白 join 而成，所以 `uv run ask.py 台北 天氣` 和 `uv run ask.py "台北 天氣"` 等價。

### 3.2 函式簽章

```python
render(events: Iterable[SSEEvent]) -> list[tuple[str, str]]   # [(title, url), ...] 去重且保序
ask(question: str) -> None
ask_json(question: str) -> dict                                # 同時 print，回傳給呼叫者接
self_check() -> None                                           # assert 失敗就 AssertionError
```

`render()` 對事件物件的要求只有「有那幾個屬性」（duck typing），因此 `SimpleNamespace` 就能當測試替身。

### 3.3 請求參數（`client.interactions.create`）

| 參數 | 值 | 為什麼 |
|---|---|---|
| `model` | `"gemini-3.7-flash"` | 投影片第 19 頁的現役旗艦 |
| `system_instruction` | 繁中、只依搜尋結果、附來源 | **伺服器端狀態不含它，每次呼叫都要重帶**（投影片第 31 頁） |
| `input` | `str`（單純文字） | 多模態才需要 `TextContent` / `ImageContent` 物件 |
| `tools` | `[{"type": "google_search"}]` | dict 形式的 tools 會被 SDK 正確解析（已驗證） |
| `stream` | `True`（`--json` 模式為預設 False） | JSON 片段中途不是合法 JSON，串流會讓 `json.loads` 炸 |
| `response_format` | `{"type":"text","mime_type":"application/json","schema": SCHEMA}` | 僅 `--json` 模式 |
| `response_mime_type` | `"application/json"` | **有 `response_format` 就必填**（SDK 參數說明原文：`This is required if response_format is set.`） |

### 3.4 SSE 事件型別（google-genai 2.20.0 實際定義）

| `event_type` | 身上的欄位 | 這支程式怎麼用 |
|---|---|---|
| `interaction.created` | `interaction` | 不用 |
| `step.start` | `index`, `step`（`Step`，有 `.type`） | `step.type == "google_search_call"` → stderr 印 `🔍 搜尋中…` |
| `step.delta` | `index`, `delta` | `delta.type == "text"` → `delta.text` 逐字印；`delta.type == "text_annotation_delta"` → `delta.annotations` |
| `step.stop` | `index`, `usage`, `step_usage`。**沒有 `step`** | 不用。碰 `ev.step` 會 `AttributeError` |
| `interaction.status_update` | `interaction_id`, `status`。**沒有 `interaction`** | 不用 |
| `interaction.completed` | `interaction`：型別是 `InteractionSseEventInteraction`，**partial resource**，`steps` / `usage` 都是 `Optional` | 走一遍 `steps[].content[].annotations` 補齊來源，所以 `or []` 不能省 |
| `error` | `error` | 印到 stderr |

> 投影片第 57 頁寫的 `step.complete` **不存在**。SDK 的 `event_type` 是 `Literal[...]` 且只有上表七種，`ev.event_type == "step.complete"` 永遠是 `False` —— 不會報錯，來源永遠空的。這是本 Lab 刻意保留的教學亮點。

### 3.5 annotation 契約

`URLCitation`（`urlcitation.py`，注意類名是全大寫 `URL`）：`type: Literal["url_citation"]`、`url: Optional[str]`、`title: Optional[str]`、`start_index` / `end_index: Optional[int]`。
`Annotation` 是 open union：`URLCitation` / `PlaceCitation` / `WordInfo` / `FileCitation` / `UnknownAnnotation`，所以一定要先看 `a.type == "url_citation"` 再取欄位。

`title` 與 `url` 都是 Optional，所以程式寫 `a.title or a.url` 當顯示名稱。`getattr(step, "content", None) or []` 的兩層防護也都必要：`GoogleSearchCallStep` **連 `content` 屬性都沒有**（只有 `arguments` / `id` / `search_type` / `signature`），`ModelOutputStep` 有 `content` 但是 `Optional[List[Content]]`。

### 3.6 `--json` 的輸出契約

```json
{
  "answer":     "string",
  "sources":    ["string", "..."],
  "confidence": 0.0
}
```

三個欄位都在 `SCHEMA["required"]` 裡。沒寫進 `required` 的欄位模型可以整個省略，下游 `data["sources"]` 就 `KeyError`。

## 4. 資料模型

無。沒有 DB、沒有本地 state 檔、沒有快取。伺服器端雖然預設 `store=True`（免費層保存 1 天），但這個 Lab 不使用 `previous_interaction_id`，所以那份狀態我們從不讀回。

## 5. 檔案結構

```
lab1/
├── PRD.md            產品需求：學習目標、FR 對照投影片步驟、驗收清單、費用
├── SPEC.md           本檔：架構、事件契約、錯誤處理、驗證方式
├── walkthrough.md    ★ 主教材：六步「動手→為什麼→驗收」＋常見錯誤表
├── ask.py            ★ 完整解答：render / ask / ask_json / self_check
├── pyproject.toml    uv 專案定義（name=lab1, requires-python>=3.13, google-genai>=2.20.0）
├── uv.lock           鎖定版本，讓教室裡每台機器裝到同一版
└── .venv/            uv 自動建的環境，不要手動碰、不要 commit
```

`ask.py` 是**單檔**且目錄裡已有 `pyproject.toml`，所以檔頂**不寫** PEP 723 檔頭（會與 pyproject 重複）。

## 6. 環境變數與設定

| 變數 | 用途 | 從哪來 | 預設 |
|---|---|---|---|
| `GEMINI_API_KEY` | SDK 自動讀取的 API key | <https://aistudio.google.com/apikey> → `export GEMINI_API_KEY="AIza..."` | 無。沒設會在 `genai.Client()` 就丟錯 |
| `GOOGLE_API_KEY` | 替代名，SDK 也認 —— 而且**優先於** `GEMINI_API_KEY`（`_api_client.py` 的 `return env_google_api_key or env_gemini_api_key or None`，兩個都設時會 log warning `Both GOOGLE_API_KEY and GEMINI_API_KEY are set. Using GOOGLE_API_KEY.`） | 同上 | 無 |
| （程式常數）`MODEL` | model ID | `ask.py` 頂部 | `"gemini-3.7-flash"` |
| （程式常數）`SYSTEM` | system instruction | `ask.py` 頂部 | 繁中 / 依搜尋結果 / 附來源 |

ANSI 色碼不是設定，是偵測：`sys.stdout.isatty()` 為 False 時 `DIM/CYAN/RESET` 全變空字串，所以 `uv run ask.py --json ... | python -m json.tool` 不會吃到色碼。

## 7. 執行流程

```bash
# 1) 拿 key
export GEMINI_API_KEY="AIza..."
echo $GEMINI_API_KEY                 # 有印出東西才往下

# 2) 建專案（本目錄已建好，從零開始才需要）
uv init --bare lab1 && cd lab1
uv add google-genai

# 3) 環境確認
uv run python -c "from google import genai; print('ok')"      # → ok

# 4) 離線邏輯確認（不花錢）
uv run ask.py --self-check                                    # → self-check ok

# 5) 先看失敗：拿掉 tools 的版本會答錯 2026 年的問題（walkthrough 步驟 2）
# 6) 再看修好：掛 google_search + stream
uv run ask.py "2026 年最新的 Gemini 模型是？"

# 7) 加分題
uv run ask.py --json "2026 年 Gemini 3 系列有哪些型號？" | uv run python -m json.tool

# 8) 驗收：三個時事問題（見 PRD §6）
```

## 8. 錯誤處理與邊界

| 情境 | 症狀 | 處理方式 |
|---|---|---|
| 用 `python ask.py` 而非 `uv run` | `ModuleNotFoundError: No module named 'google'` | 不處理，靠文件教。`uv run` 才有專案環境 |
| 沒 export key | `genai.Client()` 當場拋 `ValueError: No API key was provided. Please pass a valid API key.`（已實測，還沒送出任何請求） | 不 try/except。錯誤訊息本身就是最好的指示 |
| 兩個 key 環境變數都有值 | 新 export 的 `GEMINI_API_KEY` 沒生效，用到舊的 `GOOGLE_API_KEY` → 401／403 或用錯專案配額 | `GOOGLE_API_KEY` 優先。`env \| grep API_KEY` 檢查，多的那個 `unset` 掉 |
| `genai.Client()` 沒綁變數 | `RuntimeError: Cannot send a request, as the client has been closed.` | 程式用 `with genai.Client() as client:` 避免 |
| 事件名寫錯（`step.complete`） | 無錯誤訊息，來源永遠空的 | `render()` 只比對它真正需要的四個名稱（`step.start` / `step.delta` / `interaction.completed` / `error`），其餘三種合法事件直接掉出 `elif` 鏈；`--self-check` 的 assert 會抓到來源沒收到 |
| `step.stop` 上取 `.step` | `AttributeError: 'StepStop' object has no attribute 'step'` | `render()` 對 `step.stop` 不做任何事；self-check 的假事件刻意不給 `.step` 來把關 |
| `google_search_call` step 的 `content` 是 `None` | `TypeError: 'NoneType' object is not iterable` | `getattr(step, "content", None) or []`；self-check 的假事件裡刻意放一個 `content=None` |
| annotation 的 `title` 是 `None` | 來源那行印出 `None` | `a.title or a.url` |
| 模型一個來源都沒引 | 來源區塊空白，學生以為程式壞了 | fallback 印 `（模型沒有引用任何來源）` |
| 模型退役 / 打錯型號 | HTTP 404 `models/gemini-x.y-flash is not found` | 改 `MODEL` 常數，或用別名 `gemini-flash-latest`；`client.models.list()` 查現役 |
| 免費層配額用完 | HTTP 429 `RESOURCE_EXHAUSTED` | 不寫 backoff（範圍外）。等 5 小時刷新或綁帳單升 Tier 1 |
| 串流輸出卡成一整塊 | 答案等 10 秒才一次出現 | `print(..., end="", flush=True)`。少了 `flush` stdout 會 block-buffer |
| 色碼污染 pipe | `json.tool` 收到 `\033[36m` 而 parse 失敗 | `sys.stdout.isatty()` 為假就關色碼；🔍 提示一律走 stderr |

**刻意不做的錯誤處理**：沒有全域 try/except、沒有 retry、沒有 timeout 設定。這是教學骨架，SDK 原始的 traceback 比包裝過的訊息更有教學價值。

## 9. 驗證方式

### 離線（不需要 key、不花錢，我實際跑過）

```bash
cd $COURSE/lab1
uv run ask.py --self-check
```

實際輸出：

```
🔍 搜尋中…
答案在此self-check ok
```

（前兩行是 `render()` 在假事件上真的做了事的證據 —— `🔍 搜尋中…` 走 stderr、`答案在此` 是兩個 text delta 逐字拼出來的。）

`self_check()` 用 `SimpleNamespace` 蓋掉六個容易寫錯的點：兩次收到同一個 `url_citation` 要去重、`step.stop` 沒有 `.step` 不能碰、`interaction.status_update` 沒有 `.interaction` 不能碰、step 上完全沒有 `content` 屬性（`google_search_call`）不能炸、`content=None` 不能炸、`interaction.steps` 是 `None`（partial resource）與空事件流都回 `[]`。

### 型別與事件名稱的來源

事件與欄位不是憑印象寫的，可自己複查：

```bash
cd $COURSE/lab1
grep -rhoE '^ *event_type: Literal\["[a-z_.]+"\]' "$(uv run python -c 'import google.genai,os;print(os.path.dirname(google.genai.__file__))')"/_gaos/types/interactions/ | sort -u
```

實際輸出（剛好七行，這就是「只有七種 event_type」的證據）：

```
    event_type: Literal["error"]
    event_type: Literal["interaction.completed"]
    event_type: Literal["interaction.created"]
    event_type: Literal["interaction.status_update"]
    event_type: Literal["step.delta"]
    event_type: Literal["step.start"]
    event_type: Literal["step.stop"]
```

欄位則直接讀對應的型別檔：`stepstart.py`（有 `step`）、`stepstop.py`（沒有 `step`）、`interactionstatusupdate.py`（只有 `interaction_id` / `status`）、`interactionsseeventinteraction.py`（`steps` 是 Optional）、`urlcitation.py`（`title` / `url` 都是 Optional）。

### 線上（需要 API key）

> ⚠️ 未實測：以下驗收會真的呼叫 Gemini API，需要 `GEMINI_API_KEY` 與網路。我沒有 key，因此沒有執行過，只能保證程式的事件處理邏輯（`render()`）通過離線 assert、以及參數名稱與 SDK 型別定義一致。

- `uv run ask.py "<2026 年的時事問題>"` → 出現 `🔍 搜尋中…`、答案逐字出現、結尾有可點開的來源
- `uv run ask.py --json "..." | uv run python -m json.tool` → 合法 JSON，三個 key 齊全，`confidence` 在 0~1
- 對照組：把 `tools=` 那行註解掉再問同一題 → 答案應該變錯（grounding 的價值證明）

## 10. 已知限制與升級路徑

（`ask.py` 裡對應的 `# ponytail:` 註解標在前兩條上 —— 那兩條是刻意偷懶且有明確天花板的。）

| 限制 | 目前做法 | 什麼時候該升級 |
|---|---|---|
| 來源去重只看 `(title, url)` 完全相同 | `dict.fromkeys(sources)` | 同一頁不同 title（例如帶錨點的 URL）會重複出現時，改用 `url` 正規化後當 key |
| 沒有 retry / backoff | 撞 429 就直接 traceback | 這支工具進 CI 或跑批次時，加 `time.sleep` 指數退避；或改走 Batch API（-50%） |
| `--json` 不串流 | 整段等完再 `json.loads` | 要 UI 邊收邊顯示時，累積字串 + 增量 JSON parser |
| 一次一問，沒有對話 | 每次都是新 interaction | 要多輪就存 `interaction.id` 傳 `previous_interaction_id`（投影片第 33 頁）；注意 `store=False` 時不能用 |
| `self_check` 只蓋 `render()` | `ask` / `ask_json` 沒有測試 | 那兩支是黏膠函式，改動必然要打 API 才驗得出來；要離線測就得注入 fake client，不值得 |
| model ID 是程式常數不是環境變數 | 改 `MODEL` 一行 | 要同時比較多個模型（或投影片第 20 頁的「永遠讓 model ID 可設定」上到正式環境）時，改讀 `os.environ.get("MODEL", ...)` |
| 沒有 token / 費用統計 | 不印 usage | 想看花多少：`interaction.completed` 事件的 `ev.interaction.usage.total_tokens` |
