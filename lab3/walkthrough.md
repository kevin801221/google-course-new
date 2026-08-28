# Lab 3 走一遍：讓 Agent 工程化你的 Lab 2 專案

> 60–90 分鐘 ｜ 完整體驗 plan → execute → browser 驗證 → 回饋循環＋一個 rule 與一個 MCP

Lab 2 給你一個「能跑但沒人管」的 app。這個 Lab 不是叫 AI 再多寫一點功能，是把那坨東西變成**有規範、有驗證證據、有 remote repo** 的專案 —— 而且功能程式碼一行都不由你打字。

做完你的專案會多這些檔案：

```
你的專案/
├── AGENTS.md                   ← 跨工具的專案事實表
├── .agents/
│   ├── rules/style.md          ← Always On 團隊規則
│   └── mcp_config.json         ← GitHub MCP server
├── docs/evidence/*.webm        ← agent 自己開瀏覽器測試的錄影
└── src/…                       ← agent 寫的歷史紀錄與收藏功能
```

以及一個一行判生死的驗收指令（下面是本機實跑的輸出，只把專案路徑換成你的）：

```
$ uv run check_lab3.py .
檢查專案：/Users/you/projects/lab2-app

PASS  AGENTS.md 存在於專案根目錄
PASS  .agents/rules/ 有 rule 檔：style.md
PASS  style.md：627 字元（上限 12000）
PASS  style.md：有標註啟用模式（Always On / Manual / Model Decision / Glob 之一）
PASS  style.md：10 條「必須／禁止／一律／不得」（至少 3 條）
PASS  style.md：沒有模糊字眼「盡量」
PASS  mcp_config.json：1 個 server（github）
PASS  github：stdio 型（command=npx）
PASS  docs/evidence/ 有 browser 驗證證據：history-favorite.webm, shot.png
PASS  git 有 2 個 commit（至少 2）
PASS  git remote origin：https://github.com/YOU/lab2-app.git

11 過 / 0 失敗
```

每一步都是「動手 → 為什麼 → 驗收」。驗收沒過不要往下走。

---

## 步驟 0：前置（8 分）

**動手**

```bash
# 1) Antigravity 桌面版：https://antigravity.google/download → Google 帳號登入
# 2) Chrome：Browser surface 要用（步驟 5）
# 3) Node.js ≥ 20：npx 型 MCP server 要用
node --version        # 要 v20 以上
# 4) uv：跑驗收腳本
uv --version
# 5) GitHub PAT：github.com/settings/tokens → Fine-grained token
#    勾 Contents: Read and write ＋ Administration: Read and write（要建 repo）
export GITHUB_PAT="github_pat_貼上你的"
```

**沒做 Lab 2 怎麼辦**：任何有前端輸入框的 repo 都可以。完全沒有的話 60 秒生一個：

```bash
npm create vite@latest lab2-app -- --template react-ts
cd lab2-app && npm install
# 在 src/App.tsx 留一個「輸入框 + 送出 + 顯示結果」的最小頁面就夠了
# 懶得寫？步驟 3 之前先叫 agent 補：「把 App.tsx 改成一個輸入框加送出按鈕，送出後把文字顯示在下方」
```

**為什麼**
- 要有 `package.json` 與 `npm run dev`：agent 的 Terminal surface 靠這兩個起 dev server，Browser surface 才有東西可以點。沒有 dev server，步驟 5 的錄影就只有一個空白頁。
- PAT 用 fine-grained 而不是 classic：classic token 是「你整個帳號」的權限，agent 拿到就等於拿到全部 repo。投影片 p.121 的教訓 —— 災害半徑＝agent 的權限。
  （GitHub 對「用 fine-grained token 建新 repo」需要哪個權限時常變動，⚠️ 未實測。**建不出來就自己在網頁先開一個空的 private repo**，讓 agent 只負責 push —— 這樣 token 連 Administration 都不用給，權限更小。）
- PAT 放環境變數而不是寫進設定檔：設定檔會進 git，token 一旦 push 上 GitHub 會被自動撤銷（然後你要重新申請）。

**驗收**

```bash
cd 你的專案 && npm run dev
```

瀏覽器打開 <http://localhost:5173>（Vite 預設）要看得到畫面。**先確認 app 本來就跑得起來，再交給 agent** —— 不然等下 agent 說「測試失敗」你分不清是它寫壞的還是本來就壞的。

```bash
echo $GITHUB_PAT | cut -c1-11        # → github_pat 或 ghp_（有印出東西就好，別整串貼給別人看）
```

---

## 步驟 1：匯入專案（5 分）

**動手**

Antigravity 桌面版 → 左欄 **「+」** → **New Project** → 選你的專案資料夾 → 開好之後在對話框輸入：

```
/codesearch 輸入框的元件在哪個檔案
```

**為什麼**
- Project 定義了 **agent 能碰到的資料夾範圍**（投影片 p.98）。不在專案內的路徑它碰不到 —— 這是沙箱邊界，也是為什麼你不該把整個 `~/` 加進來。
- 一個 Project 可以加**多個**資料夾＝跨 repo 上下文。這個 Lab 只加一個。
- 先跑 `/codesearch` 是最便宜的煙霧測試：如果它搜不到你的元件，代表 index 還沒建好或你選錯資料夾，這時候派任務只會得到一堆幻覺路徑。

