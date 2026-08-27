# Lab 3.5 走一遍：讓兩個 Agent 共用一份會長大的記憶（CivicGuard）

> 90 分鐘 ｜ 綜合 Gemini CLI × Antigravity 記憶協作：`AGENTS.md` 單一事實來源 ＋ `@import` 拆檔 ＋ MCP server ＋ headless 稽核進 CI ＋ 一次完整交接

做完你會有一個 uv 專案 `civicguard`：兩支 CLI 讀同一份 `AGENTS.md`，一支稽核腳本能在 CI 紅燈，
而且「踩過的坑」是寫在檔案裡的——不是留在某一次對話裡。

```
$ uv run civicguard-audit
.github/workflows/brief.yml:14  [pip-install]  - run: pip install -r requirements.txt
    → 改用 uv add <pkg>
.github/workflows/brief.yml:14  [requirements]  - run: pip install -r requirements.txt
    → 來源是 uv.lock；真要交付才用 uv export
稽核完成：2 處違規
$ echo $?
1

# 修好之後
$ uv run civicguard-audit --json | jq -e 'length == 0'
true
$ uv run pytest -q
.....                                                                    [100%]
5 passed in 0.28s
```

每一步都是「**動手 → 為什麼 → 驗收**」。驗收沒過不要往下走，記憶類的問題往後拖只會更難查——
因為它失敗的方式是「安靜地什麼都不做」。

投影片 p.168 的五個動手步驟與本文步驟的對照（順序沒有改，只是把 MCP server 與「記憶會長大」
拆成獨立步驟，因為它們各自要跑一次失敗）：

| 投影片 p.168 | 本文 |
|---|---|
| ① 骨架 | 步驟 1（＋步驟 2 把 p.167 要求的 MCP server 跑起來） |
| ② 記憶：AGENTS.md ＋ 三份領域文件 | 步驟 3 |
| ③ 接線：`context.fileName` ＋ `GEMINI.md` | 步驟 4 |
| ④ 驗證記憶真的載到 | 步驟 5 |
| ⑤ 稽核腳本 | 步驟 6 |
| p.169 驗收⑤⑥ | 步驟 7（記憶會長大）、步驟 8（交接）、步驟 9（勾選清單） |

時間分配：骨架 20 分 ｜ 記憶 20 分 ｜ 稽核 25 分 ｜ 交接驗證 25 分。

---

## 步驟 0：前置（5 分）

**動手**

```bash
node --version                                  # 要 >= 20
npm install -g @google/gemini-cli
gemini --version                                # 0.56.x
export GEMINI_API_KEY="貼上你的 key"             # Lab 1 那把可以直接用
jq --version                                    # 沒有的話 brew install jq
```

CWA 的 key 到 <https://opendata.cwa.gov.tw> 免費註冊拿（本 lab 所有 `--self-check` 都不需要它）：

```bash
export CWA_API_KEY="貼上你的 CWA key"
```

**為什麼**
- **一定要 API key，不能用 Google 帳號登入**。2026/06/18 起 AI Pro／Ultra／免費個人帳號的 CLI 登入
  已停止服務（Discussion #28017）。官方 README 至今還在推薦「用個人帳號登入享免費額度」——那段已經過時。
  停掉的是登入路徑，工具本身還是 Apache-2.0 每週釋出，所以 API key 這條路完全不受影響。
- 沒有 `jq` 這個 lab 的第 6、7 步做不了：稽核的成敗是靠 exit code 判斷，而 exit code 是 `jq -e` 給的。

**驗收**

```bash
gemini --version && echo $GEMINI_API_KEY | cut -c1-6      # 印出版本 + key 前六碼
```

> ⚠️ 未實測：本教材撰寫環境沒有安裝 gemini CLI，所有 `gemini …` 指令的輸出以投影片為準。
> 程式碼部分（`uv run …`）全部實機跑過，輸出是真的。

---

## 步驟 1：骨架 —— 一行 uv init 開始（15 分）

**動手**

```bash
uv init lab3.5 --package --name civicguard --python 3.13 && cd lab3.5
uv add "mcp[cli]" httpx google-genai
uv add --dev pytest ruff
mkdir -p docs/domain memory scripts tests \
         .gemini/commands .gemini/agents .agents/rules .github/workflows
```

**為什麼**
- **`--name civicguard` 不能省**。目錄名 `lab3.5` 有小數點，Python 套件名不能有點，
  所以 `uv init` 會自己把它壓成合法名字。實測不給 `--name` 的結果：

  ```
  $ uv init foo3.5 --package --python 3.13
  Initialized project `foo3-5` at /.../foo3.5
  $ ls src
  foo3_5
  ```

  專案名變 `foo3-5`、套件目錄變 `src/foo3_5/`、console script 變 `foo3-5`。
  之後所有 `uv run civicguard-mcp` 都會是 `error: Failed to spawn: civicguard-mcp`。
- **`--package` 不是 `--bare`**。Lab 1 只有一支腳本所以用 `--bare`；這裡有五個模組要互相 import，
  還要在 `.gemini/settings.json` 裡用 `uv run civicguard-mcp` 啟動 MCP server——
  console script 只有 `--package` 佈局才會生成。
- **`httpx` 與 `google-genai` 這兩個依賴，本 lab 的程式碼其實一次都沒 import**。
  照抄是為了跟投影片 p.134／p.168 一致（真實專案抓資料很快就會用到 httpx）；
  這裡所有 HTTP 都用 stdlib `urllib`，所以你把它們拿掉程式一樣跑得起來。
  語言生成那一段是 `gemini` CLI 做的，不走 `google-genai`。
- **`uv add` 而不是 `pip install`**。依賴寫進 `pyproject.toml` ＋ `uv.lock`，別人 clone 之後
  `uv sync --frozen` 就跟你一模一樣。`uv run` 執行前會自動確認環境與 lock 同步，所以
  「忘了 activate 所以裝到系統 Python」這個萬年災難整段消失。這條規則等一下會被寫成
  `AGENTS.md`、`.agents/rules/`、CI 稽核三層防線——因為 Agent 會替你下指令，指令集越窄它犯錯空間越小。

**驗收**

