#!/usr/bin/env bash
# Lab 10 的唯一設定檔。deploy.sh / verify.sh / teardown.sh 都 source 這支。
# 只改這裡，三支腳本都跟著變。環境變數可覆蓋（方便同時開兩個專案對照）。

PROJECT_ID="${GOOGLE_CLOUD_PROJECT:-agent-course-2026}"
REGION="${GOOGLE_CLOUD_LOCATION:-us-central1}"

# 四個 Cloud Run service 名（也是 verify/teardown 的目標）
MCP_SVC="${MCP_SVC:-mcp-tools}"
TOOLBOX_SVC="${TOOLBOX_SVC:-toolbox}"
A2A_SVC="${A2A_SVC:-hotel-a2a}"
AGENT_SVC="${AGENT_SVC:-concierge-agent}"

# 一個 SA 走完全部鏈路（課程規模夠用）
# ponytail: 四個服務共用一個 SA，最小權限只做到「不是 Editor」。
#   正式環境一個服務一個 SA，災害半徑才切得開。
SA_NAME="${SA_NAME:-agent-sa}"
SA="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

# Secret Manager 的機密名稱（值不進這個檔案）
SECRET_SESSION_DB="${SECRET_SESSION_DB:-session-db-url}"
SECRET_DB_PASSWORD="${SECRET_DB_PASSWORD:-db-password}"

# 前面 Lab 的產物在哪（相對於 lab10/）
LAB6_DIR="${LAB6_DIR:-../lab6}"   # MCP server（server.py）
LAB8_DIR="${LAB8_DIR:-../lab8}"   # Toolbox 設定（tools.yaml）
LAB9_DIR="${LAB9_DIR:-../lab9}"   # A2A hotel service（hotel_service/agent.py）

BUILD="${BUILD:-.build}"          # 打包暫存區，只在 lab10/ 底下動

# 取某個 service 的網址；服務不存在就回空字串（呼叫端自己判斷）
svc_url() {
  gcloud run services describe "$1" \
    --region "$REGION" --project "$PROJECT_ID" \
    --format 'value(status.url)' 2>/dev/null || true
}

say() { printf '\n=== %s\n' "$*"; }
