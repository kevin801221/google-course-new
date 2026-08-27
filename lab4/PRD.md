# Lab 4 PRD：課程知識庫 × Agent 查詢

## 1. 這個 Lab 要解決什麼問題

Antigravity 的 agent 很懂程式碼，但完全不懂「你團隊的決策脈絡、內部文件、這門課教過什麼」——問它 `thinking_level` 是什麼，它會用訓練資料裡的印象瞎編。這個 Lab 把 NotebookLM（2026/07 起官方名稱 Gemini Notebook）當成一個**人工策展、來源接地**的長期記憶，再用 MCP 把它接回 Antigravity，讓 agent 每次回答都能引用你餵進去的官方文件。這是「不用自己架向量庫的 RAG」，也是 M11 Capstone「個人 LLM Wiki」的第一塊拼圖。

## 2. 學習目標

做完學生會：

1. **策展**一個單一主題的 NotebookLM 筆記本，判斷回答是否真的接地（有無行內引用），並說得出 NotebookLM 在 grounding 三種形態（Lab 1 `google_search`／本 Lab NotebookLM／Lab 8 pgvector）裡的座標與代價。
2. **產出** Studio 格式：一集指定主題的 Audio Overview。
3. **安裝並登入**社群工具 `notebooklm-mcp-cli`，用 `nlm` CLI 先驗證功能再接 agent，並看出 stdio MCP server 只是被 fork 出來的子程序（`command` 就是 `subprocess.run` 的第一個參數）。
4. **設定** Antigravity 的 `mcp_config.json`，用 `disabledTools` 擋掉破壞性工具，並說出它擋得住誰、擋不住誰（客戶端自律，不是伺服器權限）。
5. **驗證**整合成功：讓 agent 查知識庫並附引用，且能說出這條路徑為什麼會失效（非官方 API、cookie session 過期）。

## 3. 使用者故事

- 身為學生，我想有一個「只根據我給的官方文件回答」的問答入口，以便不用再分辨 chatbot 講的是 2024 年的舊 API 還是現在的寫法。
- 身為學生，我想讓 Antigravity 寫碼時能查我的課程知識庫，以便它產生的程式碼引用的是 Interactions API 而不是 `generateContent`。
- 身為學生，我想知道 agent 的 MCP 權限怎麼收斂，以便 agent 誤操作時不會刪掉我累積三個月的筆記本。
- 身為學生，我想通勤時複習 MCP 概念，以便不用另外找時間看文件。

## 4. 功能需求

| 編號 | 需求 | 對應投影片步驟 | 必要／加分 |
|---|---|---|---|
| FR-1 | 建立筆記本「Google AI Agent 課程」，加入 4 個 URL 來源：`ai.google.dev/gemini-api/docs`、`adk.dev`、`antigravity.google/docs`、`modelcontextprotocol.io` | p.193 步驟 1 | 必要 |
| FR-2 | 確認 4 個來源都 embed 完成（來源清單無 processing／failed 狀態）後才開始問答 | p.193 步驟 1（投影片沒寫，但不做會踩坑） | 必要 |
| FR-3 | 網頁版試問三題，其中一題為「Interactions API 與 generateContent 的差異」，回答必須帶行內引用 | p.193 步驟 2 | 必要 |
| FR-4 | 生成一集 Audio Overview，主題設為「給初學者的 MCP 介紹」 | p.193 步驟 3 | 必要 |
| FR-5 | `uv tool install notebooklm-mcp-cli` 並 `nlm login`，用 `nlm notebook list` / `nlm query` 驗證 CLI 可用 | p.193 步驟 4 | 必要 |
| FR-6 | 寫 `~/.gemini/config/mcp_config.json`，註冊 `notebooklm` server 且 `disabledTools` 至少含 `notebook_delete`、`source_delete`，存檔後 Settings → MCP Servers → Refresh | p.193 步驟 5、p.186 | 必要 |
| FR-7 | 提供 `wiki.py check` 離線檢查設定檔：JSON 是否可解、有無 notebooklm server、`serverUrl` 欄位名是否寫錯、破壞性工具是否已禁、`notebooklm-mcp` 是否在 PATH 上 | 投影片沒有（補的驗收工具） | 必要 |
| FR-8 | 在 Antigravity 用 prompt「查課程知識庫，總結 ADK 部署的三種方式，附引用」，回答需含引用 | p.193 步驟 6 | 必要 |
| FR-9 | 提供 `wiki.py ask` 走同一條 `nlm` 路徑做非互動式驗收：沒有任何引用連結就 exit 1 | 投影片沒有（補的驗收工具） | 必要 |
| FR-10 | 另建一本自己的舊筆記／部落格筆記本，體驗跨筆記本查詢 | p.193 步驟 7 | 加分 |
| FR-11 | 生成 Mind Map 或 Flashcards＋Quiz，當本課複習教材 | p.175 | 加分 |