**驗收**

`/codesearch` 要回傳**真實存在的檔案路徑**（例如 `src/App.tsx`）。自己開檔案確認那個路徑真的在。搜不到就等 index 跑完（左下角有進度）再試。

---

## 步驟 2：建立團隊規則（12 分）

### 2a. 先看沒有規則會怎樣（3 分，這步是刻意讓你踩的）

**動手**

先**不要**放任何 rule。派一個 30 秒的小任務：

```
在 src/utils/ 新增一支 formatTime 函式，把 ISO 時間字串轉成「幾分鐘前」。
```

看它生出來的東西。

**為什麼**

不給規則，你會得到（大概率）：

```ts
// Formats an ISO timestamp into a relative time string
export function formatTime(iso) {
  const diff = Date.now() - new Date(iso).getTime();
  return Math.floor(diff / 60000) + " minutes ago";
}
```

英文註解、參數沒型別、沒跑 lint。**這不是模型笨，是你沒講**。「像帶新同事」是投影片 p.105 的原話：新同事不會自己知道你們用繁體中文註解、不會知道 `tsconfig` 的 strict 不准繞過。

而且如果你的 `tsconfig.json` 開了 `strict`，這種程式碼在 `npx tsc --noEmit` 會直接爆（下面是本機用 typescript 5 實跑的原文）：

```
src/utils/formatTime.ts:2:28 - error TS7006: Parameter 'iso' implicitly has an 'any' type.

2 export function formatTime(iso) {
                             ~~~

Found 1 error in src/utils/formatTime.ts:2
```

—— agent 卻已經回報「完成」了。**「寫完了」不等於「能用」**，這就是為什麼下一步的 rule 要把「完成」的定義寫死。

**更陰的一種**：如果 agent 寫的是 `formatTime(iso: any)`，`npx tsc --noEmit` 會**完全不叫**（實測：0 error）。TS7006 只抓「隱含 any」，你**明確**寫 `any` 就是親手把檢查器關掉。那條要靠 eslint 的 `@typescript-eslint/no-explicit-any` 才抓得到 —— 所以規則裡的「禁止 `any`」不能只靠 `tsc`，`npm run lint` 也要跑。

**驗收**

```bash
grep -rn "any" src/utils/ ; npx tsc --noEmit
```

看到英文註解、或 `any`、或 TS7006 —— 恭喜，你看到問題了。把這支檔案留著，等下對照。

### 2b. 放上規則檔（9 分）

**動手**

```bash
cd 你的專案
cp -R $COURSE/lab3/templates/. .
ls -a .agents/rules/            # → style.md
```

打開 `AGENTS.md`，把兩個地方改成你的專案實況：**「這個專案是什麼」**那一行，跟**指令表**（你的 `package.json` 裡真的有的 script）。

`.agents/rules/style.md` 的長相（樣板已寫好，重點在這幾行）：

```markdown
<!-- 啟用模式：Always On -->

## 語言與型別
- 前端一律 TypeScript，`tsconfig.json` 必須維持 `"strict": true`。
- **禁止** `any`、`@ts-ignore`、`as unknown as`。型別不會寫就先問我，不要繞過檢查器。

## 註解與命名
- 註解一律繁體中文，一行講完「為什麼這樣寫」，不要複述程式碼在做什麼。

## 流程
- 完成前**必須**跑 `npm run lint` 與 `npx tsc --noEmit`，有錯不得交付。
- 任何持久化格式（localStorage / IndexedDB key 與 schema）變更**必須**在 Implementation Plan 裡先講清楚。
```

然後叫 agent 重做 2a 那支函式：

```
重新檢視 src/utils/formatTime.ts，讓它符合 @.agents/rules/style.md。
```

**為什麼**
- **`AGENTS.md` 和 `.agents/rules/` 兩個都要**，不是二選一。優先序（p.106）：`AGENTS.md`（層級 3）> `.agents/rules/*.md`（層級 4）。`AGENTS.md` 是跨工具開放標準 —— 同一份檔案同時餵 Antigravity、`agy`、Gemini CLI；`.agents/rules/` 是 Antigravity 專案內規則。分工：**事實**（指令、架構、禁區）寫 `AGENTS.md`，**風格與流程**寫 rules。
- **啟用模式一定要標**。四種：`Always On`（永遠掛上）、`Manual`（`@` 提及才用）、`Model Decision`（模型判斷）、`Glob`（如 `*.tsx` 才生效）。不標的話這份規則什麼時候生效你自己也不知道 —— 最常見的災難是你以為 Always On，其實 agent 從來沒讀過它。
- **用「必須／禁止」，不要用「盡量」**。「盡量跑 lint」＝agent 判斷這次可以不跑。規則的價值在於**不留判斷空間**。
- **12,000 字元上限**（p.104）。超過的部分會被截斷，而且**不會有錯誤訊息** —— 你的規則後半段安靜失效。樣板是 627 字元，你有很多空間，但別把整份架構文件貼進來；細節用 `@filename` 引用出去。
- **`~/.gemini/GEMINI.md` 的坑**（p.104）：那個檔案跟 Gemini CLI 共用，兩邊規則會互相滲透。共通規則放 `~/.gemini/AGENTS.md` 比較乾淨。這個 Lab 全部寫在專案內，不動全域。

