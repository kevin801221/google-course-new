# Lab 3.5 SPEC：讓兩個 Agent 共用一份會長大的記憶（CivicGuard）

## 1. 架構

```
┌──────────────────────────┐          ┌──────────────────────────┐
│  Antigravity 2.0 / agy   │          │  Gemini CLI 0.56.x       │
│  互動開發·規劃·瀏覽器驗證 │          │  headless·CI·排程        │
│                          │          │  + data-scout subagent   │
│  讀 AGENTS.md（原生）     │          │  讀 context.fileName      │
└──────┬───────────┬───────┘          └──────┬───────────┬───────┘
       │ 讀        │ 寫（知識/決策層）        │ 讀        │ 寫（知識/決策層）
       ▼           ▼                        ▼           ▼
┌─────────────────────────────────────────────────────────────────┐
│  記憶層（唯一共享的東西＝純 Markdown 文字，進版控）              │
│                                                                 │
│   AGENTS.md  ← 契約層，只有人類能改（PR 審核）                   │
│      │ @import                                                  │
│      ├── docs/domain/cwa-api-notes.md    ← 知識層，Agent 可直接寫 │
│      ├── docs/domain/alert-taxonomy.md                          │
│      ├── docs/domain/shelter-quirks.md                          │
│      └── memory/decisions.md             ← 決策層，append-only   │
└─────────────────────────────────────────────────────────────────┘
       ▲                                              ▲
       │ 不共享：設定檔各自一份                         │
┌──────┴────────────────────┐          ┌──────────────┴──────────┐
│ .agents/                  │          │ .gemini/                │
│  rules/*.md（always_on）   │          │  settings.json          │
│  mcp_config.json          │          │  commands/*.toml        │
│  skills/*/SKILL.md        │          │  agents/data-scout.md   │
└───────────────────────────┘          └─────────────────────────┘

工具層（兩邊都用同一份 stdio 設定，程序邊界在這裡）
┌─────────────────────────────────────────────────────────────────┐
│ uv run civicguard-mcp   ── stdio ──▶ MCPServer("civicguard")     │
│    tools: active_alerts / normalize_shelters / daily_brief       │
│ uv run civicguard-audit ── stdout JSON ──▶ jq -e ──▶ CI exit code│
└──────────────────────────────┬──────────────────────────────────┘
                               │ HTTPS（urllib，stdlib）
                               ▼
                    中央氣象署 open data / 各縣市避難所開放資料
```

**兩條接線各一行設定**：Antigravity 端零設定（v1.20.3 起原生讀 `AGENTS.md`）；
Gemini CLI 端只加 `context.fileName`。共享的只有 Markdown，設定檔、對話紀錄、產出物一律不共享。

## 2. 元件與職責

| 元件 | 檔案 | 職責 | 誰會呼叫 |
|---|---|---|---|
| 契約 | `AGENTS.md` | 專案概要、uv 強制規則、測試指令、記憶契約表、`@import` 四份子檔 | 兩支 CLI 每次提問自動帶上 |
| 轉接 | `GEMINI.md` | 只有兩行，`@./AGENTS.md`，給還沒支援 `AGENTS.md` 的工具 | Gemini CLI |
| 知識 | `docs/domain/*.md` | 會長大的領域知識：API 踩雷、分級規則、縣市欄位差異 | 被 `@import`；Agent 可直接寫 |
| 決策 | `memory/decisions.md` | append-only 交接紀錄，D-00x 編號可互相引用／取代 | 兩個 Agent 都寫 |
| 特報查詢 | `src/civicguard/cwa.py` | 打 CWA API、parse 特報（stdlib urllib，不需要 httpx） | MCP server、`civicguard-fetch` |
| 避難所正規化 | `src/civicguard/shelters.py` | 22 縣市欄位別名壓成同一 schema（D-007） | MCP server、`civicguard-shelters` |
| 簡報產生 | `src/civicguard/brief.py` | 雨量分級 ＋ 人話文案，不四捨五入（D-008） | MCP server、`civicguard-brief` |
| uv 稽核器 | `src/civicguard/audit.py` | 字面掃出 pip／venv／裸 python 殘留，JSON 輸出、非零退出 | `scripts/ci_audit.sh`、`/audit` |
| MCP server | `src/civicguard/mcp_server.py` | 把上面三個包成 MCP tools（stdio） | Gemini CLI、Antigravity |
| 排程腳本 | `scripts/daily_brief.sh` | 抓資料→gemini 產簡報→空檔就失敗 | GitHub Actions |
| CI 稽核 | `scripts/ci_audit.sh` | 第一層字面（確定性）＋第二層語意（gemini） | GitHub Actions |
| Subagent | `.gemini/agents/data-scout.md` | 獨立上下文探查 API 真實結構，只讀不寫 `src/` | 主 agent 當工具呼叫 |
| Antigravity 規則 | `.agents/rules/*.md` | `always_on` 掛上 uv 規則與領域文件引用 | Antigravity |

