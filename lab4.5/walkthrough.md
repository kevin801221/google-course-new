# Lab 4.5 走一遍：讓它自己出一集（AI 日報電台）

> 約 150 分鐘（含等待生成的空檔）｜綜合 NotebookLM MCP ＋ nlm CLI ＋ ffmpeg 後製 ＋ YouTube Data API v3 ＋ launchd 排程 ＋ 冪等狀態機

做完你會有一個 `ai-daily-radio` 專案，一行指令跑完「抓 RSS → 合併素材 → Gemini Notebook 生成 zh-TW 對談音檔與 Explainer 影片 → ffmpeg 後製 → 上傳 YouTube unlisted → 讀回 `privacyStatus` 驗證」，中途 Ctrl-C 再跑不會重複扣掉當天只有 3 次的生成配額。

而且——**在還沒有任何憑證的機器上，你第 10 分鐘就能看到整條產線跑完**：

```
$ uv run airadio run --dry-run
AI 日報 2026-08-26｜dry_run=True resume=False
  ✓ fetch（0.0s）
[dry-run] $ nlm notebook create AI 日報 2026-08-26 --json
[dry-run] $ nlm source add dry-nb-0001 --file .../build/digest.md
  ✓ notebook（0.0s）
[dry-run] $ nlm audio create dry-nb-0001 --format deep_dive --language zh-TW --confirm --json
  ✓ audio_create（0.0s）
[dry-run] $ nlm video create dry-nb-0001 --format explainer --style whiteboard --language zh-TW --confirm --json
  ✓ video_create（0.0s）
  ✓ audio_wait（0.0s）
  ✓ video_wait（0.0s）
  ✓ download（0.0s）
  ✓ post（0.0s）
  ✓ meta（0.0s）
[dry-run] videos.insert episode.mp4 privacy=unlisted
  ✓ upload（0.0s）
稽核紀錄：reports/2026-08-26.json（status=ok）
{
  "video_id": "dry-run-video-id",
  "privacy": "unlisted",
  "verified": true
}
```

每一步都有「動手 → 為什麼 → 驗收」。驗收沒過不要往下走：這條產線的步驟會互相依賴 state 檔，錯在前面、症狀出現在後面，很難查。

---

## 步驟 0：前置（5 分）

| 需要 | 怎麼確認 | 沒有的話 |
|---|---|---|
| Lab 4 做完 | 知道 notebook／source／studio 是什麼 | 先回去做 Lab 4 |
| `uv` | `uv --version` | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| `jq` | `jq --version` | `brew install jq` |
| `ffmpeg` | `ffmpeg -version` | `brew install ffmpeg`（步驟 8 才會用到） |
| Google 帳號 | 能開 notebook.google.com | 免費層就夠（Audio 3 次／日、Video 3 次／日） |
| 桌面環境 | 有可以互動的瀏覽器 | **這條產線不能跑在 CI 或無頭伺服器**，理由見步驟 3 |
| YouTube 頻道 | 可選 | 沒有就走步驟 9 的替代路徑，驗收其餘七項 |

**驗收**

```bash
uv --version && jq --version        # 兩行都有版本號
```

> 資訊基準日 2026-08-25。NotebookLM 已於 2026-07-16 改名 **Gemini Notebook**（入口 notebook.google.com、說明文件 support.google.com/gemininotebook/），但 CLI 與 MCP server 名稱還留著 `notebooklm-` 前綴。查資料時要認路徑，舊的 `/notebooklm/` 說明頁連得上但內容是改名前的。

---

## 步驟 1：專案骨架（投影片 ① 前半，10 分）

### 動手

```bash
uv init ai-daily-radio --package --python 3.13 && cd ai-daily-radio
uv add feedparser httpx google-api-python-client google-auth google-auth-oauthlib
```

`uv init --package` 會生出 `src/ai_daily_radio/`。我們的套件要叫 `airadio`（指令是 `uv run airadio`），所以改名並寫入口：

```bash
mv src/ai_daily_radio src/airadio
```

`pyproject.toml` 的 `[project.scripts]` 改成：

```toml
[project.scripts]
airadio = "airadio:cli"
```

然後**故意先不要動別的**，直接跑：

```bash
uv run airadio --help
```

### 為什麼（先看它炸）

它會炸，而且錯誤訊息長得像 hatchling 的內部問題：

```
ValueError: Unable to determine which files to ship inside the wheel using the following heuristics:
  ...
  The most likely cause of this is that there is no directory that matches the name of your project (ai_daily_radio).
  At least one file selection option must be defined in the `tool.hatch.build.targets.wheel` table
```

原因：專案名叫 `ai-daily-radio`（正規化成 `ai_daily_radio`），套件目錄卻叫 `airadio`。`--package` 模式下 `uv run` 會真的把專案 build 成 wheel 再裝進環境，hatchling 找不到同名目錄就不知道要打包什麼。投影片 p.207 的 tree 就是 `src/airadio/`，所以這個坑一定會踩到。

修法是在 `pyproject.toml` 補一段：

```toml
# 專案名叫 ai-daily-radio、套件目錄叫 airadio，名字不一致時 hatchling 找不到要打包什麼
[tool.hatch.build.targets.wheel]
packages = ["src/airadio"]
```

（另一條路是專案名就叫 `airadio`，但投影片指定 `uv init ai-daily-radio`，照著做才對得上驗收。）

順手把該有的檔案放好——`AGENTS.md`、`feeds.toml`、`.gitignore`、`.agents/mcp_config.json` 都在本目錄的 `ai-daily-radio/` 裡，直接複製：

```bash
printf 'build/\nstate/\nreports/\nsecrets/\n.venv/\n' > .gitignore
```

`secrets/` 一定要 gitignore：裡面會有 `token.json`（YouTube 的 refresh token）。

### 驗收

```bash
uv run airadio --help          # 印出 usage: airadio [-h] ...
ls uv.lock                     # 存在（驗收①要求 uv.lock 已提交）
```

---

## 步驟 2：先讓整條產線在「沒有任何憑證」的狀況下跑通（15 分）

這步投影片沒有，但它是這個 Lab 最重要的設計。

### 動手

把本目錄的 `ai-daily-radio/src/airadio/run.py` 複製到你的專案（726 行，一個檔案裝完整條產線），`src/airadio/__init__.py` 改成：

```python
"""airadio：AI 日報電台產線。實作全在 run.py。"""
from .run import cli, main   # noqa: F401
```

然後跑兩件事：

```bash
uv run airadio --self-check
uv run airadio run --dry-run
```

關鍵只有一個函式——所有外部指令都從這裡出去：

```python
def sh(*args: str, want_json: bool = True, fake=None):
    if DRY:
        log(f"[dry-run] $ {' '.join(args)}")
        return fake if fake is not None else {}
    try:
        p = subprocess.run(args, capture_output=True, text=True)
    except FileNotFoundError:
        raise Pipeline(f"找不到指令 {args[0]}——nlm 用 `uv tool install notebooklm-mcp-cli`；"
                       f"ffmpeg 用 `brew install ffmpeg`；沒有憑證時先跑 --dry-run")
    if p.returncode != 0:
        raise Pipeline(f"{args[0]} 失敗（exit {p.returncode}）：{p.stderr.strip()[:400]}")
    ...
```

每個生成類函式都自己帶一份假回應：

