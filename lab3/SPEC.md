# Lab 3 SPEC：讓 Agent 工程化你的 Lab 2 專案

> 這份 SPEC 描述的「系統」有兩半：**Antigravity 這個 host 怎麼讀你的設定檔**（你控制不了它的實作，但要知道它讀什麼、優先序如何），以及**你要交付的四個檔案**（你完全控制）。

## 1. 架構

```
┌─────────────────────────────────────────────────────────────────────┐
│ Antigravity 2.0 桌面 App（Agent Manager = mission control）          │
│                                                                     │
│   你 ──派任務/留言──▶ ┌───────────────────────────┐                 │
│                       │  Agent（gemini-3.7-flash） │                 │
│   Inbox ◀──通知────── │  effort: low/medium/high   │                 │
│                       └────┬──────┬──────┬────────┘                 │
│                            │      │      │                          │
│         三大 surface ───────┤      │      └──────────────┐           │
│                            ▼      ▼                     ▼           │
│                     ┌──────────┐ ┌──────────┐   ┌───────────────┐   │
│                     │ Editor   │ │ Terminal │   │ Browser       │   │
│                     │ 讀寫檔案 │ │ npm run  │   │ 隔離 Chrome   │   │
│                     └────┬─────┘ └────┬─────┘   │ profile       │   │
│                          │            │         └───┬───────────┘   │
│                          │            │             │ 截圖 + webm   │
│   Artifacts ◀────────────┴────────────┴─────────────┘               │
│   （task.md / implementation_plan.md / walkthrough.md / *.webm）     │
│                            ▲                                       │
│                            │ 留言（回饋被吸收，不中斷執行）         │
│                            │                                       │
│   MCP client ──stdio─▶ npx @modelcontextprotocol/server-github ──▶ GitHub API
└──────────┬──────────────────────────────────────────────────────────┘
           │ 讀設定（啟動時 + refresh 時）
           ▼
你的專案資料夾（= Antigravity Project 邊界，出了這個範圍 agent 碰不到）
├── AGENTS.md                      ← 優先序 3：跨工具開放標準
├── .agents/rules/style.md         ← 優先序 4：專案內規則（Always On）
├── .agents/mcp_config.json        ← 專案層 MCP（團隊/CI 共享用這個）
├── docs/evidence/*.webm|png       ← 你從 Artifacts 另存的驗證證據
└── src/                           ← agent 寫的功能程式碼（你不手打）

~/.gemini/GEMINI.md                ← 優先序 2：全域規則（跟 Gemini CLI 共用，會互相滲透）
~/.gemini/config/mcp_config.json   ← 全域 MCP
```

規則優先序（投影片 p.106，數字小的贏）：

| 層級 | 檔案 | 適用範圍 |
|---|---|---|
| 1（最高） | System rules（產品內建） | 不可覆蓋 |
| 2 | `~/.gemini/GEMINI.md` | 你的全域規則 |
| 3 | `AGENTS.md`（根目錄＋巢狀目錄） | 開放標準，跨工具共用 |
| 4 | `.agents/rules/*.md` | 專案內規則 |

## 2. 元件與職責

| 元件 | 職責 | 誰產生 |
|---|---|---|
| `AGENTS.md` | 專案的「事實表」：怎麼裝、怎麼跑、怎麼驗、禁區。跨工具（Antigravity／agy／Gemini CLI）共用一份 | 你（本 Lab 提供樣板） |
| `.agents/rules/style.md` | 常駐行為準則：型別、註解語言、完成條件。Always On 表示每次任務都掛上 | 你（本 Lab 提供樣板） |
| `.agents/mcp_config.json` | 宣告可用的 MCP server（本 Lab：GitHub），含傳輸方式、認證、工具黑名單 | 你（本 Lab 提供樣板） |
| `check_lab3.py` | 驗收：把上面三個檔案的「格式正確／設定沒踩雷／證據存在／已推上 remote」變成 exit code | 本 Lab 提供 |
| `implementation_plan.md` | agent 動工前的計畫書，你在上面留言 | agent |
| `walkthrough.md`（agent 版） | 完工報告：改了什麼、怎麼驗、附截圖與錄影 | agent |
| `docs/evidence/` | 你從 Artifacts 另存的錄影／截圖，讓驗收離開 Antigravity 也成立 | 你（複製） |

## 3. 介面契約

### 3.1 rule 檔（`.agents/rules/*.md`）

