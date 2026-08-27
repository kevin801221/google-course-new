# CivicGuard — Agent 說明書

這份檔案是本專案**唯一的事實來源**。Antigravity（v1.20.3 起原生讀）與 Gemini CLI
（靠 `.gemini/settings.json` 的 `context.fileName`）都讀同一份，所以規則只寫在這裡。

## 專案概要

把政府開放資料（中央氣象署特報／雨量、各縣市避難收容處所）轉成人話版示警簡報。
資料是真的髒的：欄位會改名、22 個縣市命名不一致。踩到的坑一律寫進 `docs/domain/`，
不要留在對話裡。

## Python 工作流（強制）

- 本專案一律使用 uv，**禁止**直接呼叫 `python`、`python3`、`pip`、`pip3`、`venv`、`virtualenv`。<!-- uv-ok 這行在講規則本身，稽核器要豁免 -->
- 安裝套件：`uv add <pkg>`（開發相依加 `--dev`）
- 執行程式：`uv run <cmd>`
- 一次性工具：`uvx <tool>`
- 還原環境：`uv sync --frozen`
- `uv.lock` 必須提交進版控，不可手改。

若你正要輸入 `pip install`，請停下來改成 `uv add`，並在 `memory/decisions.md` 留下一行說明。<!-- uv-ok -->

## 測試與稽核指令

```bash
uv run civicguard-audit --self-check     # 稽核器自我檢查
uv run civicguard-mcp   --self-check     # MCP 工具有沒有註冊成功
uv run civicguard-brief --self-check     # 分級與文案（含 D-008 回歸）
uv run civicguard-fetch --self-check     # 特報 parse（含 Locations 欄位坑）
uv run civicguard-shelters --self-check  # 22 縣市欄位正規化
uv run civicguard-audit --json | jq -e 'length == 0'   # CI 把關：非零就是有 uv 違規
uvx ruff check .
```

## 寫入權限（記憶契約）

| 層 | 檔案 | 誰可以寫 |
|---|---|---|
| 契約層 | `AGENTS.md` | 只有人類（PR 審核）。Agent 要改就去 `memory/decisions.md` 提案 |
| 知識層 | `docs/domain/*.md` | Agent 可直接寫，格式要跟現有條目一致 |
| 決策層 | `memory/decisions.md` | 兩個 Agent 都可寫，**append-only**，只增不改 |
| 工具層 | `.gemini/`、`.agents/` | 人類為主，變更視同程式碼變更 |

## 領域知識（拆檔維護）

@./docs/domain/cwa-api-notes.md
@./docs/domain/alert-taxonomy.md
@./docs/domain/shelter-quirks.md

## 決策紀錄

@./memory/decisions.md
