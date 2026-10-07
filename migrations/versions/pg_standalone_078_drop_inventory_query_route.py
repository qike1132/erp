"""回退「库存查询」独立路由遗留：product_batch 表 / customer.needs_batch / 导航项

背景（2026-10-07 业务裁定）
--------------------------
库存查询不再独立成页——「库存」结余列（包装部入库 − 已出货）已并入
/stock（订单查询）的库存汇总表。故回退 076/077 引入的三件东西：

1. ``product_batch`` 表（批次台账，随该页面一并废弃，数据不保留）；
2. ``customer.needs_batch`` 列（批次列显示开关）；
3. 权限点 ``stock.inventory_query`` 及其 user_permission 授权行（侧边栏导航项）。

幂等：DROP ... IF EXISTS + DELETE 按 code 过滤，重复执行安全。
单 head：并发会话的 078_stock_nav_rename 已 re-parent 到本迁移之后。

Revision ID: pg_standalone_078_drop_inventory_query_route
Revises: pg_standalone_077_product_batch_and_customer_needs_batch
Create Date: 2026-10-07
"""
from alembic import op

revision = 'pg_standalone_078_drop_inventory_query_route'
down_revision = 'pg_standalone_077_product_batch_and_customer_needs_batch'
branch_labels = None
depends_on = None

_CODE = 'stock.inventory_query'


def upgrade() -> None:
    # 1. 导航项：先删授权行再删权限点（user_permission 外键无级联，075/076 同款）
    op.execute(
        "DELETE FROM user_permission WHERE permission_id IN "
        "(SELECT id FROM permission WHERE code = '" + _CODE + "')"
    )  # nosec B608 — 常量表插值，无外部输入
    op.execute("DELETE FROM permission WHERE code = '" + _CODE + "'")  # nosec B608 — 常量表插值

    # 2. 批次台账表
    op.execute('DROP TABLE IF EXISTS product_batch')

    # 3. 客户「需要批次号」开关
    op.execute('ALTER TABLE customer DROP COLUMN IF EXISTS needs_batch')


def downgrade() -> None:
    """回退到 077 的结构（不含数据）。"""
    op.execute('ALTER TABLE customer ADD COLUMN IF NOT EXISTS needs_batch BOOLEAN NOT NULL DEFAULT false')
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
    op.execute(
        "INSERT INTO permission (code, name, icon, url, section, section_name, sort_order, is_nav, updated_at) "
        "SELECT '" + _CODE + "', '库存查询', 'fa-boxes-stacked', '" + _CODE + "', "
        "'data', '订单查询', 1, True, now() "
        "WHERE NOT EXISTS (SELECT 1 FROM permission WHERE code = '" + _CODE + "')"
    )  # nosec B608 — 常量表插值，无外部输入
