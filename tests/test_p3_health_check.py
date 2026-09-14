"""P3级修复的集成验证测试"""
import asyncio
import inspect
from pathlib import Path

import pytest

# 备份端点包（原单文件 backup.py 已拆分为子模块包）
_BACKUP_PKG = Path(__file__).resolve().parent.parent / 'fastapi_app' / 'api' / 'v1' / 'endpoints' / 'backup'
# 备份服务包（原单文件 backup_service.py 已拆分为 services/backup/ 子包）
_BACKUP_SERVICE_PKG = Path(__file__).resolve().parent.parent / 'fastapi_app' / 'services' / 'backup'


def test_database_check_is_async():
    """P3-2: 健康检查中的数据库检查函数现在应该是 async"""
    from fastapi_app.api.v1.endpoints.backup.validation import _check_database
    assert inspect.iscoroutinefunction(_check_database), \
        "_check_database 应该是 async 函数"


def test_redis_check_is_async():
    """P3-2: 健康检查中的 Redis 检查函数现在应该是 async"""
    from fastapi_app.api.v1.endpoints.backup.validation import _check_redis
    assert inspect.iscoroutinefunction(_check_redis), \
        "_check_redis 应该是 async 函数"


def test_no_loop_run_until_complete_in_backup():
    """P3-2: backup 端点包中不应再使用 loop.run_until_complete 异步反模式"""
    for py_file in sorted(_BACKUP_PKG.glob('*.py')):
        source = py_file.read_text(encoding='utf-8')
        assert 'loop.run_until_complete' not in source, \
            f"{py_file.name} 中不应使用 loop.run_until_complete（async反模式）"


def test_redis_wrapper_ping_exists():
    """P3-2: redis_wrapper 中应存在 ping 函数供健康检查使用"""
    from fastapi_app.core.redis_wrapper import ping
    assert inspect.iscoroutinefunction(ping)


def test_health_check_endpoint_uses_await():
    """P3-2: health_check 端点应使用 await 调用 check 函数（不经 runner 中转）"""
    source = (_BACKUP_PKG / 'validation.py').read_text(encoding='utf-8')
    assert 'await _check_database()' in source, \
        "health_check 应该用 await 直接调用 _check_database"
    assert 'await _check_redis()' in source, \
        "health_check 应该用 await 直接调用 _check_redis"


@pytest.mark.asyncio
async def test_health_check_runner_is_callable():
    """P3-2: health_check 的 _check_database 可以被 await 并返回 (dict, issues)"""
    from fastapi_app.api.v1.endpoints.backup.validation import _check_database
    # 由于数据库可能未连接，使用短超时来限制等待时间
    try:
        result = await asyncio.wait_for(_check_database(), timeout=5.0)
        # 现返回 (check_result, issues) 二元组
        assert len(result) == 2
        check_result, _issues = result
        assert 'status' in check_result
    except (TimeoutError, OSError):
        # 数据库不可用是允许的（开发环境无DB），验证函数能被await即可
        pass


def test_no_deprecated_get_event_loop_in_backup_service():
    """P3-5: backup 服务包中不应使用已废弃的 asyncio.get_event_loop()"""
    found_running_loop = False
    for py_file in sorted(_BACKUP_SERVICE_PKG.glob('*.py')):
        source = py_file.read_text(encoding='utf-8')
        assert 'asyncio.get_event_loop()' not in source, \
            f"{py_file.name} 中应使用 asyncio.get_running_loop() 而非已废弃的 get_event_loop()"
        if 'asyncio.get_running_loop()' in source:
            found_running_loop = True
    assert found_running_loop, \
        "backup 服务包中应存在 asyncio.get_running_loop() 的使用（records/restore 线程卸载）"