| 項目 | 契約 |
|---|---|
| 格式 | Markdown，UTF-8 |
| 大小 | 單檔 ≤ 12,000 字元（投影片 p.104） |
| 啟用模式 | 檔內註解宣告，四選一：`Always On` / `Manual`（@提及才用）/ `Model Decision` / `Glob`（如 `*.tsx`） |
| 引用其他檔 | `@filename`，例 `@.agents/rules/style.md` |
| 寫法 | 用「必須／禁止／一律／不得」，不要「盡量」 —— 模糊字眼 agent 會自行取捨 |

### 3.2 `mcp_config.json`

```jsonc
{
  "mcpServers": {
    "<name>": {
      // stdio 型（二選一）
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "env":  { "GITHUB_PERSONAL_ACCESS_TOKEN": "$GITHUB_PAT" },
      "cwd":  "/optional/working/dir",

      // 遠端型（二選一）——欄位叫 serverUrl，不是 url
      "serverUrl": "https://api.example.com/mcp/",
      "headers":   { "Authorization": "Bearer $SOME_PAT" },
      "authProviderType": "google_credentials",   // Google managed server 走 ADC
      "oauth": { "clientId": "...", "clientSecret": "..." },

      // 通用
      "disabled": false,
      "disabledTools": ["<不想給的工具名>"]
    }
  }
}
```

| 欄位 | 規則 |
|---|---|
| 頂層 key | 必須是 `mcpServers`（物件） |
| 傳輸 | `command`（＋`args`）或 `serverUrl`，**必須有其中一個** |
| `url` | **不存在這個欄位**。抄 Cursor 設定檔會寫成 `url`，Antigravity 會當這個 server 沒有傳輸方式 |
| 認證 | token 一律寫 `$ENV_VAR`；Google 服務用 `"authProviderType": "google_credentials"` ＋先跑 `gcloud auth application-default login` |
| OAuth redirect | 固定 `https://antigravity.google/oauth-callback` |
| 生效 | 改完檔案要在 UI 按 **refresh**（或重啟）才會載入 |
| 註解 | 本 Lab 交付的檔案用**嚴格 JSON**（不放註解、不放尾逗號），`check_lab3.py` 才驗得動 |

本 Lab 用的 GitHub server（實測結果）：

| 項目 | 實測值 |
|---|---|
| npm 套件 | `@modelcontextprotocol/server-github`，最新版 `2025.4.8`，**已 deprecated**（`npm view` 的 deprecated 欄位：`Package no longer supported.`） |
| 還能不能跑 | 能。`npx -y @modelcontextprotocol/server-github` 啟動印 `GitHub MCP Server running on stdio`；`initialize` 回 `serverInfo.version` `0.6.2` |
| 缺 token 會怎樣 | **不會拒絕啟動**。工具照樣列得出來，呼叫時才回 JSON-RPC `-32603` `Authentication Failed: Bad credentials` |
| 工具數 | 26 個。含 `create_repository`／`push_files`／`create_or_update_file`／`create_branch`／`list_commits`／`merge_pull_request`／`fork_repository`／`create_pull_request_review`… |
| 官方現行替代 | 遠端 server `"serverUrl": "https://api.githubcopilot.com/mcp/"` ＋ `"headers": {"Authorization": "Bearer $GITHUB_PAT"}`（⚠️ 未實測：需有效 PAT 才連得上） |

### 3.3 `check_lab3.py` 的函式簽章

```python
check_rule_text(name: str, text: str) -> list[tuple[bool, str]]
    # 純函式：長度 ≤ 12000、有啟用模式、≥3 條硬性字眼、無「盡量」

check_mcp(cfg: dict) -> list[tuple[bool, str]]
    # 純函式：mcpServers 非空、每個 server 有 command 或 serverUrl、
    #         url 誤用偵測、headers/env 明文 token 偵測

check_project(root: str) -> list[tuple[bool, str]]
    # 有副作用：讀檔 + 跑 git（log --oneline / remote get-url origin）

git(root: str, *args: str) -> str | None      # 失敗回 None，不丟例外
```

CLI 契約：

| 呼叫 | 行為 | exit code |
|---|---|---|
| `uv run check_lab3.py <path>` | 逐項印 `PASS`／`FAIL` ＋ 統計行 | 0 = 全過，1 = 有 FAIL |
| `uv run check_lab3.py` | 同上，`<path>` 預設目前目錄 | 同上 |
| `uv run check_lab3.py --self-check` | 用假設定驗檢查邏輯，不讀專案、不連網 | 0 = 通過，AssertionError = 邏輯壞了 |

