# Lab 6 的 MCP server → Cloud Run。deploy.sh 會把這個檔複製成 .build/mcp/Dockerfile。
# 關鍵差別只有兩個：transport 從 stdio 換成 streamable-http、綁 0.0.0.0:$PORT。
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

WORKDIR /app

# 先只複製依賴清單再 uv sync：改程式碼不會讓 layer cache 失效，重建快很多
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY . .

# 非 root 執行：prompt injection 打進來時少一層可玩的東西
RUN adduser --disabled-password --gecos "" app && chown -R app /app
USER app

# Lab 6 的 server.py 看這個變數決定 transport；沒設會退回 stdio，
# 那 Cloud Run 會等不到有人 listen $PORT，部署直接失敗
ENV MCP_TRANSPORT=http

# shell form：$PORT 由 Cloud Run 在容器啟動時注入（不能寫死 8080）
CMD ["sh", "-c", "uv run server.py"]
