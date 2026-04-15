#!/bin/bash
set -e

echo "=================================================="
echo "ERP系统启动中..."
echo "=================================================="

# 等待 MySQL 就绪
echo "[INFO] 等待数据库就绪..."
for i in $(seq 1 30); do
    if python -c "import pymysql; pymysql.connect(host='${DB_HOST:-db}', port=int('${DB_PORT:-3306}'), user='${DB_USER:-root}', password='${DB_PASSWORD:-}', database='${DB_NAME:-erp_system}')" 2>/dev/null; then
        echo "[OK] 数据库连接成功"
        break
    fi
    if [ "$i" -eq 30 ]; then
        echo "[WARN] 数据库连接超时，继续启动..."
    fi
    sleep 2
done

# 启动 FastAPI 服务 (后台)
echo "[INFO] 正在启动 FastAPI 服务 (端口 5002)..."
uvicorn fastapi_app.main:app \
    --host 0.0.0.0 \
    --port 5002 \
    --workers 1 \
    --log-level info \
    >> /app/logs/fastapi.log 2>&1 &
FASTAPI_PID=$!
echo "[OK] FastAPI 服务已启动 (PID: $FASTAPI_PID)"

# 等待 FastAPI 就绪
echo "[INFO] 等待 FastAPI 服务就绪..."
for i in $(seq 1 15); do
    if python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5002/api/health')" 2>/dev/null; then
        echo "[OK] FastAPI 服务就绪"
        break
    fi
    if [ "$i" -eq 15 ]; then
        echo "[WARN] FastAPI 服务就绪检查超时，继续启动 Flask..."
    fi
    sleep 2
done

# 启动 Flask 服务 (前台，作为主进程)
echo "[INFO] 正在启动 Flask 服务 (端口 5003)..."
exec gunicorn \
    --bind 0.0.0.0:5003 \
    --workers 4 \
    --timeout 120 \
    --access-logfile /app/logs/access.log \
    --error-logfile /app/logs/error.log \
    run:app
