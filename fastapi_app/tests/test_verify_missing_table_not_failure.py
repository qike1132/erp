"""恢复后 L1：库里「没有这张表」不等于「恢复失败」（审计批次4：P1-10）。

背景
----
`_verify_table_row_count` 的本意是：某表不在 manifest 里（`expected_rows == -1`）
→ L1 记「不确定」，不计 mismatch。但实现先发 `COUNT(*)`，表不存在时 `_in_savepoint`
捕获异常返回 `ok=False`，于是提前 return `{'pass': False, 'indeterminate': True}`，
**永远走不到 `expected_rows < 0 → None` 那条分支**。

后果（灾难现场）：把一份早于某表创建的合法备份恢复回来 → 那张表当然不存在 →
L1 判 fail → `_build_verification_report` 计入 `l1_mismatch` → `overall_pass=False`
→ 报告写「验证失败」。运维按报告去查「哪些表数据不对」，查到的其实是「备份里
本来就没有这张表」，真正的缺口反而被这层固定误报掩盖。

修法：COUNT 失败时先用 pg_class 分辨「表不存在」与「数不出来」，再按「这份备份
是否本应包含它」分流 —— 只有「备份里有数据、恢复后没表」才是确定失败。
"""
from __future__ import annotations

from types import SimpleNamespace

from sqlalchemy.exc import SQLAlchemyError

from fastapi_app.services.backup.verify.core import (
    _build_verification_report,
    _verify_table_row_count,
    verify_restore,
)

_TABLE = SimpleNamespace(name='order_item')


class _Nested:
    """`AsyncSession.begin_nested()` 的最小替身（回滚语义由 _in_savepoint 自己兜）。"""

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False


class _CountResult:
    def __init__(self, value: int):
        self._value = value

    def scalar(self):
        return self._value


class _PresenceResult:
    def __init__(self, present: bool):
        self._present = present

    def first(self):
        return (1,) if self._present else None


class _FakeDb:
    """COUNT(*) 抛错；pg_class 探测按 ``present`` 返回；记录执行过的 SQL。"""

    def __init__(self, *, present: bool, count_rows: int | None = None):
        self.present = present
        self.count_rows = count_rows
        self.executed: list[str] = []

    def begin_nested(self):
        return _Nested()

    async def execute(self, statement, params=None):
        sql = str(statement)
        self.executed.append(sql)
        if 'COUNT(*)' in sql:
            if self.count_rows is None:
                raise SQLAlchemyError('relation "order_item" does not exist')
            return _CountResult(self.count_rows)
        assert 'pg_class' in sql, f'探测必须查 pg_class（不按权限过滤）：{sql}'
        return _PresenceResult(self.present)


async def test_missing_table_absent_from_manifest_is_indeterminate():
    """备份早于该表创建（manifest 无此表，expected=-1）→ 不确定，不是 fail。"""
    db = _FakeDb(present=False)

    entry, table_exists = await _verify_table_row_count(db, _TABLE, '"order_item"', -1)

    assert table_exists is False
    assert entry['pass'] is None, f'缺表且备份不含它，不能判 fail（审计 P1-10）：{entry}'
    assert entry.get('missing_table') is True
    assert entry.get('note')


async def test_missing_table_with_expected_rows_is_real_failure():
    """备份里有数据、恢复后却没这张表 → 这才是真失败（不能被放宽掉）。"""
    db = _FakeDb(present=False)

    entry, table_exists = await _verify_table_row_count(db, _TABLE, '"order_item"', 5)

    assert table_exists is False
    assert entry['pass'] is False
    assert entry.get('missing_table') is True


async def test_missing_table_with_zero_expected_rows_is_indeterminate():
    """备份里该表 0 行：缺表与 0 行在 L1 不可区分 → 不确定。"""
    db = _FakeDb(present=False)

    entry, _ = await _verify_table_row_count(db, _TABLE, '"order_item"', 0)

    assert entry['pass'] is None


async def test_count_failure_with_table_present_stays_failure():
    """表在、但 COUNT 数不出来（权限/超时/连接）→ 仍判 fail + indeterminate。

    放宽的只有「表确实不存在」这一种；「没数过」不能记成通过。
    """
    db = _FakeDb(present=True)

    entry, _ = await _verify_table_row_count(db, _TABLE, '"order_item"', 5)

    assert entry['pass'] is False
    assert entry.get('indeterminate') is True
    assert 'missing_table' not in entry


async def test_present_table_matches_expected_rows():
    db = _FakeDb(present=True, count_rows=5)

    entry, table_exists = await _verify_table_row_count(db, _TABLE, '"order_item"', 5)

    assert table_exists is True
    assert entry['pass'] is True and entry['actual'] == 5


async def test_report_does_not_count_indeterminate_as_mismatch():
    """汇总层：pass=None 记「不确定」，不得进 l1_mismatch / 不得否决 overall_pass。"""
    report = _build_verification_report(
        [{'table': 'order_item', 'expected': -1, 'actual': -1,
          'pass': None, 'missing_table': True, 'note': '恢复后库中不存在该表'}],
        [], [], {}, [], '',
    )

    assert report['l1_row_count']['mismatch'] == []
    assert report['l1_row_count']['indeterminate'] == 1
    assert report['overall_pass'] is True, (
        '恢复一份不含该表的旧备份不该被判「验证失败」（审计 P1-10）'
    )


async def test_verify_restore_restoring_older_backup_passes():
    """整链路：manifest 缺某表 + 该表在恢复后的库里不存在 → overall_pass 为 True。"""
    from fastapi_app.shared_models import Base

    target = 'order_item'
    assert target in {str(t.name) for t in Base.metadata.sorted_tables}
    class _WholeDb(_FakeDb):
        """除目标表外，其余表都正常存在且行数对得上。"""

        def __init__(self):
            super().__init__(present=True, count_rows=0)
            self._target = target

        async def execute(self, statement, params=None):
            sql = str(statement)
            if 'COUNT(*)' in sql and f'"{self._target}"' in sql:
                self.executed.append(sql)
                raise SQLAlchemyError('relation does not exist')
            if 'pg_class' in sql:
                self.executed.append(sql)
                return _PresenceResult(False)
            return await super().execute(statement, params)

    manifest_tables = {
        str(t.name): {'rows': 0}
        for t in Base.metadata.sorted_tables
        if str(t.name) != target
    }

    report = await verify_restore(_WholeDb(), manifest_tables, {}, None)

    assert report['l1_row_count']['mismatch'] == []
    assert report['overall_pass'] is True, f'报告: {report["l1_row_count"]}'


async def test_relation_probe_uses_pg_class():
    """探测必须走 pg_class：information_schema.tables 按权限过滤，会把「没权限」当「没表」。"""
    db = _FakeDb(present=True)

    await _verify_table_row_count(db, _TABLE, '"order_item"', 5)

    assert any('pg_class' in s for s in db.executed), f'未发出 pg_class 探测：{db.executed}'
    assert not any('information_schema' in s for s in db.executed)
