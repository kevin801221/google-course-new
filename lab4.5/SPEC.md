# Lab 4.5 SPEC：讓它自己出一集（AI 日報電台）

## 1. 架構

```
                        ┌──────────────── 排程層（本機，必須有 GUI session）─────────────┐
                        │  launchd  ~/Library/LaunchAgents/tw.airadio.daily.plist       │
                        │  每天 06:00 → /Users/you/.local/bin/uv run airadio run --resume│
                        └───────────────────────────┬──────────────────────────────────┘
                                                    │ 絕對路徑，不載入 shell 設定檔
┌───────────────────────────────────────────────────▼───────────────────────────────────────────┐
│ 編排層  airadio（uv 專案，src/airadio/run.py）                                                  │
│                                                                                               │
│  state/YYYY-MM-DD.json  ←──每完成一步就寫──┐   reports/YYYY-MM-DD.json ←── finally 一定寫       │
│                                            │                                                  │
│  fetch → notebook → audio_create ─┐        │                                                  │
│                     video_create ─┴→ audio_wait → video_wait → download → post → meta → upload│
└───┬──────────┬───────────────────────────────┬──────────────┬────────────────┬────────────────┘
    │ HTTP     │ subprocess                    │ subprocess   │ subprocess     │ HTTPS + OAuth
    ▼          ▼                               ▼              ▼                ▼
 RSS×10    nlm notebook/source          nlm studio status   ffmpeg          YouTube Data API v3
 (feedparser)  nlm audio/video create   nlm download audio  loudnorm/thumb  videos.insert
                    │                          │                             thumbnails.set
                    ▼                          ▼                             videos.list（讀回驗證）
              Gemini Notebook（無官方 API，走逆向工程的 nlm；認證＝瀏覽器 cookie）

  另一條開發期路徑（人在場才用）：
  Antigravity ──.agents/mcp_config.json──> notebooklm-mcp（MCP server）──> 互動試 format／style
  gemini CLI  ──讀 AGENTS.md──> build/meta.json（title/description/tags）
```

程序邊界：`airadio` 自己不呼叫任何 Gemini Notebook HTTP 端點，全部經由 `subprocess` 呼叫 `nlm`；`--dry-run` 時這條邊界被 `sh()` 攔下來回假資料，所以整條流程可以在沒有 nlm、沒有 ffmpeg、沒有憑證的機器上跑完。

## 2. 元件與職責

| 元件 | 檔案／位置 | 職責 | 壞掉的症狀 |
|---|---|---|---|
| 編排狀態機 | `src/airadio/run.py` `do_run()` / `step()` | 依序跑 10 個步驟，每步結果寫進 state；已有結果就跳過 | 沒有 state → 重跑扣光配額 |
| 素材抓取 | `read_feeds()` `fetch_entries()` `select_items()` `cap_by_source()` `build_digest()` | 讀 `feeds.toml`、24 小時過濾、去重、全文優先、**每來源上限 5 則**、總上限 40 則、合併成 1 份 Markdown | 素材 < 8 則 → `Pipeline` 中止當日；沒有每來源上限 → 40 則裡 35 則是 arXiv |
| nlm 包裝 | `nlm()` `do_notebook()` `create_audio()` `create_video()` | 建 notebook、加來源、送出生成 | 找不到 `nlm` → 一行可讀錯誤（不是 traceback） |
| 輪詢 | `wait_artifact()` | 15s 起跳、×1.5 退避、上限 120s、逾時 3600s | 逾時不算失敗，隔天 `--resume` 續跑 |
| 下載 | `do_download()` | `nlm download audio\|video <nb> <artifact-id> --output <path>`，檢查 `.m4a` / `.mp4` 真的落地 | 副檔名寫 `.mp3` → nlm 直接拒絕 |
| 後製 | `do_post()` | loudnorm -16 LUFS、（有 `assets/intro.mp4` 才）concat 片頭、抽 1280×720 封面 | 參數不一致 → concat 破圖 |
| metadata | `gemini_meta()` `local_meta()` `validate_meta()` `clamp_bytes()` | 產生並**驗證** title/description/tags；gemini 不可用時退回本地樣板 | description 超 5000 bytes → 半夜炸在 API 層 |
| 上傳 | `yt_body()` `do_upload()` `check_privacy()` | resumable upload、縮圖、讀回 `privacyStatus` | 未稽核專案 → `privacyStatus=private` |
| 憑證 | `do_auth()` / `secrets/token.json`（0600） | 一次性拿 refresh token（`access_type=offline`＋`prompt=consent`） | 同意畫面 Testing → token 7 天後失效 |
| 頻道規則 | `AGENTS.md` | 節目調性＋產線硬規則，Antigravity 與 gemini CLI 共讀 | 沒有它 → LLM 生出聳動標題 |
| MCP 設定 | `.agents/mcp_config.json` | 工作區層接 `notebooklm-mcp`，`NOTEBOOKLM_ENABLED_TOOLS` 收斂到 5 個工具 | 43 個工具全開 → 吃掉上下文 |
| 排程 | `tw.airadio.daily.plist` | 每天 06:00 觸發，含明確 `PATH` | 用相對路徑 → launchd 找不到 uv |

