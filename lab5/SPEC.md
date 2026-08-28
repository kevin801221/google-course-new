# Lab 5 SPEC：課程專用 GCP 專案完整設置

> 模組 M5 ｜ 投影片 p.227-p.245，LAB 頁 p.244

## 1. 架構

這個 Lab 沒有 runtime 服務，只有「本機工具 → GCP 控制平面」的一次性設置流。真正要畫清楚的是**兩條身分邊界**：

```
                   你的筆電（本機）                             │            Google Cloud
                                                                │
  ┌──────────────┐   讀 env   ┌─────────────┐                   │
  │ env.example  │──────────▶ │  setup.sh   │                   │
  │  → .env      │            │  --dry-run  │                   │
  └──────────────┘            └──────┬──────┘                   │
                                     │ eval "gcloud ..."        │
                              ┌──────▼──────┐  身分①            │   ┌──────────────────────────┐
                              │   gcloud    │══════════════════════▶│  Cloud Resource Manager  │
                              │    CLI      │  你的使用者帳號    │   │  Billing / Budgets       │
                              └──────┬──────┘  (~/.config/      │   │  Service Usage (API 開關) │
                                     │          gcloud/         │   │  IAM / Service Accounts  │
                                     │          credentials.db) │   │  Secret Manager          │
                                     │                          │   └──────────────────────────┘
                                     │ gcloud auth              │
                                     │ application-default      │
                                     │ login  ────────┐         │
                                     │                ▼         │
                              ┌──────────────────────────────┐  │
                              │ ~/.config/gcloud/            │  │
                              │  application_default_        │  │
                              │  credentials.json            │  │
                              │  { refresh_token,            │  │
                              │    quota_project_id }        │  │
                              └──────┬───────────────────────┘  │
                                     │ 身分②：ADC              │
                              ┌──────▼──────────┐               │   ┌──────────────────────────┐
   uv run ───────────────────▶│ vertex_smoke.py │══════════════════▶│  Vertex AI (aiplatform)  │
                              │ google-genai    │  Bearer token │   │  gemini-3.7-flash        │
                              │ enterprise=True │               │   └──────────────────────────┘
                              └─────────────────┘               │
                                                                │
                              ┌─────────────┐                   │
                              │  verify.sh  │═══讀取查詢═════════▶│  （上面全部，唯讀）
                              └─────────────┘                   │
                              ┌─────────────┐                   │
                              │ teardown.sh │═══刪除═══════════▶ │  projects.delete
                              └─────────────┘                   │
```

**身分①（gcloud auth login）** 是「你」，給 CLI 用，存在 gcloud 自己的 credential DB。
**身分②（ADC）** 是「你的程式」，給任何 Google SDK 用，存在 `application_default_credentials.json`。
**身分③（附掛 SA）** 這個 Lab 只把 `agent-sa` 建好放著，M10 部署時 `gcloud run deploy --service-account $SA` 才會用到——程式碼一行都不用改，因為 ADC 查找順序第③層會自動從 metadata server 拿憑證。

ADC 查找順序（投影片 p.234），SDK 由上往下找第一個成功的：

```
① $GOOGLE_APPLICATION_CREDENTIALS 指的金鑰檔   ← 不建議，金鑰檔會外洩
② ~/.config/gcloud/application_default_credentials.json  ← 這個 Lab 用這層
③ 執行環境附掛的 service account（metadata server） ← M10 雲端用這層，零金鑰檔
```

## 2. 元件與職責

