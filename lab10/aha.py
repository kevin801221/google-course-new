"""Lab 10 的兩張對照表：部署產物不是你的開發環境；冷啟動有標價。

跑法（都在 lab10/ 執行）：
  uv run aha.py                # 兩張表都印
  uv run aha.py --deps         # 只印「本機的 ADK vs 容器裡的 ADK」
  uv run aha.py --cost         # 只印「scale-to-zero vs --min-instances 1」
  uv run aha.py --self-check   # 不連網、不花錢，用 assert 驗算術與解析

資料全部離線可查：google-adk 的套件 metadata、google/adk/cli/cli_deploy.py 的
_DOCKERFILE_TEMPLATE、本目錄的 pyproject.toml / uv.lock、投影片 p.408 的價目表。
"""

import re
import sys
import tomllib
import unicodedata
from pathlib import Path

HERE = Path(__file__).resolve().parent

DIM, BOLD, CYAN, GREEN, YELLOW, RESET = (
    ("\033[2m", "\033[1m", "\033[36m", "\033[32m", "\033[33m", "\033[0m")
    if sys.stdout.isatty() else ("",) * 6
)


# ── 對齊：中文是全寬字，算 2 格才不會排歪 ──────────────────────────────
def width(s):
    s = re.sub(r"\033\[[0-9;]*m", "", s)
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in s)


def pad(s, n):
    return s + " " * max(0, n - width(s))


def table(rows, headers):
    """rows = [(欄1, 欄2, 欄3), ...]；最後一欄不補空白。"""
    cols = list(zip(*([headers] + rows)))
    w = [max(width(c) for c in col) + 2 for col in cols]
    print(f"\n{BOLD}" + "".join(pad(h, x) for h, x in zip(headers, w)).rstrip() + RESET)
    print(DIM + "─" * (sum(w) - 2) + RESET)
    for r in rows:
        print("".join(pad(c, x) for c, x in zip(r, w)).rstrip())


# ── 表一：本機的 ADK vs 容器裡的 ADK ──────────────────────────────────
def extras_of(spec):
    """從 'google-adk[a2a,mcp]>=2.7' 撈出 {'a2a','mcp'}。"""
    m = re.search(r"google-adk\[([^\]]*)\]", spec)
    return {e.strip() for e in m.group(1).split(",")} if m else set()


def extra_packages(extras):
    """這些 extra 帶進來的直接依賴套件名（不含版本）。"""
    import importlib.metadata as md

    out = set()
    for req in md.metadata("google-adk").get_all("Requires-Dist") or []:
        for e in extras:
            if 'extra == "%s"' % e in req:
                out.add(re.split(r"[\[<>=!;\s]", req.strip(), maxsplit=1)[0])
    return out


def deps():
    import importlib.metadata as md

    from google.adk.cli import cli_deploy

    tpl = cli_deploy._DOCKERFILE_TEMPLATE
    pyproject = tomllib.loads((HERE / "pyproject.toml").read_text())
    declared_specs = pyproject["project"]["dependencies"]

    mine = extras_of(" ".join(declared_specs))
    theirs = extras_of(tpl)                      # Dockerfile 裡那行 pip install
    missing = extra_packages(mine) - extra_packages(theirs)
    # asyncpg 不是 extra，是 pyproject 直接列的 —— 容器同樣拿不到
    missing |= {s.split(">")[0] for s in declared_specs if not s.startswith("google-adk")}
    locked = len(tomllib.loads((HERE / "uv.lock").read_text())["package"])

    dev_server = next(Path(md.distribution("google-adk").locate_file(
        "google/adk/cli")).glob("dev_server.py"), None)
    dev_lines = len(dev_server.read_text().splitlines()) if dev_server else 0
    killed = "RUN python -c" in tpl and "dev_server" in tpl
    enterprise = re.search(r"ENV GOOGLE_GENAI_USE_ENTERPRISE=(\S+)", tpl)

    print(f"{BOLD}表一：本機的 ADK vs 容器裡的 ADK{RESET} "
          f"{DIM}（google-adk {md.version('google-adk')} 的 _DOCKERFILE_TEMPLATE）{RESET}")
    table([
        ("google-adk extras",
         "%d 個：%s" % (len(mine), ",".join(sorted(mine))),
         f"{YELLOW}%d 個：%s{RESET}" % (len(theirs), ",".join(sorted(theirs)))),
        ("容器少掉的直接依賴", "—", f"{YELLOW}%d 個{RESET}" % len(missing)),
        ("  其中 agent.py 用得到", "—",
         " ".join(sorted(missing & {"mcp", "toolbox-adk", "sqlalchemy", "asyncpg"}))),
        ("補回來的方式", "uv sync（讀 uv.lock）",
         "pip install -r requirements.txt（%d 個鎖定套件）" % (locked - 1)),
        ("dev_server.py（/dev/* 端點）", "%d 行，在 .venv 裡" % dev_lines,
         f"{YELLOW}被 RUN python -c … os.remove 刪掉{RESET}" if killed else "在"),
        ("模型憑證來源", "GEMINI_API_KEY（AI Studio）",
         f"{YELLOW}ENV GOOGLE_GENAI_USE_ENTERPRISE={enterprise.group(1)}{RESET}"
         " → service account" if enterprise else "?"),
    ], ("項目", "本機 uv run adk web", "容器 adk deploy cloud_run"))
    print(f"\n{DIM}結論：容器裡跑的不是你本機那套 —— 少 %d 個依賴、少一支 %d 行的 dev_server、"
          f"換一種憑證來源。部署的 bug 幾乎都長在這三行差異裡。{RESET}"
          % (len(missing), dev_lines))


