---
name: shelter-normalize
description: 把某縣市的避難收容處所原始 JSON 正規化成專案 schema，並把新發現的欄位別名補進 docs。
---

# 避難所欄位正規化

1. 讀 `docs/domain/shelter-quirks.md`，確認目標 schema 與已知別名。
2. 跑 `uv run civicguard-shelters --from-file <原始 json>`。
3. 若有欄位被吃成空字串，把新別名加進 `src/civicguard/shelters.py` 的 `ALIASES`，
   同步更新 `docs/domain/shelter-quirks.md` 的對照表。
4. 跑 `uv run civicguard-shelters --self-check` 確認舊案例沒被改壞。
5. 若這次改動改變了行為契約，在 `memory/decisions.md` 新增一條，編號接續。
