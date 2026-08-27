# Lab 5 走一遍：課程專用 GCP 專案完整設置

> 30–40 分鐘（投影片 p.244）｜ 之後 M7-M11 所有部署 Lab 的地基——做完一次，後面全程沿用
> 下面每一步的分鐘數加起來是 44 分：步驟 0 那段離線預習可以課前先做，真正動帳號的部分約 35 分。
> **這是全課唯一需要綁信用卡的 Lab。**先看完「步驟 0」再決定要不要往下。

做完你會有一個「已綁帳單、已設預算告警、六個 API 全開、ADC 通了、`agent-sa` 建好授權好、第一個 secret 存進去」的 GCP 專案，以及一支能逐項告訴你哪裡沒設好的驗收腳本：

```
$ ./verify.sh
檢查專案 agent-course-2026（region us-central1）

✓ gcloud 已安裝
✓ 已登入 gcloud（有 active account）
✓ config 的 project 是 agent-course-2026
✓ config 的 run/region 是 us-central1
✓ 帳單已綁定（billingEnabled=True）
✓ 預算告警 'course-budget' 存在
✓ API 已啟用：aiplatform.googleapis.com
✓ API 已啟用：run.googleapis.com
✓ API 已啟用：cloudbuild.googleapis.com
✓ API 已啟用：artifactregistry.googleapis.com
✓ API 已啟用：secretmanager.googleapis.com
✓ API 已啟用：sqladmin.googleapis.com
✓ ADC 可取得 access token
✗ ADC quota project 是 agent-course-2026
    修：gcloud auth application-default set-quota-project agent-course-2026
✓ service account agent-sa@agent-course-2026.iam.gserviceaccount.com 存在
✓ SA 有角色：roles/aiplatform.user
✓ SA 有角色：roles/secretmanager.secretAccessor
✓ secret 'gemini-api-key' 至少有一個 enabled 版本
· Python 走 Enterprise 路線呼叫得動 Gemini（跳過）
    加 --with-api 才會真的打一次 API

有 1 項沒過。照每項下面的「修：」處理完再跑一次。
```

> ⚠️ 未實測：上面這段是 `verify.sh` 的實際輸出格式（tty 版），但每一項的 ✓／✗ 需要真的 GCP 帳號才會跑出來。本機沒有 gcloud（`gcloud: command not found`），無法端到端重現。腳本的邏輯本身用 `--self-check` 與 `--dry-run` 離線驗過（見步驟 0）。

每一步都有「動手 → 為什麼 → 驗收」。**驗收沒過不要往下走**，GCP 的錯誤訊息會在三步之後才浮出來，那時候更難 debug。

---

## 步驟 0：前置（5 分，不用花錢）

### 動手

先確認手上有什麼：

```bash
gcloud --version          # 沒有？往下看安裝
uv --version              # 課程總覽 p.11 已經裝過
echo $GEMINI_API_KEY      # Lab 1 的產物，步驟 6 要用
```

沒有 gcloud 就裝（投影片 p.233）：

```bash
# macOS
brew install --cask google-cloud-sdk
# Linux
curl https://sdk.cloud.google.com | bash && exec -l $SHELL
# Windows：用 WSL2，然後照 Linux 那行
```

然後**在花任何錢之前**，先在本機把整套邏輯跑一遍。這一段完全不連網、不需要 GCP 帳號、不需要信用卡：

```bash
cd /Users/awesomeartengineer01/Antigravity-teach/lab5

./setup.sh --self-check
./verify.sh --self-check
./teardown.sh --self-check
uv run vertex_smoke.py --self-check

./setup.sh --dry-run          # 看它「會做什麼」，一行都不會真的跑
```

`--dry-run` 會印出完整指令序列：

```
==> 1/7 建立專案 agent-course-2026
    $ gcloud projects create agent-course-2026 --name="Agent Course"
    $ gcloud config set project agent-course-2026
    $ gcloud config set run/region us-central1

==> 2/7 綁帳單並設 25USD 預算告警（50%/90%/100%）
    $ gcloud billing projects link agent-course-2026 --billing-account=XXXXXX-XXXXXX-XXXXXX
    $ gcloud billing budgets create --billing-account=XXXXXX-XXXXXX-XXXXXX --display-name="course-budget" --budget-amount=25USD --threshold-rule=percent=0.5 --threshold-rule=percent=0.9 --threshold-rule=percent=1.0
    ! budget 只通知、不斷電。要硬上限得用 API spend cap 或 quota。
...
```

### 為什麼

**為什麼要有 `--dry-run`？** 因為這個 Lab 動的是你的信用卡帳戶。一支你沒看過內容的腳本要 `gcloud projects create` ＋ `billing projects link`，你應該先看它要打哪些指令。`--dry-run` 的實作是一個 `run()` 函式：

```bash
run() {
  printf '    $ %s\n' "${2:-$1}"
  ${DRY_RUN} && return 0     # ← dry-run 在這裡就 return，下面那行不會執行
  eval "$1"
}
```

**不這樣寫會怎樣**：學生只能靠讀 200 行 shell 猜它會做什麼，或者直接跑下去然後在自己帳號上留下一個名字打錯、ID 改不掉的專案（專案 ID 建立後**不可改**）。

**`--self-check` 又在驗什麼？** 驗「dry-run 真的沒有執行任何東西」。做法是在 `PATH` 最前面塞一支假的 `gcloud`：

```bash
printf '#!/bin/sh\necho "$@" >> "%s/CALLED"\nexit 1\n' "$SC_TMP" > "$SC_TMP/gcloud"
out="$(PATH="$SC_TMP:$PATH" "$0" --dry-run 2>&1)"
[ ! -f "$SC_TMP/CALLED" ] || { echo "  ✗ dry-run 竟然真的呼叫了 gcloud"; }
```

假 gcloud 一被呼叫就留下痕跡。哨兵檔案沒出現 → 證明 dry-run 是惰性的。**不這樣寫會怎樣**：`--dry-run` 只是一句口頭承諾。有人後來在腳本裡加了一行忘記包 `run()`，dry-run 就會偷偷動你的帳號，而且沒有任何測試會抓到。

### 驗收

四行都要印出「全部通過」：

