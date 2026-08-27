# Capstone PRD：個人 LLM Wiki ＆ Assistant System

> M11 Capstone ｜投影片 426-456 ｜預估 2-4 天（四個 Phase，每個 Phase 半天到一天）｜費用約 $0-10

## 1. 這個 Lab 要解決什麼問題（為什麼存在）

前十個模組每個都做出一塊能用的東西，但它們躺在十個資料夾裡各自為政：知識庫在 NotebookLM、RAG 在 Lab 8 的 Supabase、agent 在 Lab 7、MCP server 在 Lab 6、部署腳本在 Lab 10。Capstone 不教任何新 API，它要解決的是**整合**這件事本身：把這些零件接成一個你會天天用的系統（問知識庫、叫它研究並入庫、查自己的結構化資料、每天收一份日報），並且在雲端持續運行、可被別的 agent 接上。投影片 429 頁那句話就是全部重點——「每一個方塊都是你在 M1-M10 親手做過的東西，Capstone 只是把它們接上正確的線」。接線本身才是這個 Lab 的技術難度：委派邊界、權限邊界、成本邊界、失敗邊界。

## 2. 學習目標

做完之後你會：

1. **設計** 一個 multi-agent 系統的職責切分（誰能上網、誰能寫資料庫、誰只能查表），並用 description ＋ instruction 讓委派真的發生——委派的實作是「一段自動生成的 prompt ＋ 一個 `transfer_to_agent` 工具」，不是框架魔法（`uv run aha.py --delegation` 看原文）。
2. **建置** 雙知識庫的 ingest 管線：同一份內容 Markdown 進 pgvector（可程式化查詢）、摘要進 NotebookLM（可讀、可引用），並知道「知識庫查無資料」是 `min_sim` 門檻造出來的產品決定，不是資料庫的事實（`uv run aha.py --threshold`）。
3. **封裝** 自己的能力成四層包裝（Python 函式 → ADK tool → MCP tool → A2A skill），四層共用你寫的那一份 docstring 當規格書，讓 Capstone 的 agent、你的 Antigravity、同事的 host 共用同一份實作（`uv run aha.py --wrappers`）。
4. **部署** 五個 Cloud Run 服務並用 IAM 串起來，做到「未授權身分呼叫內部服務得到 403」。
5. **驗收與維運** 用可執行的驗收矩陣（`acceptance.py`）與 evalset 判斷系統是「能跑」還是「能用」，並說得出這 1,135 行裡哪 11 行是新邏輯、其餘全是接線（`uv run aha.py --parts`／`--map`）。

## 3. 使用者故事

- 身為學生，我想把前十個 Lab 的產出接成一個系統，以便證明自己不只會照抄單一 Lab 的步驟。
- 身為使用者，我想問「我知識庫裡關於 A2A 的重點」就得到帶引用的答案，以便不用自己翻筆記。
- 身為使用者，我想說「研究 X 並存起來」就有 agent 幫我搜尋、整理、入庫，以便下次直接查得到。
- 身為使用者，我想用自然語言問「這個月訂閱花多少」，以便不用開 SQL editor。
- 身為使用者，我想每天早上收到一份 Markdown 日報，以便知道自己昨天存了什麼、該讀什麼。
- 身為開發者，我想把知識庫能力曝露成 MCP／A2A，以便未來任何新 agent 都能接上而不用改我的程式。
- 身為付錢的人，我想知道閒置時費用是 0，以便放心讓它一直開著。

## 4. 功能需求

| 編號 | 需求 | 對應投影片 | 必要／加分 |
|---|---|---|---|
| FR-1 | 知識問答（Wiki）：問「我讀過／存過」的東西，答案帶引用；NotebookLM＋pgvector 雙庫 | 428 ①、433 | 必要 |
| FR-2 | ingest 管線：一支指令碼把網址或檔案切塊入 pgvector，並產生給 NotebookLM 的摘要 | 434 | 必要 |
| FR-3 | 研究入庫：「幫我研究 X 並存進知識庫」→ research agent 搜尋、整理、呼叫 ingest | 428 ②、436-2 | 必要 |
| FR-4 | 資料查詢：自然語言查 subscriptions／notes 等結構化資料，SQL 由 Toolbox 鎖死 | 428 ③、436-4 | 必要 |
| FR-5 | 每日摘要 workflow：Graph（純函式撈資料 → LLM 寫作 → Markdown 日報），排程觸發 | 428 ④、438 | 必要 |
| FR-6 | concierge root agent：只做理解、委派、彙整，instruction 明列「不得自答知識問題」 | 436-1、437 | 必要 |
| FR-7 | 模型分級：總管與研究用 `gemini-3.7-flash`、查表與雜活用 `gemini-3.5-flash-lite` | 437、448 | 必要 |
| FR-8 | 自建 wiki-mcp：`wiki_search`／`wiki_ingest` 兩個 tool ＋ `wiki://stats` resource | 440 | 必要 |
| FR-9 | 工具層權限矩陣：`wiki_search` 人人可用；`wiki_ingest`／notes 寫入只有 concierge 的 SA | 441-4 | 必要 |
| FR-10 | A2A：research_agent 以 `to_a2a()` 獨立部署，concierge 用 `RemoteA2aAgent` 消費 | 443-2 | 必要 |
| FR-11 | 全雲端運行：手機瀏覽器可用、session 持久（Supabase）、重啟不失憶 | 428 ⑤、443-1 | 必要 |
| FR-12 | 部署拓撲：wiki-mcp／toolbox／research-a2a 私有＋concierge 入口，IAM 綁 run.invoker | 443、444 | 必要 |
| FR-13 | 驗收矩陣：投影片 446 的六條端到端驗收變成可勾選＋可執行的清單 | 446 | 必要 |
| FR-14 | evalset 對 concierge 全綠（沿用 Lab 7 的 eval 流程） | 446-6 | 必要 |
| FR-15 | notebooklm-mcp 留在本機開發環境（cookie 認證不上雲） | 441-3 | 加分 |
| FR-16 | Agent Engine 版 concierge 對照部署（享受託管 Memory Bank） | 443-5 | 加分 |
| FR-17 | Antigravity skills：把「研究報告格式」「日報格式」寫成 skill | 441-5 | 加分 |

