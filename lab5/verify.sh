#!/usr/bin/env bash
# Lab 5 verify：逐項檢查 GCP 專案有沒有設好，印綠勾/紅叉。
#
# 跑法：
#   ./verify.sh              # 真的查（需要 gcloud）
#   ./verify.sh --dry-run    # 只印「會查什麼」，不連網
#   ./verify.sh --self-check # 驗檢查器本身的邏輯，不連網不花錢
#   ./verify.sh --with-api   # 額外真的呼叫一次 Gemini（會用掉一點額度）
#
# 退出碼 = 失敗項數（0 = 全過），可直接接 CI。

set -uo pipefail

PROJECT_ID="${PROJECT_ID:-agent-course-2026}"
REGION="${REGION:-us-central1}"
SA_NAME="${SA_NAME:-agent-sa}"
SECRET_NAME="${SECRET_NAME:-gemini-api-key}"
BUDGET_NAME="${BUDGET_NAME:-course-budget}"
SA_EMAIL="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
APIS="aiplatform.googleapis.com run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com secretmanager.googleapis.com sqladmin.googleapis.com"

DRY_RUN=false; WITH_API=false; SELFCHECK=false
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=true ;;
    --with-api) WITH_API=true ;;
    --self-check) SELFCHECK=true ;;
    *) echo "用法：$0 [--dry-run] [--with-api] | --self-check" >&2; exit 2 ;;
  esac
done

# 非 tty（管線、CI、重導向到檔案）就退成純文字，不吐 ANSI
if [ -t 1 ]; then
  OK_MARK=$'\033[32m✓\033[0m'; NG_MARK=$'\033[31m✗\033[0m'; SK_MARK=$'\033[33m·\033[0m'; DIM=$'\033[2m'; RST=$'\033[0m'
else
  OK_MARK="[ OK ]"; NG_MARK="[FAIL]"; SK_MARK="[ ?? ]"; DIM=""; RST=""
fi

FAILED=0

# 這幾個值會進 eval，先用 GCP 命名規則擋掉 shell 特殊字元（規則與 setup.sh 相同）
printf '%s' "$PROJECT_ID" | grep -Eq '^[a-z][a-z0-9-]{4,28}[a-z0-9]$' \
  || { echo "PROJECT_ID 不合法：'$PROJECT_ID'（6-30 字，小寫字母開頭，只能小寫字母/數字/連字號）" >&2; exit 2; }
printf '%s' "$SA_NAME" | grep -Eq '^[a-z][a-z0-9-]{4,28}[a-z0-9]$' \
  || { echo "SA_NAME 不合法：'$SA_NAME'" >&2; exit 2; }

# check <說明> <shell 指令>：指令 exit 0 就是過
check() {
  local label="$1"; shift
  if $DRY_RUN; then
    printf '%s %s\n    %s$ %s%s\n' "$SK_MARK" "$label" "$DIM" "$*" "$RST"
    return 0
  fi
  if eval "$*" >/dev/null 2>&1; then
    printf '%s %s\n' "$OK_MARK" "$label"
  else
    printf '%s %s\n    %s修：%s%s\n' "$NG_MARK" "$label" "$DIM" "${FIXHINT:-見 walkthrough.md 常見錯誤表}" "$RST"
    FAILED=$((FAILED+1))
  fi
  FIXHINT=""
}

main() {
  echo "檢查專案 ${PROJECT_ID}（region ${REGION}）"
  echo

  FIXHINT="macOS: brew install --cask google-cloud-sdk" \
  check "gcloud 已安裝" "command -v gcloud"

  FIXHINT="gcloud auth login" \
  check "已登入 gcloud（有 active account）" \
        "gcloud auth list --filter=status:ACTIVE --format='value(account)' | grep -q ."

  FIXHINT="gcloud config set project $PROJECT_ID" \
  check "config 的 project 是 $PROJECT_ID" \
        "gcloud config get-value project 2>/dev/null | grep -qx '$PROJECT_ID'"

  FIXHINT="gcloud config set run/region $REGION" \
  check "config 的 run/region 是 $REGION" \
        "gcloud config get-value run/region 2>/dev/null | grep -qx '$REGION'"

  FIXHINT="gcloud billing projects link $PROJECT_ID --billing-account=..." \
  check "帳單已綁定（billingEnabled=True）" \
        "gcloud billing projects describe $PROJECT_ID --format='value(billingEnabled)' | grep -q True"

  FIXHINT="重跑 ./setup.sh，或到 Console > Billing > Budgets 建 '$BUDGET_NAME'" \
  check "預算告警 '$BUDGET_NAME' 存在" \
        "gcloud billing budgets list --billing-account=\$(gcloud billing projects describe $PROJECT_ID --format='value(billingAccountName)' | sed 's#.*/##') --filter=\"displayName=$BUDGET_NAME\" --format='value(name)' | grep -q ."

  local api
  for api in $APIS; do
    FIXHINT="gcloud services enable $api --project=$PROJECT_ID" \
    check "API 已啟用：$api" \
          "gcloud services list --enabled --project=$PROJECT_ID --format='value(config.name)' | grep -qx '$api'"
  done

  FIXHINT="gcloud auth application-default login" \
  check "ADC 可取得 access token" \
        "gcloud auth application-default print-access-token | head -c 20 | grep -q ."

  FIXHINT="gcloud auth application-default set-quota-project $PROJECT_ID" \
  check "ADC quota project 是 $PROJECT_ID" \
        "tr -d ' \n' < \"\${CLOUDSDK_CONFIG:-\$HOME/.config/gcloud}/application_default_credentials.json\" | grep -q '\"quota_project_id\":\"$PROJECT_ID\"'"

  FIXHINT="gcloud iam service-accounts create $SA_NAME --project=$PROJECT_ID" \
  check "service account $SA_EMAIL 存在" \
        "gcloud iam service-accounts describe $SA_EMAIL --project=$PROJECT_ID"

  local role
  for role in roles/aiplatform.user roles/secretmanager.secretAccessor; do
    FIXHINT="gcloud projects add-iam-policy-binding $PROJECT_ID --member=serviceAccount:$SA_EMAIL --role=$role" \
    check "SA 有角色：$role" \
          "gcloud projects get-iam-policy $PROJECT_ID --flatten='bindings[].members' --filter=\"bindings.role=$role AND bindings.members:serviceAccount:$SA_EMAIL\" --format='value(bindings.role)' | grep -q ."
  done

  FIXHINT="export GEMINI_API_KEY=... 後重跑 ./setup.sh" \
  check "secret '$SECRET_NAME' 至少有一個 enabled 版本" \
        "gcloud secrets versions list $SECRET_NAME --project=$PROJECT_ID --filter=state:ENABLED --format='value(name)' | grep -q ."

  if $WITH_API || $DRY_RUN; then
    FIXHINT="看 vertex_smoke.py 的錯誤輸出；常見是 aiplatform API 沒開或 ADC quota project 沒設" \
    check "Python 走 Enterprise 路線呼叫得動 Gemini" \
          "GOOGLE_GENAI_USE_ENTERPRISE=True GOOGLE_CLOUD_PROJECT=$PROJECT_ID GOOGLE_CLOUD_LOCATION=$REGION uv run vertex_smoke.py"
  else
    printf '%s %s\n    %s加 --with-api 才會真的打一次 API%s\n' "$SK_MARK" "Python 走 Enterprise 路線呼叫得動 Gemini（跳過）" "$DIM" "$RST"
  fi

  echo
  if $DRY_RUN; then
    echo "DRY RUN：以上只是「會查什麼」，沒有真的連線。"
  elif [ "$FAILED" -eq 0 ]; then
    echo "全部通過。Lab 5 驗收完成，M7-M11 的部署 Lab 可以直接用這個專案。"
  else
    echo "有 $FAILED 項沒過。照每項下面的「修：」處理完再跑一次。"
  fi
  exit "$FAILED"
}

