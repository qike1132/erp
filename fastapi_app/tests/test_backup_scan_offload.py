"""备份目录扫描必须离开事件循环（审计 M-07 回归）。

拦哪种错：`list_backup_files()` / `backup_freshness()` 会逐 zip 读 manifest、
逐 json 解析；若在 async 端点或 /api/health 里同步调用，备份文件多时会阻塞
整个 worker，健康探测还可能超过 prod_runner 的 5s 窗口被误判。
"""
from __future__ import annotations

import threading

from fastapi_app.api.v1.endpoints.backup import records as records_mod
from fastapi_app.core import health
from fastapi_app.services.backup import freshness


def _thread_recorder(calls: dict, key: str, value):
    def _inner(*_args, **_kwargs):
        calls[key] = threading.get_ident()
        return value
    return _inner


async def test_list_server_backups_runs_scan_off_event_loop(monkeypatch):
    main_thread = threading.get_ident()
    calls: dict = {}
    monkeypatch.setattr(
        records_mod.backup_service, 'list_backup_files',
        _thread_recorder(calls, 'thread', []),
    )

    result = await records_mod.list_server_backups(user=None)

    assert result == {'success': True, 'backups': [], 'total': 0}
    assert calls['thread'] != main_thread, '备份列表扫描必须在工作线程执行'


async def test_backup_status_runs_scan_off_event_loop(monkeypatch):
    main_thread = threading.get_ident()
    calls: dict = {}
    monkeypatch.setattr(
        records_mod.backup_service, 'get_backup_status',
        _thread_recorder(calls, 'thread', {'status': 'ok'}),
    )

    result = await records_mod.backup_status(user=None)

    assert result == {'status': 'ok'}
    assert calls['thread'] != main_thread, '备份状态扫描必须在工作线程执行'


async def test_health_backup_signal_runs_freshness_off_event_loop(monkeypatch):
    main_thread = threading.get_ident()
    calls: dict = {}

    def fake_freshness():
        calls['thread'] = threading.get_ident()
        return {'ok': True, 'age_hours': 1}

    async def fake_probe(timeout=1.0):
        return True

    monkeypatch.setattr(freshness, 'backup_freshness', fake_freshness)
    monkeypatch.setattr(
        'fastapi_app.core.arq_app.probe_worker_health_isolated', fake_probe,
    )

    result = await health._backup_signal()

    assert result == {'ok': True, 'age_hours': 1, 'arq_ok': True}
    assert calls['thread'] != main_thread, '健康检查的备份扫描必须在工作线程执行'
