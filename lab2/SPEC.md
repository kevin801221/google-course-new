# Lab 2 SPEC：Build 一個 App 並部署上 Cloud Run

> 這份 SPEC 同時描述兩個東西：**(A) Build mode 生成的 app**（黑盒，只描述邊界與出口）與 **(B) 對照組最小實作**（本目錄的 `app.py`，白盒，逐欄位講清楚）。
> 兩者做同一件事，但 (A) 是 React SPA、(B) 是單檔 FastAPI。學生要看得懂差異在哪，而不是以為只有一種寫法。

## 1. 架構

### (A) Build mode 路徑（投影片 p76 步驟 1–6）

```
       瀏覽器（你）
            │  自然語言需求
            ▼
┌───────────────────────────────────────────────┐
│  aistudio.google.com/build                    │
│  ┌───────────────┐   ┌──────────────────────┐ │
│  │ Chat / 迭代   │──▶│ 生成的專案檔案樹     │ │
│  │ + Annotation  │   │ App.tsx / index.tsx  │ │
│  └───────────────┘   │ services/gemini*.ts  │ │
│          ▲            └──────────┬───────────┘ │
│          │  即時預覽 (iframe)    │             │
│          └───────────────────────┤             │
│  Secrets：API key 平台代管       │             │
└──────────────────────────────────┼─────────────┘
                                   │ 四個出口（p71）
       ┌───────────────┬───────────┼───────────────┬──────────────┐
       ▼               ▼           ▼               ▼              │
  Deploy to      Export to     Push to        Download ZIP        │
  Cloud Run      Antigravity   GitHub                             │
       │               │                                          │
       ▼               ▼                                          │
 https://<svc>    M3 Lab 的                                       │
 .run.app         起始輸入                                        │
       │
       └──▶ 執行時：瀏覽器 → Cloud Run 容器 → Gemini API（用你的 key 配額）
```

### (B) 對照組 `app.py`

```
  瀏覽器                        單一 Python 程序                    Google
 ┌────────┐  GET /            ┌────────────────────────┐
 │  一頁  │◀──── PAGE 字串 ───│ FastAPI (uvicorn)      │
 │  HTML  │                   │                        │
 │ + 30行 │  POST             │  check_url()  ← 400    │
 │   JS   │─ /api/summarize ─▶│      │                 │
 │        │  {url, length}    │      ▼                 │
 │        │                   │  summarize()           │
 │        │                   │   genai.Client()  ─────┼──▶ interactions.create
 │        │                   │      │                 │      model=gemini-3.7-flash
 │        │                   │      ▼                 │      tools=[url_context]
 │        │◀── JSON ──────────│  parse_result()        │◀─── Interaction
 │ render │  {title,bullets,  │   ↑ 檢查抓取 status    │      (steps + output_text)
 └────────┘   terms,quotes,   └────────────────────────┘
              sources,warning}
              GET /healthz ──▶ {"ok":true,"has_key":bool}   ← 不打 Gemini，排錯用
```

程序邊界：只有一個 Python 程序（`uvicorn`）。沒有資料庫、沒有 session、沒有背景任務——每個請求都是獨立的一次 `interactions.create`。這是刻意的：Cloud Run scale-to-zero，任何本機狀態都活不過一次縮容。

## 2. 元件與職責

