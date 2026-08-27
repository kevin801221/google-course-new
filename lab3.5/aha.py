"""Lab 3.5 啊哈 demo：把「記憶」拆開來看 —— 它就是幾個檔案 open() 之後串起來的字串。

不連網、不用任何 key，離線就能跑：

    uv run aha.py --show               # 掀開蓋子：AGENTS.md 的 @import 展開成什麼
    uv run aha.py --show GEMINI.md     # 從兩行轉接檔出發，看它一樣通到同一份全文
    uv run aha.py --cost               # 有數字的對照：接線前後每一輪要付多少 context
    uv run aha.py --self-check
"""

import re
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).parent
IMPORT = re.compile(r"^@(\S+)$")          # Memory Import Processor 認的就是這種行
TTY = sys.stdout.isatty()


def c(s: str, code: str) -> str:
    """非 tty（管線、CI）自動退成純文字。"""
    return f"\033[{code}m{s}\033[0m" if TTY else s


def w(s: str) -> int:
    """中文在終端機是全寬，算 2 格。"""
    return sum(2 if unicodedata.east_asian_width(ch) in "FW" else 1 for ch in s)


def pad(s: str, n: int) -> str:
    return s + " " * max(0, n - w(s))


def resolve(path: Path, seen: set | None = None, depth: int = 0) -> tuple[str, list]:
    """展開 @import，回傳（串接後全文, [(相對路徑, 原始字元數, 層級)]）。

    整個「記憶系統」的核心就是這 17 行：讀檔、看到 @ 就遞迴、把結果 join 起來。
    也因為它只是 join，所以文件才會寫「只保證串接，不保證覆蓋」——
    根本沒有覆蓋這個概念，後面的檔案不會蓋掉前面的，只會再多送一份。
    """
    seen = set() if seen is None else seen
    p = path.resolve()
    if p in seen or not p.is_file():
        return "", []                      # 循環 import 只吃第一次，缺檔安靜跳過
    seen.add(p)
    text = p.read_text(encoding="utf-8")
    tree = [(str(p.relative_to(ROOT.resolve())), len(text), depth)]
    out = []
    for line in text.splitlines(keepends=True):
        m = IMPORT.match(line.strip())
        if m:
            sub, subtree = resolve(p.parent / m.group(1), seen, depth + 1)
            out.append(sub)
            tree += subtree
        else:
            out.append(line)
    return "".join(out), tree


def est_tokens(text: str) -> int:
    """粗估：CJK 一字約 1 token，其餘約 4 字元 1 token。只用來比大小，不是帳單。"""
    cjk = sum(1 for ch in text if unicodedata.east_asian_width(ch) in "FW")
    return int(cjk + (len(text) - cjk) / 4)


def show(entry: str) -> None:
    full, tree = resolve(ROOT / entry)
    print(c(f"從 {entry} 出發，實際被載進每一次提問的檔案：", "1"))
    for rel, n, d in tree:
        print(f"  {'  ' * d}{'└─ ' if d else ''}{pad(rel, 40 - 2 * d)} {n:>6,} 字元")
    print(f"\n串接後全文：{c(f'{len(full):,} 字元', '1;36')}"
          f"　粗估 {est_tokens(full):,} tokens　（{len(tree)} 個檔）")
    print(c("\n這就是 /memory show 會給你看的東西。前 12 行：", "2"))
    for line in full.splitlines()[:12]:
        print("  │ " + line)
    print("  │ …")


def cost() -> None:
    full, tree = resolve(ROOT / "AGENTS.md")
    main = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    dec = (ROOT / "memory" / "decisions.md").read_text(encoding="utf-8")
    n_dec = dec.count("\n## D-")
    per_dec = len(dec) // max(n_dec, 1)          # 決策層總長度 ÷ 條數（含標頭，粗略單價）

    rows = [
        ("沒接線（預設只讀 GEMINI.md，而它還沒建）", 0, 0),
        ("只讀 AGENTS.md 主檔（不展開 @import）", 1, len(main)),
        ("接線後（@import 全部展開）", len(tree), len(full)),
        (f"decisions.md 再長 10 條（每條平均 {per_dec} 字元）", len(tree), len(full) + per_dec * 10),
    ]
    head = ("情境", "檔數", "字元", "粗估 tokens", "20 輪累計 tokens")
    widths = (44, 6, 9, 13, 16)
    print(c("每一輪提問都要重付一次的 context 成本", "1"))
    print(c("  ".join(pad(h, x) for h, x in zip(head, widths)), "1;4"))
    base = None
    for name, nf, nc in rows:
        t = int(nc * est_tokens(full) / max(len(full), 1))   # 同一份材料，等比例換算
        base = base if base is not None else t
        cells = (name, str(nf), f"{nc:,}", f"{t:,}", f"{t * 20:,}")
        print("  ".join(pad(v, x) for v, x in zip(cells, widths)))
    exp = len(full) / max(len(main), 1)
    print(f"\n主檔 {len(main):,} 字元 → 展開後 {c(f'{len(full):,} 字元', '1;36')}"
          f"（{c(f'×{exp:.1f}', '1;33')}），而且是{c('每問一句就整份重送一次', '1;33')}。")
    print(f"decisions.md 每新增一條，之後每一輪都多付約 {per_dec} 字元 —— "
          f"這就是投影片 p.160「定期封存，不要 @import 已結案的」的實際單價。")


def _self_check() -> None:
    full, tree = resolve(ROOT / "AGENTS.md")
    assert "@./memory/decisions.md" not in full, "@import 沒有被展開"
    assert "D-007" in full, "decisions.md 的內容沒有被串進來"
    assert len(tree) == 5, f"預期 5 個檔（主檔＋4 個 @import），實際 {len(tree)}"
    g, gtree = resolve(ROOT / "GEMINI.md")
    assert "D-007" in g, "從 GEMINI.md 出發應該經 @./AGENTS.md 抓到同一份全文"
    assert len(gtree) == 6, f"GEMINI.md 應多一層轉接檔，實際 {len(gtree)}"
    # 循環 import：A→B→A 只能吃一次，否則無窮遞迴
    assert len(resolve(ROOT / "AGENTS.md", seen={(ROOT / "AGENTS.md").resolve()})[1]) == 0
    assert w("臺南市") == 6 and w("abc") == 3, "全寬字寬度算錯，表格會歪"
    print("aha self-check ok")


def main() -> None:
    arg = sys.argv[1] if len(sys.argv) > 1 else "--show"
    if arg == "--self-check":
        return _self_check()
    if arg == "--cost":
        return cost()
    return show(sys.argv[2] if len(sys.argv) > 2 else "AGENTS.md")


if __name__ == "__main__":
    main()