```bash
cat pyproject.toml | head -3        # name = "civicguard"
ls src                              # civicguard
uv run python -c "import importlib.metadata as m; print(m.version('mcp'))"   # → 2.1.1（mcp 沒有 __version__）
git init -q 2>/dev/null; git add -A          # uv init 已經建好 .git，這裡只是把檔案放進 index
git ls-files | grep '^uv.lock$'             # → uv.lock（驗收① 要求它進版控）
git commit -qm "init civicguard"            # 真的 commit，之後 git checkout <file> 才能還原
```

---

## 步驟 2：MCP server 跑起來（先讓它壞一次）（10 分）

**動手**：先照投影片寫，故意用 `FastMCP`：

```python
# src/civicguard/mcp_server.py（第一版，會壞）
from mcp.server.fastmcp import FastMCP
mcp = FastMCP("civicguard")
```

```bash
uv run python -c "from mcp.server.fastmcp import FastMCP"
```

實際跑出來：

```
ModuleNotFoundError: No module named 'mcp.server.fastmcp'. This is mcp 2.x, where
FastMCP was renamed to MCPServer (from mcp.server.mcpserver import MCPServer) and
other APIs changed; see the migration guide at
https://py.sdk.modelcontextprotocol.io/v2/migration/#fastmcp-renamed-to-mcpserver
or pin 'mcp<2' to keep running v1 code.
```

改成 mcp 2.x 的寫法（完整版見 `src/civicguard/mcp_server.py`）：

```python
from mcp.server.mcpserver import MCPServer
from civicguard import brief, cwa, shelters

# server 名稱不要含底線：工具全名是 mcp_<server>_<tool>，解析器會在 mcp_ 之後的第一個底線切開。
mcp = MCPServer("civicguard", instructions="台灣民生示警資料查詢。回答一律附上資料時間。")

@mcp.tool()
def active_alerts(city: str) -> list[dict]:
    """查某縣市目前生效的天氣特報。city 例：臺南市（注意是「臺」不是「台」）。"""
    return cwa.parse_alerts(cwa.fetch(city), city)

def main() -> None:
    if "--self-check" in sys.argv:
        return _self_check()
    if not os.environ.get("CWA_API_KEY"):
        # stdout 是 MCP 協定通道，print() 會弄壞連線 —— 所有訊息一律走 stderr
        print("warn: 沒有 CWA_API_KEY，active_alerts 會直接失敗", file=sys.stderr)
    mcp.run(transport="stdio")
```

然後把 console scripts 補進 `pyproject.toml`：

```toml
[project.scripts]
civicguard-mcp = "civicguard.mcp_server:main"
civicguard-audit = "civicguard.audit:main"
civicguard-brief = "civicguard.brief:main"
civicguard-fetch = "civicguard.cwa:main"
civicguard-shelters = "civicguard.shelters:main"
```

**為什麼**
- 這是本 lab 第一個「投影片講的跟現實不一樣」的地方。投影片寫 `civicguard-mcp` 是 FastMCP server，
  那是 `mcp` 1.x 的類別名；`uv add "mcp[cli]"` 現在裝到的是 2.1.1，`FastMCP` 已改名 `MCPServer`。
  這個錯誤訊息算佛心（SDK 自己寫了遷移提示），大部分改名不會這麼客氣。
  不想改程式就 `uv add "mcp<2"` 釘版本——但新專案沒理由釘舊版。
- **`print()` 一定要導去 stderr**。stdio transport 的 stdout 就是協定通道，
  多印一個字就是往協定裡塞垃圾，Agent 那邊會顯示 server 掛了、但看不到原因。
- **server 名稱不含底線**。工具全名是 `mcp_<server>_<tool>`，解析器在 `mcp_` 之後的第一個底線切開。
  取名 `civic_guard` 會被切成 server=`civic`、tool=`guard_active_alerts`，然後 Agent 永遠叫不到工具，
  **而且不會有任何錯誤訊息**。所以 self-check 裡放了一條 `assert "_" not in mcp.name`。
- 缺 `CWA_API_KEY` 只警告不退出：工具列表還是要能被探索，讓 Agent 知道有哪些能力；
  真的呼叫時才失敗，錯誤訊息才指得到正確的地方。

**驗收**

```bash
uv run civicguard-mcp --self-check
```

```
mcp self-check ok: ['active_alerts', 'daily_brief', 'normalize_shelters']
```

這條檢查不連網、不花錢：它只是 `asyncio.run(mcp.list_tools())` 然後斷言三個工具都註冊成功、
每個都有 description（沒有 description 的工具，Agent 不知道什麼時候該叫它）。

想看互動版（需要 Node）：

```bash
uv run mcp dev src/civicguard/mcp_server.py     # 開 MCP Inspector
```

> ⚠️ 未實測：`mcp dev` Inspector 需要下載 node 套件，本教材環境沒跑。

---

## 步驟 3：記憶 —— 先寫 AGENTS.md，再拆三份領域文件（20 分）

**動手**：`AGENTS.md` 至少要有四塊（完整版見本目錄的 `AGENTS.md`）：

```markdown
# CivicGuard — Agent 說明書

## 專案概要
把政府開放資料轉成人話示警。資料髒，規則會長大。

## Python 工作流（強制）
- 本專案一律使用 uv，**禁止**直接呼叫 `python`、`python3`、`pip`、`pip3`、`venv`、`virtualenv`。
- 安裝套件：`uv add <pkg>`（開發相依加 `--dev`）
- 執行程式：`uv run <cmd>`　一次性工具：`uvx <tool>`　還原環境：`uv sync --frozen`
- `uv.lock` 必須提交進版控，不可手改。
若你正要輸入 pip install，請停下來改成 `uv add`，並在 memory/decisions.md 留下一行說明。

## 測試與稽核指令
（把每一條 --self-check 與 CI 指令列出來，Agent 才知道改完要跑什麼）

## 寫入權限（記憶契約）
| 層 | 檔案 | 誰可以寫 |
| 契約層 | AGENTS.md | 只有人類（PR 審核） |
| 知識層 | docs/domain/*.md | Agent 可直接寫 |
| 決策層 | memory/decisions.md | 兩個 Agent 都可寫，append-only |

## 領域知識（拆檔維護）
@./docs/domain/cwa-api-notes.md
@./docs/domain/alert-taxonomy.md
@./docs/domain/shelter-quirks.md

## 決策紀錄
@./memory/decisions.md
```