```bash
$ ./setup.sh --self-check
setup.sh --self-check 全部通過
$ ./verify.sh --self-check
verify.sh --self-check 全部通過
$ ./teardown.sh --self-check
teardown.sh --self-check 全部通過
$ uv run vertex_smoke.py --self-check
vertex_smoke.py --self-check 全部通過
```

順手踩一次最常見的坑：

```bash
$ python vertex_smoke.py --self-check
ModuleNotFoundError: No module named 'google'
```

**這個 Lab（以及整門課）一律 `uv run`，不用 `python`、不用 `pip install`、不用 `activate`。** 依賴記在 `pyproject.toml` ＋ `uv.lock`，`uv run` 會自己準備環境。

---

## 步驟 1：建立專案並綁帳單（7 分）

### 動手

先查你的 billing account ID（沒綁卡的話這裡會是空的，去 <https://console.cloud.google.com/billing> 開通 $300 試用）：

```bash
gcloud auth login                    # 如果還沒登入
gcloud billing accounts list
```

```
ACCOUNT_ID            NAME                OPEN  MASTER_ACCOUNT_ID
01ABCD-234567-89EF00  My Billing Account  True
```

抄下 `ACCOUNT_ID`，然後：

```bash
export PROJECT_ID=agent-course-2026-你的後綴      # ID 全球唯一，想清楚
export BILLING_ACCOUNT=01ABCD-234567-89EF00
export GEMINI_API_KEY=<Lab 1 那把>

./setup.sh
```

腳本的步驟 1 等價於手打這三行：

```bash
gcloud projects create $PROJECT_ID --name="Agent Course"
gcloud config set project $PROJECT_ID
gcloud config set run/region us-central1
```

**先故意做錯一次**——把 `gcloud projects create` 那行再貼一次：

```
ERROR: (gcloud.projects.create) Project creation failed. The project ID you specified is already in use by another project. Please try an alternative ID.
```

或者專案是你自己的：

```
ERROR: (gcloud.projects.create) Resource already exists in the project (resource=agent-course-2026): {}
```

現在改成跑 `./setup.sh` 第二次：

```
==> 1/7 建立專案 agent-course-2026
    已存在，跳過建立（這就是 idempotent：重跑不會撞 ALREADY_EXISTS）
```

### 為什麼

**為什麼要 idempotent？** 因為這七個步驟裡有一步（ADC）會開瀏覽器、有一步（開六個 API）要等一兩分鐘。中途被 Ctrl-C、網路斷掉、瀏覽器授權失敗，都很正常。腳本必須能從中斷處重跑。

做法就是每個「建立」動作前面先查一次：

```bash
if exists "gcloud projects describe ${PROJECT_ID}"; then
  note "已存在，跳過建立"
else
  run "gcloud projects create ${PROJECT_ID} --name=\"${PROJECT_NAME}\""
fi
```

**不這樣寫會怎樣**：重跑第二次時，`gcloud projects create` 回非零、`set -e` 的腳本當場中止在第 1 步——而你真正要跑的是第 5 步。學生會以為「我的專案壞了」，然後去刪專案重來（專案 ID 不可重用，於是又要換名字）。

**為什麼 `PROJECT_ID` 要先驗格式？** 腳本裡有這一行：

```bash
valid_project_id() { printf '%s' "$1" | grep -Eq '^[a-z][a-z0-9-]{4,28}[a-z0-9]$'; }
```

這是 GCP 的真實規則：6-30 字、小寫字母開頭、只能小寫字母／數字／連字號、結尾不能是連字號。**不這樣寫會怎樣**：兩件事。一是你要等 GCP 往返一次才知道 `Agent-Course-2026` 這個名字不合法（大寫不行）；二是 `run()` 用 `eval` 執行指令字串，`PROJECT_ID='x; rm -rf ~'` 這種值會被真的執行。正規式同時解決這兩件事——`--self-check` 裡就有一條斷言 `valid_project_id 'x; rm -rf /'` 必須回 false。

**為什麼順序是「先建專案、再綁帳單、才開 API」？** 付費 API 在沒綁帳單的專案上啟用會噴：

```
ERROR: FAILED_PRECONDITION: Billing account for project '123456789' is not found. Billing must be enabled for activation of service(s) to complete.
```

### 驗收

```bash
$ gcloud config list
[core]
account = you@example.com
project = agent-course-2026
[run]
region = us-central1

$ gcloud billing projects describe $PROJECT_ID --format='value(billingEnabled)'
True
```

`billingEnabled` 印出 `True` 才算過。印 `False` 或空的 → 帳單沒綁上，回頭確認 `BILLING_ACCOUNT` 的值。

> ⚠️ 未實測：這一步的所有 gcloud 輸出與錯誤訊息（`gcloud config list`、`billingEnabled`、`Project creation failed.`）都需要真帳號才跑得出來，本機沒有 gcloud（`gcloud: command not found`）。訊息格式抄自投影片 p.231 與 GCP 慣用格式；腳本的 idempotent 邏輯本身用 `--self-check` 離線驗過。

---

## 步驟 2：設定 $25 預算告警（5 分）

### 動手

`setup.sh` 已經幫你做了。等價的手打指令（投影片 p.231）：

```bash
gcloud billing budgets create \
    --billing-account=$BILLING_ACCOUNT \
    --display-name="course-budget" \
    --budget-amount=25USD \
    --threshold-rule=percent=0.5 \
    --threshold-rule=percent=0.9 \
    --threshold-rule=percent=1.0
```

**故意做錯**：把上面那段再貼一次。它**不會報錯**。然後：

```bash
$ gcloud billing budgets list --billing-account=$BILLING_ACCOUNT --format='table(displayName, amount.specifiedAmount.units)'
DISPLAY_NAME   UNITS
course-budget  25
course-budget  25       ← 兩個一樣的
```

這是本 Lab 最陰的一個坑：**`budgets create` 不是 idempotent，而且失敗方式是「沉默地多一份」**。所以 `setup.sh` 自己先查：

```bash
if exists "gcloud billing budgets list --billing-account=${billing} --filter=\"displayName=${BUDGET_NAME}\" --format='value(name)' | grep -q ."; then
  note "預算 '${BUDGET_NAME}' 已存在，跳過（不然會多出一個同名 budget）"
else
  run "gcloud billing budgets create ..."
fi
```

