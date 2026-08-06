"""Partition order table by order_date year

Revision ID: partition_order_by_year
Revises: drop_redundant_order_indexes
Create Date: 2026-06-22

背景
----
订单表数据量持续增长，当单表数据超过百万行时，范围查询和归档维护成本显著上升。
本迁移将 order 表从普通堆表转换为按 order_date 年度范围分区表，
提升按年查询、归档和清理的效率。

限制
----
- 转换过程需要锁表，必须在维护窗口执行。
- PostgreSQL 分区表不支持某些约束（如跨分区唯一约束），
  order_no 的唯一约束需要应用层或单独的唯一索引保证。
- 执行前必须完整备份。

实施方式
--------
由于将已有大表转换为分区表不能通过 ALTER TABLE 直接完成，
标准流程是：
1. 创建新的分区表结构（order_new）。
2. 按年度创建分区（2024-2028）及 DEFAULT 分区。
3. 迁移数据。
4. 重命名表（order -> order_old, order_new -> order）。

本迁移文件记录该流程为可审计步骤，具体执行建议通过维护脚本
`scripts/perf_partition_orders.py` 在维护窗口完成。
"""
from alembic import op
from sqlalchemy import text

revision = 'partition_order_by_year'
down_revision = 'drop_redundant_order_indexes'
branch_labels = None
depends_on = None

PARTITION_YEARS = [2024, 2025, 2026, 2027, 2028]


def upgrade():
    """声明式创建分区表结构（dry-run 风格，不在线转换原表）。"""
    connection = op.get_bind()

    # 创建新的分区表（与原表结构一致）
    connection.execute(text("""
        CREATE TABLE IF NOT EXISTS order_new (
            LIKE "order" INCLUDING ALL
        ) PARTITION BY RANGE (order_date)
    """))

    # 创建年度分区
    for year in PARTITION_YEARS:
        connection.execute(text(f"""
            CREATE TABLE IF NOT EXISTS order_new_{year}
            PARTITION OF order_new
            FOR VALUES FROM ('{year}-01-01') TO ('{year + 1}-01-01')
        """))

    # 创建默认分区，容纳边界外数据
    connection.execute(text("""
        CREATE TABLE IF NOT EXISTS order_new_default
        PARTITION OF order_new DEFAULT
    """))

    # 记录下一步需要手动执行的数据迁移和切换步骤
    connection.execute(text("""
        COMMENT ON TABLE order_new IS
        '订单分区表（待切换）。切换流程：1) 迁移数据 2) 建立索引 3) 重命名 order -> order_old, order_new -> order'
    """))


def downgrade():
    """删除新建的分区表结构。注意：不会自动恢复 order_old 数据。"""
    connection = op.get_bind()
    for year in PARTITION_YEARS:
        connection.execute(text(f'DROP TABLE IF EXISTS order_new_{year}'))
    connection.execute(text('DROP TABLE IF EXISTS order_new_default'))
    connection.execute(text('DROP TABLE IF EXISTS order_new'))