## 3. 介面契約

### 3.1 Python 函式簽章

```python
# civicguard/cwa.py
DATASET = "W-C0033-001"                       # 天氣特報 dataset id
def fetch(city: str, api_key: str | None = None, timeout: int = 20) -> dict
def parse_alerts(payload: dict, city: str) -> list[dict]
#   回傳元素：{"city","phenomena","significance","start","end"}

# civicguard/shelters.py
ALIASES: dict[str, tuple[str, ...]]           # 目標欄位 -> 各縣市別名
def normalize(row: dict) -> dict              # -> {name,district,address,capacity,note}
def normalize_all(rows: list[dict]) -> list[dict]

# civicguard/brief.py
RAIN_LEVELS = ((350.0,"超大豪雨"),(200.0,"大豪雨"),(80.0,"豪雨"),(40.0,"大雨"),(0.0,"無"))
def rain_level(mm: float) -> str              # 用原始值比門檻，不四捨五入
def make_brief(city: str, alerts: list[dict], rain_mm: float, shelters: list[dict]) -> str

# civicguard/audit.py
RULES: list[tuple[str, str, str]]             # (規則名, 正則, 建議改法)
def scan_text(text: str, path: str = "-") -> list[dict]
def scan_repo(root: str = ".") -> list[dict]
#   回傳元素：{"file","line","rule","text","fix"}
```

### 3.2 MCP 工具 schema

server 名稱 `civicguard`（**不含底線**：工具全名是 `mcp_<server>_<tool>`，
解析器在 `mcp_` 之後的第一個底線切開，名稱含底線會被切錯位、且不會報錯）。

| 工具 | 參數 | 回傳 | 說明 |
|---|---|---|---|
| `active_alerts` | `city: str` | `list[dict]` | 某縣市目前生效特報。city 用「臺」不用「台」 |
| `normalize_shelters` | `rows: list[dict]` | `list[dict]` | 正規化避難所欄位（D-007） |
| `daily_brief` | `city: str`, `rain_mm: float = 0.0` | `str` | 150 字內人話簡報，數值原始精度（D-008） |

> ⚠️ mcp 2.x 已把 `FastMCP` 改名為 `MCPServer`（`from mcp.server.mcpserver import MCPServer`）。
> 投影片寫的 `FastMCP` 是 mcp 1.x 的名字。實測 `mcp==2.1.1` 用舊名 import 會直接 `ModuleNotFoundError`。

### 3.3 稽核器輸出契約

```jsonc
// uv run civicguard-audit --json
[
  {"file": ".github/workflows/brief.yml", "line": 14, "rule": "pip-install",
   "text": "- run: pip install -r requirements.txt", "fix": "改用 uv add <pkg>"}
]
// 乾淨時輸出 []，exit 0；有任何一條 exit 1
```

exit code 約定（與 Gemini CLI 的 headless 一致的用法）：`0` 乾淨、`1` 有殘留。
Gemini CLI 自己的 exit code：`0` 成功、`1` 一般錯誤／API 失敗、`42` 輸入錯誤、`53` 超過回合上限。

### 3.4 Gemini CLI headless 契約

```bash
gemini -p "<prompt>" --output-format json   # {"response": "...", "stats": {...}}
gemini -p "<prompt>" --output-format json | jq -r '.response'
```

只用 `-o json` 取 `.response` 做判斷、用 exit code 決定 job 成敗，**不要 parse 人類可讀的 text 輸出**。

## 4. 資料模型

沒有資料庫。三個「state」都是檔案：

| 檔案 | 格式 | 命名約定 |
|---|---|---|
| `memory/decisions.md` | Markdown，`## D-00x <一句話標題>` | 編號單調遞增、append-only；欄位固定為 日期／提出／執行／背景／決定／影響／取代 |
| `docs/domain/cwa-api-notes.md` | 編號條目 `## N. <症狀>` | 每條三段：症狀 → 真相 → 什麼時候會踩到 → 對策 |
| `docs/domain/shelter-quirks.md` | 欄位對照表 | 目標欄位固定 `name／district／address／capacity／note`；新縣市只加別名字串 |

正規化後的避難所 record（`normalize()` 的輸出，也是下游唯一認可的形狀）：

