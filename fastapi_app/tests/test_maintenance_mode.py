"""维护模式：客户端来源、失败节流、与自愈/退避的对接。

背景（2026-09-28）
------------------
`maintenance_middleware` 在**每个写请求**上都会读一次维护标志。它此前走
`backup_progress._get_redis()` → `core/redis_client.get_async_redis_client()`
—— 那是**另一个**模块级缓存客户端：既不参与自愈、也不参与退避。

症状是**测试日志**里反复出现 `读取维护模式失败: Event loop is closed`
（约 2.4k 条）。经核查，这些**全部来自进程内测试套件**：真正的生产 stdout
（logs/后端(uvicorn).out.log）在同期 0 条；根因是 `_async_redis_client`
这个无复位的模块级全局 × pytest 按函数切换 event loop。

⚠️ 因此本文件锁的是**代码层面的确定性质**，不是"生产故障回归"：
1. 客户端来源改为自愈客户端（`core/redis_wrapper.get_client`）；
2. 失败日志**按异常类型**节流（不同异常类型不得被静默吞掉）；
3. 成败都告知缓存管理器（成功复位退避、失败 arm 退避）。

⚠️ 刻意**不**给维护标志加本地缓存：它是还原期间禁止写入的安全闸门，
本地缓存会让它延迟生效，等于留下一个能写入的窗口。

⚠️ 范围外但更重要：`enter_maintenance()` / `exit_maintenance()` 目前**没有生产
调用方**（还原流程用的是 `acquire_restore_lock`），所以"还原期间禁止写入"这一
保证尚未落地 —— 那是待产品决策的缺口，不在本文件覆盖范围内。
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from fastapi_app.core import maintenance


class _FakeClient:
    def __init__(self, value=None, error: Exception | None = None):
        self.value = value
        self.error = error
        self.get_calls = 0

    async def get(self, key):
        self.get_calls += 1
        if self.error is not None:
            raise self.error
        return self.value

    async def set(self, *a, **k):
        if self.error is not None:
            raise self.error
        return True

    async def delete(self, *a, **k):
        if self.error is not None:
            raise self.error
        return 1


def test_get_client_uses_selfhealing_client(monkeypatch: pytest.MonkeyPatch) -> None:
    """必须走 redis_wrapper.get_client（自愈 + 退避），而不是另一个孤立客户端。

    这是本轮修复的核心：旧路径用的客户端既不自愈也不退避，出问题只能每请求干等。
    """
    import asyncio

    sentinel = object()
    calls: list[int] = []
    monkeypatch.setattr(
        'fastapi_app.core.redis_wrapper.get_client',
        lambda: calls.append(1) or sentinel,
    )

    assert asyncio.run(maintenance._get_client()) is sentinel
    assert calls, 'maintenance 未使用自愈客户端'


async def test_is_maintenance_mode_reads_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(maintenance, '_get_client', AsyncMock(return_value=_FakeClient(b'1')))

    assert await maintenance.is_maintenance_mode() is True


async def test_missing_client_is_not_maintenance(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(maintenance, '_get_client', AsyncMock(return_value=None))

    assert await maintenance.is_maintenance_mode() is False


async def test_failure_is_reported_to_cache_manager(monkeypatch: pytest.MonkeyPatch) -> None:
    """读失败要告知缓存管理器（连接类错误会 arm 退避，让后续请求短路）。"""
    from utils.redis_cache import redis_cache

    monkeypatch.setattr(
        maintenance, '_get_client',
        AsyncMock(return_value=_FakeClient(error=ConnectionError('boom'))),
    )
    reported: list[Exception] = []
    monkeypatch.setattr(redis_cache, 'note_command_failure', lambda exc: reported.append(exc))

    assert await maintenance.is_maintenance_mode() is False
    assert reported, '维护模式读取失败未告知缓存管理器'


async def test_success_is_reported_to_cache_manager(monkeypatch: pytest.MonkeyPatch) -> None:
    """读成功也要告知（复位退避），否则一次故障后窗口会一直挂着。"""
    from utils.redis_cache import redis_cache

    monkeypatch.setattr(maintenance, '_get_client', AsyncMock(return_value=_FakeClient(None)))
    noted: list[int] = []
    monkeypatch.setattr(redis_cache, 'note_command_success', lambda: noted.append(1))

    await maintenance.is_maintenance_mode()
    assert noted, '维护模式读取成功未告知缓存管理器'


async def test_failure_logging_is_throttled(monkeypatch: pytest.MonkeyPatch) -> None:
    """同一窗口内连续失败只记一条日志。

    维护模式在每个写请求上被读取 —— 不节流的话，Redis 故障期间日志会被刷爆
    （实测生产日志已累积 1486 条同类记录）。
    """
    monkeypatch.setattr(
        maintenance, '_get_client',
        AsyncMock(return_value=_FakeClient(error=ConnectionError('boom'))),
    )
    monkeypatch.setattr(maintenance, '_last_failure_log', None)

    logged: list[str] = []
    monkeypatch.setattr(maintenance.logger, 'warning', lambda *a, **k: logged.append(str(a)))

    for _ in range(20):
        await maintenance.is_maintenance_mode()

    assert len(logged) == 1, f'失败日志未节流，记录了 {len(logged)} 条'


async def test_failure_logging_recovers_after_window(monkeypatch: pytest.MonkeyPatch) -> None:
    """窗口过后应能再记一条（不能永久静音）。"""
    monkeypatch.setattr(
        maintenance, '_get_client',
        AsyncMock(return_value=_FakeClient(error=ConnectionError('boom'))),
    )
    logged: list[str] = []
    monkeypatch.setattr(maintenance.logger, 'warning', lambda *a, **k: logged.append(str(a)))

    monkeypatch.setattr(maintenance, '_last_failure_log', None)
    await maintenance.is_maintenance_mode()

    # 模拟窗口已过
    monkeypatch.setattr(maintenance, '_last_failure_log', None)
    await maintenance.is_maintenance_mode()

    assert len(logged) == 2, '窗口过后应能再次记录'


async def test_different_exception_class_is_not_suppressed(monkeypatch: pytest.MonkeyPatch) -> None:
    """不同**异常类型**必须照常记录，不得被上一个类型的窗口吞掉。

    单一全局时间戳的节流会静默丢日志 —— 而新出现的、往往更严重的错误
    （认证失败、协议错误）恰恰**不会**被退避短路，最需要被看见。
    """
    logged: list[str] = []
    monkeypatch.setattr(maintenance.logger, 'warning', lambda *a, **k: logged.append(str(a)))
    monkeypatch.setattr(maintenance, '_last_failure_log', None)

    monkeypatch.setattr(
        maintenance, '_get_client',
        AsyncMock(return_value=_FakeClient(error=ConnectionError('boom'))),
    )
    await maintenance.is_maintenance_mode()

    monkeypatch.setattr(
        maintenance, '_get_client',
        AsyncMock(return_value=_FakeClient(error=ValueError('different class'))),
    )
    await maintenance.is_maintenance_mode()

    assert len(logged) == 2, f'不同异常类型被错误节流，只记录了 {len(logged)} 条'


def test_sentinel_is_isolated_from_repo_logs() -> None:
    """回归（2026-10-30）：测试会话必须把哨兵重定向到临时目录。

    事故形态：`test_backup_m3::test_enter_sets_flag` 只 mock 了 Redis 客户端，
    `enter_maintenance()` 仍写真实 `logs/maintenance_mode.sentinel`；该用例若异常
    退出（未执行 `exit_maintenance()`），哨兵残留并在 2×TTL 内让后续**所有**写请求
    返回 503 MAINTENANCE —— 实测把一个 setup 异常放大成 609 条错误。
    """
    repo_sentinel = (
        Path(maintenance.__file__).resolve().parents[2]
        / 'logs'
        / 'maintenance_mode.sentinel'
    )
    assert repo_sentinel != maintenance._MAINTENANCE_SENTINEL, (
        '测试会话未隔离维护模式哨兵：崩溃用例会留下哨兵，导致后续写请求集体 503'
    )
    assert 'maintenance_sentinel' in str(maintenance._MAINTENANCE_SENTINEL), (
        f'哨兵未指向 pytest 临时目录：{maintenance._MAINTENANCE_SENTINEL}'
    )
