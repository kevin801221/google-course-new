# Lab 9 PRD：跨服務 Agent 協作（A2A）

> 所屬模組：M9 A2A：Agent2Agent Protocol ｜ LAB 投影片：第 387 頁 ｜ 60–90 分 ｜ 免費層

## 1. 這個 Lab 要解決什麼問題

到 Lab 8 為止，所有 agent 都住在同一個 Python 行程裡：`sub_agents=[...]` 一掛就通，因為它們共用記憶體。但現實中訂房服務是別的團隊寫的、部署節奏不同、流量是你的十倍，甚至用 LangGraph 寫的——你拿不到它的 Python 物件，只拿到一個網址。這個 Lab 把 Lab 8 的 `hotel_agent` 拆成一個獨立行程的 A2A 服務（`to_a2a`），再用另一個獨立專案的 `RemoteA2aAgent` 去消費它，讓學生親眼確認：**跨行程之後，`sub_agents` 的寫法一個字都不用改**。這正是 Lab 10 要把服務 B 搬上 Cloud Run 的前一步——同一條鏈，先在本機跑通，上雲只換 URL 與憑證。

## 2. 學習目標

1. **曝露**一個 ADK agent 成標準 A2A 服務，並讀懂 `to_a2a()` 自動生成的 agent card 每個欄位是從哪來的——包括哪些內部細節（`description`、工具 docstring）會被抄進這份公開契約、哪些（`instruction`、實作、假資料）不會。
2. **消費**遠端 agent：用 `RemoteA2aAgent` 當 sub-agent，說明它與本地 sub-agent 在程式碼上的差異（只有一行）、在耦合面積上的差異（一個數量級級別的數字，`--aha` 量得出來）與在失敗模式上的差異（一整張表）。
3. **診斷** A2A 連線失敗：分辨「服務沒起來」「port 不一致」「origin 不一致」「相依沒裝」四種症狀各自的錯誤訊息原文。
4. **觀察** Task 狀態機：讓遠端查詢變慢，指出 `WORKING` 進度是否真的串流回來，以及決定它的是名片上哪一個欄位。
5. **判斷**什麼時候該用 A2A、什麼時候本地 `sub_agents` 就夠（對應投影片 386 的選型表）。

## 3. 使用者故事

- 身為學生，我想**把 Lab 8 的訂房 agent 變成一個獨立服務**，以便別的團隊（和下一個 Lab 的雲端版）不用複製我的程式碼就能用它。
- 身為學生，我想**在不改 root agent 架構的前提下換掉 sub-agent 的位置（本地 → 遠端）**，以便驗證「協定抹平網路邊界」不是口號。
- 身為學生，我想**在沒有 API key 也沒有網路的情況下驗證整條 A2A 鏈**，以便我在飛機上也能確認是我的程式壞了還是模型壞了。
- 身為學生，我想**看到每一種連線失敗的真實錯誤訊息**，以便上雲之後 debug 不用從零猜。

## 4. 功能需求