## 5. 非功能需求

| 項目 | 要求 |
|---|---|
| 時間盒 | 45–60 分鐘（投影片 p.193）。其中來源 embed 與 Audio Overview 生成是等待時間，交錯進行：送出 Audio Overview 後去裝 CLI。 |
| 費用上限 | **$0**。NotebookLM 免費層：100 筆記本／每本 50 來源／每日 50 次對話＋3 個音訊（p.177）。本 Lab 用掉 4 個來源、約 6 次對話、1 個音訊。 |
| 離線可測 | `wiki.py --self-check`、`wiki.py check <file>` 完全不連網、不需要登入。JSON 解析、設定檔規則、引用抽取、來源狀態掃描都在離線測試範圍。 |
| 跨平台 | 指令以 macOS／Linux shell 為主；Windows 用 WSL2。設定檔路徑 `~/.gemini/config/mcp_config.json` 由 `pathlib.Path.home()` 組出，不寫死斜線。 |
| 安全 | `nlm login` 產生的 session 檔等同你的 NotebookLM 完整權限（p.188）。不進 repo、不在共用機器登入、不貼進 prompt。 |
| 穩定性 | 這條路徑走的是非官方 API（瀏覽器 cookie 模擬），NotebookLM 改版可能整條失效。教學／個人生產力可以用，正式產品不要依賴。 |

## 6. 驗收標準

- [ ] 筆記本「Google AI Agent 課程」存在，且來源數 = 4（`uv run wiki.py sources` 顯示 `未就緒 0 筆`；前面的行數含 `nlm` 的表頭，不等於來源數）
- [ ] 網頁版三題都答得出來，且每題答案句尾有可點的行內引用編號
- [ ] 問一題**來源裡沒有的**問題，它回「來源中找不到」而不是瞎編（這才證明它是 source-grounded）
- [ ] Audio Overview 生成完成，主題是「給初學者的 MCP 介紹」，可播放
- [ ] `nlm notebook list` 列得出你的筆記本
- [ ] `uv run wiki.py check` 對 `~/.gemini/config/mcp_config.json` 回 exit 0，且沒有 `[WARN] disabledTools 少了...`
- [ ] Antigravity Settings → MCP Servers 顯示 `notebooklm` 為已連線，工具清單裡**看不到** `notebook_delete` / `source_delete`
- [ ] Antigravity agent 用 prompt「查課程知識庫，總結 ADK 部署的三種方式，附引用」答得出三種方式且附連結
- [ ] `uv run wiki.py ask "ADK 部署的三種方式？"` exit 0（有引用）
- [ ] `uv run wiki.py --self-check` 印出 `self-check 全過`

可執行的驗收指令：

```bash
cd /Users/awesomeartengineer01/Antigravity-teach/lab4
uv run wiki.py --self-check                       # 離線邏輯
uv run wiki.py check                              # 檢查全域 mcp_config.json
export NLM_NOTEBOOK_ID=<你的筆記本 id>
uv run wiki.py sources                            # 來源都 embed 好了嗎
uv run wiki.py ask "ADK 部署的三種方式？"           # 有引用才 exit 0
```

## 7. 範圍外

- **不碰 Enterprise API**。Discovery Engine v1alpha 的 `notebooks` REST API（p.181）需要 GCP 專案與 `gcloud auth print-access-token`，企業場景才走那條；本 Lab 只走 p.183 的 MCP 方案。
- **不自建 MCP server**。這裡是「用別人寫好的 MCP server」；自己寫 server 是 M6／Lab 6。
- **不自建向量庫**。切塊、嵌入、檢索全由 NotebookLM 代勞；pgvector 自建 RAG 是 M8／Lab 8。
- **不從 ADK agent 接**（`McpToolset`）。同一個知識庫給 ADK agent 消費是 M7 的事，這裡只接 Antigravity IDE。
- **不做 studio 產物的自動化下載／發佈**。`download_artifact` 串成內容產線是 Lab 4.5。
- **不做 `nlm` 的 profile 多帳號切換**。單一 Google 帳號夠用。

