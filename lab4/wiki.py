"""Lab 4 課程知識庫小工具：檢查 MCP 設定 + 用 nlm 查 NotebookLM。

跑法（全部 uv，不要用 python）：
  uv run wiki.py --self-check          # 離線驗邏輯：不連網、不打 API、不花錢
  uv run wiki.py check                 # 檢查 ~/.gemini/config/mcp_config.json
  uv run wiki.py check mcp_config.json # 檢查指定檔案（本目錄的範本）
  uv run wiki.py notebooks             # = nlm notebook list（要先 nlm login）
  uv run wiki.py sources               # 盤點來源、抓還沒 embed 完的
  uv run wiki.py ask "ADK 部署的三種方式？"   # 查知識庫，沒引用就 exit 1
  uv run wiki.py aha                   # 離線：grounding 三種形態並排比（Lab 1/4/8）

筆記本 ID：環境變數 NLM_NOTEBOOK_ID，或每個子指令後面加 --nb <id>。
"""

import json
import os
import re
import shutil
import subprocess
import sys
import unicodedata
from pathlib import Path

DEFAULT_CONFIG = Path.home() / ".gemini" / "config" / "mcp_config.json"
MUST_DISABLE = {"notebook_delete", "source_delete"}  # 投影片 p.188：先禁破壞性工具


# ---------- 純函式（--self-check 驗的就是這幾隻） ----------

def strip_jsonc(text):
    """把 // 與 /* */ 註解、尾逗號拿掉，讓投影片上那份帶註解的 config 也 parse 得動。

    # ponytail: 一次掃描的小狀態機；尾逗號那條 regex 是最後對整份字串跑，
    #           所以字串值裡真的寫 ", }" 也會被清掉（config 檔不會這樣寫）。
    #           真的要嚴謹就 uv add json5。
    """
    out, i, n, in_str = [], 0, len(text), False
    while i < n:
        c = text[i]
        if in_str:
            out.append(c)
            if c == "\\" and i + 1 < n:      # 跳過轉義字元，否則 \" 會被當成結尾
                out.append(text[i + 1])
                i += 2
                continue
            if c == '"':
                in_str = False
            i += 1
        elif c == '"':
            in_str = True
            out.append(c)
            i += 1
        elif text.startswith("//", i):
            while i < n and text[i] != "\n":
                i += 1
        elif text.startswith("/*", i):
            end = text.find("*/", i + 2)
            i = n if end < 0 else end + 2
        else:
            out.append(c)
            i += 1
    return re.sub(r",(\s*[}\]])", r"\1", "".join(out))


def check_config(text, which=shutil.which):
    """回傳 [(level, 訊息)]；level 是 ERROR / WARN / OK。which 可注入，方便離線測。"""
    try:
        cfg = json.loads(strip_jsonc(text))
    except json.JSONDecodeError as e:
        return [("ERROR", f"JSON 解不開：{e}")]

    servers = cfg.get("mcpServers")
    if not isinstance(servers, dict) or not servers:
        return [("ERROR", "沒有 mcpServers 物件（或是空的）")]

    out = []
    nb_names = []
    for name, s in servers.items():
        if not isinstance(s, dict):
            out.append(("ERROR", f"{name}: 值不是物件"))
            continue
        if "url" in s and "serverUrl" not in s:  # 附錄 D 易錯坑 ④
            out.append(("ERROR", f"{name}: 遠端欄位要叫 serverUrl，不是 url（抄 Cursor 設定必踩）"))
        if "command" not in s and "serverUrl" not in s:
            out.append(("ERROR", f"{name}: 既沒有 command（stdio）也沒有 serverUrl（遠端）"))
        cmd = s.get("command", "")
        # server 名字也算：nlm setup add gemini 寫出來的 command 可能不叫 notebooklm-mcp
        blob = name + " " + cmd + " " + " ".join(str(a) for a in (s.get("args") or []))
        if "notebooklm" in blob.lower():
            nb_names.append(name)
            missing = MUST_DISABLE - set(s.get("disabledTools") or [])
            if missing:
                out.append(("WARN", f"{name}: disabledTools 少了 {sorted(missing)}，agent 誤操作就能刪你的筆記本"))
            if cmd and not which(cmd):
                out.append(("WARN", f"{name}: PATH 上找不到 `{cmd}`，Antigravity 會連不上（跑 uv tool update-shell）"))

    if not nb_names:
        out.append(("ERROR", "找不到 notebooklm 的 MCP server（command/args 裡沒有 notebooklm 字樣）"))
    else:
        out.append(("OK", f"notebooklm server：{', '.join(nb_names)}"))
    return out


