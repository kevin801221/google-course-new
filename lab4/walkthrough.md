# Lab 4 走一遍：課程知識庫 × Agent 查詢

> 45–60 分鐘 ｜ 建立本課程的 NotebookLM 知識庫，並讓 Antigravity agent 用 MCP 查詢它

做完你會有一本策展好的筆記本、一集通勤可聽的 Audio Overview，以及一個**會查你筆記的 Antigravity agent**：

```
$ uv run wiki.py check
[OK] notebooklm server：notebooklm

$ uv run wiki.py ask "ADK 部署的三種方式？"
ADK 支援三種部署路徑 [1][2]：
1. Agent Engine —— Vertex AI 託管 runtime，adk deploy agent_engine --staging_bucket=gs://...
2. Cloud Run —— 容器化 serverless，adk deploy cloud_run --service_name=... --with_ui
3. 自管容器（GKE／任何容器平台）—— 自己包 image
  來源 https://adk.dev/deploy/agent-engine
  來源 https://adk.dev/deploy/cloud-run
```

> 上面的答案內容是示意（真實回答取決於你餵了哪些來源），但**格式是真的**：`wiki.py ask` 會把答案原樣印出、把裡面的連結撈出來列在最後，而且**一個引用都沒有的話 exit 1**。

每一步都是「動手 → 為什麼 → 驗收」。驗收沒過不要往下走——這個 Lab 有兩處會**安靜地失敗**（不報錯、但什麼都沒發生），往下走只會更難查。

本 Lab **$0**、**不需要 API key**、**不需要 GCP 專案**。需要的是 Lab 3 裝好的 Antigravity。

---

## 步驟 0：前置（3 分）

```bash
# 1) Antigravity 桌面版已安裝並登入（Lab 3 的產物）
#    沒有的話：https://antigravity.google/download

# 2) 本 Lab 的目錄
cd /Users/awesomeartengineer01/Antigravity-teach/lab4

# 3) 先確認離線工具是活的
uv run wiki.py --self-check
```

**為什麼先跑 `--self-check`**：後面步驟 5 要用 `wiki.py check` 判斷你的設定檔對不對。如果檢查器本身壞了，你會拿到一個「看起來過了」的假驗收，然後花 20 分鐘查一個不存在的問題。先確認尺規是準的，再拿它量東西。

**驗收**

```
$ uv run wiki.py --self-check
self-check 全過
```

還要確認 Google 帳號能進 <https://notebook.google.com>（2026/07 起 NotebookLM 更名 Gemini Notebook，舊網址會轉址，社群還是慣稱 NotebookLM）。

---

## 步驟 1：建立筆記本「Google AI Agent 課程」（8 分）

**動手**

1. 開 <https://notebook.google.com> → **Create new** → 標題打 `Google AI Agent 課程`。
2. **Add source → Website**（貼 URL 那個選項），一次貼一個，加這四個：

```
https://ai.google.dev/gemini-api/docs
https://adk.dev
https://antigravity.google/docs
https://modelcontextprotocol.io
```

3. 貼完**不要馬上問問題**。看來源清單左側的狀態：每個來源會先跑一段抓取＋切塊＋嵌入，完成後才會出現可勾選的 checkbox 與字數／摘要。四個 URL 通常 30 秒到 2 分鐘。

**為什麼**

- **一本一主題**。你可能想把「面試準備」「公司文件」也塞進這本——不要。NotebookLM 是對整本的來源做檢索，主題混在一起會讓不相關的段落一起被撈出來，檢索品質差很多（p.178）。這本只放這門課的官方文件。
- **為什麼是這四個 URL**：這四個剛好對應本課四個會反覆查的主題（Gemini API／ADK／Antigravity／MCP 規格）。步驟 6 要問「ADK 部署的三種方式」，答案就住在 `adk.dev` 裡——來源沒進去，那題必答不出來。
- **為什麼要等 embed 完成**：這是本 Lab 第一個「安靜失敗」。來源還在處理時你就問問題，NotebookLM **不會報錯**，它會用手上已經好的來源回答，或者回「來源中找不到相關資訊」。你會以為是自己問題問得爛，實際上是資料還沒進去。
- 免費層每本 50 個來源、每天 50 次對話（p.177），四個來源用掉 8%，很夠。

**驗收**

在筆記本右上角看來源數是不是 `4`，且四個都沒有轉圈／警示圖示。然後**故意問一題來源裡不可能有的**，證明它真的只看你的來源：

```
在筆記本的對話框輸入：
  我們公司的請假流程是什麼？
```

