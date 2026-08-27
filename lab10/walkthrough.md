# Lab 10 走一遍：整套系統上雲

> 120–150 分鐘 ｜ 把 M6-M9 的所有元件部署成真正的雲端 multi-agent 系統

做完你會有四個網址，其中三個沒有授權的人打不進去，而第四個網址上的網頁問一句話會跨越另外三個服務：

```
$ ./verify.sh
結果   HTTP  檢查項
----------------------------------------------------------
PASS   403   mcp 未授權（應被擋）
PASS   406   mcp 帶 ID token
PASS   403   toolbox 未授權（應被擋）
PASS   200   toolbox 帶 ID token
PASS   200   a2a 名片公開可讀
PASS   403   agent 未授權（應被擋）
PASS   200   agent 帶 ID token
PASS   -     a2a 名片含 name 欄位
PASS   -     mcp-tools 有綁 agent-sa 的 run.invoker
PASS   -     toolbox 有綁 agent-sa 的 run.invoker
PASS   -     secret session-db-url 存在
PASS   -     secret db-password 存在
----------------------------------------------------------
PASS=12  FAIL=0
```

> ⚠️ 未實測：上面這段是照 `verify.sh` 的輸出格式寫的示範，我沒有 GCP 帳號，沒辦法貼真實執行結果。`--self-check` 那條是實測通過的。

每一步都是「動手 → 為什麼 → 驗收」。這個 Lab 每一步都會花錢（雖然很少），驗收沒過**不要**往下走 —— 後面四個服務串起來之後，debug 難度是現在的四倍。

**這個 Lab 的一句話心法**：Cloud Run 的部署不難，難的是認證。403 是「你這個身分不能進來」，401 是「你的 token 不是給我的」。全程只要記住這兩句，你就不會卡超過五分鐘。

---

## 步驟 0：前置（10 分）

**動手**

```bash
cd lab10

# 1) 前面三個 Lab 的產物要在（路徑不對就改 config.sh 的 LAB6_DIR / LAB8_DIR / LAB9_DIR）
ls ../lab6/server.py ../lab8/tools.yaml ../lab9/hotel_service/agent.py

# 2) GCP 環境（Lab 5 做過）
export GOOGLE_CLOUD_PROJECT=<你的專案 ID>
export GOOGLE_CLOUD_LOCATION=us-central1
gcloud config set project $GOOGLE_CLOUD_PROJECT
gcloud auth list                     # 要看到你的帳號有 *

# 3) Supabase 的兩個機密（Lab 8 的 Dashboard -> Connect -> Session pooler）
export DB_PASSWORD='你的 Supabase 資料庫密碼'
export SESSION_DB_URL='postgresql+asyncpg://postgres.<ref>:<密碼>@aws-0-ap-northeast-1.pooler.supabase.com:5432/postgres'

# 4) 這個 Lab 的依賴
uv sync

# 5) 先跑離線檢查（不連網、不花錢）
./verify.sh --self-check
uv run --no-project concierge/auth.py --self-check

# 6) 讀一遍要跑什麼 —— 這一步不要跳
./deploy.sh --dry-run | less
```

**為什麼**

- **為什麼先 `--dry-run`**：這個 Lab 的每一條 `gcloud` 都會建立會計費的東西。`--dry-run` 把 30 幾條指令原樣印出來但一條都不執行，你可以先看清楚「它要用哪個專案、建哪些名字、開不開公開存取」。不看就按 Enter 的人，通常是在別人的專案裡建了四個服務才發現的那種。
- **為什麼 `SESSION_DB_URL` 要 `+asyncpg`**：ADK 的 session service 走 SQLAlchemy 的 async 引擎。寫成 `postgresql://` 會噴 `sqlalchemy.exc.InvalidRequestError: The asyncio extension requires an async driver to be used.` —— 而且是在**容器啟動時**才噴，你要去翻 Cloud Logging 才看得到（附錄 D ②）。
- **為什麼是 5432 不是 6543**：Supabase 的 transaction pooler（6543）跟 asyncpg 的 prepared statement 會衝突，症狀是「連得上，但查詢隨機失敗」—— 這是最難 debug 的一類 bug（附錄 D ③）。用 Session pooler（5432）。
- **為什麼機密走 `export` 而不是寫檔**：這兩個值馬上會被送進 Secret Manager，之後就不需要它們了。寫進 `.env` 的東西遲早會被 `git add .` 掃進去。

**驗收**

```bash
./verify.sh --self-check
# → self-check ok

uv run --no-project concierge/auth.py --self-check
# → self-check ok

echo "${SESSION_DB_URL%%:*}"       # → postgresql+asyncpg  （不是 postgresql）
gcloud config get-value project    # → 你的專案 ID，不是 (unset)
```

---

## 步驟 1：① MCP server 上雲（20 分）

Lab 6 的工具 server → Cloud Run（私有）＋ proxy 驗證。

**動手**

```bash
./deploy.sh apis sa secrets      # 一次性前置：啟 API、建 SA、放機密
./deploy.sh mcp                  # 建 image + 部署（3-5 分，Cloud Build 在跑）
```

`deploy.sh` 做的事就是這幾行（`--dry-run` 看得到）：

```bash
cp -R ../lab6 .build/mcp
cp dockerfiles/mcp.Dockerfile .build/mcp/Dockerfile
rm -rf .build/mcp/.venv
gcloud run deploy mcp-tools --source .build/mcp \
  --region us-central1 --no-allow-unauthenticated \
  --service-account agent-sa@$GOOGLE_CLOUD_PROJECT.iam.gserviceaccount.com \
  --max-instances 3
```

部署完先**故意做錯**：不帶任何認證直接打它。

```bash
MCP_URL=$(gcloud run services describe mcp-tools --region us-central1 --format 'value(status.url)')
curl -i $MCP_URL/mcp
```

你會拿到這個：

```
HTTP/2 403
content-type: text/html; charset=UTF-8
...
<html><head>
<meta http-equiv="content-type" content="text/html;charset=utf-8">
<title>403 Forbidden</title>
</head>
<body text=#000000 bgcolor=#ffffff>
<h1>Error: Forbidden</h1>
<h2>Your client does not have permission to get URL <code>/mcp</code> from this server.</h2>
</body></html>
```

**這個 403 是成功，不是失敗。** 現在用兩種合法方式進去：

```bash
# 方式 1：本機 proxy（開發者日常用這個）
gcloud run services proxy mcp-tools --region=us-central1 --port=3000 &
curl -i -X POST http://localhost:3000/mcp \
  -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'

# 方式 2：直接帶 ID token（服務對服務用這個）
TOKEN=$(gcloud auth print-identity-token)
curl -i -X POST $MCP_URL/mcp \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

**為什麼**

- **為什麼 stdio 不能上雲**：Cloud Run 只收 HTTP 請求，它沒辦法「啟動你的程式當子行程然後餵 stdin」。所以遠端 MCP 一律 streamable-http。`mcp.Dockerfile` 裡那行 `ENV MCP_TRANSPORT=http` 就是這件事 —— Lab 6 的 `server.py` 看這個變數決定 transport。**忘了設**的話 server 會用 stdio 模式啟動、沒有人 listen `$PORT`，Cloud Run 等 4 分鐘後放棄，錯誤訊息是：
  ```
  ERROR: (gcloud.run.deploy) Revision 'mcp-tools-00001-abc' is not ready and cannot serve
  traffic. The user-provided container failed to start and listen on the port defined
  provided by the PORT=8080 environment variable within the allocated timeout.
  ```
  這個訊息長得很像「我的程式有 bug」，其實九成是「我沒有 listen 對的 port」。
- **為什麼 CMD 要用 `sh -c`**：`$PORT` 是 Cloud Run 在啟動容器時注入的環境變數，exec form 的 `CMD ["uv","run","server.py"]` 不會展開任何 `$`。寫死 `--port 8080` 大部分時候會通，但 Cloud Run **不保證** `$PORT` 是 8080，所以照規矩讀變數。
- **為什麼一定要 `--no-allow-unauthenticated`**：這是一個能讀寫外部 API 的工具端點。開公開的話，全世界都能用你的配額、你的帳單。首次部署如果沒帶這個旗標，gcloud 會問「Allow unauthenticated invocations?」—— demo 選 y、正式選 N。這個 Lab 一律 N。
- **為什麼 proxy 不用自己帶 token**：`gcloud run services proxy` 在本機開一個通道，每個經過的請求由 gcloud 幫你簽上 ID token。這也是為什麼 Antigravity 的 `mcp_config.json` 可以直接寫 `"serverUrl": "http://localhost:3000/mcp"` 而不用處理認證 —— 而且欄位是 `serverUrl`，不是 `url`（附錄 D ④）。
- **為什麼 `Accept` 要同時給兩種**：MCP streamable-http 規格要求 client 宣告它同時接受 `application/json` 與 `text/event-stream`。少一個會拿到 `406 Not Acceptable` —— 那不是認證問題，是你的 header 不合規格。

**驗收**

```bash
# 1) 未授權必須被擋
curl -s -o /dev/null -w '%{http_code}\n' $MCP_URL/mcp
# → 403（拿到 200 表示你不小心開了公開存取，馬上改：
#    gcloud run services remove-iam-policy-binding mcp-tools --region us-central1 \
#      --member allUsers --role roles/run.invoker）

