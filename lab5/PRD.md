# Lab 5 PRD：課程專用 GCP 專案完整設置

> 模組 M5 Google Cloud 基礎 ｜ 投影片 LAB 頁 p.244 ｜ 預估 30-40 分 ｜ **需綁信用卡**

## 1. 這個 Lab 要解決什麼問題

M7-M11 的每一個部署 Lab（ADK 上 Cloud Run、Agent Engine、Cloud SQL、A2A 跨服務）都假設你手上有一個「已綁帳單、已開 API、已設 ADC、已有 service account、已設預算告警」的 GCP 專案。這些設定散在投影片 p.231-p.243 的五個小節裡，學生第一次做時最常見的失敗不是寫錯程式，而是 `PERMISSION_DENIED: ... API has not been used in project ... before or it is disabled`——然後花一小時找不到原因。這個 Lab 把整套環境設置一次做完、寫成可重跑的腳本、並留下一支能逐項印綠勾紅叉的驗收工具，讓後面五個模組不再因為環境問題卡住。同時因為這是全課唯一要綁信用卡的 Lab，它也負責把「先設預算告警、用完就刪專案」的成本紀律教到手上。

## 2. 學習目標

做完這個 Lab，學生能：

1. **建立**一個 GCP 專案、綁定 billing account、並在花任何錢之前設好三段門檻的預算告警。
2. **區分**兩種身分：`gcloud auth login`（你在終端機的身分）與 ADC（你的程式的身分），說出 ADC 查找順序各層用在什麼場景，並解釋為什麼同一行 `genai.Client()` 換了憑證來源卻不用改任何一行程式碼。
3. **建立** service account 並依最小權限原則只授予 `roles/aiplatform.user` 與 `roles/secretmanager.secretAccessor`，而不是偷懶給 Editor；並把 IAM policy 當成一份可 diff、可斷言的 JSON 來檢查。
4. **把機密存進** Secret Manager 並讀回來，說明為什麼本機用 `.env`、雲端一律 Secret Manager。
5. **寫出** idempotent 的雲端設置腳本：先查再建、可重跑不炸、有 `--dry-run` 可以先看指令。
6. **清乾淨**：知道預算告警只寄信不斷電，而 `gcloud projects delete` 之所以是最不會漏掉費用的清理方式，是因為 project 就是計費邊界；也知道它有 30 天緩衝期。

## 3. 使用者故事

| # | 故事 |
|---|---|
| US-1 | 身為第一次用 GCP 的學生，我想在綁卡之後**立刻**設好預算告警，以便不會因為忘記刪某個資源而被扣到錢。 |
| US-2 | 身為學生，我想有一支腳本把七個步驟一次做完，以便不用在投影片五頁之間來回抄指令。 |
| US-3 | 身為學生，我想在**沒有 GCP 帳號**的情況下先看懂腳本會做什麼（`--dry-run`），以便決定要不要綁卡。 |
| US-4 | 身為學生，我想有一支工具逐項告訴我哪一項沒設好、以及該貼哪一行指令去修，以便不用靠猜。 |
| US-5 | 身為做到一半被打斷的學生，我想重跑腳本而不會撞 `ALREADY_EXISTS`，以便從中斷處接續。 |
| US-6 | 身為課程結束的學生，我想一行指令把所有雲端資源清光，以便確定不會有殘留費用。 |
| US-7 | 身為講師，我想在課堂上用 `--dry-run` 投影出完整指令序列，以便講解每一行的用意而不用真的動我的帳號。 |

## 4. 功能需求