通知信箱要到 Console 加一次：<https://console.cloud.google.com/billing> → Budgets & alerts → `course-budget` → Manage notifications → 勾 Billing account administrators 或填自己的 email。

### 為什麼

**為什麼這步排在開 API 之前？** 投影片 p.230 第 5 點直接寫了：「在花任何錢之前先設 alert」。開 API 本身不花錢，但開完 API 之後你就有能力開 Cloud SQL 實例（本課最貴的資源）。先把告警架好，順序不能倒。

**為什麼是三段門檻而不是一段？** 50% 是「注意一下」，90% 是「該去看是什麼在吃錢」，100% 是「已經超了」。只設一段 100% 的話，你收到信的時候錢已經花完了。

**`budget` 不會斷電。** 這句話要記住：budget 只寄信，不會擋任何請求。要真的硬上限得用 API spend cap 或 quota。所以真正的保險不是 alert，而是「用完就刪」——見文末的清理段落。

**`--budget-amount=25USD` 為什麼要帶單位？** 不帶單位 gcloud 會拒絕解析。金額格式是 `<數字><貨幣代碼>`。

### 驗收

```bash
$ gcloud billing budgets list --billing-account=$BILLING_ACCOUNT \
    --filter="displayName=course-budget" --format='value(name)'
billingAccounts/01ABCD-234567-89EF00/budgets/1a2b3c4d-....
```

只能印出**一行**。印出兩行 → 你重跑了 `budgets create`，把多的那個刪掉：

```bash
gcloud billing budgets delete billingAccounts/01ABCD-234567-89EF00/budgets/<多的那個 ID>
```

再到 Console 確認三段門檻都在、通知信箱是自己的。

> ⚠️ 未實測：budget 的 `--threshold-rule` 是否真的三段都建起來、通知信是否寄達，需要真帳號驗證。

> 💡 **啊哈：任何「逐項刪」的清理清單註定落後於資源 —— 所以刪整個專案的指令比它更短，也更完整。**
> 專案是計費邊界，刪它一次涵蓋**所有**資源型別，包括你明天才會建、今天還寫不進清單的那些（M7-M11 的 Cloud Run 服務、Artifact Registry image、Cloud SQL 實例）。
> 這件事在 `teardown.sh` 裡量得出來：刪專案 2 行指令就結束，逐項刪要 5 行、而那 5 行只蓋到 Lab 5 建的 3 種資源（secret／SA＋binding／budget）。
> **動手看**：`./teardown.sh --dry-run | grep -c '\$ gcloud'` → `2`；`./teardown.sh --keep-project --dry-run </dev/null | grep -c '\$ gcloud'` → `5`。

---

## 步驟 3：啟用六個 API（5 分）

### 動手

先看現在有什麼（新專案幾乎是空的）：

```bash
$ gcloud services list --enabled --format='value(config.name)' | grep -E 'aiplatform|^run\.|cloudbuild|artifactregistry|secretmanager|sqladmin'
（沒有輸出）
```

一次開六個（投影片 p.233）：

```bash
gcloud services enable \
    aiplatform.googleapis.com \
    run.googleapis.com \
    cloudbuild.googleapis.com \
    artifactregistry.googleapis.com \
    secretmanager.googleapis.com \
    sqladmin.googleapis.com
```

`setup.sh` 的步驟 3 就是這一行。這條指令會跑 30-90 秒，沒有進度條，別以為它卡住了。

### 為什麼

**為什麼要顯式啟用？** GCP 的每個服務在每個專案裡都是預設關閉的。API 沒開時呼叫，錯誤訊息長這樣：

```
403 PERMISSION_DENIED: Vertex AI API has not been used in project agent-course-2026 before or it is disabled. Enable it by visiting https://console.developers.google.com/apis/api/aiplatform.googleapis.com/overview?project=agent-course-2026 then retry.
```

看到 `PERMISSION_DENIED` 的第一反應通常是去查 IAM 權限——**但這個訊息其實是在說 API 沒開**。投影片 p.229 第 3 點：「Permission denied 第一個檢查點常是 API 沒開」。這是本模組最值錢的一句話。

**六個各是幹什麼的**：

| API | 誰要用 | 沒開會怎樣 |
|---|---|---|
| `aiplatform` | Vertex／Agent Engine（M5 步驟 7、M7、M10） | 上面那個 403 |
| `run` | Cloud Run 部署（M2、M10） | `gcloud run deploy` 直接 403 |
| `cloudbuild` | `--source .` 部署時在雲端 build 容器 | 部署卡在 build 階段 |
| `artifactregistry` | build 出來的容器 image 存哪 | build 完推不上去 |
| `secretmanager` | 本 Lab 步驟 6、M8 的 DB 密碼 | `gcloud secrets create` 403 |
| `sqladmin` | Cloud SQL（M8） | 建不了實例 |

`run` ＋ `cloudbuild` ＋ `artifactregistry` 是 Cloud Run 部署三兄弟，少一個部署就會在不同階段掛掉，而且錯誤訊息不會直接告訴你少了哪個。一次全開最省事。

**為什麼這步不用先查存在性？** 因為 `gcloud services enable` 本身就 idempotent——已經開的服務會直接回成功。這是少數不需要 `exists` 包裝的指令。

### 驗收

```bash
$ gcloud services list --enabled --format='value(config.name)' \
    | grep -c -E 'aiplatform|^run\.|cloudbuild|artifactregistry|secretmanager|sqladmin'
6
```

必須印 `6`。印 5 以下 → 重跑 `gcloud services enable`；剛跑完就查可能還沒生效，等一分鐘再查。

> ⚠️ 未實測：`gcloud services enable` 的實際耗時、`services list --enabled` 的欄位格式（`config.name`）、以及那段 403 原文都需要真帳號驗證。

`verify.sh` 會逐個檢查並告訴你少哪一個：

```
✓ API 已啟用：aiplatform.googleapis.com
✗ API 已啟用：sqladmin.googleapis.com
    修：gcloud services enable sqladmin.googleapis.com --project=agent-course-2026
```

---

## 步驟 4：設定 ADC（8 分）—— 先讓它失敗

### 動手（第一次：故意失敗）

API 開好了，直接跑 Python 試試看：

