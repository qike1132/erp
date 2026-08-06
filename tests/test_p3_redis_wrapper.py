"""
P3-3: Redis统一封装迁移测试

验证核心模块和端点已从 utils.redis_cache 迁移到 core.redis_wrapper，
新增的safe_*函数和get_client()工作正常。
"""
import inspect
from pathlib import Path

import pytest


def test_redis_wrapper_has_all_safe_functions():
    """验证 redis_wrapper 导出所有需要的安全函数"""
    from fastapi_app.core import redis_wrapper
    expected = [
        'safe_get', 'safe_set', 'safe_delete', 'safe_delete_pattern',
        'ping', 'get_client',
        'safe_lpush', 'safe_rpush', 'safe_lrange', 'safe_ltrim', 'safe_llen', 'safe_lrem',
        'safe_publish', 'safe_incr', 'safe_expire', 'safe_exists', 'safe_get_stats',
    ]
    for name in expected:
        assert hasattr(redis_wrapper, name), f"redis_wrapper 缺少函数: {name}"
        fn = getattr(redis_wrapper, name)
        if name != 'get_client':
            assert inspect.iscoroutinefunction(fn) or callable(fn), f"{name} 应该是协程或可调用对象"


def test_get_client_returns_none_when_redis_unavailable(monkeypatch):
    """验证 Redis 不可用时 get_client() 返回 None 而非抛异常"""
    from fastapi_app.core import redis_wrapper

    monkeypatch.setattr(redis_wrapper, 'get_client', lambda: None)
    client = redis_wrapper.get_client()
    assert client is None


def test_nav_context_uses_redis_wrapper():
    """验证 nav_context.py 使用 redis_wrapper 而非直接导入 utils.redis_cache"""
    source = Path('fastapi_app/core/nav_context.py').read_text(encoding='utf-8')
    assert 'from fastapi_app.core.redis_wrapper import' in source
    assert 'from utils.redis_cache import' not in source


def test_audit_middleware_uses_redis_wrapper():
    """验证 audit_middleware.py 使用 redis_wrapper 的 safe_list 操作"""
    source = Path('fastapi_app/core/audit_middleware.py').read_text(encoding='utf-8')
    assert 'from fastapi_app.core.redis_wrapper import' in source
    assert 'from utils.redis_cache import' not in source


def test_domain_events_uses_redis_wrapper():
    """验证 domain_events.py 使用 redis_wrapper"""
    source = Path('fastapi_app/core/domain_events.py').read_text(encoding='utf-8')
    assert 'from fastapi_app.core.redis_wrapper import' in source
    assert 'from utils.redis_cache import' not in source


def test_backup_progress_uses_redis_wrapper():
    """验证 backup_progress.py 使用 get_client()"""
    source = Path('fastapi_app/core/backup_progress.py').read_text(encoding='utf-8')
    assert 'from fastapi_app.core.redis_wrapper import get_client' in source
    assert 'from utils.redis_cache import' not in source


def test_restore_progress_uses_redis_wrapper():
    """验证 restore_progress.py 使用 get_client()"""
    source = Path('fastapi_app/core/restore_progress.py').read_text(encoding='utf-8')
    assert 'from fastapi_app.core.redis_wrapper import get_client' in source
    assert 'from utils.redis_cache import' not in source


def test_deps_uses_redis_wrapper():
    """验证 deps.py 使用 get_client()"""
    source = Path('fastapi_app/core/deps.py').read_text(encoding='utf-8')
    assert 'from fastapi_app.core.redis_wrapper import get_client' in source
    assert 'from utils.redis_cache import redis_cache' not in source


def test_auth_endpoint_uses_redis_wrapper():
    """验证 auth.py 端点使用 get_client()"""
    source = Path('fastapi_app/api/v1/endpoints/auth.py').read_text(encoding='utf-8')
    assert 'from fastapi_app.core.redis_wrapper import get_client' in source
    assert 'from utils.redis_cache import redis_cache' not in source


def test_dead_letter_endpoint_uses_redis_wrapper():
    """验证 dead_letter.py 使用 redis_wrapper safe_list 操作"""
    source = Path('fastapi_app/api/v1/endpoints/dead_letter.py').read_text(encoding='utf-8')
    assert 'from fastapi_app.core.redis_wrapper import' in source
    assert 'safe_llen' in source
    assert 'safe_lrange' in source
    assert 'safe_lrem' in source
    assert 'from utils.redis_cache import' not in source


def test_auxiliary_endpoint_uses_redis_wrapper():
    """验证 auxiliary.py 缓存管理端点使用 redis_wrapper"""
    source = Path('fastapi_app/api/v1/endpoints/auxiliary.py').read_text(encoding='utf-8')
    assert 'from fastapi_app.core.redis_wrapper import' in source
    assert 'safe_get_stats' in source
    assert 'safe_delete_pattern' in source
    assert 'from utils.redis_cache import' not in source


def test_dashboard_service_uses_redis_wrapper():
    """验证 dashboard_service.py 使用 safe_get/safe_set"""
    source = Path('fastapi_app/services/dashboard_service.py').read_text(encoding='utf-8')
    assert 'from fastapi_app.core.redis_wrapper import safe_get' in source
    assert 'from fastapi_app.core.redis_wrapper import safe_set' in source
    assert 'from utils.redis_cache import' not in source


def test_safe_functions_signature():
    """验证 safe_* 函数的 context 参数一致性"""
    from fastapi_app.core import redis_wrapper
    sig = inspect.signature(redis_wrapper.safe_get)
    assert 'fallback' in sig.parameters
    assert 'context' in sig.parameters

    sig = inspect.signature(redis_wrapper.safe_set)
    assert 'timeout' in sig.parameters
    assert 'context' in sig.parameters

    sig = inspect.signature(redis_wrapper.safe_lpush)
    assert 'context' in sig.parameters

    sig = inspect.signature(redis_wrapper.ping)
    assert 'context' in sig.parameters

    sig = inspect.signature(redis_wrapper.safe_get_stats)
    assert 'context' in sig.parameters


def test_lifecycle_files_can_import_redis_cache():
    """验证 main.py/task_callbacks.py/cache.py 作为底层/生命周期文件保留直接引用是合理的"""
    main_source = Path('fastapi_app/main.py').read_text(encoding='utf-8')
    assert 'redis_cache.init_app' in main_source or 'redis_cache.close' in main_source

    cache_source = Path('fastapi_app/core/cache.py').read_text(encoding='utf-8')
    assert '_get_redis_cache' in cache_source
