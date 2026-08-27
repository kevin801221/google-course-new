#!/usr/bin/env bash
# Lab 5 teardown：清掉這個 Lab 建出來的東西。
#
# 跑法：
#   ./teardown.sh --dry-run        # 只印指令，不刪（先看清楚要刪什麼）
#   ./teardown.sh --keep-project   # 只刪 secret / SA / IAM binding / budget，專案留著
#   ./teardown.sh                  # 整個專案刪掉（最乾淨，資源一起消失）
#   ./teardown.sh --self-check     # 驗確認機制與 dry-run，不連網
#
# 注意：課程 M7-M11 的部署 Lab 全部沿用這個專案。上完整門課再刪。

set -uo pipefail

PROJECT_ID="${PROJECT_ID:-agent-course-2026}"
SA_NAME="${SA_NAME:-agent-sa}"
SECRET_NAME="${SECRET_NAME:-gemini-api-key}"
BUDGET_NAME="${BUDGET_NAME:-course-budget}"
SA_EMAIL="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

# PROJECT_ID 會進 eval 而且這支腳本會刪東西：先用 GCP 命名規則擋掉 shell 特殊字元
printf '%s' "$PROJECT_ID" | grep -Eq '^[a-z][a-z0-9-]{4,28}[a-z0-9]$' \
  || { echo "PROJECT_ID 不合法：'$PROJECT_ID'（6-30 字，小寫字母開頭，只能小寫字母/數字/連字號）" >&2; exit 2; }

DRY_RUN=false; KEEP=false; SELFCHECK=false
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=true ;;
    --keep-project) KEEP=true ;;
    --self-check) SELFCHECK=true ;;
    *) echo "用法：$0 [--dry-run] [--keep-project] | --self-check" >&2; exit 2 ;;
  esac
done

if [ -t 1 ]; then B=$'\033[1m'; Y=$'\033[33m'; D=$'\033[2m'; R=$'\033[0m'
else B=""; Y=""; D=""; R=""; fi

run() {
  printf '    %s$ %s%s\n' "$D" "$1" "$R"
  ${DRY_RUN} && return 0
  eval "$1"
}

# confirm <要求輸入的字串>：打錯就中止。dry-run 直接放行（不刪東西）。
confirm() {
  ${DRY_RUN} && { printf '    %s(dry-run：跳過需要輸入 "%s" 的確認)%s\n' "$D" "$1" "$R"; return 0; }
  printf '%s輸入 %s 確認（其他任何輸入都會中止）：%s' "$Y" "$1" "$R"
  local answer; read -r answer
  [ "$answer" = "$1" ] || { echo "已中止，什麼都沒刪。"; exit 1; }
}

main() {
  if ${KEEP}; then
    printf '%s==> 保留專案，只刪 Lab 5 建出來的資源%s\n' "$B" "$R"
    confirm "$PROJECT_ID"
    run "gcloud secrets delete $SECRET_NAME --project=$PROJECT_ID --quiet"
    run "gcloud projects remove-iam-policy-binding $PROJECT_ID --member=\"serviceAccount:$SA_EMAIL\" --role=roles/aiplatform.user --quiet"
    run "gcloud projects remove-iam-policy-binding $PROJECT_ID --member=\"serviceAccount:$SA_EMAIL\" --role=roles/secretmanager.secretAccessor --quiet"
    run "gcloud iam service-accounts delete $SA_EMAIL --project=$PROJECT_ID --quiet"
    printf '    %s預算告警要用 budget 的完整資源名刪（display name 刪不了）：%s\n' "$D" "$R"
    run "gcloud billing budgets list --billing-account=\$(gcloud billing projects describe $PROJECT_ID --format='value(billingAccountName)' | sed 's#.*/##') --filter=\"displayName=$BUDGET_NAME\" --format='value(name)'"
    printf '    %s拿到 billingAccounts/XXX/budgets/YYY 之後：gcloud billing budgets delete <那個名字>%s\n' "$D" "$R"
    return 0
  fi

  printf '%s==> 刪掉整個專案 %s%s\n' "$B" "$PROJECT_ID" "$R"
  printf '    %s專案一刪，裡面的 Cloud Run / Cloud SQL / secret / SA 全部一起消失 —— 這是最乾淨也最不會漏掉費用的做法。%s\n' "$D" "$R"
  printf '    %s刪除後有 30 天緩衝期，期間可以 gcloud projects undelete %s 救回來。%s\n' "$D" "$PROJECT_ID" "$R"
  confirm "$PROJECT_ID"
  run "gcloud projects delete $PROJECT_ID --quiet"
  printf '    %s專案已排入刪除。帳單那邊也順手確認一下沒有殘留的 budget。%s\n' "$D" "$R"
  run "gcloud config unset project"
}

