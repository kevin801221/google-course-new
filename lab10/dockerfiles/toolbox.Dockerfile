# Lab 8 的 tools.yaml → Cloud Run。deploy.sh 會複製成 .build/toolbox/Dockerfile。
#
# ⚠️ 未實測：官方 image 路徑與旗標名稱以 mcp-toolbox.dev 文件為準，我沒有 GCP 帳號可驗。
#   若 pull 不到，改成從 GitHub release 抓 binary（見下方註解的備案）。
FROM us-central1-docker.pkg.dev/database-toolbox/toolbox/toolbox:latest

# tools.yaml 就是 API 契約：SQL 寫死在檔案裡，模型只能填參數。
# 密碼用 ${DB_PASSWORD} 佔位，由 Cloud Run 的 --set-secrets 注入 —— 不進 image。
COPY tools.yaml /app/tools.yaml

# Cloud Run 預設把流量送到容器的 8080；toolbox 預設只聽 127.0.0.1，
# 不改 --address 0.0.0.0 的話健康檢查連不上 → 部署卡在 "failed to start and listen"
#
# 這裡的 8080 是唯一一個「刻意寫死」的 port：官方 image 的 ENTRYPOINT 就是那支 Go binary，
# CMD 只能給它旗標，沒有 shell 可以展開 $PORT。所以改用另一邊對齊 ——
# gcloud run deploy 的 --port 預設就是 8080，兩邊寫死同一個數字，容器與前端才對得上。
# 要改 port 就兩邊一起改（這裡的 --port 與 gcloud run deploy --port）。
CMD ["--config", "/app/tools.yaml", "--address", "0.0.0.0", "--port", "8080"]

# 備案（官方 image 換路徑時用）：
# FROM debian:bookworm-slim
# RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl \
#     && rm -rf /var/lib/apt/lists/*
# ARG TOOLBOX_VERSION=latest
# RUN curl -fsSL -o /usr/local/bin/toolbox \
#     "https://storage.googleapis.com/genai-toolbox/v${TOOLBOX_VERSION}/linux/amd64/toolbox" \
#     && chmod +x /usr/local/bin/toolbox
# COPY tools.yaml /app/tools.yaml
# ENTRYPOINT ["/usr/local/bin/toolbox"]
# CMD ["--config", "/app/tools.yaml", "--address", "0.0.0.0", "--port", "8080"]
