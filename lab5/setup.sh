#!/usr/bin/env bash
# Lab 5 setup：課程專用 GCP 專案一鍵設置（可重跑不炸）。
#
# 跑法：
#   ./setup.sh --dry-run     # 只印指令、不執行、不連網（沒 GCP 帳號也能驗邏輯）
#   ./setup.sh               # 真的做（需要 gcloud + 已登入 + billing account）
#   ./setup.sh --self-check  # 用假的 gcloud 驗 dry-run 邏輯，不連網不花錢
#
# 可用環境變數（都有預設，PROJECT_ID 跟 BILLING_ACCOUNT 建議自己給）：
#   PROJECT_ID BILLING_ACCOUNT REGION BUDGET_AMOUNT BUDGET_NAME SA_NAME
#   NOTIFY_EMAIL GEMINI_API_KEY

set -uo pipefail   # 不用 -e：我們靠指令的非零退出碼判斷「資源還不存在」

PROJECT_ID="${PROJECT_ID:-agent-course-2026}"
PROJECT_NAME="${PROJECT_NAME:-Agent Course}"
BILLING_ACCOUNT="${BILLING_ACCOUNT:-}"
REGION="${REGION:-us-central1}"
BUDGET_AMOUNT="${BUDGET_AMOUNT:-25USD}"
BUDGET_NAME="${BUDGET_NAME:-course-budget}"
SA_NAME="${SA_NAME:-agent-sa}"
SECRET_NAME="${SECRET_NAME:-gemini-api-key}"

APIS="aiplatform.googleapis.com run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com secretmanager.googleapis.com sqladmin.googleapis.com"
ROLES="roles/aiplatform.user roles/secretmanager.secretAccessor"

DRY_RUN=false; SELFCHECK=false
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=true ;;
    --self-check) SELFCHECK=true ;;
    *) echo "用法：$0 [--dry-run] | --self-check" >&2; exit 2 ;;
  esac
done

# ---- 小工具 ------------------------------------------------------------------

if [ -t 1 ]; then B=$'\033[1m'; G=$'\033[32m'; Y=$'\033[33m'; D=$'\033[2m'; R=$'\033[0m'
else B=""; G=""; Y=""; D=""; R=""; fi

step() { printf '\n%s==> %s%s\n' "$B" "$*" "$R"; }
note() { printf '    %s%s%s\n' "$D" "$*" "$R"; }
warn() { printf '    %s! %s%s\n' "$Y" "$*" "$R"; }
die()  { printf '\n%s✗ %s%s\n' "$Y" "$*" "$R" >&2; exit 1; }

# run <shell 指令字串> [顯示用字串]：dry-run 只印，實跑才 eval
run() {
  printf '    %s$ %s%s\n' "$D" "${2:-$1}" "$R"
  $DRY_RUN && return 0
  eval "$1"
}

# exists <查詢指令字串>：dry-run 一律回「不存在」，好讓後面的建立指令被印出來
exists() {
  $DRY_RUN && return 1
  eval "$1" >/dev/null 2>&1
}

# ---- 輸入驗證（GCP 真實命名規則，順便擋掉 eval 的 shell injection）----------

valid_project_id() { printf '%s' "$1" | grep -Eq '^[a-z][a-z0-9-]{4,28}[a-z0-9]$'; }
valid_billing_id() { printf '%s' "$1" | grep -Eq '^[0-9A-F]{6}-[0-9A-F]{6}-[0-9A-F]{6}$'; }
valid_sa_name()    { printf '%s' "$1" | grep -Eq '^[a-z][a-z0-9-]{4,28}[a-z0-9]$'; }