## 5. 非功能需求

| 類別 | 要求 |
|---|---|
| 時間盒 | Phase 1 半天、Phase 2 一天、Phase 3 半天、Phase 4 一天。每個 Phase 結束都有可展示的中間成果，卡住就先交中間成果再往下 |
| 費用上限 | 輕度使用 $0-2/月、重度 $5-15/月、閒置 $0（全 scale-to-zero）。單次驗收全流程 < $1 |
| 離線可測 | 每支程式都有 `--self-check` 或 `--dry-run`：不連網、不花錢。`uv run acceptance.py --offline` 一次跑完（本 repo 實測 8 條全綠） |
| 成本紀律 | 撈資料用純函式節點（零 token）、雜活用 flash-lite、迴圈一律設 `max_iterations`、GCP 設預算告警（Lab 5） |
| 跨平台 | macOS／Linux shell 為主；Windows 用 WSL2。工具鏈一律 uv，不用 pip／venv |
| 安全 | 機密走 Secret Manager，不進 git；agent 的 SA 只給 `run.invoker`，不給 Editor／Owner；內部服務 `--no-allow-unauthenticated` |
| 可觀察 | 每層都能獨立 smoke test（curl agent card、curl MCP 端點、`adk eval`），壞掉時能指出是哪一層 |

## 6. 驗收標準

完整矩陣在 `ACCEPTANCE.md`（由 `acceptance.py` 產生，共 20 條）。這裡是投影片 446 頁的六條主線：

- [ ] **446-1 知識問答**：問「我知識庫裡關於 A2A 的重點？」→ 委派 wiki_agent → 答案引用的 source 真的存在於 `documents` 表
- [ ] **446-2 研究入庫**：「研究 Cloud Run GPU 定價並存起來」→ research（跨 A2A 服務）→ ingest → 再問一次答得出來
- [ ] **446-3 資料查詢**：「我這個月的訂閱總花費？」→ data_agent → 數字等於 `select sum(monthly_twd) from subscriptions where active`
- [ ] **446-4 持久化**：對話 → 重新整理瀏覽器 → 追問前文接得上；Supabase 的 events 表看得到列
- [ ] **446-5 摘要工作流**：`uv run digest.py` 產出含「今日重點／值得深讀／待辦建議」三段的 Markdown
- [ ] **446-6 權限與品質**：`curl $WIKI_MCP_URL/mcp` 得到 403；`uv run adk eval concierge tests/capstone.evalset.json` 全綠

離線先過（不用帳號、不花錢，可以現在就跑）：

```bash
uv run acceptance.py --offline
# 期望最後一行：離線驗收：8 通過 / 0 失敗
```

## 7. 範圍外

- **不做前端**：介面就用 `adk deploy cloud_run --with_ui` 附的 Web UI。要自己寫 React 是另一個專案。
- **不做多使用者**：single-tenant，session 用 `user_id` 分隔就好，沒有註冊登入、沒有 row-level security。
- **不把 notebooklm-mcp 上雲**：cookie 認證不適合雲端（投影片 441-3），雲端的知識查詢全走 pgvector。
- **不做 embedding 微調／reranker**：pgvector 餘弦相似度 ＋ `min_sim` 門檻就結案。RAG 品質調優是另一條路。
- **不追求 100% 委派正確率**：evalset 綠燈即可；instruction 調到「不亂答」比調到「永遠選對專員」划算。
- **不做 CI**：evalset 進 CI 是投影片 449 的下一步迭代，不在這次範圍。

## 8. 費用與風險