| 元件 | 檔案／位置 | 職責 | 不負責什麼 |
|---|---|---|---|
| Build mode 生成的 React app | AI Studio 雲端 | 步驟 1–5 的主體；UI、Gemini 呼叫、部署全包 | 工程品質（錯誤處理、重試、測試）——那是 M3 Antigravity 的事 |
| `app.py` / `PAGE` | 對照組 | 一頁 HTML：表單、深色模式切換、結果渲染 | 沒有前端框架、沒有 build step；改樣式就是改那段 `<style>` |
| `app.py` / `check_url()` | 對照組 | trust boundary：只放行 http/https 絕對網址 | 不檢查網址活不活、不做 SSRF 白名單（url_context 是 Google 端抓的，不會打到你的內網） |
| `app.py` / `summarize()` | 對照組 | 組 prompt、掛 `url_context`、要結構化 JSON | 不重試、不快取 |
| `app.py` / `parse_result()` | 對照組 | 解 `output_text`、補預設值、**從 steps 撈抓取狀態** | 不驗證欄位型別（schema 已經約束了） |
| `app.py` / `/healthz` | 對照組 | 分離「容器沒起來」與「key 沒帶上去」兩種故障 | 不檢查 Gemini 通不通（那要花錢） |
| `Dockerfile` | 對照組 | 用 uv 建映像；讓 `--source .` 走 Docker 而不是 buildpacks | 不做 multi-stage 瘦身 |
| `deploy.sh` | 對照組 | 開 API → deploy → 印網址 → 打 `/healthz` | 不建專案、不綁帳單（M5） |

## 3. 介面契約

### HTTP 端點（對照組）

| Method | Path | Request | Response |
|---|---|---|---|
| GET | `/` | — | `text/html`，整頁（`PAGE` 常數） |
| GET | `/healthz` | — | `{"ok": true, "has_key": bool}` |
| POST | `/api/summarize` | `{"url": str, "length": "short"\|"medium"\|"long"}` | 見下 |

`POST /api/summarize` 成功回應：

```json
{
  "title":   "文章標題（繁中）",
  "bullets": ["重點 1", "重點 2"],
  "terms":   [{"term": "url_context", "explain": "..."}],
  "quotes":  ["原文句子（不翻譯）"],
  "sources": ["https://實際抓成功的網址"],
  "warning": null
}
```

錯誤回應（FastAPI 標準格式，都是 `{"detail": ...}`）：

| HTTP | `detail` | 觸發條件 |
|---|---|---|
| 400 | `請貼 http:// 或 https:// 開頭的完整網址` | `check_url()` 擋掉 |
| 422 | pydantic 的欄位錯誤陣列 | body 少了 `url` 或型別不對 |
| 500 | `ValueError: No API key was provided. ...` | 沒設 `GEMINI_API_KEY` |
| 500 | `<ExceptionType>: <原文>` | 其他 SDK／網路錯誤 |

> `warning` 不是錯誤：HTTP 200 但 `warning` 非 null，代表**模型沒真的讀到文章**（paywall / error / unsafe），下面的摘要是幻覺。前端要把它顯示成橘色警告框。

### Python 函式簽章（對照組）

```python
check_url(raw: str) -> str                       # 不合格 raise ValueError
summarize(url: str, length: str = "medium") -> dict
parse_result(it) -> dict                         # it 需有 .output_text 與 .steps
```

### Gemini interactions 呼叫（對照 M1）

```python
with genai.Client() as client:                   # ← 必須 with；鏈式呼叫會 RuntimeError
    it = client.interactions.create(
        model="gemini-3.7-flash",
        system_instruction=SYSTEM,
        input=f"讀這篇文章並摘要，bullets 給我 {n} 條：{url}",
        tools=[{"type": "url_context"}],         # dict 形式，tools 的 union 解得動
        response_mime_type="application/json",   # 有 response_format 就必填
        response_format={"type": "text", "mime_type": "application/json",
                         "schema": SCHEMA},
    )
```

回傳的 `Interaction` 上這個 Lab 只用兩樣：

| 欄位 | 型別 | 用途 |
|---|---|---|
| `it.output_text` | `str` | 符合 `SCHEMA` 的 JSON 字串 |
| `it.steps` | `list[Step] \| None` | 撈 `type == "url_context_result"` 的步驟 |

`url_context_result` 步驟的形狀（查自 `google-genai` 2.20.0 `_gaos/types/interactions/urlcontextresultstep.py`）：

```python
step.type   == "url_context_result"
step.call_id: str
step.result:  list[URLContextResult]     # 每個有 .url: str|None、.status: str|None
step.is_error: bool | None
```

`status` 的合法值：`"success"` / `"error"` / `"paywall"` / `"unsafe"`（來源同上檔案的 `URLContextResultStatus`）。**只有 `"success"` 算讀到了。**