預期回答是「根據提供的來源，找不到關於……的資訊」這類拒答，**而不是**編一套請假流程給你。這就是 source-grounded 與一般 chatbot 的本質差異——它寧可說不知道。如果它真的編了一套出來，你八成是在 Gemini App 的一般對話而不是筆記本裡。

> 💡 **啊哈：接地不是讓模型變誠實，是把它的視野關進你的四個來源裡**
> 「請假流程」模型本來就不知道，拒答不稀奇。真正的證明是問一題**它一定知道**的通識題——筆記本照樣說找不到。擋住幻覺的不是模型的良心，是檢索範圍。
> 代價也在同一句話裡：來源策展得爛，它會拒答一堆它其實答得出來的題。grounding 沒有免費的午餐。
> **動手看**：在筆記本對話框問 `Python 的 GIL 是什麼？`（⚠️ 未實測）→ 你應該會看到拒答或「來源中沒有提到……」；同一題貼進 Gemini App 一般對話則會拿到完整解釋。

---

## 步驟 2：網頁版試問三題（7 分）

**動手**

在筆記本對話框依序問這三題（第一題是投影片指定的）：

```
1. Interactions API 與 generateContent 的差異是什麼？
2. MCP 的 tools、resources、prompts 三者分別解決什麼問題？
3. Antigravity 的 mcp_config.json 遠端 server 欄位叫什麼？
```

每題答完，**點一下答案句尾的引用編號**（`[1]`、`[2]`），右側會跳到來源原文的那一段。

**為什麼**

- 這三題不是隨便問的：它們分別打在三個不同來源上（`ai.google.dev`、`modelcontextprotocol.io`、`antigravity.google/docs`）。三題都答得出來，才證明四個來源真的都進去了、都能被檢索到——比看來源數 = 4 更有力。
- **為什麼一定要點開引用**：引用編號是 NotebookLM 唯一的可信度證據。點開後如果原文跟答案講的不是同一件事，代表這個來源抓進來的內容不完整（常見於 SPA 網站只抓到骨架 HTML），這時你該改餵具體的子頁面 URL 而不是首頁。不驗這一步，你會把一本半殘的知識庫帶進 Capstone。
- 第 3 題有標準答案可以對：`serverUrl`（不是 `url`）。答錯就是 `antigravity.google/docs` 這個來源沒抓好——這題順便幫你檢查來源品質，也是步驟 5 會踩的坑。

**驗收**

- [ ] 三題都有實質回答，不是「找不到」
- [ ] 每題答案至少有一個行內引用編號
- [ ] 點開引用會跳到來源原文，內容跟答案對得上
- [ ] 第 3 題答出 `serverUrl`

任一題回「找不到」→ 回步驟 1，那個來源沒抓好。改餵更具體的子頁 URL（例如 `https://adk.dev/deploy` 而不是 `https://adk.dev`），或直接把官方文件另存 PDF 上傳。

---

## 步驟 3：生成一集 Audio Overview（5 分動手 + 背景等待）

**動手**

1. 右側 **Studio** 面板 → **Audio Overview** → 展開自訂選項（Customize）。
2. 主題／重點欄位填：`給初學者的 MCP 介紹`
3. 語言選繁體中文，長度預設即可 → **Generate**。
4. **按下去就先去做步驟 4**，不要盯著進度條。生成通常要幾分鐘。

**為什麼**

- **為什麼要自訂主題**：不填的話它會平均涵蓋全部四個來源，你會得到一集「Gemini API 加 ADK 加 Antigravity 加 MCP」的大雜燴，通勤聽完什麼都沒記住。填了主題等於給它一個 focus，它會以 MCP 為主軸、其他來源當背景。這是「同一個知識庫、不同輸出」的核心用法。
- **為什麼交錯做**：這個 Lab 的時間盒是 45–60 分鐘，其中音訊生成與來源 embed 都是純等待。按下 Generate 就切去裝 CLI，是唯一能壓進時間盒的排法。
- 免費層每天 3 個音訊（p.177）。生成失敗重試也在額度內，但不要連按。

**驗收**

回來時（步驟 5 之後）確認：

- [ ] Studio 面板出現一個音訊卡片，可以播放
- [ ] 前 30 秒聽起來在講 MCP／工具協定，不是在講 ADK 或 Gemini 模型
- [ ] （選）點卡片的下載鍵存成 m4a，這就是 Lab 4.5 內容產線要自動化的那個檔案

---

## 步驟 4：安裝並登入 notebooklm-mcp-cli（8 分）

