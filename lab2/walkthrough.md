# Lab 2 走一遍：Build 一個 App 並部署上 Cloud Run

> 40–60 分鐘 ｜ 體驗完整 vibe coding 循環：需求 → App → 迭代 → 公開網址

做完你會有**兩個**東西：

1. 一個 AI Studio Build mode 生成的 React app，掛在 `https://<something>.run.app` 上，用手機打開就能用。
2. 一份自己看得懂的**對照組最小實作**（本目錄的 `app.py`，單檔 FastAPI ＋ 一頁 HTML）——用來回答「剛剛那幾十個檔案裡，真正做事的到底是哪幾行」。

對照組跑起來長這樣（下面這段是本機實際輸出）：

```
$ uv run app.py --self-check
self-check ok

$ uv run app.py
INFO:     Started server process [61234]
INFO:     Uvicorn running on http://0.0.0.0:8080 (Press CTRL+C to quit)

$ curl -s localhost:8080/healthz
{"ok":true,"has_key":true}
```

每一步都是「**動手 → 為什麼 → 驗收**」。驗收沒過不要往下走——步驟 5 的 Cloud Run 部署會把前面所有沒解決的問題一次還給你。

> **UI 步驟的免責聲明**
> ⚠️ 未實測：本文所有 AI Studio Build mode 的介面操作（步驟 1、3、4、5、6）。這些需要 Google 帳號登入互動式網頁，撰寫時無法自動化驗證。按鈕位置以 2026-08 的介面為準；改版後**認文字不認座標**——找不到「Deploy」就找雲朵／火箭 icon，找不到就開右上角 `⋮` overflow menu。
> 對照組的程式碼部分（`app.py`、`Dockerfile`）是實際跑過的，哪些跑過、哪些沒跑，每一步的驗收段都會標。

---

## 步驟 0：前置（5 分）

### 動手

```bash
# 1) Lab 1 建過的 key 直接重用；沒有就去 https://aistudio.google.com/apikey 建一把
export GEMINI_API_KEY="貼上你的 key"

# 2) 進到這個 lab 的目錄
cd /Users/<你>/Antigravity-teach/lab2

# 3) 先挑一篇「真的看得到內容」的技術文章當測試素材，存起來待會一直用
export ART="https://ai.google.dev/gemini-api/docs/models"
```

另外開好瀏覽器：<https://aistudio.google.com>，Google 帳號登入。

### 為什麼

- **Build mode 不需要你給 key**（投影片 p68：secrets 平台代管），但**對照組需要**。兩邊 key 的來源不同是這個 Lab 最容易搞混的地方：Build 版的呼叫算在平台代管的憑證上，部署到 Cloud Run 之後才變成算你的配額（p77）。
- **測試素材要慎選**。挑一篇在 paywall 後面、或需要登入才看得到的文章，你會得到一份「看起來很專業但完全是編的」摘要——而且新手八成會以為是自己 prompt 寫壞了，浪費 20 分鐘。第一次測試一律用公開的官方文件。
- **不要貼公司內部連結**。免費層的輸入可能用於產品改進（p66 / p77），這是資安紅線，不是建議。

### 驗收

```bash
echo ${GEMINI_API_KEY:0:6}...   # 有印出前 6 碼就對了，不要整把印出來截圖
ls Dockerfile app.py deploy.sh  # 三個檔案都在
```

---

## 步驟 1：進入 Build mode，輸入需求（10 分）

### 動手

先**故意寫一個爛 prompt**。這步的重點不是拿到好結果，是看清 vibe coding 會在哪裡騙你。

1. AI Studio 左側導覽列點 **Build**（在 Home / Playground 下面）。
2. 中央輸入框（placeholder 通常是 "Describe the app you want to build..."）貼這句，按送出：

```
做一個技術文章摘要器
```

3. 等數十秒。右側 Preview 面板會跑起一個真的 app。
4. 把 `$ART` 那個網址貼進去，按摘要。**同時再貼一個你臨時亂編的網址**，例如：

```
https://ai.google.dev/this-page-does-not-exist-lab2
```

大概率兩個都會吐出一份煞有其事的摘要。**第二個網址根本不存在**，摘要卻寫得頭頭是道——這就是問題。

5. 現在寫真正的需求。在同一個對話框接著輸入（不要開新專案，讓它改現有的）：

```
改成「技術文章轉繁體中文摘要器」，規格如下：
1. 使用者貼一個 URL，輸出：重點摘要（條列）＋ 名詞解釋（術語 → 一句話白話）
2. 必須用 Gemini 的 url_context 工具真的去抓那個網頁的內容，
   不准只把網址字串丟給模型憑印象生成
3. 如果抓取失敗（404 / paywall / 需登入），畫面上要明確顯示「無法讀取這篇文章」，
   絕對不要生一份假摘要
4. 全部輸出用繁體中文（台灣用語），專有名詞保留英文原文
5. 支援深色模式，跟隨系統設定，並提供手動切換按鈕
```

6. 再測一次那兩個網址。

### 為什麼

**不這樣寫會怎樣**——就是你剛剛看到的：假摘要。

模型本身沒有網路。你把 `https://example.com/foo` 貼進 prompt，它收到的只是一串字。它會從網址的字面（域名、路徑裡的英文單字）＋訓練資料裡的印象，生成一篇「這種網址通常會寫什麼」的文章。輸出流暢、格式正確、內容全假，而且**不會有任何錯誤訊息**。

要它真的去讀，必須掛 `url_context` 工具（M1 教過的 `tools=[...]`，這裡換成另一個 type）。Build mode 會依你的描述自動選對 API（p68 「自動選對 API」），但它只選你**講出來**的——你沒說「要真的抓網頁」，它就只做「摘要」這個字面需求。

第 3 條「抓取失敗要說」比第 2 條更重要。掛了工具還是會失敗：paywall、需登入、robots 擋、404。工具失敗時模型會**退回憑印象生成**，症狀跟沒掛工具一模一樣。這條需求逼它把失敗顯示出來。

