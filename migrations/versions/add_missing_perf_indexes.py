"""Add missing performance indexes for StockOut, InventoryLog, and Order

Revision ID: add_missing_perf_idx
Revises: perf_idx_001
Create Date: 2026-06-06

空转说明
--------
本迁移原本要建 `idx_stockout_order_stockin`、`idx_inventory_log_product_time`、
`idx_order_date_id_desc` 三个索引，但：

1. 它用 `connection.execute(text("COMMIT"))` 绕过事务（`CONCURRENTLY` 需要），
   该写法在 SQLAlchemy 2.x 下无效，迁移从未真正生效；
2. 这三个索引在现网 `erp_system`（已在 head）中**一个都不存在**；
3. ORM 元数据（`fastapi_app/shared_models/`）也**未声明**它们——
   `idx_stockout_order_stockin` 与 ORM 已有的 `idx_stockout_order_type`
   (`order_id, stockin_id`) 语义重复。

按「迁移链必须能重建出 ORM schema（CI 的 `alembic upgrade head` + `check`
门禁）」这一约定，本迁移改为空转，避免在空库重放时产出 ORM 不认识的索引。
若确实需要这些索引，请先在 ORM 模型里声明 `Index(...)`，再新增一条迁移落地。

（保留 revision 标识以维持既有迁移链拓扑不变。）
"""

revision = 'add_missing_perf_idx'
down_revision = 'perf_idx_001'
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