CITE = re.compile(r"https?://\S+")


def citations(answer):
    """從 nlm query 的輸出撈出來源連結，去重保順序。沒有引用 = 這題沒接地。"""
    return list(dict.fromkeys(u.rstrip(".,;)]。，、；」）") for u in CITE.findall(answer or "")))


BAD_STATUS = ("processing", "pending", "queued", "failed", "error", "處理中", "失敗")


def scan_sources(text):
    """回傳 (非空行數, 還沒好的行)。用來確認來源 embed 完成，別在半熟的知識庫上問問題。

    行數不是來源數：nlm 若印表頭就會多算，所以驗收只看「未就緒 0 筆」。

    # ponytail: 靠關鍵字掃 nlm 的人類可讀輸出，nlm 改版就會失準；
    #           要穩就等上游給 --json 再改成 parse JSON。
    """
    rows = [ln for ln in (text or "").splitlines() if ln.strip()]
    return len(rows), [ln for ln in rows if any(b in ln.lower() for b in BAD_STATUS)]


def report(res, need_cite=True):
    """把 nlm 的執行結果變成 (exit code, 要印的訊息)。res 只要有 returncode/stdout/stderr。"""
    if res.returncode != 0:
        return 1, f"nlm 失敗（exit {res.returncode}）：{(res.stderr or '').strip() or '沒有 stderr'}"
    body = (res.stdout or "").strip()
    if not body:
        return 1, "nlm 沒有輸出：session 可能過期，重跑 nlm login"
    if need_cite and not citations(body):
        return 1, body + "\n\n[!] 這個回答沒有任何引用連結 —— 來源可能還沒 embed 完，或問題超出來源範圍"
    return 0, body


# ---------- 會連網的部分 ----------

def run_nlm(*args):
    nlm_cmd = shutil.which("nlm")
    if not nlm_cmd:
        local_nlm = Path.home() / ".local" / "bin" / "nlm"
        if local_nlm.exists():
            nlm_cmd = str(local_nlm)
        else:
            sys.exit("找不到 nlm：uv tool install notebooklm-mcp-cli && uv tool update-shell")
    return subprocess.run([nlm_cmd, *args], capture_output=True, text=True)


def notebook_id(argv):
    if "--nb" in argv:
        return argv[argv.index("--nb") + 1]
    nb = os.environ.get("NLM_NOTEBOOK_ID")
    if not nb:
        sys.exit("沒有筆記本 ID：export NLM_NOTEBOOK_ID=<id>（用 uv run wiki.py notebooks 查）")
    return nb


# ---------- aha：grounding 的三種形態（純離線，只讀 repo 裡的檔案） ----------

REPO = Path(__file__).resolve().parent.parent
DIM, BOLD, CYAN, RESET = (("\033[2m", "\033[1m", "\033[36m", "\033[0m")
                          if sys.stdout.isatty() else ("",) * 4)


def width(s):
    """中文在終端機是全寬字，算 2 格才不會排歪。"""
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in s)


def pad(s, n):
    return s + " " * max(0, n - width(s))


def loc(path, comment="#"):
    """數「你要維護的行數」：跳過空行與整行註解。檔案不在就回 0。"""
    p = REPO / path
    if not p.exists():
        return 0
    return sum(1 for ln in p.read_text().splitlines()
               if ln.strip() and not ln.strip().startswith(comment))


def find_line(path, needle):
    """回 (行號, 整行內容)；找不到回 (0, "")。用來證明那一行真的在檔案裡。"""
    p = REPO / path
    if not p.exists():
        return 0, ""
    for i, ln in enumerate(p.read_text().splitlines(), 1):
        if needle in ln:
            return i, ln.strip()
    return 0, ""


