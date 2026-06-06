#!/usr/bin/env bash
# ============================================================
# PostgreSQL 主从切换演练脚本
# 用途：模拟主库故障，验证应用自动重连和副本提升流程
# 前置条件：
#   - 主库和只读副本已配置流复制
#   - 应用已配置 ASYNC_DATABASE_REPLICA_URL
#   - 有 superuser 权限操作 PostgreSQL
# ============================================================
set -euo pipefail

PRIMARY_HOST="${PRIMARY_HOST:-127.0.0.1}"
PRIMARY_PORT="${PRIMARY_PORT:-5432}"
REPLICA_HOST="${REPLICA_HOST:-127.0.0.1}"
REPLICA_PORT="${REPLICA_PORT:-5433}"
APP_HEALTH_URL="${APP_HEALTH_URL:-http://127.0.0.1:5002/api/health/db}"
DB_USER="${DB_USER:-postgres}"
DB_NAME="${DB_NAME:-erp_system}"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

echo "============================================================"
echo "  PostgreSQL 主从切换演练"
echo "============================================================"
echo ""

# ---- 步骤1: 检查初始状态 ----
log_info "[1/7] 检查初始复制状态 ..."
REPLICATION_STATUS=$(psql -h "$PRIMARY_HOST" -p "$PRIMARY_PORT" -U "$DB_USER" -d "$DB_NAME" -t -c \
  "SELECT client_addr, state, sent_lsn, replay_lsn, (sent_lsn = replay_lsn) AS in_sync FROM pg_stat_replication LIMIT 1;" 2>/dev/null || echo "FAILED")

if echo "$REPLICATION_STATUS" | grep -q "streaming"; then
  log_info "复制状态正常: $REPLICATION_STATUS"
else
  log_error "复制状态异常，请先配置只读副本"
  exit 1
fi

# ---- 步骤2: 验证应用健康 ----
log_info "[2/7] 验证应用健康检查 ..."
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "$APP_HEALTH_URL" 2>/dev/null || echo "000")
if [ "$HTTP_CODE" = "200" ]; then
  log_info "应用健康检查通过 (HTTP $HTTP_CODE)"
else
  log_error "应用健康检查失败 (HTTP $HTTP_CODE)"
  exit 1
fi

# ---- 步骤3: 模拟主库故障 ----
log_warn "[3/7] 模拟主库故障（停止主库）..."
log_warn "  命令: pg_ctl stop -D /var/lib/postgresql/data -m fast"
log_warn "  或: systemctl stop postgresql"
echo ""
read -p "  是否已手动停止主库？(y/N) " CONFIRM
if [ "$CONFIRM" != "y" ]; then
  log_info "演练中止"
  exit 0
fi

# ---- 步骤4: 验证应用降级 ----
log_info "[4/7] 验证应用降级行为 ..."
sleep 5
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "$APP_HEALTH_URL" 2>/dev/null || echo "000")
if [ "$HTTP_CODE" = "503" ] || [ "$HTTP_CODE" = "500" ]; then
  log_warn "应用检测到主库故障 (HTTP $HTTP_CODE) - 符合预期"
elif [ "$HTTP_CODE" = "200" ]; then
  log_info "应用仍健康 (HTTP $HTTP_CODE) - 写操作走副本降级成功"
else
  log_warn "应用响应码: $HTTP_CODE"
fi

# ---- 步骤5: 提升副本为新主库 ----
log_warn "[5/7] 提升副本为新主库 ..."
log_warn "  在副本服务器执行: pg_ctl promote -D /var/lib/postgresql/replica_data"
echo ""
read -p "  是否已手动提升副本？(y/N) " CONFIRM
if [ "$CONFIRM" != "y" ]; then
  log_info "演练中止，请手动恢复主库"
  exit 0
fi

# ---- 步骤6: 更新应用连接并验证 ----
log_info "[6/7] 验证应用重连 ..."
sleep 5

# 重建连接池
log_info "  触发应用连接池重建: POST /api/health/db/rebuild-pool"
REBUILD_CODE=$(curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:5002/api/health/db/rebuild-pool" 2>/dev/null || echo "000")
log_info "  连接池重建响应: HTTP $REBUILD_CODE"

sleep 3
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "$APP_HEALTH_URL" 2>/dev/null || echo "000")
if [ "$HTTP_CODE" = "200" ]; then
  log_info "应用已恢复 (HTTP $HTTP_CODE)"
else
  log_error "应用未恢复 (HTTP $HTTP_CODE)，需检查连接配置"
fi

# ---- 步骤7: 验证数据完整性 ----
log_info "[7/7] 验证数据完整性 ..."
RECORD_COUNT=$(psql -h "$REPLICA_HOST" -p "$REPLICA_PORT" -U "$DB_USER" -d "$DB_NAME" -t -c \
  "SELECT count(*) FROM \"order\" WHERE is_deleted IS NOT TRUE;" 2>/dev/null | xargs || echo "QUERY_FAILED")
log_info "新主库订单记录数: $RECORD_COUNT"

echo ""
echo "============================================================"
echo "  演练完成"
echo "============================================================"
echo ""
log_warn "后续步骤："
echo "  1. 配置旧主库为新副本（反向流复制）"
echo "  2. 更新 .env 中 DB_HOST/DB_PORT 指向新主库"
echo "  3. 更新 ASYNC_DATABASE_REPLICA_URL 指向新副本"
echo "  4. 重启应用使新配置生效"
echo ""
log_info "切换耗时统计:"
echo "  主库停止 → 副本提升 → 应用恢复: 请记录实际耗时"
echo "  目标: 全流程 < 5分钟"