| 元件 | 職責 | 不負責 |
|---|---|---|
| `setup.sh` | 七個步驟的 idempotent 設置：專案 → 帳單 → 預算 → 六個 API → ADC → SA/IAM → secret | 不驗收（交給 verify.sh）、不刪東西 |
| `setup.sh` 的 `run()` | 印出指令；非 dry-run 才 `eval` 執行 | 不判斷資源存不存在 |
| `setup.sh` 的 `exists()` | 查資源是否已存在；dry-run 一律回「不存在」以便印出建立指令 | 不建立 |
| `setup.sh` 的 `valid_*()` | 用 GCP 真實命名規則驗 `PROJECT_ID` / `SA_NAME` / `BILLING_ACCOUNT`，同時擋掉 `eval` 的 shell injection | 不猜、不自動修正 |
| `verify.sh` | 19 項唯讀檢查，印 ✓／✗，退出碼＝失敗項數 | 不修任何東西（只印該貼的指令） |
| `verify.sh` 的 `check()` | 執行一段檢查指令，成功印 ✓、失敗印 ✗ ＋ `FIXHINT` 並累加 `FAILED` | 不重試、不並行 |
| `vertex_smoke.py` 的 `resolve_route()` | 從環境變數判斷會走 developer／enterprise／none 哪條路線，回傳問題清單 | 不呼叫 API、不 import google-genai |
| `vertex_smoke.py` 的 `call()` | 真的呼叫一次 `gemini-3.7-flash` | 不做重試、不做 streaming |
| `teardown.sh` | 刪除：預設整個專案，`--keep-project` 只刪 secret／IAM binding／SA | 不刪 budget（要完整資源名，腳本只幫你查出來） |
| `env.example` | 課程標準環境變數範本，M5-M11 沿用 | 不自動 source（學生自己複製成 `.env`） |

## 3. 介面契約

### shell 腳本 CLI

```
setup.sh    [--dry-run] | --self-check
verify.sh   [--dry-run] [--with-api] | --self-check
teardown.sh [--dry-run] [--keep-project] | --self-check
```

旗標用 `for arg in "$@"` 迴圈解析，可以任意順序組合；未知旗標 → 印用法、`exit 2`。

退出碼：

| 腳本 | 0 | 非 0 |
|---|---|---|
| `setup.sh` | 全部步驟走完 | `1` = `die()`（缺 BILLING_ACCOUNT、命名不合法、建專案失敗）；`2` = 旗標用錯 |
| `verify.sh` | 19 項全過 | **＝失敗項數**（可直接接 CI）；`2` = 旗標用錯或 `PROJECT_ID`／`SA_NAME` 不合法 |
| `teardown.sh` | 刪除送出 | `1` = 確認字串打錯（什麼都沒刪）；`2` = 旗標用錯或 `PROJECT_ID` 不合法 |

### shell 內部函式簽章

```bash
run()   { : "$1=要執行的 shell 指令字串; ${2:-\$1}=顯示用（可遮罩機密）"; }   # dry-run 只印
exists(){ : "$1=查詢指令字串"; }        # 回 0=存在 / 1=不存在；dry-run 恆回 1
die()   { : "$*=訊息"; }                # 印紅字並 exit 1
check() { : "$1=標籤; $2..=檢查指令"; } # 讀外部變數 FIXHINT；累加 FAILED
confirm(){ : "$1=必須被完整輸入的字串"; } # 打錯就 exit 1；dry-run 直接放行
valid_project_id() / valid_sa_name()    # ^[a-z][a-z0-9-]{4,28}[a-z0-9]$
valid_billing_id()                      # ^[0-9A-F]{6}-[0-9A-F]{6}-[0-9A-F]{6}$
```

### Python 介面

```python
resolve_route(env: Mapping[str, str]) -> tuple[str, str | None, str | None, list[str]]
# 回 (route, project, location, problems)
#   route ∈ {"enterprise", "developer", "none"}
#   problems 是給人看的中文診斷字串清單，含 SDK 會丟的真實錯誤訊息片段

explain(env) -> bool          # 印路線與問題，回 True 表示可以真的呼叫
call(project: str, location: str) -> None   # 呼叫一次 gemini-3.7-flash 並印 output_text
```

### google-genai Client 契約（google-genai 2.20.0，實際讀原始碼確認）