```bash
$ export GOOGLE_GENAI_USE_ENTERPRISE=True
$ export GOOGLE_CLOUD_PROJECT=$PROJECT_ID
$ export GOOGLE_CLOUD_LOCATION=us-central1
$ uv run vertex_smoke.py
```

```
google.auth.exceptions.DefaultCredentialsError: Your default credentials were not found. To set up Application Default Credentials, see https://cloud.google.com/docs/authentication/external/set-up-adc for more information.
```

**但你剛剛才 `gcloud auth login` 過。** gcloud 明明通了，Python 為什麼不通？

因為它們用的是**兩套不同的憑證**：

```
gcloud auth login                       → 給 CLI 用，存在 gcloud 自己的 credential DB
gcloud auth application-default login   → 給任何 Google SDK 用（ADC），存成一個 JSON
```

### 動手（第二次：修好一半）

```bash
gcloud auth application-default login     # 會開瀏覽器，授權一次
uv run vertex_smoke.py
```

這次會有回答，但前面多一段警告：

```
UserWarning: Your application has authenticated using end user credentials from Google Cloud SDK without a quota project. You might receive a "quota exceeded" or "API not enabled" error. See the following page for troubleshooting: https://cloud.google.com/docs/authentication/adc-troubleshooting/user-creds.
```

### 動手（第三次：完全修好）

```bash
gcloud auth application-default set-quota-project $PROJECT_ID
uv run vertex_smoke.py
```

```
Vertex AI 連線正常，我是 Gemini 3.7 Flash。
[tokens] 47
```

關於上面三段輸出的誠實說明：

- **第一段 `DefaultCredentialsError` 是本機實際跑出來的**（`GOOGLE_GENAI_USE_ENTERPRISE=True GOOGLE_CLOUD_PROJECT=... uv run vertex_smoke.py`，這台機器沒有 ADC）。traceback 最底層是 `google/auth/_default.py:748`。
- > ⚠️ 未實測：第二段的 quota project 警告與第三段的成功回應需要真帳號才會出現。訊息原文抄自 `google/auth/_default.py` 的 `_CLOUD_SDK_CREDENTIALS_WARNING`（本機讀原始碼確認），模型的回答文字每次不同。

### 為什麼

**為什麼要有 ADC 這層抽象？** 因為程式碼在開發機和雲端要一模一樣。ADC 的查找順序（投影片 p.234）：

```
① $GOOGLE_APPLICATION_CREDENTIALS 指的金鑰檔     ← 不建議：金鑰檔會外洩
② ~/.config/gcloud/application_default_credentials.json   ← 開發機用這層（現在做的）
③ 執行環境附掛的 service account（metadata server） ← M10 雲端用這層，零金鑰檔
```

`genai.Client(enterprise=True, project=..., location=...)` 這行在你的筆電上走②、部署到 Cloud Run 走③——**程式碼一個字都不用改**。這就是為什麼 M10 部署時你不需要把金鑰檔塞進容器。

**不這樣寫會怎樣**：走①的話你會下載一個 SA JSON 金鑰檔，然後它會出現在 git、出現在 Slack、出現在某個 Dockerfile 的 `COPY . .` 裡面。投影片 p.238 直接寫了：「不要下載 SA 的 JSON 金鑰檔——附掛代替金鑰，是 2026 的標準做法」。

**quota project 到底是什麼？** ADC 用的是「你的個人身分」，但 API 呼叫的用量要記在某個專案的帳上。沒指定 quota project，Google 不知道要記到哪，就給你那段警告，而且**在某些 API 上會直接 403**（警告裡自己寫了 `You might receive a "quota exceeded" or "API not enabled" error`）。所以警告不能當雜訊忽略。

**`vertex_smoke.py` 為什麼要先判斷路線再呼叫？** 因為 SDK 的錯誤訊息不會告訴你「你少設了哪個環境變數」。少了 `GOOGLE_GENAI_USE_ENTERPRISE` 時它丟的是：

```
ValueError: No API key was provided. Please pass a valid API key. Learn how to create an API key at https://ai.google.dev/gemini-api/docs/api-key.
```

——它以為你要走 Developer API 路線。學生看到「叫我去拿 API key」會真的去拿一把 API key，然後困惑為什麼 Vertex 還是不通。所以 `resolve_route()` 先攔下來：

```python
$ uv run vertex_smoke.py --explain
路線：none  project=None  location=None
  ! 既沒開 Enterprise 也沒有 API key → Client() 會丟 ValueError: No API key was provided.
```

**`enterprise=True` 還是 `vertexai=True`？** 投影片 p.235 寫 `vertexai=True`，這仍然可以跑。但 google-genai 2.20.0 的 `client.py` docstring 寫著 `vertexai (bool): Legacy flag for enterprise.`——2026 的正名是 `enterprise=`（環境變數也一樣：`GOOGLE_GENAI_USE_ENTERPRISE` 是新名，`GOOGLE_GENAI_USE_VERTEXAI` 是舊名，見附錄 C 改名對照表）。兩個都給且值不同會丟 `ValueError: enterprise and vertexai flags have conflicting values, please set enterprise value only.`，所以只給一個。

**`with genai.Client(...) as client:` 為什麼一定要 `with`？** 寫成 `genai.Client(...).interactions.create(...)` 的話，Client 是一個沒人持有的暫時物件，請求送出前就被 GC 關掉：

```
RuntimeError: Cannot send a request, as the client has been closed.
```

### 驗收

```bash
$ gcloud auth application-default print-access-token | head -c 20
ya29.a0AfB_byC3xY...

$ grep quota_project_id ~/.config/gcloud/application_default_credentials.json
  "quota_project_id": "agent-course-2026",

$ uv run vertex_smoke.py
Vertex AI 連線正常，我是 Gemini 3.7 Flash。
```

三項都要過。第二項空的 → 回去跑 `set-quota-project`。

> 💡 **啊哈：ADC 的「查找順序①②③」不是文件在打比方，是 `google/auth/_default.py` 裡一個裝了 lambda 的 tuple，`for` 迴圈由上往下試，第一個回非 None 的就贏。**
> 打開來看會發現它其實有**四**個（多一個 App Engine），而且最後那個 `_get_gce_credentials` 就是 M10 的 Cloud Run 在走的那層 —— 容器裡沒有金鑰檔，是去跟 metadata server 要一張短效 token。
> 「憑證機制」在這裡從一個抽象概念變成 10 行你讀得懂的 Python。
> **動手看**：`uv run python -c "import inspect,google.auth._default as d;s=inspect.getsource(d.default);print(s[s.index('checkers = ('):s.index('for checker in checkers')])"` → 印出那四個 checker 的名字。