# 2) 帶 token 必須進得去（tools/list 要看到 lab6 的工具名）
curl -s -X POST $MCP_URL/mcp -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | head -c 300
# → 應該看到 convert_currency 之類的工具名

# 3) proxy 那條也要通
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:3000/mcp
# → 405 或 406 都算過（GET 打 POST 端點），403 就是 proxy 沒起來
```

> ⚠️ 未實測：需要 GCP 專案才跑得起來。403 的 HTML 內容是 Google Frontend 的標準回應格式。

> 💡 **啊哈：這台 server 的工具邊界不在 server 上，在每個 client 自己的一行設定裡。**
> Lab 6 的 `server.py` 掛了 2 個 `@mcp.tool()`。Lab 7 只放行一個 —— `../lab7/travel_planner/agent.py:111` 的 `tool_filter=["get_weather"]`，註解寫著「`convert_currency` 不放行」。而你剛剛部署的 `concierge/agent.py` 那個 `McpToolset` **沒有 `tool_filter`**，兩個工具全開。
> 同一台 server、同一份程式碼，最小權限是 client 端各自實作的。上雲把它從「一個人的子行程」變成「任何拿到 ID token 的人都能 `tools/list` 列出全部工具的網址」，而收斂邊界的責任一行都沒往 server 那邊搬。
> **動手看**：`grep -c "@mcp.tool" ../lab6/server.py; grep -c tool_filter ../lab7/travel_planner/agent.py concierge/agent.py` → `2` / lab7 `1` / concierge `0`

---

## 步驟 2：② Toolbox 上雲（15 分）

Lab 8 的 `tools.yaml` 打包容器 → Cloud Run（私有），連 Supabase。

**動手**

```bash
./deploy.sh toolbox
```

它做的是：

```bash
cp -R ../lab8 .build/toolbox
cp dockerfiles/toolbox.Dockerfile .build/toolbox/Dockerfile
gcloud run deploy toolbox --source .build/toolbox \
  --region us-central1 --no-allow-unauthenticated \
  --service-account agent-sa@$PROJ.iam.gserviceaccount.com \
  --set-secrets "DB_PASSWORD=db-password:latest" \
  --max-instances 3
```

`dockerfiles/toolbox.Dockerfile` 只有三行有意義的內容：

```dockerfile
FROM us-central1-docker.pkg.dev/database-toolbox/toolbox/toolbox:latest
COPY tools.yaml /app/tools.yaml
CMD ["--config", "/app/tools.yaml", "--address", "0.0.0.0", "--port", "8080"]
```

**為什麼**

- **為什麼直接用官方 image**：Toolbox 是一支 Go binary，不需要 Python 環境。用官方 image 就只剩「把 `tools.yaml` 塞進去」這一件事 —— 一行 `COPY` 解決。自己寫 `FROM golang` 去 build 是白花三分鐘。
- **為什麼要 `--address 0.0.0.0`**：Toolbox 預設只聽 `127.0.0.1`。容器裡的 `127.0.0.1` 從外面連不到，Cloud Run 的健康檢查會失敗，你又會拿到那句 `failed to start and listen on the port`。這是「程式在我機器上跑得動，上雲就掛」最經典的一種。
- **為什麼這裡的 port 反而寫死 8080（步驟 1 才說不能寫死）**：因為官方 image 的 `ENTRYPOINT` 就是那支 Go binary，`CMD` 只能給它旗標，沒有 shell 可以展開 `$PORT`。所以改從另一邊對齊：`gcloud run deploy --port` 的預設值就是 8080，兩邊寫死同一個數字，容器與 Cloud Run 前端就對得上。規則其實沒變 —— **能讀 `$PORT` 就讀；讀不到就兩邊寫死同一個數字，絕不可以只寫死一邊。**
- **為什麼密碼走 `--set-secrets` 而不是 `--set-env-vars`**：`--set-env-vars` 的值會出現在 Console 的服務詳情頁、`gcloud run services describe` 的輸出、和每一份 revision 的 YAML 裡。任何有 Viewer 權限的人都看得到。`--set-secrets` 只在容器啟動時把值掛成環境變數，Console 上顯示的是「secret 的參照」而不是值本身。Lab 8 的 `tools.yaml` 早就寫成 `password: ${DB_PASSWORD}` 了，所以這裡什麼都不用改 —— **這就是「上雲不改程式碼」的意思**。
- **為什麼 `tools.yaml` 進 git 是安全的**：因為裡面只有 SQL 和 `${DB_PASSWORD}` 佔位符。SQL 進版控是刻意的設計 —— 模型只能填參數，不能改 SQL，這條界線是 Lab 8 最重要的一個決定。

**驗收**

```bash
TOOLBOX_URL=$(gcloud run services describe toolbox --region us-central1 --format 'value(status.url)')
TOKEN=$(gcloud auth print-identity-token)

# 1) 私有？
curl -s -o /dev/null -w '%{http_code}\n' $TOOLBOX_URL/api/toolset            # → 403

# 2) 帶 token 看得到 Lab 8 定義的 toolset
curl -s -H "Authorization: Bearer $TOKEN" $TOOLBOX_URL/api/toolset/hotel-tools | head -c 400
# → JSON 裡要有 search-hotels-by-city 與 get-price-stats

# 3) 真的連到 Supabase 了嗎 —— 看 log
gcloud run services logs read toolbox --region us-central1 --limit 20
# → 要看到成功載入 tools 的訊息；出現 password authentication failed 就是密碼錯或 pooler 用錯
```

> ⚠️ 未實測：官方 image 路徑與 `--config` / `--address` 旗標名以 mcp-toolbox.dev 文件與 Lab 8 的用法為準，我沒有 GCP 帳號可以 pull image 驗證。若 image pull 不到，`dockerfiles/toolbox.Dockerfile` 底部有下載 binary 的備案。

---

## 步驟 3：③ hotel agent 上雲（A2A）（15 分）

`to_a2a` 版 → Cloud Run，名片公開可讀。

**動手**

```bash
./deploy.sh a2a