## 3. 介面契約

### 3.1 CLI

```
airadio [cmd] [target] [flags]

cmd = run | fetch | wait | validate-meta | upload | auth | captions      （預設 run）
--date today|YYYY-MM-DD   --hours 24   --out build/digest.md
--notebook <nb-id>        --artifact <artifact-id>
--video <path>            --video-id <id>   --file <path>   --language zh-TW
--client secrets/client_secret.json          --privacy unlisted   --verify
--resume                  # state 已有結果的步驟跳過
--dry-run                 # 不執行任何外部指令、不需憑證，回假資料並產生佔位檔
--self-check              # assert 驗離線邏輯（7 項），不連網不花錢
```

stdout 只印機器可讀的 JSON；所有進度與警告都走 stderr（`log()`）。

### 3.2 內部函式簽章（重點）

```python
def select_items(items: list[dict], hours: int, now: float) -> list[dict]
#   item = {"title","link","summary","source","ts": int|None, "full": bool}
#   規則：ts 超過 hours 就丟；ts 為 None 一律保留；同 norm_title 或無 link 去掉

def cap_by_source(items: list[dict], limit: int = MAX_ITEMS, per_source: int = PER_SOURCE) -> list[dict]
#   全文（full=True）排前面，每個 source 最多 per_source 則，總數最多 limit
def build_digest(day: str, items: list[dict]) -> str           # 一份 Markdown，每則必附連結
def do_fetch(day: str, hours: int, out: Path) -> dict
#   -> {"count": int, "digest": "build/digest.md",
#       "top_picks": [url, ...]        # 全文來源最多 5 筆，之後單獨用 --url 加進 notebook
#       "sources": [{"title","link"}, ...]}

def do_notebook(day: str, digest: Path, top_picks: list[str]) -> str   # -> notebook id
def create_audio(nb: str) -> str        # nlm audio create --format deep_dive --language zh-TW
def create_video(nb: str) -> str        # nlm video create --format explainer --style whiteboard
def wait_artifact(nb: str, artifact_id: str, timeout_s: int = 3600) -> dict   # -> {"state": "ready"}
def do_download(nb: str, audio_art: str, video_art: str) -> dict
#   -> {"audio": "build/podcast.m4a", "video": "build/episode.mp4"}（artifact id 要傳進來才能指定 --output）
def do_post(audio: Path, video: Path) -> dict   # -> {"audio","video","thumb"}

def clamp_bytes(s: str, limit: int) -> str                     # 依 UTF-8 byte 截斷，尾巴加「…」
def validate_meta(m: dict) -> dict                             # 不合規則 raise Pipeline
def yt_body(meta: dict, privacy: str) -> dict
def check_privacy(yt, video_id: str, want: str = "unlisted") -> str
def do_upload(video: Path, thumb: Path | None, meta: dict, privacy: str, verify: bool) -> dict

def step(st: dict, name: str, fn) -> object                     # 冪等閘門，見 §4
def sh(*args: str, want_json: bool = True, fake=None)           # dry-run 時回 fake，不執行
```

### 3.3 外部指令契約（投影片為準）