| 編號 | 需求 | 對應投影片步驟 | 必要/加分 |
|---|---|---|---|
| FR-1 | `hotel_service/agent.py`：ADK `hotel_agent`（含 `search_hotels` 工具），模組頂層 `a2a_app = to_a2a(root_agent, port=8001)` | 387 步驟 1 | 必要 |
| FR-2 | 可用 `uv run uvicorn hotel_service.agent:a2a_app --port 8001` 啟動，`/.well-known/agent-card.json` 回 200 | 387 步驟 2 | 必要 |
| FR-3 | `check_card.py`：抓名片、列 skills，並**先跑一遍 ADK 的 origin 檢查**，不通就退非零 exit code | 387 步驟 2（curl 名片確認 skills）強化 | 必要 |
| FR-4 | `concierge/agent.py`：獨立 ADK 專案入口，`RemoteA2aAgent` 指向 `:8001` 名片並掛成 `sub_agents` | 387 步驟 3 | 必要 |
| FR-5 | `uv run adk web` 跑 concierge，問「東京 3000 內的旅館」，Events 面板看得到跨服務委派 | 387 步驟 4 | 必要 |
| FR-6 | `HOTEL_SLOW_SECONDS` 讓 `search_hotels` 變慢，觀察 task 停在 `WORKING` | 387 步驟 5 | 必要 |
| FR-7 | `A2A_STREAMING=1` 換成宣告 `capabilities.streaming=true` 的自訂名片（自動名片是 `false`，FR-6 才看得到串流） | 387 步驟 5 的實作前提 | 必要 |
| FR-8 | `smoke_test.py`：用純 a2a-sdk 寫的**假**訂房服務跑完整條 A2A 鏈，assert 罐頭答案回來，不連網不花錢 | 387 步驟 4 的離線版 ＋ 投影片 376–378 的 a2a-sdk server 骨架 | 必要 |
| FR-9 | 每支程式有 `--self-check`（assert，不連網） | BRIEF 規範 | 必要 |
| FR-9b | `hotel_service/agent.py --aha`：離線印出「本地 sub-agent vs A2A 遠端」的耦合面積對照（模組數／原始碼 MB／名片 bytes／倍數）與「名片會外流哪些內部細節」，服務不用起來 | 387 步驟 3 的洞見層 | 必要 |
| FR-10 | 第三個非 ADK agent（如匯率）證明跨框架互通 | 387 步驟 6 加分題 | 加分 |
| FR-11 | 把服務 B 換成 Lab 8 的 Supabase／MCP Toolbox 真資料 | 387 步驟 1 的原始意圖 | 加分 |

## 5. 非功能需求

| 項目 | 要求 |
|---|---|
| 時間盒 | 60–90 分。步驟 1–4 是主線（約 45 分），步驟 5–6 是延伸。 |
| 費用上限 | $0。唯一的 token 消耗是步驟 4／5 的幾輪對話（`gemini-3.7-flash`，免費層額度內）。沒有任何雲端資源。 |
| 離線可測 | `--self-check`（4 支）與 `smoke_test.py` 完整流程**不需要 API key、不需要網路**。學生沒 key 也能完成 60% 的驗收。 |
| 跨平台 | 指令以 macOS／Linux shell 為主。Windows 用 WSL2。需要兩個終端機分頁（服務 B 與服務 A 各一）。 |
| 相依 | `uv add "google-adk[a2a]" "a2a-sdk[http-server]"`。**兩個 extra 都要**，少任一個都在不同時機炸（見 walkthrough 步驟 1）。 |
| Port 佔用 | 8000 給 `adk web`、8001 給服務 B、8099 給 smoke test 的假服務。三個都可改。 |

## 6. 驗收標準

主線（不需要 API key）：

- [ ] `uv run hotel_service/agent.py --self-check` → `self-check ok`
- [ ] `uv run concierge/agent.py --self-check` → `self-check ok`
- [ ] `uv run check_card.py --self-check` → `self-check ok`
- [ ] `uv run smoke_test.py --self-check` → `self-check ok`
- [ ] `uv run smoke_test.py` → 最後一行 `smoke ok（3 個 event，罐頭答案有回來）`
- [ ] 服務 B 起來後 `uv run check_card.py` → 最後一行 `✓ 名片可用`，`echo $?` 是 `0`
- [ ] `uv run check_card.py http://127.0.0.1:8001` → `✗ origin 不一致…`，`echo $?` 是 `1`（**故意要失敗的那條**）
- [ ] `curl -s http://localhost:8001/.well-known/agent-card.json | grep -c search_hotels` → `1`

需要 API key（對應 LAB 頁步驟 4、5）：

- [ ] `uv run adk web` 選 concierge，問「東京 3000 以內的旅館」，回答裡出現 `淺草和風旅館` 與 `2400`
- [ ] Events 面板看得到 `hotel_agent` 這個 sub-agent 的事件（不是 concierge 自己編的）
- [ ] 服務 B 的終端機看得到一筆 `POST / HTTP/1.1 200 OK`（證明真的跨行程了）
- [ ] `HOTEL_SLOW_SECONDS=6` 重啟服務 B 後，同一個問題會等約 6 秒才回答
- [ ] 你能說出「把 `RemoteA2aAgent` 的 `agent_card` 改成 `http://127.0.0.1:8001/...` 會噴什麼」，而且真的試過

