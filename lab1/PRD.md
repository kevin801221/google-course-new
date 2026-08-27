# Lab 1 PRD：會查資料的 CLI 問答工具

> 模組 M1「Gemini 模型家族與 Gemini API」｜投影片第 56 頁（LAB）＋第 57 頁（參考解法）
> 型號名以課程投影片為準（`gemini-3.7-flash`）；若 404 請用 `client.models.list()` 確認。

## 1. 這個 Lab 要解決什麼問題

LLM 的訓練資料有截止日，問它「2026 年最新的 Gemini 模型是哪個」它會用很自信的語氣講錯 —— 這是幻覺最典型的形狀。這個 Lab 用一支不到 100 行的 CLI 工具，把「模型 + 內建工具 + 引用來源」這條最短的接地（grounding）鍊路走完一遍：學生會親眼看到同一個問題在掛上 `google_search` 前後答案完全不同，並學會從 `steps` / SSE 事件裡把「模型到底做了什麼」挖出來。這條鍊路後面每個模組（ADK 的 tools、MCP 的 server、RAG 的檢索）都是它的放大版。

## 2. 學習目標

做完學生會：

1. **呼叫** `client.interactions.create()` 完成一次文字問答，並解釋 `interaction.steps` 的型別化結構（`user_input` / `thought` / `google_search_call` / `model_output`）。
2. **掛上**內建工具 `tools=[{"type": "google_search"}]`，並用同一個問題證明 grounding 前後的答案差異。
3. **消費** `stream=True` 的 SSE 事件流，說得出七種 `event_type` 各自身上有什麼欄位（以及投影片寫的 `step.complete` 為什麼不存在），並指出這個 `for ev in stream:` 迴圈就是 agent 迴圈的最小版。
4. **抽取** `url_citation` annotation，從兩個來源（`step.delta` 的 `text_annotation_delta` ＋ `interaction.completed` 的 `steps`）撈出來源並去重。
5. **鎖定**輸出格式：用 `response_format` + JSON Schema 讓答案變成別的程式吃得下去的 `{answer, sources[], confidence}`，並說得出 schema 保證的是形狀不是內容為真（`sources` 是模型填的，annotation 才是 API 標的）。
6. **定位** `tools=` 這個參數在課程主線上的位置：`ToolParam` 是九選一的 union，`google_search` / 自訂 `function` / `mcp_server` 是兄弟，同一個「工具」概念在 Lab 6（MCP）、Lab 7（ADK tool）、Lab 9（A2A skill）換包裝。

## 3. 使用者故事

| # | 故事 |
|---|---|
| US-1 | 身為學生，我想在終端機打一句話就問到**今天**的答案，以便不必開瀏覽器查 Google 再自己讀十個分頁。 |
| US-2 | 身為學生，我想看到答案逐字出現，以便知道程式沒有掛掉（搜尋＋生成常常超過 10 秒）。 |
| US-3 | 身為學生，我想看到答案的引用連結，以便自己驗證模型有沒有在編。 |
| US-4 | 身為學生，我想用 `--json` 拿到結構化結果，以便把這支工具接進別的腳本。 |
| US-5 | 身為講師，我想有一個不連網、不花錢的檢查，以便在沒有 API key 的教室裡也能驗證學生的事件處理邏輯寫對了。 |

## 4. 功能需求

| 編號 | 需求 | 對應投影片步驟 | 必要 / 加分 |
|---|---|---|---|
| FR-1 | `uv init --bare` 建專案、`uv add google-genai`、`GEMINI_API_KEY` 走環境變數不硬編碼 | 步驟 1 | 必要 |
| FR-2 | `ask.py` 從 `sys.argv` 收問題，呼叫 `interactions.create()` 印出 `output_text` | 步驟 2 | 必要 |
| FR-3 | 掛 `tools=[{"type": "google_search"}]`，答案內容改為以搜尋結果為準 | 步驟 3 | 必要 |
| FR-4 | `stream=True`，`step.delta` 且 `delta.type == "text"` 時逐字 `print(..., flush=True)` | 步驟 3 | 必要 |
| FR-5 | 偵測 `step.start` 且 `step.type == "google_search_call"`，在 stderr 印搜尋提示 | 步驟 3（延伸） | 加分 |
| FR-6 | 結尾列出 `url_citation` 的標題與網址，去重且保留原順序 | 步驟 4 | 必要 |
| FR-7 | `--json` 模式：`response_format` + `response_mime_type="application/json"`，輸出 `{answer, sources[], confidence}` | 步驟 5 | 加分 |
| FR-8 | `--self-check`：用 `SimpleNamespace` 假事件驗 `render()`，不連網不花錢 | （投影片沒有，教學需要補上） | 必要 |
| FR-10 | `--aha`：離線印出事件流 roll call ＋「有無 `tools=`」的並排對照表（來源 0 → 2），不連網不花錢 | （補上，教學用） | 加分 |
| FR-9 | 非 tty 時自動關掉 ANSI 色碼（`sys.stdout.isatty()`），讓 `\| json.tool` 這種 pipe 不會壞掉 | （補上） | 必要 |

## 5. 非功能需求