```python
from google import genai

with genai.Client(enterprise=True, project="agent-course-2026", location="us-central1") as client:
    it = client.interactions.create(model="gemini-3.7-flash", input="...")
print(it.output_text)          # 文字
print(it.usage.total_tokens)   # token 統計
```

| 欄位 | 說明 |
|---|---|
| `enterprise=True` | 2026 現行參數名。`vertexai=True` 是 legacy 別名（`client.py` 的 docstring 寫 `vertexai (bool): Legacy flag for enterprise.`），兩個都給且值衝突會丟 `ValueError: enterprise and vertexai flags have conflicting values, please set enterprise value only.`。 |
| `project` / `location` | 不給就從 `GOOGLE_CLOUD_PROJECT` / `GOOGLE_CLOUD_LOCATION` 讀；都沒有就從 ADC 撈，撈不到丟 `Could not resolve project using application default credentials.` |
| `with ...` | 必須。`genai.Client().interactions.create(...)` 的 Client 是暫時物件，請求送出前被 GC 關掉 → `RuntimeError: Cannot send a request, as the client has been closed.` |

### gcloud 指令契約（本 Lab 用到的全部）

| 動作 | 指令 | idempotent？ |
|---|---|---|
| 建專案 | `gcloud projects create ID --name=N` | ✗ 重跑 → `ALREADY_EXISTS`，要先 `projects describe` |
| 設預設專案 | `gcloud config set project ID` | ✓ |
| 查帳單帳戶 | `gcloud billing accounts list` | ✓（唯讀） |
| 綁帳單 | `gcloud billing projects link ID --billing-account=B` | ✓（set 語意） |
| 建預算 | `gcloud billing budgets create --billing-account=B --display-name=D --budget-amount=25USD --threshold-rule=percent=0.5 ...` | **✗ 重跑會生第二個同名 budget**，要先 `budgets list --filter="displayName=D"` |
| 開 API | `gcloud services enable A B C --project=ID` | ✓（已開的直接回 OK） |
| ADC 登入 | `gcloud auth application-default login` | ✓（覆寫），但會開瀏覽器 |
| 設 quota project | `gcloud auth application-default set-quota-project ID` | ✓ |
| 建 SA | `gcloud iam service-accounts create N --project=ID` | ✗ 重跑 → `ALREADY_EXISTS`，要先 `describe` |
| 綁 role | `gcloud projects add-iam-policy-binding ID --member=serviceAccount:E --role=R --condition=None` | ✓（已有的 binding 是 no-op） |
| 建 secret | `printf '%s' "$V" \| gcloud secrets create N --data-file=-` | ✗ 重跑 → `ALREADY_EXISTS`，改用 `versions add` |
| 加 secret 版本 | `printf '%s' "$V" \| gcloud secrets versions add N --data-file=-` | ✓（每次一個新版本，可回滾） |
| 刪專案 | `gcloud projects delete ID` | ✓（30 天內可 `undelete`） |

## 4. 資料模型

沒有 DB。有三個「狀態存在哪裡」要知道：

| 狀態 | 位置 | 內容 |
|---|---|---|
| gcloud 設定 | `~/.config/gcloud/configurations/config_default` | `[core] project=`、`[run] region=` |
| ADC | `~/.config/gcloud/application_default_credentials.json` | `{"client_id":..., "refresh_token":..., "quota_project_id":"agent-course-2026", "type":"authorized_user"}` |
| Secret Manager | GCP 端 | `projects/<PROJ>/secrets/gemini-api-key/versions/1..N`，每個 version 有 state（`ENABLED` / `DISABLED` / `DESTROYED`） |

`CLOUDSDK_CONFIG` 環境變數可以蓋掉 `~/.config/gcloud` 這個路徑，`verify.sh` 檢查 quota project 時有處理（`"${CLOUDSDK_CONFIG:-$HOME/.config/gcloud}"`）。這項檢查先 `tr -d ' \n'` 再 grep，所以 gcloud 寫成縮排 JSON 或壓成一行都認得（兩種形狀都本機驗過）。

