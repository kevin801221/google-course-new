# Lab 3 PRD：讓 Agent 工程化你的 Lab 2 專案

> 所屬模組：M3 Antigravity：Agent-First 開發平台 ｜ LAB 投影片：第 122 頁 ｜ 60–90 分 ｜ 免費層可完成

## 1. 這個 Lab 要解決什麼問題

Lab 2 用 AI Studio Build「vibe coding」生出一個能跑的 app，但它是一坨沒有規範、沒有測試證據、沒有版控的程式碼 —— 換一個人（或換一次對話）接手就重來一遍。這個 Lab 把那坨東西交給 Antigravity 的 agent，走完一次完整的 **plan → execute → browser 驗證 → 回饋** 循環，並把「你希望 agent 怎麼工作」落成三個實體檔案（`AGENTS.md`、`.agents/rules/style.md`、`.agents/mcp_config.json`）＋一份可執行的驗收腳本。結束時你得到的不是「AI 幫我寫好了」，而是「這個專案從此有規範、有驗證證據、有 remote repo」。

## 2. 學習目標

做完你會：

1. **寫**一份 agent 會真的遵守的 rule 檔（Always On、硬性字眼、12,000 字元上限），說得出 rule / workflow / skill / knowledge 的分工，並用數字說明「決定 agent 產出的是 repo 裡有什麼，不是 prompt 打多長」。
2. **審**並**改** agent 的 Implementation Plan，用留言讓回饋在不中斷執行的情況下被吸收。
3. **驗**agent 的 Browser surface 產出：從 Walkthrough 打開錄影，確認它真的點過每個按鈕，而不是只說「已完成」。
4. **設**一個 MCP server（`.agents/mcp_config.json`），分辨 stdio（`command`，本質是一個講 JSON-RPC 的子行程）與遠端（`serverUrl`，**不是** `url`）兩種傳輸，用 `disabledTools` 做最小權限，並說得出同一格在 Lab 6（自己當提供者）與 Lab 10（推上 Cloud Run）會變成什麼。
5. **跑**一支驗收腳本，把「工程化做完了沒」變成 exit code，而不是感覺。

## 3. 使用者故事

- 身為學生，我想把 Lab 2 那個沒人管的專案交給 agent 整理，以便我知道「工程化」在 agent 時代具體是哪幾個檔案。
- 身為學生，我想在 agent 動工**之前**看到它的計畫並提出修改，以便我不用等它寫錯 200 行才發現方向不對。
- 身為學生，我想看到 agent 自己開瀏覽器操作的錄影，以便我敢相信「功能可用」這句話。
- 身為學生，我想把 GitHub 接成 MCP 工具，以便 agent 能自己建 repo 推程式碼，我不用切出去手動操作。
- 身為講師，我想有一個指令就能判斷學生做完沒有，以便驗收 30 個人不用一個一個看畫面。

## 4. 功能需求