A2A_URL=$(gcloud run services describe hotel-a2a --region us-central1 --format 'value(status.url)')
curl -s $A2A_URL/.well-known/agent-card.json | uv run python -m json.tool
```

**為什麼**

- **為什麼這個服務是公開的（唯一一個）**：投影片步驟 ③ 的驗收條件是「名片公開可讀」。A2A 的發現機制建立在「任何人都能讀你的名片」上 —— 名片就是公開規格，跟 `robots.txt` 一樣。如果名片也要 token，對方得先知道你是誰、先拿到授權，才能知道你會做什麼，發現機制就沒意義了。
- **但投影片 419 頁示範的是 `--no-allow-unauthenticated`，這是矛盾嗎**：不是矛盾，是兩個不同的取捨點。正式環境的做法是「服務私有 + 呼叫端 SA 綁 `run.invoker`」，連名片都要 token —— 適合企業內部已知的合作方。公開名片適合對外開放的服務。**這個 Lab 選公開**，因為步驟 ③ 要驗「名片讀得到」，而且這樣做步驟 ④ 的 `RemoteA2aAgent` 不用處理名片的認證，能把注意力留給真正難的那兩個私有服務。想做私有版：把 `deploy.sh` 的 `--allow-unauthenticated` 改回 `--no-allow-unauthenticated`，然後 `RemoteA2aAgent` 要傳一個帶 `Authorization` header 的 `httpx_client`。
- **為什麼名片上的網址會是錯的**：Lab 9 的 `agent.py` 用 `A2A_PORT` 組出 `http://localhost:8001/`。上雲之後真正的網址是 `https://hotel-a2a-xxx.run.app`，但名片裡還寫著 localhost —— 主 agent 讀到名片、照著上面的 `url` 去發請求，就會連到自己的 localhost:8001，然後 `Connection refused`。**這是這個步驟唯一真正的坑**，而且它不會在部署時報錯，要到步驟 ⑥ 問問題時才炸。
- **為什麼 `to_a2a()` 直接就是 ASGI app**：Cloud Run 要的就是一個 listen HTTP 的程序。`to_a2a()` 回傳的是標準 ASGI app，`uvicorn agent:a2a_app --port $PORT` 一行搞定，不需要任何 A2A 專用的部署工具。M9 的本機雙服務拓撲原樣上雲，差別只有網址。

**驗收**

```bash
# 1) 名片公開讀得到（不帶 token）
curl -s -o /dev/null -w '%{http_code}\n' $A2A_URL/.well-known/agent-card.json      # → 200

# 2) 名片內容對嗎 —— 三件事都要看
curl -s $A2A_URL/.well-known/agent-card.json | uv run python -m json.tool
```

三件事：

- [ ] `"name"` 是 `hotel_agent`（不是 `An ADK Agent`，那表示 Lab 9 的 `description` 是空的）
- [ ] `"skills"` 裡有訂房相關的描述（別人的 agent 靠這段決定要不要委託你）
- [ ] **`"url"` 是 `https://hotel-a2a-...run.app`，不是 `http://localhost:8001`** ← 這條最容易錯

如果 `url` 是 localhost，就要動 Lab 9 的 `agent.py` —— **這是整個 Lab 唯一要改前面 Lab 的地方**。名片上的網址是 `to_a2a()` 用 `host` / `port` / `protocol` 三個參數組出來的（ADK 2.7.1 的 `agent_to_a2a.py` 裡是 `rpc_url = f"{protocol}://{host}:{port}{prefix}/"`），所以改法是讓這三個參數認得雲端網址：

```python
# lab9/hotel_service/agent.py —— 把 to_a2a 那一段改成這樣
A2A_PORT = int(os.getenv("A2A_PORT", "8001"))
PUBLIC_HOST = os.getenv("A2A_PUBLIC_HOST")        # 例：hotel-a2a-xxxxxxxx-uc.a.run.app（不含 https://）

a2a_app = to_a2a(
    root_agent,
    host=PUBLIC_HOST or "localhost",
    port=443 if PUBLIC_HOST else A2A_PORT,        # Cloud Run 對外一律 443
    protocol="https" if PUBLIC_HOST else "http",
)
```

（Lab 9 還有一條 `A2A_STREAMING=1` 的自訂名片分支，那張名片的 `rpc_url` 是自己寫死 localhost 的 —— 上雲時**不要**開那個變數，否則你改的 `host` 會被蓋掉。）

改完之後，部署兩次（第一次才知道網址，第二次把網址餵回去）：

```bash
./deploy.sh a2a                                   # 第一次：拿到網址
A2A_URL=$(gcloud run services describe hotel-a2a --region us-central1 --format 'value(status.url)')
gcloud run services update hotel-a2a --region us-central1 \
  --set-env-vars "A2A_PUBLIC_HOST=${A2A_URL#https://}"   # 去掉 scheme，只留 host
curl -s $A2A_URL/.well-known/agent-card.json | grep -o '"url":"[^"]*"'
# → "url":"https://hotel-a2a-xxxxxxxx-uc.a.run.app:443/"（帶 :443 是正常的，443 就是 https 的預設埠）
```

> ⚠️ 未實測：`to_a2a()` 怎麼組 `rpc_url` 是讀 google-adk 2.7.1 原始碼確認的，但我沒有真的部署起來讓兩個服務對打。改 Lab 9 之前先把原檔備份一份 —— Lab 9 的 `--self-check` 不吃這條路徑，改壞了不會有人告訴你。

> 💡 **啊哈：`run.invoker` 綁的是整個服務，沒有「這個路徑公開、那個路徑要 token」這種設定。**
> 所以「名片公開可讀」的真正代價不是名片 —— 是同一個服務上的 **A2A RPC 端點也一起公開了**。任何人都能對你的 hotel agent 送任務，花你的 token、查你的資料庫。
> 想兼得只有兩條路：在 app 裡自己驗 `Authorization`，或前面架 load balancer + IAP。IAM 這一層做不到，因為它的粒度是「服務 × 身分」而不是「路徑 × 身分」。
> **動手看**：`gcloud run services get-iam-policy hotel-a2a --region us-central1 --format json` → ⚠️ 未實測：你應該會看到 policy 裡只有 `role` 與 `members`，**沒有任何路徑或 HTTP 方法欄位**

---

## 步驟 4：④ 主 agent 上雲 —— 先讓它 403 一次（30 分）

concierge（`RemoteA2aAgent` 指向③、`ToolboxToolset` 指向②）→ `adk deploy cloud_run --with_ui`。

**動手**：先看 `concierge/agent.py` 的三個工具來源怎麼接上前面三個服務。

```python
# ① MCP：header_provider 是「每次呼叫前才算 header」的鉤子
mcp_tools = McpToolset(
    connection_params=StreamableHTTPConnectionParams(
        url=auth.endpoint(MCP_URL),      # 補上 /mcp
        timeout=30.0,                    # 預設 5 秒，冷啟動會超過
    ),
    header_provider=lambda ctx: auth.auth_headers(auth.endpoint(MCP_URL)),
)

# ② Toolbox：靜態 header
db_tools = ToolboxToolset(
    server_url=TOOLBOX_URL,
    toolset_name="hotel-tools",
    additional_headers=auth.auth_headers(TOOLBOX_URL),
)

# ③ A2A：名片公開，不用帶 token
hotel_agent = RemoteA2aAgent(
    name="hotel_agent",
    description="訂房專員（雲端 A2A 服務）：依城市與預算搜尋旅館並推薦。",
    agent_card=A2A_URL.rstrip("/") + AGENT_CARD_WELL_KNOWN_PATH,
)
```

然後部署 —— **這一次故意不跑 `iam` 階段**：

```bash
./deploy.sh agent          # 注意：沒有 iam
```

`deploy.sh` 下的其實是這一條，注意 agent 路徑後面那個孤零零的 `--`：

```bash
uv run adk deploy cloud_run \
  --project=$GOOGLE_CLOUD_PROJECT --region=us-central1 \
  --service_name=concierge-agent --app_name=concierge \
  --with_ui --trace_to_cloud \
  --session_service_uri='$SESSION_DB_URL' \
  concierge \
  -- \
  --no-allow-unauthenticated \
  --service-account=agent-sa@$GOOGLE_CLOUD_PROJECT.iam.gserviceaccount.com \
  --set-secrets="SESSION_DB_URL=session-db-url:latest" \
  --set-env-vars="MCP_URL=$MCP_URL,TOOLBOX_URL=$TOOLBOX_URL,A2A_URL=$A2A_URL" \
  --max-instances=3
```

