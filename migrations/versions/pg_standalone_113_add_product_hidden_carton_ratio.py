"""product 表增加 hidden_carton_ratio（陈列样隐藏款随箱配比）

Revision ID: pg_standalone_113_add_product_hidden_carton_ratio
Revises: pg_standalone_112_add_supplier_name_to_material_registration_item
Create Date: 2026-11-08

背景
----
《蛋仔派对》市集拾趣系列毛绒公仔挂件盲盒（陈列样）这类 SKU 的采购口径：
6 个常规款按订单数量均分（``floor(N/6)``，余数按固定角色顺序逐款 +1），
隐藏款按「每 P 个订单数量配 1 个」额外采购 ``ceil(N/P)``。
P 由用户在 SKU 主数据填写（新增/编辑产品表单）；NULL = 不启用该规则，
采购生成保持「每个角色都用完整订单数量」的历史口径（存量 SKU 零行为变化）。

分配算法唯一实现：``fastapi_app/utils/scope_quantities.py``；
消费方：采购单生成（purchase_order_generate）与物料计算器
（purchase_product_service）。

幂等性
------
用 ``ADD COLUMN IF NOT EXISTS``：空库重放时 ``pg_standalone_001`` 按当时 ORM
元数据建表可能已带上该列（连同同名 CHECK），重复添加会报错。约束先
``DROP IF EXISTS`` 再 ``ADD``，对已被 001 建出的同名约束是幂等重设。
"""
from alembic import op

from migrations._legacy_base_guard import base_schema_absent

revision = 'pg_standalone_113_add_product_hidden_carton_ratio'
down_revision = 'pg_standalone_112_add_supplier_name_to_material_registration_item'
branch_labels = None
depends_on = None


def upgrade():
    if base_schema_absent():
        return
    op.execute(
        'ALTER TABLE product ADD COLUMN IF NOT EXISTS hidden_carton_ratio '
        'INTEGER NULL'
    )
    op.execute(
        'ALTER TABLE product DROP CONSTRAINT IF EXISTS ck_product_hidden_carton_ratio_positive'
    )
    op.execute(
        'ALTER TABLE product ADD CONSTRAINT ck_product_hidden_carton_ratio_positive '
        'CHECK (hidden_carton_ratio IS NULL OR hidden_carton_ratio > 0)'
    )
    # ORM 声明了 comment，迁移必须同步——否则 alembic check 会报 modify_comment。
    # 文案必须与 shared_models/product.py 的列 comment 逐字一致。
    op.execute(
        "COMMENT ON COLUMN product.hidden_carton_ratio IS "
        "'隐藏款随箱配比P(每P个订单数量配1个隐藏款;NULL=不启用陈列样角色分摊)'"
    )


def downgrade():
    if base_schema_absent():
        return
    op.execute('ALTER TABLE product DROP COLUMN IF EXISTS hidden_carton_ratio')
