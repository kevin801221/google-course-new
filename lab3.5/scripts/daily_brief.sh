#!/usr/bin/env bash
# 每日示警簡報：資料抓取與語言生成分開，出錯時知道是哪一段壞了。
set -euo pipefail

CITIES=("臺南市" "高雄市" "屏東縣")
OUT="reports/$(date +%F).md"
mkdir -p reports data

for city in "${CITIES[@]}"; do
  # 1) 先用 uv 抓原始資料（絕不直接呼叫 python）。每個縣市一份，不要三份簡報共用同一份資料。
  uv run civicguard-fetch --city "$city" > "data/${city}.json"

  # 2) 讓 Gemini CLI 依專案記憶產出人話簡報。用 jq 取 .response，不 parse 人類文字。
  gemini -p "讀 data/${city}.json，依 AGENTS.md 的分級規則產出 ${city} 的示警簡報，\
150 字內，開頭一句講結論。" \
    --output-format json | jq -r '.response' >> "$OUT"
done

# 3) 驗收：沒有內容就讓 job 失敗（gemini 吐空字串時仍會回 exit 0）
test -s "$OUT" || { echo "empty brief" >&2; exit 1; }