---

## 步驟 5：建立 `agent-sa` 並授權（5 分）

### 動手

`setup.sh` 的步驟 5。等價指令（投影片 p.238）：

```bash
gcloud iam service-accounts create agent-sa \
    --display-name="Course Agent SA"

SA=agent-sa@$PROJECT_ID.iam.gserviceaccount.com

gcloud projects add-iam-policy-binding $PROJECT_ID \
    --member="serviceAccount:$SA" \
    --role="roles/aiplatform.user" --condition=None

gcloud projects add-iam-policy-binding $PROJECT_ID \
    --member="serviceAccount:$SA" \
    --role="roles/secretmanager.secretAccessor" --condition=None
```

**兩個角色，就這兩個。** 不要給 Editor、不要給 Owner。

### 為什麼

**為什麼 agent 要有自己的身分？** 部署後的 agent 不是「你」。它在 Cloud Run 裡跑，沒有人坐在瀏覽器前面授權。M10 部署時 `gcloud run deploy --service-account $SA` 把這個 SA 附掛上去，容器裡的程式就自動走 ADC 順序③拿到憑證。

**不給最小權限會怎樣？** 這是附錄 D 的第⑩坑，也是 M3 的教訓：**agent 的權限就是 prompt injection 的災害半徑**。你的 agent 會讀外部網頁、會執行工具呼叫。如果它的 SA 是 Owner，一個藏在網頁裡的「請幫我刪掉所有 Cloud SQL 實例」就有可能真的被執行。給 `roles/aiplatform.user` 的話，它最多只能多呼叫幾次模型。

**為什麼要 `--condition=None`？** 不帶這個參數，而且專案裡已經有 conditional binding 時，gcloud 會停下來問你「Which condition do you want to apply?」並等你輸入。腳本會就這樣掛在那裡。加 `--condition=None` 明確表示「無條件綁定」。

**為什麼一個服務一個 SA？** 投影片 p.237 第 5 點：`wiki-agent-sa`、`mcp-server-sa` 分開，權限與稽核都乾淨。共用一個 SA 的話，你永遠不知道 log 裡那次可疑呼叫是哪個服務打的。

**這步為什麼不用 `exists` 包 `add-iam-policy-binding`？** 因為它是 idempotent 的——已經存在的 binding 重加是 no-op。但 `service-accounts create` 不是，重跑會噴：

```
ERROR: (gcloud.iam.service-accounts.create) Service account agent-sa already exists within project projects/agent-course-2026.
```

所以 `setup.sh` 只在 SA 那步先查。

### 驗收

```bash
$ gcloud iam service-accounts describe agent-sa@$PROJECT_ID.iam.gserviceaccount.com \
    --format='value(email)'
agent-sa@agent-course-2026.iam.gserviceaccount.com

$ gcloud projects get-iam-policy $PROJECT_ID \
    --flatten='bindings[].members' \
    --filter="bindings.members:serviceAccount:agent-sa@$PROJECT_ID.iam.gserviceaccount.com" \
    --format='value(bindings.role)'
roles/aiplatform.user
roles/secretmanager.secretAccessor
```

**恰好兩行。** 多出 `roles/editor` 或 `roles/owner` → 你（或 Console 的某個「快速設定」按鈕）給太多了，用 `remove-iam-policy-binding` 拿掉。

> ⚠️ 未實測：`get-iam-policy --flatten` 的實際輸出格式與 `Service account ... already exists` 原文需要真帳號驗證。`verify.sh` 的 role 檢查就是靠上面這個查詢的字串比對，格式若不同要改 `--format`。

---

## 步驟 6：存入第一個機密（4 分）

### 動手

把 Lab 1 的 `GEMINI_API_KEY` 存進 Secret Manager 練手（投影片 p.241）：

```bash
printf '%s' "$GEMINI_API_KEY" | gcloud secrets create gemini-api-key \
    --replication-policy=automatic --data-file=-
```

**故意做錯**：再貼一次。

```
ERROR: (gcloud.secrets.create) ALREADY_EXISTS: Secret [gemini-api-key] already exists.
```

要更新就不是 `create`，是加一個**新版本**：

```bash
printf '%s' "$NEW_KEY" | gcloud secrets versions add gemini-api-key --data-file=-
```

`setup.sh` 的步驟 6 幫你選：secret 不存在 → `create`；存在 → `versions add`。

讀回來（除錯用）：

```bash
gcloud secrets versions access latest --secret=gemini-api-key
```

### 為什麼

**為什麼不用 `echo`？** `echo "$KEY"` 會在結尾多一個換行字元，存進去的 secret 值就是 `AIza...\n`。之後程式拿去當 HTTP header 會噴 400，而你在終端機上看起來完全正常。用 `printf '%s'`（或投影片寫的 `echo -n`）。

**為什麼用 `--data-file=-`（stdin）而不是 `--data-file=key.txt` 或直接寫在指令列？** 三個理由：

1. 寫在指令列 → 進 shell history，`~/.zsh_history` 就有你的 key。
2. 寫成檔案 → 忘記刪，或者被 `git add .` 掃進去。
3. stdin → 只活在記憶體裡。

**為什麼是版本化而不是覆蓋？** 每次 `versions add` 都是一個新版本，舊版本留著。key 輪替之後發現新的那把有問題，`versions access 1` 就能拿回舊的。覆蓋式的設計沒有回滾。

**為什麼「本機 `.env`、雲端 Secret Manager」？** `.env` 檔案沒有 IAM、沒有稽核、沒有版本。它只適合「反正只有我這台機器看得到」的開發階段。M10 部署時是這樣把 secret 掛進 Cloud Run 的：

```bash
gcloud run deploy ... --set-secrets=DB_PASSWORD=db-password:latest
```

容器裡讀到的就是一個普通環境變數，但值從來沒有離開 Google 的邊界，而且「誰在什麼時候讀了哪個 secret」在 audit log 裡查得到。