```python
{"name": str, "district": str, "address": str,
 "capacity": int | str,     # 純數字轉 int；「約 300 人」保留原字串以利追溯
 "note": str}               # 從「地址及備註」切出來的備註
```

## 5. 檔案結構

```
lab3.5/                          ← 本目錄就是 uv 專案 civicguard（用 --name 指定）
├── AGENTS.md                    # 契約層：單一事實來源，兩邊共讀
├── GEMINI.md                    # 兩行轉接，@./AGENTS.md
├── README.md
├── PRD.md / SPEC.md / walkthrough.md   # 教材，稽核器刻意跳過（裡面寫滿反例）
├── pyproject.toml               # name = "civicguard"，5 個 console scripts
├── uv.lock                      # 提交進版控
├── .python-version              # 3.13
├── .gitignore                   # .gemini/.env、data/、reports/、快取
├── .gemini/
│   ├── settings.json            # context.fileName / autoMemory / mcpServers
│   ├── commands/brief.toml      # /brief 台南市
│   ├── commands/audit.toml      # /audit
│   └── agents/data-scout.md     # subagent：只讀，不改 src/
├── .agents/                     # Antigravity 側（是 .agents 不是 .antigravity）
│   ├── rules/uv-only.md         # activation: always_on
│   ├── rules/domain-cwa.md      # 再引用一次 docs/domain（Antigravity 不保證展開 AGENTS.md 的 @import）
│   ├── skills/shelter-normalize/SKILL.md
│   └── mcp_config.json          # 獨立檔；stdio 設定與 .gemini 那份相同
├── .github/workflows/brief.yml  # 每天台北 06:00 排程
├── docs/domain/
│   ├── cwa-api-notes.md         # 知識層：API 踩雷筆記
│   ├── alert-taxonomy.md        # 知識層：分級規則 ＋ 不得四捨五入
│   └── shelter-quirks.md        # 知識層：22 縣市欄位差異
├── memory/decisions.md          # 決策層：D-007、D-008…
├── scripts/
│   ├── daily_brief.sh           # 抓資料 → gemini 產簡報
│   └── ci_audit.sh              # 兩層稽核，任一層失敗就非零
├── src/civicguard/
│   ├── __init__.py
│   ├── cwa.py                   # 特報查詢＋parse（含 Locations 欄位坑）
│   ├── shelters.py              # 避難所欄位正規化（D-007）
│   ├── brief.py                 # 分級＋文案（D-008）
│   ├── audit.py                 # uv-only 稽核器
│   └── mcp_server.py            # MCP stdio server
└── tests/test_selfchecks.py     # 把五支 --self-check 收成 pytest
```

## 6. 環境變數與設定

| 變數 | 用途 | 從哪來 | 預設 |
|---|---|---|---|
| `GEMINI_API_KEY` | Gemini CLI 認證（本課唯一路徑） | <https://aistudio.google.com/apikey> | 無，缺了 `gemini -p` 直接失敗 |
| `CWA_API_KEY` | 中央氣象署 open data Authorization | <https://opendata.cwa.gov.tw> 免費註冊 | 無，缺了只影響真的打 API |
| `GOOGLE_GENAI_USE_VERTEXAI` | 改走 Vertex AI | 手動 export | 未設 |
| `GOOGLE_CLOUD_PROJECT` / `_LOCATION` | Vertex AI 專案與區域 | GCP（M5） | 未設 |
| `GEMINI_SANDBOX` | 開沙箱 | 手動 | 未設 |

金鑰放 `.gemini/.env`（不會被其他工具的 `.env` 規則干擾），並且**一定要進 `.gitignore`**。
MCP 設定裡用 `"$CWA_API_KEY"` 變數展開，不要寫死值。

Gemini CLI 認證 auto-detect 順序（沒明示時）：
`GOOGLE_GENAI_USE_GCA` → `GOOGLE_GENAI_USE_VERTEXAI` → `GOOGLE_GEMINI_BASE_URL` → `GEMINI_API_KEY` → `CLOUD_SHELL`。
要走 ADC 就得先 `unset GEMINI_API_KEY GOOGLE_API_KEY`，否則第 4 條會搶先命中。

`settings.json` 常用鍵（優先序由低到高：內建預設 → system-defaults → `~/.gemini/settings.json` → 專案 → system → 環境變數 → 命令列參數）：

| 鍵 | 本 lab 設成 | 作用 |
|---|---|---|
| `context.fileName` | `["AGENTS.md","GEMINI.md"]` | 記憶檔名，預設只讀 `GEMINI.md` |
| `experimental.autoMemory` | `true` | Auto Memory，改完要**重開 CLI** |
| `general.checkpointing.enabled` | `true` | 開了才有 `/restore` |
| `general.defaultApprovalMode` | `default` | `yolo` 只能用旗標給 |
| `mcpServers` | `civicguard` | **頂層物件**，不是巢狀在 `mcp` 底下 |