# ── 表二：scale-to-zero vs --min-instances 1 ──────────────────────────
# 投影片 p.408（us-central1）：免費 18 萬 vCPU-秒 / 36 萬 GiB-秒 / 200 萬請求
FREE_VCPU_S, FREE_GIB_S, FREE_REQ = 180_000, 360_000, 2_000_000
P_VCPU_S, P_GIB_S, P_REQ = 0.000024, 0.0000025, 0.40 / 1_000_000


def monthly(vcpu_s, gib_s, requests):
    """一個月的 Cloud Run 帳單（只算投影片給的三項）。"""
    return {
        "計費 vCPU-秒": vcpu_s,
        "計費 GiB-秒": gib_s,
        "請求數": requests,
        "超免費層 vCPU 費": max(0, vcpu_s - FREE_VCPU_S) * P_VCPU_S,
        "超免費層 RAM 費": max(0, gib_s - FREE_GIB_S) * P_GIB_S,
        "請求費": max(0, requests - FREE_REQ) * P_REQ,
    }


def total(m):
    return m["超免費層 vCPU 費"] + m["超免費層 RAM 費"] + m["請求費"]


def cost(services=4, vcpu=1.0, gib=0.5, days=30):
    idle = monthly(vcpu_s=1_500, gib_s=750, requests=500)          # 一次 Lab 的量級
    secs = services * days * 24 * 3600
    warm = monthly(vcpu_s=int(secs * vcpu), gib_s=int(secs * gib), requests=500)

    def fmt(k, m):
        v = m[k]
        return f"${v:,.2f}" if k.endswith("費") else f"{v:,}"

    rows = [(k, fmt(k, idle), fmt(k, warm)) for k in idle]
    rows.append((f"{BOLD}月費合計{RESET}",
                 f"{GREEN}${total(idle):,.2f}{RESET}",
                 f"{YELLOW}${total(warm):,.2f}{RESET}"))
    print(f"\n{BOLD}表二：冷啟動的標價{RESET} "
          f"{DIM}（{services} 個服務 × {vcpu} vCPU / {gib} GiB，{days} 天；左欄是一次 Lab 量級的估計用量）{RESET}")
    table(rows, ("項目", "現在（scale-to-zero）", "--min-instances 1"))
    print(f"\n{DIM}第一個請求等 10-20 秒，換來的是閒置時 ${total(idle):,.2f}。"
          f"要消掉那 10 秒，價目表上寫著 ${total(warm):,.2f}／月。{RESET}")
    print(f"{DIM}⚠️ 這是照投影片 p.408 價目算的上限：Cloud Run 對 min-instance 的"
          f"閒置 CPU 另有一組較低價，投影片沒給，我不編數字。{RESET}")


# ── 離線自我檢查：只驗算術與解析，不 import ADK ────────────────────────
def self_check():
    assert width("本機") == 4 and width("abc") == 3
    assert width(f"{GREEN}中{RESET}") == 2, "ANSI 不能算進寬度"
    assert pad("項目", 8) == "項目" + " " * 4

    assert extras_of('"google-adk[a2a,mcp,toolbox]>=2.7,<3"') == {"a2a", "mcp", "toolbox"}
    assert extras_of('RUN pip install "google-adk[a2a]=={v}"') == {"a2a"}
    assert extras_of("google-adk>=2.7") == set()

    free = monthly(vcpu_s=1_500, gib_s=750, requests=500)
    assert total(free) == 0, "課程用量必須全在免費層，不然這個 Lab 的 $0-5 是假的"

    secs = 4 * 30 * 24 * 3600
    warm = monthly(vcpu_s=secs, gib_s=secs // 2, requests=500)
    assert warm["計費 vCPU-秒"] == 10_368_000
    assert abs(warm["超免費層 vCPU 費"] - 244.512) < 1e-6
    assert abs(warm["超免費層 RAM 費"] - 12.06) < 1e-6
    assert warm["請求費"] == 0                      # 500 次遠低於 200 萬
    assert 256 < total(warm) < 257, total(warm)

    # 邊界：剛好用完免費層不該計費
    assert total(monthly(FREE_VCPU_S, FREE_GIB_S, FREE_REQ)) == 0
    print(f"{GREEN}self-check ok{RESET}")


if __name__ == "__main__":
    args = sys.argv[1:]
    if "--self-check" in args:
        self_check()
    elif not args or {"--deps", "--cost"} & set(args):
        if not args or "--deps" in args:
            deps()
        if not args or "--cost" in args:
            cost()
    else:
        sys.exit(f"不認識的旗標 {args}。可用：--deps / --cost / --self-check（不給旗標＝全部）")
