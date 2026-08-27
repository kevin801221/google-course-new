"""Capstone 知識層核心：chunk → embed → pgvector 寫入／檢索。四個消費者共用這一份實作。

消費者：concierge/tools.py（agent 工具）、wiki_mcp/server.py（MCP 工具）、ingest.py（CLI）、digest.py（排程）。

跑法：
  uv run wiki_core.py --self-check     # 離線：假 conn＋假 embedding，不連網不花錢不建表

環境變數：
  DATABASE_URL   Supabase Session pooler（5432）連線字串，見 SPEC.md
  GEMINI_API_KEY embedding 用
"""

import os
import sys
from types import SimpleNamespace

EMBED_MODEL = "gemini-embedding-2"  # 型號名以課程投影片為準；若 404 用 client.models.list() 確認
EMBED_DIM = 1536  # 必須等於 schema.sql 的 vector(1536)；gemini-embedding-2 預設 3072，要顯式截斷
SEARCH_SQL = (
    "select source, topic, content, 1 - (embedding <=> $1::vector) as sim "
    "from documents where embedding is not null "
    "order by embedding <=> $1::vector limit $2"
)
INSERT_SQL = "insert into documents (source, topic, content, embedding) values ($1, $2, $3, $4::vector)"
STATS_SQL = (
    "select count(*) as docs, count(distinct source) as sources, max(created_at) as latest from documents"
)
NEW_DOCS_SQL = "select id, source, content from documents where id > $1 order by id limit 50"


def dsn(url: str | None = None) -> str:
    """把各種來源的連線字串正規化成 asyncpg 吃得下的樣子，順手擋掉兩個必踩的坑。"""
    url = url or os.getenv("DATABASE_URL", "")
    if not url:
        raise RuntimeError("沒有 DATABASE_URL。Supabase → Project Settings → Database → Session pooler（5432）")
    # ADK session service 要 postgresql+asyncpg://（SQLAlchemy），asyncpg 直連要拿掉 +asyncpg
    url = url.replace("postgresql+asyncpg://", "postgresql://").replace("postgres://", "postgresql://")
    if ":6543" in url:
        raise RuntimeError("6543 是 Transaction pooler，與 asyncpg 的 prepared statement 衝突。改用 Session pooler 5432")
    return url


def chunk(text: str, size: int = 1200, overlap: int = 150) -> list[str]:
    """切塊：固定長度＋重疊。overlap 是為了不要把一句話切成兩半而讓兩塊都查不到。"""
    text = (text or "").strip()
    if not text:
        return []
    step = max(1, size - overlap)
    out = [text[i : i + size] for i in range(0, len(text), step)]
    # 最後一塊如果短到完全落在上一塊的 overlap 區裡，就是重複資料，丟掉
    if len(out) > 1 and len(out[-1]) <= overlap:
        out.pop()
    return out


def to_vector(values) -> str:
    """pgvector 的 literal 是字串 '[0.1,0.2]'。直接丟 list 會是 asyncpg 的型別錯誤。"""
    return "[" + ",".join(repr(float(v)) for v in values) + "]"


def embed(texts: list[str]) -> list[str]:
    """把多段文字一次送去 embedding，回傳 pgvector literal 清單。"""
    from google import genai  # 延後 import：--self-check 與 --dry-run 不需要 SDK 也能跑

    with genai.Client() as client:  # 一定要 with，不然 Client 被 GC → client has been closed
        # output_dimensionality 不能省：預設 3072 維，insert 進 vector(1536) 會被 pgvector 打回來
        res = client.models.embed_content(
            model=EMBED_MODEL, contents=texts, config={"output_dimensionality": EMBED_DIM}
        )
    if len(res.embeddings) != len(texts):
        raise ValueError(f"要 {len(texts)} 個向量卻拿到 {len(res.embeddings)} 個")
    return [to_vector(e.values) for e in res.embeddings]


def fetch_text(source: str) -> str:
    """網址 → 用 Gemini 的 url_context 抽正文；檔案 → 直接讀。"""
    if not source.startswith("http"):
        return open(source, encoding="utf-8").read()
    from google import genai

    with genai.Client() as client:
        r = client.interactions.create(
            model="gemini-3.5-flash-lite",  # 高頻雜活用最便宜的（$0.30/1M）
            input=f"抽取此頁正文並保留標題結構，不要加你自己的評論：{source}",
            tools=[{"type": "url_context"}],
        )
    return r.output_text or ""


def summarize(text: str) -> str:
    """150 字摘要＋3 個關鍵詞，給 NotebookLM 那一側讀。"""
    from google import genai

    with genai.Client() as client:
        r = client.interactions.create(
            model="gemini-3.5-flash-lite",
            input="以 150 字繁體中文摘要，最後附 3 個關鍵詞：\n" + text[:8000],
        )
    return r.output_text or ""


def format_hits(rows, min_sim: float = 0.25) -> dict:
    """DB 列 → 給模型看的結果。查不到就明確說查不到，這是 wiki_agent 不腦補的前提。"""
    hits = [
        {
            "source": r["source"],
            "topic": r.get("topic") or "",
            "snippet": (r["content"] or "")[:500],
            "score": round(float(r["sim"]), 3),
        }
        for r in rows
        if float(r["sim"]) >= min_sim
    ]
    seen, uniq = set(), []
    for h in hits:  # 同一份文件切成多塊，會重複命中同一個 source
        if h["source"] not in seen:
            seen.add(h["source"])
            uniq.append(h)
    if not uniq:
        return {"status": "empty", "hits": [], "note": "知識庫沒有相關內容。請直接告訴使用者查無資料，不要自行補答案。"}
    return {"status": "success", "hits": uniq, "note": "回答時必須標出 source。"}