**動手**

```bash
uv tool install notebooklm-mcp-cli
uv tool update-shell          # 把 ~/.local/bin 加進 PATH
exec $SHELL -l                # 或直接開一個新終端機，讓 PATH 生效

nlm --help                    # 先看一眼真實的子指令與旗標
nlm login                     # 會開瀏覽器，用同一個 Google 帳號登入
```

登入後**先用 CLI 驗證，不要急著接 agent**：

```bash
nlm notebook list
```

抄下「Google AI Agent 課程」那一行的 notebook id，然後：

```bash
export NLM_NOTEBOOK_ID="貼上那個 id"
cd /Users/awesomeartengineer01/Antigravity-teach/lab4
uv run wiki.py sources
uv run wiki.py ask "Interactions API 與 generateContent 的差異？"
```

> ⚠️ 未實測：`nlm` 的子指令與旗標抄自投影片 p.185，本機沒有安裝這個工具（`which nlm` → not found），無法執行驗證。跑之前先 `nlm --help` 對一次名字；`wiki.py` 呼叫的是 `nlm notebook list` / `nlm source list <id>` / `nlm query <id> "<問題>"` 這三條。

**為什麼**

- **為什麼一定要 `uv tool update-shell`**：`uv tool install` 把執行檔放在 `~/.local/bin`，這個目錄預設**不在** PATH 上。少了這步，下一句就是 `zsh: command not found: nlm`，而且錯誤訊息完全不會提到 PATH，你會以為安裝失敗又裝一次。
- **為什麼 `nlm` 和 agent 不是兩套東西**：`nlm`（人用的 CLI）和 `notebooklm-mcp`（給 agent 的 server）是同一個套件、共用同一份 session 檔。所以「`nlm query` 能跑」等於「agent 能查」——這是本 Lab 最有用的除錯槓桿：agent 查不到時，先在終端機跑 `nlm query`，就能判斷問題在 NotebookLM 那頭還是在 Antigravity 的設定。
- **為什麼 session 要小心**：`nlm login` 存下來的是**瀏覽器 cookie**，等同你的 NotebookLM 完整權限（p.188）。不要進 repo、不要在共用機器登入。效期約 2–4 週，到期重跑 `nlm login`。
- **為什麼 `wiki.py ask` 要在零引用時 exit 1**：session 過期時，`nlm` 常常是 **exit code 0 但輸出空的**——第二個「安靜失敗」。如果驗收只看 exit code，你會以為一切正常。`wiki.py` 的 `report()` 把「exit 0 + 空輸出」和「有回答但零引用」都算失敗，並直接告訴你去重跑 `nlm login`。

**驗收**

```
$ uv run wiki.py sources
（nlm 的來源清單）

掃了 5 行，未就緒 0 筆        ← 「未就緒 0 筆」是重點

$ uv run wiki.py ask "Interactions API 與 generateContent 的差異？"
（答案）
  來源 https://ai.google.dev/gemini-api/docs/...
$ echo $?
0
```

「掃了 N 行」是 `nlm source list` 的**輸出行數**，不是來源數——`nlm` 若印表頭就會比 4 多。要看的是 `未就緒 0 筆`。

`未就緒 1 筆` 以上 → 回步驟 1 等 embed。
`找不到 nlm：uv tool install ...` → PATH 沒生效，開新終端機。
`nlm 沒有輸出：session 可能過期` → 重跑 `nlm login`。

> 💡 **啊哈：`command` 型的 MCP server 不是一個服務，是被 fork 出來的子程序，它的 stdout 就是協定通道**
> 你剛剛跑的 `wiki.py` 對 `nlm` 做的事（fork 子程序、讀 stdout），跟 Antigravity 對 `notebooklm-mcp` 做的事是同一個動作；差別只在 MCP 那條 stdout 上跑的是 JSON-RPC，不是給人看的表格。
> 所以 `mcp_config.json` 的 `command` 就是 `subprocess.run` 的第一個參數（寫 `serverUrl` 的遠端 server 才不是子程序，走 HTTP）。Lab 6 你會親手寫那條 stdout 的另一端（`lab6/server.py`），並用 `lab6/probe.py` 不透過 IDE 自己 spawn 它。
> **動手看**：`grep -n 'subprocess.run' wiki.py; grep -n 'StdioServerParameters(' ../lab6/probe.py` → 兩行，同一件事：指定一個指令，把它 fork 起來讀 stdout。

---

## 步驟 5：接進 Antigravity（12 分）