# ---- self-check：驗 check() 本身，不連網 -------------------------------------

selfcheck() {
  local fails=0 out tmpf tmpd
  DRY_RUN=false
  tmpf="$(mktemp)"

  # 注意：不能寫 out="$(check ...)"，command substitution 是 subshell，
  # FAILED 的累加會留在 subshell 裡帶不回來。導向到檔案才不會開 subshell。
  FAILED=0; FIXHINT=""; check "永遠成立" "true" > "$tmpf"; out="$(cat "$tmpf")"
  [ "${FAILED}" -eq 0 ] || { echo "  x true 的檢查竟然算失敗"; fails=$((fails+1)); }
  case "$out" in *"永遠成立"*) ;; *) echo "  x 通過的項目沒印出標籤"; fails=$((fails+1)) ;; esac

  FAILED=0; FIXHINT="去修它"; check "永遠失敗" "false" > "$tmpf"; out="$(cat "$tmpf")"
  [ "${FAILED}" -eq 1 ] || { echo "  x false 的檢查沒被計入 FAILED，得到 ${FAILED}"; fails=$((fails+1)); }
  case "$out" in *"去修它"*) ;; *) echo "  x 失敗項沒印出 FIXHINT"; fails=$((fails+1)) ;; esac

  # FIXHINT 用完要清掉，不然下一項失敗會沿用上一項的修法（誤導學生）
  FAILED=0; check "沒設 hint 的失敗" "false" > "$tmpf"; out="$(cat "$tmpf")"
  case "$out" in *"去修它"*) echo "  x FIXHINT 沒被清掉，殘留到下一項"; fails=$((fails+1)) ;; esac

  rm -f "$tmpf"

  # 管線輸出（非 tty）不能有 ANSI escape
  out="$("$0" --dry-run | cat)"
  case "$out" in *$'\033'*) echo "  x 非 tty 卻吐了 ANSI escape"; fails=$((fails+1)) ;; esac
  case "$out" in *"aiplatform.googleapis.com"*) ;; *) echo "  x dry-run 沒列出 aiplatform 檢查"; fails=$((fails+1)) ;; esac
  case "$out" in *"roles/secretmanager.secretAccessor"*) ;; *) echo "  x dry-run 沒列出 secretAccessor 檢查"; fails=$((fails+1)) ;; esac
  case "$out" in *"quota_project_id"*) ;; *) echo "  x dry-run 沒列出 quota project 檢查"; fails=$((fails+1)) ;; esac
  case "$out" in *"billingEnabled"*) ;; *) echo "  x dry-run 沒列出帳單檢查"; fails=$((fails+1)) ;; esac

  # dry-run 不能真的呼叫 gcloud
  tmpd="$(mktemp -d)"
  printf '#!/bin/sh\ntouch "%s/CALLED"\nexit 1\n' "$tmpd" > "$tmpd/gcloud"; chmod +x "$tmpd/gcloud"
  PATH="$tmpd:$PATH" "$0" --dry-run >/dev/null 2>&1
  [ ! -f "$tmpd/CALLED" ] || { echo "  x dry-run 真的跑了 gcloud"; fails=$((fails+1)); }
  rm -rf "$tmpd"

  if [ "$fails" -eq 0 ]; then echo "verify.sh --self-check 全部通過"; else echo "verify.sh --self-check 失敗 $fails 項"; exit 1; fi
}

if ${SELFCHECK}; then selfcheck; else main; fi
