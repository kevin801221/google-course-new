#!/usr/bin/env bash
# 兩層稽核：第一層字面（穩定、離線可測），第二層語意（需要 GEMINI_API_KEY）。
# 任何一層有殘留就非零退出，CI 直接紅燈。
set -euo pipefail

echo "── 第一層：字面稽核 ──" >&2
uv run civicguard-audit --json | jq -e 'length == 0' > /dev/null

echo "── 第二層：語意稽核（沒有 GEMINI_API_KEY 就跳過）──" >&2
if [[ -n "${GEMINI_API_KEY:-}" ]]; then
  # sed 那段是必要的：模型很愛把 JSON 包在 ```json 圍籬裡，直接 fromjson 會炸
  gemini -p "掃描整個 repo，列出所有直接呼叫 python、python3、pip 的指令或文件片段，\
用 JSON 陣列回覆；沒有就回空陣列。只輸出 JSON。" \
    --output-format json \
    | jq -r '.response' \
    | sed -e 's/^```json//' -e 's/^```$//' \
    | jq -e 'length == 0' > /dev/null
else
  echo "skip: 沒有 GEMINI_API_KEY" >&2
fi

uvx ruff check .
echo "稽核全過" >&2
