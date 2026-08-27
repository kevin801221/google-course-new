# Lab 8 PRD：旅館查詢 Agent（三層整合）

> 模組 M8 資料庫整合：Supabase × MCP Toolbox ｜ LAB 投影片第 359 頁 ｜ 90–120 分 ｜ 免費層

## 1. 這個 Lab 要解決什麼問題

M7 的 agent 會用工具、但工具裡的資料是寫死的假資料，而且服務一重啟對話就消失 —— 這種 agent 只能 demo，不能上線。這個 Lab 把「資料層」補上：真實資料放在 Supabase PostgreSQL，資料存取包成 MCP Toolbox 的參數化 SQL 工具（模型只能給參數、不能自己寫 SQL），對話狀態用 `DatabaseSessionService` 落地同一個資料庫。做完之後這個 agent 重啟不失憶、報的價格都查得到出處、而且工具層可以被 Lab 9 的其他 agent 共用。

## 2. 學習目標

做完學生會：

1. **設計**一張同時支援結構化查詢與向量檢索的 Postgres 表（`hotels` + `vector(1536)` + HNSW 索引），並用離線對照（`seed_embeddings.py --aha`）看到「兩段式檢索」會漏答案 —— 這就是資料與向量同庫的理由。
2. **寫出** MCP Toolbox 的 `tools.yaml`（v1.x `kind:` 多文件格式），把 SQL 寫死、只開放參數，並用一個數字說明攻擊面（模型可控的 SQL 字元數＝0，對照 Supabase MCP 的無上限）—— `preflight.py --aha` 看得到。
3. **接上** ADK 的 `ToolboxToolset`，並用 instruction 讓模型不敢憑記憶報價 —— 且能親眼對照「沒接資料庫」與「接了資料庫」兩個版本的答案差異，並認出這是全課「工具」概念的第四種包裝（python 函式 → MCP tool → tools.yaml → A2A skill），schema 契約始終不變。
4. **切換** ADK sessions 從記憶體到 Supabase PostgreSQL，並用「重啟後追問」驗證狀態真的落地，同時說得出 Sessions（重放整段對話）與 state／Memory（結構化事實）是兩件不同的事。
5. **判斷** 什麼場合用 Supabase MCP（自由 SQL、開發探索）、什麼場合用 Toolbox（固定 SQL、正式流量）。

## 3. 使用者故事

- 身為學生，我想讓 agent 回答「東京 3000 元以內有哪些旅館」時去查真的資料表，以便它報的價格是我能拿去訂房的價格，而不是模型編出來的。
- 身為學生，我想把 SQL 鎖在設定檔裡，以便就算模型被 prompt injection 騙了，它手上也只有「帶兩個參數的 SELECT」這一招。
- 身為學生，我想讓 agent 記得我上一輪說的預算，以便重開瀏覽器、重啟服務之後不用再講一次。
- 身為學生，我想用一句「想泡溫泉又安靜」找到旅館，以便理解 pgvector 補上了 SQL `WHERE` 做不到的那一半。

## 4. 功能需求