**驗收**

```bash
uv run $COURSE/lab3/check_lab3.py .
```

前 6 項要 PASS：

```
PASS  AGENTS.md 存在於專案根目錄
PASS  .agents/rules/ 有 rule 檔：style.md
PASS  style.md：627 字元（上限 12000）
PASS  style.md：有標註啟用模式（Always On / Manual / Model Decision / Glob 之一）
PASS  style.md：10 條「必須／禁止／一律／不得」（至少 3 條）
PASS  style.md：沒有模糊字眼「盡量」
```

`cp -R` 把 `mcp_config.json` 一起帶進來了，所以 MCP 那兩項（`1 個 server（github）`、`stdio 型`）現在也會 PASS，最後一行是 **`8 過 / 3 失敗`**（你的專案本來就是 git repo 又有兩個以上 commit 的話會更多 PASS）。剩下 `docs/evidence/`、`git commit`、`git remote origin` 三項 **FAIL 是正常的** —— 那是步驟 5 與 6 的事。這支腳本就是你的進度條。

再驗規則真的生效：

```bash
grep -rn "any" src/utils/formatTime.ts    # → 沒東西
npx tsc --noEmit                          # → 沒有 TS7006
head -3 src/utils/formatTime.ts           # → 註解變成繁體中文
```

同一個模型、同一個任務，差別只有一個 Markdown 檔案。

> 💡 **啊哈：決定 agent 產出品質的不是你 prompt 打多長，是你 repo 裡放了什麼**
> 2a 與 2b 你打進對話框的字幾乎一樣多，結果天差地遠。多出來的一千多個字元不在對話框裡，在檔案裡 —— 而且它每次任務都自動掛上，你一輩子不用再打第二遍。prompt 是一次性的，repo 規範是常駐的；「prompt engineering」在 agent 時代大半其實是「repo engineering」。
> **動手看**：`uv run $COURSE/lab3/check_lab3.py --aha` → 51 字元 vs 1,475 字元（**29×**）、硬性約束 **0 → 17** 條、「完成」的定義從「沒寫」變成 `npm run lint ＋ npx tsc --noEmit`。（給路徑就換算你自己的專案：`--aha .`）

---

## 步驟 3：派任務（先 `/grill-me`）（12 分）

**動手**

```
/grill-me
加上輸入歷史紀錄與收藏功能，資料存 localStorage。
遵守 @.agents/rules/style.md 與 AGENTS.md。
完成前必須用 Browser surface 實測：新增三筆、收藏一筆、重新整理後資料還在。
```

agent 會**先反問**，例如：歷史要存幾筆？重複輸入要不要去重？收藏是獨立清單還是欄位？清空歷史要不要確認對話框？多分頁同時開要不要同步？

**一題一題回答**。不知道就講「你決定，寫進 Plan」。

**為什麼**
- `/grill-me` = 反向拷問，需求模糊時用；`/goal` = 跑到完成、中途不停下來問，需求明確時用（p.97）。這個任務有至少五個沒講清楚的決策點，直接 `/goal` 的結果是它自己猜五次 —— 猜錯的成本是你要重審一份 200 行的 diff。**在 prompt 階段改需求是免費的，在 diff 階段改需求要花 credits。**
- prompt 裡明確寫 `@.agents/rules/style.md`：Always On 理論上會自動掛，但**寫出來的成本是零**，而且你會在 Plan 裡看到它引用規則，等於順手驗證了 rule 有被讀到。
- 「完成前必須用 Browser surface 實測」寫進 prompt 而不只放 `AGENTS.md`：這句話是步驟 5 有沒有錄影的關鍵。四個信任原則的第一條是「agent 被要求連驗證方法一起想」（p.91）—— 你要求，它才想。
- 先 `/effort low` `/model gemini-3.7-flash`。credits 算的是「agent 完成的工作量」不是 token，一開始就 Pro + High 是純浪費（p.85 的省配額心法）。

**驗收**

agent 至少問了 **2 個**你沒想到的問題，而且下一步交出的是 **Implementation Plan**，不是直接開始改檔案。如果它跳過反問直接動工：`/grill-me` 沒吃到，重新輸入一次。

---

## 步驟 4：審 Implementation Plan 並留言（12 分）

**動手**

讀 `implementation_plan.md`（Artifacts 面板）。**至少留一則修改留言**。示範：

> localStorage 有 5MB 上限，且是同步 API，歷史筆數多會卡 UI thread。改用 IndexedDB：db `lab2app`、store `history`（keyPath `id`）、index `createdAt`。收藏改成 `history` 的 boolean 欄位，不要開第二個 store。