main() {
  valid_project_id "$PROJECT_ID" || die "PROJECT_ID 不合法：'$PROJECT_ID'（6-30 字，小寫字母開頭，只能小寫字母/數字/連字號，結尾不能是連字號）"
  valid_sa_name "$SA_NAME"       || die "SA_NAME 不合法：'$SA_NAME'（規則同 project id）"

  local sa_email="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
  local billing="$BILLING_ACCOUNT"
  if [ -z "$billing" ]; then
    if $DRY_RUN; then billing="XXXXXX-XXXXXX-XXXXXX"
    else die "沒給 BILLING_ACCOUNT。先跑 gcloud billing accounts list，再 export BILLING_ACCOUNT=XXXXXX-XXXXXX-XXXXXX"; fi
  elif ! valid_billing_id "$billing"; then
    die "BILLING_ACCOUNT 格式不對：'$billing'（要 XXXXXX-XXXXXX-XXXXXX，六碼一組共三組，大寫十六進位）"
  fi

  $DRY_RUN && note "DRY RUN：以下指令只印不跑。billing account 用假值 $billing 代表。"
  command -v gcloud >/dev/null 2>&1 || { $DRY_RUN || die "找不到 gcloud。macOS: brew install --cask google-cloud-sdk"; }

  # 1) 專案
  step "1/7 建立專案 $PROJECT_ID"
  if exists "gcloud projects describe $PROJECT_ID"; then
    note "已存在，跳過建立（這就是 idempotent：重跑不會撞 ALREADY_EXISTS）"
  else
    run "gcloud projects create $PROJECT_ID --name=\"$PROJECT_NAME\"" || die "建專案失敗：ID 全球唯一，被人用掉了就換一個"
  fi
  run "gcloud config set project $PROJECT_ID"
  run "gcloud config set run/region $REGION"

  # 2) 帳單 + 預算告警
  step "2/7 綁帳單並設 $BUDGET_AMOUNT 預算告警（50%/90%/100%）"
  if exists "gcloud billing projects describe $PROJECT_ID --format='value(billingEnabled)' | grep -q True"; then
    note "帳單已綁定，跳過"
  else
    run "gcloud billing projects link $PROJECT_ID --billing-account=$billing" || die "綁帳單失敗：確認 $billing 存在且你是 Billing Account Administrator"
  fi
  # budgets create 沒有 --if-not-exists，重跑會生出第二個同名 budget，所以自己先查
  if exists "gcloud billing budgets list --billing-account=$billing --filter=\"displayName=$BUDGET_NAME\" --format='value(name)' | grep -q ."; then
    note "預算 '$BUDGET_NAME' 已存在，跳過（不然會多出一個同名 budget）"
  else
    local notify=""
    [ -n "${NOTIFY_EMAIL:-}" ] && notify=" # 通知信箱請到 Console 的 budget 頁面加：$NOTIFY_EMAIL"
    run "gcloud billing budgets create --billing-account=$billing --display-name=\"$BUDGET_NAME\" --budget-amount=$BUDGET_AMOUNT --threshold-rule=percent=0.5 --threshold-rule=percent=0.9 --threshold-rule=percent=1.0"
    [ -n "$notify" ] && note "${notify# }"
  fi
  warn "budget 只通知、不斷電。要硬上限得用 API spend cap 或 quota。"

  # 3) 六個 API
  step "3/7 啟用六個 API"
  # services enable 本身就 idempotent（已開的會直接回 OK），所以不用先查
  run "gcloud services enable $APIS --project=$PROJECT_ID"
  note "aiplatform=Vertex/Agent Engine；run+cloudbuild+artifactregistry=Cloud Run 三兄弟"

  # 4) ADC
  step "4/7 設定 ADC（程式的身分）"
  if exists "gcloud auth application-default print-access-token"; then
    note "ADC 已存在，跳過瀏覽器授權"
  else
    warn "ADC 還沒設。這步會開瀏覽器，沒辦法無人化："
    run "gcloud auth application-default login"
  fi
  run "gcloud auth application-default set-quota-project $PROJECT_ID"
  note "quota project 沒設 → 之後每次呼叫都會噴 'authenticated using end user credentials ... without a quota project' 警告"

  # 5) service account + IAM
  step "5/7 建立 $SA_NAME 並授權"
  if exists "gcloud iam service-accounts describe $sa_email --project=$PROJECT_ID"; then
    note "SA 已存在，跳過建立"
  else
    run "gcloud iam service-accounts create $SA_NAME --project=$PROJECT_ID --display-name=\"Course Agent SA\""
  fi
  local role
  for role in $ROLES; do
    # add-iam-policy-binding 本身 idempotent（已有的 binding 重加是 no-op）
    run "gcloud projects add-iam-policy-binding $PROJECT_ID --member=\"serviceAccount:$sa_email\" --role=\"$role\" --condition=None --quiet"
  done
  note "不要下載 SA 的 JSON 金鑰檔。M10 部署用 --service-account 附掛，零金鑰檔。"

  # 6) 第一個 secret
  step "6/7 把 GEMINI_API_KEY 存進 Secret Manager"
  if [ -z "${GEMINI_API_KEY:-}" ]; then
    warn "沒有 GEMINI_API_KEY，跳過這步。export 之後重跑就會補上。"
  elif exists "gcloud secrets describe $SECRET_NAME --project=$PROJECT_ID"; then
    note "secret 已存在 → 加一個新版本（不是覆蓋，舊版本留著可回滾）"
    run "printf '%s' \"\$GEMINI_API_KEY\" | gcloud secrets versions add $SECRET_NAME --project=$PROJECT_ID --data-file=-" \
        "printf '%s' \"\$GEMINI_API_KEY\" | gcloud secrets versions add $SECRET_NAME --data-file=-"
  else
    run "printf '%s' \"\$GEMINI_API_KEY\" | gcloud secrets create $SECRET_NAME --project=$PROJECT_ID --replication-policy=automatic --data-file=-" \
        "printf '%s' \"\$GEMINI_API_KEY\" | gcloud secrets create $SECRET_NAME --replication-policy=automatic --data-file=-"
  fi

  # 7) 收尾
  step "7/7 完成"
  note "接著跑：./verify.sh"
  note "Enterprise 路線三件套（貼進 shell 或寫進 .env）："
  printf '      export GOOGLE_GENAI_USE_ENTERPRISE=True\n      export GOOGLE_CLOUD_PROJECT=%s\n      export GOOGLE_CLOUD_LOCATION=%s\n' "$PROJECT_ID" "$REGION"
}

