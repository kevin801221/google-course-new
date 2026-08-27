# Lab 6 PRD：自建 MCP Server 接進 Antigravity

## 1. 這個 Lab 要解決什麼問題

M1 學了 function calling，但那是「一個應用內」的機制：同一組工具要給 Antigravity 用、給 Claude Code 用、給 M7 的 ADK agent 用，就得各寫一遍（N×M 問題）。這個 Lab 讓學生把工具寫成一台 MCP server —— 寫一次、任何 host 都能接 —— 並完整走一遍 server 的開發循環：**寫 → Inspector 測 → 接 host → 讓 agent 真的用 → 用 host 端權限把它關掉**。這台 server 是後面 Lab 7（ADK 用 McpToolset 吃它）與 Lab 10（換成 streamable-http 部署上 Cloud Run）的共用素材，所以骨架就照能沿用的樣子寫。

## 2. 學習目標

做完學生會：

1. **寫得出** 一台含 tool×2 + resource×1 + prompt×1 的 MCP server，並用 `probe.py --aha` 指出模型收到的 description 逐字就是自己的 docstring、JSON Schema 一個字都沒手寫。
2. **用 Inspector 與 client 腳本除錯**，把「server 壞了」和「host 設定錯了」分開判斷。
3. **接進 host**（Antigravity `mcp_config.json` 的 stdio 形式），並驗證工具真的出現在 agent 的工具清單裡。
4. **設計出模型看得懂的工具**：description 寫「何時該用我」、錯誤用 `ToolError` 回報可修正的訊息、參數先驗證再連網。
5. **用 client 端權限收斂攻擊面**（host 的 `disabledTools`＝Lab 7 ADK 的 `tool_filter`），並說出 MCP 的四種威脅為什麼不能靠 prompt 防。
6. **切換 transport**：同一份程式從 stdio 換成 streamable-http（`0.0.0.0:$PORT`），並說出 Lab 10 把這台 server 丟上 Cloud Run 時唯一改的是 `MCP_TRANSPORT=http` 一行環境變數。

## 3. 使用者故事

- 身為學生，我想把「匯率換算」「查天氣」「查課程名詞」變成 agent 能自己呼叫的工具，以便不用每次手動貼資料給它。
- 身為學生，我想在接 host 之前就能確認 server 是好的，以便出錯時知道要修程式還是修設定。
- 身為學生，我想看到 agent 自己串兩個工具完成一句話的任務，以便理解 MCP 工具最終是怎麼進到模型的 function calling 清單。
- 身為學生，我想知道怎麼把危險工具關掉，以便日後接別人寫的 server 時不必整台信任。
- 身為（未來的）我，我想這台 server 不用改邏輯就能改成遠端服務，以便 Lab 10 直接丟上 Cloud Run。

## 4. 功能需求

| 編號 | 需求 | 對應投影片步驟 | 必要／加分 |
|---|---|---|---|
| FR-1 | 選一個自己真實會用的題目：tool×2 + resource×1 | p275 步驟 1 | 必要 |
| FR-2 | `server.py`：`convert_currency`（純運算）與 `get_weather`（呼叫外部 API）兩個工具，每個都有完整型別註記與 docstring | p275 步驟 2 / p258 / p263 | 必要 |
| FR-3 | `course://glossary/{term}` resource（URI 模板帶參數） | p275 步驟 2 / p258 | 必要 |
| FR-4 | `daily_briefing` prompt（會出現在 host 的 slash 選單，引導模型串兩個工具） | p258 | 加分 |
| FR-5 | 參數防呆＋錯誤訊息用 `ToolError`，讓模型知道「怎麼修」 | p262 原則 ③④ | 必要 |
| FR-6 | `uv run mcp dev server.py` 用 Inspector 手動測過三個能力 | p275 步驟 3 / p261 | 必要 |
| FR-7 | 以 stdio 掛進 Antigravity `~/.gemini/config/mcp_config.json`，Refresh 後工具出現 | p275 步驟 4 / p267 / p460 | 必要 |
| FR-8 | 實戰 prompt：「查台北現在天氣，順便把 100 美元換算成台幣」→ 觀察 agent 串兩個工具 | p275 步驟 5 | 必要 |
| FR-9 | 安全演練：把一個工具放進 `disabledTools`，觀察 agent 呼叫失敗的行為 | p275 步驟 6 / p271 | 必要 |
| FR-10 | 切成 streamable-http 跑 localhost:8080，用 `serverUrl` 重接一次 | p275 步驟 7 | 加分 |
| FR-11 | `server.py --self-check`：不連網、不起 server，直接驗工具函式回傳與防呆 | 本課規範 | 必要 |
| FR-12 | `probe.py`：用 MCP client 走真 stdio 驗 tools/resources/prompts（不需瀏覽器、不需 host） | 本課規範 | 必要 |

## 5. 非功能需求