第 5 條深色模式寫「跟隨系統 ＋ 手動切換」，不要只寫「深色模式」。只寫深色模式你可能會拿到一個永遠是黑的介面，白天用很痛苦。

### 驗收

- [ ] Preview 面板裡的 app 能操作，貼 `$ART` 會吐出繁體中文的條列摘要 ＋ 名詞解釋兩個區塊
- [ ] 貼那個**不存在的網址**，畫面顯示「無法讀取」之類的訊息，**不是**一篇摘要 ← 這條是這步的真正驗收
- [ ] 有深色／淺色切換，切下去整頁配色真的變
- [ ] 摘要裡的專有名詞（`url_context`、`streaming` 之類）保留英文，沒被翻成「網址上下文」

第二條沒過就回去改 prompt，把「抓取失敗必須明說」講得更兇（例如「寧可什麼都不輸出，也不要猜」）。這比後面任何一步都值得花時間。

---

## 步驟 2：觀察生成的程式碼結構（8 分）

### 動手

1. 預覽面板上方切到 **Code** 分頁（或點左側檔案樹圖示），你會看到一個標準 React 專案，大致長這樣：

```
index.html
index.tsx
App.tsx                    ← UI 主體，深色模式的 class 在這裡
components/                ← 拆出來的元件
services/geminiService.ts  ← 你要找的就是這個
metadata.json
package.json
```

2. 打開 `services/` 底下那個檔名帶 `gemini` 的檔案。在裡面找這四樣東西，把行號記下來：

| 找什麼 | 長什麼樣 |
|---|---|
| model 名稱 | `model: "gemini-3.7-flash"` 或類似字串 |
| system instruction | `systemInstruction:` |
| 工具 | `tools: [{ type: "url_context" }]` |
| 輸出格式 | `responseFormat` / `responseMimeType` / `responseSchema` |

3. 和 M1 的 Python 寫法並排看：

```python
# Lab 1 的 ask.py（Python）
client.interactions.create(
    model="gemini-3.7-flash",
    system_instruction=SYSTEM,
    input=question,
    tools=[{"type": "google_search"}],     # ← Lab 2 換成 url_context
    stream=True,
)
```

```typescript
// Build mode 生成的（TypeScript，同一個 Interactions API）
// ⚠️ 未實測：這段是「大致會長這樣」，實際的變數名、檔名、有沒有包一層 helper 都可能不同。
//    要對照的是欄位名，不是逐字比對。
ai.interactions.create({
  model: "gemini-3.7-flash",
  systemInstruction: SYSTEM,
  input: prompt,
  tools: [{ type: "url_context" }],
  stream: true,
});
```

### 為什麼

- **這步不做，你會一直把 Build mode 當黑盒**。看到 `tools: [{ type: "url_context" }]` 那一行的瞬間，你才會理解：步驟 1 那個假摘要不是「AI 不夠聰明」，是**那一行當時不存在**。這是整個 Lab 認知價值最高的 30 秒。
- **命名差異只有 snake_case ↔ camelCase**（`system_instruction` ↔ `systemInstruction`）。同一個 API、同一批欄位。認出這件事，之後在任何語言裡讀 Gemini 程式碼都不會慌。
- **API key 在哪？找不到是對的。** 生成的程式碼裡不會有裸 key（p68 secrets 平台代管）。你會看到類似 `process.env.API_KEY` 的東西，值由平台注入。**這也是步驟 5 部署後最常爆的地方**——部署環境沒有那個平台注入，key 要重新設定。
- **投影片 p77 說「Get code ≠ 生產程式碼」，這裡也一樣**。你會看到沒有 retry、錯誤處理只有一個 `catch(e) { alert(e) }`。這不是 bug，是分工：0→1 交給 vibe coding，1→100 交給 M3 的 Antigravity。

### 驗收

回答這三題（口頭或寫在便條紙上都行，這步沒有指令可跑）：

- [ ] 呼叫 Gemini 的檔案完整路徑是？
- [ ] 它用的 model ID 是？（和你 Lab 1 用的一樣嗎？）
- [ ] `url_context` 出現在第幾行？（找不到 = 步驟 1 的第 2 條需求沒被實作，回去補）

> 💡 **啊哈：Build mode 生的 TypeScript 和你的 Python 不是兩套 SDK，是同一個 HTTP 端點的兩件外衣。**
> 已安裝的 `google-genai` 原始碼裡，每個 API 都自帶 sh／python／javascript 三份範例，全部 `POST` 到同一個
> `https://generativelanguage.googleapis.com/v1beta/interactions`。也就是說：vibe coding 沒有走另一條後門，
> 它生的程式碼能做的事，你用一行 `curl` 也做得到——差別只在誰幫你把 UI 寫好。
> **動手看**：`uv run python -c "import re,google.genai._gaos.interactions as m;s=open(m.__file__).read();print(sorted(set(re.findall(r'\"lang\": \"(\w+)\"',s))),s.count('v1beta/interactions'),'處同一端點')"` → `['javascript', 'python', 'sh'] 32 處同一端點`

---

## 插播：對照組——自己刻一份最小實作（10 分，強烈建議）

> 這段不在投影片的六個步驟裡，但它是步驟 2 的必要補完。剛剛你看到幾十個檔案，現在看看同一件事最少要幾行。

### 動手

```bash
cd /Users/<你>/Antigravity-teach/lab2

# 先跑離線檢查（不連網、不打 API、不花錢）
uv run app.py --self-check

# 故意先不設 key，看它怎麼死
unset GEMINI_API_KEY
uv run app.py &
sleep 3
curl -s -w " [HTTP %{http_code}]\n" -X POST localhost:8080/api/summarize \
  -H 'content-type: application/json' -d '{"url":"https://ai.google.dev/gemini-api/docs/models"}'
```

你會拿到（這是實際輸出）：