## 7. 範圍外

- **不做認證**。本機 loopback 走 http、無 token。OAuth2／API key／Cloud Run IAM ID token 是 M10 的內容（投影片 381 第 4 點）。
- **不做持久化 task store**。`to_a2a` 預設 `InMemoryTaskStore`，重啟服務 B 就忘光。換 `DatabaseTaskStore` 是生產議題。
- **不做 push notification webhook**。長任務斷線重連（`SubscribeToTask`）只在 SPEC 提一句。
- **不做 gRPC／REST binding**。只用 JSON-RPC（`to_a2a` 掛的就是它）。
- **不做部署**。服務 B 上 Cloud Run 是 Lab 10。
- **不重寫 Lab 8 的 RAG**。`search_hotels` 用寫死的假資料，換成 Lab 8 的 MCP Toolbox 是加分題 FR-11。
- **不做 `INPUT_REQUIRED` 反問流程**。這是 A2A 與工具的本質差異（投影片 371），但實作要 HITL 迴圈，留給 Capstone。

## 8. 費用與風險

**費用：$0。**

| 項目 | 費用 |
|---|---|
| `gemini-3.7-flash` 對話（步驟 4、5，約 10–20 輪） | 免費層額度內。付費層報價 $0.75/1M 輸入 tokens（抄投影片第 12 頁「帳號與費用總覽」），這輪連 $0.01 都到不了 |
| A2A 協定本身 | 開放標準，$0 |
| 雲端資源 | **完全沒有**。沒建 GCP 專案、沒開服務、沒上傳檔案 |

**風險**

| 風險 | 說明 | 對策 |
|---|---|---|
| ADK 的 A2A 實作標記 EXPERIMENTAL | 匯入就噴 `UserWarning: [EXPERIMENTAL] ...`，API 可能 breaking change | 設 `ADK_SUPPRESS_A2A_EXPERIMENTAL_FEATURE_WARNINGS=1` 消音；升 ADK 大版本時重跑 `smoke_test.py` 當金絲雀 |
| 服務 B 綁 `localhost`，不是給外部連的 | `to_a2a` 的 `host` 預設 `"localhost"`，名片上就寫這個 | 本機沒差；上雲要傳 `host=<Cloud Run 網域>, protocol="https"`（M10） |
| 忘記關背景的 uvicorn | 8001 一直被佔，下次啟動 `[Errno 48] address already in use` | 清理段有 `pkill` 指令 |
| 免費層輸入可能被用於產品改進 | 附錄 D 第 ⑨ 條 | 旅館資料是假的，不要換成公司真資料 |

## 9. 前置依賴

| 依賴 | 為什麼 | 沒有的話 |
|---|---|---|
| **Lab 7**（ADK 多 agent） | 你要看得懂 `Agent(...)`、`sub_agents=`、`adk web` 的 Events 面板 | 建議先補 Lab 7，這個 Lab 不重講 ADK 基礎 |
| **Lab 8**（Supabase／MCP Toolbox） | 投影片說「把 Lab 8 的 `hotel_agent` 曝露」 | **不是硬依賴**。本 Lab 的 `search_hotels` 自帶假資料，可獨立完成；Lab 8 做完再把 tools 換掉（FR-11） |
| Google 帳號 ＋ AI Studio API key | 步驟 4、5 要真的跑對話 | 主線的 8 條離線驗收照樣能過，步驟 4、5 跳過 |
| `uv` | 本課唯一的 Python 工作流 | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| Python 3.10+（建議 3.13） | ADK 與 a2a-sdk 的最低需求 | `uv init --python 3.13` 會自己抓 |
| 兩個終端機分頁 | 服務 A 與服務 B 是兩個行程 | 一個分頁只能跑一個，會以為程式當掉 |

> ⚠️ 未實測：需要 API key 的那 5 條驗收（步驟 4、5 的真實對話）我沒有 key，沒有跑過。其餘 8 條離線驗收與 `check_card.py` 對真實 `uvicorn` 服務的輸出都是實測過的。
