"""迁移 058：把 naive UTC 写入 timestamptz 造成的下单/出货时间 +8h 纠正回来。

背景（生产实测）
----------------
pg_standalone_013 已把 ``order.order_date`` / ``stock_out.stockout_date`` 迁移为
timestamptz，但创建代码仍按旧注释写 naive UTC（``now(UTC).replace(tzinfo=None)``）。
asyncpg/PG 把 naive 值按会话时区（Asia/Shanghai）解释 ⇒ 存入瞬间早 8 小时
（PO-20260929-0008 于北京 09:29 创建，页面显示 2026-09-29 01:29）。

本文件锁住 058 的三个要求：
1. 只动 ``order.order_date`` 与 ``stock_out.stockout_date`` 两列；用户可录入墙上时间
   的列（stock_in 等）不得被波及（清单不得再扩大）；
2. upgrade 是 +8h、downgrade 是 -8h 且只回退带微秒（系统生成）的值；
3. 表/列不存在（空库重放）时跳过，与 013 的守卫口径一致。

⚠️ 2026-10-20 审计复核：058 原文假设「这两列取值全部来自系统时钟、必然带微秒」为假
——批量导入会把 Excel 提供的墙上时间写进 ``stock_out.stockout_date``（微秒恒 0）。
生产只读核验结果是受影响行数为 0，故未做数据修正迁移；但「清单不得再扩大」这条
断言的立论前提已不成立，改由 ``test_parse_date_value_keeps_zero_microsecond_for_
import_values`` 固化「用户录入值微秒恒 0」这一事实，防止后人再犯同一假设。
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

MIGRATION_PATH = (
    Path(__file__).resolve().parent.parent
    / 'migrations' / 'versions' / 'pg_standalone_058_fix_tz_naive_order_dates.py'
)

_EXPECTED_PAIRS = [
    ('order', 'order_date'),
    ('stock_out', 'stockout_date'),
]


def _load_migration_module():
    spec = importlib.util.spec_from_file_location('migration_058', MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _FakeOp:
    def __init__(self):
        self.statements: list[str] = []

    def execute(self, sql: str) -> None:
        self.statements.append(sql)


def _run_with_columns(monkeypatch, columns: dict[str, set[str]] | None):
    """加载迁移并以 fake op 执行 upgrade/downgrade，返回 (mod, op)。

    columns: 表名 → 列名集合；None 表示全部表不存在。
    """
    mod = _load_migration_module()
    op = _FakeOp()
    monkeypatch.setattr(mod, 'op', op)
    if columns is None:
        monkeypatch.setattr(mod, 'table_columns', lambda table: None)
    else:
        monkeypatch.setattr(mod, 'table_columns', lambda table: columns.get(table))
    return mod, op


def test_revision_chain_follows_057() -> None:
    mod = _load_migration_module()

    assert mod.revision == 'pg_standalone_058_fix_tz_naive_order_dates'
    assert mod.down_revision == 'pg_standalone_057_fix_incremental_cron'


def test_pairs_cover_only_system_clock_columns() -> None:
    """只动 058 选定的两列；用户可录入墙上时间的列不得出现在清单里。

    注意：本用例的名字沿用 058 当时的判断（「这几列都是系统时钟生成」），
    该判断已被 2026-10-20 审计证伪——``stock_out.stockout_date`` 也会被批量
    导入写入 Excel 提供的墙上时间。清单本身是既成事实（迁移已上生产），
    这里锁住的是「清单不得再扩大」，不是「清单里的列一定安全」。
    """
    mod = _load_migration_module()

    assert sorted(mod._PAIRS) == _EXPECTED_PAIRS
    tables = {t for t, _ in mod._PAIRS}
    assert 'stock_in' not in tables, 'stock_in.stockin_date 允许用户录入日期，不能盲 +8h'


def test_upgrade_shifts_both_columns_plus_8h(monkeypatch) -> None:
    columns = {
        'order': {'id', 'order_no', 'order_date'},
        'stock_out': {'id', 'stockout_no', 'stockout_date'},
    }
    mod, op = _run_with_columns(monkeypatch, columns)
    mod.upgrade()

    assert len(op.statements) == 2
    assert 'UPDATE "order" SET order_date = order_date + interval \'8 hours\'' in op.statements
    assert (
        'UPDATE "stock_out" SET stockout_date = stockout_date + interval \'8 hours\''
        in op.statements
    )


def test_upgrade_skips_missing_table(monkeypatch) -> None:
    """空库重放（表尚未建出）时跳过，不抛错 —— 与 013 口径一致。"""
    mod, op = _run_with_columns(monkeypatch, None)
    mod.upgrade()

    assert op.statements == []


def test_upgrade_skips_missing_column(monkeypatch) -> None:
    mod, op = _run_with_columns(monkeypatch, {'order': {'id', 'order_no'}})
    mod.upgrade()

    assert op.statements == []


def test_downgrade_shifts_back_only_microsecond_values(monkeypatch) -> None:
    """downgrade -8h 必须带微秒守卫：人工修正过的整点录入值不能被回退。"""
    columns = {'order': {'id', 'order_date'}, 'stock_out': {'id', 'stockout_date'}}
    mod, op = _run_with_columns(monkeypatch, columns)
    mod.downgrade()

    assert len(op.statements) == 2
    for sql in op.statements:
        assert "interval '8 hours'" in sql
        assert "- interval" in sql
        assert "date_part('microsecond'" in sql, sql


def test_parse_date_value_keeps_zero_microsecond_for_import_values() -> None:
    """用户录入的日期不带微秒 —— 058「取值全部来自系统时钟」的假设在代码层面为假。

    批量导入把 Excel 里的墙上时间（日期串 / 整数序列号）经 parse_date_value
    写进 ``stock_out.stockout_date``（timestamptz 列）：四种 strptime 格式都
    不带 ``%f``，Excel 序列号走整数 timedelta ⇒ 微秒恒为 0。

    后果：不能用「微秒非 0 ⇒ 系统时钟生成」去区分两类值，也就不能对含用户
    录入值的列做整列 +8h（058 的原做法）。这条断言就是复发防护。
    """
    from fastapi_app.utils import parse_date_value

    for raw in ('2026-08-08', '2026/08/08', '2026-08-08 13:45:00', '2026/08/08 13:45:00'):
        parsed = parse_date_value(raw)
        assert parsed is not None, raw
        assert parsed.microsecond == 0, raw

    excel_serial = parse_date_value(45000)
    assert excel_serial is not None
    assert excel_serial.microsecond == 0
