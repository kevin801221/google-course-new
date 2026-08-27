"""服務 B：訂房 agent，用 to_a2a() 曝露成 A2A 服務。

跑法：
  uv run uvicorn hotel_service.agent:a2a_app --port 8001      # 啟動服務（要在 lab9/ 執行）
  uv run hotel_service/agent.py --self-check                  # 離線驗 search_hotels，不連網不花錢
  uv run hotel_service/agent.py --aha                         # 本地 sub-agent vs A2A 的耦合面積對照（離線）

環境變數：
  A2A_PORT=8001              名片上要寫的 port，必須跟 uvicorn --port 一致
  HOTEL_SLOW_SECONDS=0       模擬慢查詢（步驟 5 用）
  A2A_STREAMING=0            1 = 改用宣告 streaming=true 的自訂名片
"""

import asyncio
import os
import sys
import time

from google.adk.agents import Agent

# ponytail: 旅館資料寫死在這裡。Lab 8 做完 Supabase + MCP Toolbox 之後，
# 把 tools=[search_hotels] 換成 Lab 8 的 McpToolset 就是真資料，這支檔案其他部分不用改。
HOTELS = [
    {"name": "淺草和風旅館", "city": "東京", "price": 2400, "rating": 4.1, "breakfast": False},
    {"name": "上野站前商旅", "city": "東京", "price": 2900, "rating": 4.3, "breakfast": True},
    {"name": "新宿一番飯店", "city": "東京", "price": 3600, "rating": 4.5, "breakfast": True},
    {"name": "銀座半島酒店", "city": "東京", "price": 9800, "rating": 4.8, "breakfast": True},
    {"name": "難波驛前旅館", "city": "大阪", "price": 2100, "rating": 4.0, "breakfast": False},
    {"name": "梅田天空飯店", "city": "大阪", "price": 3300, "rating": 4.4, "breakfast": True},
]


def search_hotels(city: str, max_price: int) -> dict:
    """依城市與每晚預算上限（TWD）搜尋旅館，由便宜到貴排序。

    Args:
        city: 城市名，例如「東京」「大阪」。
        max_price: 每晚預算上限（TWD）。
    """
    slow = float(os.getenv("HOTEL_SLOW_SECONDS", "0"))
    if slow:
        time.sleep(slow)  # 步驟 5：讓 task 停在 WORKING 久一點
    hits = sorted(
        (h for h in HOTELS if h["city"] == city and h["price"] <= max_price),
        key=lambda h: h["price"],
    )
    return {"city": city, "max_price": max_price, "count": len(hits), "hotels": hits}


root_agent = Agent(
    model="gemini-3.7-flash",  # 型號名以課程投影片為準，若 404 用 client.models.list() 確認
    name="hotel_agent",
    # description 會被抄進 agent card 的 skill description —— 別人的 agent 靠這段決定要不要委託你
    description="訂房專員：依城市與每晚預算搜尋旅館、比價並給推薦。",
    instruction=(
        "你是訂房專員。收到旅館需求就呼叫 search_hotels，"
        "用繁體中文列出結果（名稱／每晚價格／評分／含早餐），並推薦一間說明理由。"
        "沒有符合預算的就直接說沒有，並回報最接近的價格。"
    ),
    tools=[search_hotels],
)


def _card(port: int):
    """streaming=true 的自訂名片。to_a2a 自動生的名片 capabilities.streaming 是 false。"""
    from a2a.types import AgentCapabilities
    from google.adk.a2a.utils.agent_card_builder import AgentCardBuilder

    builder = AgentCardBuilder(
        agent=root_agent,
        rpc_url=f"http://localhost:{port}/",
        capabilities=AgentCapabilities(streaming=True),
    )
    return asyncio.run(builder.build())  # 模組載入時還沒有 event loop，可以 asyncio.run


def _card_json() -> str:
    """名片序列化成伺服器會送出的那份 JSON。純離線：不用起 uvicorn、不用 key。"""
    import json

    from google.protobuf.json_format import MessageToJson

    obj = json.loads(MessageToJson(_card(A2A_PORT)))
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


A2A_PORT = int(os.getenv("A2A_PORT", "8001"))

if {"--self-check", "--aha"} & set(sys.argv):
    a2a_app = None  # 離線模式不需要 A2A app，省掉一次 experimental warning
else:
    from google.adk.a2a.utils.agent_to_a2a import to_a2a

    # port 只影響名片上寫的 URL，不會叫誰去 listen —— 跟 uvicorn --port 不一致就連不上
    a2a_app = to_a2a(
        root_agent,
        port=A2A_PORT,
        agent_card=_card(A2A_PORT) if os.getenv("A2A_STREAMING") == "1" else None,
    )


