#!/bin/bash
# PostgreSQL 主库初始化：创建流复制用户
# 仅在首次初始化（data 目录为空）时由 docker-entrypoint-initdb.d 执行
set -e

echo "=== 创建流复制用户 ==="
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    -- 创建复制用户（密码从环境变量读取，默认与业务用户同密码，生产环境应独立设置）
    DO \$\$
    BEGIN
        IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'erp_replicator') THEN
            CREATE ROLE erp_replicator WITH REPLICATION LOGIN PASSWORD '${POSTGRES_PASSWORD}';
            RAISE NOTICE '已创建流复制用户 erp_replicator';
        ELSE
            RAISE NOTICE '流复制用户 erp_replicator 已存在，跳过';
        END IF;
    END
    \$\$;

    -- 创建只读用户（供副本对外服务）
    DO \$\$
    BEGIN
        IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'erp_readonly') THEN
            CREATE ROLE erp_readonly LOGIN PASSWORD '${POSTGRES_PASSWORD}';
            RAISE NOTICE '已创建只读用户 erp_readonly';
        ELSE
            RAISE NOTICE '只读用户 erp_readonly 已存在，跳过';
        END IF;
    END
    \$\$;

    -- 授予 erp_readonly 对业务表的只读权限（后续由应用迁移补充 GRANT）
    GRANT USAGE ON SCHEMA public TO erp_readonly;
    ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO erp_readonly;
EOSQL

echo "=== 创建物理复制槽 ==="
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    -- 创建物理复制槽（IF NOT EXISTS 不支持 pg_create_physical_replication_slot，用 DO 块）
    DO \$\$
    BEGIN
        IF NOT EXISTS (SELECT FROM pg_replication_slots WHERE slot_name = 'erp_replica_slot') THEN
            PERFORM pg_create_physical_replication_slot('erp_replica_slot');
            RAISE NOTICE '已创建物理复制槽 erp_replica_slot';
        ELSE
            RAISE NOTICE '物理复制槽 erp_replica_slot 已存在，跳过';
        END IF;
    END
    \$\$;
EOSQL

echo "=== 主库复制配置完成 ==="
