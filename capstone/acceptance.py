"""驗收矩陣：把投影片 446 頁的六條端到端驗收，變成可勾選＋可執行的清單。

跑法：
  uv run acceptance.py --self-check        # 驗矩陣本身（欄位齊全、對齊函式），離線
  uv run acceptance.py                     # 印矩陣（終端機表格）
  uv run acceptance.py --matrix > ACCEPTANCE.md   # 產出可勾選的 Markdown
  uv run acceptance.py --offline           # 真的跑所有離線檢查（不連網、不花錢），失敗回傳 exit 1

kind 的意思：offline=這台機器就能驗；cloud=要 GCP／Supabase／API key；manual=要人看畫面。
"""

import subprocess
import sys
import unicodedata

# id, phase, 投影片 446 的驗收條目, kind, 指令或動作, 預期看到什麼
CHECKS = [
    ("P1-1", "Phase 1", "知識層核心邏輯（切塊／向量／DSN 防呆）", "offline",
     "uv run wiki_core.py --self-check", "wiki_core self-check OK"),
    ("P1-2", "Phase 1", "ingest 管線可跑、dry-run 不寫 DB", "offline",
     "uv run ingest.py --self-check", "ingest self-check OK"),
    ("P1-3", "Phase 1", "schema 到位：documents 有 topic/created_at、業務表有資料", "cloud",
     "psql \"$DATABASE_URL\" -f schema.sql", "最後三個 select 印出 doc_chunks / monthly_total / topic,created_at"),
    ("P1-4", "Phase 1", "雙庫對照：同一題分別問 NotebookLM 與 pgvector", "manual",
     "uv run adk web（問 wiki_agent）＋ NotebookLM 網頁問同一題", "兩邊都有答案；NotebookLM 有引用卡、pgvector 有 source 欄位"),
    ("P2-1", "Phase 2", "團隊接線：root 禁答、google_search 獨占、模型分級", "offline",
     "uv run python -m concierge.agent --self-check", "concierge self-check OK"),
    ("P2-2", "Phase 2", "工具契約：docstring、上限夾住、DB 掛掉不拋例外", "offline",
     "uv run python -m concierge.tools --self-check", "tools self-check OK"),
    ("P2-3", "Phase 2", "摘要工作流：EMPTY 分支不呼叫 LLM、路由字串正確", "offline",
     "uv run digest.py --self-check", "digest self-check OK"),
    ("P2-4", "Phase 2", "446-6 的 eval 部分：evalset 對 concierge 全綠", "cloud",
     "uv run adk eval concierge tests/capstone.evalset.json --print_detailed_results", "每個 case 都 PASSED"),
    ("P3-1", "Phase 3", "wiki-mcp 工具邏輯與權限閘（唯讀部署擋住 ingest）", "offline",
     "uv run wiki_mcp/server.py --self-check", "wiki-mcp self-check OK"),
    ("P3-2", "Phase 3", "Toolbox 設定檔是合法 YAML 且 toolset 有列到工具", "offline",
     "uv run --with pyyaml python -c \"import yaml,sys;d=[x for x in yaml.safe_load_all(open('tools.yaml')) if x];print(len(d))\"",
     "7"),
    ("P3-3", "Phase 3", "MCP Inspector 看得到 2 tools + 1 resource", "manual",
     "uv run mcp dev wiki_mcp/server.py", "Tools 有 wiki_search／wiki_ingest；Resources 有 wiki://stats"),
    ("P3-4", "Phase 3", "Toolbox 服務回得出 personal-data toolset", "cloud",
     "curl -s $TOOLBOX_URL/api/toolset/personal-data | uv run python -m json.tool", "四個工具的 name 與 description"),
    ("P4-1", "Phase 4", "A2A 名片拿得到、skill 描述正確", "cloud",
     "curl -s $RESEARCH_A2A_URL/.well-known/agent-card.json | uv run python -m json.tool", "name=research_agent，skills[0].description 是研究員那段"),
    ("P4-2", "Phase 4", "部署腳本順序正確（工具→專員→入口）", "offline",
     "./deploy.sh --dry-run", "dry-run OK：6 段、順序 secrets → wiki-mcp → toolbox → research-a2a → IAM → concierge"),
    ("P4-3", "Phase 4", "446-1 知識問答：答案帶正確引用", "cloud",
     "在 concierge UI 問「我知識庫裡關於 A2A 的重點？」", "回覆有 source，且 source 真的在 documents 表裡"),
    ("P4-4", "Phase 4", "446-2 研究入庫：研究→ingest→再問答得到", "cloud",
     "問「研究 Cloud Run GPU 定價並存起來」，再問「我知識庫裡 Cloud Run GPU 的重點？」", "第二次問答引用到剛存的 source"),
    ("P4-5", "Phase 4", "446-3 資料查詢：Toolbox SQL 正確聚合", "cloud",
     "問「我這個月的訂閱總花費？」", "數字等於 select sum(monthly_twd) from subscriptions where active"),
    ("P4-6", "Phase 4", "446-4 持久化：重新整理後追問前文", "cloud",
     "對話 → 重新整理瀏覽器 → 追問「剛剛那筆」；並看 Supabase 的 events 表", "追問接得上；events 表有這次對話的列"),
    ("P4-7", "Phase 4", "446-5 摘要工作流產出合格日報", "cloud",
     "uv run digest.py", "Markdown 有「今日重點／值得深讀／待辦建議」三段"),
    ("P4-8", "Phase 4", "446-6 權限：未授權身分呼叫內部服務 → 403", "cloud",
     "curl -s -o /dev/null -w '%{http_code}\\n' $WIKI_MCP_URL/mcp", "403"),
]