| 編號 | 需求 | 對應投影片步驟 | 必要/加分 |
|---|---|---|---|
| FR-1 | `setup.sh` 建立專案（ID 全球唯一、建立後不可改）並設為 `gcloud config` 預設專案 | p.244 步驟 1、p.231 | 必要 |
| FR-2 | `setup.sh` 綁定 billing account，缺 `BILLING_ACCOUNT` 時提示先跑 `gcloud billing accounts list` | p.244 步驟 1、p.231 | 必要 |
| FR-3 | `setup.sh` 建立 $25 預算告警，三段門檻 50%／90%／100% | p.244 步驟 2、p.231 | 必要 |
| FR-4 | `setup.sh` 啟用六個 API：aiplatform、run、cloudbuild、artifactregistry、secretmanager、sqladmin | p.244 步驟 3、p.233 | 必要 |
| FR-5 | `setup.sh` 引導 `gcloud auth application-default login` 並設 quota project | p.244 步驟 4、p.235 | 必要 |
| FR-6 | `setup.sh` 建立 `agent-sa` 並綁 `roles/aiplatform.user` ＋ `roles/secretmanager.secretAccessor` | p.244 步驟 5、p.238 | 必要 |
| FR-7 | `setup.sh` 把 `GEMINI_API_KEY` 存進 Secret Manager（secret 已存在時改為 `versions add`） | p.244 步驟 6、p.241 | 必要 |
| FR-8 | 全部腳本 idempotent：每個建立動作前先查存在性，重跑不產生錯誤也不產生重複資源 | 投影片未提，補上 | 必要 |
| FR-9 | 全部腳本支援 `--dry-run`：只印指令、不執行、不連網 | 使用者要求 | 必要 |
| FR-10 | `verify.sh` 逐項檢查 19 項設定並印 ✓／✗，退出碼＝失敗項數 | p.244 步驟 7 | 必要 |
| FR-11 | `verify.sh` 失敗項要一併印出「修：<可貼的指令>」 | 投影片未提，補上 | 必要 |
| FR-12 | `vertex_smoke.py` 以 Enterprise 路線（`enterprise=True`）呼叫 `gemini-3.7-flash` 成功 | p.244 步驟 7、p.235 | 必要 |
| FR-13 | `teardown.sh` 支援整個專案刪除（預設）與只刪 Lab 資源（`--keep-project`），刪除前要打字確認 | p.243 | 必要 |
| FR-14 | 非 trivial 邏輯留 `--self-check`：不連網、不花錢，用假的 `gcloud` 與假環境驗邏輯 | BRIEF 規範 | 必要 |
| FR-15 | `env.example` 提供課程標準環境變數範本，之後每個模組沿用 | p.242、p.240 | 加分 |
| FR-16 | `verify.sh --with-api` 才真的打一次 API，預設跳過以免浪費額度 | 投影片未提，補上 | 加分 |

## 5. 非功能需求

| 類別 | 要求 |
|---|---|
| 時間盒 | 30-40 分。其中 `gcloud services enable` 六個 API 約 1-2 分鐘（GCP 端非同步生效），ADC 授權要開瀏覽器約 1 分鐘。 |
| 費用上限 | 本 Lab 本身建立的資源（專案、SA、secret、budget）全部 **$0**。`gemini-3.7-flash` 的一次 smoke test 呼叫落在試用額度內。預算告警設在 $25，全課估計 $0-10。 |
| 離線可測 | `setup.sh --dry-run`、`verify.sh --dry-run`、`teardown.sh --dry-run` 完全不連網；三支腳本的 `--self-check` 與 `vertex_smoke.py --self-check` 不需要 GCP 帳號、不需要 gcloud、不花錢。 |
| 跨平台 | 腳本相容 macOS 內建的 bash 3.2（不用 associative array、不用 `mapfile`、不用 `${var,,}`）。Windows 用 WSL2。 |
| 終端機輸出 | 非 tty（管線、CI、重導向）自動退成 `[ OK ]` / `[FAIL]` 純文字，不吐 ANSI escape。 |
| 依賴 | shell 端只要 `gcloud` 與 POSIX 工具（grep/sed/printf）。Python 端只有 `google-genai`，用 `uv run` 管理。 |
| 安全 | `PROJECT_ID` / `SA_NAME` / `BILLING_ACCOUNT` 在使用前用 GCP 真實命名規則驗過格式；不下載 service account JSON 金鑰檔；secret 值只從環境變數經 stdin 進 gcloud，不會出現在指令列或 shell 歷史。 |

## 6. 驗收標準

對應 p.244 步驟 7。在 `lab5/` 目錄下逐項執行：

**離線部分（不需要 GCP 帳號，全部可立刻驗）**

- [ ] `./setup.sh --self-check` → `setup.sh --self-check 全部通過`
- [ ] `./verify.sh --self-check` → `verify.sh --self-check 全部通過`
- [ ] `./teardown.sh --self-check` → `teardown.sh --self-check 全部通過`
- [ ] `uv run vertex_smoke.py --self-check` → `vertex_smoke.py --self-check 全部通過`
- [ ] `./setup.sh --dry-run` 印出的指令序列包含六個 API、三段 threshold、兩個 role
- [ ] `./verify.sh --dry-run | cat` 的輸出裡沒有 ANSI escape（`| cat` 後仍然乾淨）

**線上部分（需要 GCP 帳號與已綁卡）**

- [ ] `gcloud config list` 的 `project` ＝你的專案 ID、`run/region` ＝ `us-central1`
- [ ] `gcloud billing projects describe $PROJECT_ID --format='value(billingEnabled)'` → `True`
- [ ] Console 的 Billing → Budgets 看得到 `course-budget`，三段門檻都在，通知信箱是自己
- [ ] `gcloud services list --enabled --format='value(config.name)' | grep -c -E 'aiplatform|^run\.|cloudbuild|artifactregistry|secretmanager|sqladmin'` → `6`
- [ ] `gcloud auth application-default print-access-token | head -c 20` 印出一段 token 開頭
- [ ] `gcloud iam service-accounts describe agent-sa@$PROJECT_ID.iam.gserviceaccount.com` 成功
- [ ] `gcloud secrets versions access latest --secret=gemini-api-key` 印出你的 key
- [ ] `uv run vertex_smoke.py` 印出一句中文回答（Enterprise 路線通了）
- [ ] `./verify.sh --with-api` 全綠，退出碼 `0`

