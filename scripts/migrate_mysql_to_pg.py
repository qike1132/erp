"""数据迁移脚本: MySQL -> PostgreSQL (自动匹配列+类型转换)"""
import os

import psycopg2
import pymysql
from psycopg2.extras import execute_values

MYSQL_CONFIG = {
    'host': 'localhost',
    'port': 3306,
    'user': 'root',
    'password': os.environ.get('MYSQL_PASSWORD', ''),
    'database': 'erp_system',
}

PG_CONFIG = {
    'host': 'localhost',
    'port': 5432,
    'user': 'erp_app',
    'password': os.environ.get('DB_PASSWORD', ''),
    'dbname': 'erp_system',
}

MIGRATION_ORDER = [
    'product', 'customer', 'supplier', 'user', 'permission',
    'product_material', 'product_fabric', 'product_accessory', 'product_packaging',
    'order', 'stock_in', 'stock_out', 'inventory_log',
    'purchase_order', 'purchase_order_item',
    'staging_order', 'staging_stock_in', 'staging_stock_out',
    'approval_request', 'approval_log',
    'order_status_log', 'customer_access_log',
    'case', 'case_stock_in', 'case_stock_out', 'case_inventory_log',
    'material_registration', 'material_registration_item',
    'craft_work', 'packaging_record',
    'production_plan', 'production_plan_log', 'staging_purchase_plan',
    'purchase_plans', 'purchase_plan_details', 'shipment_records',
    'order_sync_record', 'order_sync_config', 'sync_retry_queue',
    'modification_log', 'saved_query',
    'user_permission',
]


def get_pg_columns(pg_cur, table_name):
    """获取 PG 表的列名和类型"""
    pg_cur.execute("""
        SELECT column_name, data_type, udt_name
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = %s
        ORDER BY ordinal_position
    """, (table_name,))
    return {row[0]: (row[1], row[2]) for row in pg_cur.fetchall()}


def convert_value(val, pg_type, udt_name):
    """将 MySQL 值转换为 PG 兼容类型"""
    if val is None:
        return None
    # MySQL tinyint(1) -> PG boolean
    if udt_name == 'bool':
        if isinstance(val, int):
            return bool(val)
        if isinstance(val, str):
            return val in ('1', 'true', 'True')
    # bytes -> str
    if isinstance(val, bytes):
        return val.decode('utf-8', errors='replace')
    return val


def migrate_table(mysql_cur, pg_cur, pg_conn, table_name):
    """迁移单张表"""
    # 获取 PG 列信息
    pg_cols = get_pg_columns(pg_cur, table_name)
    if not pg_cols:
        print(f'  {table_name}: not in PG (skip)')
        return 0

    # 获取 MySQL 行数
    mysql_cur.execute(f'SELECT COUNT(*) FROM `{table_name}`')
    mysql_count = mysql_cur.fetchone()[0]
    if mysql_count == 0:
        print(f'  {table_name}: 0 rows (skip)')
        return 0

    # 获取 MySQL 列名，只取 PG 中也存在的列
    mysql_cur.execute(f'SELECT * FROM `{table_name}` LIMIT 0')
    mysql_columns = [desc[0] for desc in mysql_cur.description]
    common_cols = [c for c in mysql_columns if c in pg_cols]

    if not common_cols:
        print(f'  {table_name}: no common columns (skip)')
        return 0

    skipped_cols = set(mysql_columns) - set(common_cols)
    if skipped_cols:
        print(f'  {table_name}: skipping MySQL-only columns: {skipped_cols}')

    col_list = ', '.join(f'"{c}"' for c in common_cols)
    col_types = {c: pg_cols[c] for c in common_cols}

    # 分批读取
    batch_size = 2000
    select_cols = ', '.join(f'`{c}`' for c in common_cols)
    mysql_cur.execute(f'SELECT {select_cols} FROM `{table_name}`')
    total_migrated = 0

    while True:
        rows = mysql_cur.fetchmany(batch_size)
        if not rows:
            break

        # 转换数据
        converted = []
        for row in rows:
            converted_row = []
            for i, val in enumerate(row):
                col_name = common_cols[i]
                pg_type, udt_name = col_types[col_name]
                converted_row.append(convert_value(val, pg_type, udt_name))
            converted.append(tuple(converted_row))

        # 批量插入 PG (ON CONFLICT DO NOTHING)
        insert_sql = f'INSERT INTO "{table_name}" ({col_list}) VALUES %s ON CONFLICT DO NOTHING'
        try:
            execute_values(pg_cur, insert_sql, converted, page_size=batch_size)
            pg_conn.commit()
            total_migrated += len(rows)
        except Exception as e:
            pg_conn.rollback()
            print(f'  {table_name}: batch error - {e}')
            # Try row by row
            for row_data in converted:
                try:
                    single_insert = f'INSERT INTO "{table_name}" ({col_list}) VALUES ({",".join(["%s"]*len(common_cols))}) ON CONFLICT DO NOTHING'
                    pg_cur.execute(single_insert, row_data)
                    pg_conn.commit()
                    total_migrated += 1
                except Exception:
                    pg_conn.rollback()

    # 验证
    pg_cur.execute(f'SELECT COUNT(*) FROM "{table_name}"')
    pg_count = pg_cur.fetchone()[0]
    print(f'  {table_name}: MySQL={mysql_count} -> PG={pg_count} (migrated={total_migrated})')
    return total_migrated