三份領域文件與 `memory/decisions.md` 照本目錄的版本寫（`decisions.md` 先放投影片的 D-007、D-008 兩條）。

**為什麼**
- **為什麼拆檔而不是塞成一坨**：主檔要保持人看得懂——人看得懂才有人會維護。拆檔後 diff 乾淨，
  Agent 改了哪一段一目了然。而且同一份 `docs/domain/` 也能被 Antigravity 的 rules 引用。
- **為什麼契約層只准人寫**：一旦讓 Agent 自由改 `AGENTS.md`，它會為了讓自己過關而放寬規則
  ——「稽核一直失敗，那我把規則改成允許 pip 好了」。這是實務上最常見的失控模式。
  Agent 想改規則，就叫它去 `decisions.md` 提案。
- **為什麼決策層 append-only**：「為什麼當初這樣決定」是交接時最缺的資訊。只增不改才留得住脈絡；
  要推翻舊決策就新增一條，寫明取代哪一條。
- **不要把專案知識寫進 `~/.gemini/GEMINI.md`**。那是全域檔，會跟著你去所有專案，
  而且 **Antigravity 的「+ Global 規則」寫的是同一個檔**（gemini-cli issue #16058 就是在講這件事，
  狀態 Closed as not planned——官方不打算修）。一句話記法：**全域只放個性，專案才放知識**。
- **不要同時維護 `GEMINI.md` 和 `AGENTS.md` 兩份內容**，必然分岔。留一份為主，另一份只放一行 `@import`。

**驗收**

```bash
grep -c '^@\./' AGENTS.md          # → 4（三份 domain ＋ decisions.md）
ls docs/domain                     # alert-taxonomy.md  cwa-api-notes.md  shelter-quirks.md
grep -c '^## D-' memory/decisions.md   # → 2
```

> 💡 **啊哈：所謂「記憶系統」，就是 open() 加上遞迴 join —— 沒有資料庫，沒有向量，沒有廠商的雲端。**
> `@import` 由 Memory Import Processor 展開，行為就是「看到 `@` 開頭的行，把那個檔的內容貼進來」。
> 這也解釋了投影片那句怪話「只保證串接，不保證覆蓋」：join 本來就沒有覆蓋語意，
> 後寫的規則不會蓋掉前面的，只會再多送一份互相矛盾的文字給模型。所以要靠不重複，不能靠覆蓋。
> **動手看**：`uv run aha.py --show` → 5 個檔的載入樹（AGENTS.md 1,449 字元 ＋ 四份 @import），
> 串接後 4,520 字元；`aha.py` 裡那個 17 行的 `resolve()` 就是整套機制的全部。

---

## 步驟 4：接線 —— 先看它答錯，再修（10 分）

**動手（第一段：故意還沒接線）**：`.gemini/settings.json` 先**不要**建，直接問：

```bash
gemini -p "這個專案安裝套件要用什麼指令？只回一行。"
```

預期它回 `pip install <package>` 之類的東西——**這是對的失敗**。
未設定時 `context.fileName` 預設只讀 `GEMINI.md`，而你的規則寫在 `AGENTS.md` 裡，它根本沒看到。

**動手（第二段：接上）**

```bash
printf '%s' '{"context":{"fileName":["AGENTS.md","GEMINI.md"]}}' > .gemini/settings.json
printf '本專案的 Agent 說明書維護在 AGENTS.md，這裡只留一層轉接。\n\n@./AGENTS.md\n' > GEMINI.md
```

Antigravity 端**什麼都不用做**（v1.20.3 起原生讀 `AGENTS.md`），只補一層保險：

```bash
mkdir -p .agents/rules
cat > .agents/rules/uv-only.md <<'MD'
---
activation: always_on
---
本專案 Python 一律使用 uv。禁止 pip、venv、直接呼叫 python。
細節見 @/AGENTS.md 的「Python 工作流」章節。
MD
```

**動手（第三段：把 MCP server 也接上）**

前面那個 `printf` 只寫了最關鍵的一行。實際要用的 `settings.json` 還要加上 MCP server
（`mcpServers` 是**頂層**物件，不是巢狀在 `mcp` 底下）：

```bash
cat > .gemini/settings.json <<'JSON'
{
  "context": { "fileName": ["AGENTS.md", "GEMINI.md"] },
  "general": { "defaultApprovalMode": "default", "checkpointing": { "enabled": true } },
  "experimental": { "autoMemory": true },
  "mcpServers": {
    "civicguard": {
      "command": "uv",
      "args": ["run", "civicguard-mcp"],
      "cwd": "./",
      "env": { "CWA_API_KEY": "$CWA_API_KEY" },
      "timeout": 30000,
      "trust": false
    }
  }
}
JSON
```

Antigravity 用**獨立檔案**，而且 stdio 這段可以直接複製貼上：

```bash
cat > .agents/mcp_config.json <<'JSON'
{
  "mcpServers": {
    "civicguard": {
      "command": "uv",
      "args": ["run", "civicguard-mcp"],
      "env": { "CWA_API_KEY": "$CWA_API_KEY" }
    }
  }
}
JSON
```

**為什麼**
- **這一步是整個模組的核心，卻只有一行設定**。`context.fileName` 型別是 `string | string[]`，
  未設定時預設只讀 `GEMINI.md`。少了這一行，你前面寫的 20 分鐘記憶對 Gemini CLI 來說**完全不存在**
  ——而且不會有任何錯誤訊息，它只會用訓練資料裡的通識回答你（也就是 `pip install`）。
- **命名陷阱**：舊版是扁平鍵 `contextFileName`，現在是巢狀的 `context.fileName`。
  但 `gemini-extension.json`（擴充套件清單檔）裡 `contextFileName` 仍然是正確鍵名——兩者不要混。
  寫錯鍵名不會報錯，設定會被安靜忽略。
- **`.agents/` 不是 `.antigravity/`**。官方目錄是 `.agents/`（舊版 `.agent/`），網路上不少教學寫錯。
  建錯目錄的症狀是：規則完全沒生效，也沒有任何提示。
