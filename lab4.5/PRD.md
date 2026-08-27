# Lab 4.5 PRD：讓它自己出一集（AI 日報電台）

> 所屬模組：M4.5 把 NotebookLM 變成每日內容產線 ｜ 投影片 p.223-226
> 型號／工具版本名以課程投影片為準（資訊基準日 2026-08-25）；若指令或型號 404，用 `nlm --help`、`client.models.list()` 重新確認。

## 1. 這個 Lab 要解決什麼問題

「每天固定產出一集節目」聽起來是內容問題，實際上是工程問題：Gemini Notebook 沒有官方 API（我們用的是社群逆向工程的 `notebooklm-mcp-cli`），影片生成動輒超過 30 分鐘、每天只有 3 次（免費）或 20 次（AI Pro）配額，YouTube 上傳在未稽核的 API 專案上會被**安靜地**鎖成私人。這個 Lab 要學生做出一條「會壞、但壞的時候你馬上知道，而且重跑不會二次扣配額」的產線——並且在完全沒有憑證的機器上也能用 `--dry-run` 驗證整條流程的形狀。

## 2. 學習目標

1. 用 state 檔把長時間非同步流程寫成**冪等**狀態機，中斷後 `--resume` 不重複消耗生成配額——並說得出這條產線 4.4 倍的程式碼是在處理失敗，而不是在呼叫 AI。
2. 操作 `nlm`（CLI）與 `notebooklm-mcp`（MCP server）生成 zh-TW Audio Overview 與 Explainer 影片，認出兩者是同一份能力的兩個門面（MCP 給 agent 互動、CLI 給腳本無人值守），並知道 zh-TW 有哪些格式／長度限制。
3. 用 YouTube Data API v3 以 OAuth 上傳 unlisted 影片，並**讀回 `privacyStatus`** 抓出「回 200 但被鎖成私人」的沉默失敗——同時算得出配額（1 unit／次、100 次／日）根本不是瓶頸。
4. 用 `AGENTS.md` 把頻道調性變成兩支 CLI 共讀的規則，並用程式碼（byte 級長度檢查、聳動詞彙黑名單）把 LLM 產出的 metadata 擋在送出前。
5. 用 launchd（不是 cron、不是 CI）排一條依賴瀏覽器 cookie 的產線，說得出為什麼 CI 走不通，並看出排程沒有常駐服務、只是作業系統在對的時間 exec 一次指令。

## 3. 使用者故事

- 身為學生，我想在**沒有 YouTube 頻道、沒有 nlm 憑證**的筆電上先跑通整條產線，以便我知道每一步該長什麼樣子，再去申請帳號。
- 身為學生，我想在影片生成到第 25 分鐘按下 Ctrl-C 後重跑，以便我確認今天的 3 次配額沒有被我自己燒掉。
- 身為學生，我想在上傳完成後就知道影片是不是真的 unlisted，以便我不用隔天登入 Studio 才發現整個專案還沒過稽核。
- 身為講師，我想有一個不需網路、不花錢的 `--self-check`，以便在教室 Wi-Fi 掛掉時還能驗學生的邏輯寫對了。

## 4. 功能需求

