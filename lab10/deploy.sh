#!/usr/bin/env bash
# Lab 10：把 M6-M9 的元件推上雲。
#
# 用法：
#   ./deploy.sh --dry-run            # 只印指令、不動任何雲端資源（先看一遍再跑）
#   ./deploy.sh                      # 全部階段照順序跑
#   ./deploy.sh mcp toolbox          # 只跑指定階段
#   ./deploy.sh --dry-run agent      # 兩個都可以組合
#
# 階段：apis sa secrets mcp toolbox a2a iam agent engine
#   走 walkthrough 時故意先跑 agent 再跑 iam —— 讓 403 發生一次，你才記得住。
#
# 先設好：export SESSION_DB_URL=... ; export DB_PASSWORD=...（只有 secrets 階段要）

set -eu
cd "$(dirname "$0")"
. ./config.sh

DRY=0
STAGES=""
for a in "$@"; do
  case "$a" in
    --dry-run) DRY=1 ;;
    -h|--help) sed -n '2,13p' "$0"; exit 0 ;;
    -*) echo "不認得的旗標：$a" >&2; exit 2 ;;
    *) STAGES="$STAGES $a" ;;
  esac
done
[ -n "$STAGES" ] || STAGES="apis sa secrets mcp toolbox a2a iam agent engine"

# ponytail: dry-run 用 printf 印 argv，引號還原得不完美（含空白的參數看起來會怪）。
#   要能直接複製貼上跑，改成 printf '%q ' 就好，但 %q 是 bash-only，macOS 的 sh 沒有。
run()   { if [ "$DRY" = 1 ]; then printf '  $ %s\n' "$*"; else "$@"; fi; }
# 有 pipe / 有機密的指令走這條：dry-run 印出的是變數名而不是機密值
runsh() { if [ "$DRY" = 1 ]; then printf '  $ %s\n' "$1"; else sh -c "$1"; fi; }

# 把某個 lab 目錄複製到 .build/<元件>，蓋上對應的 Dockerfile。
# 為什麼要複製：Cloud Run 的 --source 會上傳整個目錄，我們不想把 Dockerfile
# 寫進別人的 lab 目錄，也不想把 .venv（幾百 MB）傳上 Cloud Build。
prep() {
  src="$1"; name="$2"
  [ -d "$src" ] || { echo "找不到 $src —— 先做完對應的 Lab，或改 config.sh 的路徑" >&2; exit 1; }
  run rm -rf "$BUILD/$name"
  run mkdir -p "$BUILD"
  run cp -R "$src" "$BUILD/$name"
  run cp "dockerfiles/$name.Dockerfile" "$BUILD/$name/Dockerfile"
  runsh "rm -rf '$BUILD/$name/.venv' '$BUILD/$name/__pycache__' '$BUILD/$name/.pytest_cache'"
}

stage_apis() {
  say "啟用 API（第一次跑要等 1-2 分鐘）"
  run gcloud services enable \
    run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com \
    aiplatform.googleapis.com secretmanager.googleapis.com \
    --project "$PROJECT_ID"
}

stage_sa() {
  say "建 service account：$SA"
  # 已存在會回 ALREADY_EXISTS，用 || true 讓重跑不中斷（腳本要能重複執行）
  runsh "gcloud iam service-accounts create '$SA_NAME' --display-name='Lab10 agent runtime' --project='$PROJECT_ID' || true"
  for role in roles/aiplatform.user roles/secretmanager.secretAccessor roles/logging.logWriter; do
    run gcloud projects add-iam-policy-binding "$PROJECT_ID" \
      --member "serviceAccount:$SA" --role "$role" --condition None
  done
}

stage_secrets() {
  say "機密進 Secret Manager（不進 git、不進環境變數檔）"
  # dry-run 只是讀指令，不該逼你先有 Supabase 的密碼才看得到要跑什麼
  if [ "$DRY" = 0 ]; then
    : "${SESSION_DB_URL:?請先 export SESSION_DB_URL='postgresql+asyncpg://...'（Lab 8 的 Session pooler 連線字串）}"
    : "${DB_PASSWORD:?請先 export DB_PASSWORD='...'（Supabase 資料庫密碼，Toolbox 要用）}"
  fi
  # create 失敗（已存在）就 versions add —— 腳本要能重跑
  for pair in "$SECRET_SESSION_DB:SESSION_DB_URL" "$SECRET_DB_PASSWORD:DB_PASSWORD"; do
    name="${pair%%:*}"; var="${pair##*:}"
    runsh "printf '%s' \"\$$var\" | gcloud secrets create '$name' --data-file=- --project='$PROJECT_ID' || printf '%s' \"\$$var\" | gcloud secrets versions add '$name' --data-file=- --project='$PROJECT_ID'"
  done
}

stage_mcp() {
  say "① MCP server 上雲（私有）"
  prep "$LAB6_DIR" mcp
  run gcloud run deploy "$MCP_SVC" \
    --source "$BUILD/mcp" --region "$REGION" --project "$PROJECT_ID" \
    --no-allow-unauthenticated --service-account "$SA" \
    --max-instances 3
}

