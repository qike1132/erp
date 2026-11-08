"""product 增加盲盒开关与「是否有隐藏款」标记

Revision ID: pg_standalone_115_add_product_blind_box_flags
Revises: pg_standalone_114_add_product_role_is_hidden
Create Date: 2026-11-08

背景
----
产品录入新增「盲盒」选择项：勾选后展开「盲盒隐藏款装箱配比」与「该 SKU 是否有
隐藏款」。采购口径随之分三档：

- ``is_blind_box = false``：存量口径——每个角色都用完整订单数量（零行为变化）；
- ``is_blind_box = true, has_hidden_role = false``：订单数量按**角色数量**均分，
  不额外配隐藏款；
- ``is_blind_box = true, has_hidden_role = true`` 且配比非空：常规角色按
  **常规角色数量**均分（4+1 → N/4、8+1 → N/8），隐藏款额外 ``ceil(N/P)``。

数据迁移
--------
历史已配置 ``hidden_carton_ratio`` 的 SKU 是旧口径（固定 6 常规 + 1 隐藏），
回填 ``is_blind_box = true, has_hidden_role = true``，保持这些 SKU 行为不变。
生产库当前没有配置过配比的 SKU，回填为空操作。

幂等性
------
``ADD COLUMN IF NOT EXISTS``；回填 UPDATE 以 ``is_blind_box = false`` 为条件，
重放不会覆盖用户后来手动关闭的开关。Downgrade 的 DROP COLUMN 是标准回滚语句，
已登记 destructive_ddl_baseline。
"""
from alembic import op

from migrations._legacy_base_guard import base_schema_absent

revision = 'pg_standalone_115_add_product_blind_box_flags'
down_revision = 'pg_standalone_114_add_product_role_is_hidden'
branch_labels = None
depends_on = None


def upgrade():
    if base_schema_absent():
        return
    op.execute(
        'ALTER TABLE product ADD COLUMN IF NOT EXISTS is_blind_box '
        'BOOLEAN NOT NULL DEFAULT false'
    )
    op.execute(
        'ALTER TABLE product ADD COLUMN IF NOT EXISTS has_hidden_role '
        'BOOLEAN NOT NULL DEFAULT false'
    )
    # ORM 声明了 comment，迁移必须同步——否则 alembic check 会报 modify_comment。
    # 文案必须与 shared_models/product.py 的列 comment 逐字一致。
    op.execute(
        "COMMENT ON COLUMN product.is_blind_box IS "
        "'是否盲盒SKU（开启后订单数量按角色数均分；关闭=历史全量口径）'"
    )
    op.execute(
        "COMMENT ON COLUMN product.has_hidden_role IS "
        "'该盲盒SKU是否有隐藏款（有则配比生效、隐藏款额外ceil(N/P)）'"
    )
    # 历史已配配比的 SKU 属于旧口径，回填为「盲盒 + 有隐藏款」保持行为不变
    op.execute(
        'UPDATE product SET is_blind_box = true, has_hidden_role = true '
        'WHERE hidden_carton_ratio IS NOT NULL AND is_blind_box = false'
    )


def downgrade():
    if base_schema_absent():
        return
    op.execute('ALTER TABLE product DROP COLUMN IF EXISTS has_hidden_role')
    op.execute('ALTER TABLE product DROP COLUMN IF EXISTS is_blind_box')