然後才按 **Proceed**。執行期間看 `task.md` 的 Task List 一項一項打勾。

**為什麼**
- **Plan 是最便宜的攔截點**。這是四個信任原則裡「Trust」的具體做法（p.91）：動工前先看要改哪些檔、什麼順序、什麼風險。等它寫完 200 行才發現要換儲存層，你要付兩次 credits。
- **留言不會中斷執行**（p.91 的 Feedback）：回饋像 Google Docs 一樣被吸收。所以「先按 Proceed 再留言補充」也可以 —— 但儲存層這種結構決定要在按之前講。
- **為什麼挑 IndexedDB 這個留言**：它會連鎖影響 schema、非同步 API、錯誤處理三處。留一個「加上 loading 動畫」這種留言看不出回饋機制有沒有真的在運作。而且你的 rule 已經寫了「持久化格式變更必須在 Plan 裡講清楚」—— 這則留言同時在驗證那條規則。
- **不要留超過 3 則**。回饋越多，agent 越容易只吸收前兩則。想大改就整份重來。

**驗收**

- [ ] Plan 有更新版本（或 agent 在對話裡明確回覆「已改為 IndexedDB」）
- [ ] Task List 至少有一項是「改用 IndexedDB」相關
- [ ] 執行完成後：`grep -rn "localStorage" src/` 應該幾乎沒有殘留（有的話是它沒吃到你的留言 —— 直接回覆「Plan 已改 IndexedDB，請移除 localStorage 實作」）

留言前後的 Plan 各截一張圖，這是你「回饋被吸收」的證據。

---

## 步驟 5：看 browser 驗證（10 分）

**動手**

打開 agent 交的 `walkthrough.md`（Artifacts），找到 **Browser Recording** 那一段，**點開錄影看完**。然後把它另存進專案：

```bash
mkdir -p docs/evidence
# Artifacts 面板 → 錄影右鍵 → Download → 存成 docs/evidence/history-favorite.webm
# 截圖同樣另存 docs/evidence/
ls -la docs/evidence/
```

**為什麼**
- **這是 Antigravity 與純聊天式 coding 助手的本質差異**（p.101）：驗證是工作的一部分，不是你的事後工作。錄影是「它真的點過每個按鈕」的證據 —— 沒有錄影的「已完成」跟 ChatGPT 貼給你一段程式碼沒有差別。
- **一定要真的點開看**。你要確認的是：它有沒有真的重新整理過頁面？重整後資料真的還在嗎？很常見的情況是它測了「新增」但沒測「重整後還在」，而 persistence 正是這個任務的全部重點。
- **為什麼要另存到 `docs/evidence/`**：Artifacts 存在本機的 Antigravity 資料夾，Knowledge Items 也「目前無跨裝置同步」（p.113）。換一台機器、或你要交作業給講師時，證據要跟 repo 走。這也是 `check_lab3.py` 那一項在檢查的東西。
- **安全**：agent 的 browser 用**完全隔離的 Chrome profile**（p.102），碰不到你的登入狀態。但它讀到的網頁內容都可能是攻擊指令（PromptArmor，2025/11）—— 這個 Lab 只讓它開 `localhost`，不要叫它去讀不認識的網站。

**驗收**

```bash
uv run $COURSE/lab3/check_lab3.py .
# → PASS  docs/evidence/ 有 browser 驗證證據：history-favorite.webm
```

自己手動再測一遍（agent 說過的話要抽查）：

```bash
npm run dev
```

新增三筆 → 收藏一筆 → **⌘R 重新整理** → 三筆都在、收藏狀態還在。不在就回覆 agent：「重整後資料消失，請修並重新錄影」。

沒有錄影？回覆：「請用 Browser surface 實測上述三個情境並附上錄影」。做不到就檢查 Settings → Browser → Browser Tools 有沒有被停用、Chrome 裝了沒。

---

## 步驟 6：接一個 MCP（15 分）

### 6a. 先寫錯（3 分，這步也是刻意的）

**動手**

打開 `.agents/mcp_config.json`，**故意**改成從 Cursor 抄來的寫法：

```json
{
  "mcpServers": {
    "github": {
      "url": "https://api.githubcopilot.com/mcp/",
      "headers": { "Authorization": "Bearer ghp_R3alL00k1ngT0kenAAAA1234" }
    }
  }
}
```

存檔 → Antigravity UI 按 **refresh** → 打開 server 的工具清單看（桌面版：Settings → Customizations → Installed MCP Servers；`agy` CLI：輸入 `/mcp`，p.115）。

**為什麼／會發生什麼**

server 會出現在列表上，但**工具清單是空的** —— 而且沒有任何錯誤訊息。因為 Antigravity 的遠端欄位叫 **`serverUrl`**，不是 `url`（p.116、附錄 D 第 4 坑：「抄 Cursor 設定檔必踩」）。它看到一個既沒 `command` 也沒 `serverUrl` 的 server，就當它沒有傳輸方式。

這種「不報錯、安靜失效」的錯是最貴的：你會花 20 分鐘懷疑 PAT、懷疑網路、懷疑 GitHub 掛了。所以先跑腳本：