| 項目 | 要求 |
|---|---|
| 時間盒 | 60–90 分（p275／p464）。步驟 1–5 是 60 分主線，6–7 是剩下 30 分 |
| 費用 | **全程免費**（p464 標示「免費」）。天氣用 open-meteo 免費 API，不需 key、不需 GCP |
| 離線可測 | `--self-check` 完全不連網；`probe.py --offline` 只跳過天氣工具，其餘走真 stdio 協定 |
| 跨平台 | macOS／Linux 指令為主；Windows 用 WSL2（p10）。`command` 路徑要用絕對路徑，因為 host 的 PATH 跟你的 shell 不一樣 |
| 相依 | 只有 `mcp[cli]`。天氣工具用 stdlib `urllib`，不加 `httpx` |
| 工具鏈 | 一律 `uv`（`uv init --bare` → `uv add` → `uv run`），不用 pip／venv |

## 6. 驗收標準

- [ ] `uv run server.py --self-check` 印出 `self-check OK`
- [ ] `uv run probe.py` 最後一行印出 `probe OK`，且列出 `tools: ['convert_currency', 'get_weather']`
- [ ] `uv run mcp dev server.py` 開得起來，Inspector 的 Tools／Resources／Prompts 三頁各手動測過一次（Tools 頁看得到參數 schema 是 `number` 不是 `string`）
- [ ] 兩個工具的 description 在 Inspector 裡看得到內容（空的＝docstring 忘了寫）
- [ ] Antigravity Refresh 後 `course-tools` 底下兩個工具出現在工具清單
- [ ] 對 agent 說「查台北現在天氣，順便把 100 美元換算成台幣」，它**呼叫兩個工具**並回一個合起來的答案
- [ ] 故意傳 `amount=-5`，agent／Inspector 看到的是 `amount 必須 >= 0，收到的是 -5.0`（不是無說明的 crash）
- [ ] `disabledTools: ["get_weather"]` ＋ Refresh 後，agent 拿不到那個工具，並且會改用別的方法或說做不到
- [ ] （加分）`MCP_TRANSPORT=http PORT=8080 uv run server.py` 起得來，`curl -X POST http://127.0.0.1:8080/mcp` 的 `tools/list` 回得出兩個工具；改用 `serverUrl` 重接 host 也看得到工具

## 7. 範圍外

- 不做認證／OAuth（2025-03-26 起規格有 OAuth 2.1，但本機 stdio 用不到；遠端授權留給 Lab 10）
- 不做 Tasks／MCP Apps／elicitation 等 extension（p254 提到，但不是本 Lab 驗收項）
- 不寫入任何資料：本 Lab 兩個工具都是唯讀，寫入類工具的權限設計是 p262 原則 ⑤ 的討論題
- 不接 Google managed servers（BigQuery 等）—— 那是 M8／M10 的事
- 不自己實作 JSON-RPC：協定層一律交給 SDK
- 不用 pytest／不做 CI：一支 `--self-check` ＋一支 `probe.py` 就夠

## 8. 費用與風險

| 項目 | 費用 | 要清什麼 |
|---|---|---|
| MCP SDK、Inspector | 免費（本機） | 無 |
| open-meteo 天氣 API | 免費、不需 key（非商用額度） | 無 |
| Antigravity | 免費層可完成（p12） | 無 |
| 雲端資源 | **本 Lab 不建立任何雲端資源** | 無需清理 |

風險：

- **stdout 污染**：stdio 模式下 stdout 是協定通道（p260／p462 坑⑤）。實測 mcp 2.1.1 服務期間會把 fd 1 轉去 stderr、fd 0 轉去 `/dev/null` 幫你擋一手（1.x 沒有），但緩衝內容仍會在行程收尾時上線 —— log 一律 `file=sys.stderr`。細節見 walkthrough 步驟 3c。
- **裝來路不明的 server 等於裝木馬**（p270 tool poisoning）。本 Lab 只跑自己寫的程式碼；示範 `disabledTools` 是為了讓學生知道 host 端有煞車。
- **殘留行程**：`mcp dev` 會另外起 node 的 Inspector（6274／6275 埠）。Ctrl-C 沒收乾淨就 `pkill -f modelcontextprotocol/inspector`。
- **本機服務對外開放**：加分題用 `host="0.0.0.0"` 是為了 Cloud Run 慣例；在咖啡廳的 Wi-Fi 上跑，同網段的人連得到你的工具。做完就關。

## 9. 前置依賴

| 依賴 | 從哪來 | 沒有的話 |
|---|---|---|
| `uv` | p11 的安裝指令 | 整個課程的指令都跑不了 |
| Python 3.13 | `uv` 會自己抓 | — |
| Node.js ≥ 20（`npx`） | p10 | `uv run mcp dev` 起不來 Inspector（`mcp dev` 是用 npx 跑 node 版 Inspector） |
| Antigravity 桌面版 | M3（Lab 3 已裝） | 步驟 4–6 沒 host 可接；可退用 Claude Code／Cursor（設定欄位名不同，見 walkthrough 對照表） |
| Google API key／GCP 帳號 | **不需要** | — |

> 本 Lab 不需要 Gemini API key，也不需要綁卡。p465 FAQ 明說沒信用卡也能完整做完 M6。
