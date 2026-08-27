# 決策紀錄（append-only）

規則：只增不改。要推翻舊決策就新增一條，並在「取代」欄寫明取代哪一條。
已結案且不再影響行為的，搬到 `decisions-archive.md`，且**不要** @import 它。

## D-007 避難所資料改用「正規化後快取」

- 日期：2026-08-20
- 提出：antigravity（規劃階段）
- 執行：gemini-cli（批次匯入）
- 背景：22 個縣市的欄位命名不一致，台南用「分區」、高雄用「區域」、宜蘭把地址跟
  備註塞在同一欄。每個下游都自己 if-else 一次，改一次資料要改五個地方。
- 決定：新增 `shelters.normalize()`，統一輸出 `{name, district, address, capacity, note}`；
  上游原始欄位保留不動以利追溯。
- 影響：`docs/domain/shelter-quirks.md` 需同步更新對照表。
- 取代：無

## D-008 特報等級不做四捨五入

- 日期：2026-08-21
- 提出：gemini-cli（headless 稽核時發現）
- 背景：地震規模 5.45 被四捨五入成 5.5 後跨過簡報用語的分級門檻，導致文案誇大。
  雨量 79.9 毫米同樣會從「大雨」跳成「豪雨」。
- 決定：所有數值一律以原始精度輸出，分級判斷用原始值。
- 影響：`brief.rain_level()` 由大到小比門檻；self-check 加上 79.9 的回歸斷言。
- 取代：無

## D-009 特報 parse 一律容忍舊欄位名

- 日期：2026-08-26
- 提出：gemini-cli（跑 `--self-check` 時發現）
- 執行：gemini-cli
- 背景：`records.location` 在 2024 年後改名為 `records.Locations`（大寫 L、複數）。
  舊欄位在部分 dataset 仍存在但**恆為空陣列**，所以讀舊名不會報錯，只會安靜地拿到 0 筆特報；
  在已移除舊欄位的 dataset 則是 `KeyError: 'location'`。兩種症狀都不會指向真正的原因。
- 決定：一律 `recs.get("Locations") or recs.get("location") or []`，
  並在 `--self-check` 用假 payload 斷言至少解出 1 筆（文件會被讀但不會被執行，回歸檢查才會）。
- 影響：`docs/domain/cwa-api-notes.md` 第 1 條；`src/civicguard/cwa.py` 的 `parse_alerts()`。
- 取代：無
