#!/bin/bash
# PostgreSQL 只读副本初始化：从主库 basebackup 并配置 primary_conninfo
# 由 docker-entrypoint-initdb.d 在副本容器首次启动时执行
set -e

PGDATA="${PGDATA:-/var/lib/postgresql/data}"
PRIMARY_HOST="postgres"
PRIMARY_PORT="5432"
REPL_USER="erp_replicator"
# 凭据一律来自环境变量注入，未设置时快速失败，避免空密码静默发起 basebackup
: "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD must be provided via environment}"
REPL_PASSWORD="${POSTGRES_PASSWORD}"
REPL_SLOT="erp_replica_slot"

echo "=== 检查副本是否已初始化 ==="
if [ -f "$PGDATA/postgresql.auto.conf" ] && [ -f "$PGDATA/standby.signal" ]; then
    echo "副本已初始化（存在 standby.signal），跳过 basebackup"
    exit 0
fi

echo "=== 从主库执行 basebackup ==="
# 清理可能残留的数据
rm -rf "$PGDATA"/*
mkdir -p "$PGDATA"
chmod 700 "$PGDATA"

# 使用 pg_basebackup 从主库拉取全量数据
# -R: 自动创建 standby.signal 和 primary_conninfo
# -S: 使用物理复制槽
# -C: 如果复制槽不存在则创建（容错）
PGPASSWORD="$REPL_PASSWORD" pg_basebackup \
    -h "$PRIMARY_HOST" \
    -p "$PRIMARY_PORT" \
    -U "$REPL_USER" \
    -D "$PGDATA" \
    -Fp -Xs -P -R \
    -S "$REPL_SLOT" \
    -C

echo "=== basebackup 完成，验证 standby 配置 ==="
if [ -f "$PGDATA/standby.signal" ]; then
    echo "standby.signal 已创建"
else
    echo "ERROR: standby.signal 未创建，副本可能无法进入热备模式"
    exit 1
fi

# 验证 primary_conninfo 已写入
if grep -q "primary_conninfo" "$PGDATA/postgresql.auto.conf" 2>/dev/null; then
    echo "primary_conninfo 已配置"
else
    echo "WARNING: primary_conninfo 未自动写入，手动追加"
    cat >> "$PGDATA/postgresql.auto.conf" <<EOF
primary_conninfo = 'host=${PRIMARY_HOST} port=${PRIMARY_PORT} user=${REPL_USER} password=${REPL_PASSWORD}'
EOF
fi

echo "=== 副本初始化完成 ==="