```python
def create_audio(nb: str) -> str:
    out = nlm("audio", "create", nb, "--format", "deep_dive", "--language", "zh-TW",
              "--confirm", "--json", fake={"artifact_id": "dry-audio-1"})
    return out["artifact_id"]
```

### 為什麼

不這樣寫會怎樣：你要驗一次「流程順序有沒有錯」就得真的花掉一次生成配額（免費帳號一天 3 次），而影片可能要等 30 分鐘才知道下一步的參數傳錯了。第一天你就會把配額燒完，然後只能等隔天。

第二個理由是教室現實：一半的學生會卡在 `nlm login` 的瀏覽器授權或 GCP 專案開通。`--dry-run` 讓他們先把整條流程的形狀跑出來，卡住的部分後補。

`FileNotFoundError` 的攔截也不是裝飾。沒有那個 `try` 的話，忘記裝 nlm 的人會看到 20 行 traceback 結尾是：

```
FileNotFoundError: [Errno 2] No such file or directory: 'nlm'
```

半夜排程失敗時，log 裡只有這行，你得自己想起來 `nlm` 是什麼。攔在 `sh()` 一個地方，所有呼叫外部指令的路徑（nlm / ffmpeg / gemini）就都有可讀訊息了。

### 驗收

```bash
uv run airadio --self-check
```

```
  ✓ audio_create（0.0s）
  ↷ 跳過 audio_create（state 已有結果）
  ↷ 跳過 audio_create（state 已有結果）
self-check 通過（7 項）
```

（中間那三行是第 5 項在驗冪等時的正常輸出——它故意呼叫 `step()` 三次，只有第一次真的執行。）

```bash
uv run airadio run --dry-run && ls build state reports
```

```
build:
digest.md	episode.mp4	podcast.m4a	podcast_norm.m4a	thumb.jpg
reports:
2026-08-26.json
state:
2026-08-26.json
```

七項 self-check 分別驗：① 24 小時過濾＋去重＋每來源上限 ② 中文 description 的 byte 截斷 ③ metadata 五種違規 ④ `privacyStatus` 讀回驗證 ⑤ state 冪等 ⑥ digest 一定帶連結 ⑦ 上傳 body 的三個固定欄位。全部用 `assert` 與 `SimpleNamespace` 假物件，不連網、不花錢。

> 💡 **啊哈：這條產線裡真正叫 AI 生成的只有 42 行，其餘 4.4 倍的程式碼都在處理「它會失敗」。**
> 你以為做 AI 產線的難處在 prompt 與模型選型。用 ast 實際數：呼叫生成 42 行（7.7%），
> 而狀態機、驗證防錯、上傳憑證這些「讓那 42 行能在半夜無人值守活下去」的碼有 185 行。
> demo 只需要那 42 行 —— 這個比例就是 demo 與產品的差別。
> **動手看**：`uv run airadio aha lines` → 七種職責的行數對照長條圖，最後一行是 42 vs 185（4.4 倍）

---

## 步驟 3：安裝 nlm、登入、健檢（投影片 ① 後半，15 分）

### 動手

```bash
uv tool install notebooklm-mcp-cli      # 一次裝好 nlm（CLI）與 notebooklm-mcp（MCP server）
nlm login                               # 開一個受控瀏覽器，登入後擷取 cookie
nlm doctor                              # 認證、相依、MCP 設定一次看完
```

不想先裝就試：

```bash
uvx --from notebooklm-mcp-cli nlm --help
```

### 為什麼

- **這一步決定整條產線的壽命。** nlm 的認證是瀏覽器 cookie，存在 `~/.notebooklm-mcp-cli/profiles/<name>/auth.json`，活 2-4 週；超過 7 天未驗證會被標記為 stale。CSRF token 只有幾分鐘，失敗時自動換新。
- **千萬不要在 MCP 設定裡塞 `NOTEBOOKLM_COOKIES` 環境變數。** 它的優先序最高，設了之後 `nlm login` 永遠無法更新憑證——等於把重新認證的路堵死。到時候你會看到所有 nlm 指令都回認證錯誤，而 `nlm login` 跑起來一切正常卻沒有效果。
- **這就是「不能跑在 CI」的根本原因。** CI runner 沒有登入中的桌面 session、沒有 keychain、沒有可互動的瀏覽器。cookie 一過期，無人值守的環境完全無法自救。GitHub Actions 的 `schedule: cron` 還會延遲 5-30 分鐘、repo 60 天沒動就自動停用；Unix cron 沒有 GUI session、`PATH` 也很精簡。所以步驟 11 用 macOS launchd（使用者層）。
- 因為 cookie 注定會過期，產線的正確設計是**每次執行前先 `nlm doctor`，失敗就中止並通知人**，而不是重試。

### 驗收

```bash
nlm doctor
```

認證那一行是綠的（或明確寫 authenticated）。順手看一下我們只會用到的六個子指令都在：

```bash
nlm --help | grep -E "login|notebook|source|audio|video|download"
```

> ⚠️ 未實測：`nlm login` / `nlm doctor` 需要 Google 帳號與受控瀏覽器登入，本教材撰寫環境沒有安裝 `notebooklm-mcp-cli`，這一步的輸出格式以投影片 p.200 為準。

---

## 步驟 4：接進 Antigravity（投影片 ②，5 分）

### 動手

```bash
mkdir -p .agents && nlm setup add antigravity && nlm setup list
```

但**建議直接手寫工作區設定**（本目錄已附）：

```json
{
  "mcpServers": {
    "gemini-notebook-mcp": {
      "command": "notebooklm-mcp",
      "env": {
        "NOTEBOOKLM_HL": "zh-TW",
        "NOTEBOOKLM_ENABLED_TOOLS": "notebook_create,source_add,studio_create,studio_status,download_artifact"
      }
    }
  }
}
```

### 為什麼

- **路徑不一致**：`nlm setup` 會寫進 `~/.gemini/antigravity/mcp_config.json`，Antigravity 官方文件寫的全域路徑卻是 `~/.gemini/config/mcp_config.json`。手寫工作區的 `.agents/mcp_config.json` 最不會出錯，而且能進版控。
- **命名漂移**：文件寫 server 名稱是 `notebooklm-mcp`，目前原始碼預設是 `gemini-notebook-mcp`（改名的殘留），執行檔名一直是 `notebooklm-mcp`。設定裡兩個名字都可能出現，以 `nlm doctor` 的結果為準。
- **`NOTEBOOKLM_ENABLED_TOOLS` 不是潔癖**：MCP server 有 43 個工具，全開會把 agent 的上下文吃掉一大塊，而自動化真正用到的只有 5 個（`studio_create`、`studio_status`、`download_artifact` 是主角）。不收斂的話 agent 每次對話都要讀 43 份工具描述，回答變慢、也更容易挑錯工具。
- 遠端模式的欄位叫 **`serverUrl`**，不吃 `url` / `httpUrl`——抄 Cursor 設定檔必踩。要跑遠端就 `notebooklm-mcp --transport http --port 8000`，設定寫 `{"serverUrl": "http://127.0.0.1:8000/mcp"}`。

### 驗收

在 Antigravity 裡打 `/mcp`，看得到 `gemini-notebook-mcp` 且工具數是 5（不是 43）。或者：

```bash
nlm setup list && nlm doctor
```

> ⚠️ 未實測：需要 Antigravity 桌面版與已登入的 nlm，撰寫環境兩者皆無。

