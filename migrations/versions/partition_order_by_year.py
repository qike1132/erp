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

空库重放说明（2026-09-27）
--------------------------
本迁移只创建 `order_new*` 旁观结构（dry-run），并非 ORM 元数据的一部分，
真实切换由维护脚本执行。为让空库重放的终态与 ORM 元数据一致（CI 的
`alembic check` 门禁），upgrade()/downgrade() 改为显式空转。
"""
from alembic import op  # noqa: F401  (保留 alembic 迁移文件惯例的导入)

revision = 'partition_order_by_year'
down_revision = 'drop_redundant_order_indexes'
branch_labels = None
depends_on = None

# 保留年度分区清单，供维护脚本 scripts/perf_partition_orders.py 参考。
PARTITION_YEARS = [2024, 2025, 2026, 2027, 2028]


def upgrade():
    """dry-run 迁移：不在线转换原表，也不创建旁观结构（详见文件头说明）。"""


def downgrade():
    """无操作：upgrade() 不创建任何对象。"""
