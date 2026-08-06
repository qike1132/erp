"""add UNIQUE index on purchase_plans(customer_id, plan_month)

Revision ID: pg_standalone_018_purchase_plan_unique_month_customer
Revises: pg_standalone_017_add_po_source_order_ids_gin_index
Create Date: 2026-07-31

为 purchase_plans(customer_id, plan_month) 添加唯一约束，避免并发
confirm_staging 创建多个相同 (customer_id, plan_month) 的主单。

背景：
    purchase_plan_crud._get_or_create_plan_for_group 先 SELECT 后 INSERT，
    无 FOR UPDATE 也无唯一约束，并发请求可能创建多个相同主单。
    此迁移是 B2 修复的数据库侧补充；代码侧同步加 with_for_update + IntegrityError 重试。

注意事项：
    若历史数据中已存在重复 (customer_id, plan_month) 行，需先清理再创建唯一索引。
    upgrade() 采用先查重 → 失败则降级为非唯一索引的容错策略，
    避免历史脏数据阻塞迁移；但日志会告警提示需人工清理。

索引列序说明（S4 修复）：
    唯一约束语义上 (customer_id, plan_month) 与 (plan_month, customer_id) 等价，
    均能阻止重复。但模型 __table_args__ 已存在非唯一索引
    idx_ppl_month_customer (plan_month, customer_id)，故此处 UNIQUE 索引
    采用 (customer_id, plan_month) 列序以补充不同的查询模式（按 customer_id
    前缀过滤）。降级分支同样采用 (plan_month, customer_id) 与模型保持一致，
    通过 IF NOT EXISTS 避免与现有 idx_ppl_month_customer 冲突。

锁说明（S3 修复）：
    本迁移使用普通 CREATE INDEX（非 CONCURRENTLY），Alembic 默认在事务内执行，
    对 purchase_plans 表持 ACCESS EXCLUSIVE 锁直到事务结束。
    若部署环境 purchase_plans 数据量大、需在线迁移，应改为：
        with op.get_context().autocommit_block():
            op.execute("CREATE UNIQUE INDEX CONCURRENTLY ...")
    并在执行前确认无长事务持锁。
"""
from alembic import op
import logging

logger = logging.getLogger('alembic.migration')

revision = 'pg_standalone_018_purchase_plan_unique_month_customer'
down_revision = 'pg_standalone_017_add_po_source_order_ids_gin_index'
branch_labels = None
depends_on = None


def upgrade():
    """创建唯一索引；若历史存在重复行则降级为非唯一索引并告警"""
    # 先检测历史重复
    conn = op.get_bind()
    dup_check = conn.execute(
        "SELECT customer_id, plan_month, COUNT(*) AS cnt "
        "FROM purchase_plans "
        "WHERE customer_id IS NOT NULL AND plan_month IS NOT NULL "
        "GROUP BY customer_id, plan_month "
        "HAVING COUNT(*) > 1"
    ).fetchall()

    if dup_check:
        # 存在重复数据，无法直接创建 UNIQUE 索引
        # 降级方案：创建非唯一索引保证查询性能，并输出告警日志
        # S4: 列序与模型 idx_ppl_month_customer (plan_month, customer_id) 一致
        logger.warning(
            "检测到 %d 组 (customer_id, plan_month) 重复数据，"
            "降级创建非唯一索引。请清理后执行："
            "CREATE UNIQUE INDEX CONCURRENTLY uq_ppl_month_customer "
            "ON purchase_plans (customer_id, plan_month);",
            len(dup_check),
        )
        op.execute(
            "CREATE INDEX IF NOT EXISTS idx_ppl_month_customer "
            "ON purchase_plans (plan_month, customer_id)"
        )
        return

    # 无重复数据，直接创建唯一索引
    # 注意：非 CONCURRENTLY，在事务内持 ACCESS EXCLUSIVE 锁（见文件头锁说明）
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_ppl_month_customer "
        "ON purchase_plans (customer_id, plan_month)"
    )


def downgrade():
    op.execute("DROP INDEX IF EXISTS uq_ppl_month_customer")
    op.execute("DROP INDEX IF EXISTS idx_ppl_month_customer")