```
{"detail":"ValueError: No API key was provided. Please pass a valid API key. Learn how to create an API key at https://ai.google.dev/gemini-api/docs/api-key."} [HTTP 500]
```

**把這個錯誤訊息記牢**。步驟 5 部署完之後，你有很大機率會在 `*.run.app` 上再看到它一次。

現在修好：

```bash
kill %1
export GEMINI_API_KEY="貼你的 key"
uv run app.py
```

瀏覽器開 <http://localhost:8080>，貼一篇技術文章網址試。

`app.py` 全部就這幾塊（`app.py` 完整內容在同目錄，這裡只列核心）：

```python
def check_url(raw):
    """只放行 http/https 的絕對網址；不合格丟 ValueError。"""
    u = (raw or "").strip()
    p = urllib.parse.urlparse(u)
    if p.scheme not in ("http", "https") or not p.netloc:
        raise ValueError("請貼 http:// 或 https:// 開頭的完整網址")
    return u


def summarize(url, length="medium"):
    from google import genai
    n = LENGTHS.get(length, LENGTHS["medium"])
    with genai.Client() as client:              # 必須 with，理由見下
        it = client.interactions.create(
            model="gemini-3.7-flash",
            system_instruction=SYSTEM,
            input=f"讀這篇文章並摘要，bullets 給我 {n} 條：{url}",
            tools=[{"type": "url_context"}],    # ← 步驟 1 假摘要的解藥就是這一行
            response_mime_type="application/json",
            response_format={"type": "text", "mime_type": "application/json",
                             "schema": SCHEMA},
        )
    return parse_result(it)


def parse_result(it):
    """解 JSON，順手從 steps 撈「到底有沒有真的抓到網頁」。"""
    fetched = [(getattr(r, "url", None), getattr(r, "status", None))
               for s in (getattr(it, "steps", None) or [])
               if getattr(s, "type", None) == "url_context_result"
               for r in (getattr(s, "result", None) or [])]
    ok = [u for u, st in fetched if st == "success"]
    data = json.loads(it.output_text or "{}")
    return {
        "title": data.get("title") or "（無標題）",
        "bullets": data.get("bullets") or [],
        "terms": data.get("terms") or [],
        "quotes": data.get("quotes") or [],
        "sources": ok,
        "warning": None if ok else f"模型沒有成功讀到網頁內容（抓取紀錄：{fetched or '無'}），以下摘要不可信",
    }
```

### 為什麼

**為什麼要有對照組**：Build mode 生成的 React 專案幾十個檔案，你很難分辨「哪些是必要的、哪些是它順手加的」。這 20 行是必要的部分。看過之後你就有底氣去砍生成程式碼裡多餘的東西。

**`with genai.Client()` 不能省**。寫成 `genai.Client().interactions.create(...)` 的話，`Client` 是暫時物件，請求送出前就被 GC 回收關閉：

```
RuntimeError: Cannot send a request, as the client has been closed.
```

**`tools=[{"type": "url_context"}]` 少了會怎樣**：不會報錯。模型收到的只是一串網址字元，然後憑印象生成——就是步驟 1 那個假摘要。這是整個 Lab 最危險的失敗模式：**靜默、輸出漂亮、完全錯**。

**`parse_result()` 為什麼要撈 `status`**：掛了工具還是會抓不到。`url_context_result` 這個 step 裡每筆 `result` 有 `status`，合法值是 `success` / `error` / `paywall` / `unsafe`（查自 `google-genai` 2.20.0 的 `urlcontextresult.py`）。**只有 `success` 算讀到了**。不檢查的話，paywall 文章會回一份 HTTP 200 的幻覺摘要，前端無從分辨。

**`getattr(s, "result", None) or []` 的兩層防護不是龜毛**：`steps` 裡混著 `url_context_call`、`model_output` 這些步驟，它們身上**沒有 `result` 這個屬性**。直接寫 `s.result` 會 `AttributeError: 'ModelOutputStep' object has no attribute 'result'`。就算有，值也可能是 `None`，`for r in None` 會 `TypeError: 'NoneType' object is not iterable`。

**`response_mime_type` 和 `response_format` 要一起給**。只給 `response_format` 不給 `response_mime_type="application/json"`，結構化輸出不會生效，`json.loads()` 會在自由文字上炸掉。

**`check_url()` 為什麼不能省**：使用者輸入會被原封不動塞進 prompt。這是 trust boundary，`file:///etc/passwd`、`javascript:` 都得擋在進 SDK 之前——擋在前面還有個好處：不合格的請求不會花錢。

**兩個 `try` 不能合併**（`app.py` 裡有註解標出來）。SDK 沒有 key 時丟的也是 `ValueError`。合成一個 `except ValueError → 400` 的話，「忘記 export key」會被誤報成「網址格式錯」，學生會盯著網址找半小時。

### 驗收

以下三條**實際跑過**：

```bash
uv run app.py --self-check
# → self-check ok

curl -s localhost:8080/healthz
# → {"ok":true,"has_key":true}      ← has_key 是 false 就是沒 export key

curl -s -w " [HTTP %{http_code}]\n" -X POST localhost:8080/api/summarize \
  -H 'content-type: application/json' -d '{"url":"file:///etc/passwd"}'
# → {"detail":"請貼 http:// 或 https:// 開頭的完整網址"} [HTTP 400]
```

> ⚠️ 未實測：真的貼一篇文章拿到摘要（需要有效 key、會消耗配額）。`parse_result()` 的邏輯是用 `--self-check` 的假物件驗的，欄位形狀查自本機 `google-genai` 2.20.0 原始碼。

檢查清單：

- [ ] `--self-check` 印出 `self-check ok`
- [ ] `/healthz` 的 `has_key` 是 `true`
- [ ] 亂網址回 400，錯誤訊息是中文那句
- [ ] 瀏覽器開 <http://localhost:8080>，深色模式切換鈕（🌓 主題）按下去整頁配色會變，**重新整理後記得住**