### 3.4 派任務的 prompt 契約（步驟 3）

```
/grill-me
加上輸入歷史紀錄與收藏功能，資料存 localStorage。
遵守 @.agents/rules/style.md 與 AGENTS.md。
完成前必須用 Browser surface 實測：新增三筆、收藏一筆、重新整理後資料還在。
```

`/grill-me` = 反向拷問：agent 先問清模糊需求再動工（對比 `/goal` = 不停下來問，跑到完成）。

## 4. 資料模型

agent 要實作的持久化（步驟 3 的功能，schema 由 Plan 定稿，這裡是建議形狀）：

```ts
// localStorage key 命名：<專案前綴>:<實體>:v<版本>
// 版本號進 key，日後改格式時舊資料不會炸掉解析
localStorage["lab2app:history:v1"]   // JSON: HistoryItem[]
localStorage["lab2app:favorites:v1"] // JSON: string[]（HistoryItem.id）

type HistoryItem = {
  id: string;        // crypto.randomUUID()
  input: string;     // 使用者輸入原文
  createdAt: string; // ISO 8601
};
```

若你在步驟 4 的留言把它改成 IndexedDB，則 schema 變成 `db: lab2app / store: history (keyPath: id) / index: createdAt`。改動**必須**寫進 Plan（rule 有這條）。

## 5. 檔案結構

```
lab3/                                    ← 本教材目錄（你不用改）
├── PRD.md                               需求與驗收標準
├── SPEC.md                              本檔
├── walkthrough.md                       一步一步教學（主要交付物）
├── check_lab3.py                        驗收腳本（含 --self-check）
└── templates/                           要複製進「你的專案」的樣板
    ├── AGENTS.md                        → 專案根目錄
    ├── .agents/
    │   ├── rules/style.md               → 專案的 .agents/rules/style.md
    │   └── mcp_config.json              → 專案的 .agents/mcp_config.json
    └── docs/evidence/.gitkeep           → 放 agent 的錄影／截圖備份

你的專案/                                ← Lab 2 匯出的專案（或任一 repo）
├── AGENTS.md                            從樣板複製後改「這個專案是什麼」與指令表
├── .agents/
│   ├── rules/style.md                   團隊規則（Always On）
│   ├── mcp_config.json                  GitHub MCP server
│   └── workflows/                       （加分）把這次流程存成 /engineerize
├── docs/evidence/                       webm / png：browser 驗證證據
├── src/                                 agent 寫的功能程式碼
├── package.json                         npm run dev / lint / build
└── tsconfig.json                        strict: true（rule 要求不得關掉）
```

## 6. 環境變數與設定

| 變數 | 用途 | 從哪來 | 預設 |
|---|---|---|---|
| `GITHUB_PAT` | GitHub MCP server 認證（被 `mcp_config.json` 以 `$GITHUB_PAT` 引用） | <https://github.com/settings/tokens> → fine-grained token，勾 Contents: RW＋Administration: RW | 無，必填 |
| `GEMINI_API_KEY` | 只有用 `agy` CLI 且不想走 Google 登入時需要（1.1.13+） | AI Studio | 無，桌面版不需要 |
| `GOOGLE_APPLICATION_CREDENTIALS` / ADC | 只有用 `authProviderType: google_credentials` 的 MCP server 才需要 | `gcloud auth application-default login` | 本 Lab 不需要 |

Antigravity 端的設定（UI，不是環境變數）：

| 設定 | 位置 | 本 Lab 建議值 |
|---|---|---|
| 模型 | `/model` | `gemini-3.7-flash` |
| Reasoning effort | `/effort` | `low`，卡關才 `high` |
| 執行模式（CLI） | `shift+tab` | `default`（逐步確認），別一開始就 accept-edits |
| MCP 工具權限 | `/permissions` | 維持 `Ask`；要放行就精確到 `mcp(github/create_repository)`（工具名已實測存在） |
| Browser | Settings → Browser | 開啟（步驟 5 要用） |

> 模型名稱與價格／配額（`gemini-3.7-flash`、Free／AI Pro $19.99、加購 $25／2,500 credits、五小時／週雙限額）全部照投影片 p.85–86、p.97、p.120，**沒有自行推估**。這種數字變動頻繁，UI 的 `/model` 清單與官網定價頁才是最終依據。