### 5a. 先製造失敗：照投影片原樣貼上

投影片 p.186 那份設定是**帶 `//` 註解**的。先照抄一份，故意留註解、故意漏 `disabledTools`：

```bash
mkdir -p ~/.gemini/config
cat > /tmp/bad_mcp_config.json <<'EOF'
// ~/.gemini/config/mcp_config.json
{
  "mcpServers": {
    "notebooklm": {
      "command": "notebooklm-mcp",
      "args": [],
    }
  }
}
EOF

uv run python -m json.tool /tmp/bad_mcp_config.json
```

真實輸出（我這台實際跑出來的，一字不改）：

```
Expecting value: line 1 column 1 (char 0)
```

錯誤指向 line 1 —— 也就是那行 `//` 註解。把註解那行刪掉再跑一次（`tail -n +2 /tmp/bad_mcp_config.json > /tmp/bad2.json`），換一個錯：

```
Illegal trailing comma before end of object: line 5 column 17 (char 91)
```

（註解如果是寫在物件**中間**，訊息會變成 `Expecting property name enclosed in double quotes: line 3 column 5 (char 24)` —— 同一個原因、不同位置。）

> ⚠️ 未實測：投影片 p.186 與附錄 B 都用**帶 `//` 註解**的寫法呈現這個檔案，據此推斷 Antigravity 自己讀得動註解——但沒有實機驗證。所以本目錄的範本 `mcp_config.json` 刻意寫成**無註解的合法 JSON**（兩邊都安全），你也照這樣寫就不用管它到底容不容忍。

**為什麼要先看這兩個錯**：就算 Antigravity 讀得動註解，你**其他任何工具都不容忍**——`python -m json.tool`、`jq`、大部分 linter 都會炸在同一個地方。更討厭的是尾逗號：多一個逗號在某些解析器眼裡是整份設定檔壞掉，Antigravity 可能就一個 server 都不載入，而 UI 上只是「MCP Servers 清單空的」，不會有錯誤訊息告訴你是逗號的問題。

`wiki.py check` 兩種都吃得下（它先洗掉註解與尾逗號才 parse），所以它能在 JSON 有小瑕疵的情況下**繼續檢查更重要的規則**：

```
$ uv run wiki.py check /tmp/bad_mcp_config.json
[WARN] notebooklm: disabledTools 少了 ['notebook_delete', 'source_delete']，agent 誤操作就能刪你的筆記本
[WARN] notebooklm: PATH 上找不到 `notebooklm-mcp`，Antigravity 會連不上（跑 uv tool update-shell）
[OK] notebooklm server：notebooklm
```

（以上是我這台實際跑出來的輸出。第二個 WARN 是因為我這台沒裝 `notebooklm-mcp`；你裝好了就不會出現。）

### 5b. 修好：用本目錄的範本

```bash
cd /Users/awesomeartengineer01/Antigravity-teach/lab4
cat mcp_config.json
```

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

**`~/.gemini/config/mcp_config.json` 還不存在** → 直接複製：

```bash
cp mcp_config.json ~/.gemini/config/mcp_config.json
```

**已經有了（Lab 3 設過 filesystem 之類的）** → **不要覆蓋**，手動把 `"notebooklm"` 那個區塊加進現有的 `mcpServers` 物件裡。這個檔案是全域的，蓋掉會弄壞 Lab 3 的設定。加完跑檢查：

```bash
uv run wiki.py check
```

然後 **Antigravity → Settings → MCP Servers → Refresh**。

**為什麼**

- **為什麼要禁 delete 類**：`disabledTools` 讓 agent **看不到**這些工具，不是「叫了會被拒絕」。agent 的災害半徑等於它的權限（附錄 D ⑩）：一個誤判的 prompt、或某個來源網頁裡藏的 prompt injection，就足以讓它刪掉你累積三個月的來源。NotebookLM 沒有可靠的回收桶。這一行的成本是零，不寫的代價是不可逆的。
- **為什麼 `command` 不是 `serverUrl`**：`notebooklm-mcp` 是 stdio 型 server，Antigravity 用 `command` 把它 fork 成子程序，stdin/stdout 就是 MCP 協定通道。遠端型（Supabase、BigQuery）才用 `serverUrl`——**而且欄位名一定是 `serverUrl`，不是 `url`**。抄 Cursor 的設定檔必踩這個坑（附錄 D ④），寫成 `url` 的話 Antigravity 靜默不連線，`wiki.py check` 會直接判 ERROR。
- **為什麼一定要 Refresh**：Antigravity 是在啟動時載入 `mcp_config.json`。存完檔不 Refresh，agent 就是完全不知道有這個 server，你下 prompt 它只會說「我沒有這個工具」——而你剛剛才親手存過檔，最容易以為是設定寫錯，往檔案裡愈改愈亂。
- **`nlm setup add gemini` 也能一鍵寫入**（p.185），但它寫出來的內容你沒看過。第一次手寫一遍，你才知道之後 M6 自建 server、M7 接 ADK 時每個欄位在幹什麼。