```bash
$ uv run check_lab3.py .
FAIL  github：欄位寫成 url —— Antigravity 只認 serverUrl（抄 Cursor 設定檔必踩）
FAIL  github.headers.Authorization：疑似明文 token，改成 $ENV_VAR 引用
```

第二條也抓到了：token 明文寫在設定檔裡，一 commit 就外洩（GitHub 掃到會自動撤銷你的 token，然後你要重新申請一次）。

**驗收**

```bash
uv run $COURSE/lab3/check_lab3.py .
```

要看到上面那兩條 FAIL（此時是 `7 過 / 5 失敗`），並且在 Installed MCP Servers（或 `agy` 的 `/mcp`）裡看到 github 的**工具清單是空的**。這就是這一步要你親眼看到的東西：設定檔語法完全合法、UI 不報錯、功能靜靜地沒有。

> 💡 **啊哈：MCP server 不是服務，是一個吃 stdin、吐 stdout 的子行程 —— 你可以用一行 pipe 當它的 client**
> 寫錯 `url` 之所以連錯誤都沒有，是因為既沒 `command` 也沒 `serverUrl` ＝ 根本沒有行程被生出來，交握從未發生，當然沒有東西可報。Antigravity 對這個 server 做的第一件事，你現在就能自己做一遍（下面是本機實跑輸出）。
> **動手看**：`echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"you","version":"0"}}}' | npx -y @modelcontextprotocol/server-github` → `GitHub MCP Server running on stdio` 之後吐出 `{"result":{"protocolVersion":"2024-11-05","capabilities":{"tools":{}},"serverInfo":{"name":"github-mcp-server","version":"0.6.2"}},"jsonrpc":"2.0","id":1}` —— 連 token 都不用給，交握不管認證。

### 6b. 修好（12 分）

**動手**

```bash
cat .agents/mcp_config.json
```

改回樣板的 stdio 寫法：

```json
{
  "mcpServers": {
    "github": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "env": { "GITHUB_PERSONAL_ACCESS_TOKEN": "$GITHUB_PAT" },
      "disabledTools": ["merge_pull_request", "create_pull_request_review", "fork_repository"]
    }
  }
}
```

```bash
uv run python -m json.tool .agents/mcp_config.json > /dev/null && echo "JSON ok"
```

> **這個 npm 套件已被標記 deprecated**（本機 `npm view` 實測：最新版 `2025.4.8`，deprecated 訊息是 `Package no longer supported.`）。它**還跑得起來**（實測：啟動印出 `GitHub MCP Server running on stdio`，`serverInfo.version` 是 `0.6.2`，26 個工具都在），所以拿來上課沒問題，只是 `npx` 會先噴一行 `npm warn deprecated` —— 那是警告不是錯誤，別被它嚇到。
> 想用官方現行版就把這個 server 改成遠端型（順便真的用到 `serverUrl`）：
> ```json
> "github": {
>   "serverUrl": "https://api.githubcopilot.com/mcp/",
>   "headers": { "Authorization": "Bearer $GITHUB_PAT" }
> }
> ```
> ⚠️ 未實測：這個遠端端點需要有效 PAT 才連得上，本機沒有帳號可驗。stdio 版是實測過會啟動的那個，所以樣板用它。

上面 `disabledTools` 的三個名字是**實測**過的真實工具名（用 stdio 協定跟 server 講 `tools/list` 撈出來的 26 個工具之一）。這個 server 實際提供的工具包含：

```
create_repository, push_files, create_or_update_file, get_file_contents,
create_branch, list_commits, search_repositories, search_code,
create_issue, update_issue, list_issues, add_issue_comment, get_issue,
create_pull_request, get_pull_request, list_pull_requests, merge_pull_request,
create_pull_request_review, get_pull_request_files, get_pull_request_status,
get_pull_request_comments, get_pull_request_reviews, update_pull_request_branch,
fork_repository, search_issues, search_users
```

建 repo＋推程式碼只需要 `create_repository` 與 `push_files`／`create_or_update_file`，其他先關掉不影響這個 Lab。

存檔 → UI 按 **refresh**（不 refresh 就不會重載）→ 在 Installed MCP Servers（或 `agy` 的 `/mcp`）確認 github 的工具列出來了 → 派任務：

```
用 github MCP 建立一個 private repo lab2-app，把目前程式碼推上去。
commit message 用 Conventional Commits：設定檔一個 chore:、功能一個 feat:。
.env 與 node_modules 不要進 repo。
```

MCP 工具第一次呼叫會跳權限確認（預設 **Ask**）—— 看清楚它要呼叫哪個工具再放行。

