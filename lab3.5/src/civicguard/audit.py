"""CivicGuard：uv-only 稽核器 —— 掃 repo 找出違反「只准用 uv」的殘留。

這支是 CI 的把關者：乾淨 exit 0、有殘留 exit 1，輸出走 JSON 不吐人類文字。
它跟 gemini 的語意稽核是兩層：這層抓字面違規（穩定、可測），
gemini 那層抓「文件講的規則跟程式碼不一致」（聰明、但不穩定）。

跑法：
    uv run civicguard-audit --self-check
    uv run civicguard-audit                       # 人看的
    uv run civicguard-audit --json | jq -e 'length == 0'
"""

import fnmatch
import json
import os
import re
import sys
from pathlib import Path

# (規則名, 樣式, 建議改法)
RULES = [
    ("pip-install", r"\bpip3?\s+install\b", "改用 uv add <pkg>"),
    ("venv", r"\b(python3?\s+-m\s+venv|virtualenv)\b", "刪掉，uv init 已經建好環境"),
    ("activate", r"source\s+\S*\.venv/bin/activate", "刪掉，uv run 不需要 activate"),
    ("bare-python", r"(?<!uv run )\bpython3?\s+[\w./-]+\.py\b", "改用 uv run <script>.py"),
    ("requirements", r"\brequirements\.txt\b", "來源是 uv.lock；真要交付才用 uv export"),
]

# 只掃「會被執行或會被 Agent 當規則讀」的東西。教材文件（PRD/SPEC/walkthrough）本來就寫滿反例。
# ponytail: include/skip 是寫死的清單，要做成 .uvauditignore 等到真的有第二個專案再說。
DEFAULT_INCLUDE = ("*.py", "*.sh", "*.toml", "*.yml", "*.yaml", "AGENTS.md", "GEMINI.md",
                   "docs/**", "memory/**", ".gemini/**", ".agents/**")
SKIP_DIRS = {".venv", ".git", "__pycache__", "node_modules", ".ruff_cache", "reports", "data"}
SKIP_FILES = {"uv.lock", "PRD.md", "SPEC.md", "walkthrough.md", "audit.py"}
EXEMPT = "uv-ok"          # 這行有這個字就跳過（給教材與錯誤訊息範例用）


def walk(root: str, include=DEFAULT_INCLUDE):
    """回傳要掃的檔案相對路徑。"""
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            rel = os.path.relpath(os.path.join(dirpath, fn), root)
            if os.path.basename(rel) in SKIP_FILES:
                continue
            if any(fnmatch.fnmatch(rel, p) or fnmatch.fnmatch(os.path.basename(rel), p) for p in include):
                yield rel


def scan_text(text: str, path: str = "-") -> list[dict]:
    """掃一段文字，回傳違規清單。"""
    hits = []
    for i, line in enumerate(text.splitlines(), 1):
        if EXEMPT in line:
            continue
        for rule, pat, fix in RULES:
            if re.search(pat, line):
                hits.append({"file": path, "line": i, "rule": rule,
                             "text": line.strip()[:120], "fix": fix})
    return hits


def scan_repo(root: str = ".", include=DEFAULT_INCLUDE) -> list[dict]:
    hits = []
    for rel in walk(root, include):
        try:
            text = Path(root, rel).read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue          # 二進位或讀不到就跳過，稽核不該因為一張圖片而失敗
        hits += scan_text(text, rel)
    return hits


def _self_check() -> None:
    bad = "RUN pip install httpx\n" \
          "python3 -m venv .venv\n" \
          "source .venv/bin/activate\n" \
          "python main.py\n" \
          "pip install ruff   # uv-ok 這行是教材反例\n"
    hits = scan_text(bad, "x.sh")
    rules = [h["rule"] for h in hits]
    assert rules == ["pip-install", "venv", "activate", "bare-python"], rules
    assert hits[0]["line"] == 1 and hits[3]["line"] == 4
    # 正確寫法一條都不能被誤判
    good = "uv add httpx\nuv run main.py\nuv run pytest -q\nuvx ruff check .\nuv sync --frozen\n"
    assert scan_text(good) == [], scan_text(good)
    # uv run python -c 不是「直接呼叫 python」，不能誤報
    assert scan_text('uv run python -c "import ast"') == []
    # 但 uv run 後面接 .py 也不該報（bare-python 的 lookbehind 要生效）
    assert scan_text("uv run scripts/x.py") == []
    print("audit self-check ok")


def main() -> None:
    argv = sys.argv[1:]
    if "--self-check" in argv:
        return _self_check()
    hits = scan_repo(".")
    if "--json" in argv:
        print(json.dumps(hits, ensure_ascii=False, indent=2))
    else:
        for h in hits:
            print(f"{h['file']}:{h['line']}  [{h['rule']}]  {h['text']}\n    → {h['fix']}", file=sys.stderr)
        print(f"稽核完成：{len(hits)} 處違規", file=sys.stderr)
    sys.exit(1 if hits else 0)


if __name__ == "__main__":
    main()