IAM policy 的形狀（`gcloud projects get-iam-policy` 回的）：

```yaml
bindings:
- members: ["serviceAccount:agent-sa@agent-course-2026.iam.gserviceaccount.com"]
  role: roles/aiplatform.user
- members: ["serviceAccount:agent-sa@agent-course-2026.iam.gserviceaccount.com"]
  role: roles/secretmanager.secretAccessor
- members: ["user:you@example.com"]
  role: roles/owner
```

## 5. 檔案結構

```
lab5/
├── PRD.md            產品需求：為什麼做、學什麼、驗收什麼、花多少錢
├── SPEC.md           本檔：架構、契約、錯誤處理
├── walkthrough.md    一步一步教學（最重要）
├── setup.sh          七步 idempotent 設置；--dry-run / --self-check
├── verify.sh         19 項驗收檢查，印 ✓/✗；--dry-run / --with-api / --self-check
├── teardown.sh       清理；預設刪整個專案，--keep-project 只刪 Lab 資源
├── vertex_smoke.py   Enterprise 路線連通性測試；--self-check / --explain
├── env.example       課程標準環境變數範本（p.242），複製成 .env
├── pyproject.toml    uv 專案定義，唯一依賴 google-genai>=2.20.0
├── uv.lock           鎖版本（uv run 自動維護）
└── .venv/            uv 自建，不要碰、不要 commit
```

## 6. 環境變數與設定

### SDK 讀的（Enterprise 路線三件套）

| 變數 | 用途 | 從哪來 | 預設 |
|---|---|---|---|
| `GOOGLE_GENAI_USE_ENTERPRISE` | 切到 Vertex／Enterprise 路線 | 手動 export；`setup.sh` 最後會印出來 | 無（不設就走 developer 路線） |
| `GOOGLE_GENAI_USE_VERTEXAI` | 同上，2025 舊名，SDK 仍相容 | — | 無。**兩個都設且值衝突 → SDK 印警告並以 `USE_ENTERPRISE` 為準** |
| `GOOGLE_CLOUD_PROJECT` | 專案 ID | 你的 `PROJECT_ID` | 無；不設則從 ADC 撈 |
| `GOOGLE_CLOUD_LOCATION` | 區域 | 課程統一 `us-central1` | 無 |
| `GEMINI_API_KEY` | AI Studio 金鑰（developer 路線） | Lab 1 的產物 | 無。跑 Enterprise 時建議 unset：優先權規則有三個分支，而 SDK 只用 `logger.info` 記錄，預設看不到 |
| `GOOGLE_API_KEY` | ADK 讀的同義變數 | 值同 `GEMINI_API_KEY` | 無 |
| `GOOGLE_APPLICATION_CREDENTIALS` | ADC 查找順序① 的金鑰檔路徑 | **本課不用** | 無 |

### 腳本讀的（不是 SDK 讀的）

| 變數 | 用途 | 從哪來 | 預設 |
|---|---|---|---|
| `PROJECT_ID` | 專案 ID | 你自己想（全球唯一） | `agent-course-2026` |
| `PROJECT_NAME` | 專案顯示名 | — | `Agent Course` |
| `BILLING_ACCOUNT` | 帳單帳戶 ID | `gcloud billing accounts list` | 空。**非 dry-run 時空值直接中止** |
| `REGION` | 區域 | — | `us-central1` |
| `BUDGET_AMOUNT` | 預算金額 | LAB 頁指定 | `25USD` |
| `BUDGET_NAME` | 預算 display name | — | `course-budget` |
| `SA_NAME` | service account 名 | LAB 頁指定 | `agent-sa` |
| `SECRET_NAME` | secret 名 | — | `gemini-api-key` |
| `NOTIFY_EMAIL` | 預算通知信箱（只印提示，gcloud 無法直接帶） | 你自己的信箱 | 空 |
| `CLOUDSDK_CONFIG` | gcloud 設定目錄 | gcloud 官方變數 | `~/.config/gcloud` |

