#!/bin/sh
# 容器入口：启动即完成数据库初始化（建表）与数据目录准备，然后运行服务。
set -e

export DATABASE_PATH="${DATABASE_PATH:-/data/secret_santa.db}"
export STATIC_DIR="${STATIC_DIR:-/app/static}"
export DATABASE_URL="${DATABASE_URL:-sqlite:///${DATABASE_PATH}}"

mkdir -p "$(dirname "$DATABASE_PATH")"

echo "[entrypoint] 初始化数据库: $DATABASE_URL"
# 显式执行一次建表，幂等；表已存在时跳过
python -c "from app.database import init_db; init_db(); print('[entrypoint] 数据库就绪')"

PORT="${PORT:-8000}"
echo "[entrypoint] 启动服务，监听 0.0.0.0:${PORT}"
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT}"
