"""把 hotels.description 變成向量寫回 hotels.embedding，並提供一個語意搜尋的驗收指令。

投影片 8.5 的 ingest 是「切塊→嵌入→insert」；這裡的資料已經在表裡了，
所以是「select 沒向量的列→批次嵌入→update」。省一次 API 呼叫的錢，也不會種出重複資料。

跑法：
  uv run seed_embeddings.py --self-check          # 離線，不連網不花錢
  uv run seed_embeddings.py --aha                 # 啊哈 demo：同庫 vs 專用向量庫（離線）
  uv run seed_embeddings.py                       # 真的呼叫 embedding API + 寫回 Supabase
  uv run seed_embeddings.py --search "想泡溫泉"    # 語意搜尋，驗收 pgvector 真的通了
需要：export GEMINI_API_KEY=... 與 export DB_URL_RAW="postgresql://postgres.<ref>:<pw>@...:5432/postgres"
"""
import asyncio
import os
import sys
import unicodedata
from types import SimpleNamespace

MODEL = "gemini-embedding-2"   # 型號名以課程投影片為準；若 404 用 client.models.list() 確認
DIM = 1536                     # 對齊 schema.sql 的 vector(1536)（Matryoshka 截斷）
SEARCH_SQL = (
    "select name, city, price_twd, rating, "
    "       1 - (embedding <=> $1::vector) as sim "
    "from hotels where embedding is not null "
    "order by embedding <=> $1::vector limit 3"
)


# ── 啊哈 demo：資料與向量同庫 vs 專用向量庫（離線，不連網不花錢）──────────
# 四個示意軸：[溫泉, 安靜, 近車站, 便宜]。這是手寫的教學向量，不是真 embedding —— 但
# 排序公式與 pgvector 的 <=> 完全一樣（餘弦），所以「誰排前面」的邏輯是真的。
AXES = "溫泉 安靜 近車站 便宜"
FAKE = [
    # name, city, price, [溫泉, 安靜, 近車站, 便宜]
    ("Sakura Inn", "Tokyo", 2800, [0.1, 0.8, 0.9, 0.5]),
    ("Shibuya Stay", "Tokyo", 4200, [0.1, 0.2, 0.8, 0.2]),
    ("Ueno Capsule", "Tokyo", 1200, [0.0, 0.1, 0.8, 1.0]),
    ("Ginza Grand", "Tokyo", 6800, [1.0, 0.7, 0.6, 0.0]),
    ("Osaka Base", "Osaka", 1900, [0.0, 0.2, 0.8, 0.9]),
    ("Namba Family", "Osaka", 3600, [0.0, 0.1, 0.7, 0.4]),
    ("Kyoto Machiya", "Kyoto", 5200, [0.3, 1.0, 0.2, 0.1]),
    ("Kyoto Station Hub", "Kyoto", 2400, [0.0, 0.3, 1.0, 0.7]),
    ("Sapporo Snow", "Sapporo", 3100, [0.4, 0.5, 0.5, 0.5]),
    ("Taipei Riverside", "Taipei", 2200, [0.0, 0.4, 0.8, 0.6]),
]
QUERY_VEC = [1.0, 1.0, 0.0, 0.0]        # 「想泡溫泉又安靜」
HARD = {"city": "Tokyo", "max_price": 3000}
TOPK = 3


def cos_sim(a, b):
    """1 - (a <=> b)：pgvector 的餘弦距離換成相似度，公式跟資料庫裡那個運算子同一條。"""
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    return dot / (na * nb) if na and nb else 0.0


def rank(rows, k=None):
    """order by embedding <=> $1 limit k 的純 Python 版。"""
    out = sorted(((cos_sim(v, QUERY_VEC), n, c, p) for n, c, p, v in rows), reverse=True)
    return out[:k] if k else out


def ok(city, price):
    return city == HARD["city"] and price <= HARD["max_price"]


