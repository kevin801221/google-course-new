"""加分題 A：pgvector 語意搜尋，包成一個 ADK FunctionTool（投影片 8.5 的 search_knowledge 套在 hotels 上）。

Toolbox 的 SQL 工具負責「城市＋預算」這種結構化條件；這支負責「想泡溫泉、房間安靜」這種說不清的需求。
跑法（離線）：uv run python hotel_agent/rag_tool.py --self-check
"""
import decimal
import os
import sys

# 與 seed_embeddings.py 的 SEARCH_SQL 是同一句（那邊 limit 3 給人看、這邊 limit 5 給模型看）。
# 教材刻意各留一份，不做跨目錄 import。
SEARCH_SQL = (
    "select name, city, price_twd, rating, description, "
    "       1 - (embedding <=> $1::vector) as sim "
    "from hotels where embedding is not null "
    "order by embedding <=> $1::vector limit 5"
)


def jsonable(row):
    """asyncpg Record → 可 JSON 序列化的 dict。

    numeric 欄位（rating）回來是 Decimal，直接丟給 ADK 會炸
    TypeError: Object of type Decimal is not JSON serializable。
    Toolbox 幫你處理掉了，自己寫 FunctionTool 就得自己處理。
    """
    return {k: float(v) if isinstance(v, decimal.Decimal) else v for k, v in dict(row).items()}


async def search_hotels_semantic(query: str) -> dict:
    """用自然語言描述搜尋旅館（語意搜尋），適合說不出明確條件的需求。

    Args:
        query: 使用者對旅館的描述，例如「想泡溫泉又離車站近」。
    """
    # ponytail: 每次呼叫開一條新連線，免費層連線少時會吃緊；要撐流量換成模組層 asyncpg.create_pool()
    import asyncpg
    from google import genai
    with genai.Client() as client:
        emb = client.models.embed_content(
            model="gemini-embedding-2", contents=query,
            config={"output_dimensionality": 1536})
    vec = "[" + ",".join(repr(float(v)) for v in emb.embeddings[0].values) + "]"
    conn = await asyncpg.connect(os.environ["DB_URL_RAW"])
    try:
        rows = await conn.fetch(SEARCH_SQL, vec)
    finally:
        await conn.close()
    return {"status": "success", "hotels": [jsonable(r) for r in rows]}


if __name__ == "__main__":
    assert "--self-check" in sys.argv, __doc__
    import json
    row = {"name": "Ginza Grand", "rating": decimal.Decimal("4.8"), "sim": decimal.Decimal("0.87")}
    out = jsonable(row)
    assert out["rating"] == 4.8 and isinstance(out["rating"], float), out
    json.dumps(out)                                    # 沒有這行的保護就等著在 adk web 裡看紅字
    assert SEARCH_SQL.count("$1::vector") == 2         # 少 ::vector：asyncpg 不認得 pgvector 型別
    assert "embedding is not null" in SEARCH_SQL       # 沒種向量的列會排在最前面污染結果
    assert search_hotels_semantic.__doc__.strip().startswith("用自然語言")   # docstring 就是模型看的工具說明
    print("self-check ok")