## 8. 費用與風險

**費用：$0。** NotebookLM 免費層（100 筆記本／50 來源／每日 50 次對話＋3 音訊）遠超本 Lab 需求。`notebooklm-mcp-cli` 是開源工具，不收費。這個 Lab 不需要 Gemini API key、不需要 GCP 專案、不需要綁卡。

**要清的雲端資源：沒有。** 沒有部署任何服務、沒有開任何 GCP 資源。要清的是**本機憑證與設定**：

```bash
# 登出（撤掉本機 session 檔）
nlm logout

# 不想留這個工具
uv tool uninstall notebooklm-mcp-cli

# 從 Antigravity 移掉這個 server：編輯 ~/.gemini/config/mcp_config.json
# 刪掉 "notebooklm" 那個區塊，存檔後 Settings → MCP Servers → Refresh

# 確認沒有殘留的 session 檔（路徑依工具版本而異，先看一眼再刪）
ls -la ~/.notebooklm* ~/.config/nlm 2>/dev/null
```

**風險：**

| 風險 | 影響 | 對策 |
|---|---|---|
| 非官方 API（瀏覽器 cookie 模擬內部 API） | NotebookLM 改版可能讓整條路徑失效 | 個人生產力工具可以接受；正式產品走 Enterprise 官方 API＋自建 MCP（M6） |
| session 檔＝完整帳號權限 | 洩漏等同交出 NotebookLM 帳號 | 不進 repo、`.gitignore` 掉、不在共用機器登入 |
| session 效期約 2–4 週 | 過期後 agent 的查詢會安靜失敗或空回應 | 重跑 `nlm login`；`wiki.py ask` 會把空輸出報成 exit 1 而不是假裝成功 |
| agent 誤呼叫刪除類工具 | 筆記本／來源被刪掉，且沒有回收桶保證 | `disabledTools` 先禁 `notebook_delete`、`source_delete`（`wiki.py check` 會強制檢查） |
| prompt injection 從來源進來 | 餵進去的網頁若含惡意指令，agent 可能照做 | 只餵信得過的官方文件；權限最小化（附錄 D ⑩） |
| 免費層輸入可能用於產品改進 | 公司機密不該進個人版 | 公司資料走 NotebookLM Enterprise（附錄 D ⑨） |

## 9. 前置依賴

| 依賴 | 從哪來 | 沒有會怎樣 |
|---|---|---|
| Google 帳號 | 免費 | 連 notebook.google.com 都進不去 |
| Antigravity 桌面版已安裝並登入 | **Lab 3**（`antigravity.google/download`） | 步驟 5、6 完全做不了 |
| 「MCP server 怎麼設定」的概念 | **Lab 3**（M3 的 MCP 章節）、附錄 B 的 `mcp_config.json` 完整範本 | 會把 `serverUrl` 寫成 `url`、會忘記 Refresh |
| `uv` 已安裝 | M0 環境準備 | `uv tool install` 沒得跑 |
| Node.js 20+ | M0 環境準備 | 本 Lab 用不到，但同一份 `mcp_config.json` 裡的 `npx` 型 server 需要 |
| Gemini API key | **不需要**。本 Lab 完全不打 Gemini API | — |
| GCP 專案 | **不需要**（只有 Enterprise 路線才要，本 Lab 範圍外） | — |

**這個知識庫會被後面直接沿用，不要做完就刪：**

- **Lab 4.5**（NotebookLM 自動內容產線 → YouTube）：同一本筆記本、同一套 `nlm` 工具，加上 `research_start` 與 `studio_create` / `download_artifact` 串成日報產線。
- **M7 / Lab 7**：同一個 MCP server 換一個消費端——ADK agent 用 `McpToolset(connection_params=...)` 接進來（注意不是 2025 年的 `MCPToolset.from_server()`，附錄 C）。
- **M11 Capstone（個人 LLM Wiki 生態系）**：**這本筆記本就是 Capstone 的 wiki 後端，原樣沿用。** Capstone 的 research agent 每週把新的官方 blog 掃進來當來源（p.466），Antigravity 與 ADK agent 兩邊都查同一本。所以這個 Lab 的策展品質（一本一主題、來源去蕪存菁）會直接決定 Capstone 的回答品質——現在偷懶亂餵來源，兩個月後在 Capstone 收帳。