def aha():
    C, D, G, R, Z = (("\033[36m", "\033[2m", "\033[32m", "\033[31m", "\033[0m")
                     if sys.stdout.isatty() else ("",) * 5)

    def line(t):
        s, n, c, p = t
        mark = f"{G}✓{Z}" if ok(c, p) else f"{R}✗{Z}"
        return f"    {mark} sim={s:.3f}  {n:<18} {c:<8} NT${p}"

    print(f'{C}問題{Z} 東京 3000 以內，想泡溫泉又安靜   {D}（示意向量，軸＝{AXES}）{Z}')

    print(f"\n{C}[A] 專用向量庫：向量在 A 服務、city/price 在 B 資料庫 → 先向量 top-{TOPK}，"
          f"撈回應用層再過濾{Z}")
    a_top = rank(FAKE, TOPK)
    for t in a_top:
        print(line(t))
    a_hit = [t for t in a_top if ok(t[2], t[3])]
    print(f"    {D}過濾後剩 {len(a_hit)} 筆{Z}")

    print(f"\n{C}[B] pgvector 同庫：一句 SQL，WHERE 先過濾、ORDER BY 再語意排序{Z}")
    b_top = rank([r for r in FAKE if ok(r[1], r[2])], TOPK)
    for t in b_top:
        print(line(t))

    missed = [t[1] for t in b_top if t[1] not in {x[1] for x in a_top}]
    need_k = next(i + 1 for i, t in enumerate(rank(FAKE)) if ok(t[2], t[3]))
    rows = [("查詢次數", "2（向量庫＋DB）", "1"),
            ("往返", "2 次網路", "1 次"),
            (f"top-{TOPK} 之後的合格旅館", f"{len(a_hit)} 筆", f"{len(b_top)} 筆"),
            ("漏掉的", "、".join(missed) or "—", "—"),
            ("k 要開多大才撈得到 1 筆", f"{need_k}（才 10 筆資料）", f"{TOPK}（過濾在 SQL 裡）")]
    k = max(_w(r[0]) for r in rows) + 2
    print(f"\n{_pad('指標', k)}{_pad('專用向量庫（兩段式）', 26)}pgvector 同庫")
    print(D + "─" * (k + 48) + Z)
    for name, x, y in rows:
        print(f"{_pad(name, k)}{_pad(x, 26)}{y}")
    print(f"\n{D}[B] 的 SQL 就是這一句 —— 這就是全部的 RAG：{Z}\n"
          f"    select name, 1 - (embedding <=> $1::vector) as sim from hotels\n"
          f"    where city = $2 and price_twd <= $3 and embedding is not null\n"
          f"    order by embedding <=> $1::vector limit {TOPK}")


def _w(s):
    """中文全寬字算 2 格，表格才不會歪。"""
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in s)


def _pad(s, n):
    return s + " " * max(0, n - _w(s))


def to_vector(values, dim=DIM):
    """float 陣列 → pgvector 吃的文字格式 '[0.1,0.2,...]'，順手擋維度不對。"""
    values = list(values)
    if len(values) != dim:
        raise ValueError(f"維度是 {len(values)}，但 schema 是 vector({dim})："
                         f"config 少給 output_dimensionality 就會拿到 3072 維")
    return "[" + ",".join(repr(float(v)) for v in values) + "]"


def embed_text(row):
    """要被嵌入的文字。名稱與城市一起餵進去，問「東京便宜的旅館」才搜得到。"""
    tags = "、".join(row["tags"] or [])
    return f'{row["name"]}（{row["city"]}，NT${row["price_twd"]}，標籤：{tags}）：{row["description"]}'


def build_updates(rows, res):
    """(rows, embedding 回應) → executemany 的參數清單。順序靠 zip，不要自己算 index。"""
    if len(res.embeddings) != len(rows):
        raise ValueError(f"要 {len(rows)} 個向量卻拿到 {len(res.embeddings)} 個")
    return [(row["id"], to_vector(e.values)) for row, e in zip(rows, res.embeddings)]