**驗收**

```
$ uv run wiki.py check
[OK] notebooklm server：notebooklm
$ echo $?
0
```

- [ ] 沒有 `[ERROR]` 任何一行
- [ ] 沒有 `[WARN] disabledTools 少了 ...`
- [ ] Antigravity Settings → MCP Servers 裡 `notebooklm` 是已連線（綠點／Connected）
- [ ] 展開它的工具清單，找得到 `notebook_query`、`source_add`，**找不到** `notebook_delete`、`source_delete`

工具清單是空的或紅點 → 看下面的常見錯誤表；並回終端機跑 `uv run wiki.py notebooks`，用它區分「NotebookLM 那頭有問題」還是「Antigravity 的設定有問題」。

> 💡 **啊哈：`disabledTools` 是客戶端的自律，不是伺服器的權限**
> 那兩個 delete 工具在 server 端還在、你的 cookie 權限也還在。攔住它的只是你筆電上一個 JSON 檔裡的兩個字串——換一個 MCP client、或你自己在終端機跑 `nlm`，照樣刪得掉。
> 它的價值是把誤觸機率壓到零，不是築牆。真正的權限邊界在別的層：Lab 5 的 IAM、Lab 6 你自己寫的 server 裡那個 `if`。
> **動手看**：`uv run python -c "import json,pathlib as p;c=json.loads(p.Path('mcp_config.json').read_text());c['mcpServers']['notebooklm'].pop('disabledTools');p.Path('/tmp/loose.json').write_text(json.dumps(c))" && uv run wiki.py check /tmp/loose.json; echo "exit=$?"` → 兩行 `[WARN]`、一行 `[OK]`、`exit=0`。沒有任何東西攔你。

---

## 步驟 6：整合驗證（8 分）

**動手**

在 Antigravity 開一個 agent 對話，貼投影片指定的 prompt：

```
查課程知識庫，總結 ADK 部署的三種方式，附引用
```

先看它有沒有真的呼叫工具：agent 面板應該顯示一次 `notebooklm` 的工具呼叫（`notebook_list` 之後 `notebook_query`）。然後跑同一題的非互動式驗收：

```bash
uv run wiki.py ask "ADK 部署的三種方式？"
echo $?
```

**為什麼**

- **為什麼 prompt 要寫「查課程知識庫」**：不指名，agent 會直接用自己的訓練知識回答——它「知道」ADK 大概怎麼部署，答案看起來很合理，但沒有引用、也不保證是 2026 年的寫法（很可能給你 2025 年的 `MCPToolset.from_server()` 這種已改名的 API，附錄 C）。指名知識庫才會觸發工具呼叫。要更穩就寫「用 notebooklm 工具」（投影片 p.186 的測試 prompt 就是這樣寫的）。
- **為什麼要求「附引用」**：引用是你唯一能分辨「它查了」和「它編了」的方法。沒有引用的答案，跟沒接 MCP 之前的 agent 沒有差別——那你這 45 分鐘就白做了。
- **為什麼還要跑 `wiki.py ask`**：agent 的回答是 LLM 產出的，同一個 prompt 兩次結果不一樣，不能當自動化驗收。`wiki.py ask` 走的是同一條 `nlm` → NotebookLM 路徑，但輸出是決定性的、有 exit code，可以塞進 CI 或每週回歸（p.466 的「程式碼驗證」建議）。兩者一起看：agent 沒引用但 `wiki.py ask` 有 → 問題在 prompt；兩邊都沒有 → 問題在知識庫或 session。
- **`notebook_query` 就是你的 RAG API**（p.187）。切塊、嵌入、檢索、引用全由 NotebookLM 代勞——這是「不用自己架向量庫的 RAG」。自建版（pgvector）是 M8 的事，到時候你會很感謝這個 Lab 的對照組。

**驗收**

- [ ] agent 面板顯示有呼叫 `notebooklm` 的工具
- [ ] 回答列出三種部署方式（Agent Engine／Cloud Run／自管容器），且每項附連結
- [ ] 連結點得開，且內容跟答案對得上
- [ ] `uv run wiki.py ask "ADK 部署的三種方式？"` → `echo $?` 是 `0`

