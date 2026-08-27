# AI 日報電台 — 頻道規則（Antigravity 與 Gemini CLI 共讀）

## 節目調性（所有自動產生的文字都必須遵守）
- 標題與描述不使用聳動詞彙。程式碼的黑名單（`run.py` 的 `BANNED`）是強制的，共 8 個詞：
  震撼、炸裂、你不知道、驚人、必看、史上最、細思極恐、秒懂。改這裡就要改 `BANNED`。
- 不對未證實的傳聞下結論；不確定就寫「尚未證實」。
- 每一則都必須附上原始來源連結，不得只寫媒體名稱。
- 描述開頭三行是本集重點，讀完就能決定要不要聽。

## 產線硬規則
- Python 一律 uv；禁止 python／pip／venv。
- 影片格式固定 explainer（zh-TW 不支援 cinematic／short）。
- 音檔副檔名固定 .m4a（.mp3 會被 nlm 拒絕）。
- 上傳一律 privacyStatus=unlisted，公開由人決定。
- containsSyntheticMedia 一律為 true。
- 生成類步驟先看 state/<日期>.json，有結果就跳過（配額每天只有 3／20 次）。
