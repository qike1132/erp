#!/usr/bin/env bash
# Celery Flower 监控面板启动脚本
# 用法: bash scripts/celery/start_flower.sh [--port 5555] [--basic-auth user:pass]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

cd "$PROJECT_ROOT"

PORT="${FLOWER_PORT:-5555}"
BASIC_AUTH="${FLOWER_BASIC_AUTH:-}"
BROKER_API="${FLOWER_BROKER_API:-}"

ARGS=(
    --port="$PORT"
    --persistent=True
    --db="flower_db.sqlite"
    --max_tasks=10000
    --max_workers=100
)

if [ -n "$BASIC_AUTH" ]; then
    ARGS+=(--basic-auth="$BASIC_AUTH")
fi

if [ -n "$BROKER_API" ]; then
    ARGS+=(--broker-api="$BROKER_API")
fi

echo "Starting Celery Flower on port $PORT..."
exec celery -A fastapi_app.core.celery_app:celery_app flower "${ARGS[@]}"