## 7. 執行流程

```bash
# 0) 前置
node --version                     # >= 20
npm install -g @google/gemini-cli && gemini --version    # 0.56.x
export GEMINI_API_KEY="..."        # 或寫進 .gemini/.env

# 1) 骨架（本目錄名有小數點，一定要用 --name）
uv init lab3.5 --package --name civicguard --python 3.13 && cd lab3.5
uv add "mcp[cli]" httpx google-genai
uv add --dev pytest ruff
mkdir -p docs/domain memory scripts .gemini/commands .gemini/agents .agents/rules tests

# 2) 記憶：AGENTS.md ＋ 三份 docs/domain ＋ memory/decisions.md（見 walkthrough 步驟 3）

# 3) 接線
printf '%s' '{"context":{"fileName":["AGENTS.md","GEMINI.md"]}}' > .gemini/settings.json
printf '@./AGENTS.md\n' > GEMINI.md

# 4) 驗證記憶真的載到
gemini -p "這個專案安裝套件要用什麼指令？只回一行。"      # → uv add <pkg>

# 5) 程式碼與檢查
uv run civicguard-mcp --self-check
uv run pytest -q                                        # 5 passed
uvx ruff check .                                        # All checks passed!

# 6) 稽核（CI 把關）
uv run civicguard-audit --json | jq -e 'length == 0'
bash scripts/ci_audit.sh

# 7) 交接驗證
gemini -p "D-008 是什麼？我要修掉它，先講你要動哪幾個檔。"
```

## 8. 錯誤處理與邊界