> 💡 **啊哈：`nlm` 與 `notebooklm-mcp` 是同一份能力的兩個門面——CLI 給腳本，MCP 給 agent。**
> `uv tool install` 一次裝出兩個執行檔，背後同一份程式碼：MCP 的 `studio_create` 與
> `nlm audio create` 做的是同一件事，差別只在誰來呼叫。這是全課那條主線的第一站——
> 接下來換你當作者：Lab 6 把自己的函式包成 MCP server（`lab6/server.py`），
> Lab 7 讓 agent 用 `McpToolset` 把它當工具吃進去（`lab7/travel_planner/agent.py:109`）。
> **動手看**：`uv run airadio aha tools` → 六個能力 × 三種包裝（MCP 工具／nlm 子指令／本產線函式）的並排表

---

## 步驟 5：抓料並合併成一份（投影片 ③，25 分）

### 動手

```bash
uv run airadio fetch --hours 24 --out build/digest.md
```

核心是這兩個函式（`run.py`）：

```python
def select_items(items: list[dict], hours: int, now: float) -> list[dict]:
    """留 hours 小時內的、去重（同標題或同連結只留第一則）。"""
    cut = now - hours * 3600
    seen, out = set(), []
    for it in items:
        if it["ts"] is not None and it["ts"] < cut:
            continue
        key = norm_title(it["title"]) or it["link"]
        if key in seen or not it["link"]:
            continue
        seen.add(key)
        out.append(it)
    return out
```

```python
def cap_by_source(items, limit=MAX_ITEMS, per_source=PER_SOURCE):   # 40 / 5
    out, used = [], {}
    for it in sorted(items, key=lambda i: not i["full"]):     # 全文的先進來
        if used.get(it["source"], 0) >= per_source:           # 每個 feed 最多 5 則
            continue
        used[it["source"]] = used.get(it["source"], 0) + 1
        out.append(it)
        if len(out) >= limit:
            break
    return out

picked = cap_by_source(select_items(items, hours, time.time()))
if len(picked) < (2 if DRY else MIN_ITEMS):   # MIN_ITEMS = 8（dry-run 的假資料只有 2 則）
    raise Pipeline(f"當日素材只有 {len(picked)} 則（門檻 {MIN_ITEMS}）——RSS 可能回空，今天不出刊")
```

### 為什麼

- **合併成 1 份，不是 30 個來源。** 免費帳號每個 notebook 上限 50 個來源（AI Pro 300），但單一來源可以到 50 萬字／200MB。一條新聞一個來源，光 arXiv 就把配額用完了。所以把當日全部合併成一份 `digest.md`，只有少數需要全文的重點文章才單獨用 `--url` 加進去（本骨架取前 5 篇全文來源）。
- **只排序還不夠，一定要加「每來源上限」。** 第一次跑真實 RSS 你會拿到 280 則、去重後 119 則，其中絕大多數是 arXiv 的摘要。只有標題／摘要的 feed 餵進 Notebook 會生出很空的內容——主持人只能一直說「這篇論文探討了…」。
  只用 `sort(key=lambda i: not i["full"])` 再截 40 則的話（第一版就是這樣寫的），實測 40 則裡有 **35 則是 arXiv cs.AI**——因為全文 feed 一天就那幾則，剩下 35 個位置全被同一個 feed 填滿，整集變成論文摘要朗讀。加上 `per_source = 5` 之後同一次抓取變成 27 則、8 個來源（arXiv cs.AI 5、cs.CL 5、HF 5、TechCrunch 5、MIT 3、Simon Willison 2、Google AI 1、OpenAI 1）。
  誠實講：全文來源**還是只有 5 則**，投影片 p.206 說的「全文來源至少要佔一半」在 24 小時窗口內做不到（Import AI 是週刊、Simon Willison 一天 2-3 篇）。能做到的是「全文的一定排最前面、單一 feed 不會壟斷」。真的想拉高比例就把 `--hours` 開大，或在 `feeds.toml` 加更多全文來源。
- **去重要用正規化標題，不能用連結。** 同一則新聞會同時出現在 Google 官方 blog 與 TechCrunch，連結不同、標題幾乎一樣。`norm_title()` 把大小寫、標點、空白全部拿掉再比前 60 字。不去重的話節目會把同一件事講三次。
- **素材門檻是為了 `rss.arxiv.org` 的邊緣快取。** 它偶爾回空的 feed。不設門檻的話你會生出一集只有 3 則新聞的節目，還扣掉一次配額。arXiv 的 URL 我們額外加 `?cb=<timestamp>` 當 cache buster。
- `ts is None` 一律保留：有些 feed 不給日期。這是刻意偷懶（`# ponytail:`），代價是可能灌進舊文；要更嚴就丟掉並在 report 記下丟了幾則。

### 驗收

```bash
uv run airadio fetch --hours 24 --out build/digest.md | jq '{count, top_picks: (.top_picks|length)}'
```

實測輸出（2026-08-26，真實抓 10 個 feed，約 6 秒）：

```json
{
  "count": 27,
  "top_picks": 5
}
```

`count` 每天不一樣（取決於各 feed 當天發了幾則），會落在 `MIN_ITEMS`(8) 到 `MAX_ITEMS`(40) 之間；低於 8 就不出刊。重點是下面兩件事要成立：

```bash
grep -c '^## ' build/digest.md        # 要等於上面的 count
awk '/^- 來源：/{print $0}' build/digest.md | sort | uniq -c | sort -rn | head
sed -n '5,8p' build/digest.md
```

```
   5 - 來源：arXiv cs.AI
   5 - 來源：arXiv cs.CL
   5 - 來源：HF Daily Papers
   5 - 來源：TechCrunch AI
   3 - 來源：MIT Tech Review AI
```

沒有任何來源超過 5 則（`PER_SOURCE`），代表 `cap_by_source()` 生效了。

```
## 1. Quoting Paul Dix
- 來源：Simon Willison
- 連結：https://simonwillison.net/2026/Aug/26/paul-dix/
```

第 1 則是全文來源（不是 arXiv），代表排序生效了。每一則都有「連結：」——`AGENTS.md` 的調性規則要求每則都附原始來源，digest 沒帶連結，後面 metadata 就編不出來源清單。

---

## 步驟 6：建 notebook 並生成（投影片 ④，20 分 ＋ 等待）

### 動手

```bash
NB=$(nlm notebook create "AI 日報 $(date +%F)" --json | jq -r .id)
nlm source add $NB --file build/digest.md
nlm audio create $NB --format deep_dive --language zh-TW --confirm --json
nlm video create $NB --format explainer --style whiteboard --language zh-TW --confirm --json
```

或者直接讓狀態機做（推薦，因為它會寫 state）：

```bash
uv run airadio run
```

### 為什麼

- **`--format deep_dive`**：兩位主持人對談，適合每日新聞節目。其他三種是 `brief`（單人播報、官方描述兩分鐘以內）、`critique`（評論拆解）、`debate`（正反辯論）。
- **zh-TW 不能指定長度。** 官方說明頁明載長度控制（Shorter／Default／Longer）是 English Only，互動模式也只支援英文。所以本骨架**沒有** `--length` 參數——寫上去不會報錯，只會被忽略，你會以為自己控制了長度。
- **影片只能用 `explainer`。** `cinematic` 與 `short` 官方明載僅支援英文、且限 18 歲以上帳號。傳 `--format cinematic --language zh-TW` 的結果不是報錯，而是生出一支不是你要的東西（或直接失敗），這也是驗收②要 `grep explainer` 的原因。
- **兩個生成先都送出，再一起等。** `do_run()` 的順序是 `audio_create → video_create → audio_wait → video_wait`，不是「建一個等一個」。影片官方說可能超過 30 分鐘，音檔快得多，序列等會白等。
- **`audio_create` 與 `audio_wait` 一定要是兩個 state key。** 合成一步的話，「生成送出成功但輪詢中斷」重跑時會再送一次生成——當天配額只有 3 次，兩次就沒了。