相關的 SSE 事件與步驟型別（本 Lab 沒串流，但 Build mode 生成的程式碼可能有）：`url_context_call` / `url_context_result` 兩種 step type；`step.delta` 的 `delta.type` 同名。事件名只有 `interaction.created` / `step.start` / `step.delta` / `step.stop` / `interaction.completed` / `error`——**沒有 `step.complete`**。

### JSON schema（`SCHEMA` 常數）

| 欄位 | 型別 | required | 說明 |
|---|---|---|---|
| `title` | string | ✅ | 文章標題，翻成繁中 |
| `bullets` | string[] | ✅ | 重點摘要，條數由 `length` 決定 |
| `terms` | object[] | ✅ | 每個 `{term, explain}`，兩個子欄位都 required |
| `quotes` | string[] | ✅ | 原文句子，保持原文語言 |

四個欄位都進 `required`。沒寫 required 的欄位模型可能整個省略，前端 `d.bullets.map(...)` 就 `TypeError: d.bullets is undefined`。

## 4. 資料模型

無。沒有 DB、沒有 session、沒有 `previous_interaction_id`（免費層對話只保存 1 天，投影片 p66）。

唯一持久狀態是瀏覽器端的主題偏好：

| Key | 位置 | 值 | 說明 |
|---|---|---|---|
| `tldr-theme` | `localStorage` | `"dark"` / `"light"` | 沒有這個 key 時跟隨系統 `prefers-color-scheme`。讀寫都包 try/catch（無痕模式會丟 `SecurityError`） |

## 5. 檔案結構

```
lab2/
├── PRD.md              產品需求（你正在讀的隔壁那份）
├── SPEC.md             本檔
├── walkthrough.md      一步一步教學 ← 學生從這裡開始
├── app.py              對照組全部：FastAPI 路由 + 一頁 HTML + self-check
├── Dockerfile          Cloud Run 用；uv sync --locked，不走 buildpacks
├── .dockerignore       擋掉 .venv / __pycache__ / *.md
├── deploy.sh           可貼的 Cloud Run 部署腳本（gcloud）
├── pyproject.toml      uv 管的依賴：google-genai、fastapi[standard]
└── uv.lock             鎖定版本；Dockerfile 靠它做 reproducible build
```

`app.py` 內部分區（一個檔案 200 行左右，刻意不拆）：

| 區塊 | 內容 |
|---|---|
| 常數 | `MODEL` / `SYSTEM` / `LENGTHS` / `SCHEMA` |
| 邏輯 | `check_url()` / `parse_result()` / `summarize()` |
| 前端 | `PAGE`（HTML＋CSS＋JS 全在一個字串） |
| web | `make_app()`：三個路由 |
| 驗證 | `self_check()`：assert ＋ `SimpleNamespace` 假物件 |

## 6. 環境變數與設定

| 變數 | 用途 | 從哪來 | 預設 |
|---|---|---|---|
| `GEMINI_API_KEY` | `genai.Client()` 自動讀；沒有就 `ValueError: No API key was provided.` | <https://aistudio.google.com/apikey>（Lab 1 建過的可以重用） | 無，必填 |
| `PORT` | uvicorn 監聽的 port；**Cloud Run 會注入** | Cloud Run 執行環境；本機不設 | `8080` |
| `SERVICE` | `deploy.sh` 的 Cloud Run 服務名 | 自己覆寫 | `tldr-tw` |
| `REGION` | `deploy.sh` 的部署區域 | 自己覆寫（`asia-east1` 也行） | `us-central1` |

Build mode 那一側**不需要**任何環境變數：API key 由平台代管（投影片 p68），生成的程式碼裡不會有裸 key。

> 順帶記住投影片 p74 的改名：企業路線是 `GOOGLE_GENAI_USE_ENTERPRISE=True`（舊名 `GOOGLE_GENAI_USE_VERTEXAI` 仍相容）。這個 Lab 兩個都不用，M5 才用得到。

## 7. 執行流程