**為什麼**
- **stdio vs 遠端**（p.116）：`command` + `args` = 本機子行程（`npx`／`python` 都行）；`serverUrl` = 遠端 HTTP。兩個**必須有一個**。這個 Lab 用 stdio，因為 `npx` 型不用管 OAuth，錯誤也發生在本機看得到。
- **三個入口，選一個**（p.115）：MCP Store 一鍵安裝（最簡單，44+ 官方 servers 含 GitHub）／Settings UI ／直接編輯 JSON。**這個 Lab 故意讓你手寫 JSON** —— Store 裝完你不會知道它寫了什麼，而 CI 與團隊共享靠的是 `.agents/mcp_config.json` 這個檔案進 git。全域是 `~/.gemini/config/mcp_config.json`，專案層才會跟著 repo 走。
- **`$GITHUB_PAT` 而不是貼 token**：設定檔會進 git。（如果你的 Antigravity 版本不展開 `$VAR`，就把 `env` 那行刪掉、改用 shell 層的環境變數啟動 App；**絕對不要**把 token 寫回檔案。）
- **`disabledTools` 是最小權限的手段**（p.118）：同一個 server 只想用部分工具就列黑名單。樣板已經先關掉 `merge_pull_request`／`create_pull_request_review`／`fork_repository`。心法是「資料庫類 server 一律先 read-only」，GitHub 同理 —— 建 repo 需要寫入權，所以我們給，但破壞性的先關。填錯名字不會報錯（就是沒關到），所以要對照 UI 或 `/mcp` 列出的真實清單。
- **權限維持 Ask**（p.98）：要放行就精確到單一工具 `mcp(github/create_repository)`，不要 `mcp(*)`。Pillar Security 那個 RCE（2026/01）就是「工具參數也是攻擊面」的教訓。

**驗收**

```bash
uv run python -m json.tool .agents/mcp_config.json > /dev/null && echo "JSON ok"
git log --oneline          # → 至少 2 行，開頭是 chore: / feat:
git remote get-url origin  # → https://github.com/你的帳號/lab2-app.git
gh repo view --web         # 有 gh CLI 的話，直接開瀏覽器看
```

repo 頁面上要**看不到** `node_modules/` 與 `.env`。看到了就是 `.gitignore` 沒設好，回覆 agent 修。

> 💡 **啊哈：`"command": "npx"` 這一格，Lab 6 換成你自己寫的檔案，Lab 10 換成一個網址**
> 這個 Lab 你是 MCP 的**消費者**；`$COURSE/lab6/server.py` 是同一格的**提供者** —— 照 `lab6/mcp_config.sample.json` 把那格換成 `"command": "/opt/homebrew/bin/uv", "args": ["run", "--directory", "<lab6 絕對路徑>", "server.py"]` 就接上了，Antigravity 這端一個字都不用改。（uv 要寫絕對路徑、要帶 `--directory`：Antigravity 生子行程用的 PATH 與 cwd 都不是你的 shell。）
> Lab 10 把同一支檔案推上 Cloud Run，這格變成 `"serverUrl"` —— 服務是私有的，所以填 `gcloud run services proxy` 開在本機的 `http://localhost:3000/mcp`，不是 `run.app` 網址本身。這條線後面還會長：MCP tool（Lab 6）→ ADK tool（Lab 7 的 `McpToolset`）→ A2A skill（Lab 9 agent card 的 `skills`），同一個「工具」概念換三種包裝。
> **動手看**：`grep -n "MCP_TRANSPORT\|mcp = MCPServer" $COURSE/lab6/server.py` → 三行，同一支檔案既能當 stdio 子行程、也能綁 `$PORT` 當 HTTP 服務

---

## 步驟 7：驗收（8 分）

**動手**

```bash
cd 你的專案
npm run lint && npx tsc --noEmit
uv run $COURSE/lab3/check_lab3.py .
echo "exit=$?"
```

**為什麼**

投影片的驗收條件是「功能可用＋錄影存在＋GitHub repo 有完整 commits」。這三件事各自都可以「看起來有」：功能可用可能只在 agent 的機器上、錄影可能只有截圖、commits 可能只有一個 `initial commit`。腳本把三件事變成 exit code，你不用相信任何人的自我回報。

**驗收**

```
11 過 / 0 失敗
exit=0
```

（`11` 是「只有一份 rule 檔」的情況。每多一份 `.agents/rules/*.md` 就多 4 項檢查 —— 看 **`0 失敗` 與 `exit=0`**，不要背數字。）

檢查清單：

- [ ] `npm run lint` 與 `npx tsc --noEmit` 全綠
- [ ] 歷史紀錄與收藏在瀏覽器裡真的能用，**重新整理後資料還在**
- [ ] `docs/evidence/` 有 webm 或截圖，而且你真的點開看過
- [ ] Implementation Plan 的留言被吸收（`grep -rn "localStorage" src/` 幾乎沒殘留，或 Plan 有新版本）
- [ ] `grep -rn ": any" src/` 沒東西；註解是繁體中文（rule 生效的證明）
- [ ] `.agents/mcp_config.json` 用 `command`／`serverUrl`，token 是 `$GITHUB_PAT`
- [ ] GitHub 上 repo 存在、≥ 2 個 commit、message 是 `feat:`／`chore:`
- [ ] repo 裡沒有 `node_modules/`、沒有 `.env`
- [ ] `uv run check_lab3.py --self-check` 通過
- [ ] `uv run check_lab3.py .` → `11 過 / 0 失敗`

---