### 驗收

```bash
uv run airadio run --dry-run 2>&1 | grep -E "audio create|video create"
```

```
[dry-run] $ nlm audio create dry-nb-0001 --format deep_dive --language zh-TW --confirm --json
[dry-run] $ nlm video create dry-nb-0001 --format explainer --style whiteboard --language zh-TW --confirm --json
```

真的跑之後，看 state 檔拿到 artifact id：

```bash
jq '.steps | keys, .audio_create.result, .video_create.result' state/$(date +%F).json
```

> ⚠️ 未實測：`nlm audio/video create --json` 實際的欄位名（本骨架讀 `artifact_id`）抄自投影片 p.209，撰寫環境無 Gemini Notebook 憑證無法核對。若 `KeyError: 'artifact_id'`，先用 `nlm audio create $NB ... --json | jq` 看實際欄位，再改 `create_audio()` 的最後一行。

---

## 步驟 7：輪詢到好再下載（投影片 ⑤，15 分）

### 動手

```bash
uv run airadio wait --notebook $NB --artifact <artifact-id>
# 下載：用 p.210 的單檔形式，檔名自己指定（音檔一定要 .m4a）
nlm download audio $NB <audio-artifact-id> --output build/podcast.m4a
nlm download video $NB <video-artifact-id> --output build/episode.mp4
# 投影片 LAB 步驟 ⑤ 的 `nlm download all $NB --output-dir build --skip-existing` 也能用，
# 但它落地的檔名沒有文件化，腳本後面的 exists() 檢查就對不上——所以骨架用單檔形式。
```

```python
def wait_artifact(nb: str, artifact_id: str, timeout_s: int = 3600) -> dict:
    deadline, delay = time.monotonic() + timeout_s, 15
    while time.monotonic() < deadline:
        st = nlm("studio", "status", nb, "--artifact-id", artifact_id, "--json", fake={"state": "ready"})
        if st.get("state") in ("ready", "failed"):
            if st["state"] == "failed":
                raise Pipeline(f"生成失敗 artifact={artifact_id}：{st.get('error', '無訊息')}")
            return st
        time.sleep(delay)
        delay = min(delay * 1.5, 120)            # 退避，別把對方打爆
    raise Pipeline(f"輪詢逾時（{timeout_s}s）artifact={artifact_id}——不算失敗，明天 --resume 續跑")
```

### 為什麼

- **不能同步等。** 官方說明頁直接寫影片生成「有時會超過 30 分鐘」。沒有輪詢的話你的腳本會被一個 HTTP 呼叫掛在那裡，超時斷線後你連 artifact id 都不知道去哪裡撿。
- **退避上限 120 秒。** 固定 15 秒輪詢 30 分鐘＝120 次請求，對一個逆向工程的介面來說太吵，也更容易被當成異常流量。`delay * 1.5` 上限 120 是投影片給的數字。
- **逾時不當失敗。** 訊息故意寫「明天 --resume 續跑」：state 檔裡 `video_create` 已經有 artifact id，隔天重跑會直接跳到 `video_wait`，不會再扣一次配額。
- **副檔名一定是 `.m4a`。** 音檔是 AAC-in-MP4；寫 `.mp3` 會被 nlm 從 0.6.7 起直接拒絕（它會提示你改用 `.m4a` 或 `.mp4`，並附上轉檔的 ffmpeg 指令）。Google 的說明頁只寫「選擇 Download」，完全沒寫格式——`.m4a` 這件事是從 nlm 原始碼與 issue #185 確認的，屬於工具行為不是官方保證。
- **`download` 與 `source add` 不回 JSON。** 只有帶 `--json` 的子指令（`notebook create`、`audio/video create`、`studio status`）才回 JSON。骨架的 `nlm()` 因此有 `want_json` 參數；忘記關的話下載那步會噴 `Pipeline: nlm 沒有回 JSON（少了 --json？）`，而其實 nlm 根本執行成功了。
- 手機版存不了音檔（只能離線收聽），所以自動化一定要在桌面環境跑——又一個不能上 CI 的理由。

### 驗收

```bash
ls -l build/podcast.m4a build/episode.mp4
ffprobe build/podcast.m4a 2>&1 | grep -i aac        # 有 aac 那行代表真的是 AAC-in-MP4
open build/episode.mp4                              # 影片能播、旁白是繁體中文
```

`do_download()` 也會幫你擋一次：檔案沒落地就 `Pipeline: 下載後找不到 podcast.m4a——確認副檔名（音檔一定是 .m4a）`。

> ⚠️ 未實測：`nlm studio status --json` 的 `state` 值域（本骨架認 `ready` / `failed`）抄自投影片 p.209；ffprobe／播放驗收需要真的產出檔案。

---

## 步驟 8：後製與 metadata（p.211-212，20 分）

### 動手

```bash
uv run airadio run --resume        # post 與 meta 兩步會跑到
```

後製三條 ffmpeg（`do_post()`）：

```bash
# 1) 響度正規化到 Podcast 常用的 -16 LUFS
ffmpeg -y -i build/podcast.m4a -af loudnorm=I=-16:TP=-1.5:LRA=11 -c:a aac -b:a 128k build/podcast_norm.m4a
# 2) 有 assets/intro.mp4 才接片頭
ffmpeg -y -i assets/intro.mp4 -i build/episode.mp4 \
  -filter_complex "[0:v][0:a][1:v][1:a]concat=n=2:v=1:a=1[v][a]" \
  -map "[v]" -map "[a]" -c:v libx264 -crf 20 -c:a aac build/episode_final.mp4
# 3) 抽一張封面（縮圖上限 2MB）
ffmpeg -y -i build/episode_final.mp4 -ss 00:00:30 -vframes 1 -vf scale=1280:720 build/thumb.jpg
```

metadata 交給 Gemini CLI 依 `AGENTS.md` 產生，**但送出前一定要自己驗**：

```bash
gemini -p "讀 build/digest.md，依 AGENTS.md 的『節目調性』章節產生今日影片 metadata。以 JSON 回覆，欄位：title, description, tags。title 不超過 100 字元且不得使用聳動詞彙；description 開頭三行是本集重點，之後列出所有來源連結；tags 總長不超過 500 字元。" \
  --output-format json | jq -r '.response' > build/meta.json
uv run airadio validate-meta build/meta.json
```

### 為什麼（這裡先讓它失敗一次）

先做一份「看起來很合理」的中文描述，然後驗它：

```bash
uv run python -c "import json;print(json.dumps({'title':'AI 日報 2026-08-26','description':'字'*2000,'tags':['AI']},ensure_ascii=False))" > build/meta_bad.json
uv run airadio validate-meta build/meta_bad.json; echo "exit=$?"
```

實測輸出：

```
✗ description 6000 bytes，上限 5000 bytes（中文一字約 3 bytes）
exit=1
```

