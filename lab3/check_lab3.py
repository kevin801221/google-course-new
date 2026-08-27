# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Lab 3 驗收腳本：檢查 rules / mcp_config / browser 證據 / git 推送是否齊全。

跑法：
  uv run check_lab3.py <專案路徑>      # 例：uv run check_lab3.py ~/projects/lab2-app
  uv run check_lab3.py                # 不給路徑就檢查目前目錄
  uv run check_lab3.py --self-check    # 不碰檔案、不連網、不花錢，用假設定驗檢查邏輯
  uv run check_lab3.py --aha [路徑]    # 對照表：同一句需求，有／沒有 repo 規範差多少（離線）
全部 PASS → exit 0；任何 FAIL → exit 1。步驟 2 跑會有 FAIL 是正常的，步驟 7 才要全綠。
"""
import glob, json, os, re, subprocess, sys, unicodedata

RULES_MAX = 12000                                    # 投影片 p.104：rule 單檔上限 12,000 字元
MODES = ("Always On", "Manual", "Model Decision", "Glob")
HARD = re.compile(r"必須|禁止|一律|不得")             # 硬性字眼，agent 才知道哪條不能妥協
# ponytail: 明文 token 只認常見前綴，要更嚴就改成「headers/env 的值必須以 $ 開頭」白名單制
SECRET = re.compile(r"(ghp_|github_pat_|glpat-|sk-|AIza)[A-Za-z0-9_-]{12,}")
EVIDENCE_EXT = (".webm", ".png", ".jpg", ".gif", ".mp4")


def check_rule_text(name, text):
    """純函式：驗一份 rule 檔的內容。回傳 [(ok, 訊息)]。"""
    n = len(text)
    hits = len(HARD.findall(text))
    return [
        (n <= RULES_MAX, f"{name}：{n} 字元（上限 {RULES_MAX}）"),
        (any(m in text for m in MODES), f"{name}：有標註啟用模式（{' / '.join(MODES)} 之一）"),
        (hits >= 3, f"{name}：{hits} 條「必須／禁止／一律／不得」（至少 3 條）"),
        ("盡量" not in text, f"{name}：沒有模糊字眼「盡量」"),
    ]


def check_mcp(cfg):
    """純函式：驗 mcp_config.json 的結構。回傳 [(ok, 訊息)]。"""
    servers = cfg.get("mcpServers")
    if not isinstance(servers, dict) or not servers:
        return [(False, "mcp_config.json：頂層要有非空的 mcpServers 物件")]
    out = [(True, f"mcp_config.json：{len(servers)} 個 server（{', '.join(servers)}）")]
    for name, s in servers.items():
        if not isinstance(s, dict):
            out.append((False, f"{name}：設定必須是物件"))
            continue
        if "url" in s and "serverUrl" not in s:
            out.append((False, f"{name}：欄位寫成 url —— Antigravity 只認 serverUrl（抄 Cursor 設定檔必踩）"))
        elif s.get("command"):
            out.append((True, f"{name}：stdio 型（command={s['command']}）"))
        elif s.get("serverUrl"):
            out.append((True, f"{name}：遠端型（serverUrl）"))
        else:
            out.append((False, f"{name}：stdio 要 command+args、遠端要 serverUrl，兩個都沒有"))
        for bag in ("headers", "env"):
            for k, v in (s.get(bag) or {}).items():
                if isinstance(v, str) and SECRET.search(v):
                    out.append((False, f"{name}.{bag}.{k}：疑似明文 token，改成 $ENV_VAR 引用"))
    return out


def git(root, *args):
    """跑 git，失敗回 None。"""
    try:
        p = subprocess.run(("git", "-C", root) + args, capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return None
    return p.stdout.strip() if p.returncode == 0 else None


def check_project(root):
    """掃一個專案目錄，回傳 [(ok, 訊息)]。"""
    # ponytail: 只看根目錄的 AGENTS.md，巢狀目錄的版本不掃；要掃就換 os.walk
    out = [(os.path.isfile(os.path.join(root, "AGENTS.md")), "AGENTS.md 存在於專案根目錄")]

    rules_dir = os.path.join(root, ".agents", "rules")
    mds = sorted(f for f in os.listdir(rules_dir) if f.endswith(".md")) if os.path.isdir(rules_dir) else []
    out.append((bool(mds), f".agents/rules/ 有 rule 檔：{', '.join(mds) or '（沒有）'}"))
    for f in mds:
        with open(os.path.join(rules_dir, f), encoding="utf-8") as fh:
            out += check_rule_text(f, fh.read())

    cfg_path = os.path.join(root, ".agents", "mcp_config.json")
    if not os.path.isfile(cfg_path):
        out.append((False, ".agents/mcp_config.json 存在"))
    else:
        try:
            with open(cfg_path, encoding="utf-8") as fh:
                out += check_mcp(json.load(fh))
        except json.JSONDecodeError as e:
            # JSON 不吃註解也不吃尾逗號，這裡把行號直接吐出來
            out.append((False, f"mcp_config.json 不是合法 JSON：{e}"))

    # ponytail: 證據只驗「檔案存在」，要驗時長得裝 ffprobe，超出 stdlib 範圍
    ev_dir = os.path.join(root, "docs", "evidence")
    ev = [f for f in os.listdir(ev_dir) if f.lower().endswith(EVIDENCE_EXT)] if os.path.isdir(ev_dir) else []
    out.append((bool(ev), f"docs/evidence/ 有 browser 驗證證據：{', '.join(sorted(ev)) or '（沒有）'}"))

    log = git(root, "log", "--oneline")
    n = len(log.splitlines()) if log else 0
    out.append((n >= 2, f"git 有 {n} 個 commit（至少 2）"))
    remote = git(root, "remote", "get-url", "origin")
    out.append((bool(remote), f"git remote origin：{remote or '（沒設）'}"))
    return out


# ── --aha：同一句需求，agent 讀到的東西差多少 ──────────────────────────
# 步驟 2a 那句沒有規則的任務（原文照抄 walkthrough）
AHA_PROMPT = "在 src/utils/ 新增一支 formatTime 函式，把 ISO 時間字串轉成「幾分鐘前」。"
BANNED = ("`any`", "@ts-ignore", "as unknown as")     # style.md 明文禁掉的寫法


def width(s):
    """中文是全寬字，算 2 格才不會排歪。"""
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in s)


def pad(s, n):
    return s + " " * max(0, n - width(s))


def aha_rows(prompt, repo_text):
    """純函式：把「只有 prompt」與「prompt＋repo 規範」壓成可比較的數字。"""
    both = prompt + "\n" + repo_text
    done = [c for c in ("npm run lint", "npx tsc --noEmit") if c in both]
    return [
        ("agent 讀到的字元", str(len(prompt)), str(len(both)), len(prompt), len(both)),
        ("硬性約束（必須／禁止／一律／不得）",
         str(len(HARD.findall(prompt))), str(len(HARD.findall(both))),
         len(HARD.findall(prompt)), len(HARD.findall(both))),
        ("明文禁用的寫法",
         str(sum(b in prompt for b in BANNED)), str(sum(b in both for b in BANNED)),
         sum(b in prompt for b in BANNED), sum(b in both for b in BANNED)),
        ("「完成」的定義", "沒寫", " ＋ ".join(done) or "沒寫", None, None),
        ("每次任務自動掛上", "否（要你重打）",
         "是（Always On）" if "Always On" in repo_text else "否（沒標啟用模式）", None, None),
    ]


def aha(root):
    """印對照表。root 預設是教材的 templates/，所以不用先有專案也跑得動。"""
    files = [os.path.join(root, "AGENTS.md")] + sorted(glob.glob(os.path.join(root, ".agents", "rules", "*.md")))
    texts = []
    for f in files:
        if os.path.isfile(f):
            with open(f, encoding="utf-8") as fh:
                texts.append(fh.read())
    if not texts:
        sys.exit(f"{root} 底下找不到 AGENTS.md 或 .agents/rules/*.md —— 先做完步驟 2b 再跑 --aha")
    rows = aha_rows(AHA_PROMPT, "\n".join(texts))
    color = sys.stdout.isatty()
    b, d, z = ("\033[1m", "\033[2m", "\033[0m") if color else ("", "", "")
    print(f"{b}同一句需求，agent 實際讀到的東西{z}")
    print(f'{d}需求：「{AHA_PROMPT}」{z}')
    print(f"{d}右欄多出來的：{', '.join(os.path.relpath(f, root) for f in files)}{z}\n")
    kw = max(width(r[0]) for r in rows) + 2
    print(f"{b}{pad('指標', kw)}{pad('只有 prompt', 18)}{pad('prompt ＋ repo 規範', 34)}倍數{z}")
    print(d + "─" * (kw + 56) + z)
    for name, l, r, ln, rn in rows:
        ratio = "" if ln is None else (f"{rn / ln:.0f}×" if ln else f"0 → {rn}")
        print(f"{pad(name, kw)}{pad(l, 18)}{pad(r, 34)}{ratio}")
    print(f"\n{d}你打的字一個都沒變。變的是 repo 裡有什麼。{z}")


def self_check():
    ok = lambda rs: all(o for o, _ in rs)
    bad = lambda rs, kw: any(not o and kw in m for o, m in rs)

    good_rule = "<!-- 啟用模式：Always On -->\n必須跑 lint。禁止用 any。一律繁體中文註解。"
    assert ok(check_rule_text("style.md", good_rule))
    assert bad(check_rule_text("x.md", "沒有模式標註，必須跑 lint、禁止 any、一律中文"), "啟用模式")
    assert bad(check_rule_text("x.md", good_rule + "盡量寫測試"), "盡量")
    assert bad(check_rule_text("x.md", "Always On\n必須 A"), "必須")
    assert bad(check_rule_text("x.md", "Always On 必須 禁止 一律" + "字" * RULES_MAX), "上限")

    assert ok(check_mcp({"mcpServers": {"github": {"command": "npx", "args": ["-y", "x"]}}}))
    assert ok(check_mcp({"mcpServers": {"bq": {"serverUrl": "https://x/mcp", "authProviderType": "google_credentials"}}}))
    assert bad(check_mcp({"mcpServers": {"github": {"url": "https://x/mcp"}}}), "serverUrl")
    assert bad(check_mcp({"mcpServers": {"github": {"args": ["-y"]}}}), "兩個都沒有")
    assert bad(check_mcp({"mcpServers": {"g": {"command": "npx", "env": {"T": "ghp_abcdefghij1234567890"}}}}), "明文 token")
    assert ok(check_mcp({"mcpServers": {"g": {"command": "npx", "env": {"T": "$GITHUB_PAT"}}}}))
    assert bad(check_mcp({}), "mcpServers")

    rows = aha_rows("加個功能。", "<!-- 啟用模式：Always On -->\n必須跑 npm run lint 與 npx tsc --noEmit，禁止 `any`。")
    assert rows[0][3] < rows[0][4] and rows[1][3] == 0 and rows[1][4] == 2      # 字元變多、硬約束 0 → 2
    assert rows[2][4] == 1 and rows[3][2].startswith("npm run lint")            # 禁用寫法、完成定義被抓到
    assert aha_rows("x", "沒有標啟用模式")[4][2].startswith("否")
    print("self-check 通過：rule 檢查 5 項、mcp 檢查 7 項、aha 對照 4 項")


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if "--self-check" in sys.argv[1:]:
        return self_check()
    if "--aha" in sys.argv[1:]:
        # 不給路徑就用教材自己的 templates/，學生還沒 cp 到專案也能先看
        return aha(os.path.abspath(args[0]) if args else
                   os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates"))
    root = os.path.abspath(args[0] if args else ".")
    color = sys.stdout.isatty()
    g, r, z = ("\033[32m", "\033[31m", "\033[0m") if color else ("", "", "")
    print(f"檢查專案：{root}\n")
    results = check_project(root)
    for o, m in results:
        print(f"{g}PASS{z}  {m}" if o else f"{r}FAIL{z}  {m}")
    fails = sum(1 for o, _ in results if not o)
    print(f"\n{len(results) - fails} 過 / {fails} 失敗")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