**`--replication-policy=automatic` 是什麼？** secret 存哪些 region。`automatic` = Google 幫你選（多區備援），課程用這個就好。要指定 region 才用 `--replication-policy=user-managed --locations=us-central1`。

### 驗收

```bash
$ gcloud secrets versions list gemini-api-key --format='table(name, state)'
NAME  STATE
1     ENABLED

$ gcloud secrets versions access latest --secret=gemini-api-key
AIzaSy...            ← 跟你的 $GEMINI_API_KEY 一模一樣，結尾沒有多的換行

$ [ "$(gcloud secrets versions access latest --secret=gemini-api-key)" = "$GEMINI_API_KEY" ] \
    && echo "一致" || echo "不一致（檢查是不是用了 echo 而不是 printf）"
一致
```

> 💡 **啊哈：同一把 key 在這門課搬了三次家，每搬一次就少一個外洩管道 —— 你現在站在第三站。**
> ①環境變數：`lab1/ask.py:67` 的 `genai.Client()` 直接讀 `GEMINI_API_KEY`，key 的明文在你的 shell、你的 `.env`、你的 history 裡。②ADC（步驟 4）：金鑰根本不在你手上，換成一張可撤銷的授權。③Secret Manager（現在）：值有 IAM、有版本、有 audit log。
> 這條路的終點在 M10：你剛手打的 `secrets create ... || versions add` 在部署腳本裡是同一組指令，只是換成 DB 密碼。
> **動手看**：`grep -n "secrets create\|set-secrets" /Users/awesomeartengineer01/Antigravity-teach/lab10/deploy.sh` → 第 78 行是你剛打的那組 create／versions add，第 97 行 `--set-secrets "DB_PASSWORD=…:latest"` 就是把它掛進 Cloud Run 的那一行。

> ⚠️ 未實測：Secret Manager 的三個指令都需要真帳號。`ALREADY_EXISTS: Secret [...] already exists.` 的原文抄自 GCP 慣用格式。最後那個字串比對是**你自己跑得出結果**的驗收方式——它不依賴任何訊息格式，只比值相不相等。

---

## 步驟 7：驗收（5 分）

### 動手

先把 Enterprise 路線三件套設好（`setup.sh` 跑完會印給你）：

```bash
export GOOGLE_GENAI_USE_ENTERPRISE=True
export GOOGLE_CLOUD_PROJECT=$PROJECT_ID
export GOOGLE_CLOUD_LOCATION=us-central1
unset GEMINI_API_KEY        # 見下方「為什麼」
```

然後一次驗完 19 項：

```bash
./verify.sh --with-api
echo "失敗項數：$?"
```

### 為什麼

**為什麼要 `unset GEMINI_API_KEY`？** API key 和 project/location 同時存在時，優先權規則會隨著「是明確傳入還是從環境變數來」而變（`_api_client.py:725-765` 有三個分支在處理這件事），而 SDK 只用 `logger.info` 記它選了哪一邊——預設的 logging 設定下你**看不到任何訊息**。跑 Enterprise 路線就把 API key 拿掉，不要留兩套憑證讓自己猜。`vertex_smoke.py --explain` 會把這件事列出來：

```
路線：enterprise  project=agent-course-2026  location=us-central1
  ! 同時有 API key 與 project/location：明確傳入的 project/location 會贏，SDK 只記一條 INFO log（預設看不到），所以出錯時很難察覺。跑 Enterprise 就把 GEMINI_API_KEY unset。
```

**為什麼 `verify.sh` 的退出碼是失敗項數而不是 0/1？** 這樣它可以直接接進 CI 或 `&&` 鏈，而且你一眼看得出「還差幾項」。

**為什麼 `--with-api` 是選配、不是預設？** 因為那一項會真的花掉一次模型呼叫。前 18 項全是唯讀查詢，重跑一百次都免費。

**為什麼失敗項要印「修：」？** 因為「確認運作正常」對卡住的人沒有幫助。`verify.sh` 的每一項失敗都附一行可以直接貼的指令：

```
✗ ADC quota project 是 agent-course-2026
    修：gcloud auth application-default set-quota-project agent-course-2026
```

實作上是一個外部變數 `FIXHINT`，`check()` 用完會清掉——`--self-check` 裡有一條斷言就是在防「上一項的修法殘留到下一項」，那會讓學生照著錯的指令去修。

### 驗收清單

對應 LAB 頁 p.244 步驟 7：

- [ ] `gcloud config list` 的 `project` 是你的專案 ID、`run/region` 是 `us-central1`
- [ ] `gcloud billing projects describe $PROJECT_ID --format='value(billingEnabled)'` → `True`
- [ ] Console → Billing → Budgets 看得到 `course-budget`，三段門檻、通知信箱是自己
- [ ] 六個 API 都在 `gcloud services list --enabled` 裡（`grep -c` 得到 `6`）
- [ ] `gcloud auth application-default print-access-token` 印得出 token
- [ ] `~/.config/gcloud/application_default_credentials.json` 裡有 `"quota_project_id"` 且值是你的專案
- [ ] `agent-sa` 存在，且**恰好**有 `roles/aiplatform.user` ＋ `roles/secretmanager.secretAccessor` 兩個角色
- [ ] `gcloud secrets versions access latest --secret=gemini-api-key` 讀回來的值跟你的 key 一模一樣
- [ ] `uv run vertex_smoke.py` 以 `enterprise=True` 成功呼叫 `gemini-3.7-flash` 並印出一句話
- [ ] `./verify.sh --with-api` 全綠，`echo $?` 是 `0`
- [ ] 離線那四項 `--self-check` 也都還是通過的

> 型號名 `gemini-3.7-flash` 以課程投影片為準。若拿到 404，用 `client.models.list()` 確認現行型號（附錄 D 第⑧坑：preview 模型會退役，model ID 要進設定檔）。

> 💡 **啊哈：從 Developer 路線換到 Vertex，改的不是程式碼，是 SDK 決定要打「哪一台伺服器」。**
> 「程式碼不用改」可以量給你看：三種憑證下 `genai.Client()` 字串完全相同，但它算出來的 base URL 從 `generativelanguage.googleapis.com` 換成 `us-central1-aiplatform.googleapis.com`——兩個不同網域的服務。
> 而且 `Client()` 建構的當下**還沒去拿憑證**（憑證要到第一次送請求才解析），所以這張對照表在沒有 ADC、沒有 GCP 帳號的機器上照樣跑得出來。
> **動手看**：`uv run vertex_smoke.py --aha` → 三列的「程式碼」欄一模一樣，「SDK 實際打的端點」欄不一樣。