- **為什麼 Antigravity 要再放一份 rules**：官方只文件化了「Rules 檔內」的 `@` 展開，
  並沒有保證會展開根目錄 `AGENTS.md` 裡的 `@import`。重要領域知識在 `.agents/rules/` 也放一份引用最保險。
- **記憶只保證串接，不保證覆蓋**。文件寫的是把找到的內容全部 concatenate 後送給模型，
  沒有定義「後面覆蓋前面」的優先序。所以不要靠覆蓋，靠不重複。
- **MCP 只有 stdio 能無腦複製**。三種 transport 是「出現哪個鍵」決定的：`command` → stdio、
  `url` → SSE、`httpUrl` → Streamable HTTP。而 Antigravity 遠端一律只吃 `serverUrl`，
  **明確不支援 `url`／`httpUrl`**——複製錯的症狀是它完全看不到那個 server，而且沒有錯誤訊息。
  本 lab 走 stdio，所以兩份設定內容一樣，差別只在放哪個檔。
- **`mcpServers` 是頂層鍵**，不是 `mcp.mcpServers`。寫錯不會報錯，`/mcp` 就是空的。
  另外 `env` 要明確宣告要傳進去的變數（敏感環境變數預設會被遮蔽）。

**驗收**

```bash
jq -e . .gemini/settings.json .agents/mcp_config.json > /dev/null && echo "兩份設定都是合法 JSON"
jq -e '.mcpServers.civicguard.command == "uv"' .gemini/settings.json      # → true
cat GEMINI.md                     # 只有轉接那兩三行，沒有第二份規則
```

> ⚠️ 未實測：`/mcp` 看不看得到 `civicguard`（需要 gemini CLI）。離線只能驗設定檔合法、
> 以及 server 自己起得來（`uv run civicguard-mcp --self-check`，步驟 2 已驗過）。

> 💡 **啊哈：兩家不同公司的 Agent 共用記憶，靠的不是任何整合協定 —— 只是被設定成打開同一個檔案路徑。**
> Antigravity 沒有讀 Gemini CLI 的任何東西，反之亦然；共享的只有磁碟上那份 Markdown。
> 而你剛才其實鋪了**兩條互不相干的路徑**通到同一份全文：`context.fileName` 是一條，
> `GEMINI.md` 裡那行 `@./AGENTS.md` 是另一條——設定鍵打錯字，import 那條還會通。
> **動手看**：`uv run aha.py --show GEMINI.md` → 52 字元的轉接檔展開成 4,559 字元、
> 同樣那四份 `@import`（比 `--show` 多的 39 字元，就是轉接檔自己剩下的那行說明）。

---

## 步驟 5：驗證記憶真的載到（10 分）

**動手**

```bash
gemini -p "這個專案安裝套件要用什麼指令？只回一行。"
#   期待輸出：uv add <pkg>      ← 答 pip install 就是沒吃到記憶
```

進互動模式看得更清楚：

```bash
gemini
> /memory list      # 列出目前生效的記憶檔路徑
> /memory show      # 看串接後的完整內容
> /memory reload    # 剛改完 AGENTS.md，不想重開 CLI
```

**為什麼**
- **為什麼要用「同一個問題問兩邊」當驗收**：記憶失效的樣子不是報錯，是「答得很流暢但用的是通識」。
  唯一可靠的檢查就是問一個「只有讀了你的檔案才會答對」的問題。`uv add` 就是這種問題：
  模型的訓練資料裡 `pip install` 出現次數壓倒性地多，它沒讀到你的規則就一定會答 `pip`。
- **`/memory list` 比 `/memory show` 先看**。第一步永遠是確認「吃到哪幾個檔」——
  常見狀況是吃到了上一層目錄的 `GEMINI.md`（工作區層會掃父目錄），你以為在改的檔根本沒被載入。
  CLI 底部狀態列也會顯示載入的 context 檔數量。
- **`save_memory` 工具與 `/memory add` 指令在 v0.56 已移除**。網路上 2025～2026 上半年的教學幾乎都還在教它們，
  照著打只會得到「unknown command」。現在的做法是直接叫 Agent「把這件事記下來」，
  它會用 `write_file`／`replace` 去改對應的 Markdown 檔。

**驗收**（投影片 p.169 第 ② ③ 項）

```bash
gemini -p "這個專案安裝套件要用什麼指令？只回一行。"     # → uv add <pkg>
```

- [ ] `/memory list` 看得到 `AGENTS.md` 與三份 `docs/domain/*.md`
- [ ] `/memory show` 內含 uv 規則那一段
- [ ] 在 Antigravity 問同一個問題，答案一樣是 `uv add`

> ⚠️ 未實測：以上四條都需要 gemini CLI ＋ API key（本教材環境未安裝）。

> 💡 **啊哈：記憶不是「存起來」，是「每問一句就整份重送一次」—— 寫越詳細，每一輪都越貴。**
> 沒接線時模型手上關於 uv 的證據是 **0 字元**（所以它必然回 `pip install`）；接線後每一輪要送 4,520 字元。
> `decisions.md` 每新增一條，之後**每一輪**都多付約 394 字元——這是永久成本，不是一次性的。
> 這就是為什麼投影片 p.160 特別提醒「已結案的搬去 `decisions-archive.md`，而且**不要** `@import` 它」。
> **動手看**：`uv run aha.py --cost` → 四列對照表：0 → 1,449 → 4,520 字元（主檔的 ×3.1），
> 20 輪對話累計從 0 到 49,240 tokens；再長 10 條決策就變 92,160，接近翻倍。

---

## 步驟 6：稽核腳本 —— 能在 CI 回傳非零 exit code（25 分）

投影片給的是 gemini 版：

```bash
gemini -p "掃描整個 repo，列出所有直接呼叫 python、python3、pip 的指令或文件片段，\
用 JSON 陣列回覆；沒有就回空陣列。" \
  --output-format json | jq -e '.response | fromjson | length == 0'
```

**動手（第一段：先看它為什麼不能直接進 CI）**

模型很愛把 JSON 包在 Markdown 圍籬裡。`.response` 拿到 ```` ```json\n[]\n``` ```` 之後
`fromjson` 就會炸——實測 `jq` 的錯誤長這樣：

```
$ printf '```json\n[]\n```\n' | jq -e 'length == 0'
jq: parse error: Invalid numeric literal at line 2, column 0
```