def sync_sequences(pg_cur, pg_conn):
    """同步 PG 序列值到各表最大 ID"""
    pg_cur.execute("""
        SELECT table_name, column_name
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND column_default LIKE 'nextval%%'
    """)
    for table_name, col_name in pg_cur.fetchall():
        pg_cur.execute(f'SELECT MAX("{col_name}") FROM "{table_name}"')
        max_id = pg_cur.fetchone()[0]
        if max_id:
            pg_cur.execute(f"""
                SELECT pg_get_serial_sequence('"{table_name}"', '{col_name}')
            """)
            seq_row = pg_cur.fetchone()
            if seq_row and seq_row[0]:
                seq_name = seq_row[0]
                pg_cur.execute(f"SELECT setval('{seq_name}', {max_id})")
    pg_conn.commit()
    print('Sequences synced')


def main():
    print('=== MySQL -> PostgreSQL 数据迁移 ===\n')

    mysql_conn = pymysql.connect(**MYSQL_CONFIG)
    mysql_cur = mysql_conn.cursor()

    pg_conn = psycopg2.connect(**PG_CONFIG)
    pg_cur = pg_conn.cursor()

    # 不需要禁用外键：ON CONFLICT DO NOTHING + 按依赖顺序插入已足够

    total = 0
    for table in MIGRATION_ORDER:
        try:
            total += migrate_table(mysql_cur, pg_cur, pg_conn, table)
        except Exception as e:
            print(f'  {table}: ERROR - {e}')
            pg_conn.rollback()

    # 恢复外键检查（无需操作）

    # 同步序列
    print('\n同步序列值...')
    sync_sequences(pg_cur, pg_conn)

    # 验证
    print('\n=== 验证行数 ===')
    mysql_cur.execute('SHOW TABLES')
    tables = [row[0] for row in mysql_cur.fetchall()]
    mismatches = 0
    ok_count = 0
    for table in sorted(tables):
        if table in ('alembic_version', 'country_config', 'lifecycle_log',
                      'navigation_module', 'sku_batch', 'unprocessed_order'):
            continue  # MySQL 旧表，PG 不需要
        mysql_cur.execute(f'SELECT COUNT(*) FROM `{table}`')
        mc = mysql_cur.fetchone()[0]
        try:
            pg_cur.execute(f'SELECT COUNT(*) FROM "{table}"')
            pc = pg_cur.fetchone()[0]
        except Exception:
            pc = -1
        status = 'OK' if mc == pc else f'MISMATCH ({mc} vs {pc})'
        if mc == pc:
            ok_count += 1
        else:
            mismatches += 1
        if mc > 0 or (pc > 0 if isinstance(pc, int) else False):
            print(f'  {table}: MySQL={mc}, PG={pc} [{status}]')

    print(f'\n总计迁移: {total} rows, 一致: {ok_count} 表, 不一致: {mismatches} 表')

    mysql_cur.close()
    mysql_conn.close()
    pg_cur.close()
    pg_conn.close()


if __name__ == '__main__':
    main()
