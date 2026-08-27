# Lab 3.5 PRD：讓兩個 Agent 共用一份會長大的記憶（CivicGuard）

> 模組 M3.5 Gemini CLI × Antigravity 記憶協作 ｜ 投影片 p.167-170 ｜ 90 分鐘 ｜ 免費層＊
> ＊Gemini API key 走免費層即可；CWA open data 免費申請。個人 Google 帳號登入 Gemini CLI 已於 2026/06/18 停止服務，本 lab 全程用 API key。

## 1. 這個 Lab 要解決什麼問題

一個團隊同時用 Antigravity（互動開發、規劃、瀏覽器驗證）和 Gemini CLI（headless 批次、CI、排程），
但兩支工具的記憶預設各存各的：同一個資料欄位地雷，你會在 IDE 裡踩一次、半夜的 CI 再踩一次，
而且兩邊給的答案還可能互相矛盾。這個 Lab 用一個真實會髒的專案（CivicGuard 民生示警守護站）
把「單一事實來源」落地成檔案：`AGENTS.md` 當契約、`docs/domain/` 當會長大的知識、
`memory/decisions.md` 當兩個 Agent 的非同步交接介面——證明記憶是被寫進檔案的，不是留在某一次對話裡。

## 2. 學習目標

1. 建出一個符合本課規範的 uv 專案（`--package`），並讓 MCP server、CLI 腳本都用 `uv run` 跑起來。
2. 寫出一份 `AGENTS.md`，用 `@import` 拆出三份領域文件，讓兩支 CLI 讀到同一份規則。
3. 設定 `context.fileName`，並用「同一個問題問兩邊」的方式驗證記憶真的載入（而不是自我感覺良好）。
4. 說得出「記憶」的實體是什麼：`@import` 展開後那幾 KB 字元，以及它每一輪重送一次的成本（`uv run aha.py --show` / `--cost`）。
5. 寫出一支能進 CI 的 headless 稽核腳本：輸出結構化 JSON、乾淨 exit 0、有殘留回傳非零。
6. 完成一次完整交接：讓 Agent 把踩雷原因寫進 `docs/domain/` 與 `decisions.md`，下一個 session 不用重述背景就能接手。

## 3. 使用者故事

- 身為學生，我想讓 Antigravity 和 Gemini CLI 讀同一份專案規則，以便不用在兩個工具裡各講一次「本專案只准用 uv」。
- 身為學生，我想把「API 欄位改名」這種坑寫成檔案，以便下次開專案的 Agent 一開場就已經知道。
- 身為學生，我想有一支能在 CI 裡紅燈的稽核腳本，以便規則退步時當場被擋下來，而不是等 code review 抓。
- 身為學生，我想只說「修掉 D-008」就被聽懂，以便不用每次交接都重貼一次背景。

## 4. 功能需求

