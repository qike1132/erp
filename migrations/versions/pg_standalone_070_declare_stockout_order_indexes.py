"""声明 idx_stockout_no_stockin / idx_order_date_id_desc 进 ORM（补迁移对齐空库重放）

Revision ID: pg_standalone_070_declare_stockout_order_indexes
Revises: pg_standalone_069_drop_product_image_orphan_backup
Create Date: 2026-10-05

背景
----
这两个 partial 索引此前**只存在于生产库**（由库外的 ad-hoc DDL 建），ORM 与迁移链都没有：
- `idx_stockout_no_stockin` `(product_id, customer) WHERE stockin_id IS NULL`
- `idx_order_date_id_desc`  `(order_date DESC, id DESC) WHERE is_deleted IS NOT TRUE`

二者都服务真实热查询，故纳入 ORM 声明（不是误建）：
- 前者：独立出货（stockin_id IS NULL）的库存 CTE 聚合主路径
  （`services/stock_inventory_service.py`、`inventory_service.py`）；
- 后者：订单列表游标分页 `ORDER BY order_date DESC, id DESC WHERE is_deleted IS NOT TRUE`
  （`services/order/queries.py:141-157`）。

本迁移在空库上把它们建出来，使「空库重放 == ORM」成立（否则 CI 的空库
`upgrade head` + `check` 会报 add_index）。生产库二者已存在 → `IF NOT EXISTS` 空转。

downgrade 刻意空转：二者早于本迁移就存在于生产库，回滚删索引会移除现网既有索引。
"""
from alembic import op
from sqlalchemy import text

revision = 'pg_standalone_070_declare_stockout_order_indexes'
down_revision = 'pg_standalone_069_drop_product_image_orphan_backup'
branch_labels = None
depends_on = None

_CREATE = (
    'CREATE INDEX IF NOT EXISTS idx_stockout_no_stockin '
    'ON stock_out (product_id, customer) WHERE stockin_id IS NULL',
    'CREATE INDEX IF NOT EXISTS idx_order_date_id_desc '
    'ON "order" (order_date DESC, id DESC) WHERE is_deleted IS NOT TRUE',
)


def upgrade() -> None:
    for ddl in _CREATE:
        op.execute(text(ddl))


def downgrade() -> None:
    # 刻意空转：两个索引早于本迁移存在于生产库，回滚删除会移除现网既有索引。
    pass