部署會成功，服務會是綠的。打開 UI 問一句話：

```bash
AGENT_URL=$(gcloud run services describe concierge-agent --region us-central1 --format 'value(status.url)')
gcloud run services proxy concierge-agent --region=us-central1 --port=8080 &
open http://localhost:8080/dev-ui/          # macOS；Linux 用 xdg-open
```

在網頁上問：「100 美元是多少台幣？」

它會回一句像「工具呼叫失敗」或「我沒辦法查詢」的話。去看 log：

```bash
gcloud run services logs read concierge-agent --region us-central1 --limit 50 | grep -i "403\|forbid"
```

你會看到類似：

```
httpx.HTTPStatusError: Client error '403 Forbidden' for url
'https://mcp-tools-xxxxxxxx-uc.a.run.app/mcp'
```

**現在修好它：**

```bash
./deploy.sh iam
```

`iam` 階段做的只有兩條指令：

```bash
gcloud run services add-iam-policy-binding mcp-tools --region us-central1 \
  --member "serviceAccount:agent-sa@$PROJ.iam.gserviceaccount.com" --role roles/run.invoker
gcloud run services add-iam-policy-binding toolbox --region us-central1 \
  --member "serviceAccount:agent-sa@$PROJ.iam.gserviceaccount.com" --role roles/run.invoker
```

不用重新部署（IAM 是即時生效的），回到網頁重問同一句話 —— 這次會成功。

**為什麼**

- **為什麼要故意看這個 403**：因為它是這個 Lab 唯一會反覆出現的錯誤，而它的症狀最容易被誤讀。服務是綠的、部署是成功的、程式碼是對的 —— 錯的只有一條 IAM binding，而 agent 給你的錯誤訊息只會說「工具呼叫失敗」。看過一次之後，你以後遇到「agent 說工具壞了」的第一個反應就會是 `gcloud run services get-iam-policy`，而不是去讀自己的程式碼。
- **403 和 401 的差別（這個 Lab 最值錢的一句）**：
  - **403** = Cloud Run 前端擋掉了。這個身分沒有 `run.invoker`。修法是 `add-iam-policy-binding`。
  - **401** = token 本身無效，九成是 **audience 不等於目標服務 URL**。`auth.py` 的 `audience()` 就是為這件事存在的：token 的 audience 必須是 `https://mcp-tools-xxx.run.app`，**不能**是 `https://mcp-tools-xxx.run.app/mcp`。差一個 `/mcp` 就 401，而錯誤訊息只會說 `Unauthorized`，不會告訴你是 audience 的問題（附錄 D ⑦）。
  - 想確認你有沒有記住：`uv run --no-project concierge/auth.py --self-check` 裡的第一個 assert 就是這件事。
- **為什麼 MCP 用 `header_provider` 而 Toolbox 用 `additional_headers`**：ID token 有效期一小時。`header_provider` 是 callable，ADK 在**每次呼叫工具前**才執行它，token 過期會自動換新。`headers={...}` 是模組載入時算一次的靜態值 —— 實例活過一小時之後，每個工具呼叫都變 401，而且你要等一小時才會發現這個 bug。ToolboxToolset 只有靜態 `additional_headers`（`google-adk` 2.7.1 沒有 provider 版本），所以那邊有一個已知天花板，`agent.py` 裡有 `ponytail:` 註解標出來 —— 課程 demo 的實例活不到一小時（scale-to-zero 會重啟＝重新算 header），夠用。
- **為什麼那個 `--` 不能省（投影片沒講，但你一定會撞到）**：`adk deploy cloud_run` 自己的旗標（`--with_ui`、`--session_service_uri`…）只認到 `--` 為止，後面的一律原樣轉給 `gcloud run deploy`。`--no-allow-unauthenticated`、`--service-account`、`--set-secrets`、`--set-env-vars`、`--max-instances` 全都是 gcloud 的旗標，寫在 `--` 前面 adk 根本不認得，click 會在跑到 gcloud 之前就把你擋下來：
  ```
  Usage: adk deploy cloud_run [OPTIONS] AGENT
  Try 'adk deploy cloud_run --help' for help.

  Error: No such option '--no-allow-unauthenticated'.
  ```
  這條錯誤訊息很容易被誤讀成「我的 adk 版本太舊」，其實只是少了兩個字元。
- **為什麼一定要有 `requirements.txt`**：`adk deploy cloud_run` 會**幫你產一個 Dockerfile**（`google/adk/cli/cli_deploy.py` 的 `_DOCKERFILE_TEMPLATE`），內容長這樣 —— 注意這是 **adk 產給容器的**，不是要你在本機跑的指令（本機一律 `uv`）：
  ```dockerfile
  FROM python:3.11-slim
  RUN pip install "google-adk[a2a]==2.7.1"
  COPY --chown=myuser:myuser "agents/concierge/" "/app/agents/concierge/"
  RUN pip install -r "/app/agents/concierge/requirements.txt"     # ← 只有檔案存在時才會有這行
  CMD adk api_server --with_ui --port=8000 --host=0.0.0.0 --session_service_uri=$SESSION_DB_URL --artifact_service_uri=memory:// --trace_to_cloud "/app/agents"
  ```
  它只裝 `google-adk[a2a]`。`ToolboxToolset` 需要的 `toolbox-adk`、`asyncpg` 都不在裡面。少了 `requirements.txt`，容器一開機就：
  ```
  ImportError: ToolboxToolset requires the 'toolbox-adk' package.
  Please install it using `pip install google-adk[toolbox]`.
  ```
  所以 `deploy.sh` 在部署前跑 `uv export --no-hashes --no-dev --no-emit-project -o concierge/requirements.txt`。**這是 uv export 產出的部署產物，不是相依來源** —— 相依來源永遠是 `pyproject.toml` + `uv.lock`，所以它進 `.gitignore`（放在 `lab10/.gitignore`，見下一點）。
- **陷阱：`.gitignore` 放錯位置會讓部署少裝依賴**。`adk deploy` 複製 agent 目錄時會讀 **agent 目錄裡**的 `.gitignore` / `.gcloudignore` / `.ae_ignore`，符合的檔案不會被複製進去。所以如果你把 `requirements.txt` 寫進 `concierge/.gitignore`，adk 就照做把它排除，`RUN pip install -r` 那行不會產生，容器又回到上面那個 ImportError。這個 Lab 的 `.gitignore` 放在 `lab10/`（寫 `concierge/requirements.txt`），不放在 `concierge/`。
- **為什麼 `--session_service_uri` 要寫成單引號的 `'$SESSION_DB_URL'`**：那個值會被原樣寫進 Dockerfile 的 `CMD` 行。如果你在本機把變數展開了，你的 Supabase 連線字串（含密碼）就被烤進 image layer，任何能讀 Artifact Registry 的人都撈得到。而 adk 產的 `CMD` 是 shell form，所以字面上的 `$SESSION_DB_URL` 會在**容器啟動時**才由 shell 展開 —— 值來自 `--set-secrets` 掛進來的環境變數。機密留在 Secret Manager，image 裡只有變數名。
- **為什麼不用 `--allow-unauthenticated` 圖個方便**：`--with_ui` 的 dev UI 是一個能直接對你的 agent 下指令的網頁。開公開就是把「花你的 token、用你的資料庫工具」的權限送給全世界。demo 想給人看就用 `gcloud run services proxy` 開通道，或把對方的帳號加進 `run.invoker`。

**驗收**