| 編號 | 需求 | 對應投影片步驟 | 必要 / 加分 |
|---|---|---|---|
| FR-1 | uv 專案 `civicguard`（`--package`、Python 3.13），依賴 `mcp[cli]` `httpx` `google-genai`，dev 依賴 `pytest` `ruff`，`uv.lock` 進版控 | p.168 ① | 必要 |
| FR-2 | 目錄骨架：`docs/domain/`、`memory/`、`.gemini/commands/`、`.agents/rules/` | p.168 ① | 必要 |
| FR-3 | MCP server（stdio）提供 3 個工具：`active_alerts`、`normalize_shelters`、`daily_brief`；可用 `uv run civicguard-mcp` 啟動 | p.167「含 MCP server」 | 必要 |
| FR-4 | `AGENTS.md` 至少含：專案概要／Python 工作流（uv）／測試指令／`@import` 三份 `docs/domain` 與 `memory/decisions.md` | p.168 ② | 必要 |
| FR-5 | 三份領域文件實際有內容：`cwa-api-notes.md`（踩雷）、`alert-taxonomy.md`（分級）、`shelter-quirks.md`（縣市欄位差異） | p.168 ② | 必要 |
| FR-6 | 接線：`.gemini/settings.json` 設 `context.fileName = ["AGENTS.md","GEMINI.md"]`；`GEMINI.md` 只留 `@./AGENTS.md` 一層轉接 | p.168 ③ | 必要 |
| FR-7 | 記憶載入驗證：`gemini -p "這個專案安裝套件要用什麼指令？只回一行。"` 要答 `uv add <pkg>` | p.168 ④ | 必要 |
| FR-8 | headless 稽核：找出任何直接呼叫 `python` / `pip` / `venv` 的地方，`--output-format json`，乾淨 exit 0、有殘留非零 | p.168 ⑤ | 必要 |
| FR-9 | 字面稽核器 `civicguard-audit`：離線、確定性、`--json` 輸出、`--self-check` 可驗 | 補（p.168 ⑤ 的 CI 可靠版） | 必要 |
| FR-10 | 記憶會長大：刻意製造一次失敗，讓原因被寫進 `docs/domain/` 與 `memory/decisions.md`，並留下回歸檢查 | p.169 ⑤ | 必要 |
| FR-11 | 交接可驗證：新 session 只說「修掉 D-00x」，Agent 知道在講什麼 | p.169 ⑥ | 必要 |
| FR-12 | `.agents/rules/uv-only.md` 設 `activation: always_on` 作為 Antigravity 側第二層保險 | p.158 | 必要 |
| FR-13 | Custom command `/brief`、`/audit`（TOML）與 `data-scout` subagent | p.146、p.147 | 加分 |
| FR-14 | `scripts/daily_brief.sh` ＋ GitHub Actions 排程 workflow | p.152、p.153 | 加分 |
| FR-15 | `.agents/skills/shelter-normalize/SKILL.md`：把正規化流程封裝成 skill | p.134 | 加分 |

## 5. 非功能需求

| 項目 | 要求 |
|---|---|
| 時間盒 | 90 分鐘：骨架 20＋記憶 20＋稽核 25＋交接驗證 25 |
| 費用上限 | $0。Gemini API 免費層；CWA open data 免費；不動用任何 GCP 付費資源 |
| 離線可測 | 五支模組各有 `--self-check`，不連網不花錢；`uv run pytest -q` 一次跑完 |
| 跨平台 | macOS / Linux / WSL2。需要 Node.js ≥ 20（gemini CLI）與 `jq` |
| Agent 可讀性 | 所有規則都是純 Markdown，不依賴任何工具專屬格式；設定檔不共享 |
| 沒有 Antigravity 也能做 | 第 8 步可改成「開第二個 gemini session，只讀 AGENTS.md，看它能不能接手」 |

## 6. 驗收標準

對應投影片 p.169「六項全過才算完成」，pass/fail，沒有部分分數。

- [ ] **① uv 唯一性**：repo 內找不到任何 `pip install`、`python -m venv`、直接 `python xxx.py`；`uv.lock` 已進版控
  ```bash
  uv run civicguard-audit --json | jq -e 'length == 0'   # → true，exit 0
  git add -A && git ls-files | grep -q '^uv.lock$' && echo "uv.lock 已進版控"
  ```
  > 本目錄的 `.git` 是 `uv init` 建的，檔案已放進 index。要讓 `git checkout <file>` 能還原
  > （步驟 6 會用到），先 `git commit -m "init civicguard"`。
- [ ] **② 記憶確實載入**：`/memory list` 看得到 `AGENTS.md` 與三份 `docs/domain`；`/memory show` 內含 uv 規則
  ```bash
  gemini            # slash command 只能在互動模式打，-p 不吃 /memory
  > /memory list    # 應列出 AGENTS.md ＋ 三份 docs/domain
  > /memory show    # 內含「Python 工作流（強制）」那一段
  ```
  > ⚠️ 未實測：需要 gemini CLI ＋ `GEMINI_API_KEY`（本教材撰寫環境沒安裝）。
- [ ] **③ 跨工具一致**：同一個問題在 Gemini CLI 與 Antigravity 得到相同答案
  ```bash
  gemini -p "這個專案安裝套件要用什麼指令？只回一行。"   # → uv add <pkg>
  ```
- [ ] **④ 稽核可進 CI**：乾淨 exit 0、有殘留非零，輸出走 JSON 不 parse 人類文字
  ```bash
  uv run civicguard-audit; echo "exit=$?"              # → 稽核完成：0 處違規 / exit=0
  bash scripts/ci_audit.sh                             # 兩層都過才算
  ```