# ---- self-check：用假 gcloud 驗 dry-run 邏輯，不連網、不花錢 -----------------

selfcheck() {
  local out fails=0
  SC_TMP="$(mktemp -d)"
  trap 'rm -rf "$SC_TMP"' EXIT

  # 假 gcloud：只要被呼叫就留下痕跡並失敗。dry-run 若真的執行了指令，這個檔就會出現。
  printf '#!/bin/sh\necho "$@" >> "%s/CALLED"\nexit 1\n' "$SC_TMP" > "$SC_TMP/gcloud"
  chmod +x "$SC_TMP/gcloud"

  out="$(PATH="$SC_TMP:$PATH" PROJECT_ID=agent-course-2026 BILLING_ACCOUNT= GEMINI_API_KEY=fake-key "$0" --dry-run 2>&1)"

  want() { case "$out" in *"$1"*) ;; *) echo "  ✗ dry-run 輸出少了：$1"; fails=$((fails+1)) ;; esac; }

  [ ! -f "$SC_TMP/CALLED" ] || { echo "  ✗ dry-run 竟然真的呼叫了 gcloud：$(cat "$SC_TMP/CALLED")"; fails=$((fails+1)); }

  want "gcloud projects create agent-course-2026"
  want "gcloud config set project agent-course-2026"
  want "gcloud billing projects link agent-course-2026"
  want "--budget-amount=25USD"
  want "--threshold-rule=percent=0.5"
  want "--threshold-rule=percent=0.9"
  want "--threshold-rule=percent=1.0"
  for a in $APIS; do want "$a"; done
  want "gcloud auth application-default login"
  want "set-quota-project agent-course-2026"
  want "gcloud iam service-accounts create agent-sa"
  for r in $ROLES; do want "$r"; done
  want "gcloud secrets create gemini-api-key"
  want "GOOGLE_GENAI_USE_ENTERPRISE=True"

  # 非 tty 時不能有 ANSI escape
  case "$out" in *$'\033'*) echo "  ✗ 非 tty 卻吐了 ANSI escape"; fails=$((fails+1)) ;; esac

  # 輸入驗證
  valid_project_id "agent-course-2026" || { echo "  ✗ 合法 project id 被判不合法"; fails=$((fails+1)); }
  valid_project_id "Agent-Course"      && { echo "  ✗ 大寫 project id 應該被擋"; fails=$((fails+1)); }
  valid_project_id "ab"                && { echo "  ✗ 太短的 project id 應該被擋"; fails=$((fails+1)); }
  valid_project_id "trailing-"         && { echo "  ✗ 結尾連字號應該被擋"; fails=$((fails+1)); }
  valid_project_id 'x; rm -rf /'       && { echo "  ✗ 帶分號的 project id 應該被擋"; fails=$((fails+1)); }
  valid_billing_id "01ABCD-234567-89EF00" || { echo "  ✗ 合法 billing id 被判不合法"; fails=$((fails+1)); }
  valid_billing_id "123-456-789"       && { echo "  ✗ 短的 billing id 應該被擋"; fails=$((fails+1)); }

  # 沒給 BILLING_ACCOUNT 且非 dry-run → 必須 die
  if PATH="$SC_TMP:$PATH" BILLING_ACCOUNT= "$0" >/dev/null 2>&1; then
    echo "  ✗ 沒給 BILLING_ACCOUNT 竟然沒中止"; fails=$((fails+1))
  fi

  if [ "$fails" -eq 0 ]; then echo "setup.sh --self-check 全部通過"; else echo "setup.sh --self-check 失敗 $fails 項"; exit 1; fi
}

if ${SELFCHECK}; then selfcheck; else main; fi