## 7. 執行流程

從零到驗收，全部在 `lab5/` 目錄下：

```bash
cd $COURSE/lab5

# ── 階段 A：離線（不需要 GCP 帳號）─────────────────────────────
./setup.sh --self-check           # 驗設置腳本邏輯（用假 gcloud）
./verify.sh --self-check          # 驗檢查器邏輯
./teardown.sh --self-check        # 驗確認機制
uv run vertex_smoke.py --self-check   # 驗路線判斷邏輯
./setup.sh --dry-run              # 看完整指令序列（可投影給學生看）

# ── 階段 B：裝 gcloud 並登入 ──────────────────────────────────
brew install --cask google-cloud-sdk      # macOS
gcloud init                                # 登入 + 選專案 + 預設區域
gcloud billing accounts list               # 抄下 ACCOUNT_ID

# ── 階段 C：真的設置 ──────────────────────────────────────────
export PROJECT_ID=agent-course-2026-你的後綴
export BILLING_ACCOUNT=XXXXXX-XXXXXX-XXXXXX
export GEMINI_API_KEY=<Lab 1 那把>
./setup.sh                        # 七步跑完；中途會開瀏覽器做 ADC 授權

# ── 階段 D：驗收 ──────────────────────────────────────────────
export GOOGLE_GENAI_USE_ENTERPRISE=True
export GOOGLE_CLOUD_PROJECT=$PROJECT_ID
export GOOGLE_CLOUD_LOCATION=us-central1
unset GEMINI_API_KEY              # 避免兩套憑證互搶（SDK 只記 INFO log，預設看不到）
uv run vertex_smoke.py            # 應印出一句中文
./verify.sh --with-api            # 19 項全綠，exit 0

# ── 階段 E：清理（上完 M11 再做）─────────────────────────────
./teardown.sh --dry-run
./teardown.sh
```

`setup.sh` 內部順序（不可重排的地方）：

```
1 專案            ← 沒有專案，後面全部無處可放
2 帳單 → 預算      ← 預算要綁 billing account，所以在帳單之後；但在開 API 之前（投影片 p.230：花任何錢之前先設 alert）
3 六個 API        ← secretmanager 沒開，步驟 6 會 403；aiplatform 沒開，步驟 7 會 403
4 ADC             ← Python 要靠它證明身分
5 SA + IAM        ← 需要 IAM API（專案建立時預設就開）
6 secret          ← 需要 secretmanager API（步驟 3）
7 印出 Enterprise 三件套
```

## 8. 錯誤處理與邊界