| 呼叫 | 期望輸出 |
|---|---|
| `nlm notebook create "AI 日報 <日期>" --json` | `{"id": "..."}` |
| `nlm source add <nb> --file build/digest.md` / `--url <url>` | 人類可讀文字，不是 JSON（`want_json=False`，不讀回傳值） |
| `nlm audio create <nb> --format deep_dive --language zh-TW --confirm --json` | `{"artifact_id": "..."}` |
| `nlm video create <nb> --format explainer --style whiteboard --language zh-TW --confirm --json` | `{"artifact_id": "..."}` |
| `nlm studio status <nb> --artifact-id <aid> --json` | `{"state": ...}`；投影片 p.209 只明確給了 `ready` / `failed` 兩個值（骨架只認這兩個，其餘一律當「還沒好」繼續輪詢）。中間狀態叫什麼名字投影片沒寫，不要憑空當成 `queued`／`running` 去比對 |
| `nlm download audio <nb> <aid> --output build/podcast.m4a` | 不回 JSON（`want_json=False`）；落地 `build/podcast.m4a` |
| `nlm download video <nb> <aid> --output build/episode.mp4` | 同上；落地 `build/episode.mp4`。LAB 步驟 ⑤ 的 `download all --output-dir build` 也能用，但落地檔名沒有文件化，所以骨架用單檔形式 |
| `gemini -p "<prompt>" --output-format json` | `{"response": "<JSON 字串>"}` |

> ⚠️ 未實測：以上 `nlm` 與 `gemini` 的回傳欄位名（`id` / `artifact_id` / `state`）抄自投影片 p.208-210，本機沒有安裝 `notebooklm-mcp-cli` 也沒有 Gemini Notebook 憑證，無法核對。真的接上去若 KeyError，用 `nlm audio create ... --json | jq` 看實際欄位名再改 `create_audio()` 那三行。

### 3.4 YouTube API

```python
videos().insert(part="snippet,status", body={
  "snippet": {"title","description","tags","categoryId"},
  "status":  {"privacyStatus": "unlisted",
              "selfDeclaredMadeForKids": False,
              "containsSyntheticMedia": True}},
  media_body=MediaFileUpload(path, chunksize=1024*1024, resumable=True))
thumbnails().set(videoId=..., media_body=MediaFileUpload("build/thumb.jpg"))   # 2MB 上限
videos().list(part="status", id=video_id)   # -> items[0].status.privacyStatus，必須讀回驗證
captions().insert(part="snippet", body={"snippet": {"videoId","language","name","isDraft"}},
                  media_body=MediaFileUpload("build/podcast_norm.srt"))        # 需 force-ssl
```

硬限制：title 100 字元且不可含 `< >`；description **5000 bytes**（中文一字約 3 bytes ≈ 1600 字）；tags 加總 500 字元；`categoryId` 用 `videoCategories.list` 查（社群常用 27=Education、28=Science & Technology，Google 沒有公開對照表）。

## 4. 資料模型

`state/YYYY-MM-DD.json`（＝冪等的唯一依據，`reports/` 是它的收尾副本）：

```json
{
  "day": "2026-08-26",
  "dry_run": true,
  "status": "ok",
  "steps": {
    "fetch":        {"result": {"count": 40, "digest": "build/digest.md",
                                "top_picks": ["..."], "sources": [{"title": "...", "link": "..."}]},
                     "elapsed_s": 5.5},
    "notebook":     {"result": "dry-nb-0001", "elapsed_s": 0.0},
    "audio_create": {"result": "dry-audio-1", "elapsed_s": 0.0},
    "video_create": {"result": "dry-video-1", "elapsed_s": 0.0},
    "audio_wait":   {"result": {"state": "ready"}, "elapsed_s": 0.0},
    "video_wait":   {"result": {"state": "ready"}, "elapsed_s": 0.0},
    "download":     {"result": {"audio": "build/podcast.m4a", "video": "build/episode.mp4"}},
    "post":         {"result": {"audio": "build/podcast_norm.m4a", "video": "build/episode.mp4",
                                "thumb": "build/thumb.jpg"}},
    "meta":         {"result": {"title": "...", "description": "...", "tags": ["..."],
                                "category_id": "28"}},
    "upload":       {"result": {"video_id": "...", "url": "https://youtu.be/...",
                                "privacy": "unlisted", "verified_privacy": "unlisted"}}
  }
}
```

