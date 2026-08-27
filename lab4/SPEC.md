# Lab 4 SPEC：課程知識庫 × Agent 查詢

## 1. 架構

```
       策展（人工，瀏覽器）                 消費（agent / 腳本）
 ┌───────────────────────────┐   ┌──────────────────────────────────────┐
 │ notebook.google.com       │   │  Antigravity 桌面版                  │
 │  筆記本「Google AI Agent  │   │  ┌────────────────────────────────┐  │
 │            課程」          │   │  │ agent（Gemini 3.x）            │  │
 │  ├ ai.google.dev/...docs  │   │  └──────────────┬─────────────────┘  │
 │  ├ adk.dev                │   │   讀 ~/.gemini/config/mcp_config.json│
 │  ├ antigravity.google/docs│   │                 │ 啟動 stdio 子程序   │
 │  └ modelcontextprotocol.io│   └─────────────────┼────────────────────┘
 │  Studio: Audio Overview   │                     │
 └─────────────┬─────────────┘                     ▼
               │                    ┌───────────────────────────────┐
               │                    │ notebooklm-mcp（MCP server）  │
               │                    │  stdio：stdin/stdout = 協定    │
               │                    │  ~40 工具，disabledTools 過濾  │
               │                    └───────────────┬───────────────┘
               │                                    │
               │        ┌───────────────────────────┤
               │        │ 同一份 session 檔（cookie）│
               │        ▼                           ▼
               │  ┌──────────────┐        非官方內部 API（HTTPS）
               │  │ nlm CLI      │───────────────┐
               │  │ 人工維運＋驗收│                │
               │  └──────▲───────┘                │
               │         │ subprocess              │
               │  ┌──────┴───────┐                │
               │  │ wiki.py      │                │
               │  │ check/ask/   │                │
               │  │ sources      │                │
               │  └──────────────┘                │
               │                                   │
               └───────────────◀───────────────────┘
                  同一個知識庫，三種消費者
```

程序邊界：

- **Antigravity ↔ notebooklm-mcp**：同機、`stdio`。Antigravity 用 `command` 把它 fork 起來，stdin/stdout 是 MCP 協定通道（所以 server 端絕不能 `print()` 除錯，附錄 D ⑤）。
- **notebooklm-mcp / nlm ↔ NotebookLM**：跨網、HTTPS、**非官方內部 API**，靠 `nlm login` 存下來的瀏覽器 cookie 認證。兩者共用同一份 session 檔——所以 `nlm query` 能跑，agent 就能跑；`nlm query` 空回應，agent 也一定空回應。這是本 Lab 最重要的除錯槓桿。
- **wiki.py ↔ nlm**：`subprocess`，只讀 stdout/stderr/returncode。wiki.py 不自己碰 cookie、不自己打 HTTP。

## 2. 元件與職責

| 元件 | 型態 | 職責 | 誰擁有 |
|---|---|---|---|
| 筆記本「Google AI Agent 課程」 | NotebookLM 雲端資源 | 知識庫本體：來源、切塊、嵌入、檢索、行內引用全由它代勞 | Google（你的帳號空間） |
| `notebooklm-mcp-cli` | uv tool（社群，`jacob-bd/notebooklm-mcp-cli`） | 提供 `nlm` CLI（人用）＋ `notebooklm-mcp` server（agent 用），約 40 個工具 | 社群，非官方 |
| session 檔 | 本機憑證 | `nlm login` 擷取的瀏覽器 cookie，效期約 2–4 週；`nlm` 與 `notebooklm-mcp` 共用 | 你（等同帳號權限） |
| `~/.gemini/config/mcp_config.json` | JSON 設定檔 | 告訴 Antigravity 怎麼啟動 server、哪些工具要禁 | 你 |
| `mcp_config.json`（本目錄） | 範本 | 可直接抄的最小設定，已含 `disabledTools` | 本 Lab |
| `wiki.py` | Python 腳本（純 stdlib） | 離線檢查設定檔＋非互動式驗收查詢；`--self-check` 驗自己的邏輯 | 本 Lab |
| Antigravity agent | IDE 內的 LLM agent | 知識庫的主要消費端，寫碼時查規範 | 你 |

## 3. 介面契約

### 3.1 MCP 工具（節選，投影片 p.187）

Agent 會呼叫的工具，簽章以投影片為準：