2000 個中文字在你眼裡遠低於「5000」，但 YouTube 的 `snippet.description` 上限是 **5000 位元組**，一個中文字約 3 bytes——換算下來只有約 1600 字。自動產生的描述若把 40 則來源連結全列進去，很容易超過。**不驗會怎樣**：`videos.insert` 會在半夜回 400，而你的影片已經上傳到一半，state 檔卡在 `upload` 步驟，隔天早上才發現。

所以有兩層：`clamp_bytes()` 先按 byte 截（`b[:limit-3].decode("utf-8", "ignore")`，不然中文會切在字中間變亂碼），`validate_meta()` 再擋。`validate_meta()` 一共擋五種：

```python
if not t or len(t) > 100:                    raise Pipeline(f"title 長度 {len(t)}，YouTube 上限 100 字元")
if "<" in t or ">" in t:                     raise Pipeline("title 不可含 < 或 >")
if len(d.encode()) > 5000:                   raise Pipeline(f"description {nb} bytes，上限 5000 bytes...")
if sum(len(x) for x in tags) > 500:          raise Pipeline("tags 加總超過 500 字元")
if hit := [w for w in BANNED if w in t or w in d]: raise Pipeline(f"違反 AGENTS.md 節目調性，出現聳動詞彙：{hit}")
```

最後那條是驗收⑥。`AGENTS.md` 寫「標題不使用震撼、炸裂、你不知道的」是給 LLM 看的**建議**，LLM 有時就是會寫。程式碼裡的黑名單才是**強制**。兩者要對應：改 `AGENTS.md` 就要改 `BANNED`。

另外 `categoryId` 用 `28`（Science & Technology）。Google 沒有公開對照表，社群普遍用 27=Education、28=Science & Technology；正式做法是呼叫 `videoCategories.list` 並確認 `assignable` 是 true。

為什麼要做響度正規化：Overview 的音量在不同題材之間會有落差，固定跑一次 `loudnorm` 訂閱者就不用每集重調音量。這是自動化節目最容易被忽略、但聽眾最有感的一件事。而片頭反而不重要——YouTube 把「大量產出、彼此高度相似」視為風險，固定片頭沒有幫助，每集不同的封面與開場摘要才有（見步驟 9 的政策段）。

### 驗收

```bash
uv run airadio validate-meta build/meta.json && echo "OK"       # → OK
jq -r '.title, (.description|length), (.tags|join(",")|length)' build/meta.json
uv run python -c "import json;d=json.load(open('build/meta.json'));print(len(d['description'].encode()),'bytes')"
```

description 的 bytes 數 ≤ 5000、title ≤ 100 字元、tags 加總 ≤ 500。再把 title 改成「震撼！AI 日報」跑一次，必須 exit 1 並列出命中的詞。

> ⚠️ 未實測：`gemini -p --output-format json` 的實際輸出結構（本骨架讀 `.response` 再 `json.loads`）需要 Gemini CLI 登入；ffmpeg 三條指令抄自投影片 p.211，撰寫環境未安裝 ffmpeg。`--dry-run` 會跳過 gemini 直接用本地樣板，所以流程仍可驗。

---

## 步驟 9：上傳並驗證 privacyStatus（投影片 ⑥，30 分）

### 動手

先拿 refresh token（一次性）：

```bash
# GCP Console：啟用 YouTube Data API v3 → 建立 OAuth client（類型：Desktop app）
#              同意畫面 → Publishing status → In production
uv run airadio auth --client secrets/client_secret.json
chmod 600 secrets/token.json
```

再上傳：

```bash
uv run airadio upload --video build/episode.mp4 --privacy unlisted --verify
```

### 為什麼（這裡是全模組最大的地雷）

**先看沒有 token 時會怎樣**——這是「沒有 YouTube 頻道也能做」的替代路徑：

```bash
uv run airadio upload --video build/episode.mp4 --privacy unlisted --verify
```

實測輸出：

```
  ! 沒有 .../secrets/token.json，改寫 upload_payload.json（驗收其餘六項）
{
  "skipped": "no_youtube_channel",
  "payload": "build/upload_payload.json"
}
```

`build/upload_payload.json` 裡就是原本要送出去的 body，可以直接當交付物。

有頻道的話，三件事非做不可：

1. **必須用 OAuth，API key 沒有用。** API key 只識別「專案」不識別「使用者」，而上傳是寫進某個人的頻道。最小權限是 `https://www.googleapis.com/auth/youtube.upload`。**服務帳號也不行**——服務帳號沒有自己的 YouTube 頻道，官方認證指南也沒有列出這個流程。
2. **同意畫面必須是 In production。** 停在 Testing 的專案，核發的 refresh token 只有 **7 天**壽命。你的排程會在下週某天無聲死掉，症狀是上傳步驟回 401 `invalid_grant: Token has been expired or revoked.`——這是自動化上傳最常見的失敗原因。
3. **scope 一開始就要齊。** 要上字幕就同時要 `youtube.upload` ＋ `youtube.force-ssl`（`captions.insert` 用 upload scope 會 403）。事後追加 scope 等於重走一次同意流程，無人值守的排程做不到。

上傳本身用 resumable upload，只重試 5xx：

```python
RETRIABLE = (500, 502, 503, 504)
...
except HttpError as e:
    if e.resp.status not in RETRIABLE or retry >= 10:
        raise
    retry += 1
    time.sleep(random.random() * (2 ** retry))       # 指數退避加抖動
```

4xx 不重試——401/403 重試 10 次只是把同一個錯誤慢慢做完。

**然後是那個會讓你以為成功的地雷。** 官方在 `videos.insert` 頁面公告：2020-07-28 之後建立、且未經驗證的 API 專案，透過 `videos.insert` 上傳的影片都會被限制為私人觀看。它難發現是因為：

- API 回 **200**，影片 id 也拿得到，看起來完全成功
- 問題只出現在 `status.privacyStatus` 變成 `private`
- 不會出現在 `uploadStatus` 或 `rejectionReason` 裡
- 而且是「鎖定」——你手動改成 public 也改不動

所以上傳後一定要讀回來比對：

```python
def check_privacy(yt, video_id: str, want: str = "unlisted") -> str:
    got = yt.videos().list(part="status", id=video_id).execute()
    items = got.get("items") or []
    if not items:
        raise Pipeline(f"videos.list 查不到 {video_id}")
    actual = items[0]["status"]["privacyStatus"]
    if actual != want:
        raise Pipeline(f"專案可能尚未通過稽核：privacyStatus={actual}（預期 {want}）")
    return actual
```

不做這件事會怎樣：你的排程每天回報成功，一個月後你打開頻道，30 支影片全部是 private 而且改不動。解法是送出 Audit and Quota Extension Form 申請稽核（2020-07-28 之前建立的舊專案不受影響）。

**為什麼一律 unlisted**：`containsSyntheticMedia=true` 是據實申報（本專案的 Explainer 是非擬真插畫風格，依規則其實不需揭露，但官方明講「揭露 AI 內容不會限制觸及、不影響營利資格」，申報沒有壞處）。真正的風險不是揭露，是**大量產出**——YouTube 垃圾內容政策點名「使用自動化工具或 AI 大量產出高度相似、變動極小的內容」，例句甚至寫到「每支影片都用完全相同的背景音樂與重複的 AI 生成畫面，念一段 AI 生成的稿子」。這幾乎就是天真版自動產線的描述。所以自動化只負責把成品準備好，公開與否由人決定：人在放行時所做的挑選與補充，正是政策要求的原創觀點。