---

## 常見錯誤對照表

| 症狀 | 原因 | 解法 |
|---|---|---|
| `ModuleNotFoundError: No module named 'google'` | 用了 `python vertex_smoke.py` | 一律 `uv run vertex_smoke.py`。不用 pip、不用 venv、不用 activate |
| `gcloud: command not found` | 沒裝 Cloud SDK | macOS `brew install --cask google-cloud-sdk`；Linux `curl https://sdk.cloud.google.com \| bash` |
| `ERROR: (gcloud.projects.create) Project creation failed. The project ID you specified is already in use by another project.` | 專案 ID 全球唯一，被別人用掉了 | 換一個 ID（例：加自己的後綴）。ID 建立後**不可改**，想清楚再建 |
| `ERROR: FAILED_PRECONDITION: Billing account for project '...' is not found. Billing must be enabled for activation of service(s) to complete.` | 先開 API 才綁帳單，順序顛倒 | 先 `gcloud billing projects link`，再 `gcloud services enable` |
| `403 PERMISSION_DENIED: Vertex AI API has not been used in project ... before or it is disabled.` | **看起來是權限問題，其實是 API 沒開** | `gcloud services enable aiplatform.googleapis.com`，等 1 分鐘再試。這是投影片 p.229 的「第一個檢查點」 |
| `google.auth.exceptions.DefaultCredentialsError: Your default credentials were not found. To set up Application Default Credentials, see https://cloud.google.com/docs/authentication/external/set-up-adc for more information.` | 只做了 `gcloud auth login`（CLI 的身分），沒做 ADC（程式的身分） | `gcloud auth application-default login`。兩個 login 是不同的東西 |
| `UserWarning: Your application has authenticated using end user credentials from Google Cloud SDK without a quota project. You might receive a "quota exceeded" or "API not enabled" error.` | ADC 沒設 quota project，用量記不到專案帳上 | `gcloud auth application-default set-quota-project $PROJECT_ID`。這不是可以忽略的雜訊 |
| `ValueError: No API key was provided. Please pass a valid API key. Learn how to create an API key at https://ai.google.dev/gemini-api/docs/api-key.` | 忘了 `export GOOGLE_GENAI_USE_ENTERPRISE=True`，SDK 以為你要走 Developer API 路線 | 設好三件套：`GOOGLE_GENAI_USE_ENTERPRISE` ＋ `GOOGLE_CLOUD_PROJECT` ＋ `GOOGLE_CLOUD_LOCATION`。別急著去拿 API key |
| 三件套明明設了，還是噴上面那個 `No API key was provided.` | `GOOGLE_GENAI_USE_ENTERPRISE` 的值寫成 `yes`／`on`／`TRUE!` 之類。SDK 只認 `'true'` 與 `'1'`（`_api_client.py:655-662` 的 `env_str.lower() in ['true','1']`），其他值**一律當成沒設，而且不會警告** | 值就寫 `True` 或 `1`。跑 `uv run vertex_smoke.py --explain` 會直接指出「不算 true」 |
| `ValueError: Could not resolve project using application default credentials.` | 開了 Enterprise 但沒給 project，ADC 裡也撈不到 | `export GOOGLE_CLOUD_PROJECT=$PROJECT_ID`，或 `gcloud auth application-default set-quota-project` |
| `ValueError: enterprise and vertexai flags have conflicting values, please set enterprise value only.` | `Client(enterprise=True, vertexai=False)` 之類 | 只給 `enterprise=True`（`vertexai=` 是 legacy 別名） |
| `RuntimeError: Cannot send a request, as the client has been closed.` | `genai.Client().interactions.create(...)` 的 Client 沒人持有，請求送出前被 GC 關掉 | `with genai.Client(...) as client:` |
| `ERROR: (gcloud.secrets.create) ALREADY_EXISTS: Secret [gemini-api-key] already exists.` | `secrets create` 不是 idempotent | 改用 `gcloud secrets versions add gemini-api-key --data-file=-`（新版本，可回滾） |
| `ERROR: (gcloud.iam.service-accounts.create) Service account agent-sa already exists within project projects/...` | 同上，`create` 不是 idempotent | 直接跳過建立，或改跑 `./setup.sh`（它會先 `describe` 再決定） |
| `budgets list` 印出兩個 `course-budget`，但**沒有任何錯誤** | `gcloud billing budgets create` 重跑會沉默地多建一個 | `gcloud billing budgets delete billingAccounts/.../budgets/<多的那個>`；之後用 `./setup.sh`，它會先 `budgets list --filter=displayName=` 查過 |
| gcloud 停在 `Which condition do you want to apply?` 等你輸入 | `add-iam-policy-binding` 沒帶 `--condition` 而專案裡有 conditional binding | 加 `--condition=None` |
| secret 讀回來的值尾多一個換行，程式拿去用噴 400 | 用了 `echo "$KEY"` 而不是 `printf '%s'` | `printf '%s' "$KEY" \| gcloud secrets create ... --data-file=-` |
| `./setup.sh` 直接中止：`✗ 沒給 BILLING_ACCOUNT` | 沒 export | `gcloud billing accounts list` 抄 ID → `export BILLING_ACCOUNT=XXXXXX-XXXXXX-XXXXXX` |
| `./setup.sh` 說 `PROJECT_ID 不合法` | 用了大寫、太短（< 6 字）、或結尾是連字號 | 6-30 字、小寫字母開頭、只能小寫字母／數字／連字號、結尾不是連字號 |
| `verify.sh` 輸出在管線裡出現 `\033[32m` 之類垃圾 | 不該發生——腳本用 `[ -t 1 ]` 判斷 tty | 若真的出現請回報；非 tty 應該退成 `[ OK ]` / `[FAIL]` |
| bash 報 `line 58: PROJECT_ID?: unbound variable` 但變數明明有設 | macOS 內建 bash 3.2 遇到 `$VAR` 緊接中文全形括號會把全形字當識別字元 | 全形字前一律寫 `${VAR}`。三支腳本都已處理 |

