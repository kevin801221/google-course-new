# Lab 10 PRD：整套系統上雲

## 1. 這個 Lab 要解決什麼問題

前九個 Lab 的成果全部只活在 `localhost`：MCP server 是 stdio 子行程、Toolbox 是本機 binary、A2A 服務是 `uvicorn --port 8001`、session 是 InMemory 一關就沒。這個 Lab 把這四個元件變成四個有網址、有身分、有存取控制的雲端服務，並讓主 agent 跨這四個服務完成一次回答 —— 從「我電腦上跑得動」變成「別人可以用、重開機還在、出事查得到、月底帳單看得懂」。

## 2. 學習目標

做完學生會：

1. **部署並存取** 一個私有（`--no-allow-unauthenticated`）的 Cloud Run 服務：proxy 與 ID token 兩種合法入口，加上 service-to-service 三件套（呼叫端 SA、`roles/run.invoker`、audience 全等目標網址）—— 能從 401 / 403 的差別反推是哪一件錯了，也知道 IAM 的粒度是「服務 × 身分」而不是「路徑 × 身分」。
2. **注入** 機密：把 Supabase 連線字串放 Secret Manager，用 `--set-secrets` 掛進容器，證明它沒有出現在 image、環境變數檔或 git 裡。
3. **診斷** 「本機跑得動、上雲就掛」：說得出 `adk deploy` 產的容器與自己的開發環境差在哪三件事（google-adk extras 少 4 個、`dev_server.py` 被刪掉、模型憑證從 API key 換成 service account），並知道依賴斷層要靠 `requirements.txt` 補（`uv run aha.py --deps`）。
4. **對照** 同一份 agent 在 Cloud Run（自由容器、`--with_ui`）與 Agent Engine（託管 runtime、內建 sessions/traces）上的部署與操作體驗差異 —— 包含「託管換掉的是執行身分」這個代價。
5. **算清並清光**：說得出閒置帳單為零與第一次請求冷啟動是同一個 scale-to-zero 的兩面（`uv run aha.py --cost` 算出 `--min-instances 1` 的月費），然後刪掉這個 Lab 建的所有計費資源，在帳單頁面確認歸零。

## 3. 使用者故事

- 身為學生，我想把 Lab 6 的 MCP server 變成一個網址，**以便**團隊其他人（和我的雲端 agent）都能用同一套工具，而不是每個人本機跑一份。
- 身為學生，我想讓私有服務對沒授權的人回 403，**以便**我確認「私有」不是寫在文件上的形容詞，而是真的擋得住。
- 身為學生，我想讓對話重開機還在，**以便**知道 session 落地跟不落地的差別到底在哪一行設定。
- 身為學生，我想一次跑完 `verify.sh` 就知道 12 個檢查項哪個掛了，**以便**不必逐個服務點 Console 猜。
- 身為學生，我想有一支 `teardown.sh` 一鍵刪光，**以便**我敢動手做，不怕忘記關而被扣款。

## 4. 功能需求

| 編號 | 需求 | 對應投影片步驟 | 必要 / 加分 |
|---|---|---|---|
| FR-1 | Lab 6 的 MCP server 以 streamable-http 部署到 Cloud Run，私有，且能用 `gcloud run services proxy` 從本機連上 | ① （p.423 / p.415-416） | 必要 |
| FR-2 | Lab 8 的 `tools.yaml` 打包成容器部署到 Cloud Run，私有，透過 Secret Manager 拿 Supabase 密碼 | ② | 必要 |
| FR-3 | Lab 9 的 `to_a2a()` 服務部署到 Cloud Run，`/.well-known/agent-card.json` 公開讀得到 | ③ （p.419） | 必要 |
| FR-4 | concierge agent 用 `adk deploy cloud_run --with_ui` 部署，工具指向 FR-1/FR-2，sub_agent 指向 FR-3 | ④ （p.410） | 必要 |
| FR-5 | `SESSION_DB_URL` 走 Secret Manager 掛 Supabase，連線字串不進 image、不進 git | ⑤ （p.412-413） | 必要 |
| FR-6 | 從 `--with_ui` 網頁問「預算 3000 東京兩晚」，一次回答跨四個雲端服務 | ⑥ | 必要 |
| FR-7 | 同一份 concierge 再用 `adk deploy agent_engine` 部署一次，比較兩者體驗 | ⑦ （p.402-403） | 必要 |
| FR-8 | `teardown.sh` 刪光所有服務，帳單頁面確認無異常 | ⑧ （p.402 的「刪除習慣」） | 必要 |
| FR-9 | `deploy.sh --dry-run` 只印指令不動雲端；`deploy.sh <階段>` 可單獨重跑任一階段 | 投影片沒要求，但沒有它學生不敢按 Enter | 必要 |
| FR-10 | `verify.sh` 逐項檢查健康與「未授權應為 403」，含 `--self-check` 離線驗判定邏輯 | 對應 p.411 smoke test，擴充成可重複執行 | 必要 |
| FR-11 | 逛一次 Agent Garden，找出最接近 concierge 的官方樣板 | 10.2（p.398-399） | 加分 |
| FR-12 | `gcloud run services update-traffic` 把流量切回上一個 revision | p.422 上線檢查清單第 6 項 | 加分 |