Build mode（瀏覽器，無指令）：

```
aistudio.google.com → 左側 Build → 貼需求 → 生成 → 預覽測試
  → 文字迭代 ×2 → annotation 改 UI ×1 → Deploy to Cloud Run
  → 手機開 *.run.app → Export to Antigravity
```

對照組（從零到驗收）：

```bash
# 1. 環境
cd /Users/<你>/Antigravity-teach/lab2
export GEMINI_API_KEY="貼你的 key"

# 2. 離線驗證（不花錢）
uv run app.py --self-check                      # → self-check ok

# 3. 本機跑起來
uv run app.py                                   # → Uvicorn running on http://0.0.0.0:8080
open http://localhost:8080                       # 貼一篇技術文章的網址試

# 4. 容器化驗證（可跳過，但這步能提前抓到 90% 的部署失敗）
docker build -t lab2-tldr .
docker run -d --name lab2-tldr -e PORT=9090 -p 9090:9090 \
  -e GEMINI_API_KEY="$GEMINI_API_KEY" lab2-tldr   # -d 是必要的：前景跑會卡住，下一行永遠不會執行
sleep 3
curl -s localhost:9090/healthz                  # → {"ok":true,"has_key":true}
docker rm -f lab2-tldr                          # 驗完就收；不收的話 docker rmi 會說 image 正在使用中

# 5. 上 Cloud Run（需要已綁帳單的 GCP 專案）
gcloud config set project <你的 PROJECT_ID>
bash deploy.sh                                  # 印出 *.run.app 網址並自動打 /healthz
```

## 8. 錯誤處理與邊界

| 情境 | 症狀 | 處理方式 |
|---|---|---|
| 使用者貼 `file://` / `javascript:` / 只打網域名 | — | `check_url()` 擋在最前面 → HTTP 400，不進 SDK、不花錢 |
| 沒設 `GEMINI_API_KEY` | `500 ValueError: No API key was provided.` | 刻意**不**跟 400 共用 try：SDK 缺 key 也丟 `ValueError`，混在一起會被誤報成「網址格式錯」，學生會往錯的方向找很久 |
| 文章在 paywall 後面 / 抓取失敗 | HTTP 200，但摘要是編的 | `parse_result()` 檢查每個 `url_context_result` 的 `status`；沒有一個 `"success"` 就填 `warning`，前端顯示橘色警告 |
| 模型回傳空 JSON | `output_text == "{}"` | 所有欄位 `or []` / `or "（無標題）"` 補預設；前端 `.map()` 不會炸 |
| `it.steps is None`（沒有任何步驟） | — | `(getattr(it, "steps", None) or [])`，安全走空迴圈，`warning` 會提示「抓取紀錄：無」 |
| step 沒有 `result` 欄位（例如 `model_output`） | — | `getattr(s, "result", None) or []`。直接 `s.result` 會 `AttributeError` |
| 前端把模型輸出當 HTML 塞進 DOM | XSS | JS 端 `esc()` 逃逸 `< > & " '` 再組字串。**模型輸出是不可信輸入**——它可能忠實抄了文章裡的一段 `<script>`。引號也要逃：`sources` 是塞進 `href="..."` 的，只逃 `< > &` 的話網址裡一個 `"` 就能跳出屬性接 `onmouseover=` |
| Cloud Run 給的 port 不是 8080 | 容器 healthcheck 失敗、部署 rollback | `int(os.environ.get("PORT", 8080))`，寫死會失敗 |
| `localStorage` 不可用（無痕模式） | JS 拋 `SecurityError`，整段 script 中斷 | 讀寫都包 `try{}catch(e){}` |
| Cloud Run 預設私有 | 手機開了顯示 `403 Forbidden` | `--allow-unauthenticated`（`deploy.sh` 已帶） |
| 部署後每次都 500，本機正常 | `ValueError: No API key was provided.` | `--set-env-vars GEMINI_API_KEY=...`。本機的 `export` 不會跟著上雲 |

## 9. 驗證方式

**離線可驗（已實際跑過，見 walkthrough 的驗收段）**