## 7. 範圍外

- **不部署任何服務**。Cloud Run 部署是 M10／Lab 10 的事，這裡只把 `run`／`cloudbuild`／`artifactregistry` 三個 API 開好。
- **不建 Cloud SQL 實例**。只開 `sqladmin` API；實例是 M8／Lab 8 才建（而且它是本課最貴的資源，開了要記得刪）。
- **不做 organization / folder 層級的設定**。個人帳號沒有 organization，`gcloud projects create` 不帶 `--organization` 就好。
- **不設 API spend cap（硬上限）**。投影片明確說「budget 只通知不擋費用」，硬上限要走 quota，不在 30 分鐘的時間盒內。
- **不下載 service account JSON 金鑰檔**。附掛（attach）取代金鑰是 2026 標準做法，下載金鑰檔反而是要教學生**不要做**的事。
- **不做 Terraform／Deployment Manager**。這個 Lab 的價值是讓學生看懂每一行 gcloud 在做什麼；IaC 是另一門課。
- **不處理 Workload Identity Federation、VPC-SC、CMEK** 等企業級設定。

## 8. 費用與風險

### 需要付費／需要綁卡

| 項目 | 說明 |
|---|---|
| 綁信用卡 | **這是全課唯一必須綁卡的 Lab**。GCP 的 $300／90 天試用需要信用卡驗證。試用期間不會自動扣款——要手動升級成付費帳戶才會。 |
| 本 Lab 資源費用 | 專案、service account、IAM binding、budget 都不收費。Secret Manager 有 active secret version 的計價，本 Lab 只存一個 version，金額可忽略（投影片沒列 Secret Manager 價目，實際數字看 <https://cloud.google.com/secret-manager/pricing>）。 |
| 一次 API 呼叫 | `vertex_smoke.py` 呼叫一次 `gemini-3.7-flash`，數百 token 等級，落在試用額度內。 |
| 全課估計 | 免費層＋試用額度內；就算全走付費層也 < $10（投影片 p.230）。 |

### 風險與對策

| 風險 | 對策 |
|---|---|
| 忘記刪資源被持續扣款 | 步驟 2 的預算告警是第一道防線（50%／90%／100% 三段寄信）。**在建任何其他資源之前先設好。** |
| 預算告警不會斷電 | budget 只通知不擋費用。真正的保險是「用完就刪專案」，不是靠 alert。 |
| 專案 ID 建立後不可改 | 命名想清楚（例：`agent-course-2026`）。ID 全球唯一，被別人用掉就要換一個。 |
| SA 權限給太大 | 只給 `roles/aiplatform.user` ＋ `roles/secretmanager.secretAccessor`。agent 被 prompt injection 時，權限就是災害半徑（投影片 p.237、附錄 D 第⑩坑）。 |
| SA JSON 金鑰檔外洩 | 不下載。雲端用附掛，本機用 ADC。 |
| 重跑腳本產生重複 budget | `gcloud billing budgets create` 沒有 idempotent 保護，重跑會生第二個同名 budget。`setup.sh` 先用 `budgets list --filter=displayName=...` 查過才建。 |

### 清理指令

```bash
# 建議：整個專案刪掉，資源全部一起消失（最不會漏費用）
./teardown.sh --dry-run     # 先看要刪什麼
./teardown.sh               # 需要打字輸入專案 ID 確認

# 等價的手動指令
gcloud projects delete agent-course-2026
# 30 天內可救回：
gcloud projects undelete agent-course-2026

# 只想清 Lab 5 的資源、專案留給後面的 Lab 用：
./teardown.sh --keep-project
```

> **時機**：M7-M11 全部沿用這個專案。**上完整門課再刪**，不要做完 Lab 5 就刪。

## 9. 前置依賴

| 依賴 | 從哪來 | 沒有會怎樣 |
|---|---|---|
| Google 帳號 | 免費 | 連 `gcloud auth login` 都過不了 |
| 一張信用卡 | 自備 | `gcloud billing accounts list` 是空的，步驟 1 綁不上帳單，後面全部失敗 |
| `gcloud` CLI | macOS `brew install --cask google-cloud-sdk`；Linux `curl https://sdk.cloud.google.com \| bash` | `setup.sh` 直接中止 |
| `uv` | 課程總覽 p.11 已裝 | `uv run vertex_smoke.py` 跑不動 |
| `GEMINI_API_KEY` | **Lab 1 的產物**（<https://aistudio.google.com/apikey>） | 步驟 6 會被跳過（腳本會警告並繼續），少一項驗收 |
| bash 3.2+ | macOS 內建 | — |

**後續依賴這個 Lab 的**：Lab 7（ADK，用 Enterprise 路線）、Lab 8（Cloud SQL、Secret Manager）、Lab 9（A2A 跨服務）、Lab 10（Cloud Run ＋ Agent Engine 部署）、Capstone。
