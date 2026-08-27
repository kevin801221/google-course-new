"""Lab 6 MCP server：匯率換算（tool）＋天氣查詢（tool）＋課程名詞表（resource）＋每日簡報（prompt）。

跑法：
  uv run server.py --self-check        # 不連網、不起 server，只驗工具邏輯（交付前必跑）
  uv run mcp dev server.py             # MCP Inspector，瀏覽器開 http://localhost:6274
  uv run server.py                     # stdio：給 Antigravity / Claude Code 當子行程
  MCP_TRANSPORT=http uv run server.py  # streamable-http，綁 0.0.0.0:$PORT（Lab 10 上雲沿用）

注意：stdio 模式下 stdout 是協定通道。mcp 2.x 服務期間會把 fd 1 轉去 stderr（fd 0 轉去 /dev/null）
幫你擋一手，但別靠它 —— 1.x 沒這道護欄，而且緩衝內容會在行程收尾時真的上線。log 一律 file=sys.stderr。
"""

import contextlib
import json
import os
import sys
import urllib.parse
import urllib.request
from types import SimpleNamespace

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

# 變數名只能是 mcp / server / app，`mcp dev` 只會去找這三個名字
mcp = MCPServer("course-tools")

WEATHER_API = "https://api.open-meteo.com/v1/forecast"

GLOSSARY = {
    "mcp": "Model Context Protocol：AI 的 USB-C，統一工具的發現、描述與傳輸（M6）",
    "a2a": "Agent2Agent：agent 之間互相發現與委派任務的協定，與 MCP 互補（M9）",
    "adk": "Agent Development Kit：Google 開源的 agent 開發框架，定義 agent/tool/workflow（M7）",
    "skill": "SKILL.md 封裝「怎麼做好一件事」的方法論＋腳本，教 agent 做事而非提供 API（M3）",
    "antigravity": "Google 的 agent-first 開發平台（IDE＋Agent Manager＋agy CLI）（M3）",
    "grounding": "讓模型的回答附著在可查證來源上（如 google_search）而非訓練記憶（M1）",
}


def _get_json(url: str, params: dict) -> dict:
    """GET 一個 JSON API。用 stdlib 就夠，不為一個 GET 加 httpx 依賴。"""
    req = urllib.request.Request(
        f"{url}?{urllib.parse.urlencode(params)}",
        headers={"User-Agent": "lab6-mcp/0.1"},
    )
    # ponytail: 同步阻塞 I/O；SDK 會把同步 tool 丟到 worker thread 跑，單人開發夠用。
    # 要並發打十幾個 API 再換成 async def ＋ httpx.AsyncClient。
    with contextlib.closing(urllib.request.urlopen(req, timeout=10)) as r:
        return json.loads(r.read())


@mcp.tool()
def convert_currency(amount: float, rate: float = 32.0) -> dict:
    """把美元金額換算成新台幣（TWD）。

    什麼時候用我：使用者提到美元、USD、匯率換算，或要把報價換成台幣時。
    參數：amount 是美元金額（必須 >= 0）；rate 是 1 美元兌台幣的匯率（必須 > 0，預設 32.0）。
    回傳：{"status": "success", "usd": 原金額, "twd": 換算結果, "rate": 使用的匯率}。
    注意：本工具不查即時匯率，rate 沒給就用預設值 32.0，需要精準數字請自行帶入 rate。
    """
    if amount < 0:
        raise ToolError("amount 必須 >= 0，收到的是 %r" % amount)
    if rate <= 0:
        raise ToolError("rate 必須 > 0（1 美元兌台幣），收到的是 %r" % rate)
    return {"status": "success", "usd": amount, "twd": round(amount * rate, 2), "rate": rate}


