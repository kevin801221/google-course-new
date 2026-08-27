# Lab 2 PRD：Build 一個 App 並部署上 Cloud Run

> 模組 M2 Google AI Studio ｜ 投影片第 76 頁 ｜ 40–60 分 ｜ 費用：免費

## 1. 這個 Lab 要解決什麼問題

M1 讓學生會用 SDK 呼叫 Gemini，但呼叫成功 ≠ 有東西可以交給別人用。這個 Lab 走完 vibe coding 的完整循環——**需求 → App → 迭代 → 公開網址**——讓學生親手驗證「一句自然語言在 40 分鐘內變成一個手機打得開的 `*.run.app`」這件事是真的，同時看清 Build mode 生成的程式碼就是 M1 教的那些 `interactions` 呼叫（不是魔法），並在最後把專案匯出給 M3 的 Antigravity 接手工程化。

## 2. 學習目標

做完學生會：

1. **用自然語言在 AI Studio Build mode 生成**一個能跑的 web app，並讀懂它呼叫 Gemini 的那個檔案——認出生成的 TypeScript 和 Lab 1 的 Python 打的是同一個 `interactions` 端點，`tools` 只是換一個 `type`。
2. **用兩種方式迭代**同一個 app：文字指令（改行為）與 annotation 點選（改 UI），分辨兩者各適合什麼。
3. **判斷** LLM 摘要是「真的讀了那篇文章」還是「憑網址編的」，並知道要看 `url_context` 的抓取狀態才算數。
4. **部署** app 到 Cloud Run 拿到公開 HTTPS 網址，並用手機（不同網路、不同裝置）驗證它真的公開；算得出 scale-to-zero 與常駐（`--min-instances 1`）的月費差距，知道留著網址不等於付月租。
5. **診斷** 本機正常但雲端 500 的典型原因（環境變數沒帶上去、Cloud Run 預設私有、`$PORT` 沒讀），並知道換成 Enterprise（IAM）認證只要改環境變數、程式碼不用動。
6. **匯出** 專案到 Antigravity，成為 M3 Lab 的起始輸入。

## 3. 使用者故事

- 身為學生，我想在不寫前端的情況下拿到一個能用的 app，以便先確認「這個產品點子有沒有意思」再決定要不要投入工程。
- 身為學生，我想看懂生成的程式碼裡呼叫 Gemini 的那一段，以便把 M1 的知識和眼前這個 app 對上，而不是把 Build mode 當黑盒。
- 身為學生，我想有一份自己寫的最小對照實作，以便在 Build mode 生成失敗、配額用完、或生成結果太肥看不懂時，仍然知道「這件事的核心其實只有 20 行」。
- 身為學生，我想拿到一個能傳給別人的網址，以便向同事／老闆展示，而不是「你來我電腦看」。
- 身為學生，我想把專案完整帶進 Antigravity，以便 M3 直接接續開發而不用從零重建。

## 4. 功能需求

| 編號 | 需求 | 對應投影片步驟 | 必要／加分 |
|---|---|---|---|
| FR-1 | 進入 Build mode，用一段自然語言需求生成 app（建議題目：技術文章轉繁中摘要器，貼 URL → 重點摘要＋名詞解釋，支援深色模式） | p76 步驟 1 | 必要 |
| FR-2 | 在生成的檔案樹中找到呼叫 Gemini 的檔案，指出 model、system instruction、tools、輸出格式各在哪一行 | p76 步驟 2 | 必要 |
| FR-3 | 文字迭代第一輪：加上摘要長度選項（短／中／長） | p76 步驟 3 | 必要 |
| FR-4 | 文字迭代第二輪：引用原文的句子用 quote 樣式呈現 | p76 步驟 3 | 必要 |
| FR-5 | 用 annotation 工具點選預覽畫面上的元件，改一個 UI 細節（顏色或位置） | p76 步驟 4 | 必要 |
| FR-6 | Deploy to Cloud Run，取得 `*.run.app` 網址，用手機打開驗證 | p76 步驟 5 | 必要 |
| FR-7 | Export to Antigravity，確認對話歷史／檔案／secrets 都帶過去 | p76 步驟 6 | 必要 |
| FR-8 | 跑通對照組最小實作 `app.py`（單檔 FastAPI ＋ 一頁 HTML），對照 Build 版的檔案量與呼叫寫法 | p76 步驟 2 的延伸 | 加分（強烈建議） |
| FR-9 | 用 `deploy.sh` 把對照組實作也推上 Cloud Run，體驗「沒有 Build mode 幫你按按鈕」的版本 | p76 步驟 5 的延伸 | 加分 |
| FR-10 | 摘要結果要能分辨模型是否真的讀到網頁（顯示抓取狀態警告） | 投影片未提，補足 p77「Get code ≠ 生產程式碼」 | 加分 |

## 5. 非功能需求

| 類別 | 要求 |
|---|---|
| 時間盒 | 40–60 分。Build mode 生成 + 兩輪迭代 ≤ 20 分；Cloud Run 首次部署 5–10 分（build 階段慢，正常）；對照組實作 10 分。 |
| 費用上限 | $0。AI Studio 免費層（配額計算量制、每 5 小時刷新）＋ Cloud Run 免費層。Build mode 前 2 個 app 免信用卡部署。 |
| 離線可測 | 對照組 `app.py` 的 URL 檢查與回應解析必須能用 `uv run app.py --self-check` 驗證，不連網、不打 API、不花錢。容器啟動與 `$PORT` 行為可用本機 docker 驗。 |
| 跨平台 | 指令以 macOS／Linux shell 為主；Windows 用 WSL2。Build mode 與 Deploy 全在瀏覽器，無平台差異。 |
| 資安 | 貼進 Build mode 的需求描述與測試網址不得含公司機密／客戶個資（免費層輸入可能用於產品改進，投影片 p66／p77）。 |
| 可觀察性 | 對照組提供 `/healthz`，不打 Gemini 也能區分「容器沒起來」與「key 沒帶上去」。 |

