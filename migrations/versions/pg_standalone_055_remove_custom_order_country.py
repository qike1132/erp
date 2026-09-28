"""移除定制订单：删除 order_type/country 列与 country 表

Revision ID: pg_standalone_055_remove_custom_order_country
Revises: pg_standalone_054
Create Date: 2026-09-28

背景
----
「定制订单」订单类型与「国家」维度已从前后端整体移除（见
docs/superpowers/specs/2026-09-28-remove-custom-order-design.md）。
本迁移删除其数据层残留：

- 五张表的 order_type / country 列
- 定制订单专用部分索引 idx_order_custom_type
- 国家主数据表 country

数据说明
--------
执行前已核查：`order` 仅 4 条 regular（含 2 条软删），`order_item` 2 条
regular，`stock_in` / `staging_order` / `staging_stock_out` 为空，
`country` 2 行国家名。**无任何定制订单数据**，删列与删表不丢业务数据。

实现要点
--------
1. 使用 `migrations/_legacy_base_guard.py` 的幂等包装，容忍现网与空库重放
   之间的漂移（与 pg_standalone_054 同一约定）。
2. `country` 表用 `drop_table_if_exists` 而非 `drop_table_if_empty`：表内本就
   只有定制订单用的国家名主数据，随功能一并删除是有意为之，非静默丢数据。
3. `downgrade()` 只恢复结构（列、索引、空表），不恢复数据。
"""
import sqlalchemy as sa

from migrations._legacy_base_guard import (
    add_column_if_absent,
    base_schema_absent,
    create_index_if_absent,
    create_table_if_absent,
    drop_column_if_absent,
    drop_index_if_exists,
    drop_table_if_exists,
)

# revision identifiers, used by Alembic.
revision = 'pg_standalone_055_remove_custom_order_country'
down_revision = 'pg_standalone_054'
branch_labels = None
depends_on = None

# order_type 在原库中为 NOT NULL（order/staging_order 无 server_default），
# 回滚重建时给出 server_default 以便旧代码继续写入。
_TABLES = ('order', 'order_item', 'stock_in', 'staging_order', 'staging_stock_out')


def upgrade():
    # 空库守卫：pg_standalone_001 尚未建出基础 schema 时整条增量迁移空转。
    if base_schema_absent():
        return
    drop_index_if_exists('idx_order_custom_type', table_name='order')
    for table in _TABLES:
        drop_column_if_absent(table, 'order_type')
        drop_column_if_absent(table, 'country')
    drop_table_if_exists('country')


def downgrade():
    # 空库守卫：pg_standalone_001 尚未建出基础 schema 时整条增量迁移空转。
    if base_schema_absent():
        return
    for table in _TABLES:
        add_column_if_absent(table, sa.Column(
            'order_type', sa.String(20), nullable=False,
            server_default='regular',
            comment='订单类型：regular=常规订单, custom=定制订单',
        ))
        add_column_if_absent(table, sa.Column(
            'country', sa.String(100), nullable=True,
            comment='国家名称（仅定制订单使用）',
        ))
    create_table_if_absent(
        'country',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('name', sa.String(100), unique=True, nullable=False, comment='国家名称'),
    )
    create_index_if_absent(
        'idx_order_custom_type', 'order', ['product_id', 'customer', 'country'],
        postgresql_where=sa.text("(order_type)::text = 'custom'::text"),
    )