規則：
- step key 固定 10 個，順序 `fetch, notebook, audio_create, video_create, audio_wait, video_wait, download, post, meta, upload`。
- 有 `result` = 完成，`--resume` 直接跳過；有 `error` = 失敗，重跑會重試該步。
- `status` 在 `do_run()` 一開始就寫 `failed`，只有跑完 `upload` 才改成 `ok`——`--resume` 讀進來的舊 state 可能已經是 `ok`，若只在 `finally` 裡 `setdefault`，今天失敗會沿用昨天的 `ok`，稽核紀錄就謊報成功。
- `audio_create`／`video_create` 與 `audio_wait`／`video_wait` **一定要分成兩個 key**：不然「生成成功但輪詢中斷」重跑時會再送一次生成，扣掉當天配額。

## 5. 檔案結構

```
lab4.5/
├── PRD.md
├── SPEC.md
├── walkthrough.md
└── ai-daily-radio/                      # 學生的交付專案（可直接複製當起點）
    ├── AGENTS.md                        # 頻道調性＋產線硬規則（Antigravity 與 gemini CLI 共讀）
    ├── .agents/mcp_config.json          # 工作區層 notebooklm-mcp 設定＋收斂工具集
    ├── .gitignore                       # build/ state/ reports/ secrets/ 不進版控
    ├── feeds.toml                       # 10 個 RSS 來源，full_text 標記決定排序優先
    ├── pyproject.toml                   # 依賴＋[project.scripts] airadio＋hatch packages
    ├── tw.airadio.daily.plist           # launchd 範本（絕對路徑＋PATH）
    └── src/airadio/
        ├── __init__.py                  # 只 re-export cli/main
        └── run.py                       # 整條產線：fetch/notebook/studio/post/youtube/state
```

執行期產生（皆 gitignore）：`build/`（digest.md、podcast.m4a、episode.mp4、podcast_norm.m4a、thumb.jpg、meta.json、upload_payload.json）、`state/`、`reports/`、`secrets/`（client_secret.json、token.json 0600）、`assets/intro.mp4`（可選）。

> 投影片 p.207 把產線拆成 `fetch.py / notebook.py / studio.py / post.py / youtube.py / run.py` 六個模組；本骨架先全部放在 `run.py`（約 620 行），這樣學生一個檔案看完整條流程。要拆的話按 §2 的元件切，函式名不用改。

## 6. 環境變數與設定

| 變數／設定 | 用途 | 從哪來 | 預設 |
|---|---|---|---|
| `NOTEBOOKLM_HL` | 固定 Notebook 輸出語言 | 自己 export 或寫在 `.agents/mcp_config.json` 的 `env` | 無（本 lab 設 `zh-TW`） |
| `NOTEBOOKLM_ENABLED_TOOLS` | 只開 5 個 MCP 工具，省上下文 | 同上 | 43 個全開 |
| `NOTEBOOKLM_COOKIES` | **絕對不要設** | — | — |
| `~/.notebooklm-mcp-cli/profiles/<name>/auth.json` | nlm 的 cookie，2-4 週過期 | `nlm login` | profile `default` |
| `secrets/client_secret.json` | OAuth Desktop app client | GCP Console → 憑證 | 無 |
| `secrets/token.json` | refresh token（0600） | `uv run airadio auth --client secrets/client_secret.json` | 無 → 走 `upload_payload.json` 路線 |
| `MIN_ITEMS` / `MAX_ITEMS` / `PER_SOURCE`（常數） | 素材數下限 8、總上限 40、每個 feed 上限 5 | `run.py` 頂端 | 8 / 40 / 5 |
| `BANNED`（常數） | 聳動詞彙黑名單 | `run.py` 頂端，與 `AGENTS.md` 對應 | 8 個詞 |
| `SCOPES`（常數） | `youtube.upload` ＋ `youtube.force-ssl` | `run.py` 頂端 | 兩個一起要（事後補要重走同意流程） |
| `PATH`（plist 內） | launchd 不載入 shell 設定檔 | `tw.airadio.daily.plist` | 必填 |

`NOTEBOOKLM_COOKIES` 的優先序最高於一切，設了之後 `nlm login` 永遠無法更新憑證，等於把重新認證的路堵死。

## 7. 執行流程（從零到驗收）

