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

只动 ``order.order_date`` 与 ``stock_out.stockout_date``：这两列在**当时**
被认为全部来自系统时钟（``now()``），故全量 +8h。
``stock_in.stockin_date`` / ``order_sync_config.updated_at`` 允许用户录入
墙上时间（微秒恒为 0 的取值语义正确），混存无法可靠区分，本迁移不动，
宁可保留个别旧误差也不引入新的错值。

⚠️ 2026-10-20 审计复核：上述「全部来自系统时钟」的**假设是错的**（见下），
本迁移的 SQL 保持原样（已上生产；历史迁移不得改写行为，否则重放与线上分叉），
此处只更正事实陈述。

    stock_out.stockout_date 并不只由系统时钟写入——批量导入会把 Excel 里
    用户提供的墙上时间经 ``parse_date_value`` 写进该列（timestamptz），
    而该函数的四种 strptime 格式都不带 ``%f``、Excel 序列号走整数
    timedelta ⇒ **微秒恒为 0**。058 把这类本来就正确的墙上时间也推了
    8 小时（18:00 后导入的会跨日 → 日报口径错位），且 downgrade 的
    微秒守卫只回退 ``microsecond <> 0`` 的行 ⇒ 被错改的行永远无法回退。

生产数据核验（2026-10-20，只读查询）结论：**实际影响为 0，无需数据修正迁移**。

    SELECT count(*) FROM stock_out WHERE date_part('microsecond', stockout_date)=0;
      → 0（共 21 行，全部非零微秒，且最早 2026-09-30，晚于本迁移的 09-29）
    SELECT count(*) FROM "order" WHERE date_part('microsecond', order_date)=0;
      → 48（共 67 行），但这 48 行的订单号日期全部 ≥ 20260929，即创建于本迁移
        之后，未被 +8h 波及；被错改的指纹（微秒=0 且小时=8）计数为 0。

复发防护：``tests/test_migration_058_fix_tz_naive_order_dates.py`` 断言
``parse_date_value`` 对导入形态输入返回微秒恒为 0——后人再写「整列 +8h」
这类迁移前，先看这条断言。

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

# (表, 列)：058 当时认为全部取值均由系统时钟生成（带微秒），整体 +8h 即还原真实时刻。
# ⚠️ 该前提已被证伪（stock_out 可含导入的墙上时间，微秒恒 0）——见文件头。
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