| 編號 | 需求 | 對應投影片步驟 | 必要 / 加分 |
|---|---|---|---|
| FR-1 | `schema.sql`：`hotels` 表（8.2 的六個欄位）＋ `description`／`embedding vector(1536)`＋ HNSW 索引＋ 10 筆跨城市跨價位種資料，可重複執行 | LAB 1（8.2、8.5 頁） | 必要 |
| FR-2 | `tools.yaml`：`kind: source`（Supabase Session pooler）＋ `search-hotels-by-city`（city, max_price）＋ `get-price-stats`（各城市 count/avg/min/max）＋ `toolset: hotel-tools` | LAB 2（8.6 頁） | 必要 |
| FR-3 | `preflight.py`：離線檢查 `tools.yaml`（`$N` 與 parameters 對不對得上、source/tool 有沒有指錯、`${VAR}` 有沒有 export） | 投影片沒有，補的（啟動前就抓錯） | 必要 |
| FR-4 | Toolbox 啟動並用 curl 確認工具清單載入 | LAB 3 | 必要 |
| FR-5 | `hotel_agent/agent.py`：`ToolboxToolset(toolset_name="hotel-tools")` ＋ 禁止憑空報價的 instruction | LAB 4 | 必要 |
| FR-6 | 對照組：先看到 agent 沒有資料庫時編出來的價格，再接上工具 | 投影片沒有，教學節奏需要 | 必要 |
| FR-7 | `adk web --session_service_uri`（`postgresql+asyncpg://` Session pooler）讓 sessions 落地 Supabase | LAB 5（8.4 頁） | 必要 |
| FR-8 | 持久化驗證：說出預算 → 重啟 `adk web` → 追問「我剛的預算是多少」→ Table Editor 看得到 sessions／events 列 | LAB 6 | 必要 |
| FR-9 | `seed_embeddings.py`：把 `description` 批次嵌入寫回 `embedding`，並提供 `--search` 語意搜尋驗收指令 | LAB 7（8.5 頁） | 加分 |
| FR-10 | `hotel_agent/rag_tool.py`：pgvector 語意搜尋包成 FunctionTool，`LAB8_RAG=1` 時掛上 agent | LAB 7 | 加分 |
| FR-11 | Antigravity 掛 Supabase MCP（`read_only=true`＋`project_ref`＋`features`），請它檢視 `hotels` 的索引 | LAB 8 | 加分 |

## 5. 非功能需求

| 項目 | 要求 |
|---|---|
| 時間盒 | 主線（FR-1～FR-8）60–80 分；兩題加分各 20 分。單步超過 15 分先看常見錯誤表 |
| 費用上限 | Supabase 免費層（500MB DB）＋ Gemini 免費層。主線零元；加分題 A 會呼叫 embedding API（10 筆短描述，用量極小） |
| 離線可測 | `preflight.py --self-check`、`seed_embeddings.py --self-check`、`rag_tool.py --self-check`、`schema.sql` 語法（sqlglot）全部不連網、不需要帳號 |
| 跨平台 | macOS／Linux。Toolbox 執行檔要抓對 OS／CPU（macOS 是 `darwin/arm64`）；macOS 的 5000 埠常被 AirPlay 佔用，用 `--port 5001` |
| 相依管理 | 一律 uv：`uv init --bare` → `uv add` → `uv run`。不出現 pip／venv／requirements.txt |
| 資料相容 | `hotels` 的欄位名與型別要能被 Lab 9／Lab 10／Capstone 直接沿用，不再改 schema |

## 6. 驗收標準

主線：

- [ ] Supabase SQL Editor 跑完 `schema.sql`，`select count(*) from hotels` ≥ 10，且 `create extension` 那行沒紅字
- [ ] `uv run preflight.py` 輸出 `OK：可以啟動 Toolbox 了`，exit code 0
- [ ] Toolbox 起得來，且 `curl -s http://127.0.0.1:5000/api/toolset/hotel-tools` 看得到兩個工具名稱
- [ ] `adk web` 裡問「東京三千元以內有什麼旅館？」，回答的旅館名稱／價格與 `schema.sql` 第 5 段的驗收查詢結果一致
- [ ] 問「哪個城市平均房價最低？」時，trace 裡看到的是 `get-price-stats` 一次呼叫，不是五次 `search-hotels-by-city`
- [ ] 把 agent 的 `tools=` 拿掉再問價格，它會編一個價格出來 —— 你看過這個對照組
- [ ] 對話中說「我預算 3000」→ Ctrl-C 停掉 `adk web` → 用同一條 `--session_service_uri` 重啟 → 追問「我剛說的預算是多少」，它答得出 3000
- [ ] Supabase Table Editor 的 `sessions` 與 `events` 表看得到剛剛那輪對話的列
- [ ] 三支 `--self-check` 都印 `self-check ok`