| 情境 | 症狀（真實訊息） | 處理方式 |
|---|---|---|
| `gcloud` 沒裝 | `gcloud: command not found` | `setup.sh` 非 dry-run 時 `die()` 並印 brew 指令；`verify.sh` 第一項就紅叉 |
| 沒給 `BILLING_ACCOUNT` | — | `die("沒給 BILLING_ACCOUNT。先跑 gcloud billing accounts list...")`，不會跑到任何 gcloud |
| `BILLING_ACCOUNT` 格式錯 | — | 正規式擋掉並印出正確格式 `XXXXXX-XXXXXX-XXXXXX` |
| `PROJECT_ID` 不合法（大寫、太短、結尾連字號、含分號） | GCP 會回 `Invalid project ID` | 本地正規式先擋，順便擋掉 `eval` 的 injection |
| 專案 ID 被別人用掉 | `ERROR: (gcloud.projects.create) Project creation failed. ... requested entity already exists` | `die()` 提示換一個 ID（全球唯一） |
| 專案已是自己的 | — | `exists "gcloud projects describe ..."` 命中 → 跳過建立，印「已存在」 |
| 帳單沒綁就開付費 API | `FAILED_PRECONDITION: Billing account for project ... is not found. Billing must be enabled` | 步驟 2 排在步驟 3 之前 |
| 沒有 Billing Account Administrator 權限 | `PERMISSION_DENIED: The caller does not have permission` | `die()` 提示確認帳單帳戶與權限 |
| 重跑 `budgets create` | 沒有錯誤，但**多出一個同名 budget**（沉默的重複） | 先 `budgets list --filter="displayName=..."` 查過才建 |
| API 沒開就呼叫 | `403 PERMISSION_DENIED: Vertex AI API has not been used in project <ID> before or it is disabled.` | 步驟 3 一次開六個；`verify.sh` 逐個 API 檢查 |
| API 剛開就呼叫 | 同上 403（GCP 端要幾十秒生效） | 等 1-2 分鐘重跑 `verify.sh` |
| ADC 沒設 | `google.auth.exceptions.DefaultCredentialsError: Your default credentials were not found. To set up Application Default Credentials, see https://cloud.google.com/docs/authentication/external/set-up-adc for more information.` | 步驟 4 引導 `gcloud auth application-default login` |
| ADC 沒設 quota project | `UserWarning: Your application has authenticated using end user credentials from Google Cloud SDK without a quota project. You might receive a "quota exceeded" or "API not enabled" error.` | `gcloud auth application-default set-quota-project <ID>` |
| 只做了 `gcloud auth login` 沒做 ADC | 同 `DefaultCredentialsError`——CLI 通了但 Python 不通 | 兩個 login 是不同的東西，都要做 |
| `GOOGLE_GENAI_USE_ENTERPRISE` 沒設（或值不是 `true`/`1`） | `ValueError: No API key was provided. Please pass a valid API key. Learn how to create an API key at https://ai.google.dev/gemini-api/docs/api-key.` | `resolve_route()` 事先攔下來並印出三件套 |
| `GOOGLE_CLOUD_PROJECT` 沒設且 ADC 撈不到 | `ValueError: Could not resolve project using application default credentials.` | `resolve_route()` 事先攔下 |
| Enterprise 與 API key 同時存在 | 明確傳入的 `project`/`location` 會贏、環境變數的 api key 被清掉，但 SDK 只用 `logger.info` 記這件事（預設看不到），行為不直覺 | `resolve_route()` 列為 problem；建議 `unset GEMINI_API_KEY` |
| `enterprise=` 與 `vertexai=` 同時給且衝突 | `ValueError: enterprise and vertexai flags have conflicting values, please set enterprise value only.` | 只給 `enterprise=True` |
| `genai.Client()` 沒用 `with` | `RuntimeError: Cannot send a request, as the client has been closed.` | 一律 `with genai.Client(...) as client:` |
| 用 `python vertex_smoke.py` | `ModuleNotFoundError: No module named 'google'` | 一律 `uv run vertex_smoke.py` |
| secret 已存在還跑 `secrets create` | `ERROR: (gcloud.secrets.create) ALREADY_EXISTS: Secret [gemini-api-key] already exists.` | `exists` 命中改走 `versions add` |
| secret 用 `echo` 而非 `printf` 存入 | 值尾多一個 `\n`，讀回來字串不等 | `printf '%s'`（或 `echo -n`）＋ `--data-file=-` |
| `PROJECT_ID` 含 shell 特殊字元 | 可能被 `eval` 執行 | 三支腳本都在任何 `eval` 之前用同一組 GCP 命名正規式擋掉並 `exit 2`（`setup.sh` 的 `valid_*()`；`verify.sh`／`teardown.sh` 在檔頭直接擋，teardown 尤其重要——它是會刪東西的那支） |
| 非 tty 輸出 | 管線裡出現 `\033[32m` 之類垃圾 | `[ -t 1 ]` 判斷，非 tty 用 `[ OK ]`／`[FAIL]` |
| bash 3.2（macOS 內建）遇到 `$VAR` 緊接中文全形括號 | `line N: PROJECT_ID?: unbound variable` | 全形字元前一律寫 `${VAR}` |
| teardown 打錯確認字串 | — | `confirm()` 立刻 `exit 1`，一個 gcloud 都不會跑（self-check 驗過） |