def grounding_table():
    """同一個『答案要有出處』，三種基礎設施 —— 行數是現場數出來的，不是我編的。"""
    ln1, src1 = find_line("lab1/ask.py", 'tools=[{"type": "google_search"}]')
    n1 = 1 if ln1 else 0
    n4 = loc("lab4/mcp_config.json", "//")
    n8 = loc("lab8/schema.sql", "--") + loc("lab8/seed_embeddings.py") + loc("lab8/tools.yaml")

    cols = ("Lab 1 google_search", "Lab 4 NotebookLM", "Lab 8 pgvector")
    rows = [
        ("來源是誰選的", "Google 的全網索引", "你：貼 4 個 URL", "你：寫進 Postgres"),
        ("切塊＋嵌入誰做", "Google", "NotebookLM", "你：seed_embeddings.py"),
        ("檢索誰做", "Google", "NotebookLM", "你的 SQL：<=> 餘弦距離"),
        ("引用從哪來", "annotations 事件", "答案裡的 [1][2]", "你 SELECT 出來的欄位"),
        ("上游改版會壞嗎", "不會：官方 API", "會：非官方 cookie", "不會：DB 是你的"),
        ("你維護的行數", str(n1), str(n4), str(n8)),
    ]
    files = ("lab1/ask.py:%d" % ln1, "lab4/mcp_config.json", "lab8/schema.sql ＋ seed_embeddings.py ＋ tools.yaml")

    k_w = max(width(r[0]) for r in rows) + 2
    c_w = max(max(width(c) for c in cols), max(width(x) for r in rows for x in r[1:])) + 2
    print(f"\n{BOLD}grounding 的三種形態：同一個「答案要有出處」，三種基礎設施{RESET}")
    print(f"\n{BOLD}{pad('', k_w)}{''.join(pad(c, c_w) for c in cols)}{RESET}")
    print(DIM + "─" * (k_w + c_w * 3) + RESET)
    for r in rows:
        print(f"{pad(r[0], k_w)}{''.join(pad(x, c_w) for x in r[1:])}")
    print(DIM + "─" * (k_w + c_w * 3) + RESET)
    print(f"{pad('程式碼在哪', k_w)}{DIM}{files[0]}{RESET}")
    print(f"{pad('', k_w)}{DIM}{files[1]}{RESET}")
    print(f"{pad('', k_w)}{DIM}{files[2]}{RESET}")
    if n1:
        r4 = f"{n4 / n1:.0f}×" if n1 else "—"
        r8 = f"{n8 / n1:.0f}×" if n1 else "—"
        print(f"\n{CYAN}行數倍數{RESET} {n1} → {n4}（{r4}）→ {n8}（{r8}）"
              f"　{DIM}接地品質越可控，你要養的東西越多{RESET}")
        print(f"{CYAN}Lab 1 那一行{RESET} {src1}")
    return rows, (n1, n4, n8)