加分：

- [ ] `uv run seed_embeddings.py` 之後 `select count(*) from hotels where embedding is null` = 0
- [ ] `uv run seed_embeddings.py --search "想泡溫泉"` 的第一名是 Ginza Grand（描述裡有溫泉），`sim` > 後兩名
- [ ] `LAB8_RAG=1 uv run adk web` 問「想找安靜、能泡湯的地方」會呼叫 `search_hotels_semantic`
- [ ] Antigravity 接上 Supabase MCP（read_only），能讀到 `hotels` 的索引清單並提出建議

## 7. 範圍外

- **不做 RLS 與多租戶權限**：我們走 Postgres 連線（`postgres` 使用者）直連，RLS policy 對這條路不生效。Supabase Dashboard 會顯示 "RLS Disabled" 警告，這個 Lab 裡是預期的，不要花時間關掉它。
- **不把 Toolbox 部署上雲**：`server_url` 換成 Cloud Run 網址＋ID token 是 Lab 10 的事。
- **不做 hybrid search／reranking**：投影片 8.5 講了調優順序 —— 先改 chunking 與 top-k，這個 Lab 連 chunking 都不需要（描述本來就短）。
- **不用 Transaction pooler（6543）**：不是「暫不支援」，是會間歇性壞掉，見常見錯誤表。
- **不寫前端**：`adk web` 就是 UI。
- **不改 `hotels` 欄位名**：Lab 9／10／Capstone 吃同一張表。想加欄位請 `alter table add column`，不要改既有欄位。

## 8. 費用與風險

| 項目 | 費用 | 要不要清 |
|---|---|---|
| Supabase 專案 | 免費層 500MB DB、pgvector 內建 | 免費層專案閒置會被暫停，但 Lab 9／10／Capstone 還要用 —— **不要刪** |
| Gemini API（agent 對話） | 免費層即可；付費層 3.7 Flash $0.75/1M 輸入 tokens | 無資源 |
| Gemini embedding（加分題 A） | 10 筆短描述，一次 API 呼叫。價格以官方頁為準，本教材不編數字 | 無資源 |
| Toolbox 執行檔 | 免費（開源、本機跑） | `rm toolbox` 即可 |

風險：

- **密碼外洩**：`tools.yaml` 會進 git，所以密碼一定走 `${DB_PASSWORD}`；`.env` 要進 `.gitignore`。Supabase 資料庫密碼等於整個資料庫的 root 權限。
- **prompt injection**：Toolbox 的固定 SQL 是這個 Lab 最重要的防線 —— 就算模型被騙，它也只能改 `city` 與 `max_price` 兩個參數。加分題 B 的 Supabase MCP 一定要帶 `read_only=true`＋`project_ref`。
- **免費層連線數**：Session pooler 的連線有限，`adk web`＋Toolbox＋psql 同時開就可能吃滿。連不上先關掉不用的。

## 9. 前置依賴

| 依賴 | 從哪來 | 檢查方式 |
|---|---|---|
| Supabase 帳號與專案 | supabase.com 免費註冊（M0 環境準備、8.2） | Dashboard 看得到 project ref |
| 資料庫密碼與 Session pooler 連線字串 | Supabase Dashboard → Connect → Session pooler（5432） | 字串裡有 `pooler.supabase.com:5432` |
| `GEMINI_API_KEY` | aistudio.google.com/apikey（Lab 1 拿過的那把） | `echo $GEMINI_API_KEY` 非空 |
| ADK 基本操作 | Lab 7（`adk web`、agent 目錄結構、instruction 怎麼寫） | 會用 `adk web` 選 agent |
| uv | M0 的安裝指令 | `uv --version` |
| Antigravity（僅加分題 B） | Lab 3 裝過 | `~/.gemini/config/mcp_config.json` 存在 |

不需要 GCP 帳號、不需要信用卡 —— 這個 Lab 全程在免費層。
