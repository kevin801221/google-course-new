#!/usr/bin/env bash
# Lab 10 逐項驗收：四個服務健康嗎、私有服務對「沒帶 token 的人」是不是真的 403。
#
# 用法：
#   ./verify.sh --self-check   # 離線驗判定邏輯，不連網、不花錢（交付前必跑）
#   ./verify.sh                # 真的打雲端，逐項印 PASS/FAIL
#   ./verify.sh --verbose      # 順便把每個回應的前 200 字印出來
#
# 判定規則（重點在第二條）：
#   403     必須是 403 —— 沒帶 token 就該被 Cloud Run 前端擋掉
#   not403  只要不是 401/403/000 就算過 —— /mcp 用 GET 打會回 406，
#           那是「IAM 放我進去了，只是我用錯 HTTP 方法」，這也算通過
#   200     必須是 200

set -eu
cd "$(dirname "$0")"

# ---- 純判定邏輯（--self-check 驗的就是這兩個函式，不碰網路）----------------

judge() { # judge <expect> <actual_code> -> PASS / FAIL
  case "$1" in
    403)    [ "$2" = 403 ] && echo PASS || echo FAIL ;;
    200)    [ "$2" = 200 ] && echo PASS || echo FAIL ;;
    not403) case "$2" in 401|403|000|"") echo FAIL ;; *) echo PASS ;; esac ;;
    *)      echo "FAIL" ;;
  esac
}

# ID token 的 audience 必須全等於目標服務的根網址：多一個 /mcp 就 401。
audience() { # audience <url> -> scheme://host
  printf '%s\n' "$1" | sed -E 's#^(https?://[^/]+).*#\1#'
}

# ---- --self-check：假資料 + assert，不連網 -------------------------------

ck() { # ck <實際> <預期> <說明>
  [ "$1" = "$2" ] || { echo "self-check FAIL：$3 → 得到 '$1'，預期 '$2'"; exit 1; }
}

self_check() {
  ck "$(judge 403 403)"       PASS "沒帶 token 拿到 403 = 私有部署生效"
  ck "$(judge 403 200)"       FAIL "沒帶 token 卻拿到 200 = 服務是公開的，危險"
  ck "$(judge 403 000)"       FAIL "000 是連不上，不能當成「被擋掉」"
  ck "$(judge 200 200)"       PASS "帶 token 拿到 200"
  ck "$(judge 200 404)"       FAIL "404 不是 200"
  ck "$(judge not403 406)"    PASS "406 = IAM 過了，只是 GET 打 /mcp 用錯方法"
  ck "$(judge not403 200)"    PASS "200 當然算過"
  ck "$(judge not403 403)"    FAIL "403 = IAM 沒過，這才是要抓的"
  ck "$(judge not403 401)"    FAIL "401 = token audience 錯了，也要抓"
  ck "$(judge not403 "")"     FAIL "空字串（curl 沒跑起來）不能算過"
  ck "$(audience https://mcp-tools-abc123-uc.a.run.app/mcp)" \
     "https://mcp-tools-abc123-uc.a.run.app" "audience 要砍掉 /mcp 路徑"
  ck "$(audience https://x-uc.a.run.app)" \
     "https://x-uc.a.run.app" "沒有路徑時原樣回傳"
  ck "$(audience http://localhost:3000/mcp)" \
     "http://localhost:3000" "proxy 也要能算（雖然 proxy 不需要 token）"
  echo "self-check ok"
}

if [ "${1:-}" = "--self-check" ]; then self_check; exit 0; fi

# ---- 真的打雲端 ----------------------------------------------------------

. ./config.sh
VERBOSE=0
if [ "${1:-}" = "--verbose" ]; then VERBOSE=1; fi

# 中文全寬字沒辦法用 printf 對齊 → 定寬欄位放前面，中文標籤放最後
row() { printf '%-6s %-5s %s\n' "$1" "$2" "$3"; }

PASS=0; FAIL=0
# 沒裝 gcloud 的話，下面每一行都會噴 command not found —— 先講清楚
command -v gcloud >/dev/null || {
  echo "找不到 gcloud。這支腳本要打真的雲端資源；只想離線驗判定邏輯就跑 ./verify.sh --self-check" >&2
  exit 2
}
TOKEN="$(gcloud auth print-identity-token)"