| 編號 | 需求 | 對應投影片步驟 | 必要／加分 |
|---|---|---|---|
| FR-1 | 在 Antigravity 建立 Project，匯入 Lab 2 專案資料夾（沒做 Lab 2 → 用任一自己的 repo，或用 §9 的替代方案 60 秒生一個） | 步驟 1 | 必要 |
| FR-2 | 專案根目錄有 `AGENTS.md`，寫明指令、硬規則、驗證方式 | 步驟 2（延伸 p.106 優先序） | 必要 |
| FR-3 | 有 `.agents/rules/style.md`：TypeScript strict、繁中註解、完成必跑 lint；標註啟用模式 Always On；≤ 12,000 字元 | 步驟 2 | 必要 |
| FR-4 | 用 `/grill-me` 派任務「加上輸入歷史紀錄與收藏功能，資料存 localStorage」，回答完 agent 的反問才動工 | 步驟 3 | 必要 |
| FR-5 | 審 Implementation Plan，**至少留一則修改留言**（例：改用 IndexedDB），並在後續 plan 或 Walkthrough 看到它被吸收 | 步驟 4 | 必要 |
| FR-6 | Walkthrough 附 Browser surface 的操作錄影／截圖；學生打開看過，並另存一份到 `docs/evidence/` | 步驟 5 | 必要 |
| FR-7 | 接一個 MCP server（GitHub），寫進 `.agents/mcp_config.json`，refresh 後工具可用 | 步驟 6 | 必要 |
| FR-8 | 請 agent 用 MCP 建 GitHub repo 並推上程式碼，commit message 走 Conventional Commits | 步驟 6 | 必要 |
| FR-9 | `uv run check_lab3.py <專案路徑>` 全綠（單一 rule 檔時是 11 項，exit 0；判準是 `0 失敗`） | 步驟 7 | 必要 |
| FR-10 | rule 生效的反證：先在**沒有** rule 的狀態下派一個小任務，看到英文註解／`any`，再加 rule 重跑對照；用 `uv run check_lab3.py --aha` 把差距量化成數字 | 教學設計（p.104–105） | 加分 |
| FR-11 | 把這次流程存成 workflow（`.agents/workflows/`），下次一個指令重跑 | p.107 | 加分 |
| FR-12 | `disabledTools` 把 GitHub 的破壞性工具先關掉（樣板已預填實測過的工具名 `merge_pull_request`／`create_pull_request_review`／`fork_repository`） | p.118 | 加分 |

## 5. 非功能需求

| 項目 | 要求 |
|---|---|
| 時間盒 | 60–90 分。步驟 3–5 是 agent 在跑，等待時去讀它的 Task List，不要盯著轉圈 |
| 費用上限 | $0。Antigravity 免費層＋GitHub 免費帳號即可。credits 不夠就把 `/effort` 降到 low、`/model` 換 `gemini-3.7-flash` |
| 離線可測 | 三個交付檔案＋`check_lab3.py` 完全離線可驗（`--self-check` 不連網、不花錢）。Antigravity 本體、MCP、GitHub push 需要網路與帳號 |
| 跨平台 | macOS 12+／Windows 10 64-bit（建議 WSL2）／Linux glibc ≥ 2.28。Browser surface 需本機安裝 Chrome |
| 可重跑 | 所有交付檔案都是純文字，砍掉重來成本 < 1 分鐘 |

## 6. 驗收標準

對應投影片步驟 7「功能可用＋錄影存在＋GitHub repo 有完整 commits」，加上可執行的檢查：

```bash
cd /path/to/你的專案
uv run $COURSE/lab3/check_lab3.py .
```

預期最後一行是 `11 過 / 0 失敗`、exit code 0。（`11` 是只有一份 rule 檔的情況，每多一份 `.agents/rules/*.md` 多 4 項；判準是 `0 失敗`。）

- [ ] Antigravity Project 開得起來，agent 讀得到專案檔案（`/codesearch` 搜得到你的元件名）
- [ ] `AGENTS.md` 在根目錄，內含可跑的指令表
- [ ] `.agents/rules/style.md` 有 `啟用模式：Always On`、≥ 3 條「必須／禁止」、無「盡量」、≤ 12,000 字元
- [ ] agent 產出的程式碼註解是繁體中文、沒有 `any`（`grep -rn ": any" src/` 沒東西）
- [ ] `npm run lint` 與 `npx tsc --noEmit` 全綠
- [ ] 歷史紀錄與收藏功能在瀏覽器裡真的能用，重新整理後資料還在
- [ ] Walkthrough 裡有 browser 錄影／截圖，且 `docs/evidence/` 有一份備份
- [ ] Implementation Plan 的留言在後續版本被吸收（截圖留證）
- [ ] `.agents/mcp_config.json` 是合法 JSON、用 `serverUrl`／`command`、token 走 `$ENV_VAR`
- [ ] GitHub 上有這個 repo，≥ 2 個 commit，message 是 `feat:`／`chore:` 格式
- [ ] `uv run check_lab3.py --self-check` 通過

## 7. 範圍外

