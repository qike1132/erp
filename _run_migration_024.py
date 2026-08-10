"""执行迁移 024：customer_sampling_part 加 version_no 列"""
import sys
sys.path.insert(0, r'd:\erp_system')
from fastapi_app.core.database import get_sync_engine

e = get_sync_engine()
with e.connect() as conn:
    # 1. 添加 version_no 列
    conn.exec_driver_sql(
        "ALTER TABLE customer_sampling_part "
        "ADD COLUMN IF NOT EXISTS version_no VARCHAR(8) NOT NULL DEFAULT 'T1'"
    )
    conn.commit()
    print('已添加 version_no 列')

    # 2. 删除旧索引（仅 name 不含 version_no）
    try:
        conn.exec_driver_sql('DROP INDEX IF EXISTS idx_csp_part_name')
        conn.commit()
        print('已删除旧索引 idx_csp_part_name')
    except Exception as exc:
        print(f'删除旧索引（可忽略）: {exc}')

    # 3. 创建新索引（含 version_no）
    try:
        conn.exec_driver_sql(
            'CREATE INDEX IF NOT EXISTS idx_csp_part_name_version '
            'ON customer_sampling_part (project_id, version_no, part_name)'
        )
        conn.commit()
        print('已创建新索引 idx_csp_part_name_version')
    except Exception as exc:
        print(f'创建新索引（可忽略）: {exc}')

# 验证
with e.connect() as conn:
    cols = conn.exec_driver_sql(
        "SELECT column_name, column_default FROM information_schema.columns "
        "WHERE table_name='customer_sampling_part' AND column_name='version_no'"
    ).fetchall()
    print(f'\n列验证: {cols}')

    sample = conn.exec_driver_sql(
        'SELECT id, part_name, version_no FROM customer_sampling_part LIMIT 3'
    ).fetchall()
    print(f'抽样数据: {sample}')

    count = conn.exec_driver_sql(
        "SELECT version_no, count(*) FROM customer_sampling_part GROUP BY version_no"
    ).fetchall()
    print(f'版本分布: {count}')

print('\n迁移 024 完成')