進階驗收（證明它真的在讀你的來源，不是在背訓練資料）——問一題 2026 年才有的細節：

```
在 Antigravity：查課程知識庫，Antigravity 的 mcp_config.json 遠端 server 欄位叫什麼？要附引用。
```

答 `serverUrl` 且附 `antigravity.google/docs` 的連結才算過。答 `url` = 它在憑印象講話，來源沒讀到。

> 💡 **啊哈：Lab 1 的 `google_search`、這裡的 NotebookLM、Lab 8 的 pgvector，是同一件事的三種基礎設施**
> 三者都在回答「答案要有出處」，差別只在**誰策展來源、誰做切塊嵌入、誰做檢索**。你交出去的控制權越多，要維護的行數越少：1 行 → 9 行 → 180 行以上。
> NotebookLM 這一格的座標是：來源你選、檢索別人做、上游改版會整條斷。Lab 8 你會把最後一格自己蓋一次，蓋完才有資格判斷什麼時候該自建。
> **動手看**：`uv run wiki.py aha` → 三欄並排表，倒數第二行 `行數倍數 1 → 9（9×）→ 183（183×）`（行數是現場數 repo 檔案算的，會隨教材演進微調）。

---

## 步驟 7：加分題 —— 跨筆記本查詢（8 分，選做）

**動手**

再建一本，主題**完全不同**（這是重點）：

1. notebook.google.com → Create new → 標題 `我的舊筆記／部落格`
2. 餵你自己的東西：部落格 RSS 或幾篇文章 URL、會議記錄 PDF、YouTube 教學連結（NotebookLM 會自動抓字幕，p.174）。
3. 回終端機：

```bash
nlm notebook list                       # 抄第二本的 id
uv run wiki.py ask --nb <第二本的 id> "我對 agent 架構的看法有哪些前後矛盾的地方？"
```

不改環境變數也能查另一本——`--nb` 會蓋掉 `NLM_NOTEBOOK_ID`。

**為什麼**

- **為什麼一定要開新的一本，不要塞進課程那本**：這就是「一本一主題」的實驗。把你的部落格塞進課程筆記本，之後問「ADK 部署」時，你三年前寫的雜文段落會跟官方文件一起被撈進檢索結果，答案品質直接崩。開兩本、查詢時選一本，是 NotebookLM 唯一的「命名空間」機制。
- **為什麼這題問「前後矛盾」**：策展知識庫最有價值的用法不是「幫我找資料」（Google 就會了），是「對照我自己過去的說法」。這種問題只有你的私有來源答得出來。
- 免費層 100 本（p.177），開第二本不用擔心額度。

**驗收**

- [ ] `nlm notebook list` 列出兩本
- [ ] `--nb` 查第二本，答案引用的是你自己的文章，**不是** adk.dev
- [ ] 不加 `--nb` 時查的還是課程那本（環境變數沒被弄壞）

---

## 步驟 8：驗收清單

```bash
cd /Users/awesomeartengineer01/Antigravity-teach/lab4
uv run wiki.py --self-check
uv run wiki.py check
uv run wiki.py sources
uv run wiki.py ask "ADK 部署的三種方式？"; echo "exit=$?"
```

- [ ] 筆記本「Google AI Agent 課程」有 4 個來源，`sources` 顯示 `未就緒 0 筆`
- [ ] 網頁版三題都有實質回答＋行內引用，引用點開對得上原文
- [ ] 問來源外的問題時它回「找不到」而不是瞎編
- [ ] Audio Overview 生成完成，主題是 MCP，可播放
- [ ] `nlm notebook list` 列得出筆記本
- [ ] `uv run wiki.py check` exit 0，且沒有 `disabledTools 少了` 的 WARN
- [ ] Antigravity 的 MCP Servers 裡 notebooklm 已連線，工具清單**看不到** delete 類
- [ ] agent 用「查課程知識庫，總結 ADK 部署的三種方式，附引用」答得出三種方式＋連結
- [ ] `uv run wiki.py ask "ADK 部署的三種方式？"` exit 0
- [ ] `uv run wiki.py --self-check` 印出 `self-check 全過`

---

## 常見錯誤對照表

