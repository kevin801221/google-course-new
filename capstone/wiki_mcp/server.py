"""Phase 3 wiki-mcp：把 Capstone 的知識庫能力曝露成 MCP server（Antigravity／Claude／自己的 agent 都能用）。

跑法（在 capstone/ 執行）：
  uv run wiki_mcp/server.py --self-check                    # 離線驗工具邏輯與權限閘，不連網不花錢
  uv run mcp dev wiki_mcp/server.py                         # MCP Inspector，瀏覽器開 http://localhost:6274
  uv run wiki_mcp/server.py                                 # stdio：給本機 host 當子行程
  MCP_TRANSPORT=http uv run wiki_mcp/server.py              # streamable-http，綁 0.0.0.0:$PORT（上 Cloud Run 用）

環境變數：
  DATABASE_URL         Supabase Session pooler（5432）
  WIKI_ALLOW_INGEST    1=允許寫入（concierge 的 SA 專用服務才設）；預設 0，唯讀
  MCP_TRANSPORT        http=streamable-http；其他=stdio

注意：stdio 模式下 stdout 是協定通道，任何 print() 都會弄壞連線 —— log 一律 file=sys.stderr。
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # 讓 wiki_core 可 import

import wiki_core
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

mcp = MCPServer("personal-wiki")  # 變數名只能是 mcp / server / app，`mcp dev` 只找這三個


def ingest_allowed() -> bool:
    """權限矩陣（投影片 441）：wiki_search 人人可用，wiki_ingest 只給 concierge 的 SA。"""
    return os.getenv("WIKI_ALLOW_INGEST", "0") == "1"


@mcp.tool()
async def wiki_search(query: str, top_k: int = 5) -> dict:
    """搜尋個人知識庫，回傳最相關的段落與來源。

    什麼時候用我：使用者問「我知識庫裡…」「我之前存過的…」，或需要引用他自己的筆記時。
    參數：query 是問題原文；top_k 要幾段，預設 5，上限 20。
    回傳：{"status": "success"|"empty", "hits": [{source, topic, snippet, score}], "note": ...}。
    status=empty 代表庫裡真的沒有，請直接回覆查無資料，不要自行補答案。
    """
    if not query.strip():
        raise ToolError("query 不能是空字串")
    try:
        return await wiki_core.search_impl(query, max(1, min(int(top_k), 20)))
    except Exception as e:
        raise ToolError(f"知識庫查詢失敗（{type(e).__name__}: {e}）—— 檢查 DATABASE_URL 與 documents 表")


@mcp.tool()
async def wiki_ingest(url: str, topic: str = "") -> dict:
    """把網頁內容抓取、切塊、embed 後存入知識庫（寫入操作，需要授權）。

    什麼時候用我：使用者明確說「存起來」「加進知識庫」時。
    參數：url 完整網址（http/https）；topic 分類標籤，例如 protocol、gcp、reading。
    回傳：{"status": "success", "chunks": 寫入段數}。
    """
    if not ingest_allowed():
        raise ToolError("這個 wiki-mcp 是唯讀部署（WIKI_ALLOW_INGEST=0）。入庫請走 concierge 的 wiki_agent")
    if not url.startswith("http"):
        raise ToolError(f"url 要 http(s) 開頭，收到的是 {url!r}")
    try:
        return await wiki_core.ingest_impl(url, topic)
    except Exception as e:
        raise ToolError(f"入庫失敗（{type(e).__name__}: {e}）")


@mcp.resource("wiki://stats")
async def stats() -> str:
    """知識庫統計：文件塊數、來源數、最近更新時間。"""
    try:
        return await wiki_core.stats_impl()
    except Exception as e:
        return f"統計查詢失敗（{type(e).__name__}: {e}）"


def _self_check() -> None:
    import asyncio

    real = (wiki_core.search_impl, wiki_core.ingest_impl, wiki_core.stats_impl)

    async def fake_search(q, k):
        return {"status": "success", "hits": [{"source": "a.md", "score": 0.8}], "note": "n", "k": k}

    async def fake_ingest(u, t):
        return {"status": "success", "source": u, "topic": t, "chunks": 2}

    async def fake_stats():
        return "文件塊數：42｜來源數：7｜最近更新：2026-08-26"

    wiki_core.search_impl, wiki_core.ingest_impl, wiki_core.stats_impl = fake_search, fake_ingest, fake_stats
    try:
        assert asyncio.run(wiki_search("A2A"))["hits"][0]["source"] == "a.md"
        assert asyncio.run(wiki_search("A2A", top_k=99))["k"] == 20  # 夾住上限，避免撐爆 host 的 context
        for bad in ["", "   "]:
            try:
                asyncio.run(wiki_search(bad))
                raise AssertionError("空 query 應該擋掉")
            except ToolError:
                pass

        # 預設唯讀：wiki_ingest 要被權限閘擋下
        os.environ.pop("WIKI_ALLOW_INGEST", None)
        try:
            asyncio.run(wiki_ingest("https://x.dev"))
            raise AssertionError("唯讀部署應該擋掉 wiki_ingest")
        except ToolError as e:
            assert "唯讀" in str(e), e

        os.environ["WIKI_ALLOW_INGEST"] = "1"
        assert asyncio.run(wiki_ingest("https://x.dev", "proto"))["chunks"] == 2
        try:
            asyncio.run(wiki_ingest("x.dev"))
            raise AssertionError("非 http 應該擋掉")
        except ToolError as e:
            assert "http" in str(e), e

        assert "文件塊數" in asyncio.run(stats())
        # DB 掛掉時 resource 不能拋例外（host 會直接斷線），要回可讀的字串
        wiki_core.stats_impl = lambda: (_ for _ in ()).throw(RuntimeError("boom"))
        assert "統計查詢失敗" in asyncio.run(stats())
    finally:
        wiki_core.search_impl, wiki_core.ingest_impl, wiki_core.stats_impl = real
        os.environ.pop("WIKI_ALLOW_INGEST", None)

    for f in (wiki_search, wiki_ingest):
        doc = getattr(f, "__doc__", "") or ""
        assert "什麼時候用我" in doc and "參數" in doc, f  # docstring 就是模型的說明書

    print("wiki-mcp self-check OK", file=sys.stderr)


if __name__ == "__main__":
    if "--self-check" in sys.argv:
        _self_check()
    elif os.getenv("MCP_TRANSPORT") == "http":
        # 2026-07-28 規格是無狀態的：stateless_http=True 才能在 Cloud Run 上水平擴展
        mcp.run(
            transport="streamable-http",
            host="0.0.0.0",
            port=int(os.getenv("PORT", 8080)),
            json_response=True,
            stateless_http=True,
        )
    else:
        mcp.run()  # 預設 stdio