```bash
TOKEN=$(gcloud auth print-identity-token)

# 1) 私有？
curl -s -o /dev/null -w '%{http_code}\n' $AGENT_URL/list-apps                    # → 403

# 2) 帶 token 看得到 app
curl -s -H "Authorization: Bearer $TOKEN" $AGENT_URL/list-apps                   # → ["concierge"]
# 拿到 [] 就是 concierge/__init__.py 裡少了 from . import agent

# 3) IAM 綁好了嗎
gcloud run services get-iam-policy mcp-tools --region us-central1 | grep -A2 run.invoker
# → 要看到 agent-sa@...

# 4) 那個 403 你看過了嗎
# - [ ] 我看到過 httpx.HTTPStatusError: ... '403 Forbidden' 這一行
# - [ ] 我知道修它只需要一條 add-iam-policy-binding，不用改程式碼、不用重新部署
```

**這一步哪些是實測過的**（不用 GCP 帳號也驗得到，用一份裝好的 google-adk 2.7.1）：

- ✅ 少了 `--` 真的會噴 `Error: No such option '--no-allow-unauthenticated'.`；加上 `--` 之後一路跑到 `Deploy failed: [Errno 2] No such file or directory: 'gcloud'`（本機沒裝 gcloud）—— 表示所有旗標都被吃下去了。
- ✅ 產出的 Dockerfile `CMD` 是 shell form，裡面是字面的 `$SESSION_DB_URL`（不是展開後的連線字串）。
- ✅ 有 `requirements.txt` → `RUN pip install -r "/app/agents/concierge/requirements.txt"`；沒有 → `# No requirements.txt found.`。
- ✅ 在 `concierge/` 放一個寫著 `requirements.txt` 的 `.gitignore`，adk 會印 `Reading ignore patterns from .gitignore...` 然後 Dockerfile 變回 `# No requirements.txt found.` —— 上面那個陷阱是真的。
- ✅ `concierge/agent.py` 三種接法 import 得起來：`uv run python -c "import concierge.agent as m; print(m.root_agent.name)"`（要先設好三個 URL 環境變數，而且私有服務的網址在本機會噴 `DefaultCredentialsError`，所以本機請用 proxy 的 `http://localhost:3000`）。

> ⚠️ 未實測：`gcloud run deploy` 本身、Cloud Run 真的回 403、UI 上的工具呼叫失敗訊息、`--set-secrets` 掛進去的值真的沒進 image layer —— 這些都要有 GCP 專案才驗得到。

> 💡 **啊哈：容器裡跑的 ADK 不是你本機那套 —— 少 26 個依賴、少一支 1522 行的 `dev_server.py`、憑證來源整個換掉。**
> 上面看過 adk 產的 Dockerfile 長什麼樣，這裡是它的數字：你 `pyproject.toml` 宣告 5 個 extra，那行 `pip install "google-adk[a2a]"` 只認 1 個。
> 它還會 `os.remove` 掉剛裝好的 `dev_server.py` —— 本機 `adk web` 的 `/dev/*` trace、`build_graph`、agent builder 端點在雲上**不存在**。而 `cli_deploy.py:85` 那行 `ENV GOOGLE_GENAI_USE_ENTERPRISE=1` 把模型後端從 AI Studio key 換成企業後端、憑證改走容器身分（ADC＝`agent-sa`），這才是 `agent-sa` 一定要 `roles/aiplatform.user` 的原因。
> **動手看**：`uv run aha.py --deps` → 六列對照表；`asyncpg mcp sqlalchemy toolbox-adk` 那一列就是「容器缺、`agent.py` 要」的交集

---

## 步驟 5：⑤ session 持久化（10 分）

`SESSION_DB_URL` 走 Secret Manager 掛 Supabase。

**動手**：這一步在步驟 4 的 `./deploy.sh agent` 裡已經做完了（`--set-secrets "SESSION_DB_URL=session-db-url:latest"`）。現在要**證明它真的生效**。

```bash
gcloud run services proxy concierge-agent --region=us-central1 --port=8080 &
```

在 `http://localhost:8080/dev-ui/` 開一個對話，說「我叫小明，我吃素」。然後：

```bash
# 強制換一個新實例（等同重啟）
gcloud run services update concierge-agent --region us-central1 \
  --update-env-vars "FORCE_NEW_REVISION=$(date +%s)"
```

回到同一個 session（UI 的 session 下拉選單挑同一個 id），問「我叫什麼名字？」

**為什麼**

- **不這樣寫會怎樣**：`adk deploy cloud_run` 在沒給 `--session_service_uri` 時，會自動填 `memory://`（`cli_deploy.py` 裡寫死的）。那表示 session 存在容器的記憶體裡。Cloud Run 是 scale-to-zero 的 —— 沒流量幾分鐘後實例就收掉，你的對話歷史連同它一起消失。使用者的體感是「它忘記我剛剛說什麼」，而且**沒有任何錯誤訊息**。這是所有「本機好好的、上雲怪怪的」問題裡最常見的一種。
- **為什麼是 `--set-secrets` 而不是 `--set-env-vars`**：連線字串裡有資料庫密碼。`--set-env-vars` 的值會出現在 `gcloud run services describe` 的輸出、Console 的服務詳情頁、和每一份 revision 的 YAML。`--set-secrets` 掛的是參照，值只在容器啟動時注入。
- **為什麼 session 落地要用同一個 Supabase**：M8 已經把資料庫準備好了，沒必要為 session 再開一個 Cloud SQL（會花錢）。ADK 第一次啟動會自己建表，你不用寫 DDL。
- **為什麼不用 `agentengine://ID`**：那是把 session 交給託管 Agent Engine 的選項（`adk deploy cloud_run --agent_engine_id=<ID>`）。步驟 ⑦ 會另外部署一個 Agent Engine，但那是對照組，不要把 Cloud Run 的 session 也綁進去 —— 混在一起你就分不清哪個效果是誰的。

**驗收**

```bash
# 1) 環境變數是參照，不是值
gcloud run services describe concierge-agent --region us-central1 \
  --format 'yaml(spec.template.spec.containers[0].env)'
# → SESSION_DB_URL 那一項要是 valueFrom.secretKeyRef，不是明文 postgresql+asyncpg://...

# 2) 表真的被建出來了（在 Supabase SQL Editor 跑）
#    select table_name from information_schema.tables where table_schema='public';
#    → 除了 hotels，還要多出 ADK 建的 sessions / events 等表

# 3) 重啟後對話還在
# - [ ] 換 revision 之後，同一個 session id 問「我叫什麼名字」，它答得出「小明」
# - [ ] describe 的輸出裡搜不到你的資料庫密碼
```

> ⚠️ 未實測：表名是從 `google/adk/sessions/schemas/v1.py` 的 `__tablename__` 讀出來的（`sessions` `events` `app_states` `user_states` `adk_internal_metadata`），不是跑起來看到的 —— 而 `database_session_service.py` 同時 import 了 v0 與 v1，連到舊 schema 的資料庫時表會少一張。

> 💡 **啊哈：同一條連線字串，兩種主權 —— `hotels` 的 schema 是你定的，`sessions` 的你連 `CREATE TABLE` 都看不到。**
> Lab 8 的 `tools.yaml` 用你手寫的 SQL 讀 `hotels`（schema 你定、SQL 進版控）；這一步的 `SESSION_DB_URL` 指向同一台 Supabase，ADK 自己建那幾張 session 表（schema 它定、DDL 在它的 SQLAlchemy model 裡，不在你的版控裡）。
> 「狀態存哪裡」的四格到這裡收齊 DB 那一格：檔案／session state（記憶體）／DB／模型 context —— 上雲之後只有 DB 那一格活得過容器重啟。
> **動手看**：`grep -n "FROM hotels" ../lab8/tools.yaml; grep -n __tablename__ .venv/lib/python*/site-packages/google/adk/sessions/schemas/v1.py` → 你的 SQL 在 git 裡（28 / 44 行）；ADK 那五張表（`sessions` `events` `app_states` `user_states` `adk_internal_metadata`）只存在於它的 SQLAlchemy model 裡，那段 `CREATE TABLE` 你永遠看不到

---

## 步驟 6：⑥ 端到端驗收（15 分）