## 9. 驗證方式

### 自我檢查（不連網、不花錢、不需要 GCP 帳號）

三支 shell 腳本的 `--self-check` 都用同一招：**在 `PATH` 前面塞一支假的 `gcloud`**，它一被呼叫就 `touch` 一個哨兵檔案並回非零。然後跑 `--dry-run`，斷言：

1. 哨兵檔案**沒有**被建立 → 證明 dry-run 真的不執行任何指令。
2. dry-run 的輸出包含該有的東西（六個 API 名、三段 `--threshold-rule=percent=`、兩個 role、`gcloud secrets create`、`GOOGLE_GENAI_USE_ENTERPRISE=True`…）。
3. 輸出裡沒有 ANSI escape（非 tty）。

另外各自驗自己的關鍵邏輯：

| 腳本 | self-check 驗什麼 |
|---|---|
| `setup.sh` | 上面三項 ＋ `valid_project_id` / `valid_billing_id` 的正負例（大寫、太短、結尾連字號、`x; rm -rf /`、短 billing id）＋ 沒給 `BILLING_ACCOUNT` 且非 dry-run 一定中止 |
| `verify.sh` | `check "x" "true"` 不計失敗且印出標籤；`check "x" "false"` 讓 `FAILED` 變 1 且印出 `FIXHINT`；`FIXHINT` 用完會清掉（不然下一項失敗會沿用上一項的修法，誤導學生）；dry-run 列出 aiplatform／secretAccessor／quota_project_id／billingEnabled 四類檢查；dry-run 不呼叫 gcloud |
| `teardown.sh` | 預設模式印 `projects delete` ＋ `undelete` 提示；`--keep-project` **不**印 `projects delete`；`remove-iam-policy-binding` 的行號必須小於 `service-accounts delete`（順序反了 binding 會留下孤兒 member）；未知旗標 `exit 2`；`PROJECT_ID='x; rm -rf /tmp/nope'` 要在碰到 confirm 之前就 `exit 2` 且沒跑任何 gcloud；確認字串打錯 → 非零退出且一個 gcloud 都沒跑 |
| `vertex_smoke.py` | `resolve_route()` 九組情境：三件套齊全、舊名 `USE_VERTEXAI`、缺 project、缺 location、值寫 `yes`（SDK 不認，必須被判成沒設）、值寫 `True!`、值寫 `1`、什麼都沒有、只有 API key、Enterprise ＋ API key 並存 |

跑法：

```bash
./setup.sh --self-check && ./verify.sh --self-check && ./teardown.sh --self-check \
  && uv run vertex_smoke.py --self-check
```

### 驗收怎麼看

```bash
./verify.sh              # 19 項，✓/✗；紅叉下面直接印該貼的指令
echo $?                  # 0 = 全過；非 0 = 失敗項數
./verify.sh --with-api   # 再加一項：真的打一次 Gemini
./verify.sh | cat        # 管線裡看 → 自動變 [ OK ] / [FAIL]
```

### 已離線驗過的（本機實跑）

- `bash -n` 三支腳本語法
- `setup.sh --self-check` / `verify.sh --self-check` / `teardown.sh --self-check`
- `uv run vertex_smoke.py --self-check`
- `./setup.sh --dry-run`、`./verify.sh --dry-run`、`./teardown.sh --dry-run` 的完整輸出
- `google-genai` 2.20.0 原始碼：`enterprise=` / `vertexai=` 參數、`GOOGLE_GENAI_USE_ENTERPRISE` 環境變數、`No API key was provided`、`Could not resolve project using application default credentials.`；`google-auth` 的 `Your default credentials were not found.` 與 quota project 警告原文
- **本機實跑重現** `google.auth.exceptions.DefaultCredentialsError: Your default credentials were not found. ...`：這台機器沒有 ADC，`GOOGLE_GENAI_USE_ENTERPRISE=True GOOGLE_CLOUD_PROJECT=agent-course-2026 GOOGLE_CLOUD_LOCATION=us-central1 uv run vertex_smoke.py` 走到 `_api_client.py:1301 → google/auth/_default.py:748` 丟出此例外——證明 `resolve_route()` 放行後真的會打到 ADC 那一層
- `uv run vertex_smoke.py --explain` 的兩條分支（空環境 → `路線：none` exit 1；Enterprise ＋ API key 並存 → `路線：enterprise` ＋ 警告 exit 0）