| 症狀 | 原因 | 解法 |
|---|---|---|
| `zsh: command not found: nlm` | `uv tool install` 把執行檔放在 `~/.local/bin`，這個目錄不在 PATH 上 | `uv tool update-shell` 然後**開新終端機**（`exec $SHELL -l`） |
| 裝好也 `update-shell` 了，`wiki.py check` 還是 `[WARN] PATH 上找不到 notebooklm-mcp` | 這個套件實際裝出來的執行檔名可能不叫 `notebooklm-mcp` | `uv tool list` 看它到底裝了哪幾個執行檔，把 `mcp_config.json` 的 `command` 改成那個名字（`which <名字>` 確認） |
| `Expecting value: line 1 column 1 (char 0)` 或 `Expecting property name enclosed in double quotes: line 3 column 5 (char 24)` | `mcp_config.json` 裡有 `//` 註解，`json.loads` / `json.tool` / `jq` 都不吃 | 用工具檢查時先把註解拿掉（`wiki.py check` 會自己洗掉），或直接抄本目錄無註解的範本（Antigravity 是否容忍註解未實測）|
| `Illegal trailing comma before end of object: line 5 column 17 (char 91)` | 抄設定檔時最後一個欄位後面多一個逗號 | 刪掉那個逗號。這個錯可能讓 Antigravity 整份設定不載入，而 UI 只是「清單空的」 |
| Antigravity 說「我沒有 notebooklm 這個工具」，但檔案明明存好了 | 存檔後沒按 Refresh；Antigravity 只在載入時讀設定 | Settings → MCP Servers → **Refresh**。還是不行就重開 Antigravity |
| MCP Servers 清單裡遠端 server 永遠連不上，沒有錯誤訊息 | 欄位寫成 `url`（抄 Cursor 設定必踩，附錄 D ④） | 改成 `serverUrl`。`uv run wiki.py check` 會把這條判成 `[ERROR]` |
| `nlm 沒有輸出：session 可能過期，重跑 nlm login`（`nlm` exit code 是 0！） | cookie session 效期約 2–4 週，過期後是**安靜失敗**：不報錯、只是回空的 | `nlm login` 重新登入。這就是為什麼驗收不能只看 exit code |
| 回答是「根據提供的來源，找不到相關資訊」，但那份文件明明加進去了 | 來源還在 embed，或 SPA 網站只抓到骨架 HTML | `uv run wiki.py sources` 看 `未就緒` 筆數；抓不完整就改餵具體子頁 URL 或上傳 PDF |
| agent 答得出 ADK 部署方式但**完全沒有引用** | prompt 沒指名知識庫，agent 直接用訓練知識回答（很可能是 2025 年的舊 API） | prompt 明確寫「查課程知識庫」「用 notebooklm 工具」「附引用」 |
| `找不到 nlm：uv tool install notebooklm-mcp-cli && uv tool update-shell`（`wiki.py` 自己印的） | `wiki.py` 先用 `shutil.which` 檢查，不讓 subprocess 丟裸的 `FileNotFoundError` | 照訊息裝＋update-shell |
| `沒有筆記本 ID：export NLM_NOTEBOOK_ID=<id>` | 忘了 export，或換了新終端機（export 不跨 session） | `uv run wiki.py notebooks` 查 id 再 export；想長期留著寫進 `~/.zshrc` |
| `zsh: command not found: python`（我這台實測：`(eval):1: command not found: python`） | macOS 沒有叫 `python` 的執行檔 | 本課一律 `uv run wiki.py`。**其他 lab 用 `python xxx.py` 還會多一個 `ModuleNotFoundError: No module named 'google'`**——`uv run` 才會用到 `pyproject.toml` 裝好的環境 |
| 某天筆記本被刪了／來源少了一半 | `disabledTools` 沒設，agent 呼叫了 `notebook_delete` / `source_delete` | 事後救不回來。**現在**就把兩個 delete 工具寫進 `disabledTools` |
| 昨天還好，今天所有 MCP 查詢都失敗 | 走的是非官方 API（cookie 模擬內部端點），NotebookLM 改版就會斷（p.188） | 更新 `notebooklm-mcp-cli`；長期要穩就走 Enterprise 官方 API＋自建 MCP（M6） |

---

## 完整解答

- `wiki.py`（同目錄）—— 設定檔檢查器＋非互動式驗收查詢，純標準庫，含 `--self-check`。
- `mcp_config.json`（同目錄）—— 步驟 5 的最小設定範本，已含 `disabledTools`。
- `SPEC.md` §3 有 MCP 工具清單與 `nlm` 指令的完整契約；§8 是錯誤處理對照表的技術版。

離線就能跑的部分（下面是我這台實際跑出來的完整輸出）：

