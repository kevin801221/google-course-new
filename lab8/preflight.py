# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml"]
# ///
"""tools.yaml 的離線體檢：在啟動 Toolbox 之前把設定檔的錯抓出來。

Toolbox 對某些設定錯誤是「啟動成功但工具行為不對」（例如 $N 對不上參數），
啟動後才發現要多花五分鐘來回，所以先在本機用純文字檢查一輪。

上面的 PEP 723 檔頭讓 uv 自己抓 pyyaml —— lab8/ 沒有 pyproject.toml，
少了檔頭 `uv run preflight.py` 會噴 ModuleNotFoundError: No module named 'yaml'。

跑法：
  uv run preflight.py                  # 檢查 ./tools.yaml
  uv run preflight.py other.yaml       # 檢查別的檔
  uv run preflight.py --self-check     # 離線自我檢查，不連網不花錢
  uv run preflight.py --aha            # 啊哈 demo：模型能碰的 vs 碰不到的
"""
import os
import re
import sys
import unicodedata

import yaml

REQUIRED = {"source": ["name", "type"], "tool": ["name", "type", "source", "statement"],
            "toolset": ["name", "tools"]}


def check(docs):
    """回傳問題清單；'x ' 開頭是錯（會讓 Toolbox 行為不對），'! ' 開頭是提醒。

    # ponytail: 只做離線純文字檢查，不驗 SQL 語意（欄位／表存不存在）；
    # 要驗就得連 DB 做 prepare，那就不是「啟動前三秒體檢」了
    """
    problems, names = [], {}
    for i, d in enumerate(docs):
        if not isinstance(d, dict):
            problems.append(f"x 第 {i + 1} 份文件不是 mapping（YAML 縮排或 --- 分隔寫壞了）")
            continue
        kind = d.get("kind")
        if kind not in REQUIRED:
            problems.append(f"x 第 {i + 1} 份文件的 kind={kind!r} 不認識（只能是 source/tool/toolset）")
            continue
        for f in REQUIRED[kind]:
            if not d.get(f):
                problems.append(f"x {kind} 缺少必要欄位 {f}")
        key = (kind, d.get("name"))
        if key in names:
            problems.append(f"x {kind} 名稱重複：{d.get('name')}")
        names[key] = d

    for (kind, name), d in names.items():
        if kind == "tool":
            if ("source", d.get("source")) not in names:
                problems.append(f"x tool {name} 指向不存在的 source：{d.get('source')}")
            params = d.get("parameters") or []
            used = {int(n) for n in re.findall(r"\$(\d+)", d.get("statement") or "")}
            want = set(range(1, len(params) + 1))
            if used != want:
                problems.append(
                    f"x tool {name} 的 $N 與 parameters 對不上："
                    f"statement 用了 {sorted(used) or '無'}，parameters 有 {len(params)} 個 → 應該是 {sorted(want) or '無'}")
            for p in params:
                if not isinstance(p, dict) or not p.get("description"):
                    problems.append(f"! tool {name} 的參數缺 description —— 模型看不到說明會亂填")
        if kind == "toolset":
            for t in d.get("tools") or []:
                if ("tool", t) not in names:
                    problems.append(f"x toolset {name} 列了不存在的 tool：{t}")

    for var in {m for d in names.values() for m in re.findall(r"\$\{(\w+)\}", yaml.safe_dump(d))}:
        if not os.environ.get(var):
            problems.append(f"! 環境變數 {var} 目前是空的 —— Toolbox 會拿空字串去連 DB")
    return problems


# ── 啊哈 demo：模型能碰的到底是什麼 ──────────────────────────────────
INJECT = "Tokyo'; drop table hotels; --"


def _w(s):
    """中文是全寬字，算 2 格表格才不會歪。"""
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in s)


def _pad(s, n):
    return s + " " * max(0, n - _w(s))