從 `--with_ui` 網頁問「預算 3000 東京兩晚」→ 跨四個雲端服務完成回答。

**動手**

```bash
./verify.sh
```

12 項全 PASS 之後，回到 UI 問一句需要三種工具的話：

```
我預算一晚 3000 台幣，東京兩晚，另外 100 美元大概多少台幣？幫我推薦一間並說明理由。
```

然後看 trace：

```bash
open "https://console.cloud.google.com/traces/list?project=$GOOGLE_CLOUD_PROJECT"
```

**為什麼**

- **為什麼要問一句需要三種工具的話**：分開問三次，每個服務都可能只是「剛好能單獨動」。合起來問一次才驗得到真正的東西：主 agent 有沒有正確路由、A2A 的委派有沒有把上下文帶過去、四個容器的認證有沒有全部串通。這才是「multi-agent 系統」而不是「三個各自能動的服務」。
- **為什麼第一次很慢（10-20 秒）**：四個 Cloud Run service 都是 scale-to-zero，第一個請求要等四次冷啟動串起來。第二次問就快了。這不是 bug，是 serverless 的代價 —— 換來的是沒流量時零費用。要消掉冷啟動就設 `--min-instances 1`，但那表示 24 小時都在計費，這個 Lab 不做。
- **為什麼要看 trace**：生產 agent 必須能回答三個問題 —— 它做了什麼、為什麼、花了多少錢。`--trace_to_cloud` 讓每次查詢變成一條 span 瀑布：模型呼叫多久、哪個工具慢、哪一跳失敗。沒有 trace 的時候，「agent 好慢」這句話你完全沒辦法往下查。

**驗收**

```bash
./verify.sh
# → PASS=12  FAIL=0
```

一次回答裡要同時出現這三件事：

- [ ] **匯率換算的數字**（來自 ① MCP server）
- [ ] **具體的旅館名稱與價格**（來自 ② Toolbox → Supabase 的 `hotels` 表，不是模型編的）
- [ ] **推薦理由**（來自 ③ A2A hotel agent 的委派）
- [ ] Cloud Trace 裡看得到一條 span 瀑布，含工具呼叫的節點
- [ ] 第二次問同樣的問題明顯比第一次快（冷啟動的證據）

怎麼判斷旅館是查來的還是編的：故意問一個資料庫裡沒有的城市（例如「冰島雷克雅未克」）。它應該說查不到，而不是很有自信地編三間旅館出來。

> ⚠️ 未實測：需要四個服務全部部署完成。

> 💡 **啊哈：上面那句「這個 Lab 不做 `--min-instances 1`」，價目表上的數字是 $256.57／月。**
> 4 個服務常駐一個月＝1,036 萬 vCPU-秒，扣掉 18 萬免費額度後照 p.408 價目是 $244.51，加 RAM $12.06。你剛剛等的那 10 秒，就是這筆錢的另一個寫法 —— 而它是「代價」還是「便宜」，取決於你有沒有真的算過。
> **動手看**：`uv run aha.py --cost` → 並排表，月費合計 `$0.00` vs `$256.57`（不連網、不花錢；p.408 沒給 min-instance 的閒置 CPU 折扣價，所以這是上限）

---

## 步驟 7：⑦ Agent Engine 對照組（15 分）

同一個 agent `adk deploy agent_engine` 再部署一次，比較體驗。

**動手**：這一步跟步驟 ④ 有一個關鍵差別 —— **Agent Engine 沒有 `--set-env-vars`**。adk 是把 agent 目錄裡的 `.env` 讀出來當環境變數帶上雲（`cli_deploy.py` 的 `to_agent_engine` 走 `dotenv_values(agent_folder/.env)`）。所以要先把三個真網址寫進 `concierge/.env`：

```bash
cp concierge/.env.sample concierge/.env    # 還沒有的話
for s in mcp-tools toolbox hotel-a2a; do
  echo "$s = $(gcloud run services describe $s --region us-central1 --format 'value(status.url)')"
done
# 把三個網址填進 concierge/.env 的 MCP_URL / TOOLBOX_URL / A2A_URL
# 注意：這裡要填「真網址」，不是本機 proxy 的 localhost —— 容器裡沒有 proxy

./deploy.sh engine
```

（`deploy.sh engine` 會先檢查 `concierge/.env` 裡有沒有 `MCP_URL`，沒有就直接擋下來並印出要填什麼 —— 不然你會部署成功、然後在雲端拿到 `KeyError: 'MCP_URL'`。）

它做的事：

```bash
uv export --no-hashes --no-dev --no-emit-project -o concierge/requirements.txt
uv run adk deploy agent_engine \
  --project=$GOOGLE_CLOUD_PROJECT --region=us-central1 \
  --display_name="Lab10 Concierge" \
  concierge
```

完成後去 Console：Vertex AI → Agent Engine（選單上可能寫 Agent Runtime）。

**為什麼**

- **投影片這裡有一處要修**：投影片 403 頁與附錄 A 的速查表都寫 `--staging_bucket=gs://...`。在 google-adk 2.7.1 這個旗標**已經 deprecated**，帶了會噴：
  ```
  WARNING: --staging_bucket is deprecated and will be removed. Please leave it unspecified.
  ```
  它只是警告不是錯誤，投影片的指令還是跑得動，但新寫的腳本不要再帶。同一批被 deprecate 的還有 `--requirements_file`、`--env_file`、`--adk_app`、`--absolutize_imports` —— 現在改成讀 agent 目錄裡的 `requirements.txt`、`.env` 和 `.agent_engine_config.json`。（查證方式：`grep -n "staging_bucket" -A6` 翻 `google/adk/cli/cli_tools_click.py`。）
- **同一份程式碼、兩種部署，差在哪**：

  | | Cloud Run（步驟 ④） | Agent Engine（這一步） |
  |---|---|---|
  | 你管什麼 | 容器裡的一切 | 只管 agent 程式碼 |
  | session | 你自己接 Supabase（步驟 ⑤） | 內建託管 sessions |
  | 記憶 | 沒有，要自己做 | Memory Bank（p.404） |
  | 觀測 | 自己開 `--trace_to_cloud` | traces / logs / metrics 內建分頁 |
  | 測試介面 | `--with_ui` 的 dev UI（要自己開通道） | Console 內建聊天視窗 + debug 面板 |
  | 自訂 API / 前端 | 想加什麼路由都行 | 不行，只有 agent 端點 |
  | 計費 | 用多少算多少，scale-to-zero | vCPU-小時 $0.085 + RAM GiB-小時 $0.009，免費層 50 vCPU-h + 100 GiB-h |
  | 閒置成本 | 零 | **不是零** —— 這是它最容易踩的一點 |

  一句話：**要掛自訂 API / 前端 / MCP server 就 Cloud Run；純 agent API 想最快上線就 Agent Engine。**
- **這一步可能會失敗，而失敗本身就是資訊**：這個 concierge 要連兩個私有 Cloud Run 服務。它在 Cloud Run 上跑的時候身分是 `agent-sa`（我們綁過 `run.invoker`）；在 Agent Engine 上跑的時候身分是 Vertex AI 的服務代理，那個身分沒有 `run.invoker`，所以工具呼叫大概會 403。要修就得把那個服務代理也綁上 `run.invoker`。**這正好說明了「託管」的代價**：runtime 不是你的，執行身分也就不是你選的。
- **為什麼一定要記得刪**：Agent Engine 不是 scale-to-zero。閒置的 reasoningEngine 資源會持續計 vCPU-小時。投影片 402 頁那句「收工刪除（避免閒置計費）」不是客套話。

**驗收**

```bash
# 1) 資源建出來了
gcloud beta ai agent-engines list --region us-central1 --format 'table(name,displayName)'
# → 要看到 Lab10 Concierge 與它的 reasoningEngines/<ID>

# 2) Console 的內建聊天視窗問一句「東京有哪些旅館」
# - [ ] 它回得出話（模型層通了）
# - [ ] 工具呼叫成功 → 恭喜；工具 403 → 你剛好驗證了上面那段「執行身分不是你選的」
# - [ ] Traces 分頁點得開，看得到 span

# 3) 你能回答：什麼情況你會選 Agent Engine，什麼情況選 Cloud Run
```