```
$ uv run wiki.py --self-check
self-check 全過

$ uv run wiki.py check mcp_config.json
[WARN] notebooklm: PATH 上找不到 `notebooklm-mcp`，Antigravity 會連不上（跑 uv tool update-shell）
[OK] notebooklm server：notebooklm

$ uv run python -m json.tool mcp_config.json
（原樣印出格式化過的 JSON，沒有錯誤）
```

那個 `[WARN]` 是因為我這台沒裝 `notebooklm-mcp-cli`；你裝好並 `uv tool update-shell` 之後就只剩 `[OK]` 那一行。

> ⚠️ 未實測：`nlm` 相關的所有指令（`login` / `notebook list` / `source list` / `query`）與 MCP 工具的參數 schema。理由：本機沒安裝 `notebooklm-mcp-cli`，且安裝後仍需真實 Google 帳號登入才能執行。這些簽章抄自投影片 p.185–p.187。

---

## 想再往下玩

- **Lab 4.5（NotebookLM 自動內容產線）**：同一本筆記本加上 `research_start` 掃新文章、`studio_create` 生音訊、`download_artifact` 下載，串成「AI 日報電台」自動發到 YouTube。你這個 Lab 手動點的 Audio Overview，那邊全部變成腳本。
- **M7 / Lab 7（ADK）**：換一個消費端——ADK agent 用 `McpToolset(connection_params=...)` 接同一個 server（**不是** 2025 年的 `MCPToolset.from_server()`，附錄 C）。同一個知識庫、三種消費者（Antigravity／ADK agent／你自己），這就是 p.190 的 LLM Wiki 架構。
- **M8 / Lab 8（自建 RAG）**：用 pgvector 自己做一次切塊＋嵌入＋檢索，然後跟 `notebook_query` 比：品質、延遲、你花的時間。做過這個對照，你才知道什麼時候該自建、什麼時候該用託管。
- **每週維運循環（p.191）**：好文章隨手 `source_add`、通勤聽 Audio Overview、工作遇到問題先查 wiki、新決策寫成文件入庫、每月移除過期來源。30 分鐘／週，換一個永遠答得出「我們當初為什麼這樣設計」的系統。
- **Code review 顧問（p.192）**：另建一本「API 設計規範」筆記本，然後在 Antigravity 下「根據 API 設計規範筆記本，審查這個 PR 的 endpoint 命名，引用具體條文」。

**這本筆記本不要刪** —— M11 Capstone 的「個人 LLM Wiki」直接沿用它當 wiki 後端，Capstone 的 research agent 每週會往裡面加來源。現在策展得好，兩個月後省你一天。

---

## 這個 Lab 你真正學到的

- **grounding 在 Google 生態系裡有三種基礎設施**，NotebookLM 是中間那格：來源你策展、檢索託管給別人、代價是上游改版會整條斷（`uv run wiki.py aha` 一眼看完三格）。
- **「不編造」不是模型的美德，是檢索範圍的結果**——所以知識庫的品質上限，就是你餵進去那幾個 URL 的品質上限。
- **MCP server 只是一個子程序**，`command` 那個欄位等同 `subprocess.run` 的第一個參數；Lab 6 之後你會發現自己寫一個 server 沒什麼神祕的。
- **agent 的災害半徑 = 它的工具清單**，而 `disabledTools` 只是客戶端自律；要真的擋，得往 IAM 或自己寫的 server 那層走。
- **同一個知識庫可以有很多消費端**（你自己、Antigravity、之後的 ADK agent、Capstone 的 research agent）——策展一次的投資，會在後面每個模組被領走一次。

---

## 清理

本 Lab **沒有任何雲端資源要清**（沒部署服務、沒開 GCP 資源、$0）。要清的是本機憑證與設定：

```bash
# 撤掉本機 session（cookie 等同你的 NotebookLM 帳號權限）
nlm logout

# 不想留這個工具
uv tool uninstall notebooklm-mcp-cli

# 確認沒有殘留的 session 檔（路徑依版本而異，先看再刪）
ls -la ~/.notebooklm* ~/.config/nlm 2>/dev/null

# 從 Antigravity 移掉這個 server
#   編輯 ~/.gemini/config/mcp_config.json，刪掉 "notebooklm" 區塊
#   → Settings → MCP Servers → Refresh
```

**筆記本本身建議保留**（Lab 4.5、M7、Capstone 都會用）。真的要刪：notebook.google.com 的筆記本清單 → 三點選單 → Delete。**注意 `disabledTools` 擋的是 agent，不擋你自己在網頁上刪。**
