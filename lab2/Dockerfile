# Cloud Run 用這個 Dockerfile build。有 Dockerfile 時 `gcloud run deploy --source .`
# 就不會走 buildpacks（buildpacks 找不到 requirements.txt 會直接失敗，而本課不用 requirements.txt）。
FROM python:3.13-slim
COPY --from=ghcr.io/astral-sh/uv:0.12.3 /uv /bin/uv
WORKDIR /app

# 先只複製依賴清單：改 app.py 時這層 cache 還在，重 build 快很多
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev

COPY app.py ./
ENV PORT=8080
EXPOSE 8080
# --no-sync：容器內不要再解一次依賴（沒網路權限也不該再解）
CMD ["uv", "run", "--no-sync", "app.py"]
