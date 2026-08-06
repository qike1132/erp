"""P3级修复的集成验证测试"""
import asyncio
import inspect

import pytest


def test_database_check_is_async():
    """P3-2: 健康检查中的数据库检查函数现在应该是 async"""
    from fastapi_app.api.v1.endpoints.backup import _check_database
    assert inspect.iscoroutinefunction(_check_database), \
        "_check_database 应该是 async 函数"


def test_redis_check_is_async():
    """P3-2: 健康检查中的 Redis 检查函数现在应该是 async"""
    from fastapi_app.api.v1.endpoints.backup import _check_redis
    assert inspect.iscoroutinefunction(_check_redis), \
        "_check_redis 应该是 async 函数"


def test_no_loop_run_until_complete_in_backup():
    """P3-2: backup.py 中不应再使用 loop.run_until_complete 异步反模式"""
    from fastapi_app.api.v1.endpoints import backup
    source = inspect.getsource(backup)
    assert 'loop.run_until_complete' not in source, \
        "backup.py 中不应使用 loop.run_until_complete（async反模式）"


def test_redis_wrapper_ping_exists():
    """P3-2: redis_wrapper 中应存在 ping 函数供健康检查使用"""
    from fastapi_app.core.redis_wrapper import ping
    assert inspect.iscoroutinefunction(ping)


def test_health_check_endpoint_uses_await():
    """P3-2: health_check 端点应使用 await 调用 check 函数"""
    from fastapi_app.api.v1.endpoints import backup
    source = inspect.getsource(backup)
    # 确认 health_check 函数中有 'await runner()' 调用
    assert 'await runner()' in source, \
        "health_check 应该用 await runner() 调用 check 函数"


@pytest.mark.asyncio
async def test_health_check_runner_is_callable():
    """P3-2: health_check 端点的 check_runners 中的 runner 可以被 await"""
    from fastapi_app.api.v1.endpoints.backup import _check_database, _check_redis
    # 由于数据库/Redis可能未连接，使用短超时来限制等待时间
    try:
        result = await asyncio.wait_for(_check_database(), timeout=5.0)
        assert len(result) == 3
        check_result, issues, severity = result
        assert 'status' in check_result
    except (asyncio.TimeoutError, OSError):
        # 数据库不可用是允许的（开发环境无DB），验证函数能被await即可
        pass


def test_no_deprecated_get_event_loop_in_backup_service():
    """P3-5: backup_service.py 中不应使用已废弃的 asyncio.get_event_loop()"""
    from pathlib import Path
    source = Path('fastapi_app/services/backup_service.py').read_text(encoding='utf-8')
    assert 'asyncio.get_event_loop()' not in source, \
        "backup_service.py 中应使用 asyncio.get_running_loop() 而非已废弃的 get_event_loop()"
    assert 'asyncio.get_running_loop()' in source