> ⚠️ 未實測：需要 GCP 專案。`--staging_bucket` 已 deprecated 這件事是讀 google-adk 2.7.1 的 `cli_tools_click.py` 原始碼確認的（`callback=_deprecate_parameter`，只印黃字警告，不是錯誤）。Agent Engine 連私有 Cloud Run 會不會 403，我沒有實際驗證。

---

## 步驟 8：⑧ 清理（10 分）

刪除或縮零所有服務；確認 budget 頁面無異常。

**動手**

```bash
./teardown.sh --dry-run     # 先看要刪什麼
./teardown.sh               # 真的刪
```

**為什麼**：見本文最後的「清理」一節（完整可貼指令都在那裡）。這裡只講一件事 —— **scale-to-zero 不等於免費**。Cloud Run 的服務縮到零之後 vCPU 不計費，但它的 image 還躺在 Artifact Registry 裡，四個 image 加起來 1-2 GB，是這個 Lab 唯一有機會吃掉免費層的一項（Artifact Registry 的免費額度投影片沒給，看 cloud.google.com/pricing）。而 Agent Engine 根本不會縮到零。所以「縮零」只解決了兩項成本裡的一項，`teardown.sh` 該刪的還是要刪。

**驗收**

```bash
gcloud run services list --region us-central1                      # → 空的
gcloud beta ai agent-engines list --region us-central1              # → 空的
gcloud artifacts repositories list --location us-central1           # → 沒有 cloud-run-source-deploy
open "https://console.cloud.google.com/billing?project=$GOOGLE_CLOUD_PROJECT"
```

- [ ] 四個 Cloud Run service 都不見了
- [ ] Agent Engine 清單是空的（**最容易漏的一項**）
- [ ] `cloud-run-source-deploy` 這個 Artifact Registry repo 被刪了
- [ ] 帳單頁面的 Cloud Run / Vertex AI 兩列沒有繼續長（等 24 小時後再看一次更準）
- [ ] Supabase **沒有**被動到（Capstone 還要用）

---

## 常見錯誤對照表

| 症狀 | 原因 | 解法 |
|---|---|---|
| `ERROR: (gcloud.run.deploy) Revision 'mcp-tools-00001-abc' is not ready and cannot serve traffic. The user-provided container failed to start and listen on the port defined provided by the PORT=8080 environment variable within the allocated timeout.` | 容器沒有 listen `$PORT`。MCP 少了 `MCP_TRANSPORT=http`（跑成 stdio）；toolbox 少了 `--address 0.0.0.0`（只聽 127.0.0.1）；或 `CMD` 用 exec form 導致 `$PORT` 沒展開 | Dockerfile 的 `CMD` 改 `["sh","-c","… $PORT"]`；MCP 加 `ENV MCP_TRANSPORT=http`；toolbox 加 `--address 0.0.0.0` |
| `<h1>Error: Forbidden</h1><h2>Your client does not have permission to get URL <code>/mcp</code> from this server.</h2>`（HTTP 403） | 沒帶 ID token，或這個身分沒有 `roles/run.invoker`。這是 **Cloud Run 前端**擋的，你的 app 根本沒收到請求 | 人：`gcloud run services proxy` 或 `-H "Authorization: Bearer $(gcloud auth print-identity-token)"`。服務：`./deploy.sh iam` |
| `httpx.HTTPStatusError: Client error '403 Forbidden' for url 'https://mcp-tools-xxx-uc.a.run.app/mcp'`（出現在 agent 的 log 裡，UI 上只顯示「工具呼叫失敗」） | `agent-sa` 沒綁目標服務的 `run.invoker` | `./deploy.sh iam`。IAM 即時生效，不用重新部署 |
| `HTTP 401 Unauthorized`（token 明明是剛拿的） | audience 不等於目標服務 URL。最常見是把 `/mcp` 一起放進 audience，或 region 那段網址抄錯一個字元 | audience 只到 host：`https://mcp-tools-xxx.run.app`。`concierge/auth.py` 的 `audience()` 專門處理這件事，跑 `--self-check` 看它怎麼切 |
| `ImportError: ToolboxToolset requires the 'toolbox-adk' package. Please install it using pip install google-adk[toolbox].`（容器一開機就掛） | `adk deploy` 產的 Dockerfile 只裝 `google-adk[a2a]`。少了 `concierge/requirements.txt`，或你把它寫進了 `concierge/.gitignore`（adk 會讀 agent 目錄的 .gitignore 並排除符合的檔案） | `uv export --no-hashes --no-dev --no-emit-project -o concierge/requirements.txt`；`.gitignore` 放在 `lab10/` 而不是 `concierge/` |
| `sqlalchemy.exc.InvalidRequestError: The asyncio extension requires an async driver to be used. The loaded 'psycopg2' is not async.` | `SESSION_DB_URL` 寫成 `postgresql://` | 改 `postgresql+asyncpg://`（附錄 D ②） |
| `ModuleNotFoundError: No module named 'asyncpg'` | `google-adk[db]` 只給 sqlalchemy，async driver 要自己加 | `uv add asyncpg`，重新 `uv export` 再部署 |
| 連得上資料庫，但查詢隨機失敗 / prepared statement 錯誤 | 用了 Supabase 的 transaction pooler（6543） | 換 Session pooler（5432）（附錄 D ③） |
| agent 說「找不到 hotel_agent」或第一次委派就整個炸掉 | A2A 名片抓不到，而 `RemoteA2aAgent` 是**第一次被呼叫時**才去抓名片，不是啟動時 —— 所以部署綠燈不代表名片是通的 | `curl $A2A_URL/.well-known/agent-card.json` 先確認；`verify.sh` 有這一項 |
| A2A 委派時 `Connection refused` 或連到 `localhost:8001` | 名片上的 `url` 還是本機網址。Lab 9 的 `A2A_PORT` 只影響名片寫的網址，不影響 listen | 讓 Lab 9 的 agent 讀公開網址的環境變數，部署完回填（步驟 3） |
| `curl -H "Authorization: Bearer $TOKEN" $AGENT_URL/list-apps` 回 `[]` | `concierge/__init__.py` 少了 `from . import agent`，ADK 掃不到 `root_agent` | 把那一行加回去 |
| `406 Not Acceptable`（打 `/mcp`） | 不是認證問題。MCP streamable-http 要求 client 同時宣告接受 `application/json` 與 `text/event-stream` | 補 `-H 'Accept: application/json, text/event-stream'`。`verify.sh` 把 406 判為 PASS，因為它證明 IAM 已經放行 |
| `WARNING: --staging_bucket is deprecated and will be removed. Please leave it unspecified.` | 投影片 403 頁的寫法，在 google-adk 2.7.1 已 deprecated | 拿掉這個旗標即可（只是警告，不影響部署） |
| `ModuleNotFoundError: No module named 'google'`（本機跑 concierge） | 用了 `python xxx.py` | 一律 `uv run`。這個 Lab 的離線檢查是 `uv run --no-project concierge/auth.py --self-check` |
| `404 NOT_FOUND: Publisher Model ... not found`（agent 一開口就掛） | `concierge/agent.py` 的型號名 `gemini-3.7-flash` 抄自投影片，你的專案/region 可能沒有這個型號 | 型號名以課程投影片為準；404 就用 `client.models.list()` 查目前可用的名字，改 `agent.py` 那一行 |
| `gcloud secrets create` 說 `ALREADY_EXISTS` | secret 已經建過了 | 已處理：`deploy.sh` 的 secrets 階段是 `create || versions add`，重跑不會壞 |
| `Error: No such option '--no-allow-unauthenticated'.`（跟著一行 `Usage: adk deploy cloud_run [OPTIONS] AGENT`） | gcloud 的旗標寫在 `--` 前面了。`adk deploy cloud_run` 自己的旗標到 `--` 為止，後面才是原樣轉給 gcloud 的 | agent 路徑後面加一個 `--`：`… concierge -- --no-allow-unauthenticated --service-account=…`（實測過） |
| `KeyError: 'MCP_URL'`（Agent Engine 上，Cloud Run 那份卻好好的） | Agent Engine 沒有 `--set-env-vars`，它讀的是 agent 目錄的 `.env` | 把三個真網址寫進 `concierge/.env` 再 `./deploy.sh engine`（腳本會先幫你擋一次） |
| `google.auth.exceptions.DefaultCredentialsError: Neither metadata server or valid service account credentials are found.`（本機 `adk web` 一啟動就掛） | 使用者帳號的 ADC 不能簽任意 audience 的 ID token，只有 service account 或雲上的 metadata server 可以 | 本機別直連私有服務：開 `gcloud run services proxy`，`.env` 的 `MCP_URL` / `TOOLBOX_URL` 填 `http://localhost:3000` / `3001`（`auth.py` 看到 localhost 就不去換 token） |

