---
activation: always_on
---

本專案 Python 一律使用 uv。禁止 `pip`、`venv`、直接呼叫 `python`。
細節見 @/AGENTS.md 的「Python 工作流」章節。

違規會被 `uv run civicguard-audit` 在 CI 擋下來。
