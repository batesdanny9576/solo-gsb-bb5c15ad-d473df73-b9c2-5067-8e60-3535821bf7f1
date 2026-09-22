# syntax=docker/dockerfile:1

# ---- 阶段 1：构建 React 前端 ----
FROM node:20-alpine AS frontend
WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci || npm install
COPY frontend/ ./
RUN npm run build

# ---- 阶段 2：Python 后端 + 前端产物 ----
FROM python:3.11-slim
WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    STATIC_DIR=/app/static \
    DATABASE_PATH=/data/secret_santa.db \
    DATABASE_URL=sqlite:////data/secret_santa.db \
    PORT=8000

COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./
COPY --from=frontend /build/frontend/dist ./static

RUN chmod +x ./entrypoint.sh && mkdir -p /data
VOLUME ["/data"]

EXPOSE 8000
ENTRYPOINT ["./entrypoint.sh"]
