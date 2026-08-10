"""执行迁移 023 和验证"""
import sys
sys.path.insert(0, r'd:\erp_system')
from fastapi_app.core.database import get_sync_engine

e = get_sync_engine()
with e.connect() as conn:
    # 1. 查看当前版本
    rows = conn.exec_driver_sql("SELECT * FROM alembic_version").fetchall()
    print('当前 alembic_version:', rows)

    # 2. 执行迁移 023 的 SQL
    # 添加 status 列
    conn.exec_driver_sql(
        "ALTER TABLE customer_sampling_project "
        "ADD COLUMN IF NOT EXISTS status VARCHAR(20) NOT NULL DEFAULT 'in_progress'"
    )
    conn.commit()
    print('已添加 status 列')

    # 3. 数据迁移
    conn.exec_driver_sql(
        "UPDATE customer_sampling_project SET status = 'completed' WHERE is_archived = true"
    )
    conn.commit()
    print('数据迁移完成: is_archived=true → status=completed')

    # 4. CHECK 约束
    try:
        conn.exec_driver_sql(
            "ALTER TABLE customer_sampling_project ADD CONSTRAINT ck_csp_status_valid "
            "CHECK (status IN ('in_progress', 'completed', 'cancelled'))"
        )
        conn.commit()
        print('CHECK 约束已添加')
    except Exception as exc:
        print(f'CHECK 约束可能已存在: {exc}')

    # 5. 更新 alembic_version
    conn.exec_driver_sql(
        "UPDATE alembic_version SET version_num = 'pg_standalone_023_add_status'"
    )
    conn.commit()
    print('已 stamp 到 pg_standalone_023_add_status')

# 验证
with e.connect() as conn:
    cols = conn.exec_driver_sql(
        "SELECT column_name, column_default FROM information_schema.columns "
        "WHERE table_name='customer_sampling_project' AND column_name IN ('status', 'is_archived')"
    ).fetchall()
    print('\n验证列:')
    for c in cols:
        print(f'  {c[0]}: default={c[1]}')

    # 抽样
    sample = conn.exec_driver_sql(
        "SELECT id, is_archived, status FROM customer_sampling_project LIMIT 3"
    ).fetchall()
    print('\n抽样数据:')
    for s in sample:
        print(f'  id={s[0]}, is_archived={s[1]}, status={s[2]}')

    status_counts = conn.exec_driver_sql(
        "SELECT status, count(*) FROM customer_sampling_project GROUP BY status"
    ).fetchall()
    print('\n状态分布:')
    for sc in status_counts:
        print(f'  {sc[0]}: {sc[1]}')

print('\n迁移 023 完成')
