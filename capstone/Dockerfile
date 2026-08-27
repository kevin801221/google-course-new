# 一份 Dockerfile 供兩個服務用（wiki-mcp 與 research-a2a），入口用 Cloud Run 的 --command/--args 覆寫。
# 有 Dockerfile 時 `gcloud run deploy --source .` 會走 docker build，不需要 requirements.txt（本課不用 pip）。
# ⚠️ 未實測：這台機器沒有 docker，也沒有 GCP 專案，這份 Dockerfile 沒有 build 過。
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

WORKDIR /app
# 先只複製依賴清單：改程式碼時這層還能命中快取（冷啟動與 build 時間都靠它）
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY . .
ENV PORT=8080 MCP_TRANSPORT=http PYTHONUNBUFFERED=1
EXPOSE 8080

# 預設入口＝wiki-mcp。research-a2a 部署時用：
#   --command uv --args "run,uvicorn,research_service.agent:a2a_app,--host,0.0.0.0,--port,8080"
CMD ["uv", "run", "--frozen", "wiki_mcp/server.py"]
