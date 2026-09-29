"""修复「naive UTC 写入 timestamptz 列」导致的下单/出货时间早 8 小时

背景
----
pg_standalone_013（2026-05-23）已把 ``order.order_date`` 等列由
TIMESTAMP WITHOUT TIME ZONE 迁移为 timestamptz，但创建代码仍按旧注释写入
``datetime.now(UTC).replace(tzinfo=None)``（naive UTC）。asyncpg / PG 会把
naive 值按**会话时区（Asia/Shanghai, +08）**解释，于是存入的瞬间比真实时刻
早 8 小时（例如北京 09:29 创建的订单存成 01:29+08）。页面「下单时间」由此
显示为 UTC 钟面值（实证：PO-20260929-0008 于 09:29 创建，页面显示
2026-09-29 01:29）。

代码侧已在同次变更改为写入 aware UTC（``datetime.now(UTC)``）；本迁移只
负责纠正存量数据：把受影响列整体 +8 小时。

只动 ``order.order_date`` 与 ``stock_out.stockout_date``：这两列的全部取值
都来自系统时钟（``now()``），必然带微秒 → 全量 +8h 安全。
``stock_in.stockin_date`` / ``order_sync_config.updated_at`` 允许用户录入
墙上时间（微秒恒为 0 的取值语义正确），混存无法可靠区分，本迁移不动，
宁可保留个别旧误差也不引入新的错值。

Revision ID: pg_standalone_058_fix_tz_naive_order_dates
Revises: pg_standalone_057_fix_incremental_cron
Create Date: 2026-09-29
"""
from alembic import op

from migrations._legacy_base_guard import table_columns

revision = 'pg_standalone_058_fix_tz_naive_order_dates'
down_revision = 'pg_standalone_057_fix_incremental_cron'
branch_labels = None
depends_on = None

# (表, 列)：全部取值均为系统时钟生成（带微秒），整体 +8h 即还原真实时刻
_PAIRS = [
    ('order', 'order_date'),
    ('stock_out', 'stockout_date'),
]


def upgrade() -> None:
    for table, column in _PAIRS:
        present = table_columns(table)
        if present is None or column not in present:
            continue
        op.execute(f'UPDATE "{table}" SET {column} = {column} + interval \'8 hours\'')


def downgrade() -> None:
    """逆向 -8h：仅当值仍带微秒（未被后续人工修正为整点录入值）时回退。"""
    for table, column in _PAIRS:
        present = table_columns(table)
        if present is None or column not in present:
            continue
        op.execute(
            f"UPDATE \"{table}\" SET {column} = {column} - interval '8 hours' "
            f"WHERE date_part('microsecond', {column})::bigint % 1000000 <> 0"
        )
