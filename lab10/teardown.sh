#!/usr/bin/env bash
# Lab 10 清理：刪掉這個 Lab 建的所有雲端資源。
#
# 用法：
#   ./teardown.sh --dry-run     # 先看要刪什麼
#   ./teardown.sh               # 真的刪（每一項都 || true，刪不到不中斷）
#   ./teardown.sh --keep-secrets  # 留下機密（Capstone 還要用）
#
# 刪不掉的東西不會讓腳本停下來 —— 清理腳本最重要的是「跑完」，不是「乾淨地失敗」。

set -eu
cd "$(dirname "$0")"
. ./config.sh

DRY=0; KEEP_SECRETS=0
for a in "$@"; do
  case "$a" in
    --dry-run) DRY=1 ;;
    --keep-secrets) KEEP_SECRETS=1 ;;
    -h|--help) sed -n '2,10p' "$0"; exit 0 ;;
    *) echo "不認得的旗標：$a" >&2; exit 2 ;;
  esac
done

runsh() { if [ "$DRY" = 1 ]; then printf '  $ %s\n' "$1"; else sh -c "$1" || true; fi; }

say "1/5 刪四個 Cloud Run service（scale-to-zero 不等於免費：image 還佔 Artifact Registry）"
for svc in "$AGENT_SVC" "$A2A_SVC" "$TOOLBOX_SVC" "$MCP_SVC"; do
  runsh "gcloud run services delete '$svc' --region '$REGION' --project '$PROJECT_ID' --quiet"
done

say "2/5 刪 Agent Engine（閒置也計費，這個一定要刪）"
runsh "gcloud beta ai agent-engines list --region '$REGION' --project '$PROJECT_ID' --format='value(name)'"
# 刻意不自動刪：誤刪別的 reasoningEngine 比漏刪還痛。把上面列出的 name 貼進下面這行自己跑。
# ponytail: 一行人工步驟換掉「xargs 自動刪」的誤刪風險，代價是你可能忘記貼 —— 驗收清單有這一項。
echo "  ↑ 把上面列出的 resource name 貼進這一行自己跑（或用 Console：Vertex AI -> Agent Engine）："
echo "    gcloud beta ai agent-engines delete <NAME> --region '$REGION' --project '$PROJECT_ID' --quiet"

say "3/5 刪 Cloud Build 留下的 image（--source 部署會在 Artifact Registry 堆 image）"
runsh "gcloud artifacts repositories delete cloud-run-source-deploy --location '$REGION' --project '$PROJECT_ID' --quiet"

say "4/5 刪 service account 與它的 project-level 綁定"
for role in roles/aiplatform.user roles/secretmanager.secretAccessor roles/logging.logWriter; do
  runsh "gcloud projects remove-iam-policy-binding '$PROJECT_ID' --member 'serviceAccount:$SA' --role '$role' --condition None --quiet"
done
runsh "gcloud iam service-accounts delete '$SA' --project '$PROJECT_ID' --quiet"

if [ "$KEEP_SECRETS" = 1 ]; then
  say "5/5 機密保留（--keep-secrets）"
else
  say "5/5 刪機密"
  for s in "$SECRET_SESSION_DB" "$SECRET_DB_PASSWORD"; do
    runsh "gcloud secrets delete '$s' --project '$PROJECT_ID' --quiet"
  done
fi

say "本機暫存"
runsh "rm -rf '$BUILD' concierge/requirements.txt"

cat <<EOF

清完了。最後一件事（腳本做不到，要用眼睛看）：
  1. 帳單頁面確認 Cloud Run / Vertex AI 這兩列沒有繼續長
     https://console.cloud.google.com/billing
  2. 服務清單確認是空的
     gcloud run services list --region $REGION --project $PROJECT_ID
  3. Supabase 那邊沒有動到 —— 資料庫還在，Capstone 會用到
EOF
