#!/usr/bin/env bash
# Lab 2：把對照組實作部署到 Cloud Run。可直接貼進終端機執行：
#     export GEMINI_API_KEY="..."
#     bash deploy.sh
# 覆寫預設值：SERVICE=my-svc REGION=asia-east1 bash deploy.sh
set -euo pipefail

SERVICE="${SERVICE:-tldr-tw}"
REGION="${REGION:-us-central1}"
: "${GEMINI_API_KEY:?先 export GEMINI_API_KEY，不然部署上去的 app 會每次都 500}"

PROJECT="$(gcloud config get-value project 2>/dev/null)"
[ -n "$PROJECT" ] && [ "$PROJECT" != "(unset)" ] || { echo "先 gcloud config set project <ID>"; exit 1; }
echo "→ project=$PROJECT service=$SERVICE region=$REGION"

# 第一次部署必開這三個 API，少一個 build 階段就會 403
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com

# --allow-unauthenticated：不加的話手機打開會看到 403 Forbidden（Cloud Run 預設私有）
# ponytail: key 用 --set-env-vars 直接塞, 正式環境改 Secret Manager（M5 教）
gcloud run deploy "$SERVICE" \
  --source . \
  --region "$REGION" \
  --allow-unauthenticated \
  --set-env-vars "GEMINI_API_KEY=$GEMINI_API_KEY" \
  --memory 512Mi \
  --max-instances 3
# --max-instances 是免費層的保險絲：被人亂打也不會爆掉你的 Gemini API 配額

URL="$(gcloud run services describe "$SERVICE" --region "$REGION" --format='value(status.url)')"
echo "→ 上線網址：$URL"
curl -fsS "$URL/healthz" && echo " ← has_key 必須是 true"
