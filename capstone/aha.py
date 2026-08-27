"""Capstone 的五個對照 demo：全部離線、不用 key、不花錢，用來看清這套系統的接線。

跑法（在 capstone/ 執行）：
  uv run aha.py --parts        # 零件盤點：新套件 0 個，唯一的新演算法幾行
  uv run aha.py --map          # M1-M10 的產物接成一張接線圖（會檢查檔案真的在）
  uv run aha.py --wrappers     # 同一份 docstring 的四種包裝：Python / ADK / MCP / A2A
  uv run aha.py --delegation   # ADK 委派的真面目：description 被貼進 root 的 system instruction
  uv run aha.py --threshold    # 「查不到」不是 DB 給的，是 min_sim 這個數字造出來的
  uv run aha.py --self-check   # 用 assert 驗上面五段的資料，不印表
"""

import ast
import asyncio
import os
import sys
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

DIM, BOLD, CYAN, GREEN, YELLOW, RESET = (
    ("\033[2m", "\033[1m", "\033[36m", "\033[32m", "\033[33m", "\033[0m") if sys.stdout.isatty() else ("",) * 6
)

# 檔案 → 它是哪個 Lab 的零件（投影片 430 的裝備檢查表，落到本 repo 的實體檔案）
PARTS = {
    "wiki_core.py": ("Lab 8", "pgvector RAG（chunk／embed／檢索）"),
    "ingest.py": ("Lab 1", "Gemini 呼叫＋url_context 抽正文"),
    "schema.sql": ("Lab 8", "documents 表加 topic／created_at"),
    "concierge/agent.py": ("Lab 7", "multi-agent 委派結構"),
    "concierge/tools.py": ("Lab 7", "ADK function tool 契約"),
    "digest.py": ("Lab 7", "Graph workflow＋路由"),
    "tests/capstone.evalset.json": ("Lab 7", "evalset 四個 case"),
    "wiki_mcp/server.py": ("Lab 6", "自建 MCP server"),
    "tools.yaml": ("Lab 8", "MCP Toolbox 的 SQL 工具"),
    "mcp_config.sample.json": ("Lab 3/4", "Antigravity 當 MCP host"),
    "research_service/agent.py": ("Lab 9", "to_a2a() 曝露 agent card"),
    "deploy.sh": ("Lab 5/10", "IAM／Secret Manager／Cloud Run"),
    "Dockerfile": ("Lab 10", "容器化（一份服務兩個部署）"),
    "acceptance.py": ("Lab 7", "可執行的驗收矩陣"),
}

# 第三方套件 → 第一次見到它的 Lab。不在這張表裡的就是「新套件」
KNOWN_PKGS = {
    "google.genai": "Lab 1（Gemini API）",
    "google": "Lab 1（google-genai / google-adk）",
    "google.adk": "Lab 7（ADK）",
    "mcp": "Lab 6（自建 MCP server）",
    "asyncpg": "Lab 8（Supabase pgvector）",
    "yaml": "Lab 8（Toolbox tools.yaml）",
    "a2a": "Lab 9（A2A SDK）",
}
STDLIB = set(sys.stdlib_module_names)


def width(s):
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in s)


def pad(s, n):
    return s + " " * max(0, n - width(s))


def rows(header, data, widths):
    print(f"\n{BOLD}" + "".join(pad(h, w) for h, w in zip(header, widths)).rstrip() + RESET)
    print(DIM + "─" * (sum(widths) - 2) + RESET)
    for r in data:
        print("".join(pad(str(c), w) for c, w in zip(r, widths)).rstrip())


# ── --parts：零件盤點 ────────────────────────────────────────────────
def py_files():
    return [f for f in PARTS if f.endswith(".py")]


def count_lines(path):
    return len(open(os.path.join(HERE, path), encoding="utf-8").read().splitlines())


def third_party_imports():
    """掃所有 .py 的 import，扣掉標準庫與本 repo 自己的模組，剩下的就是第三方。"""
    local = {os.path.basename(f)[:-3] for f in py_files()} | {"concierge", "wiki_mcp", "research_service"}
    found = {}
    for f in py_files():
        tree = ast.parse(open(os.path.join(HERE, f), encoding="utf-8").read())
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                # from google import genai → 記成 google.genai，不要退化成 google
                names = [f"{node.module}.{a.name}" for a in node.names] if node.module == "google" else [node.module]
            for n in names:
                top = n.split(".")[0]
                if top in STDLIB or top in local:
                    continue
                found.setdefault(".".join(n.split(".")[:2]) if top == "google" else top, set()).add(f)
    return found