## 常見錯誤對照表

| 症狀 | 原因 | 解法 |
|---|---|---|
| 看得到 server 但工具清單是空的，沒有任何錯誤訊息 | 遠端欄位寫成 `url`（抄 Cursor 設定檔） | 改成 `serverUrl`；跑 `uv run check_lab3.py .` 會直接指名 |
| `mcp_config.json 不是合法 JSON：Illegal trailing comma before end of object: line 4 column 23 (char 58)` | JSON 最後一個欄位後面留了逗號 | 刪掉尾逗號；`uv run python -m json.tool .agents/mcp_config.json` 先驗 |
| `Expecting property name enclosed in double quotes: line 2 column 3 (char 4)` | 在 JSON 裡寫了 `//` 註解（投影片範例為了說明才加的） | 交付檔用嚴格 JSON，註解寫在 `AGENTS.md` |
| 改完 `mcp_config.json`，server 還是舊的／根本沒出現 | 沒按 refresh | Settings → Customizations → Installed MCP Servers → refresh，或重啟 App |
| server 有上線、工具都列得出來，但一呼叫就回 `Authentication Failed: Bad credentials`（JSON-RPC `code: -32603`） | PAT 錯／過期，或 `$GITHUB_PAT` 沒被展開（server 收到字面的 `$GITHUB_PAT` 當 token）。**這個 server 缺 token 時不會拒絕啟動**，所以「有上線」不代表認證好了 | `export GITHUB_PAT=...` 後**重開 Antigravity**（GUI App 不會繼承你之後才設的 shell 變數）；仍失敗就改用 shell 層環境變數，不要把 token 寫回檔案 |
| `npx` 噴 `npm warn deprecated @modelcontextprotocol/server-github@2025.4.8: Package no longer supported.` | 這個 npm 套件已停止維護（官方改推遠端 server） | 這是**警告不是錯誤**，server 照樣起得來（實測 `0.6.2`、26 個工具）；要換官方現行版見步驟 6b 的遠端寫法 |
| `error TS7006: Parameter 'iso' implicitly has an 'any' type.` 但 agent 說「完成」 | 沒有 rule 規定「完成前必須跑 `npx tsc --noEmit`」 | 把完成條件寫進 `.agents/rules/style.md`（步驟 2b） |
| `npm error Missing script: "lint"` | `AGENTS.md` 的指令表抄了樣板沒改，你的 `package.json` 根本沒有 `lint` | 改 `AGENTS.md` 成你真的有的 script，或 `npm i -D eslint` 加一個 |
| `npm error code EUSAGE` ＋ `The npm ci command can only install with an existing package-lock.json` | 專案沒有 lockfile（AI Studio 匯出常常沒有） | 先 `npm install` 生 lockfile，之後才能 `npm ci` |
| `fatal: your current branch 'main' does not have any commits yet` | 專案還沒有任何 commit，`check_lab3.py` 會算成 0 個 | `git init && git add -A && git commit -m "chore: 初始化"`（或請 agent 做） |
| `error: remote origin already exists.` | agent 或你已經加過 origin | `git remote set-url origin <新網址>` |
| `TypeError: crypto.randomUUID is not a function` | 用非 localhost 的 http 開頁面（`crypto.randomUUID` 只在 secure context 有） | 用 `http://localhost:5173`，不要用 `http://192.168.x.x:5173` |
| `QuotaExceededError: Failed to execute 'setItem' on 'Storage'` | localStorage 5MB 塞滿（歷史沒設上限） | 這正是步驟 4 要留言改 IndexedDB 的理由；或請 agent 加筆數上限 |
| `(eval):1: command not found: python` | macOS 只有 `python3`，沒有 `python` | 一律 `uv run check_lab3.py`。（這支腳本剛好零依賴，`python3 check_lab3.py` 也會過；但其他 Lab 的腳本有依賴，用 `python` 跑就會 `ModuleNotFoundError: No module named 'google'` —— 養成 `uv run` 的習慣，不要挑場合） |
| rule 寫了但 agent 完全不理 | 沒標啟用模式，或超過 12,000 字元被截斷（**不會報錯**） | 加 `<!-- 啟用模式：Always On -->`；`check_lab3.py` 會印實際字元數 |
| Antigravity 出現你只寫給 Gemini CLI 的規則 | `~/.gemini/GEMINI.md` 兩邊共用、互相滲透 | 共通規則搬到 `~/.gemini/AGENTS.md`，工具專屬的才留 GEMINI.md |
| 任務排隊很久或被拒 | credits 用完（五小時／週雙限額） | `/effort low` ＋ `/model gemini-3.7-flash`；等刷新 |

---

## 完整解答

本目錄（`$COURSE/lab3/`）：

| 檔案 | 用途 |
|---|---|
| `templates/AGENTS.md` | 複製到專案根目錄，改「這個專案是什麼」＋指令表 |
| `templates/.agents/rules/style.md` | 複製成專案的 `.agents/rules/style.md`，Always On，627 字元 |
| `templates/.agents/mcp_config.json` | 複製成專案的 `.agents/mcp_config.json`，GitHub stdio server |
| `check_lab3.py` | 驗收腳本，`--self-check` 不連網不花錢；`--aha` 印「有／沒有 repo 規範」的對照表 |
| `PRD.md` / `SPEC.md` | 需求與規格（含 MCP 欄位完整契約、規則優先序表） |

