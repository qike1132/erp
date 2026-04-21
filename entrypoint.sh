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

# 启动 FastAPI 服务 (前台主进程)
echo "[INFO] 正在启动 FastAPI 服务 (端口 5002)..."
exec uvicorn fastapi_app.main:app \
    --host 0.0.0.0 \
    --port 5002 \
    --workers 1 \
    --log-level info