## 7. 執行流程

```bash
# ── 0. 前置 ────────────────────────────────────────────────
export GITHUB_PAT="github_pat_..."          # 別 echo 到共享畫面上
cd ~/projects/lab2-app                       # 你的 Lab 2 專案
npm ci && npm run dev                        # 確認 app 本來就跑得起來，再交給 agent

# ── 1. 匯入專案 ────────────────────────────────────────────
# Antigravity → 左欄「+」→ New Project → 選這個資料夾

# ── 2. 建立規範檔 ──────────────────────────────────────────
cp -R $COURSE/lab3/templates/. .
uv run $COURSE/lab3/check_lab3.py .   # 預期：rules/mcp 綠，證據與 git 紅

# ── 3-5. 派任務、審 Plan、看 browser 驗證（在 Antigravity UI 裡） ──
# /grill-me → 回答反問 → 審 Plan → 留言 → Proceed → 看 Walkthrough 錄影
# 另存錄影：Artifacts 上的錄影 → 右鍵下載 → docs/evidence/

# ── 6. 接 MCP ──────────────────────────────────────────────
# .agents/mcp_config.json 已就位 → UI 按 refresh → Settings → Customizations →
#   Installed MCP Servers 確認 github 上線（agy CLI 是 /mcp）
uv run python -m json.tool .agents/mcp_config.json > /dev/null && echo "JSON ok"
# 派任務：「用 github MCP 建立 repo lab2-app（private）並把目前程式碼推上去，
#           commit 用 Conventional Commits」

# ── 7. 驗收 ────────────────────────────────────────────────
npm run lint && npx tsc --noEmit
uv run $COURSE/lab3/check_lab3.py .   # 預期 11 過 / 0 失敗
```

## 8. 錯誤處理與邊界

| 情境 | 症狀 | 處理方式 |
|---|---|---|
| `mcp_config.json` 寫成 `url` | UI 的 server 列表出現但工具清單是空的；`agy` 的 `/mcp` 也看不到 tools | 改成 `serverUrl`；`check_lab3.py` 會直接指名 |
| JSON 有尾逗號或 `//` 註解 | `json.decoder.JSONDecodeError: Illegal trailing comma before end of object: line 4 column 23` | 交付檔用嚴格 JSON |
| 改了 JSON 沒 refresh | 設定檔明明對，server 還是舊的／不存在 | Settings → Installed MCP Servers → refresh，或重啟 App |
| PAT 明文寫在 `headers` | 檔案一 commit 就外洩，GitHub 會自動撤銷該 token | 用 `$GITHUB_PAT`；`check_lab3.py` 的 SECRET regex 會抓 `ghp_`／`github_pat_`／`sk-`／`AIza` 開頭的字串 |
| `$GITHUB_PAT` 沒被展開／PAT 過期 | server 有上線、工具列得出來，呼叫才回 `-32603 Authentication Failed: Bad credentials` | 重開 App（GUI 不繼承之後才設的 shell 變數）；仍失敗改用 shell 層環境變數，不要把 token 寫回檔案 |
| `npx` 噴 `npm warn deprecated ...server-github@2025.4.8: Package no longer supported.` | 套件停止維護，官方改推遠端 server | 警告而非錯誤，server 仍可用；要換就改成遠端型（見 §3.2 表格最後一列） |
| `disabledTools` 填錯工具名 | 沒有錯誤訊息，就是沒關到 | 對照 UI 的工具清單（或 `tools/list`）的真實工具名 |
| rule 檔超過 12,000 字元 | 規則被截斷，後半段安靜失效 | 拆成多個檔（`style.md`／`testing.md`），或改 Glob 模式只在相關檔案生效 |
| rule 寫「盡量」 | agent 自行取捨，你以為有規範其實沒有 | 改成「必須／禁止」 |
| `~/.gemini/GEMINI.md` 與 Gemini CLI 互相滲透 | Antigravity 出現你只寫給 Gemini CLI 的規則（或反之） | 共通規則放 `~/.gemini/AGENTS.md`，工具專屬的才放 GEMINI.md |
| agent 說完成但沒錄影 | Walkthrough 只有文字 | 回覆「請用 Browser surface 實測並附錄影」；或在 `AGENTS.md` 的驗證方式寫成硬規則（樣板已寫） |
| Browser surface 開不起來 | 提示找不到 Chrome／要求授權 | 裝 Chrome；Settings → Browser → Browser Tools 確認沒被停用 |
| agent 開了不認識的網站 | 潛在 indirect prompt injection（p.121） | 只讓它開 localhost；用 URL 允許清單限制網域 |
| credits 用完 | 任務排隊或直接拒絕 | `/effort low`＋`gemini-3.7-flash`；五小時／週雙限額，等刷新 |
| `check_lab3.py` 說 0 個 commit | 專案還不是 git repo | `git init && git add -A && git commit -m "chore: 初始化"`（或讓 agent 做） |