def aha(docs):
    """把 tools.yaml 攤成「模型看得到的」與「Postgres 收到的」兩面，再打一發 injection。

    離線推演 tools.yaml 的參數化語義（$N＝bind parameter），不是攔截真的 Toolbox 封包。
    """
    C, D, G, R, Z = (("\033[36m", "\033[2m", "\033[32m", "\033[31m", "\033[0m")
                     if sys.stdout.isatty() else ("",) * 5)
    tools = [d for d in docs if isinstance(d, dict) and d.get("kind") == "tool"]

    print(f"\n{C}[1] 模型看得到的工具面{Z}")
    for t in tools:
        ps = t.get("parameters") or []
        sig = ", ".join(f'{p["name"]}: {p["type"]}' for p in ps)
        print(f'    {t["name"]}({sig})')
    n_params = sum(len(t.get("parameters") or []) for t in tools)
    print(f"    {D}→ 模型可填 {n_params} 個參數；可改的 SQL 文字 0 字{Z}")

    victim = next(t for t in tools if (t.get("parameters") or []))
    stmt = " ".join((victim["statement"] or "").split())
    print(f"\n{C}[2] Postgres 收到的 SQL（固定，寫在 yaml 裡）{Z}\n    {stmt}")

    print(f'\n{C}[3] 打一發 injection：city = {INJECT}{Z}')
    naive = stmt.replace("$1", f"'{INJECT}'").replace("$2", "3000")   # 有人真的這樣拼字串
    safe_args = {"$1": INJECT, "$2": 3000}
    print(f"    {R}拼字串版{Z} {naive}")
    print(f"    {G}Toolbox 版{Z} {stmt}")
    print(f"    {D}           參數 {safe_args}{Z}")

    rows = [("SQL 語句數", str(naive.count(";") - naive.count("; --")), "1"),
            ("模型可控的 SQL 字元數", str(len(INJECT)), "0"),
            ("DROP TABLE 進得去嗎", "進得去", "不行（只是一個城市名字）"),
            ("查詢結果", "hotels 表沒了", "0 列（沒有這個城市）")]
    k = max(_w(r[0]) for r in rows) + 2
    print(f"\n{_pad('指標', k)}{_pad('拼字串（自己寫 SQL）', 26)}Toolbox（$N bind）")
    print(D + "─" * (k + 50) + Z)
    for name, a, b in rows:
        print(f"{_pad(name, k)}{_pad(a, 26)}{b}")
    print(f"\n{D}對照組：Supabase MCP 的 execute_sql 是 1 個工具、1 個參數 —— "
          f"那個參數就是整句 SQL，可控字元數無上限。{Z}")


def self_check():
    good = """
kind: source
name: db
type: postgres
---
kind: tool
name: t1
type: postgres-sql
source: db
statement: SELECT 1 FROM hotels WHERE city = $1
parameters:
  - {name: city, type: string, description: 城市}
---
kind: toolset
name: ts
tools: [t1]
"""
    os.environ.setdefault("DB_PASSWORD", "x")
    assert [p for p in check(list(yaml.safe_load_all(good))) if p.startswith("x")] == []

    def errs(text):
        return [p for p in check(list(yaml.safe_load_all(text))) if p.startswith("x")]

    # $2 卻只有一個參數 —— 最常見也最難看出來的錯
    assert any("$N" in e for e in errs(good.replace("city = $1", "city = $2")))
    # 參數多一個、statement 沒用到
    assert any("$N" in e for e in errs(good.replace("- {name: city, type: string, description: 城市}",
                                                   "- {name: city, type: string, description: 城市}\n"
                                                   "  - {name: mx, type: integer, description: 上限}")))
    assert any("不存在的 source" in e for e in errs(good.replace("source: db", "source: nope")))
    assert any("不存在的 tool" in e for e in errs(good.replace("tools: [t1]", "tools: [t9]")))
    assert any("kind" in e for e in errs(good.replace("kind: toolset", "kind: toolsets")))
    assert any("缺少必要欄位" in e for e in errs(good.replace("statement: SELECT 1 FROM hotels WHERE city = $1", "")))
    # 提醒類：參數沒 description
    warns = check(list(yaml.safe_load_all(good.replace(", description: 城市", ""))))
    assert any(w.startswith("! ") and "description" in w for w in warns), warns
    print("self-check ok")


def main():
    if "--self-check" in sys.argv:
        return self_check()
    path = next((a for a in sys.argv[1:] if not a.startswith("-")), "tools.yaml")
    with open(path, encoding="utf-8") as f:
        docs = [d for d in yaml.safe_load_all(f) if d is not None]
    if "--aha" in sys.argv:
        return aha(docs)
    problems = check(docs)
    kinds = sorted({d.get("kind") for d in docs if isinstance(d, dict)})
    print(f"{path}：{len(docs)} 份文件（{', '.join(str(k) for k in kinds)}）")
    for p in problems:
        print(("\033[31m" if p.startswith("x") else "\033[33m") * sys.stdout.isatty() + p
              + "\033[0m" * sys.stdout.isatty())
    fatal = [p for p in problems if p.startswith("x")]
    print("OK：可以啟動 Toolbox 了" if not fatal else f"有 {len(fatal)} 個錯要先修")
    sys.exit(1 if fatal else 0)


if __name__ == "__main__":
    main()
