"""AUD-03（2026-10-24 审计）回归锁：pg_dump 不可用的 JSON 降级必须显性化。

原先降级只记 warning：manifest 无 dump_format、evaluate_backup_completeness
仍判 success、无任何告警——灾难恢复能力静默失效（JSON 包不含 schema、无法
空库恢复），且 7 天保留期后可用的 pg_dump 包被清理光。

修复后（本文件锁定）：
1. manifest 自述 dump_format（sql 默认 / json 降级）；
2. evaluate 对 dump_format=json 判 partial（旧产物无该字段不回溯改判）；
3. 降级发生时发 alert_service 告警（warning 级）。
"""
# metrics/alert_service.py 内有同名单例实例 alert_service，且 metrics/__init__
# 把实例 re-export 到包命名空间——`from ... import alert_service` 拿到的是实例。
# 用 importlib 显式取模块再取实例。
import importlib
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi_app.services.backup.records import evaluate_backup_completeness

_alert_module = importlib.import_module('fastapi_app.services.backup.metrics.alert_service')


def _patch_alert(monkeypatch, impl):
    monkeypatch.setattr(_alert_module.alert_service, 'send_alert', impl)


def test_manifest_records_dump_format():
    from fastapi_app.services.backup.orchestration.core import _build_manifest

    user = SimpleNamespace(username='tester', id=1)
    manifest = _build_manifest(
        user, 'remark', partial=False, include_set=set(), exclude_set=set(),
        dump_info={'format': 'json', 'pg_version': '', 'db_name': 'x',
                   'dump_size': 1, 'duration_seconds': 0},
        baseline_at='', table_stats={}, count_failed_tables=[],
        coverage={'complete': True}, checksums={}, fingerprints={},
        snapshot_schema={},
    )
    assert manifest['dump_format'] == 'json'
    # pg_dump 正常路径（无 format 字段）默认 sql
    manifest2 = _build_manifest(
        user, 'remark', partial=False, include_set=set(), exclude_set=set(),
        dump_info={'pg_version': '18', 'db_name': 'x', 'dump_size': 1,
                   'duration_seconds': 1},
        baseline_at='', table_stats={}, count_failed_tables=[],
        coverage={'complete': True}, checksums={}, fingerprints={},
        snapshot_schema={},
    )
    assert manifest2['dump_format'] == 'sql'


def test_evaluate_flags_json_degraded_as_partial():
    status, detail = evaluate_backup_completeness(
        {'dump_format': 'json', 'coverage': {'complete': True}})
    assert status == 'partial'
    assert 'JSON' in detail and 'schema' in detail


def test_evaluate_keeps_legacy_manifest_success():
    """旧产物无 dump_format 字段：不回溯改判（保持其历史状态）。"""
    status, _detail = evaluate_backup_completeness({'coverage': {'complete': True}})
    assert status == 'success'


def test_evaluate_json_degraded_with_failed_tables_lists_them():
    status, detail = evaluate_backup_completeness(
        {'dump_format': 'json', 'failed_tables': ['orders'],
         'coverage': {'complete': True}})
    assert status == 'partial'
    assert 'orders' in detail


def test_degradation_sends_alert(monkeypatch, tmp_path):
    """_export_database 捕获 pg_dump 失败后必须发 alert_service 告警。"""
    import asyncio

    from fastapi_app.services.backup.orchestration import core as orch

    alerts = []

    async def _fake_alert(**kwargs):
        alerts.append(kwargs)
        return True

    _patch_alert(monkeypatch, _fake_alert)
    # run_pg_dump 抛 RuntimeError（pg_dump 不可用的真实形态）
    monkeypatch.setattr(orch, 'run_pg_dump',
                        AsyncMock(side_effect=RuntimeError('pg_dump: command not found')))
    # JSON 兜底导出走桩（避免真实 DB）
    monkeypatch.setattr(orch, 'execute_legacy_backup_to_bytes',
                        AsyncMock(return_value=b'{}'))

    db = AsyncMock()
    user = SimpleNamespace(id=1, username='tester')
    dump_info, pg_ok, _ = asyncio.run(orch._export_database(
        db, user, 'remark', tmp_path, 'snap-1', partial=False,
        tables=None, exclude_tables=None, progress_cb=None))

    assert pg_ok is False
    assert dump_info['format'] == 'json'
    assert len(alerts) == 1, '降级必须发告警（AUD-03）'
    assert alerts[0]['task_name'] == 'pg_dump_unavailable'
    assert alerts[0]['severity'] == 'warning'
    assert 'JSON' in alerts[0]['error']


def test_degradation_alert_failure_does_not_break_backup(monkeypatch, tmp_path):
    """告警通道故障不得中断备份（防御分支）。"""

    import asyncio

    from fastapi_app.services.backup.orchestration import core as orch

    async def _broken_alert(**kwargs):
        raise RuntimeError('smtp down')

    _patch_alert(monkeypatch, _broken_alert)
    monkeypatch.setattr(orch, 'run_pg_dump',
                        AsyncMock(side_effect=RuntimeError('no pg_dump')))
    monkeypatch.setattr(orch, 'execute_legacy_backup_to_bytes',
                        AsyncMock(return_value=b'{}'))

    db = AsyncMock()
    user = SimpleNamespace(id=1, username='tester')
    dump_info, pg_ok, _ = asyncio.run(orch._export_database(
        db, user, 'remark', tmp_path, 'snap-1', partial=False,
        tables=None, exclude_tables=None, progress_cb=None))
    assert pg_ok is False and dump_info['format'] == 'json'


def test_partial_table_backup_is_json_but_not_degraded_alert(monkeypatch, tmp_path):
    """表级备份固定走 JSON（设计如此），不触发 pg_dump 告警。"""
    import asyncio

    from fastapi_app.services.backup.orchestration import core as orch

    alerts = []

    async def _fake_alert(**kwargs):
        alerts.append(kwargs)
        return True

    _patch_alert(monkeypatch, _fake_alert)
    monkeypatch.setattr(orch, 'execute_legacy_backup_to_bytes',
                        AsyncMock(return_value=b'{}'))

    db = AsyncMock()
    user = SimpleNamespace(id=1, username='tester')
    _, _, _ = asyncio.run(orch._export_database(
        db, user, 'remark', tmp_path, 'snap-1', partial=True,
        tables={'order'}, exclude_tables=None, progress_cb=None))
    assert alerts == [], '表级 JSON 是设计行为，不得告警'