| 類別 | 工具 | 用途 |
|---|---|---|
| 筆記本 | `notebook_list` / `notebook_create` / `notebook_get` | 列出、建立、讀取筆記本 |
| 來源 | `source_add` / `source_list` | 加 URL／文件、盤點來源 |
| 查詢 | **`notebook_query`** | 核心：對筆記本問答（帶引用）。想成「對你策展知識庫的 RAG API」 |
| 研究 | `research_start` | 發動 Deep Research，結果存成新來源 |
| 產出 | `studio_create` / `download_artifact` | 生成音訊／報告並下載 |
| 分享 | `notebook_share` | 調整分享權限 |
| **禁用** | `notebook_delete` / `source_delete` | 寫進 `disabledTools`，agent 看不到也叫不動 |

> ⚠️ 未實測：工具的**參數名稱**（例如 `notebook_query` 到底吃 `notebook_id` 還是 `id`）沒有離線可查的來源，本文件不編。要看真實 schema，接上後在 Antigravity 的 Settings → MCP Servers → notebooklm 展開工具清單，或 CLI 內 `/mcp`。

### 3.2 `nlm` CLI（投影片 p.185）

```bash
nlm login                                  # 開瀏覽器擷取 session
nlm logout
nlm notebook list                          # 列出所有筆記本
nlm source add <notebook_id> --url "https://adk.dev"
nlm source list <notebook_id>
nlm query <notebook_id> "ADK 的 session 有哪幾種實作？"
nlm setup add gemini                       # 一鍵寫入 IDE 的 MCP 設定（也支援 claude-code / cursor）
```

> ⚠️ 未實測：以上簽章抄自投影片 p.185，本機沒安裝這個工具，無法驗證 `source list` 是否真的存在或旗標名稱。跑之前先 `nlm --help` 對一次。

### 3.3 `wiki.py` 子指令

| 指令 | 連網？ | 行為 | exit code |
|---|---|---|---|
| `wiki.py --self-check` | 否 | assert 驗 `strip_jsonc` / `check_config` / `citations` / `scan_sources` / `report` | 0 過，assert 炸 = 1 |
| `wiki.py check [path]` | 否 | 檢查設定檔，逐行印 `[ERROR]` / `[WARN]` / `[OK]`。省略 path 用 `~/.gemini/config/mcp_config.json` | 有 ERROR 則 1 |
| `wiki.py notebooks` | 是 | `nlm notebook list` 的包裝 | nlm 失敗或空輸出則 1 |
| `wiki.py sources [--nb id]` | 是 | `nlm source list`，再掃有沒有未就緒的來源 | 有未就緒則 1 |
| `wiki.py ask "問題" [--nb id]` | 是 | `nlm query`，印答案與抽出的來源連結 | **回答沒有任何引用連結則 1** |

### 3.4 純函式簽章（`--self-check` 的驗證對象）

```python
strip_jsonc(text: str) -> str
# 移除 // 與 /* */ 註解、尾逗號。字串內的 // 不動（"http://a//b" 要活著）。

check_config(text: str, which=shutil.which) -> list[tuple[str, str]]
# 回傳 [(level, message)]，level ∈ {"ERROR", "WARN", "OK"}。
# which 可注入 → 離線也能測「PATH 上找不到執行檔」這條規則。

citations(answer: str | None) -> list[str]
# 從回答裡撈 http(s) 連結，去重保順序，去掉尾隨的中英文標點。

scan_sources(text: str | None) -> tuple[int, list[str]]
# (非空行數, 含 processing/pending/queued/failed/error/處理中/失敗 的行)
# 行數不是來源數：nlm 若印表頭就會多算，所以驗收只看「未就緒 0 筆」。

report(res, need_cite: bool = True) -> tuple[int, str]
# res 只需要有 .returncode / .stdout / .stderr（duck typing，
# 所以 self-check 用 types.SimpleNamespace 就能假造，不必真的跑 nlm）
```

### 3.5 `mcp_config.json` 契約（投影片 p.186 + 附錄 B）

```json
{
  "mcpServers": {
    "notebooklm": {
      "command": "notebooklm-mcp",
      "args": [],
      "disabledTools": ["notebook_delete", "source_delete"]
    }
  }
}
```

三條規則（附錄 B 的原話）：**遠端欄位叫 `serverUrl` 不是 `url`**、**改完要 Refresh**、**Google 服務用 `google_credentials` 走 ADC**。本 Lab 的 notebooklm 是 stdio 型，用 `command`，前兩條照樣適用（同一個檔案裡其他 server 常踩第一條）。

## 4. 資料模型

沒有自建 DB。三份持久化狀態：

| 狀態 | 位置 | 內容 | 備註 |
|---|---|---|---|
| 知識庫 | NotebookLM 雲端 | 筆記本 → 來源（URL／檔案）→ 切塊與嵌入 | 全託管，你看不到 schema，也不用管 |
| session | 本機（路徑依工具版本，`nlm login` 產生） | 瀏覽器 cookie | **等同帳號密碼**，`.gitignore` 掉 |
| MCP 設定 | `~/.gemini/config/mcp_config.json` | 見 3.5 | 全域，所有 Antigravity 專案共用 |
| 筆記本 ID | 環境變數 `NLM_NOTEBOOK_ID` | 字串 | 只是方便，不寫進檔案避免誤 commit |

