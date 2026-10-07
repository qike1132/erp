"""产品批次台账表 + 客户「需要批次号」开关

背景（2026-10-07 业务裁定）
--------------------------
1. 库存查询页（/inventory-query）新增「批次号台账」：有些客户需要产品批次号、
   有些不需要；批次号 + 数量由用户手工登记，挂在 产品 + 客户 维度，仅供查看/对账，
   **不参与库存扣减、不改出货流程**，与 product.current_stock 无写入关系。
2. customer 增 needs_batch 开关，控制库存查询页是否显示批次列。

幂等：CREATE TABLE / ADD COLUMN / CREATE INDEX 带 IF (NOT) EXISTS 守卫，重复执行安全。
customer.needs_batch 为 NOT NULL，必须带 server_default（存量行需有值）。
本迁移不夹带业务逻辑、不写数据（AGENTS.md §5.7）；单 head（down_revision=076）。

Revision ID: pg_standalone_077_product_batch_and_customer_needs_batch
Revises: pg_standalone_076_inventory_query_nav
Create Date: 2026-10-07
"""
from alembic import op

revision = 'pg_standalone_077_product_batch_and_customer_needs_batch'
down_revision = 'pg_standalone_076_inventory_query_nav'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---- 1. 产品批次台账表 ----
    op.execute(
        'CREATE TABLE IF NOT EXISTS product_batch ('
        ' id SERIAL PRIMARY KEY,'
        ' product_id INTEGER NOT NULL REFERENCES product(id) ON DELETE CASCADE,'
        ' customer VARCHAR(100) NOT NULL,'
        ' batch_no VARCHAR(100) NOT NULL,'
        ' quantity INTEGER NOT NULL,'
        ' remark VARCHAR(500),'
        ' created_by VARCHAR(50),'
        ' created_at TIMESTAMPTZ NOT NULL,'
        ' updated_at TIMESTAMPTZ,'
        ' CONSTRAINT uq_product_batch_no UNIQUE (product_id, customer, batch_no)'
        ')'
    )
    op.execute(
        'CREATE INDEX IF NOT EXISTS idx_product_batch_product_customer '
        'ON product_batch (product_id, customer)'
    )
    op.execute("COMMENT ON TABLE product_batch IS '产品批次台账（产品+客户+批次号，手工登记，不参与库存扣减）'")
    op.execute("COMMENT ON COLUMN product_batch.batch_no IS '批次号（自定义）'")
    op.execute("COMMENT ON COLUMN product_batch.quantity IS '批次数量'")

    # ---- 2. 客户「需要批次号」开关 ----
    op.execute('ALTER TABLE customer ADD COLUMN IF NOT EXISTS needs_batch BOOLEAN NOT NULL DEFAULT false')
    op.execute("COMMENT ON COLUMN customer.needs_batch IS '是否需要产品批次号（库存查询页批次列显示开关）'")


def downgrade() -> None:
    op.execute('ALTER TABLE customer DROP COLUMN IF EXISTS needs_batch')
    op.execute('DROP TABLE IF EXISTS product_batch')