- **不寫後端、不部署**。上雲是 M10／Lab 10 的事。
- **不做 Hooks、Subagents、Skills 的完整實作**（p.109–112 概念頁），這個 Lab 只碰 rules 與 MCP 各一個。多的留給 Lab 6（自建 MCP server）與 Lab 3.5（跨工具共享記憶）。
- **不比較模型**。想比 Flash vs Pro 是 M1 的事。
- **不追求功能完美**。歷史紀錄與收藏只是「一個足夠複雜、需要規劃與驗證的任務」載體；agent 的流程才是主角。
- **不手動寫功能程式碼**。你只寫規範檔與留言；`src/` 底下的東西一行都不該由你打字。

## 8. 費用與風險

| 項目 | 費用 | 說明 |
|---|---|---|
| Antigravity | $0 | 免費層：個人 Google 帳號，每月基本 credits 週期性刷新。AI Pro $19.99/月更順 |
| GitHub | $0 | 免費帳號＋PAT |
| GCP | 不需要 | 這個 Lab 完全不碰 GCP |

風險與對策：

- **credits 燒光**：credits 算「agent 完成的工作量」，不是 token；儀表板有五小時／週雙限額。派任務前先 `/effort low`、`/model gemini-3.7-flash`，卡關才升。
- **prompt injection**（p.121，PromptArmor 2025/11）：browser subagent 讀到的網頁內容都可能是攻擊指令。**這個 Lab 只讓 agent 開 localhost**，不要叫它去讀不認識的網站。
- **機密外洩**：`.env` 不進 repo，PAT 只放環境變數（`check_lab3.py` 會抓明文 token）。GitHub PAT 用 fine-grained、只給這一個 repo、只給 contents 寫入權。
- **權限**：MCP 工具權限維持 `Ask`；GitHub server 先用 `disabledTools` 關掉破壞性工具。

清理（做完課程不想留東西）：

```bash
# 1) 刪 GitHub repo（gh CLI）
gh repo delete <你的帳號>/<repo> --yes
# 2) 撤銷 PAT：github.com/settings/tokens → Revoke
# 3) 移除 MCP server：把 .agents/mcp_config.json 的 github 區塊刪掉，UI 按 refresh
# 4) Antigravity 端：Settings → Customizations → Installed MCP Servers → 移除
```

## 9. 前置依賴

| 依賴 | 怎麼取得 | 沒有的話 |
|---|---|---|
| Lab 2 的專案資料夾 | AI Studio Build → Download code，解壓後是一個 React + TS 專案 | 用任一自己的 repo；或 60 秒生一個替代品：<br>`npm create vite@latest lab2-app -- --template react-ts && cd lab2-app && npm i`<br>再手動加一個「輸入框 + 送出 + 顯示結果」的最小頁面（或直接請 agent 加），Lab 3 的步驟完全照走 |
| Antigravity 2.0 桌面版 | <https://antigravity.google/download>，Google 帳號登入 | 這個 Lab 做不了；`agy` CLI 共用同一套 rules／MCP 設定，可退而用 CLI 走步驟 2、6、7，但步驟 4、5（Plan 留言、browser 錄影）需要桌面版 |
| Chrome | 本機安裝 | Browser surface 不能用，步驟 5 無法完成 |
| Node.js ≥ 20 | <https://nodejs.org> | `npx` 型 MCP server 起不來 |
| GitHub 帳號＋PAT | github.com/settings/tokens（fine-grained，勾 Contents: Read and write；建新 repo 另需 Administration: Read and write，⚠️ 未實測 —— GitHub 對此的權限規則常變，建不出來就先在網頁手開空 repo，只讓 agent push） | 步驟 6 做不了，可改用 filesystem MCP 練設定檔，但驗收的 repo 那條過不了 |
| uv | `curl -LsSf https://astral.sh/uv/install.sh \| sh` | 跑不了 `check_lab3.py` |

> 前一個 Lab 的產物就是這個 Lab 的輸入；這個 Lab 的產物（`AGENTS.md` + rules）會在 Lab 3.5 被 Gemini CLI 與 Antigravity 共用。