## 5. 檔案結構

```
lab4/
├── PRD.md              產品需求：範圍、驗收、費用、前置依賴（含 Capstone 沿用說明）
├── SPEC.md             本文件：架構、介面契約、錯誤處理
├── walkthrough.md      一步一步教學（主要交付物）
├── mcp_config.json     可直接抄的最小 MCP 設定範本（已禁破壞性工具）
├── wiki.py             設定檔檢查器＋非互動式驗收查詢，純 stdlib，含 --self-check
├── pyproject.toml      uv init --bare --name lab4 生成，dependencies 是空的
└── uv.lock             uv run 第一次跑時生成
```

`wiki.py` 只用標準庫（`json` / `os` / `re` / `shutil` / `subprocess` / `sys` / `pathlib`），所以 `dependencies = []`。有 `pyproject.toml` 就不要再加 PEP 723 檔頭（重複）。

## 6. 環境變數與設定

| 變數／設定 | 用途 | 從哪來 | 預設 |
|---|---|---|---|
| `NLM_NOTEBOOK_ID` | `wiki.py ask` / `sources` 要查哪一本 | `uv run wiki.py notebooks` 的輸出 | 無，缺了就 exit 並提示 |
| `--nb <id>` | 蓋掉環境變數，臨時查另一本（加分題的跨筆記本查詢） | 你 | 無 |
| `~/.gemini/config/mcp_config.json` | Antigravity 全域 MCP 設定 | 你手寫，或 `nlm setup add gemini` 寫 | 檔案可能不存在，要自己建目錄 |
| session 檔 | cookie 認證 | `nlm login` | 無，缺了所有查詢都空 |
| `GEMINI_API_KEY` | **本 Lab 不需要** | — | — |

## 7. 執行流程

```bash
# ── 0. 專案（本目錄已經 init 好，重建才需要）
cd /Users/awesomeartengineer01/Antigravity-teach/lab4
uv init --bare --name lab4          # 只有重建時才跑
uv run wiki.py --self-check         # → self-check 全過

# ── 1~3. 瀏覽器：notebook.google.com
#   建筆記本「Google AI Agent 課程」→ 加 4 個 URL 來源
#   → 等來源都變成就緒 → 試問三題確認有引用
#   → Studio → Audio Overview，主題「給初學者的 MCP 介紹」

# ── 4. CLI
uv tool install notebooklm-mcp-cli
uv tool update-shell                 # 讓 nlm 進 PATH（新開一個終端機）
nlm login                            # 開瀏覽器擷取 session
nlm notebook list                    # 抄下你的 notebook id
export NLM_NOTEBOOK_ID=<id>
uv run wiki.py sources               # → 掃了 N 行，未就緒 0 筆
uv run wiki.py ask "Interactions API 與 generateContent 的差異？"

# ── 5. 接進 Antigravity
mkdir -p ~/.gemini/config
cp mcp_config.json ~/.gemini/config/mcp_config.json    # 已有檔案就手動合併 mcpServers
uv run wiki.py check                 # → [OK] notebooklm server：notebooklm
# Antigravity → Settings → MCP Servers → Refresh

# ── 6. 整合驗收
# Antigravity 裡下 prompt：
#   「查課程知識庫，總結 ADK 部署的三種方式，附引用」
uv run wiki.py ask "ADK 部署的三種方式？"   # 同一條路徑的非互動式驗收
```

## 8. 錯誤處理與邊界

