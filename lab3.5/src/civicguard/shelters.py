"""CivicGuard：避難收容處所欄位正規化（D-007）。

各縣市開放資料的欄位名不一致：台南叫「分區」、高雄叫「區域」、
宜蘭把地址與備註塞在同一欄。這支把它們壓成同一個 schema。

跑法：
    uv run civicguard-shelters --self-check
    uv run civicguard-shelters --from-file data/shelters_tainan.json
"""

import json
import sys
from pathlib import Path

# 目標欄位 -> 各縣市用過的別名（新縣市就往這裡加一個字串，不要再開一個函式）
ALIASES = {
    "name": ("名稱", "場所名稱", "收容處所名稱", "避難收容處所"),
    "district": ("分區", "區域", "鄉鎮市區", "行政區"),
    "address": ("地址", "位置", "地址及備註"),
    "capacity": ("可容納人數", "容量", "收容人數"),
}


def normalize(row: dict) -> dict:
    """一列原始資料 -> {name, district, address, capacity, note}。找不到的欄位給空值。"""
    out = {}
    for field, names in ALIASES.items():
        val = next((row[n] for n in names if row.get(n) not in (None, "")), "")
        out[field] = val
    out["note"] = ""
    # 宜蘭把備註跟地址塞在同一欄，用全形括號或「備註」切開
    for sep in ("（備註：", "(備註：", " 備註："):
        if sep in str(out["address"]):
            addr, _, note = str(out["address"]).partition(sep)
            out["address"], out["note"] = addr.strip(), note.rstrip("）)").strip()
            break
    # 人數一律轉 int；髒資料（"約 300 人"、""）保留原值以利追溯
    if isinstance(out["capacity"], str) and out["capacity"].isdigit():
        out["capacity"] = int(out["capacity"])
    return out


def normalize_all(rows: list[dict]) -> list[dict]:
    return [normalize(r) for r in rows]


def _self_check() -> None:
    tainan = {"名稱": "永康國中", "分區": "永康區", "地址": "台南市永康區中山南路", "可容納人數": "1200"}
    kaohsiung = {"場所名稱": "苓雅國小", "區域": "苓雅區", "地址": "高雄市苓雅區三多一路", "容量": "800"}
    yilan = {"收容處所名稱": "羅東國小", "鄉鎮市區": "羅東鎮",
             "地址及備註": "宜蘭縣羅東鎮公正路1號（備註：僅開放一樓）", "收容人數": "約 300 人"}

    a, b, c = normalize_all([tainan, kaohsiung, yilan])
    assert a["district"] == "永康區" and a["capacity"] == 1200
    assert b["district"] == "苓雅區" and b["name"] == "苓雅國小"
    assert c["address"] == "宜蘭縣羅東鎮公正路1號", c["address"]      # 備註要被切掉
    assert c["note"] == "僅開放一樓", c["note"]
    assert c["capacity"] == "約 300 人"                              # 髒的就留原字串，不猜
    assert normalize({})["name"] == ""                               # 空 row 不能炸
    # 同一批資料的 key 集合必須完全一致，下游才敢直接建表
    assert {tuple(sorted(x)) for x in (a, b, c)} == {tuple(sorted(a))}
    print("shelters self-check ok")


def main() -> None:
    if "--self-check" in sys.argv:
        return _self_check()
    argv = sys.argv[1:]
    path = argv[argv.index("--from-file") + 1] if "--from-file" in argv else sys.exit("用 --from-file <json>")
    rows = json.loads(Path(path).read_text(encoding="utf-8"))
    print(json.dumps(normalize_all(rows), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