> 💡 **啊哈：`url_context` 只是 `tools` 陣列裡九種 `type` 之一，而「你自己寫的一個 python 函式」也在同一份名單上。**
> API 眼裡沒有「grounding 工具」和「自訂工具」的分別，只有一個 union：`function` / `google_search` /
> `url_context` / `mcp_server` / `code_execution` / `file_search` / `retrieval` / `google_maps` / `computer_use`。
> 這是全課主線的岔路口：`../lab1/ask.py:73` 用 `google_search`、這裡用 `url_context`、`../lab6/server.py:51`
> 用 `@mcp.tool()` 把函式掛上 MCP server、`../lab7/travel_planner/agent.py:121` 直接把函式塞進 ADK 的 `tools=[...]`。換的是包裝，不是概念。
> **動手看**：`uv run python -c "from google.genai._gaos.types.interactions.tool import _TOOL_VARIANTS as T; print(sorted(T))"` → 印出那九個名字

---

## 步驟 3：文字迭代兩輪（8 分）

### 動手

回到 AI Studio Build mode 的對話框。**一次只講一件事**，等它生成完、測過，再講下一件。

**第一輪——加上摘要長度選項：**

```
在 URL 輸入框旁邊加一個下拉選單：短 / 中 / 長。
短 = 3 條重點，中 = 5 條，長 = 8 條。
這個選項要真的改到送給模型的指令，不是只在前端截斷。
```

生成完，同一篇文章分別選「短」和「長」各跑一次，數條數。

**第二輪——引用原文的句子用 quote 樣式：**

```
摘要下面加一個「原文引用」區塊：從文章裡挑 2-3 句最關鍵的原句，
保持原文語言不要翻譯，用 blockquote 樣式呈現
（左側 4px 色條 + 淺灰底 + 斜體），視覺上和一般段落分得開。
深色模式下色條和底色也要對應調整。
```

### 為什麼

- **「要真的改到送給模型的指令，不是只在前端截斷」這句非講不可。** 不講的話，最省事的實作是讓模型照樣生 8 條、前端 `slice(0, 3)`。結果：選「短」跟選「長」一樣慢、一樣貴、一樣多 token，只是少顯示幾條。這是 LLM app 最常見的假優化。
- **一輪只講一件事**。兩件事一起講，它可能只做一件、或兩件都做半套，而且你分不出是哪個需求沒被理解。改壞了要回退時也難——一次一件事，壞了就回上一輪。
- **深色模式要單獨點出來**。「加 blockquote 樣式」它會給你 `background: #f5f5f5`，深色模式下就變成一塊刺眼的白。生成式 UI 幾乎不會主動處理兩套配色，你得每次改樣式都提醒它一次。
- **「保持原文語言不要翻譯」**：引用的價值在於可回溯原文。翻譯過的「引用」你沒辦法拿去原文裡 Ctrl+F 比對，就失去引用的意義了。

對照組裡對應的是 `LENGTHS` 這個 dict 和 `SCHEMA` 的 `quotes` 欄位——三行的事：

```python
LENGTHS = {"short": "3", "medium": "5", "long": "8"}
...
input=f"讀這篇文章並摘要，bullets 給我 {n} 條：{url}",
```

### 驗收

- [ ] 介面上有短／中／長選單
- [ ] 同一篇文章：選「短」的條數明顯少於選「長」（3 vs 8 左右，不用剛好）
- [ ] 切到 Code 分頁，確認長度選項有進到送給模型的 prompt 字串裡（搜 `3` / `bullets` / `條`），**不是**只在 render 時 slice
- [ ] 「原文引用」區塊有左側色條 ＋ 底色 ＋ 斜體，和上面的條列視覺上分得開
- [ ] 引用的句子是原文語言（英文文章 → 英文句子），沒被翻成中文
- [ ] **切到深色模式**，引用區塊沒有變成一塊白色

最後一條沒過就再補一句：「blockquote 的底色和色條要用 CSS 變數，跟著主題切換」。

---

## 步驟 4：用 annotation 改一個 UI 細節（5 分）

### 動手

1. 在 Preview 面板上方（或側邊）找 **annotation 工具**——通常是一個游標／畫筆／方框選取的 icon，滑過去會顯示 "Select element" 或 "Annotate"。點它啟用。
2. 游標移到預覽畫面上，元件會被高亮框住。**點那顆「摘要」按鈕**。
3. 旁邊跳出的輸入框裡寫具體的指令，例如：

```
這顆按鈕改成圓角膠囊形（border-radius 999px），
寬度撐滿輸入框那一列，並移到選單的右邊
```

4. 送出，看 Preview 面板的變化。

### 為什麼

- **不用 annotation 會怎樣**：你得用文字描述「是哪一個元件」。介面上有三顆按鈕時，「把按鈕改圓角」它得猜——猜錯就改到別顆，或者三顆全改。你再打字澄清，它再猜。annotation 把「指定目標」這件事從模糊的自然語言變成一次點擊，這是它存在的唯一理由（p68 「視覺化指定修改目標」）。
- **分工要記住**：**annotation 指目標，文字講內容**。點了按鈕還是要用文字說「要改成什麼」。有人以為點一下就會自動變好看——不會。
- **指令要具體到數值**。「大一點」它可能加 2px 你看不出來，你會以為它沒動。給 `border-radius 999px`、「撐滿那一列」這種可驗證的描述，才驗收得起來。
- **這步驟做完不要繼續改 UI**。投影片只要求一個 UI 細節，時間盒 40–60 分。UI 可以無限迭代，但這個 Lab 的重點在後面的部署。

### 驗收

- [ ] Preview 裡那顆按鈕**看得出來變了**（形狀 / 位置 / 顏色）
- [ ] 切到 Code 分頁，找得到對應的 CSS 或 className 改動
- [ ] 其他按鈕**沒有**被一起改掉（改到別的就是 annotation 沒點準，重來一次）

