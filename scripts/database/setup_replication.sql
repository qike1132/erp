-- Create replication user for streaming replication
DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'replicator') THEN
    CREATE ROLE replicator WITH REPLICATION LOGIN PASSWORD 'ERP_Replication_2026_Secure';
  END IF;
END
$$;

-- Create read-only user for application read replica access
DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'erp_readonly') THEN
    CREATE ROLE erp_readonly WITH LOGIN PASSWORD 'ERP_ReadOnly_2026_Secure';
  END IF;
END
$$;

-- Grant read-only permissions
GRANT CONNECT ON DATABASE erp_system TO erp_readonly;
GRANT USAGE ON SCHEMA public TO erp_readonly;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO erp_readonly;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO erp_readonly;
