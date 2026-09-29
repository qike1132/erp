"""迁移 057：按 task_type 纠正与 02:00 全量撞车的增量调度时刻。

背景（生产实测）
----------------
056 按 **name**（`每日增量备份`）纠正增量时刻，但生产那行已被改名为
「自定义增量备份」⇒ 未命中，仍是 `0 2 * * *`，与每日全量同分钟。

name 是用户可改字段，不能当迁移的匹配键；本文件锁住 057 的两个要求：
1. 按 `task_type='incremental'` 匹配（改名也命中）；
2. 仍带 `cron_expr='0 2 * * *'` 取值守卫 —— 只纠撞车的行，不动别处。
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext

MIGRATION_PATH = (
    Path(__file__).resolve().parent.parent
    / 'migrations' / 'versions' / 'pg_standalone_057_fix_incremental_cron.py'
)

_COLLIDING = '0 2 * * *'
_EXPECTED = '0 6,10,14,18,22 * * *'


def _load_migration_module():
    spec = importlib.util.spec_from_file_location('migration_057', MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _make_db(rows: list[tuple[str, str, str, int]]):
    engine = sa.create_engine('sqlite://')
    conn = engine.connect()
    conn.execute(sa.text(
        'CREATE TABLE backup_schedule ('
        ' id INTEGER PRIMARY KEY AUTOINCREMENT,'
        ' name VARCHAR(100) NOT NULL,'
        ' task_type VARCHAR(30) NOT NULL,'
        ' cron_expr VARCHAR(100) NOT NULL,'
        ' enabled BOOLEAN NOT NULL DEFAULT 1)'
    ))
    for name, task_type, cron, enabled in rows:
        conn.execute(
            sa.text(
                'INSERT INTO backup_schedule (name, task_type, cron_expr, enabled)'
                ' VALUES (:n, :t, :c, :e)'
            ),
            {'n': name, 't': task_type, 'c': cron, 'e': enabled},
        )
    return engine, conn


def _crons(conn) -> dict[str, str]:
    out = {}
    for r in conn.execute(sa.text('SELECT name, cron_expr FROM backup_schedule ORDER BY id')):
        out[r[0]] = r[1]
    return out


# 生产实测状态：增量被改名为「自定义增量备份」，时刻与全量撞车
_RENAMED_AND_COLLIDING = [
    ('自定义增量备份', 'incremental', _COLLIDING, 1),
    ('每日全量备份', 'full', _COLLIDING, 1),
]


def test_fixes_renamed_incremental_row() -> None:
    """按 name 匹配会漏掉改名后的行 —— 这正是 057 存在的理由。"""
    mod = _load_migration_module()
    engine, conn = _make_db(_RENAMED_AND_COLLIDING)
    try:
        mod.op = Operations(MigrationContext.configure(conn))
        mod.upgrade()

        assert _crons(conn)['自定义增量备份'] == _EXPECTED
    finally:
        conn.close()
        engine.dispose()


def test_leaves_the_full_backup_alone() -> None:
    mod = _load_migration_module()
    engine, conn = _make_db(_RENAMED_AND_COLLIDING)
    try:
        mod.op = Operations(MigrationContext.configure(conn))
        mod.upgrade()

        assert _crons(conn)['每日全量备份'] == _COLLIDING, '全量的作息不在本迁移职责内'
    finally:
        conn.close()
        engine.dispose()


def test_does_not_touch_an_incremental_at_another_time() -> None:
    """取值守卫：增量若已被设成别的时刻，说明有人有意调过，不得覆盖。"""
    mod = _load_migration_module()
    engine, conn = _make_db([('自定义增量备份', 'incremental', '0 5,17 * * *', 1)])
    try:
        mod.op = Operations(MigrationContext.configure(conn))
        mod.upgrade()

        assert _crons(conn)['自定义增量备份'] == '0 5,17 * * *'
    finally:
        conn.close()
        engine.dispose()


def test_does_not_touch_other_task_types_at_0200() -> None:
    """只认 incremental：同一分钟的 full / cleanup 不该被本迁移改动。"""
    mod = _load_migration_module()
    engine, conn = _make_db([
        ('每日全量备份', 'full', _COLLIDING, 1),
        ('备份清理', 'cleanup', _COLLIDING, 1),
        ('备份完整性巡检', 'integrity_check', _COLLIDING, 1),
    ])
    try:
        mod.op = Operations(MigrationContext.configure(conn))
        mod.upgrade()

        assert set(_crons(conn).values()) == {_COLLIDING}
    finally:
        conn.close()
        engine.dispose()


def test_is_idempotent() -> None:
    mod = _load_migration_module()
    engine, conn = _make_db(_RENAMED_AND_COLLIDING)
    try:
        mod.op = Operations(MigrationContext.configure(conn))
        mod.upgrade()
        mod.upgrade()

        assert _crons(conn)['自定义增量备份'] == _EXPECTED
    finally:
        conn.close()
        engine.dispose()


def test_downgrade_restores_the_colliding_time() -> None:
    mod = _load_migration_module()
    engine, conn = _make_db(_RENAMED_AND_COLLIDING)
    try:
        mod.op = Operations(MigrationContext.configure(conn))
        mod.upgrade()
        mod.downgrade()

        assert _crons(conn)['自定义增量备份'] == _COLLIDING
    finally:
        conn.close()
        engine.dispose()


def test_downgrade_spares_a_time_changed_elsewhere() -> None:
    """升级后有人又把它调到别的时刻 → 回滚不得把对方的值改回去。"""
    mod = _load_migration_module()
    engine, conn = _make_db(_RENAMED_AND_COLLIDING)
    try:
        mod.op = Operations(MigrationContext.configure(conn))
        mod.upgrade()
        conn.execute(sa.text(
            "UPDATE backup_schedule SET cron_expr = '0 9 * * *' WHERE task_type = 'incremental'"
        ))
        mod.downgrade()

        assert _crons(conn)['自定义增量备份'] == '0 9 * * *'
    finally:
        conn.close()
        engine.dispose()


def test_revision_chain_follows_056() -> None:
    mod = _load_migration_module()

    assert mod.revision == 'pg_standalone_057_fix_incremental_cron'
    assert mod.down_revision == 'pg_standalone_056_restore_backup_schedules'


def test_expected_cron_matches_the_036_seed() -> None:
    """改回去的值必须与 036 种子一致，否则等于悄悄换了一套作息。"""
    mod = _load_migration_module()

    assert mod._EXPECTED_CRON == '0 6,10,14,18,22 * * *'


@pytest.mark.parametrize('name', ['incremental', 'full'])
def test_task_type_is_a_real_scheduler_type(name: str) -> None:
    from fastapi_app.services.backup.schedule_service import TASK_TYPE_TO_FUNC

    assert name in TASK_TYPE_TO_FUNC