# ── 啊哈對照：同一個 agent，本地掛法 vs A2A 掛法，耦合面積差幾個數量級 ──
def _aha() -> None:
    import subprocess
    import unicodedata
    from pathlib import Path

    tty = sys.stdout.isatty()
    B, D, G, Y, R = ("\033[1m", "\033[2m", "\033[32m", "\033[33m", "\033[0m") if tty else ("",) * 5
    # 中文是全寬字算 2 格；ANSI escape 不佔格子，量寬度前要先扣掉，不然上色的欄位會排歪
    import re
    w = lambda s: sum(2 if unicodedata.east_asian_width(c) in "WF" else 1
                      for c in re.sub(r"\033\[[0-9;]*m", "", s))
    pad = lambda s, n: s + " " * max(0, n - w(s))

    card = _card_json()

    # 本地掛法的耦合面積：另起一個乾淨的 python，量「import 這支模組」拉進多少東西。
    # 注意這不是「A 的行程多載入幾個模組」——A 自己是 ADK agent，本來就載了大半（實測只多 8 個）。
    # 貴的是：這些模組與版本，本地掛法得跟服務 A 鎖在同一個 venv；A2A 掛法一個都不用。
    probe = (
        "import sys;b=set(sys.modules);sys.argv.append('--self-check');"
        "import hotel_service.agent;from pathlib import Path;"
        "n=[sys.modules[m] for m in list(sys.modules) if m not in b];"
        "f=[getattr(m,'__file__','') or '' for m in n];"
        "print(len(n),sum(Path(x).stat().st_size for x in f if x.endswith('.py')))"
    )
    out = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True,
        cwd=Path(__file__).resolve().parent.parent,
        env={**os.environ, "ADK_SUPPRESS_A2A_EXPERIMENTAL_FEATURE_WARNINGS": "1"},
    )
    mods, src = (int(x) for x in out.stdout.split()[-2:])

    k, c1, c2 = 28, 26, 24
    print(f"\n{B}[1] 服務 A 要「裝下」多少服務 B{R}   {D}（都不用 key、不連網、服務沒起來）{R}\n")
    print(f"{B}{pad('指標', k)}{pad('本地 sub_agents（Lab 7）', c1)}{pad('A2A 遠端（Lab 9）', c2)}{R}")
    print(D + "─" * (k + c1 + c2) + R)
    for name, a, b in [
        ("B 拉進來、A 得共用的模組", f"{mods} 個", f"{G}0 個{R}"),
        ("連帶鎖住的 python 原始碼", f"{src / 1e6:.1f} MB", f"{G}0{R}"),
        ("A 對 B 的全部認識", "整個 python 物件", f"名片 {len(card.encode()):,} bytes"),
        ("B 改用 Go／LangGraph 寫", f"{Y}辦不到（同 venv）{R}", f"{G}改 0 行{R}"),
        ("B 的 crash／OOM", f"{Y}同一個行程，A 一起死{R}", "A 收到 timeout=30s"),
    ]:
        print(f"{pad(name, k)}{pad(a, c1)}{b}")
    print(f"\n{'':<{k}}{B}耦合面積差 {src / len(card.encode()):,.0f}×{R} "
          f"{D}（鎖在一起的原始碼 {src / 1e6:.1f} MB ÷ 名片 {len(card.encode()):,} bytes）{R}")

    # 名片是不用認證就抓得到的公開檔案 —— 到底哪些東西會被抄上去
    print(f"\n{B}[2] 名片是公開檔案 —— 服務 B 的哪些內部細節會外流{R}\n")
    for label, needle in [
        ("instruction（system prompt）", root_agent.instruction[:10]),
        ("HOTELS 假資料的旅館名", HOTELS[0]["name"]),
        ("HOTELS 假資料的價格", str(HOTELS[0]["price"])),
        ("工具 docstring 的「Args:」整段", "Args:"),
    ]:
        leaked = needle in card
        print(f"  {Y}✗ 外流了{R}  {label}" if leaked else f"  {G}✓ 沒外流{R}  {label}")
    print(f"\n{D}名片全文 {len(card.encode()):,} bytes，"
          f"skills {card.count('\"id\"')} 個。以上全部離線算出來。{R}\n")


def _self_check() -> None:
    r = search_hotels("東京", 3000)
    assert r["count"] == 2, r
    assert [h["name"] for h in r["hotels"]] == ["淺草和風旅館", "上野站前商旅"], r
    assert search_hotels("東京", 1)["hotels"] == []          # 預算太低 → 空清單，不是 None
    assert search_hotels("京都", 99999)["count"] == 0        # 沒有的城市 → 0，不噴 KeyError
    assert root_agent.name == "hotel_agent"                  # 名片的 skill id 會用這個名字
    assert root_agent.description                            # 空的 description 名片會退成 "An ADK Agent"
    # --aha 的兩個宣稱：docstring 整段上了公開名片，instruction 沒有
    card = _card_json()
    assert "Args:" in card, card
    assert root_agent.instruction[:10] not in card, "instruction 竟然上名片了？"
    print("self-check ok")


if __name__ == "__main__":
    if "--aha" in sys.argv:
        _aha()
    elif "--self-check" in sys.argv:
        _self_check()
    else:
        print(__doc__)
