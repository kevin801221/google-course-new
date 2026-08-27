#!/usr/bin/env bash
# Phase 4 部署腳本（投影片 444 的 runbook 變成可跑的東西）。
#
# 跑法：
#   ./deploy.sh --dry-run     # 預設：只印指令，不碰雲端（不花錢）
#   ./deploy.sh --apply       # 真的部署，會產生費用
#
# 部署順序＝依賴順序：先工具層、再專員、最後入口 —— 每一步都能獨立 smoke test。
# 需要的環境變數：PROJ（GCP 專案 ID）、REGION（預設 us-central1）、SUPABASE_URL、DB_PASSWORD
set -euo pipefail

MODE="${1:---dry-run}"
PROJ="${PROJ:-YOUR_PROJECT_ID}"
REGION="${REGION:-us-central1}"
SA="agent-sa@${PROJ}.iam.gserviceaccount.com"
# ⚠️ 未實測：官方 image 路徑請以 mcp-toolbox.dev 的文件為準，這裡只是預設值
TOOLBOX_IMAGE="${TOOLBOX_IMAGE:-us-central1-docker.pkg.dev/database-toolbox/toolbox/toolbox:latest}"
# ADK 的 session service 走 SQLAlchemy，前綴要 postgresql+asyncpg://（少了 async driver 直接報錯）
SESSION_URI="${SUPABASE_URL:-postgresql://USER:PW@HOST:5432/postgres}"
SESSION_URI="${SESSION_URI#postgresql://}"
SESSION_URI="postgresql+asyncpg://${SESSION_URI#postgresql+asyncpg://}"

run() {   # dry-run 就只印；apply 才執行
  if [ "$MODE" = "--apply" ]; then
    echo "+ $*" >&2
    "$@"
  else
    echo "  $*"
  fi
}

svc_url() {   # 服務網址：apply 時真的查，dry-run 印成 placeholder（不碰雲端）
  if [ "$MODE" = "--apply" ]; then
    gcloud run services describe "$1" --project "$PROJ" --region "$REGION" --format='value(status.url)'
  else
    echo "https://$1-XXXX.$REGION.run.app"
  fi
}

secret() {   # $1=secret 名 $2=值。--data-file=- 要有人餵 stdin，不然 apply 會卡住等你打字
  if [ "$MODE" = "--apply" ]; then
    echo "+ gcloud secrets create $1 (值從環境變數 pipe 進去)" >&2
    printf '%s' "$2" | gcloud secrets create "$1" --project "$PROJ" --data-file=- --quiet \
      || printf '%s' "$2" | gcloud secrets versions add "$1" --project "$PROJ" --data-file=- --quiet
  else
    echo "  printf '%s' \"\$$3\" | gcloud secrets create $1 --project $PROJ --data-file=- --quiet"
  fi
}

if [ "$MODE" != "--apply" ] && [ "$MODE" != "--dry-run" ]; then
  echo "用法：./deploy.sh [--dry-run|--apply]" >&2
  exit 2
fi

if [ "$MODE" = "--apply" ]; then
  : "${PROJ:?需要 PROJ}"; : "${SUPABASE_URL:?需要 SUPABASE_URL}"; : "${DB_PASSWORD:?需要 DB_PASSWORD}"
  [ "$PROJ" = "YOUR_PROJECT_ID" ] && { echo "PROJ 還是預設值，先 export PROJ=你的專案" >&2; exit 2; }
fi

echo "== 0) 機密就緒（已存在就補一個新版本，不會失敗）"
secret session-db-url "${SUPABASE_URL:-}" SUPABASE_URL
secret db-password "${DB_PASSWORD:-}" DB_PASSWORD
secret tools-yaml "$(cat tools.yaml)" '(cat tools.yaml)'

