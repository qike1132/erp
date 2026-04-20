#!/bin/bash
# ============================================================================
# ERP System - 数据库权限降级脚本
# 创建受限应用用户，替代 root 直连，遵循最小权限原则
# 适用：MySQL 8.0+ / Docker docker-entrypoint-initdb.d
#
# Docker initdb 会自动执行 .sh 文件，shell 变量替换正常工作。
# ============================================================================

set -e

# 等待 MySQL 就绪
until mysqladmin ping -h localhost --silent 2>/dev/null; do
    sleep 1
done

# 密码来源：环境变量，未设置则使用与 root 相同的密码
# 注意：密码不能包含单引号(')，否则会导致 SQL 语法错误
APP_PASSWORD="${DB_APP_PASSWORD:-${DB_PASSWORD}}"
MONITOR_PASSWORD="${DB_MONITOR_PASSWORD:-${DB_PASSWORD}}"

# 转义密码中的特殊字符（单引号在 SQL 中用 \' 转义）
APP_PASSWORD_ESCAPED=$(printf '%s' "$APP_PASSWORD" | sed "s/'/\\\\'/g")
MONITOR_PASSWORD_ESCAPED=$(printf '%s' "$MONITOR_PASSWORD" | sed "s/'/\\\\'/g")

mysql -u root -p"${MYSQL_ROOT_PASSWORD}" <<SQL
-- 1. 创建应用用户（日常运行：Flask + FastAPI + Celery Worker）
CREATE USER IF NOT EXISTS 'erp_app'@'%' IDENTIFIED BY '${APP_PASSWORD_ESCAPED}';

-- 2. 授予 DML 权限（日常运行所需）
GRANT SELECT, INSERT, UPDATE, DELETE ON erp_system.* TO 'erp_app'@'%';

-- 3. 授予视图权限（SHOW TABLES, SHOW COLUMNS 等）
GRANT SHOW VIEW ON erp_system.* TO 'erp_app'@'%';

-- 4. 授予执行权限（stored procedures 如果有）
GRANT EXECUTE ON erp_system.* TO 'erp_app'@'%';

-- 5. 刷新权限
FLUSH PRIVILEGES;

-- 6. 创建监控用户（Prometheus mysqld-exporter）
CREATE USER IF NOT EXISTS 'erp_monitor'@'%' IDENTIFIED BY '${MONITOR_PASSWORD_ESCAPED}';
GRANT PROCESS, REPLICATION CLIENT, SELECT ON *.* TO 'erp_monitor'@'%';
FLUSH PRIVILEGES;
SQL

echo "数据库用户创建完成: erp_app, erp_monitor"