---

## 完整解答

| 檔案 | 是什麼 |
|---|---|
| `config.sh` | 唯一設定檔：專案、region、四個服務名、三個 Lab 路徑。改這裡三支腳本都跟著變 |
| `deploy.sh` | 9 階段部署。`--dry-run` 只印指令；`./deploy.sh mcp` 只跑一個階段 |
| `verify.sh` | 12 項驗收。`--self-check` 離線驗判定邏輯（實測通過） |
| `teardown.sh` | 刪光。`--dry-run` / `--keep-secrets` |
| `dockerfiles/*.Dockerfile` | 三個元件各一份，`deploy.sh` 會複製到 `.build/<元件>/Dockerfile` |
| `concierge/agent.py` | 主 agent：MCP + Toolbox + RemoteA2aAgent 三種接法並排在一支檔案裡 |
| `concierge/auth.py` | audience / endpoint / auth_headers。**卡在 401 的時候先讀這支** |
| `aha.py` | 兩張離線對照表：本機的 ADK vs 容器裡的 ADK、scale-to-zero vs `--min-instances 1`。`--self-check` 實測通過 |

設計理由、完整介面契約、錯誤處理表：`SPEC.md`。需求對照投影片步驟、費用明細、驗收清單：`PRD.md`。

---

## 想再往下玩

- **`--min-instances 1` 對照組**：把 concierge 設成常駐，量一下第一次回應快多少 —— 然後看帳單，算出「消掉冷啟動」這件事一個月值多少錢。
- **一鍵回滾**：`gcloud run revisions list --service concierge-agent` 找到上一版，`gcloud run services update-traffic concierge-agent --to-revisions=<REV>=100`。p.422 上線檢查清單第 6 項就是這個，10 秒的事，但沒練過的人在事故現場想不起來。
- **`cloud-run-mcp`**：把「部署到 Cloud Run」本身變成 agent 的工具（`npx -y @google-cloud/cloud-run-mcp` 掛進 Antigravity），然後對它說「把這個專案部署到 Cloud Run」。M3 的 agent 用 M6 的協定呼叫 M10 的平台部署 M7 的 agent —— 這個 Lab 做完才有資格覺得它有趣。
- **Agent Garden 反向工程**：去 `console.cloud.google.com/agent-platform/agent-garden` 找最接近 concierge 的官方樣板，讀它的架構怎麼拆 agent —— 你剛親手踩過一遍，這次讀得懂它為什麼那樣拆。
- **接下去是 Capstone**：這個 Lab 的四個服務加上 M4 的知識庫，就是「個人 LLM Wiki／助理系統」的骨架。差別只在你要接的是 Supabase 的 `hotels` 表，還是你自己的筆記。

---

## 這個 Lab 你真正學到的

- 「部署」不是把程式搬上去，是在另一個 runtime 重建一份環境 —— 少 26 個依賴、少一支 1522 行的 dev_server、憑證來源整個換掉，而 bug 全長在這三處差異裡。
- IAM 的粒度是「服務 × 身分」而不是「路徑 × 身分」：403 是身分沒被放行、401 是 audience 不等於目標網址，而「名片公開」等於整個服務公開。
- 同一個函式往外包一層就多一層要過的認證：python 函式 → MCP tool → 有 IAM policy 的網址，本體一個字沒改，呼叫成本從一次函式呼叫變成一次 HTTPS ＋一顆 ID token ＋一條 `run.invoker` binding。而「哪些工具放行」這件事，從頭到尾都是 client 端自己寫的一行 `tool_filter`。
- serverless 的成本模型就是它的體感代價：閒置 $0 與第一次請求等 10 秒，是同一個 scale-to-zero 的兩面，價差 $256／月。
- 託管（Agent Engine）換掉的不只是維運，是**執行身分** —— runtime 不是你的，你就不能選它用誰的權限去呼叫別人。

---

## 清理

**這個 Lab 有會計費的雲端資源，一定要清。** 一鍵版：

```bash
cd lab10
./teardown.sh --dry-run    # 先看
./teardown.sh              # 再刪
```

手動版（`teardown.sh` 做的就是這些，貼上去也一樣）：

```bash
PROJ=$GOOGLE_CLOUD_PROJECT
R=us-central1

# 1) 四個 Cloud Run service
for s in concierge-agent hotel-a2a toolbox mcp-tools; do
  gcloud run services delete $s --region $R --project $PROJ --quiet
done

# 2) Agent Engine（閒置也計費，最容易漏的一項）
gcloud beta ai agent-engines list --region $R --project $PROJ --format='value(name)'
gcloud beta ai agent-engines delete <上面列出的 name> --region $R --project $PROJ --quiet

# 3) Cloud Build 堆在 Artifact Registry 的 image（四個 image 1-2 GB，唯一有機會超免費層的一項）
gcloud artifacts repositories delete cloud-run-source-deploy --location $R --project $PROJ --quiet

# 4) service account 與它的 project-level 綁定
for role in roles/aiplatform.user roles/secretmanager.secretAccessor roles/logging.logWriter; do
  gcloud projects remove-iam-policy-binding $PROJ \
    --member "serviceAccount:agent-sa@$PROJ.iam.gserviceaccount.com" \
    --role $role --condition None --quiet
done
gcloud iam service-accounts delete agent-sa@$PROJ.iam.gserviceaccount.com --project $PROJ --quiet

# 5) 機密（Capstone 還要用就跳過這步，或用 ./teardown.sh --keep-secrets）
gcloud secrets delete session-db-url --project $PROJ --quiet
gcloud secrets delete db-password --project $PROJ --quiet

# 6) 本機暫存
rm -rf .build concierge/requirements.txt

# 7) 確認（這三條都要是空的）
gcloud run services list --region $R --project $PROJ
gcloud beta ai agent-engines list --region $R --project $PROJ
gcloud artifacts repositories list --location $R --project $PROJ
```

最後看帳單頁面：<https://console.cloud.google.com/billing> —— Cloud Run 與 Vertex AI 兩列不該繼續長。帳單資料有幾小時延遲，隔天再看一次比較準。Lab 5 設的預算告警這時候是你的第二道防線。

**不要動的東西**：Supabase 專案（Capstone 要用）、GCP 專案本身（下個 Lab 要用）、`gcloud` 的登入狀態。

預估這個 Lab 的總花費 **$0-5**：Cloud Run 全程在免費層內（200 萬請求 / 18 萬 vCPU-秒），Agent Engine 跑十幾分鐘也在 50 vCPU-h 的免費層內，唯一可能超的是 Artifact Registry 存的那 1-2 GB image —— 那也是第 3 步要刪的原因。（Cloud Build / Artifact Registry / Secret Manager 的免費額度投影片沒給，我不編數字。）
