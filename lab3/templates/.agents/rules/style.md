<!-- 啟用模式：Always On -->

# 團隊風格規範（style.md）

## 語言與型別

- 前端一律 TypeScript，`tsconfig.json` 必須維持 `"strict": true`。
- **禁止** `any`、`@ts-ignore`、`as unknown as`。型別不會寫就先問我，不要繞過檢查器。
- 所有 export 的函式**必須**有明確回傳型別。

## 註解與命名

- 註解一律繁體中文，一行講完「為什麼這樣寫」，不要複述程式碼在做什麼。
- 檔名 kebab-case、元件 PascalCase、hook 以 `use` 開頭。

## 流程

- 完成前**必須**跑 `npm run lint` 與 `npx tsc --noEmit`，有錯不得交付。
- 任何持久化格式（localStorage / IndexedDB key 與 schema）變更**必須**在 Implementation Plan 裡先講清楚。
- commit message 用 Conventional Commits（`feat:` / `fix:` / `chore:`）。

## 溝通

- Implementation Plan 與 Walkthrough 一律繁體中文。
- 風險與 breaking change 用**粗體**標示。
- 不確定的需求**不得**自己猜，先問。
