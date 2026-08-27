# 中央氣象署 API 踩雷筆記

格式：每條寫「症狀 → 真相 → 什麼時候會踩到」。新條目往下加，不要改舊條目。

## 1. `records.location` 改名為 `records.Locations`

- 症狀：`KeyError: 'location'`，或更糟——不報錯但永遠拿到 0 筆特報。
- 真相：2024 年後欄位改名為 `records.Locations`（大寫 L、複數）。舊欄位在部分
  dataset 仍存在，但**恆為空陣列**，所以讀舊名不會爆，只會安靜地少資料。
- 什麼時候會踩到：任何 parse 特報回應的地方。看到「查得到但都沒特報」先懷疑這條。
- 對策：`recs.get("Locations") or recs.get("location") or []`，並在 self-check 用假
  payload 斷言至少解出 1 筆。

## 2. 縣市名用「臺」不用「台」

- 症狀：`locationName` 比對永遠不中，回傳空陣列。
- 真相：官方資料一律用「臺南市」「臺北市」，使用者輸入通常打「台」。
- 對策：`fetch()` 與 `parse_alerts()` 一進來就 `city = city.replace("台", "臺")`，再用 `in` 做寬鬆比對。
  只用 `in` 是不夠的——「台南市」不是「臺南市」的子字串，一定要先換字。

## 3. 縣市可能包兩層

- 症狀：`TypeError: string indices are integers`。
- 真相：部分 dataset 是 `records.Locations[].Location[]`（外層是資料集、內層才是地點），
  部分則直接是地點清單。
- 對策：`for loc in g.get("Location") or [g]:`，兩種形狀都吃。

> ⚠️ 未實測：本專案沒有 CWA_API_KEY，以上欄位名以課程投影片與 open data 文件為準。
> 第一次真的打通 API 後，請用 `@data-scout` 對照實際回應並更新這份檔案。