| 編號 | 需求 | 對應投影片步驟 | 必要／加分 |
|---|---|---|---|
| FR-1 | `uv init ai-daily-radio --package --python 3.13`，依賴用 `uv add`，全域 CLI 用 `uv tool install notebooklm-mcp-cli`；`nlm login` + `nlm doctor` 通過 | p.224 ① | 必要 |
| FR-2 | 工作區 `.agents/mcp_config.json` 接上 `notebooklm-mcp`，用 `NOTEBOOKLM_ENABLED_TOOLS` 收斂到 5 個工具 | p.224 ②、p.202-203 | 必要 |
| FR-3 | `airadio fetch --hours 24 --out build/digest.md`：讀 `feeds.toml`、過濾 24 小時內、去重、全文來源優先、**每個 feed 上限 5 則**（不然 40 則裡 35 則是 arXiv）、**合併成 1 份** Markdown；素材數低於門檻中止 | p.224 ③、p.206-208 | 必要 |
| FR-4 | 建當日 notebook、加 digest 來源（＋最多 5 篇全文 URL）、生成 `deep_dive` 音檔與 `explainer` 影片，語言固定 zh-TW | p.224 ④、p.204-205 | 必要 |
| FR-5 | 輪詢 `studio status`（退避、逾時 1 小時不算失敗），下載成 `.m4a` / `.mp4` | p.224 ⑤、p.209-210 | 必要 |
| FR-6 | 上傳 unlisted（`containsSyntheticMedia=true`）＋自訂縮圖，上傳後 `videos.list` 讀回 `privacyStatus` 驗證 | p.224 ⑥、p.215-217 | 必要 |
| FR-7 | metadata 由 `gemini -p` 依 `AGENTS.md` 產生，送出前用 `validate-meta` 檢查 title ≤100 字元、description ≤5000 **bytes**、tags ≤500 字元、無聳動詞彙 | p.212、p.221 | 必要 |
| FR-8 | ffmpeg 後製：loudnorm 到 -16 LUFS、（有 intro 才）接片頭、抽一張 1280×720 封面 | p.211 | 必要 |
| FR-9 | `state/YYYY-MM-DD.json` 逐步落地；`--resume` 跳過已完成步驟；失敗步驟記下錯誤訊息 | p.207、p.209 | 必要 |
| FR-10 | `reports/YYYY-MM-DD.json` 稽核紀錄：來源清單、artifact id、video id、每步耗時與失敗原因 | p.197 產出③ | 必要 |
| FR-11 | `--dry-run`：無任何憑證、無 nlm／ffmpeg／gemini 也能跑完十個步驟並產出佔位檔案 | 課程自加（可測性） | 必要 |
| FR-12 | `--self-check`：assert 驗去重／每來源上限、byte 截斷、metadata 驗證、privacy 驗證、冪等，不連網不花錢 | 課程自加（BRIEF 規範） | 必要 |
| FR-13 | `~/Library/LaunchAgents/tw.airadio.daily.plist` 每天 06:00 跑 `airadio run --resume`，絕對路徑 | p.219 | 必要 |
| FR-14 | 沒有 YouTube 頻道的替代路徑：產生 `build/upload_payload.json` 取代上傳 | p.223 註腳 | 必要 |
| FR-15 | 加分：`.m4a` 產生 Podcast RSS，描述自動附上一集連結 | p.225 加分題 | 加分 |
| FR-16 | 加分：`uvx faster-whisper-cli` 產 SRT 後 `captions.insert` 上字幕（需 `youtube.force-ssl`） | p.216 | 加分 |

## 5. 非功能需求

| 項目 | 要求 |
|---|---|
| 時間盒 | 總計 ~150 分：30 分骨架＋nlm、30 分 fetch、45 分生成（含等待空檔）、45 分 YouTube。等待生成時去做 FR-7／FR-8。 |
| 費用上限 | $0。Gemini Notebook 免費層（Audio 3／日、Video 3／日）、YouTube API 免費、`gemini` CLI 免費層。整條產線一天約消耗 1 unit（上傳桶）＋450 units（共用 10,000 桶）。 |
| 離線可測 | `--self-check` 與 `--dry-run` 必須在無網路、無憑證、未安裝 nlm／ffmpeg 的環境下成功（本 lab 已實測，見 walkthrough 步驟 2）。 |
| 跨平台 | 產線本體 macOS／Linux 皆可；排程只提供 macOS launchd（Linux 請改 systemd timer，需 `Persistent=true` ＋ `enable-linger`）。**不能跑在 CI**：nlm 認證是瀏覽器 cookie。 |
| 可靠性 | 每次執行前 `nlm doctor`；cookie 2-4 週會過期，過期只能靠人開瀏覽器重登，產線必須把這件事**大聲講出來**而不是靜靜失敗。 |

## 6. 驗收標準

對應投影片 p.225 的六項，每項都給可執行指令：

- [ ] **① 全程 uv**：沒有任何 `pip`／`venv`／直接 `python`；全域 CLI 用 `uv tool install`；`uv.lock` 已提交
      `grep -rEn "pip install|python -m venv|source .*activate" . --include="*.md" --include="*.py" ; ls uv.lock`（前者要無輸出）
- [ ] **② 語言正確**：音檔與影片都是繁體中文；影片格式是 `explainer`
      `grep -n 'zh-TW\|explainer' src/airadio/run.py`（`create_video` 必須是 explainer，不是 cinematic／short）
- [ ] **③ 副檔名正確**：音檔 `.m4a`、影片 `.mp4` 可播
      `ls -l build/podcast.m4a build/episode.mp4 && ffprobe build/podcast.m4a 2>&1 | grep -i aac`
- [ ] **④ 冪等**：中途 Ctrl-C 後 `--resume` 重跑，生成步驟被跳過
      `uv run airadio run --dry-run --resume 2>&1 | grep -c "↷ 跳過"` → 應為 `10`
- [ ] **⑤ 上傳有驗證**：讀回 `videos.list` 檢查 `privacyStatus`，不符預期讓流程失敗
      `uv run airadio --self-check`（第 4 項就是驗這件事）＋真上傳過的 `reports/<日期>.json` 裡有 `verified_privacy`（`--dry-run` 與無 token 的替代路徑不會有這個欄位）