@mcp.tool()
def get_weather(lat: float, lon: float) -> dict:
    """查詢指定經緯度的即時天氣：氣溫、風速、降雨量。

    什麼時候用我：使用者問某地「現在」的天氣、氣溫、要不要帶傘時。
    參數：lat 緯度 -90~90，lon 經度 -180~180。台北約 lat=25.03, lon=121.56；
         高雄約 lat=22.62, lon=120.31；東京約 lat=35.68, lon=139.69。
    回傳：{"status": "success", "temp_c": 攝氏溫度, "wind_kmh": 風速, "precipitation_mm": 降雨量}。
    失敗時會回傳協定層錯誤，訊息會說明是參數錯還是上游 API 掛了。
    """
    if not -90 <= lat <= 90:
        raise ToolError("lat 必須在 -90~90 之間，收到的是 %r（別把經緯度寫反）" % lat)
    if not -180 <= lon <= 180:
        raise ToolError("lon 必須在 -180~180 之間，收到的是 %r" % lon)
    try:
        payload = _get_json(
            WEATHER_API,
            {
                "latitude": lat,
                "longitude": lon,
                "current": "temperature_2m,wind_speed_10m,precipitation",
            },
        )
    except Exception as e:  # 上游掛掉要讓模型看得懂，不能讓它以為是自己參數錯
        raise ToolError("open-meteo 查詢失敗（%s: %s），請稍後重試或換一組經緯度" % (type(e).__name__, e))
    cur = payload.get("current")
    if not cur:
        raise ToolError("open-meteo 回應沒有 current 欄位：%s" % json.dumps(payload)[:200])
    return {
        "status": "success",
        "temp_c": cur["temperature_2m"],
        "wind_kmh": cur["wind_speed_10m"],
        "precipitation_mm": cur["precipitation"],
    }


@mcp.resource("course://glossary/{term}")
def glossary(term: str) -> str:
    """課程名詞解釋：把 term 換成 mcp / a2a / adk / skill / antigravity / grounding。"""
    return GLOSSARY.get(term.strip().lower(), "查無此名詞：%s（可用：%s）" % (term, "、".join(GLOSSARY)))


@mcp.prompt()
def daily_briefing(city: str = "台北", usd: float = 100.0) -> str:
    """產生每日簡報提示：同時用到天氣與匯率兩個工具。"""
    return (
        f"請用 get_weather 查 {city} 現在的天氣，再用 convert_currency 把 {usd} 美元換成台幣，"
        "最後用三行繁體中文摘要：天氣一行、匯率一行、今天適不適合出門一行。"
    )


def _self_check():
    """不連網、不起 server：直接呼叫工具函式驗回傳與防呆。"""
    assert convert_currency(100) == {"status": "success", "usd": 100, "twd": 3200.0, "rate": 32.0}
    assert convert_currency(100, 31.5)["twd"] == 3150.0
    for bad in [(-1.0, 32.0), (100.0, 0.0)]:
        try:
            convert_currency(*bad)
            raise AssertionError("應該擋掉 %r" % (bad,))
        except ToolError:
            pass

    # 把 urlopen 換成假物件：驗解析與組裝，不打真 API
    fake_body = json.dumps(
        {"current": {"temperature_2m": 31.4, "wind_speed_10m": 12.0, "precipitation": 0.2}}
    ).encode()
    real_urlopen = urllib.request.urlopen
    urllib.request.urlopen = lambda *a, **k: SimpleNamespace(read=lambda: fake_body, close=lambda: None)
    try:
        assert get_weather(25.03, 121.56) == {
            "status": "success",
            "temp_c": 31.4,
            "wind_kmh": 12.0,
            "precipitation_mm": 0.2,
        }
        # 上游回傳缺 current → 要變成看得懂的 ToolError，不是 KeyError
        urllib.request.urlopen = lambda *a, **k: SimpleNamespace(read=lambda: b'{"error":true}', close=lambda: None)
        try:
            get_weather(25.03, 121.56)
            raise AssertionError("缺 current 應該報 ToolError")
        except ToolError as e:
            assert "current" in str(e)
    finally:
        urllib.request.urlopen = real_urlopen

    for bad in [(999.0, 0.0), (0.0, 999.0)]:  # 經緯度寫反/超界要在連網前就擋下
        try:
            get_weather(*bad)
            raise AssertionError("應該擋掉 %r" % (bad,))
        except ToolError:
            pass

    assert "USB-C" in glossary("MCP")  # 大小寫、空白都要吃
    assert "USB-C" in glossary(" mcp ")
    assert "查無此名詞" in glossary("blockchain")
    assert "get_weather" in daily_briefing() and "convert_currency" in daily_briefing()
    print("self-check OK", file=sys.stderr)


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
