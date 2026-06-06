#!/usr/bin/env bash
# ============================================================
# PostgreSQL 只读副本配置脚本
# 用途：在主库上配置流复制，在副本上配置 hot standby
# 前置条件：
#   - 主库和副本已安装相同版本的 PostgreSQL
#   - 主库已启用 WAL 归档或 WAL keep segments
#   - 网络互通
# ============================================================
set -euo pipefail

PRIMARY_HOST="${PRIMARY_HOST:-127.0.0.1}"
PRIMARY_PORT="${PRIMARY_PORT:-5432}"
REPLICA_HOST="${REPLICA_HOST:-127.0.0.1}"
REPLICA_PORT="${REPLICA_PORT:-5433}"
REPLICA_USER="${REPLICA_USER:-erp_replication}"
DB_NAME="${DB_NAME:-erp_system}"
PG_DATA_PRIMARY="/var/lib/postgresql/data"
PG_DATA_REPLICA="/var/lib/postgresql/replica_data"

echo "=== PostgreSQL 只读副本配置 ==="

# ---- 步骤1: 主库配置 ----
echo "[1/5] 配置主库 postgresql.auto.conf ..."

# 在主库上设置复制参数
psql -h "$PRIMARY_HOST" -p "$PRIMARY_PORT" -U postgres -d postgres <<SQL
ALTER SYSTEM SET wal_level = replica;
ALTER SYSTEM SET max_wal_senders = 10;
ALTER SYSTEM SET max_replication_slots = 10;
ALTER SYSTEM SET wal_keep_size = '256MB';
ALTER SYSTEM SET hot_standby = on;
SQL

echo "[1/5] 创建复制用户 ..."
psql -h "$PRIMARY_HOST" -p "$PRIMARY_PORT" -U postgres -d postgres <<SQL
DO \$\$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '${REPLICA_USER}') THEN
    CREATE ROLE ${REPLICA_USER} WITH REPLICATION LOGIN PASSWORD '${REPLICA_PASSWORD:-changeme}';
  END IF;
END
\$\$;
SQL

echo "[1/5] 配置 pg_hba.conf 允许复制连接 ..."
PG_HBA_ENTRY="host    replication     ${REPLICA_USER}     ${REPLICA_HOST}/32    md5"
PG_HBA_FILE="${PG_DATA_PRIMARY}/pg_hba.conf"
if ! grep -qF "$PG_HBA_ENTRY" "$PG_HBA_FILE" 2>/dev/null; then
  echo "$PG_HBA_ENTRY" >> "$PG_HBA_FILE"
  echo "  已添加复制规则到 pg_hba.conf"
else
  echo "  pg_hba.conf 已包含复制规则，跳过"
fi

echo "[1/5] 重启主库使配置生效 ..."
echo "  请手动执行: systemctl restart postgresql"

# ---- 步骤2: 创建复制槽 ----
echo "[2/5] 在主库创建复制槽 ..."
psql -h "$PRIMARY_HOST" -p "$PRIMARY_PORT" -U postgres -d postgres <<SQL
SELECT pg_create_physical_replication_slot('erp_replica_slot', true)
  WHERE NOT EXISTS (
    SELECT 1 FROM pg_replication_slots WHERE slot_name = 'erp_replica_slot'
  );
SQL

# ---- 步骤3: 基础备份 ----
echo "[3/5] 从主库创建基础备份 ..."
echo "  在副本服务器上执行:"
echo "  pg_basebackup -h ${PRIMARY_HOST} -p ${PRIMARY_PORT} -U ${REPLICA_USER} -D ${PG_DATA_REPLICA} -Fp -Xs -P -R"
echo "  -R 参数会自动创建 standby.signal 和 postgresql.auto.conf"

# ---- 步骤4: 副库配置 ----
echo "[4/5] 配置副本 postgresql.auto.conf ..."
echo "  在副本服务器 ${PG_DATA_REPLICA}/postgresql.auto.conf 中添加:"
cat <<'CONF'
primary_conninfo = 'host=PRIMARY_HOST port=5432 user=erp_replication password=changeme dbname=erp_system'
primary_slot_name = 'erp_replica_slot'
hot_standby = on
port = 5433
CONF

# ---- 步骤5: 验证 ----
echo "[5/5] 验证复制状态（在主库执行）:"
echo "  psql -U postgres -c 'SELECT * FROM pg_stat_replication;'"
echo ""
echo "=== 配置完成 ==="
echo "副本连接信息:"
echo "  host: ${REPLICA_HOST}"
echo "  port: ${REPLICA_PORT}"
echo "  dbname: ${DB_NAME}"
echo ""
echo "应用端 .env 配置:"
echo "  ASYNC_DATABASE_REPLICA_URL=postgresql+asyncpg://erp_app:PASSWORD@${REPLICA_HOST}:${REPLICA_PORT}/${DB_NAME}"
