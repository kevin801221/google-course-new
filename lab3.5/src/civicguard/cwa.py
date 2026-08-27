"""CivicGuard：中央氣象署天氣特報查詢（stdlib only，不裝 httpx 也能跑）。

跑法：
    uv run civicguard-fetch --self-check                   # 離線驗 parse 邏輯
    uv run civicguard-fetch --city 臺南市                   # 真的打 API，需 CWA_API_KEY
    uv run civicguard-fetch --city 台南市 --from-file data/today.json
"""

import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path

# 特報 dataset：天氣警特報-各縣市地區天氣警特報。id 以投影片為準，404 就去 opendata.cwa.gov.tw 查。
DATASET = "W-C0033-001"
BASE = "https://opendata.cwa.gov.tw/api/v1/rest/datastore/"


def fetch(city: str, api_key: str | None = None, timeout: int = 20) -> dict:
    """打 CWA open data，回傳原始 JSON dict。city 打「台」會自動正規化成「臺」。"""
    city = city.replace("台", "臺")          # 官方資料一律用「臺」，打「台」會安靜地拿到 0 筆
    key = api_key or os.environ.get("CWA_API_KEY")
    if not key:
        sys.exit("缺 CWA_API_KEY。到 https://opendata.cwa.gov.tw 註冊拿一把，再 export CWA_API_KEY=...")
    qs = urllib.parse.urlencode({"Authorization": key, "locationName": city})
    with urllib.request.urlopen(f"{BASE}{DATASET}?{qs}", timeout=timeout) as r:
        return json.load(r)


def parse_alerts(payload: dict, city: str) -> list[dict]:
    """從回應撈出某縣市目前生效的特報，回傳扁平 dict list。

    地雷：2024 年後欄位由 records.location 改名為 records.Locations（大寫 L、複數），
    舊欄位仍存在但恆為空陣列 —— 讀舊名不會報錯，只會安靜地拿到 0 筆。
    地雷二：官方 locationName 用「臺」，使用者一定會打「台」，所以先正規化再比對。
    """
    city = city.replace("台", "臺")
    recs = payload.get("records") or {}
    groups = recs.get("Locations") or recs.get("location") or []
    out = []
    for g in groups:
        # 有的回應把縣市包一層 Locations[].Location[]，有的直接就是地點清單
        for loc in g.get("Location") or [g]:
            if city not in (loc.get("locationName") or ""):
                continue
            for hz in (loc.get("hazardConditions") or {}).get("hazards") or []:
                info = hz.get("info") or {}
                vt = hz.get("validTime") or {}
                out.append({
                    "city": loc["locationName"],
                    "phenomena": info.get("phenomena") or "",
                    "significance": info.get("significance") or "",
                    "start": vt.get("startTime") or "",
                    "end": vt.get("endTime") or "",
                })
    return out


def _self_check() -> None:
    # 真實回應的縮小版：新欄位 Locations 有料，舊欄位 location 存在但是空的
    payload = {"records": {
        "location": [],
        "Locations": [{"Location": [
            {"locationName": "臺南市", "hazardConditions": {"hazards": [
                {"info": {"phenomena": "大雨", "significance": "特報"},
                 "validTime": {"startTime": "2026-08-26 08:00:00", "endTime": "2026-08-26 20:00:00"}}]}},
            {"locationName": "高雄市", "hazardConditions": {"hazards": []}},
        ]}],
    }}
    got = parse_alerts(payload, "臺南市")
    assert len(got) == 1, f"讀到 {len(got)} 筆，預期 1 筆 —— 是不是還在讀 records.location？"
    assert got[0]["phenomena"] == "大雨"
    assert parse_alerts(payload, "台南市") == got          # 打「台」也要中（官方資料是「臺」）
    assert parse_alerts(payload, "高雄市") == []          # 有地點但沒特報
    assert parse_alerts({}, "臺南市") == []                # 空回應不能炸
    assert parse_alerts({"records": {}}, "臺南市") == []
    print("cwa self-check ok")


def main() -> None:
    if "--self-check" in sys.argv:
        return _self_check()
    argv = sys.argv[1:]
    city = argv[argv.index("--city") + 1] if "--city" in argv else "臺南市"
    if "--from-file" in argv:
        payload = json.loads(Path(argv[argv.index("--from-file") + 1]).read_text(encoding="utf-8"))
    else:
        payload = fetch(city)
    alerts = parse_alerts(payload, city)
    print(json.dumps(alerts, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