- [ ] **⑥ 語氣受控**：標題與描述由 Gemini CLI 依 `AGENTS.md` 產生，無聳動詞彙、來源連結完整
      `uv run airadio run --dry-run`（會落地 `build/meta.json`）→ `uv run airadio validate-meta build/meta.json` → exit 0；把 title 改成「震撼！」再跑一次 → exit 1
- [ ] **⑦ 產出**：至少一集實際產出（`.m4a` ＋ `.mp4`）＋ 一支 unlisted YouTube 影片（含自訂縮圖）；沒有頻道者以 `build/upload_payload.json` 替代
- [ ] **⑧ 稽核紀錄**：`reports/<日期>.json` 含來源清單、artifact id、video id、每步耗時

## 7. 範圍外

- **不做公開發布**。一律 `privacyStatus=unlisted`，公開由人按。YouTube 垃圾內容政策點名「用自動化大量產出高度相似內容」，人工放行時的挑選與補充才是政策要求的原創觀點。
- 不寫 nlm 的替代實作（不自己逆向 Gemini Notebook 前端）。
- 不做 cinematic／short 影片（zh-TW 不支援，且限 18 歲以上帳號）。
- 不做 Podcast 平台上架（RSS 產生是加分題，實際投稿不在範圍）。
- 不把 nlm 那一段搬上 CI（結構上不可行，見 p.219）。
- 不追求「生成品質」的調校：這個 Lab 驗的是產線可靠性，內容好不好聽是 Antigravity 互動調校（p.221 ②）的事。

## 8. 費用與風險

| 項目 | 費用 | 說明 |
|---|---|---|
| Gemini Notebook | 免費層 | Audio 3 次／日、Video 3 次／日；AI Pro 各 20 次。**重跑一次就少一次**——這是 state 檔存在的第二個理由 |
| YouTube Data API v3 | 免費 | `videos.insert` 獨立桶 1 unit／日 100 次；`thumbnails.set` 50 units、`captions.insert` 400 units（共用 10,000 桶） |
| Gemini CLI | 免費層 | metadata 產生；不可用時本 lab 的程式碼會退回本地樣板並照樣過 validate |
| GCP | $0 | 只需要一個 Google Cloud 專案來開 YouTube Data API 與建 OAuth client，不佈署任何資源 |

風險與對策：

- **cookie 2-4 週過期**：每次執行先 `nlm doctor`；失敗就發通知叫人重跑 `nlm login`。不要在 MCP 設定塞 `NOTEBOOKLM_COOKIES`，它優先序最高，會讓 `nlm login` 永遠無法更新憑證。
- **OAuth 同意畫面停在 Testing**：refresh token 只活 7 天，排程下週某天無聲死掉。必須設成 In production。
- **未稽核專案上傳被鎖私人**：API 回 200、影片在、但 `privacyStatus=private` 且改不動。上傳後一定要讀回驗證，並送 Audit and Quota Extension Form。
- **nlm 隨時可能因 Google 改前端而壞**：這是設計決策不是意外，所以整條產線圍繞「壞掉時馬上知道」設計。

清理（本 lab 沒有雲端資源要刪，但有本機東西要收）：

```bash
launchctl bootout gui/$(id -u)/tw.airadio.daily        # 停排程
rm ~/Library/LaunchAgents/tw.airadio.daily.plist
rm -rf build state reports secrets                     # 憑證與產物（secrets 千萬別 commit）
uv tool uninstall notebooklm-mcp-cli
rm -rf ~/.notebooklm-mcp-cli                           # 連 cookie 一起清
# YouTube 上的測試影片自己去 Studio 刪；OAuth client 可留著，不收費
```

## 9. 前置依賴

| 依賴 | 說明 |
|---|---|
| Lab 4 | 已經用過 Gemini Notebook 與 `notebooklm-mcp`，知道 notebook／source／studio 的概念 |
| Lab 3 / 3.5 | 會用 Antigravity 工作區設定與 `AGENTS.md` 共享記憶；`gemini` CLI 已裝好（Node ≥ 20） |
| Google 帳號 | Gemini Notebook 免費層（每個 notebook 上限 50 個來源、Audio／Video 各 3 次／日）；有 AI Pro 更順（來源 300、各 20 次／日） |
| Google Cloud 專案 | 只用來開 YouTube Data API v3 ＋ 建 Desktop app 類型 OAuth client（不綁卡也能開） |
| YouTube 頻道 | **可選**。沒有的話走 FR-14，改交 `upload_payload.json` |
| 本機工具 | `uv`、`ffmpeg`（`brew install ffmpeg`）、`jq`、桌面環境（有瀏覽器可登入的 GUI session） |