一行複製全部：

```bash
cp -R $COURSE/lab3/templates/. 你的專案/
```

誠實分界線：

**本機實跑過、可以照抄的**：`check_lab3.py` 的每一行 `PASS`／`FAIL` 與統計行（`7 過 / 5 失敗`、`8 過 / 3 失敗`、`11 過 / 0 失敗`）、JSON 的兩種 `JSONDecodeError` 原文、`TS7006`（typescript 5 + `strict`）、`npm error Missing script: "lint"`、`npm error code EUSAGE`、兩條 git 錯誤、`npm warn deprecated ...server-github@2025.4.8`、server 啟動訊息 `GitHub MCP Server running on stdio` 與 `initialize` 交握回應（`serverInfo.version` `0.6.2`）、`--aha` 的整張對照表（51 vs 1,475 字元、29×、0 → 17 條）、`tools/list` 撈到的 26 個工具名、以及用假 token 呼叫工具得到的 `Authentication Failed: Bad credentials`。

> ⚠️ 未實測：Antigravity 桌面版的所有 UI 操作（Project 匯入、`/codesearch`、`/grill-me`、Plan 留言、Browser surface 錄影、`/mcp` 面板、MCP refresh、`$ENV_VAR` 在 `mcp_config.json` 裡會不會被展開）、遠端 `https://api.githubcopilot.com/mcp/` 端點、GitHub repo 建立與 push、以及瀏覽器端的 `TypeError: crypto.randomUUID is not a function`／`QuotaExceededError`（那兩條是 Web API 的既知行為，不是本機重現的輸出）。本機沒安裝 Antigravity、也沒有可用的 Google／GitHub 帳號；這些步驟依投影片 p.95–122 撰寫。

---

## 想再往下玩

- **把這次流程存成 workflow**：完成後直接說「把剛剛的流程存成 workflow `/engineerize`」—— agent 會從對話歷史萃取，寫成 `.agents/workflows/engineerize.md`（p.107）。下次接手任何 repo 一個指令跑完。
- **加一個 Hook**：`PostToolUse` 每次改檔自動跑 `npm run lint`（p.112）。這樣「完成前必須跑 lint」從「規則」升級成「機制」—— 規則會被忽略，機制不會。
- **換到 CLI 走一遍**：`cd 你的專案 && agy`。同一套 rules／MCP 設定共用（p.120），`shift+tab` 切 default → accept-edits → plan。`agy -p "跑全部測試並摘要失敗原因" --output-format json` 就能塞進 CI。
- **Lab 3.5**：讓 Gemini CLI 與 Antigravity 共享同一份 `AGENTS.md` 記憶（CivicGuard）。你這個 Lab 產出的 `AGENTS.md` 就是那個 Lab 的輸入。
- **Lab 6**：把 GitHub MCP 換成你自己寫的 MCP server —— 這次你是設定檔的消費者，那次你是提供者。

---

## 這個 Lab 你真正學到的

- **agent 的品質上限寫在 repo 裡，不寫在對話框裡**：同一個模型、同一句話，差 17 條硬性約束就是兩份完全不同的程式碼；你能重複的是檔案，不是那次講得特別清楚的 prompt。
- **「寫完了」與「能用」之間隔著一段錄影**：Antigravity 把驗證搬進 agent 的工作範圍（三大 surface 的第三個），這是它和聊天式助手的分界線 —— 而你的責任從「自己測」變成「抽查它測過的證據」。
- **Plan 是這條流水線上最便宜的攔截點**：需求在 prompt 階段改是免費的，在 Plan 階段改是一則留言，在 diff 階段改是第二次 credits。
- **MCP 在 Google 生態系裡的位置，就是 `mcp_config.json` 的那一格**：這個 Lab 你填 `npx`（消費別人的 server），Lab 6 填 `uv run server.py`（自己當提供者），Lab 10 填 `serverUrl`（推上 Cloud Run）—— 同一個介面，三種身分。
- **權限是設計決策，不是設定畫面**：fine-grained PAT、`disabledTools`、`mcp(github/create_repository)` 而不是 `mcp(*)` —— 災害半徑等於你當初懶得縮的那幾格。

---

## 清理

```bash
# 1) 刪 GitHub repo
gh repo delete <你的帳號>/lab2-app --yes
# 2) 撤銷 PAT：github.com/settings/tokens → Revoke
unset GITHUB_PAT
# 3) 移除 MCP server：刪掉 .agents/mcp_config.json 的 github 區塊，UI 按 refresh
# 4) Antigravity 端：Settings → Customizations → Installed MCP Servers → 移除
```

沒有雲端資源要清（這個 Lab 完全不碰 GCP，$0）。`AGENTS.md` 與 `.agents/rules/` 建議**留著** —— 後面每個 Lab 的專案都會想抄。