| 情境 | 症狀 | 處理方式 |
|---|---|---|
| 用 `python xxx.py` 而不是 `uv run` | `ModuleNotFoundError: No module named 'mcp'` | 一律 `uv run`；規則寫進 `AGENTS.md`，並讓 `civicguard-audit` 在 CI 擋 |
| `uv init` 沒給 `--name` | 專案名變成 `lab3-5`、套件目錄變成 `src/lab3_5/`，`civicguard-*` 指令全都不存在 | 一定要 `--name civicguard` |
| mcp 2.x 用舊名 import | `ModuleNotFoundError: No module named 'mcp.server.fastmcp'. This is mcp 2.x, where FastMCP was renamed to MCPServer…` | 改 `from mcp.server.mcpserver import MCPServer`，或 `uv add "mcp<2"` |
| CWA 欄位改名 | 不報錯，`parse_alerts` 永遠回 `[]`（舊欄位存在但恆為空陣列）；欄位整個不存在時 `KeyError: 'location'` | `recs.get("Locations") or recs.get("location") or []`，並用 self-check 斷言至少 1 筆 |
| 縣市名打「台」 | 回傳空陣列，看起來像沒特報 | 官方資料用「臺」：`fetch()` 與 `parse_alerts()` 進來就 `city.replace("台", "臺")`，再用 `in` 寬鬆比對；self-check 有 `parse_alerts(payload, "台南市")` 的斷言 |
| MCP stdio server 用 `print()` 除錯 | 連線壞掉、Agent 顯示 server 掛了 | stdout 是協定通道，訊息一律 `file=sys.stderr` |
| MCP server 名稱含底線 | 工具名被切錯位，Agent 叫不到工具，**不會報錯** | server 名稱不含底線；`mcp_server.py` 的 self-check 有斷言 |
| 模型把 JSON 包在 ```` ```json ```` 圍籬裡 | `jq: parse error: Invalid numeric literal at line 2, column 0` | prompt 明寫「只輸出 JSON」，並在管線裡 `sed` 掉圍籬 |
| 稽核器誤報規則本身 | `AGENTS.md` 裡「禁止 pip install」那行被自己抓出來 | 用行內 `uv-ok` 標記豁免（Markdown 寫成 `<!-- uv-ok -->`，渲染後看不見） |
| 缺 `CWA_API_KEY` | MCP server 啟動時 stderr 警告，呼叫 `active_alerts` 才失敗 | 允許 server 起來（工具列表仍可探索），呼叫時才 `sys.exit` 給明確訊息 |
| 遠端 MCP 設定直接複製 | Antigravity 看不到 server，無錯誤訊息 | Gemini CLI 用 `url`／`httpUrl`，Antigravity 只吃 `serverUrl`；stdio 才能無腦共用 |
| `decisions.md` 無限長大 | 每次提問都送出，吃掉上下文、費用上升 | 已結案的搬 `decisions-archive.md`，**且不要 `@import` 它** |
| 改了 `AGENTS.md` 但 CLI 沒吃到 | Agent 還在講舊規則 | `/memory reload`；`experimental.autoMemory` 改動要重開 CLI |

## 9. 驗證方式

| 層次 | 怎麼跑 | 預期 |
|---|---|---|
| 單元（離線、不花錢） | `uv run civicguard-{fetch,shelters,brief,audit,mcp} --self-check` | 各印 `... self-check ok` |
| 全部單元 | `uv run pytest -q` | `5 passed` |
| 風格 | `uvx ruff check .` | `All checks passed!` |
| CI 把關 | `uv run civicguard-audit --json \| jq -e 'length == 0'` | `true`，exit 0 |
| Shell 語法 | `bash -n scripts/daily_brief.sh scripts/ci_audit.sh` | 無輸出 |
| JSON 設定 | `jq -e . .gemini/settings.json .agents/mcp_config.json` | 印出內容，exit 0 |
| 記憶載入 | 互動模式 `/memory list`、`/memory show` | 看到 `AGENTS.md` 與三份 `docs/domain` |
| 跨工具一致 | 同一問題問 `gemini -p` 與 Antigravity | 兩邊都回 `uv add` |
| 交接 | 新 session 只說「修掉 D-008」 | Agent 不問背景就能指出要動哪些檔 |

**離線驗不到的部分**（本 lab 已在文件內逐處標 `> ⚠️ 未實測`）：

- `gemini` CLI 的所有互動（`/memory list`、`-p`、`--output-format json`、exit code 42／53）——本機沒安裝 gemini CLI，也需要 `GEMINI_API_KEY`。
- Antigravity 端的原生 `AGENTS.md` 讀取、`always_on` rules 生效與否。
- Antigravity 是否展開根目錄 `AGENTS.md` 內的 `@import`（官方沒文件化，所以 `.agents/rules/domain-cwa.md` 再引用一次當保險）。
- CWA open data 的真實回應欄位（需要 `CWA_API_KEY`）；`parse_alerts` 的形狀假設以投影片為準。
- `data-scout.md` 的 `model: gemini-3.7-flash` 與 `cwa.py` 的 `DATASET = "W-C0033-001"`：型號名／dataset id 照抄投影片（p.147／p.144），未實際打通。404 就用 `client.models.list()` 或 opendata.cwa.gov.tw 查現行值。
- GitHub Actions workflow 實際執行。
- Auto Memory 的抽取與 `/memory inbox`（觸發條件是 session 閒置 ≥ 3 小時且 ≥ 10 則使用者訊息）。

## 10. 已知限制與升級路徑

| 限制 | 位置 | 升級路徑 |
|---|---|---|
| 稽核器的 include／skip 是寫死的清單 | `audit.py` `# ponytail:` 註解 | 真的有第二個專案要用時再做成 `.uvauditignore` |
| 稽核是純正則字面比對，改個寫法就繞得過 | `audit.py` `RULES` | 語意層交給 `scripts/ci_audit.sh` 的第二層 gemini 稽核；要更嚴就補 `.gemini/hooks/hooks.json`（p.137 第③層防線） |
| 教材三檔（PRD/SPEC/walkthrough）被稽核跳過 | `audit.py` `SKIP_FILES` | 這是刻意的：教材必須能寫反例。真實專案把 `SKIP_FILES` 清空 |
| `shelters.ALIASES` 只覆蓋台南／高雄／宜蘭三種形狀 | `shelters.py` | 用 headless 批次跑其餘 19 縣市，把新別名加進 `ALIASES` 與 `shelter-quirks.md` |
| `capacity` 髒資料保留原字串，型別不穩定 | `shelters.py` | 下游要算總量時再加一層 `parse_capacity()`，別在正規化階段猜 |
| `cwa.parse_alerts` 的回應形狀是推測 | `cwa.py`、`docs/domain/cwa-api-notes.md` | 用 `@data-scout` 打一次真實 API，對照後更新文件與 parser |
| 沒有 hook 攔截 `pip` | 無檔案 | p.137 的 `PreToolUse` hook：偵測到 `pip install` 就拒絕並回傳等價 uv 指令，Agent 會自己改寫重試 |
| `decisions.md` 會隨時間吃掉上下文 | `memory/decisions.md` | 封存到 `decisions-archive.md` 且不 `@import` |
| 遠端 MCP 設定要寫兩份 | `.gemini/settings.json` vs `.agents/mcp_config.json` | 寫一支腳本從單一來源產生兩份（`url`/`httpUrl` vs `serverUrl`） |