stage_toolbox() {
  say "② Toolbox 上雲（私有，連 Supabase）"
  prep "$LAB8_DIR" toolbox
  run gcloud run deploy "$TOOLBOX_SVC" \
    --source "$BUILD/toolbox" --region "$REGION" --project "$PROJECT_ID" \
    --no-allow-unauthenticated --service-account "$SA" \
    --set-secrets "DB_PASSWORD=$SECRET_DB_PASSWORD:latest" \
    --max-instances 3
}

stage_a2a() {
  say "③ hotel agent 上雲（A2A，名片公開可讀）"
  prep "$LAB9_DIR" a2a
  # 投影片步驟 ③ 要「名片公開可讀」→ 這個服務開 allow-unauthenticated。
  # 投影片 419 頁示範的是 --no-allow-unauthenticated（正式做法），兩者的取捨見 walkthrough 步驟 3。
  run gcloud run deploy "$A2A_SVC" \
    --source "$BUILD/a2a" --region "$REGION" --project "$PROJECT_ID" \
    --allow-unauthenticated --service-account "$SA" \
    --max-instances 3
}

stage_iam() {
  say "IAM 串接：讓 $SA 能呼叫私有服務"
  for svc in "$MCP_SVC" "$TOOLBOX_SVC"; do
    run gcloud run services add-iam-policy-binding "$svc" \
      --region "$REGION" --project "$PROJECT_ID" \
      --member "serviceAccount:$SA" --role roles/run.invoker
  done
}

stage_agent() {
  say "④⑤ 主 agent 上雲（Cloud Run，--with_ui + session 落 Supabase）"
  if [ "$DRY" = 1 ]; then
    M="\$(svc_url $MCP_SVC)"; T="\$(svc_url $TOOLBOX_SVC)"; A="\$(svc_url $A2A_SVC)"
  else
    M=$(svc_url "$MCP_SVC"); T=$(svc_url "$TOOLBOX_SVC"); A=$(svc_url "$A2A_SVC")
    [ -n "$M$T$A" ] || { echo "三個依賴服務都查不到網址，先跑 mcp / toolbox / a2a 階段" >&2; exit 1; }
  fi
  echo "  MCP=$M"; echo "  TOOLBOX=$T"; echo "  A2A=$A"

  # adk deploy 產的 Dockerfile 是 `RUN pip install -r requirements.txt`，
  # 沒有這個檔容器裡只有 google-adk[a2a]，toolbox-adk 會缺 → 開機就掛。
  run uv export --no-hashes --no-dev --no-emit-project -o concierge/requirements.txt

  # --session_service_uri 用單引號的 '$SESSION_DB_URL'：
  #   adk 產的 Dockerfile CMD 是 shell form，變數在容器啟動時才展開，
  #   連線字串因此留在 Secret Manager，不會被烤進 image layer。
  #
  # agent 路徑後面那個 `--` 不能省：adk deploy cloud_run 自己的旗標到 `--` 為止，
  #   後面的一律原樣轉給 gcloud run deploy。少了它 click 會直接拒絕：
  #   Error: No such option '--no-allow-unauthenticated'.
  run uv run adk deploy cloud_run \
    --project="$PROJECT_ID" --region="$REGION" \
    --service_name="$AGENT_SVC" --app_name=concierge \
    --with_ui --trace_to_cloud \
    --session_service_uri='$SESSION_DB_URL' \
    concierge \
    -- \
    --no-allow-unauthenticated \
    --service-account="$SA" \
    --set-secrets="SESSION_DB_URL=$SECRET_SESSION_DB:latest" \
    --set-env-vars="MCP_URL=$M,TOOLBOX_URL=$T,A2A_URL=$A" \
    --max-instances=3
}

stage_engine() {
  say "⑦ Agent Engine 對照組（同一份 concierge 再部署一次）"
  # Agent Engine 沒有 --set-env-vars 可用：adk 是讀 agent 目錄裡的 .env 當環境變數
  # （cli_deploy.py 的 to_agent_engine 走 dotenv_values(agent_folder/.env)）。
  # 沒有這三個網址，容器一開機 agent.py 就 KeyError: 'MCP_URL'。
  if [ "$DRY" = 0 ] && ! grep -q '^MCP_URL=' concierge/.env 2>/dev/null; then
    echo "concierge/.env 裡沒有 MCP_URL —— 先做這件事：" >&2
    echo "  cp concierge/.env.sample concierge/.env" >&2
    for v in "MCP_URL $MCP_SVC" "TOOLBOX_URL $TOOLBOX_SVC" "A2A_URL $A2A_SVC"; do
      set -- $v
      echo "  $1=$(svc_url "$2")" >&2
    done
    exit 1
  fi
  run uv export --no-hashes --no-dev --no-emit-project -o concierge/requirements.txt
  # ADK 2.7.1 的 --staging_bucket 已 deprecated（投影片 403 頁還有寫，帶了只會噴黃字警告）
  run uv run adk deploy agent_engine \
    --project="$PROJECT_ID" --region="$REGION" \
    --display_name="Lab10 Concierge" \
    concierge
}

for s in $STAGES; do
  case "$s" in
    apis|sa|secrets|mcp|toolbox|a2a|iam|agent|engine) "stage_$s" ;;
    *) echo "不認得的階段：$s（可用：apis sa secrets mcp toolbox a2a iam agent engine）" >&2; exit 2 ;;
  esac
done

if [ "$DRY" = 1 ]; then
  printf '\n（--dry-run：以上指令都沒有真的執行）\n'
fi