def self_check():
    slide = """// ~/.gemini/config/mcp_config.json
    { "mcpServers": { "notebooklm": { "command": "notebooklm-mcp", "args": [],
        "disabledTools": ["notebook_delete", "source_delete"], } } }"""
    assert json.loads(strip_jsonc(slide))["mcpServers"]["notebooklm"]["command"] == "notebooklm-mcp"
    assert strip_jsonc('{"u": "http://a//b"}') == '{"u": "http://a//b"}'  # 字串裡的 // 不能砍
    assert strip_jsonc('{"p": "C:\\\\x", /* 註解 */ "q": 1}').count('"') == 6

    yes = lambda _: "/usr/local/bin/notebooklm-mcp"
    ok = check_config(slide, which=yes)
    assert [l for l, _ in ok] == ["OK"], ok

    bad = check_config('{"mcpServers":{"notebooklm":{"command":"notebooklm-mcp"}}}', which=yes)
    assert any(l == "WARN" and "disabledTools" in m for l, m in bad), bad

    nopath = check_config(slide, which=lambda _: None)
    assert any("PATH" in m for _, m in nopath), nopath

    urlbad = check_config('{"mcpServers":{"notebooklm":{"url":"https://x","args":["notebooklm"]}}}', which=yes)
    assert any(l == "ERROR" and "serverUrl" in m for l, m in urlbad), urlbad

    assert any(l == "ERROR" for l, _ in check_config('{"mcpServers":{"fs":{"command":"npx"}}}', which=yes))
    # nlm setup add gemini 可能寫成別的 command，靠 server 名字也要認得出來
    setup = check_config('{"mcpServers":{"notebooklm":{"command":"nlm","args":["mcp"],'
                         '"disabledTools":["notebook_delete","source_delete"]}}}', which=yes)
    assert [l for l, _ in setup] == ["OK"], setup
    assert check_config("{oops")[0][0] == "ERROR"
    assert check_config("{}") == [("ERROR", "沒有 mcpServers 物件（或是空的）")]

    assert citations("見 [1] https://adk.dev/deploy 與 https://adk.dev/deploy。") == ["https://adk.dev/deploy"]
    assert citations("來源中找不到相關資訊。") == []

    total, bad_rows = scan_sources("adk.dev  ready\nantigravity  processing\n\nmcp.io  ready")
    assert (total, len(bad_rows)) == (3, 1), (total, bad_rows)

    from types import SimpleNamespace as NS
    assert report(NS(returncode=1, stdout="", stderr="session expired"))[0] == 1
    assert report(NS(returncode=0, stdout="", stderr=""))[0] == 1
    code, msg = report(NS(returncode=0, stdout="來源中找不到。", stderr=""))
    assert code == 1 and "沒有任何引用" in msg
    assert report(NS(returncode=0, stdout="答案 https://adk.dev", stderr=""))[0] == 0

    assert width("課程知識庫") == 10 and width("adk.dev") == 7
    assert pad("行數", 6) == "行數  "
    assert loc("lab4/mcp_config.json", "//") == 9, "範本 JSON 沒有註解，9 行就是 9 行"
    assert loc("lab4/no-such-file.json") == 0        # 檔案不在不能炸
    assert find_line("lab4/mcp_config.json", "disabledTools")[0] == 6
    assert find_line("lab4/mcp_config.json", "沒有這串")== (0, "")
    print("self-check 全過")


def main(argv):
    if not argv or argv[0] in ("--self-check", "-h", "--help"):
        return self_check() if argv and argv[0] == "--self-check" else print(__doc__)

    cmd = argv[0]
    if cmd == "check":
        path = Path(argv[1]) if len(argv) > 1 and not argv[1].startswith("-") else DEFAULT_CONFIG
        if not path.exists():
            sys.exit(f"設定檔不存在：{path}（步驟 5 要自己建）")
        findings = check_config(path.read_text())
        for level, msg in findings:
            print(f"[{level}] {msg}")
        sys.exit(1 if any(l == "ERROR" for l, _ in findings) else 0)

    if cmd == "aha":
        grounding_table()
        return

    if cmd == "notebooks":
        res = run_nlm("notebook", "list")
        code, msg = report(res, need_cite=False)
        print(msg)
        sys.exit(code)

    if cmd == "sources":
        res = run_nlm("source", "list", notebook_id(argv))
        code, msg = report(res, need_cite=False)
        print(msg)
        if code == 0:
            total, bad = scan_sources(msg)
            # 印「行數」不印「來源數」：nlm 可能有表頭，行數不等於來源數
            print(f"\n掃了 {total} 行，未就緒 {len(bad)} 筆" + ("".join(f"\n  - {b}" for b in bad) or ""))
            code = 1 if bad else 0
        sys.exit(code)

    if cmd == "ask":
        nb = notebook_id(argv)
        args = list(argv[1:])
        if "--nb" in args:
            idx = args.index("--nb")
            if idx + 1 < len(args):
                args.pop(idx + 1)
            args.pop(idx)
        q = " ".join(args).strip()
        if not q:
            sys.exit('用法：uv run wiki.py ask "你的問題"')
        code, msg = report(run_nlm("query", "notebook", nb, q))
        print(msg)
        for u in citations(msg):
            print(f"  來源 {u}")
        sys.exit(code)

    sys.exit(f"不認識的指令 {cmd!r}，看 uv run wiki.py --help")


if __name__ == "__main__":
    main(sys.argv[1:])
