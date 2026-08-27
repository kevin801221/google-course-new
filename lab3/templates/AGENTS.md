# AGENTS.md

> 這份檔案是跨工具的開放慣例：Antigravity（v1.20.3+ 原生支援）、Antigravity CLI（agy）、
> Gemini CLI 與其他 coding agents 都會讀。專案專屬的細規則放 `.agents/rules/`，用 @ 引用。

## 這個專案是什麼

<一句話：例「Lab 2 從 AI Studio Build 匯出的單頁 React app，功能是 XXX」>

## 指令（agent 要驗證時一律用這幾條，不要自己發明）

| 目的 | 指令 |
|---|---|
| 安裝依賴 | `npm ci`（沒有 lockfile 才用 `npm install`） |
| 起 dev server | `npm run dev` → http://localhost:5173 |
| 型別檢查 | `npx tsc --noEmit` |
| Lint | `npm run lint` |
| 建置 | `npm run build` |

## 硬規則

- 完成任何任務前**必須**跑 `npm run lint` 與 `npx tsc --noEmit`，兩者全綠才算完成。
- **禁止**新增 UI 套件或狀態管理套件；需要新依賴一律先問我。
- **禁止**把 API key 寫進原始碼或 commit `.env`；一律走環境變數。
- 詳細程式風格見 @.agents/rules/style.md

## 驗證方式

- 前端行為改動**必須**用 Browser surface 實測一遍，並把錄影／截圖存到 `docs/evidence/`。
- 工程化設定改動後跑：`uv run <lab3 教材目錄>/check_lab3.py .`（把路徑換成你電腦上 lab3 的位置）