```bash
# 0) 專案（無憑證也能到步驟 2）
uv init ai-daily-radio --package --python 3.13 && cd ai-daily-radio
uv add feedparser httpx google-api-python-client google-auth google-auth-oauthlib
# pyproject.toml 補上：[tool.hatch.build.targets.wheel] packages = ["src/airadio"]

# 1) 離線驗證（不需要任何憑證、不需要 nlm／ffmpeg）
uv run airadio --self-check                 # → self-check 通過（7 項）
uv run airadio run --dry-run                # → 10 步全綠，產出佔位檔
uv run airadio run --dry-run --resume       # → 10 個「↷ 跳過」

# 2) 工具與登入
uv tool install notebooklm-mcp-cli && nlm login && nlm doctor
mkdir -p .agents && nlm setup add antigravity && nlm setup list

# 3) 真的跑
uv run airadio fetch --hours 24 --out build/digest.md
NB=$(nlm notebook create "AI 日報 $(date +%F)" --json | jq -r .id)   # 或直接 airadio run
uv run airadio run                          # fetch→…→upload，途中可 Ctrl-C
uv run airadio run --resume                 # 續跑，已完成的跳過

# 4) OAuth 與上傳（有頻道才做）
uv run airadio auth --client secrets/client_secret.json && chmod 600 secrets/token.json
uv run airadio upload --video build/episode.mp4 --privacy unlisted --verify

# 5) 排程
cp tw.airadio.daily.plist ~/Library/LaunchAgents/   # 先把 /Users/you 換掉
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/tw.airadio.daily.plist
launchctl print gui/$(id -u)/tw.airadio.daily | head
```

## 8. 錯誤處理與邊界

| 情境 | 症狀 | 處理方式 |
|---|---|---|
| 找不到 `nlm` / `ffmpeg` / `gemini` | `FileNotFoundError: [Errno 2] ... 'nlm'` | `sh()` 統一轉成 `Pipeline`，一行講清楚要裝什麼、或先跑 `--dry-run` |
| nlm cookie 過期 | 所有 nlm 指令回認證錯誤 | 執行前先 `nlm doctor`；失敗就中止並通知人重跑 `nlm login`（無法自救） |
| nlm 沒回 JSON | `json.JSONDecodeError` | `sh()` 轉成 `Pipeline`「沒有回 JSON（少了 --json？）」 |
| RSS 回空 | 素材數 < 8 | arXiv 加 cache buster 重抓；仍不足就 `Pipeline` 中止當日，不出刊 |
| 素材過多 | 119 則塞進一集 | 全文優先＋每來源上限 5 則＋總上限 40（單一來源上限 50 萬字／200MB，不會爆） |
| 單一 feed 壟斷 | 40 則裡 35 則是 arXiv cs.AI | `cap_by_source()` 每來源上限 5；實測同一次抓取變成 27 則、8 個來源 |
| 生成逾時 | 輪詢滿 3600s | `Pipeline` 中止，state 保留；隔天 `--resume` 續跑，不重送生成 |
| 生成 `failed` | `state == "failed"` | 立刻 raise，錯誤訊息寫進 state，人來看是不是配額用盡 |
| 配額用盡 | 生成指令回錯 | state 檔擋住重跑；重試前先確認不是配額問題（免費 3／日） |
| 下載檔不見 | `build/podcast.m4a` 不存在 | `Pipeline` 提示副檔名（`.mp3` 會被 nlm 拒絕） |
| description 超長 | `len(s.encode()) > 5000` | `clamp_bytes()` 先截；`validate_meta()` 再擋，兩層 |
| LLM 生出聳動標題 | title 含黑名單詞 | `validate_meta()` raise，列出命中的詞；退回 `local_meta()` 樣板 |
| 上傳被鎖私人 | 回 200 但 `privacyStatus=private` | `check_privacy()` raise「專案可能尚未通過稽核」，當日流程標記失敗 |
| 上傳 5xx | `HttpError 500/502/503/504` | 指數退避加抖動，最多 10 次；其他狀態碼直接 raise |
| 沒有 YouTube 頻道 | `secrets/token.json` 不存在 | 寫 `build/upload_payload.json` 並回 `{"skipped": "no_youtube_channel"}` |
| Ctrl-C | KeyboardInterrupt | `step()` 已把完成的步驟落地；`finally` 仍寫 report（`status=failed`） |

## 9. 驗證方式