| 情境 | 症狀 | 處理方式 |
|---|---|---|
| `nlm` 不在 PATH | `wiki.py` 印 `找不到 nlm：uv tool install notebooklm-mcp-cli && uv tool update-shell` 並 exit 1 | 先 `shutil.which("nlm")` 判斷，不讓 `subprocess` 丟裸的 `FileNotFoundError` |
| session 過期 | `nlm` returncode 0 但 stdout 空 | `report()` 把「exit 0 + 空輸出」也算失敗，訊息直接叫你 `nlm login`。**這是最常見也最難察覺的失敗**，因為它不報錯 |
| 來源還沒 embed 完 | 回答變成「來源中找不到」或沒有引用 | `sources` 掃 processing/pending/failed；`ask` 在零引用時 exit 1 |
| 設定檔帶 `//` 註解 | `json.loads` 丟 `Expecting property name enclosed in double quotes` | `strip_jsonc` 先洗過再 parse。本目錄範本刻意不帶註解（Antigravity 是否容忍註解 ⚠️ 未實測，`python -m json.tool` 確定不容忍） |
| 設定檔有尾逗號 | `Illegal trailing comma before end of object` | `strip_jsonc` 尾端一個 regex 清掉 |
| 遠端 server 寫成 `url` | Antigravity 靜默不連線，工具清單是空的 | `check_config` 判定 ERROR（附錄 D 易錯坑 ④） |
| `disabledTools` 忘了寫 | 沒有症狀——直到 agent 某天刪掉你的來源 | `check_config` 判定 WARN，訊息寫明後果 |
| 設定檔存在但沒有 `mcpServers` | Antigravity 一個 server 都不載入 | `check_config` 判定 ERROR 並提早 return |
| 改完設定沒 Refresh | agent 說「沒有 notebooklm 這個工具」 | 這是 UI 步驟，程式檢查不到；walkthrough 用「先失敗再修」演一次 |
| 問題超出來源範圍 | 回「來源中找不到相關資訊」 | **這是正確行為，不是 bug**。source-grounded 的價值就在這裡 |
| 回答有引用但連結點不開 | 來源 URL 已失效 | 人工修剪來源（p.191 每月修剪） |
| `nlm` 輸出格式改版 | `scan_sources` 的關鍵字掃描失準 | 已知限制，見 §10 |

## 9. 驗證方式

**離線可驗（已實際跑過）：**

```bash
uv run wiki.py --self-check              # → self-check 全過
uv run wiki.py check mcp_config.json     # → [WARN] PATH 上找不到 ...  [OK] notebooklm server：notebooklm
uv run python -m json.tool mcp_config.json   # 範本是合法 JSON（沒有註解）
uv run python -c "import ast;ast.parse(open('wiki.py').read());print('ok')"
```

`--self-check` 涵蓋：投影片那份帶註解＋尾逗號的 config 能被解開、字串內的 `//` 不被誤砍、跳脫字元不破壞字串邊界、缺 `disabledTools` → WARN、執行檔不在 PATH → WARN、`url` 誤用 → ERROR、沒有 notebooklm server → ERROR、壞 JSON → ERROR、空 config → ERROR、引用去重與尾標點、來源狀態掃描、`report()` 的三種失敗（非零 exit／空輸出／零引用）。假物件用 `types.SimpleNamespace`，`which` 用 lambda 注入，**完全不連網、不需要登入、不花錢**。

**要人看的（無法自動化）：**

- 網頁版回答的行內引用是否指向正確段落（點開比對）
- Audio Overview 的內容是否真的在講 MCP
- Antigravity Settings → MCP Servers 的連線狀態與工具清單

**無法離線驗證的（本文件已標 ⚠️）：**

> ⚠️ 未實測：`nlm` 的實際指令旗標與輸出格式、MCP 工具的參數 schema、`notebooklm-mcp` 與 Antigravity 的握手行為、Audio Overview 的生成時間。理由：本機沒有安裝 `notebooklm-mcp-cli`（`which nlm` → not found），而安裝後仍需要真實 Google 帳號登入才能跑任何指令。所有相關敘述抄自投影片 p.185–p.187，未經執行驗證。

## 10. 已知限制與升級路徑

| 限制 | 程式碼位置 | 升級路徑 |
|---|---|---|
| `strip_jsonc` 是一次掃描的小狀態機，不處理跨行字串等變態情況 | `wiki.py` 的 `# ponytail:` 註解 | 真的需要嚴謹解析就 `uv add json5`；設定檔這種規模沒必要 |
| `scan_sources` 靠關鍵字掃 `nlm` 的人類可讀輸出，上游改版就失準 | `wiki.py` 的 `# ponytail:` 註解 | 等 `nlm` 提供 `--json` 就改成 parse JSON |
| `citations` 只認 `http(s)://` 開頭的裸連結；純編號引用（`[1]` 沒附 URL）抓不到 | `citations()` | 要精確就得知道 `nlm query` 的引用格式，等 `--json` 輸出 |
| `check_config` 認 server 的方式是「server 名字／command／args 裡有 notebooklm 字樣」 | `check_config()` | 夠用了。要嚴謹就對照 `nlm setup add gemini` 實際寫出來的 key |
| 整條路徑走非官方 API | 架構層級 | Enterprise：Discovery Engine 官方 REST API（p.181）＋自己用 FastMCP 包一個正式 server（M6） |
| 不能接受非官方工具時 | 架構層級 | 把筆記匯出成 Markdown，用 filesystem MCP＋自建 RAG（M8）（p.188 替代方案） |
| `wiki.py` 每次都 fork 一個 `nlm` 程序，沒有連線重用 | `run_nlm()` | 驗收腳本一次跑幾題，不值得優化 |