## 6. 驗收標準

對應投影片 p76 的六個步驟，逐項勾：

- [ ] **步驟 1**：Build mode 生成的 app 在右側預覽面板可操作，貼一個真實技術文章 URL 後會吐出繁中摘要。
- [ ] **步驟 2**：能指出生成專案裡呼叫 Gemini 的檔案路徑（通常是 `services/geminiService.ts` 之類），並說出它用的 model 名稱。
- [ ] **步驟 3a**：介面上出現摘要長度選項，選「短」和選「長」的輸出條數明顯不同。
- [ ] **步驟 3b**：引用原文的句子以 quote 樣式（縮排／左側色條／斜體）呈現，和一般段落視覺上分得開。
- [ ] **步驟 4**：透過 annotation 點選改掉的那個元件，在預覽裡看得到差異（顏色或位置變了）。
- [ ] **步驟 5**：拿到 `https://<something>.run.app` 網址；用**手機行動網路**（不是同一個 Wi-Fi）打開，頁面正常載入且功能可用。
- [ ] **步驟 6**：Antigravity 裡看得到這個專案的檔案與 Build mode 的對話歷史。

加分項（對照組）：

```bash
cd lab2
uv run app.py --self-check
# 預期：self-check ok

uv run app.py &                       # 另一個終端機
curl -s localhost:8080/healthz
# 預期：{"ok":true,"has_key":true}     ← has_key 是 false 就是沒 export GEMINI_API_KEY

curl -s -w " [HTTP %{http_code}]\n" -X POST localhost:8080/api/summarize \
  -H 'content-type: application/json' -d '{"url":"file:///etc/passwd"}'
# 預期：{"detail":"請貼 http:// 或 https:// 開頭的完整網址"} [HTTP 400]
```

## 7. 範圍外

- **不做前端框架教學**。生成的是 React 專案，但這個 Lab 不教 React；讀不懂 `.tsx` 不影響驗收。
- **不做 Android app 生成**（投影片 p70 有提，是 I/O 2026 新功能）。想玩自己去，不列驗收。
- **不做自訂網域、CI/CD、Firebase 後端綁定**。Cloud Run 拿到 `*.run.app` 就結束。
- **不做 Secret Manager**。對照組的 API key 直接走 `--set-env-vars`，正式做法是 M5 的題目。
- **不做 Enterprise／Vertex 路線的部署**（`GOOGLE_GENAI_USE_ENTERPRISE`）。M2 只認 Developer API key，兩條路線的選型見投影片 p73–75、實作在 M5。
- **不追求對照組實作和 Build 版功能對等**。對照組是「最少要寫什麼」的示範，不是 Build 版的重寫。

## 8. 費用與風險

| 項目 | 費用 | 說明 |
|---|---|---|
| AI Studio Build mode | 免費 | 免費層配額以計算量計、每 5 小時刷新 |
| Cloud Run（Build mode 一鍵部署） | 免費 | 前 2 個 app 免信用卡部署（投影片 p66／p71） |
| Cloud Run（自己 `gcloud run deploy`） | 約 $0 | 走 Cloud Run 免費層，scale-to-zero，沒人打就不算錢；但**需要一個已綁帳單的 GCP 專案**（M5 才設，所以 FR-9 是加分項） |
| Gemini API 呼叫（部署後的 app） | 免費層 | ⚠️ 用的是**你自己的 key 配額**（投影片 p77）。網址公開分享 = 別人幫你燒配額 |

風險與對策：

- **配額被燒**：`deploy.sh` 預設 `--max-instances 3` 當保險絲；分享網址前先在 AI Studio Dashboard（<https://aistudio.google.com/rate-limit>）看用量，付費層記得設 spend cap。
- **資料外洩**：免費層輸入可能用於產品改進。測試只用公開技術文章網址，不要貼內網連結或含 token 的 URL。
- **preview 模型退役**：`gemini-3.7-flash` 這類型號名以課程投影片為準（基準日 2026-08-25）。若 404 用 `client.models.list()` 確認，並把 model ID 放設定檔而不是寫死（投影片 p77、附錄 D-⑧）。

**清理指令**（做完不想留東西）：

```bash
# Build mode 部署的服務：在 AI Studio 的 Deploy 面板刪，或用 gcloud
gcloud run services list --region us-central1
gcloud run services delete tldr-tw --region us-central1 --quiet

# 順手清掉 build 產生的容器映像（不清會佔 Artifact Registry 免費額度）
gcloud artifacts repositories list
gcloud artifacts repositories delete cloud-run-source-deploy \
  --location us-central1 --quiet
```

## 9. 前置依賴

| 依賴 | 必要性 | 從哪來 |
|---|---|---|
| Google 帳號 | 必要 | 登入 <https://aistudio.google.com> |
| `GEMINI_API_KEY` | 對照組必要 | Lab 1 已經建過；沒有就到 <https://aistudio.google.com/apikey> 建。Build mode 本身**不需要**你手動給 key（secrets 平台代管，投影片 p68） |
| Lab 1 完成 | 建議 | 步驟 2 要「對照 M1 學過的 interactions 呼叫」，沒做過 Lab 1 會看不出差別 |
| `uv` | 對照組必要 | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| `gcloud` ＋ 已綁帳單的 GCP 專案 | 僅 FR-9 需要 | M5 才正式設定。只做必要項的話完全不需要 gcloud |
| Antigravity 桌面版 | 步驟 6 需要 | <https://antigravity.google/download>（M3 的主角，這裡只要裝好能開） |