def width(s: str) -> int:
    """中文在終端機是兩格寬。少了這個，表格框線會歪掉（BRIEF 的硬要求）。"""
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in s)


def pad(s: str, n: int) -> str:
    return s + " " * max(0, n - width(s))


def print_table(rows: list[tuple], color: bool) -> None:
    headers = ("ID", "Phase", "驗收條目", "kind")
    cols = [max(width(h), *(width(str(r[i])) for r in rows)) for i, h in enumerate(headers)]
    line = "  ".join(pad(h, cols[i]) for i, h in enumerate(headers))
    print(line)
    print("-" * width(line))
    for r in rows:
        mark = {"offline": "\033[32m", "cloud": "\033[33m", "manual": "\033[36m"}.get(r[3], "") if color else ""
        end = "\033[0m" if color and mark else ""
        print("  ".join(pad(str(r[i]), cols[i]) for i in range(3)) + "  " + mark + str(r[3]) + end)


def markdown() -> str:
    out = ["# Capstone 驗收矩陣", "",
           "對應投影片 446 頁的六條端到端驗收＋四個 Phase 的中間成果。",
           "`offline` 這台機器就能驗；`cloud` 要 GCP／Supabase／API key；`manual` 要人看畫面。", ""]
    for phase in ("Phase 1", "Phase 2", "Phase 3", "Phase 4"):
        out.append(f"## {phase}")
        out.append("")
        out.append("| 勾 | ID | 驗收條目 | kind | 怎麼驗（可貼） | 預期看到 |")
        out.append("|---|---|---|---|---|---|")
        for cid, ph, item, kind, how, expect in CHECKS:
            if ph == phase:
                out.append(f"| [ ] | {cid} | {item} | {kind} | `{how}` | {expect} |")
        out.append("")
    off = [c for c in CHECKS if c[3] == "offline"]
    out += ["## 一次跑完所有離線檢查", "", "```bash", "uv run acceptance.py --offline", "```", "",
            f"共 {len(off)} 條，全綠才往下走 Phase 4 的雲端驗收。", ""]
    return "\n".join(out)


def run_offline() -> int:
    """真的執行 kind=offline 的指令，回傳失敗數。"""
    failed = 0
    for cid, _ph, item, kind, how, expect in CHECKS:
        if kind != "offline":
            continue
        p = subprocess.run(how, shell=True, capture_output=True, text=True)
        out = (p.stdout + p.stderr).strip()
        ok = p.returncode == 0 and expect.split("（")[0].strip() in out
        print(f"[{'PASS' if ok else 'FAIL'}] {cid} {item}")
        if not ok:
            failed += 1
            print(f"       指令：{how}\n       預期含：{expect}\n       實際：{out[-400:]}")
    print(f"\n離線驗收：{len([c for c in CHECKS if c[3] == 'offline']) - failed} 通過 / {failed} 失敗")
    return failed


def _self_check() -> None:
    ids = [c[0] for c in CHECKS]
    assert len(ids) == len(set(ids)), "ID 重複"
    assert all(len(c) == 6 for c in CHECKS), "每條都要六個欄位"
    # 投影片 446 的六條驗收，每一條都要至少有一列對應（少一條就是漏驗）
    for n in range(1, 7):
        assert any(f"446-{n}" in c[2] for c in CHECKS), f"投影片 446 的第 {n} 條沒有對應的驗收列"
    assert {c[3] for c in CHECKS} == {"offline", "cloud", "manual"}
    assert len([c for c in CHECKS if c[3] == "offline"]) >= 6

    # 中文寬度：這是表格不歪掉的關鍵
    assert width("驗收") == 4 and width("ok") == 2 and width("ok 驗收") == 7
    assert width(pad("驗收", 6)) == 6 and pad("ok", 4) == "ok  "

    md = markdown()
    assert md.count("| [ ] |") == len(CHECKS)
    for phase in ("Phase 1", "Phase 2", "Phase 3", "Phase 4"):
        assert f"## {phase}" in md

    # run_offline：把 subprocess 換成假的，驗 PASS/FAIL 判定與回傳值
    # 假 runner 一定會印一堆 FAIL（那是預期的），吞掉它的輸出，不然學生會以為驗收壞了
    import contextlib
    import io

    real = subprocess.run
    subprocess.run = lambda *a, **k: type("R", (), {"returncode": 0, "stdout": "wiki_core self-check OK", "stderr": ""})()
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            assert run_offline() > 0  # 只有第一條會通過，其他預期字串不同 → 有失敗
            subprocess.run = lambda *a, **k: type("R", (), {"returncode": 1, "stdout": "", "stderr": "boom"})()
            assert run_offline() == len([c for c in CHECKS if c[3] == "offline"])
    finally:
        subprocess.run = real

    print("acceptance self-check OK", file=sys.stderr)


if __name__ == "__main__":
    if "--self-check" in sys.argv:
        _self_check()
    elif "--matrix" in sys.argv:
        print(markdown())
    elif "--offline" in sys.argv:
        raise SystemExit(1 if run_offline() else 0)
    else:
        print_table(CHECKS, color=sys.stdout.isatty())