| 類別 | 要求 |
|---|---|
| 時間盒 | 30–45 分鐘（投影片標示），含拿 API key |
| 費用上限 | $0。免費層即可完成；Search Grounding 每月 5,000 次查詢免費，本 Lab 全程約 10 次以內 |
| 離線可測 | `--self-check` 不打網路、不需要 key；事件處理與去重邏輯全靠它把關 |
| 跨平台 | macOS / Linux shell 為主。Windows 建議 WSL2（`export` 語法不同） |
| 依賴 | 只有 `google-genai`（投影片下限 `>=2.3.0`；本專案 `pyproject.toml` 寫 `>=2.20.0`，即實測版本）。其餘一律 stdlib，不裝 `rich` |
| 可維護 | model ID 放模組常數 `MODEL`（投影片明講：模型退役是常態，Gemini 3 Pro preview 只活 4 個月） |

## 6. 驗收標準

對應投影片第 56 頁步驟 6「問三個 2026 年的時事問題，答案須帶正確來源連結」。

```bash
cd /Users/awesomeartengineer01/Antigravity-teach/lab1

# 0) 離線檢查（不需要 key，這條一定要先過）
uv run ask.py --self-check
# 預期最後一行：self-check ok

# 1) 三個時事問題
uv run ask.py "2026 年 Google I/O 發表了什麼 AI 產品？"
uv run ask.py "現在 Gemini API 的免費額度是多少？"
uv run ask.py "Nano Banana 2 是什麼？"

# 2) 加分題
uv run ask.py --json "2026 年 Gemini 3 系列有哪些型號？" | uv run python -m json.tool
```

- [ ] `uv run ask.py --self-check` 印出 `self-check ok`，exit code 0
- [ ] 三題都在答案前先出現 `🔍 搜尋中…`（證明真的觸發了 `google_search_call` step）
- [ ] 三題的答案都是 2026 年的資訊，不是舊訓練資料
- [ ] 三題結尾都列出至少一個來源，連結點得開且內容與答案相關
- [ ] 答案是逐字出現的（不是等 10 秒後一次噴出來）
- [ ] `--json` 輸出能被 `python -m json.tool` parse，`answer` / `sources` / `confidence` 三個 key 都在，`confidence` 落在 0~1
- [ ] 拿掉 `tools=` 再問同一題，答案會變錯 —— 學生能說出為什麼

## 7. 範圍外

- **不做多輪對話**。`previous_interaction_id` 是投影片第 33 頁的內容，這個 Lab 一次一問，不維護 session。
- **不做多模態**。不餵圖、不生圖（`ImageContent` 那組坑留給 M1 的其他範例與 Lab 3）。
- **不做 function calling 迴圈**。這裡只用內建工具 `google_search`，自訂函式的宣告→執行→回傳留給 M7 的 ADK。
- **不做 streaming JSON**。JSON 模式故意不串流：JSON 片段中途不是合法 JSON，`json.loads` 會炸。這是「想再往下玩」的題目。
- **不做重試 / rate limit 退避**。撞到 429 就等 5 小時配額刷新或升 Tier 1，不在這支 30 行工具裡寫 backoff。
- **不部署**。上雲是 M10 的事。

## 8. 費用與風險

| 項目 | 數字（M1 第 22 頁定價表；帳號與費用總覽見 M0 第 12 頁） | 說明 |
|---|---|---|
| `gemini-3.7-flash` | 輸入 $0.75 / 1M tokens、輸出 $3.75 / 1M（促銷價至 2026/12/31） | 本 Lab 問十題大約幾千 tokens，實際費用 < $0.01 |
| Search Grounding | 每月 5,000 次查詢免費，之後 $14 / 千次 | Gemini 3 按「實際執行的查詢」計費，一次提問可能觸發多次查詢 |
| 免費層 | 綁 Google 帳號即可，不用信用卡；配額每 5 小時刷新 | 額度看 <https://aistudio.google.com/rate-limit> |

風險與對策：

- **API key 洩漏**＝別人花你的配額。走 `export`，不要硬編碼、不要 commit。正式環境改用 Secret Manager（M5）。
- **免費層的輸入可能用於產品改進**（僅存 1 天；付費層保存 55 天且不用於訓練）。不要拿公司機密資料當測試問題 —— 這是投影片附錄 D 十大坑的第 ⑨ 條。
- **模型退役是常態**。`MODEL = "gemini-3.7-flash"` 一旦 404，改常數或改用別名 `gemini-flash-latest`。

清理：**這個 Lab 沒有任何雲端資源要刪**（沒建 GCP 專案、沒開服務、沒上傳檔案）。要收乾淨只有兩件事：

```bash
unset GEMINI_API_KEY                      # 清掉當前 shell 的 key
# 不再用這把 key → aistudio.google.com/apikey 頁面上 Delete
rm -rf /Users/awesomeartengineer01/Antigravity-teach/lab1/.venv   # 只是本機環境，隨時 uv run 會重建
```

## 9. 前置依賴

| 依賴 | 從哪來 | 卡住的話 |
|---|---|---|
| Python 3.10+（建議 3.13） | 本專案 `pyproject.toml` 要求 `>=3.13` | `uv python install 3.13` |
| `uv` | M0 環境準備：`curl -LsSf https://astral.sh/uv/install.sh \| sh` | 全課一律 uv，不用 pip / venv |
| Google 帳號 | 免費，不需信用卡 | — |
| `GEMINI_API_KEY` | <https://aistudio.google.com/apikey>（M0 checklist 第 4 項） | `echo $GEMINI_API_KEY` 沒東西就是沒 export |
| 前一個 Lab | **無**。這是全課第一個 Lab | — |

後續依賴這個 Lab 的：M2（AI Studio 用同一把 key）、M7（ADK 的 `google_search` 是同一個內建工具，但有「不能與其他工具同掛」的額外限制）。