CI 看到非零 exit code 會以為「有 uv 違規」，其實是格式問題。這種假紅燈比沒有稽核更糟：
跑三次紅兩次，兩週後全隊就開始 `--no-verify`。

**動手（第二段：兩層稽核）**

第一層是確定性的字面稽核，用 Python 寫（完整版見 `src/civicguard/audit.py`）：

```python
RULES = [
    ("pip-install", r"\bpip3?\s+install\b", "改用 uv add <pkg>"),
    ("venv", r"\b(python3?\s+-m\s+venv|virtualenv)\b", "刪掉，uv init 已經建好環境"),
    ("activate", r"source\s+\S*\.venv/bin/activate", "刪掉，uv run 不需要 activate"),
    ("bare-python", r"(?<!uv run )\bpython3?\s+[\w./-]+\.py\b", "改用 uv run <script>.py"),
    ("requirements", r"\brequirements\.txt\b", "來源是 uv.lock；真要交付才用 uv export"),
]
EXEMPT = "uv-ok"      # 這行有這個字就跳過（給教材與錯誤訊息範例用）
```

第二層才是 gemini 的語意稽核，並且把圍籬 `sed` 掉、沒 key 就跳過（見 `scripts/ci_audit.sh`）：

```bash
uv run civicguard-audit --json | jq -e 'length == 0' > /dev/null

if [[ -n "${GEMINI_API_KEY:-}" ]]; then
  gemini -p "…只輸出 JSON。" --output-format json \
    | jq -r '.response' \
    | sed -e 's/^```json//' -e 's/^```$//' \
    | jq -e 'length == 0' > /dev/null
fi
```

**動手（第三段：真的抓一次）**

把 workflow 照投影片 p.153 抄好，然後**故意寫成從別的教學複製來的樣子**：

```yaml
      - run: pip install -r requirements.txt
```

```bash
uv run civicguard-audit; echo "exit=$?"
```

實測輸出（這是真的跑出來的）：

```
AGENTS.md:14  [venv]  - 本專案一律使用 uv，**禁止**直接呼叫 `python`、`python3`、`pip`…
    → 刪掉，uv init 已經建好環境
AGENTS.md:21  [pip-install]  若你正要輸入 `pip install`，請停下來改成 `uv add`…
    → 改用 uv add <pkg>
.github/workflows/brief.yml:14  [pip-install]  - run: pip install -r requirements.txt
    → 改用 uv add <pkg>
.github/workflows/brief.yml:14  [requirements]  - run: pip install -r requirements.txt
    → 來源是 uv.lock；真要交付才用 uv export
稽核完成：4 處違規
exit=1
```

四條裡有兩條是**誤報**：`AGENTS.md` 那兩行是在「講這條規則」，不是在違規。
規則本身被自己的稽核器擋下來，這是每個 linter 都會遇到的事。修法是給一個明確、可 grep 的豁免標記
（Markdown 註解渲染後看不見）：

```markdown
- 本專案一律使用 uv，**禁止**直接呼叫 `python`、`pip`、`venv`、`virtualenv`。<!-- uv-ok 這行在講規則本身，稽核器要豁免 -->
```

真正的違規則要真的修：

```yaml
      - run: uv sync --frozen
```

**為什麼**
- **CI 的把關者必須是確定性的**。LLM 稽核很聰明（它能抓「文件教的指令跟程式碼實際跑的不一致」這種
  正則抓不到的東西），但同一份 repo 跑兩次可能給不同答案，而且會多收費。所以：字面稽核當 gate，
  語意稽核當 advisor。不要用 `-o text` 去 parse 人類文字，一律 `-o json` 取 `.response`，
  用 exit code 決定 job 成敗。
- **為什麼 `bare-python` 的正則要有 `(?<!uv run )`**：不加的話 `uv run main.py` 自己會被抓出來，
  稽核器就永遠是紅的。self-check 裡專門有一條 `assert scan_text("uv run scripts/x.py") == []` 守這件事。
- **為什麼豁免要用行內標記而不是整檔跳過**：整檔跳過的話，`AGENTS.md` 之後真的被 Agent 寫進
  `pip install` 也不會被抓到。標記在行上，範圍最小、而且 `grep -rn "uv-ok"` 一眼看完所有例外。
- **為什麼 `PRD.md` / `SPEC.md` / `walkthrough.md` 是整檔跳過**（`audit.py` 的 `SKIP_FILES`）：
  教材天生寫滿反例，逐行標記會把文章弄得不能讀。這是刻意的取捨，真實專案要把這份清單清空。
- **`test -s "$OUT" || exit 1`**（`scripts/daily_brief.sh` 最後那行）也是同一個道理：
  gemini 失敗時可能吐空字串卻回 exit 0，沒有這行 CI 會綠燈通過一份空簡報。

**驗收**

```bash
uv run civicguard-audit --self-check                     # → audit self-check ok
uv run civicguard-audit; echo "exit=$?"                  # → 稽核完成：0 處違規 / exit=0
uv run civicguard-audit --json | jq -e 'length == 0'     # → true
bash -n scripts/ci_audit.sh scripts/daily_brief.sh       # 語法先過，別在 CI 才發現
```

把這一串存成 custom command 就不用每次打字（`.gemini/commands/audit.toml`，
處理順序固定 `@{}` → `!{}` → `{{args}}`；`/commands reload` 不用重開 CLI）：
互動模式打 `/audit` 就會先跑字面稽核、再做語意檢查。
另一支 `.gemini/commands/brief.toml` 則是 `/brief 臺南市`。

> ⚠️ 未實測：`.toml` 的語法是否被 CLI 正確解析，需要 gemini CLI 實機驗。

再故意塞一行違規、確認它真的會紅：

```bash
echo '# pip install httpx' >> scripts/daily_brief.sh
uv run civicguard-audit --json | jq -e 'length == 0'; echo "exit=$?"   # → false / exit=1
git checkout scripts/daily_brief.sh                      # 還原
```

---

## 步驟 7：記憶會長大 —— 製造一次失敗，讓它變成永久記憶（15 分）

這是投影片 p.144 那一段的離線可跑版本。

**動手（第一段：踩雷）**

照直覺寫 `cwa.py` 的 parse：

```python
def parse_alerts(payload: dict, city: str) -> list[dict]:
    recs = payload.get("records") or {}
    groups = recs["location"]              # ← 直覺寫法
    ...
