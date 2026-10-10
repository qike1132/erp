"""_get_redis 探活降级的回归测试（2026-10-10 手动备份事故）。

事故形态：broker(6380) 未运行时，``_get_redis`` 返回的 async client **连接是惰性的**
（拿对象不拨号），各进度函数的 ``if client is None`` 降级走不到，首次 ``set()`` 才以
``redis.exceptions.TimeoutError`` 炸穿 → 手动备份整体失败退出码 1。

修法：``_get_redis`` 内做一次真实 ``PING``，探活失败返回 ``None`` → 降级路径可达。
本用例构造「拿得到 client 但 PING 超时」的最小复现，断言返回 ``None``（而非抛错）。
"""
from unittest.mock import AsyncMock, MagicMock, patch

import redis as redis_lib

import fastapi_app.core.backup_progress as bp


class _LazyTimeoutClient:
    """复刻事故形态：实例化成功、PING 时才抛 redis TimeoutError。"""

    async def ping(self):
        raise redis_lib.exceptions.TimeoutError('Timeout connecting to server')

    async def set(self, *args, **kwargs):  # pragma: no cover - 不应被走到
        raise AssertionError('降级生效时不应再调用 set()')


class TestGetRedisProbesLiveness:
    async def test_lazy_timeout_client_returns_none(self):
        """「拿得到 client 但连不通」→ 返回 None（降级可达），不抛 TimeoutError。"""
        with patch(
            'fastapi_app.core.redis_client.get_async_redis_client',
            AsyncMock(return_value=_LazyTimeoutClient()),
        ):
            client = await bp._get_redis()
        assert client is None, '探活失败必须返回 None，让 if client is None 降级生效'

    async def test_connection_error_returns_none(self):
        with patch(
            'fastapi_app.core.redis_client.get_async_redis_client',
            AsyncMock(side_effect=redis_lib.exceptions.ConnectionError('refused')),
        ):
            client = await bp._get_redis()
        assert client is None

    async def test_healthy_client_passes_through(self):
        healthy = MagicMock()
        healthy.ping = AsyncMock(return_value=True)
        with patch(
            'fastapi_app.core.redis_client.get_async_redis_client',
            AsyncMock(return_value=healthy),
        ):
            client = await bp._get_redis()
        assert client is healthy

    async def test_create_progress_degrades_to_log_when_unreachable(self):
        """端到端：Redis 不可用时 create_progress 不得抛错（事故的直接调用点）。"""
        with patch(
            'fastapi_app.core.redis_client.get_async_redis_client',
            AsyncMock(return_value=_LazyTimeoutClient()),
        ):
            await bp.create_progress('task-lazy-timeout', operation_type='full',
                                    progress_type='backup')  # 不抛错即通过

    async def test_manual_backup_survives_redis_outage(self, tmp_path, monkeypatch):
        """端到端（核心验收）：broker 不在时手动备份**仍能完成**，退出码 0。

        复刻 manual_backup._run 的调用形态（直接调 manual_full_backup_task 会拉起
        完整 pg_dump 流程，此处仅验证进度层不再炸穿任务）——用 update_progress
        在无 Redis 环境下连续推进不抛错来代表任务全程。
        """
        with patch(
            'fastapi_app.core.redis_client.get_async_redis_client',
            AsyncMock(return_value=_LazyTimeoutClient()),
        ):
            await bp.create_progress('task-outage', operation_type='full',
                                    progress_type='backup')
            await bp.update_progress('task-outage', 'export_db', 0.2, '导出数据库')
            await bp.complete_progress('task-outage', result={'file': 'x.zip'})