---

## 完整解答

同目錄的檔案就是走完七步的成品：

| 檔案 | 是什麼 |
|---|---|
| `setup.sh` | 七步 idempotent 設置。`--dry-run` 只印指令、`--self-check` 離線驗邏輯 |
| `verify.sh` | 19 項驗收檢查，印 ✓／✗ ＋ 修法。`--with-api` 才真的打 API |
| `teardown.sh` | 清理。預設刪整個專案，`--keep-project` 只刪 Lab 資源 |
| `vertex_smoke.py` | Enterprise 路線連通性測試。`--explain` 只診斷環境不呼叫 API；`--aha` 印憑證/端點對照表（離線） |
| `env.example` | 課程標準環境變數範本（投影片 p.242），複製成 `.env`，M5-M11 沿用 |
| `PRD.md` / `SPEC.md` | 需求與規格；`SPEC.md` 第 8 節是完整的錯誤處理表 |

卡住的時候先跑 `./verify.sh`，它會直接告訴你哪一項沒過、該貼哪一行。

---

## 想再往下玩

- **把 `run/region` 換成 `asia-east1`（台灣機房）跑一次 `vertex_smoke.py`**，比較延遲。注意投影片 p.243 的警告：部分 preview 功能較晚到 asia-east1，`gemini-3.7-flash` 在那邊不一定有。
- **幫 `agent-sa` 加 `roles/run.invoker` 並拔掉 `aiplatform.user`**，然後跑 `verify.sh` 看它抓不抓得到。這是在練「權限漂移偵測」——`verify.sh` 本質上是一份最小權限的 assertion。
- **把 `verify.sh` 接成 CI 的一步**（退出碼＝失敗項數，天生適合）。之後每個部署 Lab 開始前先跑一次，環境壞了立刻知道。
- **Lab 8 會用到 Secret Manager 存 Supabase 密碼**：`printf '%s' "$DB_PASSWORD" | gcloud secrets create db-password --data-file=-`。步驟 6 練的就是這個。
- **Lab 10 會把 `agent-sa` 附掛給 Cloud Run**：`gcloud run deploy ... --service-account $SA --set-secrets=DB_PASSWORD=db-password:latest`。步驟 5 建的 SA 那時才真正上工。

---

## 這個 Lab 你真正學到的

- **憑證是環境的屬性，不是程式碼的屬性。** 同一行 `genai.Client()` 在筆電上借你的身分、在 Cloud Run 上用附掛 SA 的身分，換的是 ADC 查到哪一層，不是任何一行 Python。
- **權限是一份文件，不是一排開關。** IAM policy 是可以 diff、可以進 git、可以在 CI 裡斷言的 JSON——所以「最小權限」是一件寫得出測試的事，`verify.sh` 就是那個測試。
- **成本控制的最後一道防線是「刪容器」不是「收告警」。** Project 是計費邊界，這是它在 GCP 心智模型裡真正的角色；budget alert 只是提早知道。
- **機密每往上搬一層，就少一個外洩管道。** 環境變數（快，但明文散在 shell、`.env`、history）→ ADC（金鑰根本不在你手上，可撤銷）→ Secret Manager（有 IAM、有版本、有 audit log）。M8 的 DB 密碼、M10 的 `--set-secrets` 都是第三站。
- **`PERMISSION_DENIED` 的第一個檢查點是「API 有沒有開」而不是「權限夠不夠」。** GCP 用同一個錯誤碼講兩件不同的事，知道這點可以省掉三小時。

---

## 清理

> **時機：上完 M11 再清。** M7-M11 的部署 Lab 全部沿用這個專案，做完 Lab 5 就刪等於後面五個 Lab 要重做一次。

### 建議做法：整個專案刪掉

投影片 p.243 第 5 點：Lab 專案整個刪除最乾淨——資源全部一起消失，不會有「忘記刪的 Cloud SQL 實例每月扣你錢」這種事。

```bash
cd /Users/awesomeartengineer01/Antigravity-teach/lab5
./teardown.sh --dry-run      # 先看它要刪什麼
./teardown.sh                # 會要你打字輸入專案 ID 確認
```

等價的手打指令：

```bash
gcloud projects delete agent-course-2026
gcloud config unset project
```

刪除後有 **30 天緩衝期**，期間可以救回來：

```bash
gcloud projects undelete agent-course-2026
```

### 只想清 Lab 5 的資源、專案留著

```bash
./teardown.sh --keep-project
```

它會依序做（**順序很重要：先解 IAM binding 再刪 SA，反過來會在 policy 裡留下指向不存在的 SA 的孤兒 member**）：

```bash
gcloud secrets delete gemini-api-key --quiet
gcloud projects remove-iam-policy-binding $PROJECT_ID --member="serviceAccount:$SA" --role=roles/aiplatform.user --quiet
gcloud projects remove-iam-policy-binding $PROJECT_ID --member="serviceAccount:$SA" --role=roles/secretmanager.secretAccessor --quiet
gcloud iam service-accounts delete $SA --quiet
```

### budget 要自己刪

budget 不屬於專案、屬於 billing account，所以刪專案不會刪掉它。而且它只能用完整資源名刪：

```bash
# 先查出完整名字
gcloud billing budgets list --billing-account=$BILLING_ACCOUNT \
    --filter="displayName=course-budget" --format='value(name)'
# → billingAccounts/01ABCD-234567-89EF00/budgets/1a2b3c4d-...

gcloud billing budgets delete billingAccounts/01ABCD-234567-89EF00/budgets/1a2b3c4d-...
```

`teardown.sh --keep-project` 會幫你查出名字，但**刪的那一行留給你自己貼**——避免手滑刪掉別的專案的預算告警。留著它其實也沒壞處：budget 不收費，而且下次開新專案還能用。

### 費用檢查

清完之後到 <https://console.cloud.google.com/billing> 看一下：

- Reports → 確認本月費用是你預期的（Lab 5 本身應該是 $0）
- Budgets & alerts → 確認沒有殘留的 budget 指向已刪除的專案

> ⚠️ 未實測：清理指令都沒有在真帳號上執行過（本機沒有 gcloud）。`teardown.sh` 的確認機制、旗標解析、刪除順序有用 `--self-check` 離線驗過。
