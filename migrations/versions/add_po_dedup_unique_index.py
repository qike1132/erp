"""add partial unique index on purchase_order to prevent duplicate pending orders

Revision ID: add_po_dedup_unique_index
Revises: merge_resolve_all_heads
Create Date: 2026-06-18

背景
----
/purchase 页面"一键审核"逻辑历史上会异常生成 4 条完全相同的重复 pending
采购单。本次修复通过应用层 + 缓存层 + 服务层清理函数多层防护后，再在
数据库层加一道**最终防线**：

  * 唯一索引 (customer_id, supplier_id, source_order_ids) WHERE status='pending'

效果
----
* 同一客户 + 同一供应商 + 同一 source_order_ids 集合，只能存在一条
  status='pending' 的采购单。
* 重复 INSERT 会在数据库层被拒绝（UniqueViolationError），由 ORM 层捕获
  并转为业务幂等响应。
* confirmed / completed 状态的订单不受影响（partial index），允许后续
  在不同业务节点生成新单。

注意
----
* source_order_ids 是 Text 类型的 JSON 字符串。
  本次直接以字符串相等作为去重依据。理论上前端可能因 JSON 数组顺序不同
  产生 "[1,2,3]" 与 "[3,1,2]" 两种字符串，应用层 `_normalize_source_ids`
  仍会先做集合归一化清理重复。
* 若希望更严格，可改用表达式索引对 source_order_ids 做排序后再比较。
  当前实现保持简单，足够覆盖 /purchase 一键审核的典型重复场景。
* alembic 的 ``begin_transaction`` 会包裹整个 migration，``CREATE INDEX
  CONCURRENTLY`` 必须在事务外执行，因此这里退回到普通 ``CREATE INDEX``。
  purchase_order 表写操作不频繁，短暂锁表可接受。若未来需要零阻塞，可用
  ``op.get_context().autocommit_block()`` 改写（alembic 1.6+）。
"""
from alembic import op
from sqlalchemy import text

from migrations._legacy_base_guard import base_schema_absent

revision = 'add_po_dedup_unique_index'
down_revision = 'merge_resolve_all_heads'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 空库守卫：pg_standalone_001 尚未建出基础 schema 时整条增量迁移空转。
    # 判据要求 product / customer 同时缺失，遗留库与已建库一律照常执行。
    if base_schema_absent():
        return
    op.execute(text(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_po_pending_dedup
        ON purchase_order (customer_id, supplier_id, source_order_ids)
        WHERE status = 'pending'
        """
    ))


def downgrade() -> None:
    # 空库守卫：pg_standalone_001 尚未建出基础 schema 时整条增量迁移空转。
    # 判据要求 product / customer 同时缺失，遗留库与已建库一律照常执行。
    if base_schema_absent():
        return
    op.execute(text("DROP INDEX IF EXISTS uq_po_pending_dedup"))