### 沒辦法離線驗的

> ⚠️ 未實測：以下全部需要真的 GCP 帳號＋已綁信用卡的 billing account，本機沒有安裝 gcloud（`gcloud: command not found`），無法執行。

- 所有 `gcloud` 指令的真實行為與輸出格式（專案建立、帳單綁定、budget 建立、API 啟用、IAM binding、Secret Manager）
- 各項 `gcloud ... --format=...` 查詢的實際回傳字串是否與 `verify.sh` 的 `grep` 樣式相符
- `gcloud auth application-default login` 的瀏覽器授權流程與寫出的 JSON 欄位名
- `vertex_smoke.py` 真的呼叫 `gemini-3.7-flash` 是否成功（型號名以投影片為準；若 404，用 `client.models.list()` 確認現行型號）
- 錯誤訊息表中標記為 gcloud 端的訊息（`ALREADY_EXISTS`、`FAILED_PRECONDITION`、`403 PERMISSION_DENIED`）是原文格式，但未在本機重現

## 10. 已知限制與升級路徑

| 限制 | 程式碼位置 | 升級路徑 |
|---|---|---|
| `run()` 與 `check()` 用 `eval` 跑字串指令 | `setup.sh` / `verify.sh` / `teardown.sh` | 字串都是腳本內的常值，外部輸入（`PROJECT_ID` / `SA_NAME` / `BILLING_ACCOUNT`）在任何 `eval` 之前用正規式驗過。要更硬就改成陣列 ＋ `"${cmd[@]}"`，但那樣沒辦法帶 pipe，`check()` 得整組重寫。 |
| dry-run 一律假設「資源不存在」 | `setup.sh` 的 `exists()` | 這是刻意的：dry-run 要印出**完整**指令序列給學生看。想看「已存在時會跳過什麼」就直接跑真的。 |
| budget 通知信箱沒辦法用 gcloud 一行帶入 | `setup.sh` 步驟 2 | `gcloud billing budgets create` 的通知要先建 Monitoring notification channel 再用 `--notifications-rule-monitoring-notification-channels` 綁。30 分鐘時間盒內不值得，改成印提示叫學生去 Console 加一次。 |
| `teardown.sh --keep-project` 不自動刪 budget | `teardown.sh` | budget 要用完整資源名 `billingAccounts/X/budgets/Y` 才刪得掉。腳本幫你查出名字，刪的那一行留給你自己貼——避免手滑刪掉別的專案的 budget。 |
| 檢查是序列執行，19 項各一次 gcloud 往返 | `verify.sh` | 約 20-40 秒。要快就改成把 `services list`、`get-iam-policy` 各查一次後在本地比對。項數這麼少不值得。 |
| `vertex_smoke.py` 不重試、不 streaming | `vertex_smoke.py` 的 `call()` | 這是連通性測試，不是應用。streaming 是 Lab 1 的主題。 |
| `resolve_route()` 只認 `true`/`1`（與 SDK 對齊） | `vertex_smoke.py` | 判斷規則抄自 `_api_client.py:655-662`（`env_str.lower() in ['true','1']`）。本函式是「事先攔下來給人看得懂的錯誤」，不是 SDK 行為的完整複製（例如 express-mode API key 的三個優先權分支就沒複製）。SDK 若改判斷規則，這裡要跟著改。 |
| 沒有做 organization / folder 層級 | 全部 | 個人帳號沒有 organization。企業環境要加 `--organization` 或 `--folder`。 |
