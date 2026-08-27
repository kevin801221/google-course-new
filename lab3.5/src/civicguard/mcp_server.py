"""CivicGuard MCP server（stdio）：把三個能力包成 Agent 可呼叫的工具。

注意 mcp 2.x 已把 FastMCP 改名成 MCPServer（投影片寫的是 FastMCP，那是 mcp 1.x）。

跑法：
    uv run civicguard-mcp --self-check     # 不開 server，只驗工具有註冊成功
    uv run civicguard-mcp                  # 進 stdio 模式，等 Agent 接上來
    uv run mcp dev src/civicguard/mcp_server.py    # MCP Inspector（需要 node）
"""

import asyncio
import os
import sys

from mcp.server.mcpserver import MCPServer

from civicguard import brief, cwa, shelters

# server 名稱不要含底線：工具全名是 mcp_<server>_<tool>，解析器會在 mcp_ 之後的第一個底線切開。
mcp = MCPServer("civicguard", instructions="台灣民生示警資料查詢。回答一律附上資料時間。")


@mcp.tool()
def active_alerts(city: str) -> list[dict]:
    """查某縣市目前生效的天氣特報。city 例：臺南市（注意是「臺」不是「台」）。"""
    return cwa.parse_alerts(cwa.fetch(city), city)


@mcp.tool()
def normalize_shelters(rows: list[dict]) -> list[dict]:
    """把各縣市格式不一的避難收容處所資料壓成同一個 schema（見 D-007）。"""
    return shelters.normalize_all(rows)


@mcp.tool()
def daily_brief(city: str, rain_mm: float = 0.0) -> str:
    """產出某縣市的人話版示警簡報。數值一律原始精度，不四捨五入（見 D-008）。"""
    alerts = cwa.parse_alerts(cwa.fetch(city), city)
    return brief.make_brief(city, alerts, rain_mm, [])


def _self_check() -> None:
    tools = asyncio.run(mcp.list_tools())
    names = sorted(t.name for t in tools)
    assert names == ["active_alerts", "daily_brief", "normalize_shelters"], names
    # 每個工具都要有描述，不然 Agent 不知道什麼時候該叫它
    assert all(t.description for t in tools)
    # server 名稱含底線會讓 mcp_<server>_<tool> 被切錯位
    assert "_" not in mcp.name, mcp.name
    print(f"mcp self-check ok: {names}")


def main() -> None:
    if "--self-check" in sys.argv:
        return _self_check()
    if not os.environ.get("CWA_API_KEY"):
        # stdout 是 MCP 協定通道，print() 會弄壞連線 —— 所有訊息一律走 stderr
        print("warn: 沒有 CWA_API_KEY，active_alerts 會直接失敗", file=sys.stderr)
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