echo "== 1) 工具層：wiki-mcp（私有，唯讀）"
run gcloud run deploy wiki-mcp --source . --project "$PROJ" --region "$REGION" \
  --no-allow-unauthenticated --service-account "$SA" \
  --set-env-vars "MCP_TRANSPORT=http,WIKI_ALLOW_INGEST=0" \
  --set-secrets "DATABASE_URL=session-db-url:latest"

echo "== 2) 工具層：toolbox（官方 image ＋ 你的 tools.yaml）"
# 投影片 444 寫 --source toolbox/，但 Toolbox 是官方 image，本 repo 也沒有 toolbox/ 目錄
# （照抄會得到 ERROR: Source directory does not exist）。tools.yaml 用 secret 掛成檔案，改設定不用重 build。
run gcloud run deploy toolbox --image "$TOOLBOX_IMAGE" --project "$PROJ" --region "$REGION" \
  --no-allow-unauthenticated --service-account "$SA" \
  --set-secrets "/app/tools.yaml=tools-yaml:latest,DB_PASSWORD=db-password:latest" \
  --args "--tools-file,/app/tools.yaml,--address,0.0.0.0,--port,8080"

echo "== 3) A2A 研究服務（私有，獨立擴展）"
run gcloud run deploy research-a2a --source . --project "$PROJ" --region "$REGION" \
  --no-allow-unauthenticated --service-account "$SA" \
  --command uv --args "run,uvicorn,research_service.agent:a2a_app,--host,0.0.0.0,--port,8080"
# 名片上的 host 要是自己的公開網址；服務起來才知道網址，所以是「先部署再回填」兩步
run gcloud run services update research-a2a --project "$PROJ" --region "$REGION" \
  --update-env-vars "A2A_PUBLIC_URL=$(svc_url research-a2a)"

echo "== 4) IAM：只有 concierge 的 SA 能呼叫內部服務（最小權限）"
for SVC in wiki-mcp toolbox research-a2a; do
  run gcloud run services add-iam-policy-binding "$SVC" --project "$PROJ" --region "$REGION" \
    --member "serviceAccount:${SA}" --role roles/run.invoker
done

echo "== 5) 入口：concierge（ADK 幫你包容器＋掛 UI）"
# --session_service_uri 是「重整不失憶」的唯一開關（驗收 446-4）。少了它 session 存在記憶體，
# 冷啟動或擴展一次就全沒了，而且不會報錯。前綴要 postgresql+asyncpg://（SQLAlchemy async）。
run uv run adk deploy cloud_run --project "$PROJ" --region "$REGION" \
  --service_name concierge --with_ui --session_service_uri "$SESSION_URI" concierge/
# adk deploy 沒有 --set-env-vars，下游服務的網址只能部署完再回填（不填的話 TOOLBOX_URL 還是 127.0.0.1:5000）
run gcloud run services update concierge --project "$PROJ" --region "$REGION" \
  --update-env-vars "TOOLBOX_URL=$(svc_url toolbox),RESEARCH_A2A_URL=$(svc_url research-a2a)" \
  --update-secrets "DATABASE_URL=session-db-url:latest"

echo "== 6) smoke test（部署完照這個順序驗，壞在哪一層立刻知道）"
echo "  gcloud run services describe wiki-mcp --region $REGION --format='value(status.url)'"
echo "  curl -s -o /dev/null -w '%{http_code}\\n' \$WIKI_MCP_URL/mcp                      # 期望 403（沒帶 token）"
echo "  curl -H \"Authorization: Bearer \$(gcloud auth print-identity-token)\" \$WIKI_MCP_URL/mcp  # 期望 200/406"
echo "  curl -s \$RESEARCH_A2A_URL/.well-known/agent-card.json | uv run python -m json.tool"

if [ "$MODE" = "--apply" ]; then
  echo "== 部署完成。記得 uv run acceptance.py 走一遍雲端驗收，然後看帳單。"
else
  echo "dry-run OK：6 段、順序 secrets → wiki-mcp → toolbox → research-a2a → IAM → concierge（沒有碰任何雲端資源）"
fi
