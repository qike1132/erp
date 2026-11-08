"""product_role 增加 is_hidden（隐藏款标记，每 SKU 至多一个）

Revision ID: pg_standalone_114_add_product_role_is_hidden
Revises: pg_standalone_113_add_product_hidden_carton_ratio
Create Date: 2026-11-08

背景
----
「盲盒隐藏款装箱配比」原先只按角色名精确等于「隐藏款」识别隐藏角色，现场
希望能在 BOM 角色页签里**右键指定任意角色**为隐藏款（不改名、可随时换），
并把指定结果持久化。故在 ``product_role`` 上加布尔标记：

- ``is_hidden = true`` 的角色即隐藏款；分配算法**优先**按标记识别，
  没有标记时回退「名字精确等于隐藏款」（兼容历史数据）；
- 每产品至多一个 true：用**部分唯一索引**兜底（PG/SQLite 均支持），
  应用层在保存时自动替换原隐藏款并留审计日志。

幂等性
------
``ADD COLUMN IF NOT EXISTS`` + ``CREATE UNIQUE INDEX IF NOT EXISTS``，
空库重放（001 已按当前元数据建表）也不会重复报错。Downgrade 的
DROP INDEX / DROP COLUMN 是标准回滚语句，已登记 destructive_ddl_baseline。
"""
from alembic import op

from migrations._legacy_base_guard import base_schema_absent

revision = 'pg_standalone_114_add_product_role_is_hidden'
down_revision = 'pg_standalone_113_add_product_hidden_carton_ratio'
branch_labels = None
depends_on = None


def upgrade():
    if base_schema_absent():
        return
    op.execute(
        'ALTER TABLE product_role ADD COLUMN IF NOT EXISTS is_hidden '
        'BOOLEAN NOT NULL DEFAULT false'
    )
    # ORM 声明了 comment，迁移必须同步——否则 alembic check 会报 modify_comment。
    # 文案必须与 shared_models/product_material.py 的列 comment 逐字一致。
    op.execute(
        "COMMENT ON COLUMN product_role.is_hidden IS "
        "'隐藏款标记（每产品至多一个；右键指定，优先于角色名识别）'"
    )
    op.execute(
        'CREATE UNIQUE INDEX IF NOT EXISTS uq_product_role_hidden_per_product '
        'ON product_role (product_id) WHERE is_hidden'
    )
    # 113 的列注释随文案改名同步（列名/语义不变，仅显示名：「盲盒隐藏款装箱配比」）。
    # 必须与 shared_models/product.py 的列 comment 逐字一致，否则 alembic check 报
    # modify_comment。
    op.execute(
        "COMMENT ON COLUMN product.hidden_carton_ratio IS "
        "'盲盒隐藏款装箱配比P(每P个订单数量配1个隐藏款;NULL=不启用陈列样角色分摊)'"
    )


def downgrade():
    if base_schema_absent():
        return
    op.execute('DROP INDEX IF EXISTS uq_product_role_hidden_per_product')
    op.execute('ALTER TABLE product_role DROP COLUMN IF EXISTS is_hidden')