def embed(contents):
    from google import genai
    with genai.Client() as client:      # 不用 with 會被 GC 關掉 → client has been closed
        return client.models.embed_content(
            model=MODEL, contents=contents,
            config={"output_dimensionality": DIM})


async def seed():
    import asyncpg
    conn = await asyncpg.connect(os.environ["DB_URL_RAW"])
    rows = await conn.fetch("select id, name, city, price_twd, tags, description from hotels "
                            "where description is not null and embedding is null order by id")
    if not rows:
        print("沒有需要嵌入的列（都嵌過了）")
    else:
        # ponytail: 一次全撈，資料量是 10 筆等級。上千筆要分批（一次 100）避免 payload 過大
        res = embed([embed_text(r) for r in rows])
        await conn.executemany("update hotels set embedding = $2::vector where id = $1",
                               build_updates(rows, res))
        print(f"寫回 {len(rows)} 筆向量：" + "、".join(r["name"] for r in rows))
    print("尚未嵌入的列：", await conn.fetchval("select count(*) from hotels where embedding is null"))
    await conn.close()


async def search(query):
    import asyncpg
    vec = to_vector(embed(query).embeddings[0].values)
    conn = await asyncpg.connect(os.environ["DB_URL_RAW"])
    for r in await conn.fetch(SEARCH_SQL, vec):
        print(f'{r["sim"]:.3f}  {r["name"]:<20} {r["city"]:<8} NT${r["price_twd"]} ★{r["rating"]}')
    await conn.close()


def self_check():
    assert to_vector([0.5] * DIM).startswith("[0.5,0.5")
    assert to_vector([0.5] * DIM).count(",") == DIM - 1
    try:
        to_vector([0.1, 0.2, 0.3])          # 忘了 output_dimensionality 的下場
    except ValueError as e:
        assert "vector(1536)" in str(e), e
    else:
        raise AssertionError("維度不對居然沒擋下來")

    row = {"id": 7, "name": "Ginza Grand", "city": "Tokyo", "price_twd": 6800,
           "tags": ["五星", "溫泉"], "description": "頂樓有溫泉。"}
    txt = embed_text(row)
    assert "Ginza Grand" in txt and "Tokyo" in txt and "溫泉" in txt and "6800" in txt, txt
    assert embed_text({**row, "tags": None})                      # tags 是 NULL 也不能炸

    fake = SimpleNamespace(embeddings=[SimpleNamespace(values=[0.1] * DIM)])
    assert build_updates([row], fake) == [(7, to_vector([0.1] * DIM))]
    try:
        build_updates([row, row], fake)      # 回傳數量對不上就別寫進資料庫
    except ValueError as e:
        assert "拿到 1 個" in str(e), e
    else:
        raise AssertionError("數量不符居然沒擋下來")

    assert SEARCH_SQL.count("$1::vector") == 2   # 少了 ::vector，asyncpg 不認得 pgvector 型別

    # aha demo：同庫過濾一定不會比兩段式漏
    assert abs(cos_sim(QUERY_VEC, QUERY_VEC) - 1.0) < 1e-9
    assert cos_sim([1.0, 0, 0, 0], [0, 1.0, 0, 0]) == 0.0
    assert [t for t in rank(FAKE, TOPK) if ok(t[2], t[3])] == [], "兩段式在 top-3 應該全被過濾掉"
    assert rank([r for r in FAKE if ok(r[1], r[2])], TOPK)[0][1] == "Sakura Inn"
    assert _w("溫泉") == 4 and _pad("溫泉", 6) == "溫泉  "
    print("self-check ok")


if __name__ == "__main__":
    if "--self-check" in sys.argv:
        self_check()
    elif "--aha" in sys.argv:
        aha()
    elif "--search" in sys.argv:
        asyncio.run(search(sys.argv[sys.argv.index("--search") + 1]))
    else:
        asyncio.run(seed())
