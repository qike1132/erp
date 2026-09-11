-- Create replication user for streaming replication
-- 密码经 psql 变量注入（禁止硬编码）：
--   psql -v POSTGRES_PASSWORD=... -v READONLY_PASSWORD=... -f setup_replication.sql
-- 注：psql 变量在 $$美元引号$$ 内不插值，故用 \gexec 拼接执行
SELECT 'CREATE ROLE replicator WITH REPLICATION LOGIN PASSWORD ' || quote_literal(:'POSTGRES_PASSWORD')
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'replicator') \gexec

-- Create read-only user for application read replica access
SELECT 'CREATE ROLE erp_readonly WITH LOGIN PASSWORD ' || quote_literal(:'READONLY_PASSWORD')
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'erp_readonly') \gexec

-- Grant read-only permissions
GRANT CONNECT ON DATABASE erp_system TO erp_readonly;
GRANT USAGE ON SCHEMA public TO erp_readonly;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO erp_readonly;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO erp_readonly;
