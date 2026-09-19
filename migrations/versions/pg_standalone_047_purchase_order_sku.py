"""采购单逐 SKU 数量快照：新增 purchase_order_sku 表（方案 C 治本）

**背景**

`/beile-order`（湖北订单页）在「同一订单含多 SKU」时无法让每个 SKU 对应展示
各自的订单数量。根因（RC-1）在于数据模型层：汇总下单时「1 个客户 = 1 张采购单」，
多 SKU 的产品名被 `'、'.join` 拼接、数量被求和写入 `purchase_order.product_quantity`，
逐 SKU 下单量自落库起即不可还原。

本迁移新增 `purchase_order_sku` 表，把逐 SKU 的订单数量 / 备品量 / 损耗率快照落库：

- `order_qty`   该 SKU 在来源记录中的订单数量；
- `spare_qty`   `ceil(order_qty × 损耗率‰)`；
- `spare_rate`  损耗率快照（千分之几）；
- `source_order_id` / `source_record_type`  来源记录定位（**必须含 record_type**：
  本仓 order.id 与 stockin.id 会撞号，缺列会导致读路径串号）。

**口径恒等式**：`Σ order_qty == purchase_order.product_quantity`（同一采集口径）。

**唯一约束** `(po_id, source_record_type, source_order_id, product_name)`：写路径
已按该四元组合并（同来源同产品名合并为一行），回填脚本以「先删后插」实现幂等，
唯一约束作为第二道防线。不纳入 `product_barcode`（可为 NULL，PG 下 NULL != NULL
会使约束失效）。

**幂等**：DDL 一律 `CREATE TABLE IF NOT EXISTS` / `CREATE INDEX IF NOT EXISTS`，
重复执行结果不变。

**回滚**：`downgrade()` 对称 `DROP TABLE IF EXISTS`（本表本次新增，无历史数据可丢）。

**链位置**：接在 046（采购单备品字段）之后，保证全图单一 head、线性无分叉。

Revision ID: pg_standalone_047_purchase_order_sku
Revises: pg_standalone_046_po_spare_fields
Create Date: 2026-09-18
"""
import sqlalchemy as sa
from alembic import op

revision = 'pg_standalone_047_purchase_order_sku'
down_revision = 'pg_standalone_046_po_spare_fields'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """创建 purchase_order_sku 表 + 索引 + 唯一约束（幂等）。"""
    op.execute(sa.text(
        """
        CREATE TABLE IF NOT EXISTS purchase_order_sku (
            id SERIAL PRIMARY KEY,
            po_id INTEGER NOT NULL REFERENCES purchase_order(id) ON DELETE CASCADE,
            product_name VARCHAR(200),
            product_barcode VARCHAR(50),
            order_qty NUMERIC(12,2),
            spare_qty NUMERIC(12,2),
            spare_rate NUMERIC(8,2),
            source_order_id INTEGER,
            source_record_type VARCHAR(10),
            create_time TIMESTAMP WITH TIME ZONE,
            CONSTRAINT uq_po_sku_po_source_product
                UNIQUE (po_id, source_record_type, source_order_id, product_name)
        )
        """
    ))
    op.execute(sa.text(
        'CREATE INDEX IF NOT EXISTS idx_purchase_order_sku_po ON purchase_order_sku (po_id)'
    ))
    op.execute(sa.text(
        'CREATE INDEX IF NOT EXISTS idx_purchase_order_sku_source '
        'ON purchase_order_sku (source_record_type, source_order_id)'
    ))
    op.execute(sa.text(
        "COMMENT ON TABLE purchase_order_sku IS "
        "'采购单逐 SKU 数量快照（方案 C）：Σ order_qty == purchase_order.product_quantity'"
    ))


def downgrade() -> None:
    """对称删除本表（结构回滚，无反向数据重建）。"""
    op.execute(sa.text('DROP TABLE IF EXISTS purchase_order_sku'))