```

self-check 用的假 payload 是真實回應的縮小版：新欄位 `Locations` 有料、舊欄位 `location` 存在但是空的。

```bash
uv run civicguard-fetch --self-check
```

實測輸出：

```
Traceback (most recent call last):
  ...
  File ".../src/civicguard/cwa.py", line 69, in _self_check
    assert len(got) == 1, f"讀到 {len(got)} 筆，預期 1 筆 —— 是不是還在讀 records.location？"
           ^^^^^^^^^^^^
AssertionError: 讀到 0 筆，預期 1 筆 —— 是不是還在讀 records.location？
```

有些 dataset 連舊欄位都拿掉了，那時會是另一種症狀：

```
KeyError: 'location'
```

**動手（第二段：修好）**

```python
    groups = recs.get("Locations") or recs.get("location") or []
```

```bash
uv run civicguard-fetch --self-check      # → cwa self-check ok
```

**動手（第三段：把它變成記憶，而不是只印在 log）**

在 Gemini CLI 裡：

```
> 修好它，然後把這個坑寫進 docs/domain/cwa-api-notes.md，格式照現有條目，
  要寫明「什麼時候會踩到」。再在 memory/decisions.md 新增一條，編號接續，
  註明提出者為 gemini-cli。
  ✓ replace  src/civicguard/cwa.py            (+3 -3)
  ✓ replace  docs/domain/cwa-api-notes.md     (+6 -0)
  ✓ replace  memory/decisions.md              (+9 -0)   D-009
> /memory reload
  Loaded 4 context files.
```

新增的決策條目長這樣（格式見 `memory/decisions.md`）：

```markdown
## D-009 特報 parse 一律容忍舊欄位名
- 日期：2026-08-26
- 提出：gemini-cli（跑 --self-check 時發現）
- 背景：records.location 在 2024 年後改名 records.Locations，舊欄位仍存在但恆為空陣列，
  讀舊名不會報錯、只會安靜地拿到 0 筆。
- 決定：一律 `recs.get("Locations") or recs.get("location") or []`，
  並在 self-check 用假 payload 斷言至少解出 1 筆。
- 影響：docs/domain/cwa-api-notes.md 第 1 條。
- 取代：無
```

**為什麼**
- **這一段就是整個模組的縮影**：踩雷 → 修好 → 寫進 `docs/domain/` → `@import` 讓 Gemini CLI 立刻生效
  → 因為同一份檔也被 Antigravity 讀到，下次在 IDE 裡開發的 Agent 也不會再踩。一次學習，兩個 Agent 受益。
- **為什麼失敗訊息要自己寫在 assert 後面**：`AssertionError: 讀到 0 筆，預期 1 筆` 沒有下半句的話，
  下一個人（或下一個 Agent）看到只會知道「數量不對」，得重新讀一次 API 文件。
  把診斷寫進訊息裡，是最便宜的記憶。
- **為什麼一定要留回歸檢查**：文件會被讀、但不會被執行。只寫進 `docs/domain/` 的知識，
  下一次有人重寫 parser 時照樣會踩回去。`--self-check` 是那份文件的執行版本。
- **`@data-scout` 這時候派上用場**（檔案 `.gemini/agents/data-scout.md`，front matter 格式照投影片
  p.147；`/agents list` 可確認被讀到，`/agents reload` 重載）：
  `@data-scout 幫我查臺南市特報 API 的實際回應結構`。
  它有獨立上下文，探查產生的大量 JSON 不會污染主對話；工具也收斂成只有讀取類，
  不可能誤改 `src/`。而且 subagent 不能再呼叫 subagent（防遞迴）。

**驗收**

```bash
uv run civicguard-fetch --self-check           # → cwa self-check ok
uv run pytest -q                               # → 5 passed
grep -c '^## D-' memory/decisions.md           # → 3（D-007、D-008 ＋ 新的那條）
grep -n 'Locations' docs/domain/cwa-api-notes.md   # 坑有被寫進知識層
```

> 💡 **啊哈：你剛做的是「記憶的第一種存法」，全課還有兩種，差別只在「要不要每輪都送」。**
> 檔案（本 lab）：跨 agent、進版控，代價是每輪整份重送 4,520 字元 → Lab 7 的 session state
> （`lab7/travel_planner/agent.py:56`：記憶變成 dict 的 key，前綴決定作用域——無前綴只活在這條
> session，`user:` 才跨 session——但不進版控、也不是每輪整份送）→ Capstone 的向量庫
> （`capstone/schema.sql:8` 的 `documents` 表、`vector(1536)` 欄位），大到不能整份送，改成「用到才查」。
> **動手看**：`grep -n 'user:budget' ../lab7/travel_planner/agent.py; grep -n 'embedding vector' ../capstone/schema.sql`

---

## 步驟 8：交接驗證 —— 兩個 Agent 之間不用重述背景（20 分）

**動手（沒有 Antigravity 就開第二個 gemini session，驗證邏輯相同）**

在 Antigravity（或新的 `gemini` session）裡，**不要**解釋任何背景，直接說：

```
修掉 D-008 提到的四捨五入問題，並補上回歸測試。
```

它應該能自己講出：這是「數值不得四捨五入」的決策、要動 `brief.py` 的 `rain_level()`、
回歸測試放 `--self-check`（因為 `AGENTS.md` 的「測試與稽核指令」章節寫了）。

反向的交接（Gemini CLI 發現 → Antigravity 接手）長這樣：

```bash
# 半夜的 CI，headless gemini 跑例行稽核
gemini -p "稽核最近 7 天的簡報輸出，找出與 alert-taxonomy.md 不一致的用語" \
  --output-format json | jq -r '.response'