---

## 步驟 5：Deploy → Cloud Run（12 分）

### 動手

**5a. Build mode 一鍵部署**

1. 右上角找 **Deploy**（雲朵或火箭 icon；找不到就開 `⋮` overflow menu → "Deploy to Cloud Run"）。
2. 面板會問服務名稱、region。region 挑 `us-central1` 或 `asia-east1`（離台灣近）。
3. 按下部署，等 **3–8 分鐘**。它在背後做的事是：打包容器 → 上傳 → Cloud Build → 推 Artifact Registry → 建立 Cloud Run 服務。第一次特別慢，看到進度條卡住不要重按。
4. 完成後拿到一個 `https://<service>-<hash>.run.app` 網址。
5. **用手機開，而且關掉 Wi-Fi 用行動網路。**

**5b.（加分）把對照組也推上去**

```bash
cd /Users/<你>/Antigravity-teach/lab2

# 先在本機用容器驗一遍。這步是實際跑過的，能提前抓到大部分部署失敗
docker build -t lab2-tldr .
docker run -d --name lab2-tldr -e PORT=9090 -p 9090:9090 \
  -e GEMINI_API_KEY="$GEMINI_API_KEY" lab2-tldr    # -d 別省：前景跑會卡住，後面的 curl 永遠不會執行
sleep 3
curl -s localhost:9090/healthz     # → {"ok":true,"has_key":true}
docker rm -f lab2-tldr             # 驗完就收，不然清理段的 docker rmi 會說 image 正在使用中

# 真的上雲（需要已綁帳單的 GCP 專案，M5 才正式設）
gcloud config set project <你的 PROJECT_ID>
bash deploy.sh
```

**先體驗一次失敗**（這段值得刻意做，因為你八成本來就會踩到）。手動跑一次少東西的部署：

```bash
gcloud run deploy tldr-broken --source . --region us-central1
```

> ⚠️ 未實測（沒有 gcloud）：不帶 `--allow-unauthenticated` 時 gcloud 很可能會**互動問你** `Allow unauthenticated invocations to [tldr-broken] (y/N)?`。要看到下面那個 403，這裡要回 **N**（直接按 Enter 就是 N）。回 y 就等於補了那個參數，這個失敗體驗就沒了。

`deploy.sh` 裡刻意帶的兩個參數這次都沒給，於是你會連中兩發：

- 沒有 `--allow-unauthenticated` → 手機打開網址看到 **403 Forbidden**（Cloud Run 服務預設是私有的）
- 沒有 `--set-env-vars GEMINI_API_KEY=...` → 首頁載得出來，但一按摘要就 **500**，`detail` 是那句 `ValueError: No API key was provided.`

看到之後再跑正確版：

```bash
bash deploy.sh
```

### 為什麼

**「本機好好的，上雲就壞」的三大原因，這一步全湊齊了：**

1. **`export` 不會跟著上雲。** 你本機的 `export GEMINI_API_KEY=...` 只活在那個 shell。容器裡是全新的環境，一個變數都沒有。這就是為什麼 `deploy.sh` 必須 `--set-env-vars`。步驟 2 裡「找不到裸 key」是因為 AI Studio 平台幫你注入，離開那個平台就沒人幫你注入了。
2. **Cloud Run 預設私有。** 不加 `--allow-unauthenticated`，只有帶著 IAM identity token 的請求進得去。你自己的瀏覽器可能因為登入著 Google 帳號而**看起來正常**，別人打開就 403——所以驗收一定要用**別的裝置 ＋ 別的網路**，這是 `--allow-unauthenticated` 沒生效唯一可靠的檢測方式。
3. **`$PORT` 是 Cloud Run 給的，不是你決定的。** `app.py` 寫 `int(os.environ.get("PORT", 8080))`。寫死 `port=8080` 的話，Cloud Run 注入別的 port 時你的程式聽錯地方，健康檢查失敗，部署 rollback，log 顯示 `The user-provided container failed to start and listen on the port defined provided by the PORT=... environment variable`。這種錯最難查，因為程式碼本身完全沒 bug。

**為什麼要有 `Dockerfile`**：`gcloud run deploy --source .` 有 Dockerfile 就用 Dockerfile，沒有就走 buildpacks。而 Python buildpacks 找的是 `requirements.txt`——本課一律用 uv，沒有那個檔案，buildpacks 會直接失敗。寫一個 12 行的 Dockerfile 比為了它生一份 `requirements.txt` 乾淨。

**為什麼 `--max-instances 3`**：部署後的 app 用的是**你的 API key 配額**（p77）。網址是公開的，有人（或某個爬蟲）連續打，配額就沒了。`--max-instances` 是最便宜的保險絲。

**API key 明文放在 `--set-env-vars` 是刻意偷懶**（`deploy.sh` 裡有 `# ponytail:` 註解標出來）。天花板是任何有 `run.viewer` 權限的人都看得到這把 key。正式做法是 Secret Manager：

```bash
echo -n "$GEMINI_API_KEY" | gcloud secrets create gemini-key --data-file=-
# 然後 deploy 時改用 --set-secrets GEMINI_API_KEY=gemini-key:latest
```

M5 會正式教。Lab 2 不做，因為它需要先設好 IAM。

### 驗收

**必要（Build mode 部署）**

- [ ] 拿到 `https://....run.app` 網址
- [ ] **手機關 Wi-Fi 用行動網路**打開，頁面正常載入
- [ ] 手機上貼一篇文章網址，真的吐出摘要（不是 500、不是空白）
- [ ] 深色模式在手機上也對（手機系統設深色 → 網頁跟著深）

**加分（對照組部署）**