| 項目 | 免費層／費用 | 風險與對策 |
|---|---|---|
| Gemini API | 3.7 Flash $0.75/1M 輸入；flash-lite $0.30/1M | research agent 的搜尋量是最大變數 → 分級模型＋在 instruction 限制搜尋輪數 |
| Search grounding | 每月前 5,000 次查詢免費 | 研究任務會一次打好幾次搜尋 → 別把 research 排成每小時排程 |
| Cloud Run × 4-5 服務 | 每月 200 萬次請求免費層；scale-to-zero 時 $0 | `min-instances=1` 會開始月租 → 除非真的受不了冷啟動，不要設 |
| Supabase | 免費層 500MB＋pgvector | documents 表會長大 → 定期清 topic 為空的雜訊 |
| Secret Manager | 有免費額度（⚠️ 投影片沒給數字，額度請查 cloud.google.com/secret-manager/pricing） | 版本會累積 → 用完刪舊版本 |
| Cloud Scheduler | 有免費 job 額度（⚠️ 投影片沒給數字，請查 cloud.google.com/scheduler/pricing） | 日報一天一次就好，不要設每小時 |
| 帳單失控 | — | GCP 預算告警（Lab 5）＋ `LoopAgent max_iterations` ＋ `thinking_level` 不要一律 high |
| prompt injection | — | 災害半徑＝agent 權限：SA 只給 `run.invoker`，寫入工具只掛在 concierge，Toolbox 把 SQL 寫死 |

用完要清（雲端資源會一直算錢的只有 min-instances 與 Secret Manager 版本，但服務留著也會被掃）：見 `walkthrough.md` 最後一節「清理」的可貼指令。

## 9. 前置依賴

### 9.1 元件 × 模組對照（投影片 430 的裝備檢查表，加上「這個元件在哪個 Phase 用到」）

| Capstone 元件 | 來自模組 | 複用的 Lab | 用在哪個 Phase | 本 repo 對應檔案 |
|---|---|---|---|---|
| Gemini 呼叫＋結構化輸出 | M1 | Lab 1 的 `ask.py` 模式 | Phase 1（ingest 的 fetch／summarize） | `wiki_core.py` |
| NotebookLM 知識庫＋MCP | M4 | Lab 4 原樣沿用 | Phase 1（策展側）、Phase 3（本機 host） | `mcp_config.sample.json` |
| GCP 專案／IAM／Secrets | M5 | Lab 5 的專案 | Phase 4（部署、機密、SA） | `deploy.sh` |
| 自建 wiki-mcp server | M6 | Lab 6 骨架改造 | Phase 3 | `wiki_mcp/server.py` |
| Multi-agent＋workflow | M7 | Lab 7 的委派結構＋evalset | Phase 2 | `concierge/agent.py`、`digest.py`、`tests/capstone.evalset.json` |
| pgvector RAG＋Toolbox | M8 | Lab 8 的三層整合 | Phase 1（documents 表）、Phase 3（Toolbox） | `schema.sql`、`tools.yaml`、`wiki_core.py` |
| A2A 曝露與消費 | M9 | Lab 9 的雙服務 | Phase 4 | `research_service/agent.py`、`concierge/agent.py` |
| Cloud Run／Agent Engine 部署 | M10 | Lab 10 的部署鏈 | Phase 4 | `deploy.sh`、`Dockerfile` |

四個 Phase 的建置路線（投影片 431）：

| Phase | 目標 | 中間成果（可展示） | 需要雲端？ |
|---|---|---|---|
| Phase 1 知識層 | NotebookLM＋pgvector 就緒、ingest 管線 | `uv run ingest.py <url>` 真的寫進 documents，兩邊各問同一題 | Supabase |
| Phase 2 Agent 團隊 | 四個 agent 本機跑通＋evalset | `uv run adk web` 能委派，`adk eval` 全綠 | API key |
| Phase 3 工具層 | wiki-mcp＋Toolbox 容器化 | Antigravity 的 `/mcp` 看得到 `wiki_search` | 否（本機即可） |
| Phase 4 串聯部署 | A2A 接線、全部上 Cloud Run、驗收 | 手機瀏覽器打開 concierge 就能用 | GCP |

### 9.2 帳號與金鑰

| 依賴 | 從哪來 | 沒有它會怎樣 |
|---|---|---|
| `GEMINI_API_KEY` | AI Studio（免費、不用信用卡） | `ValueError: No API key was provided.` |
| `DATABASE_URL` | Supabase → Connect → **Session pooler（5432）** | `RuntimeError: 沒有 DATABASE_URL`（本 repo 的防呆訊息） |
| GCP 專案＋`agent-sa` | Lab 5 | Phase 4 全部做不了；Phase 1-3 照樣能做 |
| NotebookLM 筆記本 | Lab 4 | 只剩單庫，做不到 433 頁的雙庫對照驗收 |
| uv | M0 的安裝指令 | 用 `python xxx.py` 會 `ModuleNotFoundError: No module named 'google'` |

> 沒有 GCP 帳號也能做完 Phase 1-3 的本機版（約 60% 的內容）：知識層、agent 團隊、wiki-mcp 都能在本機跑，只有 Phase 4 的部署與 A2A 跨服務需要雲端。