| 要驗什麼 | 怎麼跑 | 預期 |
|---|---|---|
| 離線邏輯（去重、byte 截斷、metadata 驗證、privacy 驗證、冪等、digest 帶連結、上傳 body） | `uv run airadio --self-check` | `self-check 通過（7 項）`，exit 0 |
| 整條流程形狀（無憑證） | `uv run airadio run --dry-run` | 10 個 `✓`，`status=ok`，`build/` 有 5 個檔 |
| 冪等 | `uv run airadio run --dry-run --resume` | 10 個 `↷ 跳過` |
| metadata 硬限制 | `uv run airadio validate-meta build/meta_bad.json` | `✗ description 6000 bytes，上限 5000 bytes`，exit 1 |
| 真實 RSS | `uv run airadio fetch --hours 24 --out build/digest.md` | 2026-08-26 實測 `{"count": 27, "top_picks": 5}`（數字每天不同，8≤count≤40）；`grep -c '^## ' build/digest.md` 等於 count；每個來源不超過 5 則 |
| 缺工具的錯誤訊息 | `uv run airadio run`（未裝 nlm） | `✗ 找不到指令 nlm——nlm 用 uv tool install ...` |
| metadata 檔真的有落地（驗收⑥ 要用） | `uv run airadio run --dry-run && uv run airadio validate-meta build/meta.json` | 印出 metadata JSON，exit 0 |
| 檔案不存在時不噴 traceback | `uv run airadio validate-meta build/nope.json` | `✗ [Errno 2] No such file or directory: 'build/nope.json'`，exit 1 |

已在本機實測通過：上表全部（`fetch` 實抓真實 RSS，約 6 秒抓 280 則、去重後 119 則、每來源上限後 27 則／8 個來源）。

無法離線驗證（文件內也標了 `⚠️ 未實測`）：

- `nlm login` / `nlm doctor` / `nlm setup add antigravity`：需要 Google 帳號與受控瀏覽器登入。
- `nlm audio|video|studio|download` 的實際 JSON 欄位名與 `state` 值域：需要 Gemini Notebook 憑證。
- `gemini -p --output-format json` 的實際輸出：需要 Gemini CLI 登入。
- `videos.insert` / `thumbnails.set` / `videos.list` / `captions.insert`：需要 GCP 專案、OAuth client 與 YouTube 頻道。`check_privacy()` 的邏輯有用 `SimpleNamespace` 假物件驗過，但真實 API 沒有。
- ffmpeg 三條指令：本機未安裝 ffmpeg，指令字串抄自投影片 p.211。
- launchd 排程是否準時觸發：需要等到隔天 06:00，且機器不能睡著。

## 10. 已知限制與升級路徑

| 位置 | 偷懶的地方（`# ponytail:` 註解） | 天花板 | 升級路徑 |
|---|---|---|---|
| `run.py` 檔頭 | 整條產線一個檔案 | 約 620 行，再長就難讀 | 照 §2 元件切成投影片 p.207 的六個模組，函式名不動 |
| `DRY` 全域旗標 | 不做 context 物件 | 不能同時跑 dry 與真跑 | 需要平行就把 `sh` 綁進一個小 class |
| `select_items()` | `ts is None` 一律保留 | 沒給日期的 feed 可能灌進舊文 | 改成丟掉並在 report 記下丟掉幾則 |
| `cap_by_source()` | 每來源固定上限 5，不看內容品質 | 全文來源一天只有 5 則時，比例仍拉不到投影片說的一半 | 把 `--hours` 開大、`feeds.toml` 加全文來源，或改成按內容長度加權挑選 |
| `local_meta()` | 樣板字串，不呼叫 LLM | 描述千篇一律，正是 YouTube 垃圾內容政策點名的形狀 | 只當 fallback；正式跑一定走 `gemini_meta()` |
| `do_post()` | 有 `assets/intro.mp4` 才接片頭 | 沒統一參數前的 concat 會破圖 | concat 前先各自 transcode 成同解析度／fps／取樣率 |
| `wait_artifact()` | 序列等 audio 再等 video | 兩個都慢的話總時間相加 | 已先送出兩個生成請求，要再快就用 thread 併行輪詢 |
| `do_upload()` | 縮圖失敗不重試 | `thumbnails.set` 偶發 5xx 會讓整步失敗 | 包進同一個退避迴圈 |
| 無通知機制 | 失敗只寫 report | 半夜壞了沒人知道 | 在 `do_run()` 的 `finally` 接一行 `osascript -e 'display notification'` 或寄信 |