- [ ] **⑤ 記憶會長大**：刻意製造一次失敗，原因被寫進 `docs/domain/` 與 `decisions.md`，且下次不再犯
  ```bash
  uv run civicguard-fetch --self-check    # → cwa self-check ok（回歸檢查擋住舊欄位名）
  grep -c '^## D-' memory/decisions.md    # → 至少 3（D-007、D-008 ＋ 你新增的那條）
  ```
- [ ] **⑥ 交接可驗證**：新開 session 不重述背景，直接說「修掉 D-00x」，Agent 知道你在講什麼
  ```bash
  gemini -p "D-008 是什麼？我要修掉它，先講你要動哪幾個檔。"
  ```

全部檢查一次跑完：

```bash
uv run pytest -q                                      # → 5 passed
uvx ruff check .                                      # → All checks passed!
uv run civicguard-audit --json | jq -e 'length == 0'   # → true
```

## 7. 範圍外

- **不做真的資料管線**：不建資料庫、不做定時抓取的正式版；`data/`、`reports/` 都在 `.gitignore` 裡。
- **不做前端／地圖**：投影片提到的地圖與無障礙標籤是 Antigravity 側的延伸練習，不在本 lab 驗收。
- **不遷移到 agy**：`agy plugin import gemini` 屬於 p.165 的延伸，不做。
- **不寫 Hook 攔截**：p.137 的三層防線第③層（`.gemini/hooks/hooks.json`）本 lab 用 `civicguard-audit` 在 CI 擋，不寫 hook。
- **不追求 CWA 欄位 100% 正確**：欄位名以投影片與 open data 文件為準，實際回應請用 `@data-scout` 驗證後更新 `docs/domain/`。
- **不做 Auto Memory 的產出驗收**：它「證據不夠強時預設不產生任何東西」，多數 `/memory inbox` 是空的，無法當驗收條件。

## 8. 費用與風險

| 項目 | 費用 | 風險與對策 |
|---|---|---|
| Gemini API key | 免費層（AI Studio 建立） | 排程任務最容易失控燒額度：`--model` 指定便宜模型、`--allowed-mcp-server-names` 限制範圍、`/stats` 追用量 |
| CWA open data | 免費（需註冊會員拿 Authorization key） | key 不要 commit，放 `.gemini/.env` |
| Gemini CLI | 開源 Apache-2.0 免費 | 2026/06/18 起免費個人帳號登入已停止服務，只能用 API key／Vertex AI |
| GitHub Actions | 公開 repo 免費額度 | 排程 workflow 記得設 `workflow_dispatch` 才能手動測；secrets 用 `GEMINI_API_KEY`、`CWA_API_KEY` |
| 隱私 | — | `experimental.autoMemory` 會把對話摘錄送給模型做萃取。機敏專案先評估再開 |

**沒有雲端資源要清**。本 lab 只在本機建檔案。要整個丟掉：

```bash
cd .. && rm -rf lab3.5        # 沒有任何雲端殘留
```

## 9. 前置依賴

| 依賴 | 從哪來 | 沒有會怎樣 |
|---|---|---|
| `uv` | `curl -LsSf https://astral.sh/uv/install.sh \| sh`（M0） | 整個 lab 跑不了 |
| Node.js ≥ 20 | 官網或 `brew install node` | `npm install -g @google/gemini-cli` 會失敗 |
| Gemini CLI 0.56.x | `npm install -g @google/gemini-cli` | 第 5、6、8 步無法做（程式碼部分仍可跑） |
| `GEMINI_API_KEY` | <https://aistudio.google.com/apikey>（Lab 1 已拿過） | `gemini -p` 直接失敗 |
| `jq` | `brew install jq` | 稽核的 exit code 判斷做不了 |
| `CWA_API_KEY` | <https://opendata.cwa.gov.tw> 免費註冊 | 只影響真的打 API；所有 `--self-check` 不需要 |
| Antigravity（選配） | <https://antigravity.google/download>（Lab 3） | 第 8 步改用「第二個 gemini session」替代，驗證邏輯相同 |
