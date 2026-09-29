"""迁移 056：补回被删的备份例行调度 + 纠正漂移的增量时刻。

背景（/backup 上线前审计，生产库实测）
--------------------------------------
生产 `backup_schedule` 只剩 2 行，且「每日增量备份」被改成与全量同一时刻
（`0 2 * * *`），完整性巡检 / 清理 / 月度灾备演练三行**整行缺失**。
删除路径只有 UI 的 `DELETE /backup/schedule/{id}`，故属界面误删造成的漂移。

本文件把迁移的两个要求钉死：
1. 缺失的 3 条按 name 补回，且 cleanup 以 **disabled** 落库（它会真删备份文件）；
2. 增量时刻**只纠正漂移值**，不覆盖运维另行设定的时刻；重复执行幂等。
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
    / 'migrations' / 'versions' / 'pg_standalone_056_restore_backup_schedules.py'
)

_INCREMENTAL = '每日增量备份'
_INTEGRITY = '备份完整性巡检'
_CLEANUP = '备份清理'
_DISASTER = '月度灾备恢复演练'

_EXPECTED_INCREMENTAL_CRON = '0 6,10,14,18,22 * * *'
_SEEDED_INCREMENTAL_CRON = '0 6,10,14,18,22 * * *'


def _load_migration_module():
    spec = importlib.util.spec_from_file_location('migration_056', MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _make_db(rows: list[tuple[str, str, str, int]]):
    """建一个 sqlite 内存库，backup_schedule 预置给定行，并绑定真实 Operations。"""
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
    for row in rows:
        conn.execute(
            sa.text(
                'INSERT INTO backup_schedule (name, task_type, cron_expr, enabled)'
                ' VALUES (:n, :t, :c, :e)'
            ),
            {'n': row[0], 't': row[1], 'c': row[2], 'e': row[3]},
        )
    return engine, conn


def _ops(conn) -> Operations:
    return Operations(MigrationContext.configure(conn))


def _rows(conn) -> dict[str, dict]:
    result = conn.execute(sa.text('SELECT name, task_type, cron_expr, enabled FROM backup_schedule'))
    return {r[0]: {'task_type': r[1], 'cron_expr': r[2], 'enabled': bool(r[3])} for r in result}


# 生产实测的漂移状态
_DRIFTED = [
    ('每日全量备份', 'full', '0 2 * * *', 1),
    (_INCREMENTAL, 'incremental', '0 2 * * *', 1),
]

# 036/037 种子跑完后的完整状态（新部署）
_INTACT = [
    ('每日全量备份', 'full', '0 2 * * *', 1),
    (_INCREMENTAL, 'incremental', _SEEDED_INCREMENTAL_CRON, 1),
    (_INTEGRITY, 'integrity_check', '0 3 * * *', 1),
    (_CLEANUP, 'cleanup', '0 4 * * *', 1),
    (_DISASTER, 'disaster_recovery_test', '30 3 1 * *', 1),
]


def test_restores_missing_schedules_with_cleanup_disabled() -> None:
    mod = _load_migration_module()
    engine, conn = _make_db(_DRIFTED)
    try:
        mod.op = _ops(conn)
        mod.upgrade()

        rows = _rows(conn)
        assert len(rows) == 5, f'应补回 3 条，实际 {sorted(rows)}'
        assert rows[_INTEGRITY]['task_type'] == 'integrity_check'
        assert rows[_INTEGRITY]['cron_expr'] == '0 3 * * *'
        assert rows[_INTEGRITY]['enabled'] is True
        assert rows[_DISASTER]['task_type'] == 'disaster_recovery_test'
        assert rows[_DISASTER]['cron_expr'] == '30 3 1 * *'
        assert rows[_DISASTER]['enabled'] is True
        assert rows[_CLEANUP]['cron_expr'] == '0 4 * * *'
        assert rows[_CLEANUP]['enabled'] is False, (
            'cleanup 会真删备份文件，上线阶段必须以 disabled 落库，由人显式开启'
        )
    finally:
        conn.close()
        engine.dispose()


def test_fixes_drifted_incremental_cron() -> None:
    mod = _load_migration_module()
    engine, conn = _make_db(_DRIFTED)
    try:
        mod.op = _ops(conn)
        mod.upgrade()

        assert _rows(conn)[_INCREMENTAL]['cron_expr'] == _EXPECTED_INCREMENTAL_CRON
    finally:
        conn.close()
        engine.dispose()


def test_does_not_override_a_deliberate_incremental_time() -> None:
    """只纠正漂移值 —— 运维另外设的时刻必须原样保留。"""
    mod = _load_migration_module()
    rows = [('每日全量备份', 'full', '0 2 * * *', 1), (_INCREMENTAL, 'incremental', '0 5,17 * * *', 1)]
    engine, conn = _make_db(rows)
    try:
        mod.op = _ops(conn)
        mod.upgrade()

        assert _rows(conn)[_INCREMENTAL]['cron_expr'] == '0 5,17 * * *'
    finally:
        conn.close()
        engine.dispose()


def test_is_idempotent() -> None:
    mod = _load_migration_module()
    engine, conn = _make_db(_DRIFTED)
    try:
        mod.op = _ops(conn)
        mod.upgrade()
        mod.upgrade()

        rows = _rows(conn)
        assert len(rows) == 5, f'重复执行不得插入重复行：{sorted(rows)}'
    finally:
        conn.close()
        engine.dispose()


def test_leaves_a_fresh_install_untouched() -> None:
    """新部署（036/037 已种全）跑本迁移应当几乎无副作用。

    特别是不得把 cleanup 从 enabled 改成 disabled —— 那会改变新安装的默认行为。
    本迁移的角色是**修复漂移**，不是重新定义默认值。
    """
    mod = _load_migration_module()
    engine, conn = _make_db(_INTACT)
    try:
        mod.op = _ops(conn)
        mod.upgrade()

        rows = _rows(conn)
        assert len(rows) == 5
        assert rows[_CLEANUP]['enabled'] is True
        assert rows[_INCREMENTAL]['cron_expr'] == _SEEDED_INCREMENTAL_CRON
    finally:
        conn.close()
        engine.dispose()


def test_downgrade_removes_only_what_it_added() -> None:
    mod = _load_migration_module()
    engine, conn = _make_db(_DRIFTED)
    try:
        mod.op = _ops(conn)
        mod.upgrade()
        mod.downgrade()

        rows = _rows(conn)
        assert sorted(rows) == sorted(['每日全量备份', _INCREMENTAL]), '回滚后应只剩原有两行'
        assert rows[_INCREMENTAL]['cron_expr'] == '0 2 * * *', '漂移值应被还原'
    finally:
        conn.close()
        engine.dispose()


def test_module_revision_chain() -> None:
    """修订号必须挂在当前 head 之后，否则迁移根本不会被应用。"""
    mod = _load_migration_module()

    assert mod.revision == 'pg_standalone_056_restore_backup_schedules'
    assert mod.down_revision == 'pg_standalone_055_remove_custom_order_country'


def test_seed_names_match_prior_migrations() -> None:
    """补种用的 name 必须与 036/037 完全一致，否则幂等判断会失效、插出重复行。"""
    mod = _load_migration_module()
    seeded = {row[0] for row in mod._MISSING_SEEDS}

    assert seeded == {_INTEGRITY, _CLEANUP, _DISASTER}


@pytest.mark.parametrize('name', [_INTEGRITY, _CLEANUP, _DISASTER])
def test_seed_task_types_are_known(name: str) -> None:
    """task_type 必须是调度器 TASK_TYPE_TO_FUNC 认得的类型，否则入队时被跳过。"""
    from fastapi_app.services.backup.schedule_service import TASK_TYPE_TO_FUNC

    mod = _load_migration_module()
    task_type = next(t for n, t, _c, _e in mod._MISSING_SEEDS if n == name)

    assert task_type in TASK_TYPE_TO_FUNC