### 驗收

離線先驗邏輯（`--self-check` 的第 4 項就是這個，用 `SimpleNamespace` 假的 `yt`）：

```bash
uv run airadio --self-check      # → self-check 通過（7 項）
```

真的上傳完：

```bash
jq -r '.steps.upload.result | .url, .privacy, .verified_privacy' state/$(date +%F).json
```

三行分別是 `https://youtu.be/xxx`、`unlisted`、`unlisted`。第三行不是 `unlisted` 就代表專案沒過稽核，流程會直接失敗（這是驗收⑤要的行為）。用 Antigravity 的 browser subagent 打開那個連結，確認標題、縮圖、字幕都對、影片真的能播。

> ⚠️ 未實測：`videos.insert` / `thumbnails.set` / `videos.list` / `captions.insert` 都需要 GCP 專案、OAuth client 與 YouTube 頻道，撰寫環境沒有。`check_privacy()` 的判斷邏輯已用假物件驗過（private → raise、unlisted → 通過），但真實 API 回傳沒有驗。

> 💡 **啊哈：上傳配額比你聽過的便宜 1600 倍；真正會鎖死你的那件事，一個 unit 都不花。**
> 網路上「`videos.insert` 一次 1600 units、一天只能傳 6 支」已經作廢兩次：2025-12 降到約 100，
> 2026-06 起改成獨立配額桶、每次 1 unit、每天 100 支。整條產線一天用 451 units（共用桶 4.5%）。
> 所以「配額」這個你會第一個擔心的東西根本不是瓶頸，而會讓你三十支影片全部鎖成私人的稽核限制，
> 不消耗配額、不回錯誤、也不在任何 quota dashboard 上——只有讀回 `privacyStatus` 看得到。
> **動手看**：`uv run airadio aha quota` → 舊說法 vs 現制的倍數表，＋本產線一天的實際 units 用量

---

## 步驟 10：證明冪等（10 分）

### 動手（先讓它做錯一次）

跑兩次，都不帶 `--resume`：

```bash
uv run airadio run --dry-run 2>&1 | grep -E "audio_create|video_create"
uv run airadio run --dry-run 2>&1 | grep -E "audio_create|video_create"
```

實測輸出（兩次都一樣）：

```
  ✓ audio_create（0.0s）
  ✓ video_create（0.0s）
```

**兩個 `✓` 代表它真的又送了一次生成請求。** 在真跑模式下，這就是當天 3 次配額裡的第 2 次沒了。

現在加上 `--resume`：

```bash
uv run airadio run --dry-run --resume 2>&1 | grep "↷"
```

```
  ↷ 跳過 fetch（state 已有結果）
  ↷ 跳過 notebook（state 已有結果）
  ↷ 跳過 audio_create（state 已有結果）
  ↷ 跳過 video_create（state 已有結果）
  ↷ 跳過 audio_wait（state 已有結果）
  ↷ 跳過 video_wait（state 已有結果）
  ↷ 跳過 download（state 已有結果）
  ↷ 跳過 post（state 已有結果）
  ↷ 跳過 meta（state 已有結果）
  ↷ 跳過 upload（state 已有結果）
```

### 為什麼

冪等的全部祕密就這 15 行：

```python
def step(st: dict, name: str, fn):
    if name in st["steps"]:
        log(f"  ↷ 跳過 {name}（state 已有結果）")
        return st["steps"][name]["result"]
    t0 = time.monotonic()
    try:
        result = fn()
    except Exception as e:
        st["steps"][name] = {"error": f"{type(e).__name__}: {e}", "elapsed_s": ...}
        save_state(st)
        raise
    st["steps"][name] = {"result": result, "elapsed_s": round(time.monotonic() - t0, 1)}
    save_state(st)                               # 每步就落地，Ctrl-C 才不會白跑
    return result
```

三個設計決定：

- **每步結束就 `save_state()`，不是最後才寫。** 影片生成動輒 30 分鐘以上，中途一定會斷（睡眠、網路、Ctrl-C）。最後才寫的話，斷在第 8 步等於前 7 步全部要重跑，包含兩次生成。
- **失敗也寫。** `except` 裡把錯誤訊息寫進 state 再 raise，這樣 `reports/` 裡看得到「哪一步、什麼錯」，不用去翻 `/tmp/airadio.err`。
- **`--resume` 是選項而不是預設。** 預設丟掉舊 state 是為了讓「今天重新出一集」這件事有辦法做（例如素材抓錯了）。排程用的 plist 裡固定加 `--resume`。

`do_run()` 的 `finally` 一定會寫 `reports/YYYY-MM-DD.json`：

```python
st = load_state(day, resume)
st["status"] = "failed"        # 先假設失敗，跑到最後一步才改成 ok
...
finally:
    save_state(st)
    (REPORTS / f"{day}.json").write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")
```

`status` 為什麼要先寫 `failed`：`--resume` 讀進來的舊 state 可能已經是 `status: "ok"`（昨天跑成功過）。如果只在 `finally` 裡 `setdefault`，今天跑到一半失敗時那個舊的 `ok` 會被留下來，稽核紀錄就會謊報成功——這種 bug 你要一個月後打開頻道才會發現。

不寫 report 會怎樣：半夜失敗，早上你只知道「沒有新影片」，不知道是 cookie 過期、RSS 回空、還是生成逾時。

### 驗收

```bash
uv run airadio run --dry-run --resume 2>&1 | grep -c "↷ 跳過"      # → 10
jq -r '.status, (.steps|keys|length), .steps.fetch.elapsed_s' reports/$(date +%F).json
```

真跑的版本：跑到 `audio_wait` 時按 Ctrl-C，然後 `uv run airadio run --resume`，`audio_create` 與 `video_create` 必須是 `↷ 跳過`。

> 💡 **啊哈：這個 agent 的「記憶」就是一個 2KB 的 JSON 檔，而且它剛好夠用。**
> `state/2026-08-27.json` 的 10 個 key 就是它記得的全部事情，沒有向量庫、沒有 session 服務。
> 同一件事在 Lab 7 叫 session state（`lab7/travel_planner/agent.py` 的 `tool_context.state["user:budget"]`），
> 在 Lab 8 是 Supabase 的一列。差別只在「記憶要活多久、誰讀得到」——
> 這條產線的記憶只活一天、只有自己讀，那麼一個檔案就是正確答案，不是偷懶。
> **動手看**：`jq '.steps | keys' state/$(date +%F).json && wc -c state/*.json` → 十個步驟名，約 2KB

---

## 步驟 11：排程（p.219，10 分）

### 動手

```bash
cp tw.airadio.daily.plist ~/Library/LaunchAgents/     # 先把 /Users/you 換成你的路徑
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/tw.airadio.daily.plist
launchctl print gui/$(id -u)/tw.airadio.daily | head -20
```

plist 的關鍵三段：

```xml
<key>ProgramArguments</key><array>
  <string>/Users/you/.local/bin/uv</string>
  <string>run</string><string>airadio</string><string>run</string><string>--resume</string>
</array>
<key>WorkingDirectory</key><string>/Users/you/code/ai-daily-radio</string>
<key>EnvironmentVariables</key><dict>
  <key>PATH</key><string>/opt/homebrew/bin:/usr/bin:/bin:/Users/you/.local/bin</string>
</dict>
```

