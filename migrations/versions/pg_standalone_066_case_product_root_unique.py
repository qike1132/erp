"""case_product_root_unique

Revision ID: pg_standalone_066_case_product_root_unique
Revises: pg_standalone_065_case_movement_indexes
Create Date: 2026-10-04

背景（2026-10-04 第十四轮审计 · 皮套重写域补审）
--------------------------------------------
`case.product_id` 只有普通索引，无唯一约束；`create_case_item` 建主件时不查重、
不取 advisory lock，而 `get_or_create_case_tree_for_product` 用 `scalar_one_or_none()`
读同一产品的皮套 —— 并发/双击造出**同产品的第二个主件**后，该读抛
`MultipleResultsFound` → `POST /cases/for-product`（皮套设置核心路径）与按产品名
批量导入 500。

本迁移加**部分唯一索引** `uq_case_product_root`：`product_id` 在
`parent_id IS NULL`（主件）时唯一 —— 配件(parent_id 非空)不受约束（多个配件可关联
同一产品）。代码侧 create_case_item 同步取同一把 advisory lock + 查重（见同批提交）。

安全性：现网 `case` 实测 6 个主件、**0 个重复组**，故建唯一索引不会因存量重复失败。
空库重放时表尚未由 001 建出 → `create_index_if_absent` 的表存在性守卫整体跳过。
"""

from alembic import op
from sqlalchemy import text

from migrations._legacy_base_guard import create_index_if_absent

revision = 'pg_standalone_066_case_product_root_unique'
down_revision = 'pg_standalone_065_case_movement_indexes'
branch_labels = None
depends_on = None

_INDEX = 'uq_case_product_root'


def upgrade():
    create_index_if_absent(
        _INDEX, 'case', ['product_id'],
        unique=True, postgresql_where=text('parent_id IS NULL'),
    )


def downgrade():
    op.drop_index(_INDEX, table_name='case', if_exists=True)
