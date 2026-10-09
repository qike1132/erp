"""产品-客户归属关联表（多对多）

背景（2026-10-09 用户裁定）
----
产品页要给每个 SKU 挂「所属客户」，下单/出货/备货/备货计划选产品时按客户过滤，
避免甲客户选到乙客户的专属 SKU。

为什么是关联表而不是 product.customer_id 单列：一个 SKU 可以同时属于多个客户
（同一个产品卖给两家时不必建两行重复 SKU）。用户明确选了多对多。

口径
----
**未挂任何客户的 SKU 对所有客户可见** —— 存量 SKU 上线当天不挂客户也不会从
下单页消失，避免「搜不到东西」；挂上客户后才收紧。过滤 SQL 见
fastapi_app/services/product_visibility.py（单一事实来源）。

安全性 / 幂等
----
纯新建表 + 索引，不改动任何既有列、不回填数据、不写业务数据（AGENTS.md §5.7）；
`IF NOT EXISTS` 守卫使空库重放与重复执行均安全，也不触发破坏性 DDL 守卫。
两个外键均 ON DELETE CASCADE：删产品/删客户时归属行自动清理，不留孤儿。
**本文件不代维护者执行**；是否应用到生产由维护者决定。

Revision ID: pg_standalone_086_product_customer_link
Revises: pg_standalone_085_add_user_department
Create Date: 2026-10-09
"""
from alembic import op

revision = 'pg_standalone_086_product_customer_link'
down_revision = 'pg_standalone_085_add_user_department'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        'CREATE TABLE IF NOT EXISTS product_customer ('
        ' id SERIAL PRIMARY KEY,'
        ' product_id INTEGER NOT NULL REFERENCES product(id) ON DELETE CASCADE,'
        ' customer_id INTEGER NOT NULL REFERENCES customer(id) ON DELETE CASCADE,'
        ' create_time TIMESTAMPTZ,'
        ' CONSTRAINT uq_product_customer UNIQUE (product_id, customer_id)'
        ')'
    )
    # 可见性过滤按 customer_id 反查（「这个客户能看到哪些 SKU」）
    op.execute(
        'CREATE INDEX IF NOT EXISTS idx_product_customer_customer '
        'ON product_customer (customer_id)'
    )
    op.execute("COMMENT ON TABLE product_customer IS '产品-客户归属（多对多；未挂客户的 SKU 对所有客户可见）'")
    op.execute("COMMENT ON COLUMN product_customer.product_id IS '产品ID'")
    op.execute("COMMENT ON COLUMN product_customer.customer_id IS '客户ID'")
    op.execute("COMMENT ON COLUMN product_customer.create_time IS '创建时间'")


def downgrade() -> None:
    op.execute('DROP TABLE IF EXISTS product_customer')