### 為什麼

- **絕對路徑，不然一定失敗。** launchd 不會載入你的 shell 設定檔，`PATH` 裡沒有 `~/.local/bin`。寫 `uv` 的結果是 `launchctl` 記錄一個 spawn 失敗（errno 2），什麼 log 都沒有。`uv`、`ffmpeg`、`nlm` 全部要完整路徑，或在 plist 裡自己設 `PATH`（本範本兩者都做了）。
- **為什麼是 launchd（使用者層）而不是 cron／CI**：nlm 需要登入中的桌面 session 與 keychain。`GitHub Actions` 的 cron 會延遲 5-30 分鐘、repo 60 天沒動就停用；Unix cron 沒有 GUI session。Linux 要用 systemd timer 的話記得 `Persistent=true`（補跑）＋ `enable-linger`。
- **機器睡著不會跑。** `StartCalendarInterval` 會在喚醒後補跑一次錯過的排程，但睡眠期間不執行。要準時就得設電源排程喚醒（`pmset repeat wakeorpoweron MTWRFSU 05:55:00`）。
- **`--resume` 一定要加。** 昨天卡在 `video_wait` 的 artifact，今天 06:00 會直接續拿，不重送生成。
- Antigravity 的 `/schedule` 能用但不適合這裡：Antigravity 必須開著（官方沒說明關閉後會不會執行）、已知排程任務會卡在權限或 MCP 授權對話框（半夜沒人按）、設定檔位置沒有文件化不利版控。開發期試跑用它可以。

### 驗收

```bash
launchctl print gui/$(id -u)/tw.airadio.daily | grep -E "state|program|path"
launchctl kickstart -p gui/$(id -u)/tw.airadio.daily     # 立刻手動觸發一次
tail -20 /tmp/airadio.log /tmp/airadio.err
```

`/tmp/airadio.log` 要看得到 `AI 日報 <日期>｜dry_run=False resume=True` 那一行。看不到就是 `PATH` 或 `WorkingDirectory` 寫錯。

> ⚠️ 未實測：launchd 是否在隔天 06:00 準時觸發需要真的等一天，且機器不能睡著；撰寫時只驗過 plist 的 XML 結構。

> 💡 **啊哈：「讓它自己動」沒有任何常駐的 agent 服務，全部祕密是一個 21 行的 XML。**
> 掀開來看，launchd 只知道四件事：跑哪個執行檔、在哪個目錄跑、幾點跑、`PATH` 是什麼。
> 沒有 daemon、沒有 agent runtime、沒有 webhook——「自動化」就是作業系統在對的時間 `exec` 一次你的指令。
> 所以觸發器是可換的（Linux 換一份 systemd unit，`run.py` 一行都不用改），前提是狀態不在程序裡。
> Lab 10 從反面教同一課：Cloud Run 隨時把實例收掉，session 不落地就靜靜消失（`lab10/walkthrough.md` 步驟 5「⑤ session 持久化」）。
> **動手看**：`plutil -p tw.airadio.daily.plist` → 印出 `Label` / `ProgramArguments` / `StartCalendarInterval` / `PATH`，就這些

---

## 步驟 12：驗收（10 分）

對應投影片 p.225 的六項，每項都有可貼的指令：

```bash
# ① 全程 uv（下面這行要沒有輸出）
grep -rEn "pip install|python -m venv|source .*activate" . --include="*.md" --include="*.py" --include="*.toml"
ls uv.lock

# ② 語言正確（audio 是 deep_dive/zh-TW；video 是 explainer，不是 cinematic/short）
grep -n "deep_dive\|explainer\|zh-TW" src/airadio/run.py

# ③ 副檔名正確
ls -l build/podcast.m4a build/episode.mp4 && ffprobe build/podcast.m4a 2>&1 | grep -i aac

# ④ 冪等
uv run airadio run --dry-run --resume 2>&1 | grep -c "↷ 跳過"        # → 10

# ⑤ 上傳有驗證
uv run airadio --self-check                                          # → self-check 通過（7 項）
jq -r '.steps.upload.result.verified_privacy' state/$(date +%F).json # 真上傳過才有 → unlisted
# （--dry-run 的 upload 結果是 {"video_id":"dry-run-video-id",...}，沒有 token 的是
#   {"skipped":"no_youtube_channel"}，這兩種情況這行會印 null——離線就以 self-check 第 4 項為準）

# ⑥ 語氣受控
uv run airadio validate-meta build/meta.json && echo OK
jq -r .title build/meta.json    # 沒有震撼／炸裂／你不知道的
grep -c "^- .*http" build/meta.json 2>/dev/null || jq -r .description build/meta.json | grep -c http
```

檢查清單：

- [ ] ① 全程 uv，`uv.lock` 已提交，沒有 pip／venv／直接 python
- [ ] ② 音檔與影片都是繁體中文；影片格式是 `explainer`
- [ ] ③ 音檔是 `.m4a`（不是 `.mp3`）、影片 `.mp4` 能播
- [ ] ④ Ctrl-C 後 `--resume` 重跑，生成步驟被跳過（10 個 `↷`）
- [ ] ⑤ 上傳後讀回 `videos.list` 檢查 `privacyStatus`，不符預期讓流程失敗
- [ ] ⑥ 標題與描述由 Gemini CLI 依 `AGENTS.md` 產生，無聳動詞彙、來源連結完整
- [ ] ⑦ 至少一集實際產出：`build/podcast.m4a` ＋ `build/episode.mp4` ＋ 一支 unlisted 影片（含自訂縮圖）；沒有頻道者以 `build/upload_payload.json` 替代
- [ ] ⑧ `reports/<日期>.json` 有來源清單、artifact id、video id、每步耗時
- [ ] ⑨ `uv run airadio --self-check` 與 `uv run airadio run --dry-run` 都通過

---

## 常見錯誤對照表