def func_lines(path, name):
    """某個函式實際佔幾行（ast 的 lineno～end_lineno）。"""
    tree = ast.parse(open(os.path.join(HERE, path), encoding="utf-8").read())
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
    return fn.end_lineno - fn.lineno + 1


def consumers_of(symbol):
    """grep 誰 import 了 wiki_core —— 一份實作，幾個消費者。"""
    out = []
    for f in py_files():
        if f == "wiki_core.py":
            continue
        if symbol in open(os.path.join(HERE, f), encoding="utf-8").read():
            out.append(f)
    return out


def parts_data():
    pkgs = third_party_imports()
    unknown = sorted(k for k in pkgs if k not in KNOWN_PKGS)
    total = sum(count_lines(f) for f in py_files())
    chunk_n = func_lines("wiki_core.py", "chunk")
    return {
        "total": total,
        "pkgs": pkgs,
        "unknown": unknown,
        "chunk": chunk_n,
        "consumers": consumers_of("import wiki_core"),
    }


def show_parts():
    d = parts_data()
    print(f"{BOLD}Capstone 零件盤點{RESET} {DIM}—— 這個 Lab 到底用了幾樣「新東西」{RESET}")
    rows(
        ["檔案", "行數", "來自", "本來是什麼"],
        [[f, count_lines(f), PARTS[f][0], PARTS[f][1]] for f in py_files()],
        [28, 7, 10, 34],
    )
    rows(
        ["第三方套件", "第一次見到它的 Lab"],
        [[k, KNOWN_PKGS.get(k, f"{YELLOW}★ 新套件{RESET}")] for k in sorted(d["pkgs"])],
        [22, 34],
    )
    ratio = f"{(d['total'] - d['chunk']) / d['chunk']:.0f}×"
    rows(
        ["指標", "數字"],
        [
            ["Python 總行數", f"{d['total']:,}"],
            ["第三方套件種類", len(d["pkgs"])],
            ["其中前面 Lab 沒見過的", f"{GREEN}{len(d['unknown'])}{RESET}"],
            ["唯一算得上新演算法的 chunk()", f"{d['chunk']} 行"],
            ["接線 : 新邏輯", f"{BOLD}{ratio}{RESET}"],
            ["wiki_core 的消費者", f"{len(d['consumers'])} 個（{', '.join(d['consumers'])}）"],
        ],
        [32, 46],
    )
    print(f"\n{DIM}接線佔 {d['total'] - d['chunk']} 行、新邏輯 {d['chunk']} 行。系統的價值在接線，不在元件。{RESET}")


# ── --map：接線圖 ───────────────────────────────────────────────────
WIRING = """
                     ┌──────────────── 手機／瀏覽器 ────────────────┐
                     │  adk deploy cloud_run --with_ui   (Lab 10)  │
                     └───────────────────┬─────────────────────────┘
                                         │ /run_sse
                  ┌──────────────────────▼──────────────────────┐
                  │  concierge (root)  concierge/agent.py       │  Lab 7
                  │  只委派、不自答；session → Supabase (Lab 8)  │
                  └───┬──────────────┬───────────────┬──────────┘
       transfer_to_    │              │               │
       agent (Lab 7)   │              │               │
        ┌──────────────▼──┐ ┌─────────▼────────┐ ┌────▼─────────────┐
        │ wiki_agent      │ │ research_agent   │ │ data_agent       │
        │ search_knowledge│ │ google_search    │ │ ToolboxToolset   │
        │  Lab 8          │ │  Lab 1 / Lab 9   │ │  Lab 8           │
        └────────┬────────┘ └────────┬─────────┘ └────────┬─────────┘
                 │                   │ A2A                │ HTTP
                 │              ┌────▼──────────────┐ ┌───▼────────────┐
                 │              │ research-a2a      │ │ MCP Toolbox    │
                 │              │ to_a2a()  Lab 9   │ │ tools.yaml Lab8│
                 │              └────┬──────────────┘ └───┬────────────┘
                 │                   │ ingest             │ 寫死的 SQL
   ┌─────────────▼───────────────────▼───────┐            │
   │  wiki_core.py  ← 一份實作，四個消費者     │            │
   │  chunk / embed / search / ingest  Lab 8 │            │
   └──┬────────────┬──────────────┬──────────┘            │
      │            │              │                       │
┌─────▼─────┐ ┌────▼────────┐ ┌───▼──────────┐    ┌───────▼────────────┐
│ ingest.py │ │ digest.py   │ │ wiki_mcp/    │    │ Supabase Postgres  │
│ CLI Lab1  │ │ Graph Lab7  │ │ server.py    │    │ sessions＋pgvector │
└───────────┘ └─────────────┘ │  Lab 6       │    │ ＋業務表    Lab 8  │
                              └───┬──────────┘    └────────────────────┘
                                  │ MCP
                        ┌─────────▼──────────────┐   ┌──────────────────┐
                        │ 你的 Antigravity  Lab3 │   │ NotebookLM  Lab4 │
                        │ 同事的 host（未來的）  │   │ 策展側（人工）   │
                        └────────────────────────┘   └──────────────────┘

  全部跑在：GCP 專案／IAM／Secret Manager (Lab 5) ＋ Cloud Run (Lab 10)
"""


