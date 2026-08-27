# Lab 9 的 hotel_service（to_a2a 版）→ Cloud Run。複製成 .build/a2a/Dockerfile。
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY . .

RUN adduser --disabled-password --gecos "" app && chown -R app /app
USER app

# Lab 9 的 to_a2a(host=, port=, protocol=) 只影響「名片上寫的網址」，不是 listen 的 port
# （listen 的是下面 uvicorn 的 --port $PORT）。Cloud Run 對外一律 443，名片得寫真 https 網址：
#   1. 先部署一次拿到網址
#   2. gcloud run services update hotel-a2a --set-env-vars A2A_PUBLIC_HOST=hotel-a2a-xxx.run.app
#   3. Lab 9 的 agent.py 要讀 A2A_PUBLIC_HOST 才有用 —— 改法見 walkthrough 步驟 3
#
# ⚠️ 未實測：模組路徑寫的是 Lab 9 的 hotel_service.agent:a2a_app，
#   若你的 Lab 9 目錄結構不同，改這一行就好。
CMD ["sh", "-c", "uv run uvicorn hotel_service.agent:a2a_app --host 0.0.0.0 --port ${PORT:-8080}"]