| 症狀 | 原因 | 解法 |
|---|---|---|
| `ValueError: Unable to determine which files to ship inside the wheel ... no directory that matches the name of your project (ai_daily_radio)` | 專案名 `ai-daily-radio` 與套件目錄 `airadio` 不同名，hatchling 不知道要打包什麼 | `pyproject.toml` 加 `[tool.hatch.build.targets.wheel]` `packages = ["src/airadio"]` |
| `ModuleNotFoundError: No module named 'feedparser'` | 用了 `python src/airadio/run.py` | 一律 `uv run airadio ...`；這個 lab 沒有 venv 要 activate |
| `FileNotFoundError: [Errno 2] No such file or directory: 'nlm'`（本骨架已轉成 `✗ 找不到指令 nlm——nlm 用 uv tool install notebooklm-mcp-cli；...`） | 沒裝 CLI，或 launchd 沒有 `PATH` | `uv tool install notebooklm-mcp-cli`；排程情境改用絕對路徑 |
| 所有 nlm 指令回認證錯誤，`nlm login` 跑起來正常但沒效果 | MCP 設定裡設了 `NOTEBOOKLM_COOKIES`，它優先序最高，把重新認證的路堵死了 | 把 `NOTEBOOKLM_COOKIES` 從 `mcp_config.json` 與 shell 設定檔裡全部刪掉，再 `nlm login` |
| `nlm download` 說要 `.m4a` 或 `.mp4`，附上一段 ffmpeg 指令 | 音檔是 AAC-in-MP4，寫 `.mp3` 從 0.6.7 起被直接拒絕 | 下載成 `.m4a`；真的需要 mp3 再 `ffmpeg -i x.m4a -codec:a libmp3lame -q:a 2 x.mp3`（YouTube 吃 mp4，其實不用轉） |
| `Pipeline: nlm 沒有回 JSON（少了 --json？）` | 需要讀回傳值的子指令沒加 `--json`（`video create` 最常忘）；反過來 `source add`／`download` 本來就不回 JSON，卻用 JSON 去解析 | 要讀回傳值的一律加 `--json`；不需要回傳值的用 `nlm(..., want_json=False)` |
| `KeyError: 'artifact_id'` | nlm 版本更新後欄位名變了 | `nlm audio create $NB ... --json \| jq` 看實際欄位，改 `create_audio()` 最後一行 |
| `Pipeline: description 6000 bytes，上限 5000 bytes（中文一字約 3 bytes）` | `snippet.description` 上限是**位元組**，中文一字約 3 bytes ≈ 只有 1600 字 | `clamp_bytes(s, 5000)` 先截，`validate-meta` 再擋；來源連結太多就截掉尾巴 |
| `Pipeline: 違反 AGENTS.md 節目調性，出現聳動詞彙：['震撼']` | LLM 沒照 `AGENTS.md` 寫 | 這是預期行為（程式碼的黑名單才是強制）；重跑 `meta` 步驟或手改 `build/meta.json` |
| 上傳回 200、影片存在，但 `privacyStatus=private` 且改不動 | 2020-07-28 之後建立、未通過稽核的 API 專案，`videos.insert` 上傳的影片被強制鎖成私人 | `check_privacy()` 讀回驗證讓流程失敗；送 Audit and Quota Extension Form 申請稽核 |
| 排程跑了一週後上傳步驟 401 `invalid_grant: Token has been expired or revoked.` | OAuth 同意畫面停在 Testing，refresh token 只有 7 天壽命 | 同意畫面 → Publishing status → **In production**，重新 `airadio auth` |
| `HttpError 403 ... insufficientPermissions` 在 `captions.insert` | `captions.insert` 需要 `youtube.force-ssl`，`youtube.upload` 不夠 | 一開始就同時要兩個 scope；事後追加要重走同意流程 |
| launchd 到了 06:00 什麼都沒發生，`/tmp/airadio.err` 是空的 | plist 用了相對路徑，launchd 不載入 shell 設定檔，spawn 直接失敗（errno 2） | `ProgramArguments` 第一個字串寫 `/Users/you/.local/bin/uv`，並在 plist 設 `PATH` |
| 影片接了片頭之後破圖／音訊不同步 | 片頭與主片的解析度、frame rate、音訊取樣率不一致就 concat | concat 前先各自 transcode 成同參數；或先不要片頭（`assets/intro.mp4` 不存在就跳過這步） |
| 當天第二次跑就說配額用盡 | 沒帶 `--resume`，state 被丟掉，生成步驟又送了一次（免費 3 次／日） | 續跑一律 `uv run airadio run --resume`；排程的 plist 裡也要有 |

---

## 完整解答

本目錄的 `ai-daily-radio/` 就是走完 12 步的版本：

| 檔案 | 內容 |
|---|---|
| `ai-daily-radio/src/airadio/run.py` | 整條產線（726 行）：`sh()` dry-run 攔截、`step()` 冪等閘門、fetch／notebook／studio／post／meta／upload、`--self-check` 7 項、`aha` 三張對照表 |
| `ai-daily-radio/src/airadio/__init__.py` | 只 re-export `cli` / `main` |
| `ai-daily-radio/pyproject.toml` | 依賴、`[project.scripts] airadio`、`[tool.hatch.build.targets.wheel]`（步驟 1 的坑） |
| `ai-daily-radio/feeds.toml` | 10 個 RSS 來源，`full_text` 標記決定排序優先 |
| `ai-daily-radio/AGENTS.md` | 節目調性＋產線硬規則（Antigravity 與 gemini CLI 共讀） |
| `ai-daily-radio/.agents/mcp_config.json` | 工作區層 `notebooklm-mcp` 設定＋收斂到 5 個工具 |
| `ai-daily-radio/tw.airadio.daily.plist` | launchd 範本（絕對路徑＋`PATH`＋`--resume`） |

學生卡住時再開。想自己寫的話，順序是：`step()` → `select_items()` → `validate_meta()` → `check_privacy()`，這四個函式就是 self-check 驗的東西。

---

## 想再往下玩

- **加分題（投影片 p.225）**：把 `build/podcast_norm.m4a` 產生 Podcast RSS（stdlib 的 `xml.etree.ElementTree` 就夠），並在描述裡自動附上上一集連結（`reports/` 裡有前一天的 video id）。
- **上字幕**：`uvx faster-whisper-cli build/podcast_norm.m4a --language zh --output_format srt` 產生有時間碼的 SRT，再 `uv run airadio captions --video-id $VIDEO_ID --file build/podcast_norm.srt --language zh-TW`。官方用來上傳「無時間碼逐字稿」的 `sync` 參數已 deprecated，一定要有時間碼。
- **用 Antigravity 省配額**：接上 `notebooklm-mcp` 後在 IDE 裡互動試不同 `--format` 與 `--style`，滿意了才寫進腳本（p.221 ②）。生成配額一天只有 3 次，用腳本試風格很快就沒了。
- **失敗通知**：`do_run()` 的 `finally` 裡接一行 `osascript -e 'display notification ...'`，cookie 過期時你會在早上就知道，而不是三天後。
- **下一站 M5／Lab 5**：把「抓取與 metadata」那半條產線搬到 Cloud Run（`nlm` 那段必須留在本機），順便學 Secret Manager 存 `token.json`——這正是投影片 p.219 說的混合作法。

---

## 這個 Lab 你真正學到的

- agent 的產出可以是一個檔案、一集節目、一支上架的影片——聊天視窗只是它眾多輸出裝置裡最不重要的那一個。
- 一條產線的工程量不在呼叫 AI（42 行），在讓那幾行能無人值守地活下去（185 行）：冪等、配額、憑證過期、沉默失敗。
- 同一份能力在 Google 生態系裡至少有兩個門面，MCP 給 agent 互動、CLI 給腳本無人值守；選哪個看的是「半夜有沒有人按確認」。
- 平台最貴的限制都不會報錯（zh-TW 不能調長度、未稽核專案鎖私人、description 上限是 bytes），所以自動化必須自己讀回來驗。
- 「自動化」在作業系統層面就是一個排程檔在對的時間 exec 一次指令，沒有任何常駐服務；換平台只換那個檔案。

---

## 清理

本 lab 沒有雲端資源會計費，但本機有東西要收：

```bash
launchctl bootout gui/$(id -u)/tw.airadio.daily          # 停排程
rm ~/Library/LaunchAgents/tw.airadio.daily.plist
rm -rf build state reports secrets                       # 產物與憑證（secrets 千萬別 commit）
uv tool uninstall notebooklm-mcp-cli
rm -rf ~/.notebooklm-mcp-cli                             # 連 cookie 一起清
# YouTube 上的測試影片自己去 Studio 刪；GCP 的 OAuth client 留著不收費，
# 但如果不再用，到 Console → 憑證 把它刪掉比較乾淨。
```