def show_map():
    print(f"{BOLD}前十個模組的產物，接成一張圖{RESET}")
    print(WIRING)
    missing = [f for f in PARTS if not os.path.exists(os.path.join(HERE, f))]
    rows(
        ["圖上的方塊", "檔案在不在", "來自"],
        [[PARTS[f][1], f"{GREEN}✓{RESET} {f}" if f not in missing else f"{YELLOW}✗ 缺{RESET} {f}", PARTS[f][0]] for f in PARTS],
        [36, 34, 10],
    )
    print(f"\n{DIM}{len(PARTS)} 個方塊、缺 {len(missing)} 個。每個方塊都是你前面某一天做過的東西。{RESET}")


# ── --wrappers：同一份 docstring 的四種包裝 ─────────────────────────
def wrappers_data():
    """同一個能力，四個生態系層級各自的「規格」長什麼樣。全部離線生成。"""
    import json

    from google.adk.tools import FunctionTool

    from concierge.tools import search_knowledge

    out = {}
    out["python"] = {
        "layer": "① Python 函式（你只寫了這一份）",
        "where": "concierge/tools.py",
        "schema": f"async def search_knowledge(query: str, top_k: int = 5) -> dict\n"
        f'    """{(search_knowledge.__doc__ or "").strip().splitlines()[0]} …"""',
    }
    decl = FunctionTool(search_knowledge)._get_declaration()
    out["adk"] = {
        "layer": "② ADK function tool（Lab 7）",
        "where": "concierge/agent.py 的 tools=[...]",
        "schema": json.dumps(decl.model_dump(exclude_none=True)["parameters_json_schema"], ensure_ascii=False),
    }
    sys.path.insert(0, os.path.join(HERE, "wiki_mcp"))
    import server as wiki_server

    tool = next(t for t in asyncio.run(wiki_server.mcp.list_tools()) if t.name == "wiki_search")
    out["mcp"] = {
        "layer": "③ MCP tool（Lab 6）",
        "where": "wiki_mcp/server.py → 任何 host 的 tools/list",
        "schema": json.dumps(tool.model_dump(exclude_none=True)["input_schema"], ensure_ascii=False),
    }
    os.environ["A2A_SKIP_APP"] = "1"
    from google.adk.a2a.utils.agent_card_builder import AgentCardBuilder

    import research_service.agent as rs

    card = asyncio.run(AgentCardBuilder(agent=rs.root_agent, rpc_url="http://localhost:8001/").build())
    skill = card.skills[0]
    out["a2a"] = {
        "layer": "④ A2A skill（Lab 9）",
        "where": "research_service/agent.py → /.well-known/agent-card.json",
        "schema": f'{{"id": "{skill.id}", "description": "{skill.description[:30]}…"}}',
    }
    return out


def show_wrappers():
    d = wrappers_data()
    print(f"{BOLD}同一個能力，四層包裝紙{RESET} {DIM}—— 全部從 docstring／description 自動生出來{RESET}")
    for k in ("python", "adk", "mcp", "a2a"):
        v = d[k]
        print(f"\n{CYAN}{BOLD}{v['layer']}{RESET} {DIM}{v['where']}{RESET}")
        print("  " + v["schema"])
    adk_props = d["adk"]["schema"]
    mcp_props = d["mcp"]["schema"]
    same = adk_props.replace("search_knowledgeParams", "X") == mcp_props.replace("wiki_searchArguments", "X")
    print(
        f"\n{DIM}② 與 ③ 的 JSON schema 逐字相同（除了 title）：{RESET}"
        f"{GREEN if same else YELLOW}{same}{RESET}"
        f"{DIM} —— 兩個不同框架，同一份型別標註。{RESET}"
    )


# ── --delegation：委派的真面目 ──────────────────────────────────────
def delegation_text():
    from google.adk.flows.llm_flows.agent_transfer import _build_transfer_instruction_body

    import concierge.agent as m

    return _build_transfer_instruction_body("transfer_to_agent", m.root_agent.sub_agents), m.root_agent.sub_agents