hit() { # hit <名稱> <expect> <url> [auth]  —— auth 給 "auth" 就帶 token
  name="$1"; expect="$2"; url="$3"; auth="${4:-}"
  if [ -z "$url" ]; then
    row FAIL "-" "$name（服務不存在或查不到網址）"
    FAIL=$((FAIL + 1)); return 0
  fi
  if [ "$auth" = auth ]; then
    body="$(curl -s -m 20 -w '\n%{http_code}' -H "Authorization: Bearer $TOKEN" "$url" || true)"
  else
    body="$(curl -s -m 20 -w '\n%{http_code}' "$url" || true)"
  fi
  code="$(printf '%s' "$body" | tail -n 1)"
  r="$(judge "$expect" "$code")"
  row "$r" "$code" "$name"
  if [ "$VERBOSE" = 1 ]; then
    printf '    %s\n' "$(printf '%s' "$body" | head -c 200 | tr '\n' ' ')"
  fi
  if [ "$r" = PASS ]; then PASS=$((PASS + 1)); else FAIL=$((FAIL + 1)); fi
}

MCP_URL="$(svc_url "$MCP_SVC")"
TOOLBOX_URL="$(svc_url "$TOOLBOX_SVC")"
A2A_URL="$(svc_url "$A2A_SVC")"
AGENT_URL="$(svc_url "$AGENT_SVC")"

# 表頭不能走 row()：中文是全寬字，printf 的 %-6s 是算 byte 的，對不齊 → 手動補空白
printf '%s\n' "結果   HTTP  檢查項"
printf '%s\n' "----------------------------------------------------------"

# ① MCP server：私有 + proxy/token 才進得去
hit "mcp 未授權（應被擋）"          403    "${MCP_URL:+$MCP_URL/mcp}"
hit "mcp 帶 ID token"               not403 "${MCP_URL:+$MCP_URL/mcp}" auth

# ② Toolbox：私有；/api/toolset 是它的清單端點
hit "toolbox 未授權（應被擋）"      403    "${TOOLBOX_URL:+$TOOLBOX_URL/api/toolset}"
hit "toolbox 帶 ID token"           200    "${TOOLBOX_URL:+$TOOLBOX_URL/api/toolset}" auth

# ③ A2A：名片要公開讀得到（步驟 ③ 的驗收條件）
hit "a2a 名片公開可讀"              200    "${A2A_URL:+$A2A_URL/.well-known/agent-card.json}"

# ④ 主 agent：私有，帶 token 才看得到 app 清單
hit "agent 未授權（應被擋）"        403    "${AGENT_URL:+$AGENT_URL/list-apps}"
hit "agent 帶 ID token"             200    "${AGENT_URL:+$AGENT_URL/list-apps}" auth

# 名片內容要真的是 hotel agent，不是隨便一個 200
if [ -n "$A2A_URL" ] && curl -s -m 20 "$A2A_URL/.well-known/agent-card.json" | grep -q '"name"'; then
  row PASS "-" "a2a 名片含 name 欄位"; PASS=$((PASS + 1))
else
  row FAIL "-" "a2a 名片含 name 欄位"; FAIL=$((FAIL + 1))
fi

# IAM：agent-sa 真的拿到 run.invoker 了嗎（403 的頭號原因就是這條沒綁）
for svc in "$MCP_SVC" "$TOOLBOX_SVC"; do
  if gcloud run services get-iam-policy "$svc" --region "$REGION" --project "$PROJECT_ID" \
       --format json 2>/dev/null | grep -q "$SA"; then
    row PASS "-" "$svc 有綁 $SA_NAME 的 run.invoker"; PASS=$((PASS + 1))
  else
    row FAIL "-" "$svc 有綁 $SA_NAME 的 run.invoker"; FAIL=$((FAIL + 1))
  fi
done

# 機密存在嗎
for s in "$SECRET_SESSION_DB" "$SECRET_DB_PASSWORD"; do
  if gcloud secrets describe "$s" --project "$PROJECT_ID" >/dev/null 2>&1; then
    row PASS "-" "secret $s 存在"; PASS=$((PASS + 1))
  else
    row FAIL "-" "secret $s 存在"; FAIL=$((FAIL + 1))
  fi
done

printf '%s\n' "--------------------------------------------------------------"
printf 'PASS=%s  FAIL=%s\n' "$PASS" "$FAIL"
[ "$FAIL" = 0 ] || exit 1