async def _conn():
    import asyncpg

    return await asyncpg.connect(dsn())


async def search_impl(query: str, top_k: int = 5) -> dict:
    """語意檢索：query 轉向量 → pgvector 排序 → 格式化。"""
    vec = embed([query])[0]
    conn = await _conn()
    try:
        rows = await conn.fetch(SEARCH_SQL, vec, top_k)
    finally:
        await conn.close()
    return format_hits([dict(r) for r in rows])


async def ingest_impl(source: str, topic: str = "") -> dict:
    """抓內容 → 切塊 → embed → 寫入 documents。回傳寫了幾塊。"""
    text = fetch_text(source)
    chunks = chunk(text)
    if not chunks:
        return {"status": "error", "message": f"{source} 抽不到內容（空頁面或檔案是空的）"}
    vecs = embed(chunks)
    conn = await _conn()
    try:
        await conn.executemany(INSERT_SQL, [(source, topic, c, v) for c, v in zip(chunks, vecs)])
    finally:
        await conn.close()
    return {"status": "success", "source": source, "topic": topic, "chunks": len(chunks)}


async def stats_impl() -> str:
    conn = await _conn()
    try:
        r = await conn.fetchrow(STATS_SQL)
    finally:
        await conn.close()
    return f"文件塊數：{r['docs']}｜來源數：{r['sources']}｜最近更新：{r['latest']}"


def _self_check() -> None:
    # chunk：短文一塊、長文有重疊、空字串零塊
    assert chunk("") == [] and chunk("   ") == []
    assert chunk("abc") == ["abc"]
    parts = chunk("x" * 3000)
    assert len(parts) == 3 and [len(p) for p in parts] == [1200, 1200, 900], [len(p) for p in parts]
    assert len(chunk("y" * 1100)) == 1  # 1100 < size + overlap 的殘量，一塊就夠
    assert len(chunk("y" * 1100, size=1000, overlap=150)) == 2  # 尾巴 250 > overlap，是新內容要留
    assert len(chunk("y" * 851, size=1000, overlap=150)) == 1  # 尾巴只剩 1 字，整塊都在 overlap 裡 → 丟掉

    assert to_vector([1, 0.5]) == "[1.0,0.5]"

    # 維度必須跟建表的 vector(N) 一致，不然 insert 會被 pgvector 打回來（而且只在真的寫入時才炸）
    ddl = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "schema.sql"), encoding="utf-8").read()
    assert f"vector({EMBED_DIM})" in ddl, f"schema.sql 的 vector() 維度跟 EMBED_DIM={EMBED_DIM} 不一致"

    # dsn：兩個必踩的坑要在連線前就擋下來
    assert dsn("postgresql+asyncpg://u:p@h:5432/db").startswith("postgresql://")
    for bad, kw in [("postgresql://u:p@h:6543/db", "6543"), ("", "DATABASE_URL")]:
        try:
            dsn(bad)
            raise AssertionError("應該擋掉 %r" % bad)
        except RuntimeError as e:
            assert kw in str(e), e

    # format_hits：低分過濾、同 source 去重、查不到要有明確的 empty 契約
    rows = [
        {"source": "a.md", "topic": "t", "content": "第一塊" * 300, "sim": 0.9},
        {"source": "a.md", "topic": "t", "content": "第二塊", "sim": 0.8},
        {"source": "b.md", "topic": "", "content": "另一份", "sim": 0.4},
        {"source": "c.md", "topic": "", "content": "雜訊", "sim": 0.1},
    ]
    out = format_hits(rows)
    assert [h["source"] for h in out["hits"]] == ["a.md", "b.md"], out
    assert len(out["hits"][0]["snippet"]) == 500
    empty = format_hits([])
    assert empty["status"] == "empty" and "不要自行補答案" in empty["note"]

    # search_impl：把 embed 與連線換成假物件，驗 SQL 參數順序與回傳格式
    import asyncio

    calls = {}
    real_embed, real_conn = globals()["embed"], globals()["_conn"]
    globals()["embed"] = lambda texts: ["[0.1,0.2]" for _ in texts]

    async def fake_conn():
        async def fetch(sql, vec, k):
            calls["sql"], calls["vec"], calls["k"] = sql, vec, k
            return [{"source": "a.md", "topic": "", "content": "hit", "sim": 0.7}]

        async def close():
            calls["closed"] = True

        return SimpleNamespace(fetch=fetch, close=close)

    globals()["_conn"] = fake_conn
    try:
        res = asyncio.run(search_impl("A2A 是什麼", top_k=3))
        assert res["hits"][0]["source"] == "a.md", res
        assert calls["vec"] == "[0.1,0.2]" and calls["k"] == 3 and calls["closed"]
        assert "<=>" in calls["sql"] and "::vector" in calls["sql"]  # 少了 ::vector 會是 asyncpg 型別錯
    finally:
        globals()["embed"], globals()["_conn"] = real_embed, real_conn

    print("wiki_core self-check OK", file=sys.stderr)


if __name__ == "__main__":
    if "--self-check" in sys.argv:
        _self_check()
    else:
        print(__doc__)