## 5. 非功能需求

| 項目 | 要求 |
|---|---|
| 時間盒 | 120-150 分。其中 Cloud Build 建映像佔掉約 4 × 3-5 分（等的時候去讀 Agent Garden，別乾等） |
| 費用上限 | 目標 $0-5。Cloud Run 有每月 200 萬請求 / 18 萬 vCPU-秒免費層；Agent Engine 有 50 vCPU-h + 100 GiB-h 免費層。全部服務設 `--max-instances 3`，收工執行 `teardown.sh` |
| 離線可測 | `verify.sh --self-check`（判定邏輯）與 `concierge/auth.py --self-check`（audience 計算）不連網、不需帳號、不花錢 |
| 可重複執行 | `deploy.sh` 任一階段可重跑（`gcloud secrets create` 失敗自動退成 `versions add`、SA 已存在不中斷）；`teardown.sh` 每一項 `|| true`，刪不到不停 |
| 跨平台 | 腳本用 `#!/usr/bin/env bash` + POSIX 語法（不用 array、不用 `%q`），macOS 內建的 bash 3.2 跑得動；Windows 用 WSL2 |
| 不動別人的目錄 | 部署前把 lab6/lab8/lab9 複製到 `lab10/.build/`，Dockerfile 蓋在副本上 —— 不在別的 Lab 目錄留檔案 |

## 6. 驗收標準

```bash
# 離線（不用帳號、不花錢）
./verify.sh --self-check                          # → self-check ok
uv run --no-project concierge/auth.py --self-check # → self-check ok
./deploy.sh --dry-run                              # → 印出 31 條指令，沒有任何一條被執行（不用先有 Supabase 密碼）

# 雲端（要 GCP 專案）
./verify.sh                                        # → PASS=12  FAIL=0
```

- [ ] `curl https://mcp-tools-xxx.run.app/mcp` 不帶 token → **403**（不是 200、不是 404）
- [ ] `gcloud run services proxy mcp-tools --port=3000` 後，`http://localhost:3000/mcp` 通
- [ ] `curl -H "Authorization: Bearer $(gcloud auth print-identity-token)" .../api/toolset` → 200，回傳 `hotel-tools` 裡的工具清單
- [ ] `curl https://hotel-a2a-xxx.run.app/.well-known/agent-card.json` 不帶 token → 200，且 JSON 裡有 `"name"`
- [ ] `curl -H "Authorization: Bearer $TOKEN" $AGENT_URL/list-apps` → `["concierge"]`
- [ ] `--with_ui` 網頁問「預算 3000 東京兩晚」→ 回答裡同時出現匯率換算（MCP）、旅館清單（Toolbox）、推薦理由（A2A hotel agent）
- [ ] 關掉瀏覽器、重新開同一個 session id → 之前的對話還在（session 落 Supabase 的證據）
- [ ] Cloud Trace 看得到一次查詢的 span 瀑布，裡面有工具呼叫
- [ ] `adk deploy agent_engine` 完成，Console 的 Agent Engine 內建聊天視窗回得出話
- [ ] `./teardown.sh` 跑完，`gcloud run services list` 是空的
- [ ] 你能說出「403 和 401 分別是哪一件事沒做對」，而且兩種都親眼看過

## 7. 範圍外

- **不做 GKE**。投影片立場：知道有 `adk deploy gke` 就好（p.393）。
- **不做 GPU / 自架模型**。Lab 一律用 Gemini API（p.421）。L4 約 $0.19/秒，一個下午忘記關就超過整門課的預算。
- **不做 CI/CD 與 IaC**。那是 Agent Starter Pack 的範圍（p.399），這個 Lab 只做手動部署 + 腳本。
- **不做灰度分流**。`update-traffic` 只在加分題出現，不寫進主線。
- **不改 Lab 6/8/9 的程式碼 —— 只有一個例外**。上雲的關鍵是「原封不動搬上去」，要改的只有啟動參數與環境變數。唯一的例外是 Lab 9 的名片網址：`to_a2a()` 用 `host`/`port`/`protocol` 組出名片上的 `url`，Lab 9 現行版本組出來的是 `http://localhost:8001/`，上雲之後消費端照著它打會 `Connection refused`。這一行必須改（walkthrough 步驟 3 有完整改法）。這個例外本身就是教材：**名片是「別人照著打」的網址，不是「我自己 listen」的網址。**
- **不做 Memory Bank**（p.404）。它是 Agent Engine 的加值功能，留給 Capstone。

