"""/api/health 匿名响不应泄露运维细节。

匿名请求原本就能拿到 backup（备份路径/时间/大小）、audit_retention（归档目录、
保留期、最近清理结果）与 checks 结构；这些是内部运维信号，登录后才应可见。
匿名侧只保留 status/app 这类「服务是否活着」的最小信息。
"""
from __future__ import annotations

import pytest

from fastapi_app.core import health


class _PingableRedis:
    async def ping(self) -> bool:
        return True


@pytest.fixture()
def _healthy_dependencies(monkeypatch: pytest.MonkeyPatch):
    async def _db_ok() -> bool:
        return True

    async def _backup() -> dict:
        return {'ok': True, 'status': 'healthy', 'latest_backup_time': '2026-11-02T03:00:00'}

    def _audit() -> dict:
        return {'ok': True, 'status': 'healthy', 'archive_dir': '/secret/audit'}

    def _numbering_retention() -> dict:
        return {'ok': True, 'status': 'healthy', 'archive_dir': '/secret/numbering'}

    async def _redis():
        return _PingableRedis()

    monkeypatch.setattr(health, 'verify_db_connectivity', _db_ok)
    monkeypatch.setattr(health, '_backup_signal', _backup)
    monkeypatch.setattr(health, '_audit_retention_signal', _audit)
    monkeypatch.setattr(health, '_numbering_audit_retention_signal', _numbering_retention)
    monkeypatch.setattr(
        'fastapi_app.core.redis_client.get_async_redis_client', _redis,
    )
    health._health_cache.update(
        {'public_data': None, 'internal_data': None, 'cached_at': 0.0},
    )


@pytest.mark.asyncio
async def test_anonymous_health_hides_operational_detail(
    _healthy_dependencies,
) -> None:
    body = await health._build_fresh_health(None, [])
    assert 'backup' not in body
    assert 'audit_retention' not in body
    assert 'numbering_audit_retention' not in body
    assert 'checks' not in body
    assert body['status'] == 'healthy'


@pytest.mark.asyncio
async def test_authenticated_health_keeps_operational_detail(
    _healthy_dependencies,
) -> None:
    body = await health._build_fresh_health(42, [])
    assert 'backup' in body
    assert 'audit_retention' in body
    assert body['numbering_audit_retention']['archive_dir'] == '/secret/numbering'
    assert 'checks' in body


def test_numbering_retention_failure_degrades_health() -> None:
    assert health._resolve_status(
        True, True, True, numbering_audit_retention_ok=False,
    ) == 'degraded'


def test_cached_health_keeps_numbering_retention_for_authenticated_user() -> None:
    saved = dict(health._health_cache)
    health._health_cache['internal_data'] = {
        'numbering_audit_retention': {'ok': True, 'archive_dir': '/secret/numbering'},
    }
    try:
        body = health._health_from_cache({'status': 'healthy', 'app': 'erp'}, 42, [])
        assert body['numbering_audit_retention']['archive_dir'] == '/secret/numbering'
    finally:
        # 缓存是模块级全局；不还原会污染同会话后续用例的 fresh-health 断言。
        health._health_cache.update(saved)