selfcheck() {
  local fails=0 out tmpd
  tmpd="$(mktemp -d)"
  printf '#!/bin/sh\ntouch "%s/CALLED"\nexit 1\n' "$tmpd" > "$tmpd/gcloud"; chmod +x "$tmpd/gcloud"

  # 1) 整個專案刪除的 dry-run
  out="$(PATH="$tmpd:$PATH" "$0" --dry-run 2>&1)"
  want() { case "$out" in *"$1"*) ;; *) echo "  x dry-run 輸出少了：$1"; fails=$((fails+1)) ;; esac; }
  want "gcloud projects delete agent-course-2026"
  want "undelete agent-course-2026"
  case "$out" in *$'\033'*) echo "  x 非 tty 卻吐了 ANSI escape"; fails=$((fails+1)) ;; esac
  [ ! -f "$tmpd/CALLED" ] || { echo "  x dry-run 真的跑了 gcloud"; fails=$((fails+1)); }

  # 2) --keep-project 的 dry-run：必須先解 IAM binding，才刪 SA（順序反了 binding 會留下孤兒 member）
  out="$(PATH="$tmpd:$PATH" "$0" --keep-project --dry-run 2>&1 </dev/null)"
  case "$out" in *"gcloud projects delete"*) echo "  x --keep-project 竟然要刪專案"; fails=$((fails+1)) ;; esac
  want "gcloud secrets delete gemini-api-key"
  want "remove-iam-policy-binding"
  want "gcloud iam service-accounts delete"
  local n_bind n_sa
  n_bind="$(printf '%s\n' "$out" | grep -n 'remove-iam-policy-binding' | tail -1 | cut -d: -f1)"
  n_sa="$(printf '%s\n' "$out" | grep -n 'service-accounts delete' | head -1 | cut -d: -f1)"
  [ -n "$n_bind" ] && [ -n "$n_sa" ] && [ "$n_bind" -lt "$n_sa" ] || { echo "  x 刪除順序錯：要先 remove-iam-policy-binding 再刪 SA"; fails=$((fails+1)); }

  # 3) 亂給旗標要吐用法並退出碼 2
  PATH="$tmpd:$PATH" "$0" --nope >/dev/null 2>&1
  [ "$?" -eq 2 ] || { echo "  x 未知旗標應該 exit 2"; fails=$((fails+1)); }

  # 4) PROJECT_ID 帶 shell 特殊字元 → 還沒碰到 confirm 就要 exit 2
  rm -f "$tmpd/CALLED"
  PATH="$tmpd:$PATH" PROJECT_ID='x; rm -rf /tmp/nope' "$0" --dry-run >/dev/null 2>&1
  [ "$?" -eq 2 ] || { echo "  x 帶分號的 PROJECT_ID 應該 exit 2"; fails=$((fails+1)); }
  [ ! -f "$tmpd/CALLED" ] || { echo "  x 不合法的 PROJECT_ID 竟然還跑了 gcloud"; fails=$((fails+1)); }

  # 5) 確認機制：打錯字串必須中止、退出碼非 0、且沒跑任何 gcloud
  rm -f "$tmpd/CALLED"
  if printf 'wrong-id\n' | PATH="$tmpd:$PATH" "$0" >/dev/null 2>&1; then
    echo "  x 打錯確認字串竟然沒中止"; fails=$((fails+1))
  fi
  [ ! -f "$tmpd/CALLED" ] || { echo "  x 確認失敗後還是跑了 gcloud"; fails=$((fails+1)); }

  rm -rf "$tmpd"
  if [ "$fails" -eq 0 ]; then echo "teardown.sh --self-check 全部通過"; else echo "teardown.sh --self-check 失敗 $fails 項"; exit 1; fi
}

if ${SELFCHECK}; then selfcheck; else main; fi