```bash
uv run app.py --self-check
```

`self_check()` 用 `types.SimpleNamespace` 假造 `Interaction`，斷言四件事：

1. 六種不合格網址（空字串、純空白、`file://`、`javascript:`、無 scheme、無 host）都被擋，合格網址會 strip 空白後原樣通回。
2. `status == "success"` 時 `sources` 收得到、`warning` 是 `None`。
3. `status == "paywall"` 時 `warning` 一定非 null（這條顧的是「把幻覺當摘要送出去」）。
4. `output_text == "{}"` ＋ `steps is None` 時所有陣列欄位是 `[]`、`title` 有預設、`warning` 非 null——也就是不會 `KeyError`、不會 `TypeError`。

順手驗到的邊界：`step` 沒有 `result` 屬性、`result` 是 `None`，兩種都不能炸。

**本機端到端可驗**

```bash
curl -s localhost:8080/healthz
curl -s -w " [HTTP %{http_code}]\n" -X POST localhost:8080/api/summarize \
  -H 'content-type: application/json' -d '{"url":"file:///etc/passwd"}'
```

**容器可驗**：`docker build` ＋ `docker run -e PORT=9090` 打 `/healthz`，確認 `$PORT` 真的被讀。

**沒辦法離線驗的**

> ⚠️ 未實測：AI Studio Build mode 的全部 UI 操作（步驟 1–6）。需要 Google 帳號登入互動式網頁，介面按鈕位置以 2026-08 為準，可能改版。
> ⚠️ 未實測：`gcloud run deploy` 與 `*.run.app` 實際上線。本機沒有安裝 gcloud（`which gcloud` → not found），也沒有已綁帳單的 GCP 專案。`deploy.sh` 只驗到 `bash -n`（語法無誤）。
> ⚠️ 未實測：真實的 Gemini API 呼叫（`summarize()` 走完整路徑）。需要有效的 `GEMINI_API_KEY` 且會消耗配額。`parse_result()` 是用假物件驗的，欄位形狀查自本機 `google-genai` 2.20.0 原始碼。
> ⚠️ 未實測：`gemini-3.7-flash` 這個型號名是否還在線。型號名以課程投影片為準（基準日 2026-08-25）；若 404 用 `client.models.list()` 確認。

## 10. 已知限制與升級路徑

| 位置 | ponytail 註解 | 天花板 | 升級路徑 |
|---|---|---|---|
| `app.py` `api()` | `# ponytail: 一律 500 帶原文訊息, 要分類重試就上 M10 的錯誤處理` | 429（配額用完）和 503（模型忙）都變成同一個 500，前端無法決定要不要重試；錯誤原文會直接吐給使用者 | 依 exception 型別分流 ＋ 指數退避重試；M10 的部署章節處理 |
| `deploy.sh` | `# ponytail: key 用 --set-env-vars 直接塞, 正式環境改 Secret Manager（M5 教）` | key 明文存在 Cloud Run 服務設定裡，任何有 `run.viewer` 的人都看得到 | `echo -n "$K" \| gcloud secrets create gemini-key --data-file=-` ＋ `--set-secrets`；M5 |
| `summarize()` | 無註解，設計如此 | 每次請求都重打一次 API，同一個網址問十次付十次 | 加 `functools.lru_cache` 或 Cloud Run 前面掛 CDN；不值得在 Lab 2 做 |
| `PAGE` | 無註解，設計如此 | 沒有 build step、沒有元件化，HTML/CSS/JS 全在一個 Python 字串裡。超過 300 行就該拆 | 就是去用 Build mode 生成的 React 版本，或進 M3 讓 Antigravity 重構 |
| 無 session | 設計如此 | 沒有歷史紀錄、重整就消失 | 接 Supabase（M8）；`previous_interaction_id` 在免費層只活 1 天，不能當儲存 |
| `MODEL` 寫在常數 | — | 型號退役時要改程式碼（附錄 D-⑧ 的坑） | 挪到環境變數：`os.environ.get("MODEL", "gemini-3.7-flash")` |
