"""oosp_unique_process

Revision ID: pg_standalone_064_oosp_unique_process
Revises: pg_standalone_063_fix_order_status_check
Create Date: 2026-10-04

背景（2026-10-04 第十四轮审计 · 并发安全专项）
--------------------------------------------
外发工序生成 `sync_outsource_processes_for_order` 是 **check-then-act**：
先 SELECT 该订单已有工序集合，再对缺失的 (order_item_id, product_id, process_type)
逐个 INSERT。并发（双击「生成工序」/ 自动生成撞手工生成）时两次调用各自读到
「尚无」，双双插入 → 同一 (订单,明细,产品,工序) 出现两行工序，各自可发满目标量
→ **超发 + 双份流水**。`order_outsource_process` 原只有普通索引，无唯一约束兜底。

本迁移补一个唯一索引 `uq_oosp_order_item_product_process`：
  (order_id, order_item_id, product_id, process_type) 唯一。
`NULLS NOT DISTINCT`（PG 15+，本机 18）使 `order_item_id` 为空的行
（单 SKU 旧订单无 OrderItem 明细）也参与去重——PG 默认把 NULL 视为互不相同，
不加该选项时旧订单仍可重复插入。

安全性：现网 `order_outsource_process` 实测 **0 行**（且按该四元组分组无重复），
故建唯一索引不会因存量重复而失败。空库重放时表尚未由 001 建出 → 由
`create_index_if_absent` 的 table 存在性守卫整体跳过。
"""

from alembic import op

from migrations._legacy_base_guard import create_index_if_absent

revision = 'pg_standalone_064_oosp_unique_process'
down_revision = 'pg_standalone_063_fix_order_status_check'
branch_labels = None
depends_on = None

_TABLE = 'order_outsource_process'
_INDEX = 'uq_oosp_order_item_product_process'
_COLUMNS = ['order_id', 'order_item_id', 'product_id', 'process_type']


def upgrade():
    create_index_if_absent(_INDEX, _TABLE, _COLUMNS, unique=True, postgresql_nulls_not_distinct=True)


def downgrade():
    op.drop_index(_INDEX, table_name=_TABLE)