```bash
# 本機容器（實際跑過）
curl -s localhost:9090/healthz
# → {"ok":true,"has_key":true}

# 上雲後（deploy.sh 最後一行會自動幫你打）
URL=$(gcloud run services describe tldr-tw --region us-central1 --format='value(status.url)')
curl -fsS "$URL/healthz"
# → {"ok":true,"has_key":true}        ← has_key 是 false 就是忘了 --set-env-vars

curl -s -o /dev/null -w "%{http_code}\n" "$URL/"
# → 200                                ← 403 就是忘了 --allow-unauthenticated
```

> ⚠️ 未實測：`gcloud run deploy` 與 `*.run.app` 上線。撰寫環境沒有安裝 gcloud（`which gcloud` → not found），也沒有已綁帳單的 GCP 專案。`deploy.sh` 只驗到 `bash -n`（語法無誤）。
> ✅ 已實測：`docker build` 成功、`docker run -e PORT=9090` 起得來、容器內 `/healthz` 回 `{"ok":true,"has_key":false}`（未給 key 的情況）。也就是「容器會不會起、會不會讀 `$PORT`」這兩件最常炸的事是驗過的。

> 💡 **啊哈：你寫的程式在 image 裡只是最上面 20.5kB 的一層，底下四層加起來 283MB。**
> `gcloud run deploy --source .` 本質上就是這個 `docker build`：Debian base 109MB ＋ Python 43.7MB ＋
> uv 45.6MB ＋ 依賴 85.1MB，最上面那薄薄一層才是 `app.py`（不到萬分之一）。這疊東西就是冷啟動的來源：
> 沒流量時實例被收掉，下一個請求要重新把 283MB 拉起來。Lab 10 那個「第一次問要等 10-20 秒」（`../lab10/walkthrough.md` 步驟 6）就是同一件事乘以四個服務。
> **動手看**：`docker history lab2-tldr --format '{{.Size}}\t{{.CreatedBy}}'` → `app.py` 那層 20.5kB，往下依序是 85.1MB（`uv sync`）／45.6MB（uv）／43.7MB（Python）／109MB（Debian）

---

## 步驟 6：匯出準備（5 分）

### 動手

1. 右上角 `⋮` overflow menu（或 Deploy 旁邊的分享／出口區）找 **Export to Antigravity**。
2. 它會問你要開哪個 workspace，或直接喚起本機的 Antigravity 桌面版（沒裝先去 <https://antigravity.google/download>）。
3. 進到 Antigravity 之後確認三件事：
   - 檔案樹跟 AI Studio 裡看到的一樣（`App.tsx`、`services/geminiService.ts`…）
   - **Build mode 的對話歷史在**（你的六段 prompt 都看得到）
   - secrets 有帶過來（不是明文顯示，是 Antigravity 認得那個 key 的存在）
4. 順手也按一次 **Download ZIP** 當離線備份。

### 為什麼

- **不匯出會怎樣**：M3 Lab 的起點就是這個專案。沒匯出你就得在 Antigravity 裡從零重建，那個 Lab 的重點（讓 agent 把 prototype 工程化）就沒東西可以工程化了。
- **對話歷史比程式碼值錢。** 程式碼 ZIP 一下就有了，但「當初為什麼這樣做」全在對話裡。Antigravity 的 agent 讀得到那段歷史，它就知道「使用者堅持要 url_context」「使用者要求抓取失敗必須明說」——不用你重講一遍。這是 Export to Antigravity 和 Download ZIP 的真正差別（p71）。
- **ZIP 還是要下載一份。** 雲端出口都有可能改版或掛掉。ZIP 是一個標準 React 專案，`npm install && npm run dev` 就能跑，你手上永遠有一條退路。
- **另外三個出口不必都做**（Push to GitHub、Download ZIP、Deploy）。這個 Lab 只有 Cloud Run 和 Antigravity 是必要路徑，其他兩個知道存在就好。

### 驗收

- [ ] Antigravity 裡開得到這個專案，檔案樹完整
- [ ] Build mode 的對話歷史看得到（至少找得到你步驟 1 那段長需求）
- [ ] 本機有一份 ZIP 備份

> ⚠️ 未實測：Export to Antigravity 的完整流程。需要 Google 帳號登入 ＋ Antigravity 桌面版，無法自動化驗證。實際 UI 可能是彈窗、深層連結（deep link）或要求先在 Antigravity 端登入同一個帳號。

> 💡 **啊哈：把這個 app 從「API key」換成「企業 IAM 認證」，程式碼一個字都不用改——改的是環境變數。**
> `genai.Client()` 沒參數時會自己看環境：有 `GOOGLE_GENAI_USE_ENTERPRISE=True` ＋ `GOOGLE_CLOUD_PROJECT`
> 就走 Enterprise（IAM／ADC，算在你的 GCP 專案上而不是個人 key），否則讀 `GEMINI_API_KEY` 走 Developer API（投影片 p74）。
> 所以「先用免費層做，正式再換企業版」不是重寫，是換一組 env——`../lab5/vertex_smoke.py:24` 就在做這件事，Lab 10 上雲時同一組變數再出現一次。
> **動手看**：`uv run python -c "import re,google.genai._api_client as m;print(*sorted(set(re.findall(r'GOOGLE_GENAI_USE_\w+|GEMINI_API_KEY',open(m.__file__).read()))))"` → `GEMINI_API_KEY GOOGLE_GENAI_USE_ENTERPRISE GOOGLE_GENAI_USE_VERTEXAI`（舊名還在；兩個都設而且值不一致時 SDK 會 warn，以 ENTERPRISE 為準）

---

## 步驟 7：驗收

投影片 p76 的六步全部收攏成一張清單。**全部打勾才算完成這個 Lab。**

```bash
# 對照組的三條可執行驗收（實際跑過）
cd /Users/<你>/Antigravity-teach/lab2
uv run app.py --self-check
# → self-check ok

uv run app.py & sleep 3
curl -s localhost:8080/healthz
# → {"ok":true,"has_key":true}

curl -s -w " [HTTP %{http_code}]\n" -X POST localhost:8080/api/summarize \
  -H 'content-type: application/json' -d '{"url":"file:///etc/passwd"}'
# → {"detail":"請貼 http:// 或 https:// 開頭的完整網址"} [HTTP 400]
kill %1
```

