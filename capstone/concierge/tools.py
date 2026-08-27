"""concierge 用的兩個自製工具：查知識庫、把網頁存進知識庫。實作在 ../wiki_core.py，這裡只負責「講給模型聽」。

跑法：
  uv run python -m concierge.tools --self-check     # 離線，不連網不花錢（要在 capstone/ 執行）
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # 讓 wiki_core 可 import

import wiki_core


async def search_knowledge(query: str, top_k: int = 5) -> dict:
    """搜尋個人知識庫（pgvector），回傳最相關的段落與來源。

    什麼時候用我：使用者問「我知識庫裡…」「我之前存的…」「我讀過的資料怎麼說」時，一律先用我。
    參數：query 是使用者的問題原文（不要自己改寫成關鍵字）；top_k 是要幾段，預設 5，最多 20。
    回傳：{"status": "success"|"empty"|"error", "hits": [{source, topic, snippet, score}], "note": ...}。
    status 是 empty 代表知識庫真的沒有 —— 直接告訴使用者查無資料，不要用你自己的記憶回答。
    """
    top_k = max(1, min(int(top_k), 20))
    try:
        return await wiki_core.search_impl(query, top_k)
    except Exception as e:  # DB 掛了要讓模型看得懂，不然它會以為是自己參數錯然後重試到死
        return {"status": "error", "message": f"知識庫查詢失敗（{type(e).__name__}: {e}）", "hits": []}


async def ingest_document(url: str, topic: str = "") -> dict:
    """把一個網址的內容抓下來、切塊、embed，存進個人知識庫。

    什麼時候用我：使用者明確說「存起來」「加進知識庫」「記下這篇」時才用；只是問問題不要用我。
    參數：url 是完整網址（要有 http/https）；topic 是分類標籤，例如 protocol、gcp、reading。
    回傳：{"status": "success", "chunks": 寫入的段數} 或 {"status": "error", "message": ...}。
    """
    if not url.startswith("http"):
        return {"status": "error", "message": f"url 要是 http(s) 開頭的完整網址，收到的是 {url!r}"}
    try:
        return await wiki_core.ingest_impl(url, topic)
    except Exception as e:
        return {"status": "error", "message": f"入庫失敗（{type(e).__name__}: {e}）"}


def _self_check() -> None:
    import asyncio
    from types import SimpleNamespace

    real = (wiki_core.search_impl, wiki_core.ingest_impl)
    seen = {}

    async def fake_search(q, k):
        seen["q"], seen["k"] = q, k
        return {"status": "success", "hits": [{"source": "a.md"}]}

    async def fake_ingest(u, t):
        return {"status": "success", "source": u, "topic": t, "chunks": 3}

    wiki_core.search_impl, wiki_core.ingest_impl = fake_search, fake_ingest
    try:
        assert asyncio.run(search_knowledge("A2A 是什麼"))["hits"][0]["source"] == "a.md"
        assert seen["k"] == 5  # 預設值
        asyncio.run(search_knowledge("x", top_k=99))
        assert seen["k"] == 20, seen  # 上限要夾住，不然模型會一次撈 1000 段把 context 撐爆
        asyncio.run(search_knowledge("x", top_k=0))
        assert seen["k"] == 1
        assert asyncio.run(ingest_document("https://a2a-protocol.org", "proto"))["chunks"] == 3
        bad = asyncio.run(ingest_document("a2a-protocol.org"))
        assert bad["status"] == "error" and "http" in bad["message"], bad

        # DB 掛掉：要變成 status=error 的字典，不能讓 exception 冒到 ADK 的 tool runner
        async def boom(*a, **k):
            raise RuntimeError("connection refused")

        wiki_core.search_impl = boom
        res = asyncio.run(search_knowledge("x"))
        assert res["status"] == "error" and "RuntimeError" in res["message"], res
    finally:
        wiki_core.search_impl, wiki_core.ingest_impl = real

    # 工具的 docstring 就是模型的說明書：ADK 只會把 docstring 送進 schema，缺了模型就不知道何時該用
    for f in (search_knowledge, ingest_document):
        assert f.__doc__ and "什麼時候用我" in f.__doc__ and "參數" in f.__doc__, f.__name__

    print("tools self-check OK", file=sys.stderr)


if __name__ == "__main__":
    if "--self-check" in sys.argv:
        _self_check()