## 8. 費用與風險

| 資源 | 免費層 | 這個 Lab 的用量 | 風險 |
|---|---|---|---|
| Cloud Run 請求 | 200 萬次／月 | 幾百次 | 無 |
| Cloud Run vCPU | 18 萬 vCPU-秒／月 | scale-to-zero，只有你在問的時候計費 | 忘記設 `--max-instances`，被 loop 的 agent 打爆 → 已在 deploy.sh 寫死 3 |
| Cloud Build | 投影片沒給 | 4 次 × 3-5 分 | 反覆重建可能吃完當日免費建置時間，失敗先看 log 再重跑 |
| Artifact Registry | 投影片沒給 | 4 個 image，約 1-2 GB | **可能超**（免費層是 GB 級的個位數以下）。`teardown.sh` 第 3 步刪 `cloud-run-source-deploy` repo |
| Agent Engine | 50 vCPU-h + 100 GiB-h／月（p.401） | 一個 instance 跑十幾分鐘 | **閒置也計費**。這是最容易忘記刪的一項 |
| Secret Manager | 投影片沒給 | 2 個 secret | 無（量級太小） |
| Gemini API | 見 M1 | 幾十次查詢 | 無 |
| Supabase | 500 MB（課程總覽表） | 沿用 Lab 8 | 無 |

價格與免費層數字全部抄投影片 p.401 / p.408 / p.421 與課程總覽表。**標「投影片沒給」的三項我不編數字** —— Cloud Build、Artifact Registry、Secret Manager 的免費額度請看 <https://cloud.google.com/pricing>，它們也是這個 Lab 唯一有機會超的三項（前兩項靠 `teardown.sh` 解決）。

預估總花費 **$0-5**（與課程 Lab 總覽表的「Lab 10 ~$0-5」一致）。

清理指令（完整版見 walkthrough 最後一節）：

```bash
./teardown.sh --dry-run   # 先看要刪什麼
./teardown.sh             # 真的刪
```

風險提醒：
- **prompt injection 的災害半徑 = agent 的權限**（附錄 D ⑩）。這個 Lab 的 `agent-sa` 只給 `aiplatform.user` + `secretmanager.secretAccessor` + `logging.logWriter` + 兩個服務的 `run.invoker`，**沒有** Editor / Owner。
- **免費層輸入可能用於產品改進**（附錄 D ⑨）。這個 Lab 用 `GOOGLE_GENAI_USE_ENTERPRISE=True` 走 GCP 專案，不是免費層。

## 9. 前置依賴

| 依賴 | 從哪來 | 沒有會怎樣 |
|---|---|---|
| GCP 專案 + 綁卡 + 預算告警 | Lab 5 | `gcloud run deploy` 直接失敗 |
| `gcloud` 已登入且設好專案 | Lab 5（`gcloud auth login` + `gcloud auth application-default login`） | 每個指令都要手打 `--project` |
| `lab6/server.py`（支援 `MCP_TRANSPORT=http`） | Lab 6 | 容器起不來：Cloud Run 等不到有人 listen `$PORT` |
| `lab8/tools.yaml` + Supabase 專案（Session pooler 5432） | Lab 8 | Toolbox 容器起得來但每個查詢都失敗 |
| `lab9/hotel_service/agent.py`（`to_a2a` 版） | Lab 9 | 沒有 A2A 服務可部署，步驟 ③④⑥ 全斷 |
| Supabase 連線字串與資料庫密碼 | Lab 8 的 Dashboard → Connect | 步驟 ⑤ 做不了 |
| `uv` | M0 環境準備 | `uv run adk` 找不到；`uv export` 產不出部署要的依賴清單 |
| Node.js 20+ | M0 環境準備 | 只有「想再往下玩」的 `npx @google-cloud/cloud-run-mcp` 需要，主線不用 |

三個路徑寫在 `config.sh`（`LAB6_DIR` / `LAB8_DIR` / `LAB9_DIR`），目錄名不一樣就改那三行。