- [ ] **步驟 1**：Build mode 生成的 app 能跑；貼不存在的網址時**明確拒答**而不是編一篇摘要
- [ ] **步驟 2**：說得出呼叫 Gemini 的檔案路徑、model ID、`url_context` 在第幾行
- [ ] **插播**：`uv run app.py --self-check` → `self-check ok`；本機 <http://localhost:8080> 能用
- [ ] **步驟 3a**：短／中／長選單有效，條數真的不同，而且改到了 prompt（不是前端 slice）
- [ ] **步驟 3b**：原文引用用 blockquote 樣式，深色模式下配色正確
- [ ] **步驟 4**：annotation 改掉的元件看得出差異，其他元件沒被波及
- [ ] **步驟 5**：`*.run.app` 網址，**用手機行動網路**開得起來且功能正常
- [ ] **步驟 6**：Antigravity 裡有專案檔案 ＋ Build mode 對話歷史
- [ ] 全程沒有把公司／客戶資料貼進免費層

> 💡 **啊哈：那個公開網址掛在網路上一整個月，帳單可以是 $0.00——因為它只在有人按下「摘要」的那 20 秒才收費。**
> 習慣租機器的人會以為「上線＝開始付月費」。Cloud Run 計費單位是**請求佔用 CPU 的秒數**：同一個服務加上
> `--min-instances 1`（常駐、消掉冷啟動）是 730 vCPU-小時／月，scale-to-zero 是 16.9——÷43，而且整個落在免費層裡。
> 所以步驟 5 那個 `*.run.app` 可以留著當作品集；真正要盯的是**配額**（你的 API key）而不是機器費。
> **動手看**：`uv run app.py --aha` → 並排表最後一列 `$60.19` vs `$0.00`，以及「每天 296 次以內帳單維持 $0」

---

## 常見錯誤對照表

| 症狀 | 原因 | 解法 |
|---|---|---|
| 貼一個**不存在的網址**也吐出漂亮摘要 | Build 生成的程式碼沒掛 `url_context`；模型只看到網址字串，憑印象編。不會有任何錯誤訊息 | 在對話框明確要求「必須用 url_context 真的抓網頁，抓不到要明說」，然後到 Code 分頁確認 `tools: [{ type: "url_context" }]` 真的在 |
| 掛了 `url_context` 還是編 | 文章在 paywall／需登入／被 robots 擋。`url_context_result` 的 `status` 是 `paywall` / `error` / `unsafe`，模型會退回憑印象生成 | 只信 `status == "success"` 的結果。對照組的 `parse_result()` 會回傳 `warning` 欄位；測試改用公開文件 |
| `ModuleNotFoundError: No module named 'uvicorn'` | 用了 `python app.py` / `python3 app.py`。本課一律 uv，沒有全域安裝 | `uv run app.py` |
| `{"detail":"ValueError: No API key was provided. Please pass a valid API key. Learn how to create an API key at https://ai.google.dev/gemini-api/docs/api-key."}`（HTTP 500） | 沒 `export GEMINI_API_KEY`；或部署時忘了 `--set-env-vars`（本機的 export 不會上雲） | 本機：`export GEMINI_API_KEY=...`。雲端：`gcloud run deploy ... --set-env-vars "GEMINI_API_KEY=$GEMINI_API_KEY"`。先打 `/healthz` 看 `has_key` 分辨是哪一邊 |
| `RuntimeError: Cannot send a request, as the client has been closed.` | `genai.Client()` 沒綁變數，鏈式呼叫時 Client 被 GC 關掉 | `with genai.Client() as client:` |
| `AttributeError: 'ModelOutputStep' object has no attribute 'result'` | 直接寫 `s.result` 遍歷 `it.steps`；只有 `url_context_result` 這種 step 有 `result` | `getattr(s, "result", None) or []`，並先用 `s.type` 過濾 |
| `TypeError: 'NoneType' object is not iterable` | `it.steps` 或 `step.result` 是 `None` 就直接 `for ... in` | 一律 `(... or [])` |
| `json.decoder.JSONDecodeError: Expecting value: line 1 column 1 (char 0)` | 只給了 `response_format` 沒給 `response_mime_type="application/json"`，模型吐自由文字 | 兩個一起給 |
| 前端 `TypeError: d.bullets is undefined` | `SCHEMA` 裡沒把該欄位列進 `required`，模型整個省略 | 四個欄位全部進 `required`；後端也 `data.get("x") or []` 兜一層 |
| 手機打開 `*.run.app` 顯示 **403 Forbidden**（自己電腦卻正常） | Cloud Run 服務預設私有，沒加 `--allow-unauthenticated`。自己瀏覽器登著 Google 帳號可能剛好過得去 | `gcloud run deploy ... --allow-unauthenticated`。驗收一律用**別的裝置 ＋ 行動網路** |
| 部署失敗，log 寫 `The user-provided container failed to start and listen on the port defined provided by the PORT=... environment variable` | port 寫死。Cloud Run 用 `$PORT` 告訴容器要聽哪裡 | `port=int(os.environ.get("PORT", 8080))` |
| `gcloud run deploy --source .` 在 build 階段就失敗，說找不到 `requirements.txt` | 目錄裡沒有 Dockerfile，`--source` 退回走 Python buildpacks，而 buildpacks 只認 `requirements.txt` | 用本目錄的 `Dockerfile`（uv sync）。本課不產 `requirements.txt` |
| `ERROR: (gcloud.run.deploy) PERMISSION_DENIED: Cloud Build API has not been used in project ... before or it is disabled` | 第一次部署，API 沒開 | `gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com`（`deploy.sh` 已經幫你做） |
| `ERROR: [Errno 48] error while attempting to bind on address ('0.0.0.0', 8080): address already in use` | 上一次 `uv run app.py &` 還在跑 | `pkill -f app.py`，或換 `PORT=8081 uv run app.py` |
| 深色模式切了，引用區塊 / 卡片還是一塊白 | 生成的 CSS 把顏色寫死（`background:#f5f5f5`），沒進主題變數 | 迭代時明說「顏色要用 CSS 變數，跟著主題切換」 |
| 選「短」跟選「長」一樣慢、一樣多 token | 長度只在前端 `slice()`，模型照樣生 8 條 | 迭代 prompt 加「這個選項要真的改到送給模型的指令，不是前端截斷」 |
| 摘要裡的專有名詞被翻成中文（`url_context` → 「網址上下文」） | system instruction 沒交代術語處理 | 明寫「專有名詞保留英文原文」 |
| `404` / `model not found` | 型號名以投影片為準（基準日 2026-08-25），preview 模型會退役（附錄 D-⑧） | `uv run python -c "from google import genai; c=genai.Client(); print([m.name for m in c.models.list()])"`，並把 model ID 挪到環境變數 |

