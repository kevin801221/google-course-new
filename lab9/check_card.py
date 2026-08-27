"""抓 A2A agent card、列出 skills，並先跑一遍 ADK 會做的 origin 檢查。

只用標準庫，不需要 adk / a2a-sdk。

跑法：
  uv run check_card.py                          # 預設 http://localhost:8001
  uv run check_card.py http://127.0.0.1:8001    # 故意用錯 host，看 origin 檢查抓到
  uv run check_card.py --self-check             # 離線驗解析邏輯，不連網
"""

import json
import sys
import urllib.error
import urllib.request
from urllib.parse import urlparse

WELL_KNOWN = "/.well-known/agent-card.json"
DEFAULT_PORTS = {"http": 80, "https": 443}


def card_url(base: str) -> str:
    return base.rstrip("/") + WELL_KNOWN


def origin(url: str) -> tuple:
    p = urlparse(url)
    return (p.scheme.lower(), (p.hostname or "").lower(), p.port or DEFAULT_PORTS.get(p.scheme.lower()))


def is_loopback(host: str) -> bool:
    h = (host or "").strip("[]").lower()
    return h == "localhost" or h.endswith(".localhost") or h.startswith("127.") or h == "::1"


def rpc_urls(card: dict) -> list:
    """名片上宣告的 RPC URL。注意 JSON 是 camelCase，不是 Python 的 snake_case。"""
    urls = [i["url"] for i in card.get("supportedInterfaces") or [] if i.get("url")]
    if not urls and card.get("url"):
        urls.append(card["url"])  # 0.x 舊名片把 url 放在頂層
    return urls


def problems(source_url: str, card: dict) -> list:
    """回傳 ADK 會拿來拒絕連線的理由，空清單 = 過關。"""
    out = []
    urls = rpc_urls(card)
    if not urls:
        return ["名片沒有任何 RPC URL（supportedInterfaces 是空的）"]
    src = origin(source_url)
    for u in urls:
        o = origin(u)
        if o[0] != "https" and not is_loopback(o[1]):
            out.append(f"RPC URL 非 https 又不是 loopback：{u}")
        if o != src:
            out.append(f"origin 不一致：名片寫 {u}（{o}），但你是從 {src} 抓到名片的")
    return out


def fetch(base: str) -> tuple:
    url = card_url(base)
    with urllib.request.urlopen(url, timeout=10) as r:
        return url, json.load(r)


def report(source_url: str, card: dict) -> int:
    print(f"名片來源  {source_url}")
    print(f"agent     {card.get('name')}  v{card.get('version')}")
    print(f"描述      {card.get('description')}")
    caps = card.get("capabilities") or {}
    print(f"streaming {caps.get('streaming', False)}   push {caps.get('pushNotifications', False)}")
    for u in rpc_urls(card):
        print(f"RPC       {u}")
    for s in card.get("skills") or []:
        print(f"  - skill {s.get('id')}  [{','.join(s.get('tags') or [])}]  {s.get('description')}")
    errs = problems(source_url, card)
    for e in errs:
        print(f"✗ {e}")
    print("✓ 名片可用" if not errs else "✗ ADK 會用 AgentCardResolutionError 拒絕這張名片")
    return 1 if errs else 0


def _self_check() -> None:
    assert card_url("http://localhost:8001/") == "http://localhost:8001/.well-known/agent-card.json"
    good = {
        "name": "hotel_agent",
        "version": "0.0.1",
        "capabilities": {"streaming": False},
        "supportedInterfaces": [{"url": "http://localhost:8001", "protocolBinding": "JSONRPC"}],
        "skills": [{"id": "hotel_agent", "tags": ["llm"], "description": "訂房專員"}],
    }
    src = card_url("http://localhost:8001")
    assert problems(src, good) == [], problems(src, good)
    # 從 127.0.0.1 抓到一張寫 localhost 的名片 → origin 不一致
    bad = problems(card_url("http://127.0.0.1:8001"), good)
    assert len(bad) == 1 and "origin 不一致" in bad[0], bad
    # port 打錯（uvicorn --port 8002 但 to_a2a(port=8001)）
    bad = problems(card_url("http://localhost:8002"), good)
    assert len(bad) == 1 and "origin 不一致" in bad[0], bad
    # 遠端主機用 http → 被擋（Cloud Run 一定要 https）
    remote = {**good, "supportedInterfaces": [{"url": "http://booking.example.com"}]}
    assert any("非 https" in p for p in problems("http://booking.example.com" + WELL_KNOWN, remote))
    # 舊版名片把 url 放頂層
    assert rpc_urls({"url": "http://localhost:8001"}) == ["http://localhost:8001"]
    assert rpc_urls({}) == [] and problems(src, {}) == ["名片沒有任何 RPC URL（supportedInterfaces 是空的）"]
    # capabilities 缺 key 不能炸（proto3 的 false 欄位不會出現在 JSON 裡）
    assert report(src, {**good, "capabilities": {}}) == 0
    print("self-check ok")


if __name__ == "__main__":
    if "--self-check" in sys.argv:
        _self_check()
        sys.exit(0)
    base = next((a for a in sys.argv[1:] if not a.startswith("-")), "http://localhost:8001")
    try:
        src, card = fetch(base)
    except urllib.error.HTTPError as e:
        sys.exit(f"✗ {card_url(base)} 回 HTTP {e.code} —— 服務在跑但這個路徑沒有名片：base URL 多了斜線或路徑？to_a2a 用了 rpc_path 前綴？")
    except OSError as e:
        sys.exit(f"✗ 連不上 {card_url(base)}：{e} —— 服務 B 沒在跑，或 port 不對")
    sys.exit(report(src, card))