def show_delegation():
    text, subs = delegation_text()
    print(f"{BOLD}ADK 的「委派」拆開來看{RESET} {DIM}—— 這段是 ADK 自己加到 root system instruction 的原文{RESET}")
    print(DIM + "─" * 60 + RESET)
    print(text.strip())
    print(DIM + "─" * 60 + RESET)
    rows(
        ["你在 agent.py 寫的 description", "去了哪裡"],
        [[s.description[:16] + "…", "原文出現在上面那段 prompt 裡"] for s in subs],
        [40, 40],
    )
    print(
        f"\n{DIM}root 沒有「委派能力」這種東西：它只是多了一個 transfer_to_agent 工具，"
        f"加上上面這段把你的 description 原文貼進去的 prompt。{RESET}"
    )


# ── --threshold：「查不到」是誰決定的 ──────────────────────────────
FAKE_ROWS = [
    {"source": "notes/a2a.md", "topic": "protocol", "content": "Agent Card 放在 /.well-known/agent-card.json", "sim": 0.81},
    {"source": "notes/gcp.md", "topic": "gcp", "content": "Cloud Run 的 scale-to-zero", "sim": 0.34},
    {"source": "notes/book.md", "topic": "reading", "content": "上週讀的小說心得", "sim": 0.12},
    {"source": "notes/recipe.md", "topic": "life", "content": "滷肉飯的做法", "sim": 0.03},
]


def threshold_data():
    import wiki_core

    return [(t, wiki_core.format_hits(FAKE_ROWS, min_sim=t)) for t in (0.0, 0.25, 0.5, 0.9)]


def show_threshold():
    print(f"{BOLD}「知識庫裡沒有」是誰說的？{RESET} {DIM}—— 同一批檢索結果，只改 min_sim{RESET}")
    print(f"\n{DIM}pgvector 回來的四列（相似度）：{RESET} " + "  ".join(f"{r['source']}={r['sim']}" for r in FAKE_ROWS))
    rows(
        ["min_sim", "status", "留下幾筆", "wiki_agent 會引用誰"],
        [
            [t, res["status"], len(res["hits"]), ", ".join(h["source"] for h in res["hits"]) or "（無）"]
            for t, res in threshold_data()
        ],
        [10, 11, 11, 46],
    )
    print(
        f"\n{DIM}`order by embedding <=> $1::vector limit $2` 永遠會回滿 top_k 列 —— 連滷肉飯都在裡面。"
        f"status=empty 不是資料庫給的，是 wiki_core.format_hits 的 min_sim=0.25 造出來的。{RESET}"
    )


def _self_check():
    d = parts_data()
    assert d["total"] > 800 and d["chunk"] > 5, d
    assert d["unknown"] == [], f"有沒對照到 Lab 的新套件：{d['unknown']}"
    assert len(d["consumers"]) >= 4, d["consumers"]
    assert [f for f in PARTS if not os.path.exists(os.path.join(HERE, f))] == [], "接線圖指到不存在的檔案"

    counts = [len(res["hits"]) for _, res in threshold_data()]
    assert counts == sorted(counts, reverse=True) and counts[0] == 4 and counts[-1] == 0, counts
    assert threshold_data()[-1][1]["status"] == "empty"

    w = wrappers_data()
    assert set(w) == {"python", "adk", "mcp", "a2a"}
    # 兩個框架從同一份型別標註生出來的 schema，除了 title 應該逐字相同
    assert w["adk"]["schema"].replace("search_knowledgeParams", "X") == w["mcp"]["schema"].replace(
        "wiki_searchArguments", "X"
    ), (w["adk"]["schema"], w["mcp"]["schema"])
    assert "agent-card" in w["a2a"]["where"]

    core = open(os.path.join(HERE, "wiki_core.py"), encoding="utf-8").read()
    tops = [ln.split()[1].split(".")[0] for ln in core.splitlines() if ln.startswith(("import ", "from "))]
    assert set(tops) <= {"os", "sys", "types"}, f"wiki_core 的依賴方向反了：{tops}"

    text, subs = delegation_text()
    assert "transfer_to_agent" in text and len(subs) == 3
    for s in subs:  # description 一定要原文出現在 prompt 裡，這是委派會不會發生的唯一依據
        assert s.description in text, s.name

    print("aha self-check OK", file=sys.stderr)


MODES = {
    "--parts": show_parts,
    "--map": show_map,
    "--wrappers": show_wrappers,
    "--delegation": show_delegation,
    "--threshold": show_threshold,
    "--self-check": _self_check,
}

if __name__ == "__main__":
    hit = [a for a in sys.argv[1:] if a in MODES]
    if not hit:
        print(__doc__)
    for a in hit:
        MODES[a]()