---

## 完整解答

同目錄下：

| 檔案 | 是什麼 |
|---|---|
| `app.py` | 對照組完整實作。單檔 FastAPI ＋ 一頁 HTML ＋ `--self-check` ＋ `--aha`（帳單試算） |
| `Dockerfile` | Cloud Run 用的映像定義（uv、讀 `$PORT`） |
| `deploy.sh` | 可貼的部署腳本（開 API → deploy → 印網址 → 打 `/healthz`） |
| `PRD.md` / `SPEC.md` | 需求與技術規格；`SPEC.md` 第 3 節有完整的 API 契約與欄位表 |

**再強調一次**：`app.py` 不是「標準答案」。AI Studio Build mode 生成的是 React + TypeScript 專案，檔案數是它的幾十倍，長得完全不一樣，而且**那個才是這個 Lab 的主線產出**。`app.py` 的用途是對照（看清核心只有 20 行）與保底（Build mode 失敗或配額用完時你還有東西能跑）。

---

## 想再往下玩

- **加 `google_search` 當退路**：`url_context` 抓不到時（`status != "success"`），改用 `tools=[{"type":"google_search"}]` 搜這篇文章的標題，用二手資料生摘要，並在畫面上標明「來源為搜尋結果，非原文」。Lab 1 的 `../lab1/ask.py` 有現成的 grounding 寫法。
- **串流版**：把 `summarize()` 改成 `stream=True`，用 SSE 推到前端逐字顯示。事件只有 `interaction.created` / `step.start` / `step.delta` / `step.stop` / `interaction.completed` / `error`——**沒有 `step.complete`**，寫錯不會報錯只會安靜地什麼都不做。
- **Compare 模式選型**（投影片 p77 建議）：把同一篇文章丟給 `gemini-3.7-flash` 和 `gemini-3.1-pro-preview`（型號名以課程投影片為準；`-preview` 結尾的會退役，若 404 用 `client.models.list()` 確認），比摘要品質與延遲，有數據再決定 `MODEL` 要設哪個。
- **接 M3**：拿 Export to Antigravity 過去的專案，讓 agent 補 Build mode 沒做的部分——錯誤處理、retry、測試、把 API key 換成 Secret Manager。這正是 **Lab 3** 的主題（60–90 分）。

---

## 這個 Lab 你真正學到的

- **vibe coding 在生態系裡的位置是「UI 產生器」**：它負責 0→1 的殼，底下打的是跟我手寫完全一樣的 `v1beta/interactions` 端點——沒有另一個更聰明的後端。
- **「工具」是一個 union，不是一個功能**：`url_context` 和「我自己寫的一個 python 函式」在同一份九人名單上，之後的 MCP（M6）／ADK（M7）／A2A（M9）只是換包裝。
- **幻覺不是模型不夠聰明，是輸入是空的**：抓網頁失敗的症狀跟沒掛工具一模一樣，所以「有沒有真的讀到」必須是程式裡的一個欄位（`status == "success"`），不是一種信任。
- **「本機好、雲端壞」只有兩類原因**：環境（env var 沒跟著上雲）與身分（沒 `--allow-unauthenticated`）；而 `/healthz` 這種六行端點是我在雲上唯一還能問話的窗口。
- **serverless 的成本結構跟租機器相反**：付的是請求佔用的秒數而不是月租，所以真正會失控的不是雲端帳單，是那把公開在網路上的 API key 配額。

---

## 清理

雲端資源不清會佔免費額度（Build mode 的免費部署只有前 2 個 app）。

```bash
# 1) 看有哪些服務
gcloud run services list --region us-central1

# 2) 刪掉這個 Lab 建的（Build mode 部署的那個服務名在 AI Studio 的 Deploy 面板看得到）
gcloud run services delete tldr-tw     --region us-central1 --quiet
gcloud run services delete tldr-broken --region us-central1 --quiet   # 步驟 5 故意失敗那個

# 3) 清掉 build 產生的容器映像（不清會佔 Artifact Registry 免費額度）
gcloud artifacts repositories list
gcloud artifacts repositories delete cloud-run-source-deploy \
  --location us-central1 --quiet

# 4) 本機（先收容器再刪 image，順序反了會 conflict: image is being used by running container）
docker rm -f lab2-tldr
docker rmi lab2-tldr
pkill -f app.py
```

> ⚠️ 未實測：以上 gcloud 清理指令。撰寫環境沒有 gcloud（`which gcloud` → not found）；指令依課程附錄 A 的 gcloud 速查表寫成。執行前先用 `gcloud run services list` 確認服務名，`delete` 是不可逆的。
>
> **想留著當作品集**：Cloud Run scale-to-zero，沒人打就幾乎不算錢，可以留。但一定要記得 `--max-instances` 有設、AI Studio Dashboard（<https://aistudio.google.com/rate-limit>）偶爾看一眼用量——公開網址用的是你的 API key 配額。