# 讓它把發現寫進共享記憶，而不是只印在 log
gemini -p "把上述發現寫成 memory/decisions.md 的新條目，編號接續，註明提出者為 gemini-cli，\
並在 docs/domain/alert-taxonomy.md 補上說明" --approval-mode auto_edit
```

**為什麼**
- **共享記憶就是它們的非同步通訊協定**。兩個 Agent 從不直接對話：夜間的 headless agent 負責
  發現與記錄，白天的互動 agent 負責理解與修復。中間的介面就是那幾份 Markdown。
- **為什麼決策要有編號**：「修掉 D-008」四個字能取代一整段背景說明，是因為 D-008 在
  `decisions.md` 裡有「背景／決定／影響」三欄。沒有編號你就得每次貼一次上下文，
  貼的過程中還會漏掉「當初為什麼不那樣做」——而那正是 Agent 最需要、也最容易自己重蹈的部分。
- **「定案」這一步不可外包**。整個循環（探索 → 定案 → 執行 → 發現 → 回流）裡，
  只有「把最終決定寫進共享記憶」必須人類動手。跳過這步，兩個 Agent 就會各自記得不同版本的結論。
- **Antigravity 沒有 `/memory` 家族、也沒有 Auto Memory**，別在那邊找。自動記憶是 Gemini CLI 獨有的能力，
  而且它刻意不准自動改專案共享的 `GEMINI.md`——那是團隊契約，只能人審後進版控。
- **遠端 MCP 設定不能直接複製**：Gemini CLI 用 `url`（SSE）／`httpUrl`（Streamable HTTP），
  Antigravity 只吃 `serverUrl`。複製錯的症狀是 Antigravity 完全看不到那個 server，沒有錯誤訊息。
  stdio 設定（本 lab 用的）兩邊格式相同，可以無腦複製，差別只在放哪個檔。

**驗收**

- [ ] 新 session 只說「修掉 D-008」，Agent 能講出背景與要動的檔案，且沒有反問你 D-008 是什麼
- [ ] 同一個問題（安裝套件用什麼指令）在兩支 CLI 得到相同答案
- [ ] Agent 提議改 `AGENTS.md` 時，你能指出「契約層要走 PR，去 `decisions.md` 提案」

> ⚠️ 未實測：本步驟全部需要 gemini CLI ／ Antigravity 實機操作。

---

## 步驟 9：驗收（5 分）

投影片 p.169：六項全過才算完成，pass/fail，沒有部分分數——記憶要嘛生效，要嘛沒生效。

```bash
# 一次跑完所有離線檢查
uv run pytest -q                                        # → 5 passed
uvx ruff check .                                        # → All checks passed!
uv run civicguard-audit --json | jq -e 'length == 0'    # → true
bash -n scripts/*.sh                                    # 無輸出
jq -e . .gemini/settings.json .agents/mcp_config.json > /dev/null && echo "設定檔合法"
```

- [ ] **① uv 唯一性**：`civicguard-audit` 回 `[]`；`git ls-files | grep uv.lock` 有東西
- [ ] **② 記憶確實載入**：`/memory list` 有 `AGENTS.md` ＋三份 `docs/domain`；`/memory show` 含 uv 規則
- [ ] **③ 跨工具一致**：`gemini -p "這個專案安裝套件要用什麼指令？只回一行。"` 與 Antigravity 同答 `uv add`
- [ ] **④ 稽核可進 CI**：乾淨 exit 0、有殘留非零，輸出走 `--output-format json`
- [ ] **⑤ 記憶會長大**：`uv run civicguard-fetch --self-check` 通過，`decisions.md` 有你新增的那條
- [ ] **⑥ 交接可驗證**：新 session 只說「修掉 D-00x」就被聽懂

---

## 常見錯誤對照表

| 症狀 | 原因 | 解法 |
|---|---|---|
| `ModuleNotFoundError: No module named 'mcp'` | 用了 `python src/civicguard/mcp_server.py` | 一律 `uv run civicguard-mcp`。這條規則寫進 `AGENTS.md`，並讓 `civicguard-audit` 在 CI 擋 |
| `ModuleNotFoundError: No module named 'mcp.server.fastmcp'. This is mcp 2.x, where FastMCP was renamed to MCPServer…` | 投影片寫的 `FastMCP` 是 mcp 1.x 的類別名 | 改 `from mcp.server.mcpserver import MCPServer`，或 `uv add "mcp<2"` 釘舊版 |
| `error: Failed to spawn: civicguard-mcp` / `Caused by: No such file or directory (os error 2)` | 不在專案目錄裡，或 `uv init` 沒給 `--name`（套件名被壓成 `lab3-5`） | `cd lab3.5`；重建時用 `uv init lab3.5 --package --name civicguard` |
| `AssertionError: 讀到 0 筆，預期 1 筆 —— 是不是還在讀 records.location？` | CWA 欄位改名成 `records.Locations`，舊欄位存在但恆為空陣列 | `recs.get("Locations") or recs.get("location") or []`，並把坑寫進 `docs/domain/cwa-api-notes.md` |
| `KeyError: 'location'` | 同上，但那個 dataset 連舊欄位都移除了 | 同上。不要用 `[]` 取值，一律 `.get(...) or []` |
| `jq: parse error: Invalid numeric literal at line 2, column 0` | 模型把 JSON 包在 ```` ```json ```` 圍籬裡，`fromjson` 吃不下 | prompt 明寫「只輸出 JSON」，管線裡 `sed -e 's/^```json//' -e 's/^```$//'` |
| 查得到縣市但特報永遠是空的 | 縣市名打「台南市」，官方資料是「臺南市」 | `fetch()`／`parse_alerts()` 一進來就 `city.replace("台", "臺")`，再用 `in` 寬鬆比對（只用 `in` 沒用，「台南市」不是「臺南市」的子字串） |
| Agent 一直回 `pip install` | `.gemini/settings.json` 沒設 `context.fileName`，預設只讀 `GEMINI.md` | 加 `{"context":{"fileName":["AGENTS.md","GEMINI.md"]}}`，然後 `/memory reload` |
| 設定寫了但完全沒生效，也沒報錯 | 用了舊的扁平鍵 `contextFileName`（只有 `gemini-extension.json` 才用那個名字） | 改成巢狀 `context.fileName` |
| Antigravity 的規則完全沒生效，無提示 | 建了 `.antigravity/` 目錄 | 官方目錄是 `.agents/`（舊版 `.agent/`） |
| MCP server 顯示掛掉但看不到原因 | stdio server 用 `print()` 除錯，污染了協定通道 | 所有訊息 `print(..., file=sys.stderr)` 或用 logging |
| Agent 看得到 server 卻叫不到工具，沒有錯誤 | server 名稱含底線，`mcp_<server>_<tool>` 被切錯位 | server 名稱不含底線（`civicguard` 可以，`civic_guard` 不行） |
| Antigravity 完全看不到遠端 MCP server | 直接複製了 Gemini CLI 的 `url` / `httpUrl` | Antigravity 只吃 `serverUrl`；stdio 設定才能無腦共用 |
| `unknown command: /memory add` / 找不到 `save_memory` 工具 | v0.56 已移除這兩個 | 直接叫 Agent「把這件事記下來」，它會用 `write_file`／`replace` 改 Markdown |
| `/memory inbox` 每次都是空的 | Auto Memory 觸發條件是 session 閒置 ≥ 3 小時且 ≥ 10 則使用者訊息，且證據不夠強時預設不產生任何東西 | 正常現象，不是壞掉。改完 `experimental.autoMemory` 要**重開 CLI** |
| 改了 `AGENTS.md`，Agent 還在講舊規則 | 記憶是啟動時載入的 | `/memory reload`（別名 `/memory refresh`） |
| 你以為在用 Vertex AI，其實還在打 AI Studio 額度 | auto-detect 第 4 條 `GEMINI_API_KEY` 搶先命中 | 走 ADC 前先 `unset GEMINI_API_KEY GOOGLE_API_KEY` |
| CI 綠燈但簡報是空的 | gemini 吐空字串仍回 exit 0 | `test -s "$OUT" \|\| { echo "empty brief" >&2; exit 1; }` |
| 稽核器把 `AGENTS.md` 裡「禁止 pip install」那行當違規 | 規則本身被自己的稽核器抓到 | 行內加豁免標記 `<!-- uv-ok -->`（Markdown 渲染後看不見） |

---

## 完整解答

本目錄就是走完九步的成品：

| 檔案 | 內容 |
|---|---|
| `AGENTS.md` | 契約層：uv 規則、測試指令、記憶契約表、四個 `@import` |
| `GEMINI.md` | 兩行轉接 |
| `docs/domain/*.md` | 知識層三份（API 踩雷、分級規則、縣市欄位差異） |
| `memory/decisions.md` | D-007、D-008、D-009（步驟 7 的產物） |
| `.gemini/settings.json` | `context.fileName`、`autoMemory`、`mcpServers` |
| `.gemini/commands/{brief,audit}.toml` | `/brief 臺南市`、`/audit` |
| `.gemini/agents/data-scout.md` | 只讀的探查 subagent |
| `.agents/rules/*.md`、`.agents/mcp_config.json`、`.agents/skills/` | Antigravity 側 |
| `src/civicguard/cwa.py` | 特報 parse（含 `Locations` 欄位坑 ＋ self-check） |
| `src/civicguard/shelters.py` | 22 縣市欄位正規化（D-007） |
| `src/civicguard/brief.py` | 分級與文案（D-008，含 79.9 的回歸斷言） |
| `src/civicguard/audit.py` | uv-only 稽核器 |
| `src/civicguard/mcp_server.py` | MCP stdio server（三個工具） |
| `scripts/{ci_audit,daily_brief}.sh` | 兩層稽核、每日簡報 |
| `.github/workflows/brief.yml` | 台北 06:00 排程 |
| `tests/test_selfchecks.py` | 五支 self-check 收成 pytest |
| `aha.py` | 離線 demo：`--show` 展開 `@import`、`--cost` 算每輪 context 成本 |

卡住時再開。想看每一支怎麼跑，讀檔案頂端的 docstring。

## 想再往下玩

- **補上第三層防線**：寫 `.gemini/hooks/hooks.json`，在 `PreToolUse` 攔 `run_shell_command`，
  指令含 `pip install` 就拒絕並回傳等價的 uv 指令——Agent 會自己改寫後重試，你不用出手。
- **把稽核接成 GitHub Action**：改用 `google-github-actions/run-gemini-cli`，加上 PR 審查與 issue 分流；
  CLI 內打 `/setup-github` 可以一鍵產生設定。
- **`decisions.md` 開始長大之後**：寫一支腳本把已結案的搬進 `decisions-archive.md`，
  並且**不要** `@import` 它——每次提問都會送出，這是最容易失控的費用來源，用 `/stats` 追。
- **把剩下 19 個縣市補完**：`gemini -p "依 D-007 與 shelter-quirks.md，對 22 個縣市逐一產生 normalize 對照並寫入 tests/fixtures" -o json`，
  跑完叫它把新發現的欄位差異補回 `shelter-quirks.md`，形成閉環。
- **下一站 Lab 4（M4 NotebookLM）**：當知識量超過 Markdown 能承載的規模時，記憶要再往外推一層。

## 這個 Lab 你真正學到的

- **「context engineering」不是抽象名詞，是幾個檔案路徑**：記憶的實體就是 `AGENTS.md` 的 `@import` 展開後那 4,520 字元，用 `uv run aha.py --show` 一眼看完。
- **跨廠商共用記憶不需要協定，只需要同一個路徑**：Antigravity 與 Gemini CLI 之間沒有任何整合，共享的只有 Markdown 文字；設定檔、對話、產出物一律不共享。
- **記憶是有單價的**：每一輪提問都整份重送，所以「寫進記憶」和「刪出記憶」一樣重要——這是之後所有 lab 選擇存法的判準。
- **我知道檔案式記憶在生態系裡的位置**：它是「記憶」這條主線的第一站，往後是 Lab 7 的 session state、Capstone 的 pgvector，同一件事換容器。
- **規則要生效必須有執行版本**：寫進 `docs/domain/` 的知識會被讀但不會被執行，所以每條規則旁邊都要有一支 `--self-check` 或 CI 稽核在守。

## 清理

沒有雲端資源。全部丟掉：

```bash
cd .. && rm -rf lab3.5
```

只清本機快取與產出物：

```bash
rm -rf .venv .pytest_cache .ruff_cache data reports
uv sync --frozen        # 需要時一行還原
```

排程 workflow 如果已經推上 GitHub，記得到 Actions 頁面把 `daily-civic-brief` 停用——
不然它每天早上六點都會花你的 API 額度。
