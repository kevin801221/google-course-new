"""Phase 1 ingest 管線：一支指令碼餵飽兩庫（pgvector 可查 ＋ 摘要給 NotebookLM 可讀）。

跑法：
  uv run ingest.py --self-check                       # 離線：假 fetch／embed／DB，不連網不花錢
  uv run ingest.py notes/a2a.md --dry-run             # 只切塊不入庫，看它會寫幾塊、內容長怎樣
  uv run ingest.py https://a2a-protocol.org --topic protocol   # 真的呼叫 API＋寫 Supabase

環境變數：DATABASE_URL、GEMINI_API_KEY（見 SPEC.md）
"""

import asyncio
import sys
from types import SimpleNamespace

import wiki_core


def parse_args(argv: list[str]) -> dict:
    """手工 parse：三個 flag 而已，argparse 的 help 排版反而更花時間。"""
    args = {"source": None, "topic": "", "dry_run": False}
    rest = list(argv)
    if "--dry-run" in rest:
        args["dry_run"] = True
        rest.remove("--dry-run")
    if "--topic" in rest:
        i = rest.index("--topic")
        if i + 1 >= len(rest):
            raise SystemExit("--topic 後面要接主題名，例如 --topic protocol")
        args["topic"] = rest[i + 1]
        del rest[i : i + 2]
    positional = [a for a in rest if not a.startswith("-")]
    if not positional:
        raise SystemExit("用法：uv run ingest.py <url 或檔案> [--topic X] [--dry-run]")
    args["source"] = positional[0]
    return args


def main(argv: list[str]) -> int:
    a = parse_args(argv)
    text = wiki_core.fetch_text(a["source"])
    chunks = wiki_core.chunk(text)
    print(f"來源：{a['source']}｜topic：{a['topic'] or '(無)'}｜字數：{len(text)}｜切成 {len(chunks)} 塊")
    if a["dry_run"]:
        for i, c in enumerate(chunks[:3]):
            print(f"--- chunk {i} ({len(c)} 字) ---\n{c[:200]}")
        print("dry-run：沒有呼叫 embedding、沒有寫入 DB、沒有花錢", file=sys.stderr)
        return 0
    res = asyncio.run(wiki_core.ingest_impl(a["source"], a["topic"]))
    print(res)
    if res.get("status") != "success":
        return 1  # 入庫失敗就不要再花一次 summarize 的錢
    # NotebookLM 那一側：摘要印出來，手動貼進筆記本或交給 notebooklm-mcp（Lab 4）
    print("\n=== 給 NotebookLM 的摘要 ===")
    print(wiki_core.summarize(text))
    return 0


def _self_check() -> None:
    assert parse_args(["a.md"]) == {"source": "a.md", "topic": "", "dry_run": False}
    assert parse_args(["a.md", "--topic", "x", "--dry-run"]) == {"source": "a.md", "topic": "x", "dry_run": True}
    assert parse_args(["--dry-run", "--topic", "t", "http://x"])["source"] == "http://x"
    for bad in [[], ["--dry-run"], ["a.md", "--topic"]]:
        try:
            parse_args(bad)
            raise AssertionError("應該擋掉 %r" % bad)
        except SystemExit:
            pass

    # 整條路徑走一次：fetch／embed／DB 全換成假的，驗參數傳遞與回傳
    real = (wiki_core.fetch_text, wiki_core.embed, wiki_core._conn, wiki_core.summarize)
    wiki_core.fetch_text = lambda src: "第一段內容。" * 300
    wiki_core.embed = lambda texts: ["[0.1]" for _ in texts]
    wiki_core.summarize = lambda text: "摘要 OK"
    written = {}

    async def fake_conn():
        async def executemany(sql, rows):
            written["sql"], written["rows"] = sql, rows

        async def close():
            written["closed"] = True

        return SimpleNamespace(executemany=executemany, close=close)

    wiki_core._conn = fake_conn
    try:
        assert main(["fake.md", "--dry-run"]) == 0
        assert not written, "dry-run 不可以寫 DB"
        assert main(["fake.md", "--topic", "proto"]) == 0
        assert written["closed"] and len(written["rows"]) == 2, written["rows"]
        assert written["rows"][0][1] == "proto"  # topic 有傳到 SQL 參數
        assert written["rows"][0][3] == "[0.1]"  # 向量是字串 literal，不是 list
        # 抽不到內容要回 error，不能靜靜寫入 0 塊
        wiki_core.fetch_text = lambda src: "   "
        assert main(["empty.md"]) == 1
    finally:
        wiki_core.fetch_text, wiki_core.embed, wiki_core._conn, wiki_core.summarize = real

    print("ingest self-check OK", file=sys.stderr)


if __name__ == "__main__":
    if "--self-check" in sys.argv:
        _self_check()
    else:
        raise SystemExit(main(sys.argv[1:]))