## 9. 驗證方式

| 要驗什麼 | 怎麼驗 | 離線可行？ |
|---|---|---|
| 檢查腳本自己的邏輯 | `uv run check_lab3.py --self-check` → 印 `self-check 通過：rule 檢查 5 項、mcp 檢查 7 項` | ✅ |
| 樣板檔案格式正確 | `uv run check_lab3.py templates` → 前 8 項 PASS（證據與 git 三項 FAIL 是預期的） | ✅ |
| MCP JSON 合法 | `uv run python -m json.tool templates/.agents/mcp_config.json` | ✅ |
| rule 長度 | 腳本會印實際字元數（樣板：627） | ✅ |
| 功能真的能用 | 瀏覽器手動操作：新增三筆、收藏一筆、重新整理 | ❌ 需要 app 跑起來 |
| agent 真的測過 | 打開 Walkthrough 的 webm 看它點按鈕 | ❌ 需要 Antigravity |
| MCP server 起得來、工具名正確 | `npx -y @modelcontextprotocol/server-github`＋stdio 講 `initialize` / `tools/list` | ✅（已實測：0.6.2、26 個工具） |
| MCP 工具上線（在 Antigravity 裡） | Installed MCP Servers 列出 github 的 tools（`agy` 用 `/mcp`） | ❌ 需要 Antigravity |
| PAT 有效 | 呼叫任一工具，看有沒有 `Authentication Failed: Bad credentials` | ❌ 需要真 PAT |
| repo 推上去了 | `git log --oneline` ＋ `gh repo view` | ❌ 需要 GitHub 帳號 |

> ⚠️ 未實測：Antigravity 桌面版的所有 UI 操作（Project 匯入、`/codesearch`、`/grill-me`、Plan 留言、Browser surface 錄影、`/mcp` 面板、MCP refresh、`$ENV_VAR` 在 `mcp_config.json` 裡會不會被展開）、遠端 `https://api.githubcopilot.com/mcp/` 端點、GitHub repo 建立與 push。本機沒有安裝 Antigravity、也沒有 Google／GitHub 帳號可用；這些步驟的敘述依投影片 p.95–122。
>
> 已實測（本機真的跑過）：`check_lab3.py` 全部輸出與 exit code、樣板檔案格式與字元數、兩種 `JSONDecodeError` 原文、`TS7006`（typescript 5 + `strict`；同一段程式改成明確 `any` 則 0 error）、`npm`／`git` 的錯誤原文、GitHub MCP server 的啟動訊息／版本／26 個工具名／`Bad credentials` 錯誤。

## 10. 已知限制與升級路徑

| 限制 | 現況（`# ponytail:` 對應） | 升級路徑 |
|---|---|---|
| 明文 token 偵測只認前綴 | `SECRET` regex 認 `ghp_`／`github_pat_`／`glpat-`／`sk-`／`AIza` | 要更嚴就改成「headers/env 的值必須以 `$` 開頭」白名單制 |
| 「有跑 lint」無法驗 | 腳本只驗設定檔與證據存在，不驗 agent 真的跑過 lint | 加 Hook：`PostToolUse` 自動跑 lint（p.112），或 CI 上 GitHub Actions |
| browser 證據只驗「檔案存在」 | 不看內容、不看長度 | 驗 webm 檔頭與時長需要 ffprobe，超出「stdlib 優先」的範圍 |
| rule 檢查是字面比對 | 「必須／禁止」的條數用 regex 數，寫廢話也能過 | 這種東西人審比機器準；驗收時抽看一條 |
| 只支援單一 rule 目錄 | 不看巢狀目錄的 `AGENTS.md`（p.106 提到可巢狀） | 需要時把 `check_project` 的 `AGENTS.md` 檢查換成 `os.walk` |
| git 檢查靠 subprocess | 沒 git 或不是 repo 就回 `None`，當作 0 個 commit | 夠用；要更精確就讀 `.git/HEAD` |
