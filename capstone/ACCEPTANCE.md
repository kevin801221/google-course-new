# Capstone 驗收矩陣

對應投影片 446 頁的六條端到端驗收＋四個 Phase 的中間成果。
`offline` 這台機器就能驗；`cloud` 要 GCP／Supabase／API key；`manual` 要人看畫面。

## Phase 1

| 勾 | ID | 驗收條目 | kind | 怎麼驗（可貼） | 預期看到 |
|---|---|---|---|---|---|
| [ ] | P1-1 | 知識層核心邏輯（切塊／向量／DSN 防呆） | offline | `uv run wiki_core.py --self-check` | wiki_core self-check OK |
| [ ] | P1-2 | ingest 管線可跑、dry-run 不寫 DB | offline | `uv run ingest.py --self-check` | ingest self-check OK |
| [ ] | P1-3 | schema 到位：documents 有 topic/created_at、業務表有資料 | cloud | `psql "$DATABASE_URL" -f schema.sql` | 最後三個 select 印出 doc_chunks / monthly_total / topic,created_at |
| [ ] | P1-4 | 雙庫對照：同一題分別問 NotebookLM 與 pgvector | manual | `uv run adk web（問 wiki_agent）＋ NotebookLM 網頁問同一題` | 兩邊都有答案；NotebookLM 有引用卡、pgvector 有 source 欄位 |

## Phase 2

| 勾 | ID | 驗收條目 | kind | 怎麼驗（可貼） | 預期看到 |
|---|---|---|---|---|---|
| [ ] | P2-1 | 團隊接線：root 禁答、google_search 獨占、模型分級 | offline | `uv run python -m concierge.agent --self-check` | concierge self-check OK |
| [ ] | P2-2 | 工具契約：docstring、上限夾住、DB 掛掉不拋例外 | offline | `uv run python -m concierge.tools --self-check` | tools self-check OK |
| [ ] | P2-3 | 摘要工作流：EMPTY 分支不呼叫 LLM、路由字串正確 | offline | `uv run digest.py --self-check` | digest self-check OK |
| [ ] | P2-4 | 446-6 的 eval 部分：evalset 對 concierge 全綠 | cloud | `uv run adk eval concierge tests/capstone.evalset.json --print_detailed_results` | 每個 case 都 PASSED |

## Phase 3

| 勾 | ID | 驗收條目 | kind | 怎麼驗（可貼） | 預期看到 |
|---|---|---|---|---|---|
| [ ] | P3-1 | wiki-mcp 工具邏輯與權限閘（唯讀部署擋住 ingest） | offline | `uv run wiki_mcp/server.py --self-check` | wiki-mcp self-check OK |
| [ ] | P3-2 | Toolbox 設定檔是合法 YAML 且 toolset 有列到工具 | offline | `uv run --with pyyaml python -c "import yaml,sys;d=[x for x in yaml.safe_load_all(open('tools.yaml')) if x];print(len(d))"` | 7 |
| [ ] | P3-3 | MCP Inspector 看得到 2 tools + 1 resource | manual | `uv run mcp dev wiki_mcp/server.py` | Tools 有 wiki_search／wiki_ingest；Resources 有 wiki://stats |
| [ ] | P3-4 | Toolbox 服務回得出 personal-data toolset | cloud | `curl -s $TOOLBOX_URL/api/toolset/personal-data | uv run python -m json.tool` | 四個工具的 name 與 description |

## Phase 4

| 勾 | ID | 驗收條目 | kind | 怎麼驗（可貼） | 預期看到 |
|---|---|---|---|---|---|
| [ ] | P4-1 | A2A 名片拿得到、skill 描述正確 | cloud | `curl -s $RESEARCH_A2A_URL/.well-known/agent-card.json | uv run python -m json.tool` | name=research_agent，skills[0].description 是研究員那段 |
| [ ] | P4-2 | 部署腳本順序正確（工具→專員→入口） | offline | `./deploy.sh --dry-run` | dry-run OK：6 段、順序 secrets → wiki-mcp → toolbox → research-a2a → IAM → concierge |
| [ ] | P4-3 | 446-1 知識問答：答案帶正確引用 | cloud | `在 concierge UI 問「我知識庫裡關於 A2A 的重點？」` | 回覆有 source，且 source 真的在 documents 表裡 |
| [ ] | P4-4 | 446-2 研究入庫：研究→ingest→再問答得到 | cloud | `問「研究 Cloud Run GPU 定價並存起來」，再問「我知識庫裡 Cloud Run GPU 的重點？」` | 第二次問答引用到剛存的 source |
| [ ] | P4-5 | 446-3 資料查詢：Toolbox SQL 正確聚合 | cloud | `問「我這個月的訂閱總花費？」` | 數字等於 select sum(monthly_twd) from subscriptions where active |
| [ ] | P4-6 | 446-4 持久化：重新整理後追問前文 | cloud | `對話 → 重新整理瀏覽器 → 追問「剛剛那筆」；並看 Supabase 的 events 表` | 追問接得上；events 表有這次對話的列 |
| [ ] | P4-7 | 446-5 摘要工作流產出合格日報 | cloud | `uv run digest.py` | Markdown 有「今日重點／值得深讀／待辦建議」三段 |
| [ ] | P4-8 | 446-6 權限：未授權身分呼叫內部服務 → 403 | cloud | `curl -s -o /dev/null -w '%{http_code}\n' $WIKI_MCP_URL/mcp` | 403 |

## 一次跑完所有離線檢查

```bash
uv run acceptance.py --offline
```

共 8 條，全綠才往下走 Phase 4 的雲端驗收。

