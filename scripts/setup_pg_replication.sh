#!/bin/bash
# ============================================================
# PostgreSQL 流复制配置脚本 - ERP System
# 用于搭建主从复制（读写分离基础）
#
# 用法:
#   主库: sudo bash setup_pg_replication.sh primary
#   副库: sudo bash setup_pg_replication.sh replica <primary_host> <primary_port>
#
# 前置条件:
#   - PostgreSQL 15+ 已安装
#   - 以 root 或 postgres 用户运行
# ============================================================

set -euo pipefail

PG_DATA="${PG_DATA:-/var/lib/postgresql/15/main}"
PG_CONF="${PG_DATA}/postgresql.conf"
PG_HBA="${PG_DATA}/pg_hba.conf"
REPL_USER="repl_user"
REPL_PASSWORD="${REPL_PASSWORD:-$(openssl rand -base64 24)}"

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# ============================================================
# 主库配置
# ============================================================
setup_primary() {
    log_info "配置 PostgreSQL 主库 (Primary)..."

    # 1. 创建复制用户
    log_info "创建复制用户: ${REPL_USER}"
    sudo -u postgres psql -c "DROP ROLE IF EXISTS ${REPL_USER};" 2>/dev/null || true
    sudo -u postgres psql -c "CREATE ROLE ${REPL_USER} WITH REPLICATION LOGIN PASSWORD '${REPL_PASSWORD}';"

    # 2. 配置 postgresql.conf
    log_info "配置 postgresql.conf..."
    cat >> "${PG_CONF}" << 'EOF'

# ==================== 流复制配置 ====================
wal_level = replica
max_wal_senders = 5
wal_keep_size = 1024    # 保留 1GB WAL
hot_standby = on
synchronous_commit = on
EOF

    # 3. 配置 pg_hba.conf
    log_info "配置 pg_hba.conf..."
    cat >> "${PG_HBA}" << EOF

# ==================== 流复制认证 ====================
host    replication    ${REPL_USER}    0.0.0.0/0    scram-sha-256
EOF

    # 4. 重启 PostgreSQL
    log_info "重启 PostgreSQL..."
    systemctl restart postgresql

    log_info "主库配置完成！"
    log_info "复制用户密码 (请妥善保存): ${REPL_PASSWORD}"
    log_info "请在副库执行: sudo bash setup_pg_replication.sh replica $(hostname -I | awk '{print $1}') 5432"
}

# ============================================================
# 副库配置
# ============================================================
setup_replica() {
    local primary_host="$1"
    local primary_port="${2:-5432}"

    if [ -z "${primary_host}" ]; then
        log_error "缺少主库地址参数"
        echo "用法: sudo bash setup_pg_replication.sh replica <primary_host> <primary_port>"
        exit 1
    fi

    log_info "配置 PostgreSQL 副库 (Replica)..."
    log_info "主库地址: ${primary_host}:${primary_port}"

    # 1. 停止 PostgreSQL
    log_info "停止 PostgreSQL..."
    systemctl stop postgresql

    # 2. 清空数据目录
    log_info "清空数据目录..."
    rm -rf "${PG_DATA}"/*
    mkdir -p "${PG_DATA}"
    chown postgres:postgres "${PG_DATA}"
    chmod 700 "${PG_DATA}"

    # 3. 使用 pg_basebackup 初始化
    log_info "执行 pg_basebackup..."
    sudo -u postgres pg_basebackup \
        -h "${primary_host}" \
        -p "${primary_port}" \
        -U "${REPL_USER}" \
        -D "${PG_DATA}" \
        -Fp \
        -Xs \
        -P \
        -R

    # 4. 配置 hot_standby
    cat >> "${PG_CONF}" << 'EOF'

# ==================== 副库配置 ====================
hot_standby = on
hot_standby_feedback = on
EOF

    # 5. 启动 PostgreSQL
    log_info "启动 PostgreSQL..."
    systemctl start postgresql

    # 6. 验证
    log_info "验证复制状态..."
    sleep 3
    sudo -u postgres psql -c "SELECT * FROM pg_stat_replication;" 2>/dev/null || \
        log_warn "请在主库上执行: SELECT * FROM pg_stat_replication; 验证复制状态"

    log_info "副库配置完成！"
}

# ============================================================
# 主逻辑
# ============================================================
case "${1:-}" in
    primary)
        setup_primary
        ;;
    replica)
        setup_replica "${2:-}" "${3:-5432}"
        ;;
    *)
        echo "PostgreSQL 流复制配置脚本"
        echo ""
        echo "用法:"
        echo "  主库: sudo bash $0 primary"
        echo "  副库: sudo bash $0 replica <primary_host> [primary_port]"
        echo ""
        echo "环境变量:"
        echo "  PG_DATA       - PostgreSQL 数据目录 (默认: /var/lib/postgresql/15/main)"
        echo "  REPL_PASSWORD - 复制用户密码 (默认: 随机生成)"
        exit 1
        ;;
esac