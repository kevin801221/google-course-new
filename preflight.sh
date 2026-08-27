#!/usr/bin/env bash
# 課前環境檢查：開課前 10 分鐘全班一起跑，把壞掉的機器先抓出來。
#   ./preflight.sh          檢查
#   ./preflight.sh --fix    只印安裝指令，不自動裝（裝什麼由你決定）
# 退出碼：Day 1 必要項目有缺 → 1；其餘只警告 → 0
set -uo pipefail

if [ -t 1 ]; then G=$'\033[32m'; R=$'\033[31m'; Y=$'\033[33m'; D=$'\033[2m'; B=$'\033[1m'; N=$'\033[0m'
else G=; R=; Y=; D=; B=; N=; fi

FIX=${1:-}   # --fix：只想看修法時用，檢查照跑
day1_fail=0
declare -a fixes=()

row() { # 狀態 名稱 說明 修法
  local mark
  case $1 in
    ok)   mark="${G}✅${N}" ;;
    warn) mark="${Y}⚠️ ${N}" ;;
    bad)  mark="${R}❌${N}" ;;
  esac
  printf "  %s %-14s %s\n" "$mark" "$2" "${D}$3${N}"
  [ -n "${4:-}" ] && fixes+=("$4")
  return 0
}

need() { command -v "$1" >/dev/null 2>&1; }

echo "${B}課前環境檢查${N}  $(uname -s) $(uname -m)"

printf "\n"; echo "${B}Day 1 必要${N}（缺了 Lab 1 就開不了）"
if need uv; then row ok uv "$(uv --version)"
else row bad uv "找不到 —— 全課唯一的 Python 工作流" "curl -LsSf https://astral.sh/uv/install.sh | sh"; day1_fail=1; fi

if need git; then row ok git "$(git --version | cut -d' ' -f3)"
else row warn git "找不到（拉教材用）" "xcode-select --install  # macOS"; fi

if [ -n "${GEMINI_API_KEY:-}" ]; then
  row ok GEMINI_API_KEY "已設定（${#GEMINI_API_KEY} 字元）"
else
  row bad GEMINI_API_KEY "沒設 —— 去 https://aistudio.google.com/apikey 拿，免費層即可" 'export GEMINI_API_KEY="你的key"   # 建議寫進 ~/.zshrc'
  day1_fail=1
fi

# 真正的教室測試：uv 能不能裝套件（同時驗網路與 PyPI）
if need uv; then
  if out=$(cd "$(mktemp -d)" && uv run --no-project --with google-genai python -c "import google.genai;print('ok')" 2>&1 | tail -1); then
    [ "$out" = ok ] && row ok "uv+PyPI" "能從 PyPI 裝 google-genai（教室網路 OK）" \
      || row bad "uv+PyPI" "uv 跑起來但裝不了套件：$out" "檢查教室網路 / 公司 proxy"
    [ "$out" = ok ] || day1_fail=1
  else
    row bad "uv+PyPI" "裝不了套件（網路或 proxy 問題）" "檢查教室網路 / 公司 proxy"; day1_fail=1
  fi
fi

printf "\n"; echo "${B}Day 1 建議${N}（Lab 2/3/6 會用到）"
if need node; then
  v=$(node -v | tr -d 'v' | cut -d. -f1)
  [ "$v" -ge 20 ] 2>/dev/null && row ok node "$(node -v)（npx 型 MCP server 需要 ≥20）" \
    || row warn node "$(node -v) 太舊，npx 型 MCP server 需要 ≥20" "brew install node"
else row warn node "找不到 —— Lab 3/6 的 npx 型 MCP server 會起不來" "brew install node"; fi

need docker && row ok docker "$(docker --version | cut -d' ' -f3 | tr -d ,)" \
  || row warn docker "找不到 —— Lab 2 想在本機驗容器才需要（可跳過，直接 gcloud run deploy）" "https://docs.docker.com/desktop/"

printf "\n"; echo "${B}Day 2 必要${N}（Lab 5 之後全部踩在這上面）"
if need gcloud; then
  row ok gcloud "$(gcloud --version 2>/dev/null | head -1 | cut -d' ' -f4)"
  proj=$(gcloud config get-value project 2>/dev/null | grep -v '^(unset)$' || true)
  [ -n "$proj" ] && row ok "gcloud-proj" "$proj" || row warn "gcloud-proj" "還沒設 —— Lab 5 會建" "gcloud init"
  gcloud auth list --filter=status:ACTIVE --format='value(account)' 2>/dev/null | grep -q . \
    && row ok "gcloud-auth" "$(gcloud auth list --filter=status:ACTIVE --format='value(account)' 2>/dev/null | head -1)" \
    || row warn "gcloud-auth" "還沒登入" "gcloud auth login"
else
  row warn gcloud "找不到 —— Day 2 的 Lab 5/10 需要（Day 1 用不到，可今晚再裝）" "https://cloud.google.com/sdk/docs/install"
fi

printf "\n"; echo "${B}選配${N}"
need jq && row ok jq "$(jq --version)" || row warn jq "Lab 3.5 的腳本會用" "brew install jq"
need ffmpeg && row ok ffmpeg "$(ffmpeg -version 2>/dev/null | head -1 | cut -d' ' -f3)" \
  || row warn ffmpeg "Lab 4.5 產音檔會用" "brew install ffmpeg"

echo
if [ "$day1_fail" -eq 1 ]; then
  echo "${R}${B}Day 1 必要項目有缺，Lab 1 現在跑不起來。${N}"
else
  echo "${G}${B}Day 1 可以開始了。${N}${D}（Day 2 的 gcloud 今晚再裝也來得及）${N}"
fi

if [ ${#fixes[@]} -gt 0 ]; then
  printf "\n"; echo "${B}修法${N}${D}（自己貼，這支腳本不會替你裝東西）${N}"
  printf '  %s\n' "${fixes[@]}"
fi

exit "$day1_fail"
