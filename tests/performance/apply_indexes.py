#!/usr/bin/env python3
"""
应用数据库索引 - 执行模型变更中新增的数据库索引
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

import psycopg

from fastapi_app.core.config import settings

INDEXES = [
    {
        "name": "idx_ppd_barcode",
        "table": "purchase_plan_details",
        "column": "barcode",
        "sql": "CREATE INDEX IF NOT EXISTS idx_ppd_barcode ON purchase_plan_details (barcode);",
    },
    {
        "name": "idx_sr_customer_name",
        "table": "shipment_records",
        "column": "customer_name",
        "sql": "CREATE INDEX IF NOT EXISTS idx_sr_customer_name ON shipment_records (customer_name);",
    },
]


def get_conn():
    url = settings.ASYNC_DATABASE_URL.replace("+asyncpg", "")
    return psycopg.connect(url)


def main():
    print("=" * 60)
    print("数据库索引应用脚本")
    print("=" * 60)

    with get_conn() as conn:
        with conn.cursor() as cur:
            # 确认表数据量
            print("\n当前表数据量:")
            for idx_info in INDEXES:
                cur.execute(f"SELECT COUNT(*) FROM {idx_info['table']}")
                count = cur.fetchone()[0]
                print(f"  - {idx_info['table']}: {count:,} 条")

            print("\n开始创建索引...")
            for idx_info in INDEXES:
                idx_name = idx_info["name"]
                print(f"\n  -> 创建索引 {idx_name} on {idx_info['table']}({idx_info['column']})")

                # 先检查索引是否已存在
                cur.execute(
                    """
                    SELECT 1 FROM pg_indexes
                    WHERE indexname = %s AND schemaname = 'public'
                """,
                    (idx_name,),
                )
                exists = cur.fetchone()

                if exists:
                    print(f"     [跳过] 索引 {idx_name} 已存在")
                    continue

                cur.execute(idx_info["sql"])
                conn.commit()
                print(f"     [成功] 索引 {idx_name} 创建完成")

            print("\n索引验证:")
            for idx_info in INDEXES:
                cur.execute(
                    """
                    SELECT indexname, tablename, indexdef
                    FROM pg_indexes
                    WHERE indexname = %s AND schemaname = 'public'
                """,
                    (idx_info["name"],),
                )
                row = cur.fetchone()
                if row:
                    print(f"  [OK] {row[0]} on {row[1]}: {row[2][:80]}...")
                else:
                    print(f"  [FAIL] {idx_info['name']} 未找到")

    print("\n" + "=" * 60)
    print("索引应用完成")
    print("=" * 60)


if __name__ == "__main__":
    main()
