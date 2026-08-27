"""CivicGuard：把特報 + 雨量 + 避難所壓成一段人話簡報。

分級規則見 docs/domain/alert-taxonomy.md；D-008 規定數值一律以原始精度輸出，
分級判斷也用原始值 —— 不准四捨五入。

跑法：
    uv run civicguard-brief --self-check
    uv run civicguard-brief --city 臺南市 --rain 79.9
"""

import sys

# (門檻 mm/24h, 等級名)。由大到小比，第一個成立的就是答案。
RAIN_LEVELS = ((350.0, "超大豪雨"), (200.0, "大豪雨"), (80.0, "豪雨"), (40.0, "大雨"), (0.0, "無"))


def rain_level(mm: float) -> str:
    """雨量分級。用原始值比較，不做四捨五入（D-008）。"""
    return next(name for t, name in RAIN_LEVELS if mm >= t)


def make_brief(city: str, alerts: list[dict], rain_mm: float, shelters: list[dict]) -> str:
    """回傳 150 字內的簡報字串，第一句就是結論。"""
    lv = rain_level(rain_mm)
    head = f"{city}目前無生效特報，維持正常作息。" if not alerts else \
        f"{city}目前有{'、'.join(dict.fromkeys(a['phenomena'] for a in alerts))}特報，請提高警覺。"
    # 用 repr-free 的原始字串印雨量：79.9 就是 79.9，不會變成 80
    body = f"近 24 小時累積雨量 {rain_mm} 毫米（{lv}級）。"
    if shelters:
        s = shelters[0]
        body += f"最近的避難收容處所：{s['name']}（{s['district']}，{s['address']}）。"
    return head + body


def _self_check() -> None:
    # 1) 分級門檻用原始值：79.9 不能被進位成 80 而跨級
    assert rain_level(79.9) == "大雨", rain_level(79.9)
    assert rain_level(80.0) == "豪雨"
    assert rain_level(0) == "無"
    # 2) 原始精度必須出現在文案裡（D-008 的回歸測試）
    txt = make_brief("臺南市", [{"phenomena": "大雨"}], 79.9, [])
    assert "79.9" in txt and "80" not in txt, txt
    assert txt.startswith("臺南市目前有大雨特報")
    # 3) 沒特報時要講「無」，不能空字串
    assert "無生效特報" in make_brief("高雄市", [], 3.5, [])
    # 4) 同一種現象出現兩次只講一次
    two = make_brief("臺南市", [{"phenomena": "大雨"}, {"phenomena": "大雨"}], 10, [])
    assert two.count("大雨") == 1, two
    # 5) 有避難所就要帶到
    sh = [{"name": "永康國中", "district": "永康區", "address": "中山南路"}]
    assert "永康國中" in make_brief("臺南市", [], 0, sh)
    print("brief self-check ok")


def main() -> None:
    if "--self-check" in sys.argv:
        return _self_check()
    argv = sys.argv[1:]
    city = argv[argv.index("--city") + 1] if "--city" in argv else "臺南市"
    rain = float(argv[argv.index("--rain") + 1]) if "--rain" in argv else 0.0
    print(make_brief(city, [], rain, []))


if __name__ == "__main__":
    main()
