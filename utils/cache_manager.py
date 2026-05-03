"""
缓存管理模块
提供缓存清理和防缓存措施
"""
import logging
from functools import wraps

_logger = logging.getLogger(__name__)


def no_cache(view_func):
    """
    防缓存装饰器
    添加HTTP响应头，防止浏览器和服务器缓存数据
    """
    @wraps(view_func)
    def decorated_function(*args, **kwargs):
        result = view_func(*args, **kwargs)
        if isinstance(result, dict):
            from fastapi.responses import JSONResponse
            result = JSONResponse(content=result)

        if hasattr(result, 'headers'):
            result.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate, max-age=0'
            result.headers['Pragma'] = 'no-cache'
            result.headers['Expires'] = '0'
            result.headers['Last-Modified'] = 'Mon, 26 Jul 1997 05:00:00 GMT'
        return result
    return decorated_function


def clear_cache_after_change():
    """
    数据变更后清除相关缓存的装饰器（支持异步函数）
    """
    def decorator(view_func):
        import asyncio

        @wraps(view_func)
        async def async_decorated_function(*args, **kwargs):
            result = await view_func(*args, **kwargs)

            try:
                from utils.redis_cache import redis_cache
                await redis_cache.delete_pattern('inventory:*')
                await redis_cache.delete_pattern('stock:*')
                await redis_cache.delete_pattern('order:*')
                await redis_cache.delete_pattern('product:*')
                await redis_cache.delete_pattern('report:*')
                await redis_cache.delete_pattern('customer:*')
            except Exception as e:
                _logger.warning("清除缓存时出错: %s", e)

            return result

        @wraps(view_func)
        def sync_decorated_function(*args, **kwargs):
            result = view_func(*args, **kwargs)

            try:
                import asyncio as _aio
                try:
                    loop = _aio.get_running_loop()
                except RuntimeError:
                    loop = None

                from utils.redis_cache import redis_cache
                patterns = ['inventory:*', 'stock:*', 'order:*', 'product:*', 'report:*', 'customer:*']
                for pattern in patterns:
                    if loop and loop.is_running():
                        _aio.run_coroutine_threadsafe(redis_cache.delete_pattern(pattern), loop)
                    else:
                        _aio.run(redis_cache.delete_pattern(pattern))
            except Exception as e:
                _logger.warning("清除缓存时出错: %s", e)

            return result

        if asyncio.iscoroutinefunction(view_func):
            return async_decorated_function
        return sync_decorated_function
    return decorator


async def invalidate_cache_on_write(request, response):
    """
    响应后缓存失效处理（异步版本）
    对 POST/PUT/DELETE/PATCH 且成功的请求, 按URL路径清除对应缓存
    """
    if request.method not in ('POST', 'PUT', 'DELETE', 'PATCH'):
        return response

    if response.status_code >= 400:
        return response

    try:
        from utils.redis_cache import redis_cache

        path = request.url.path.lower()

        patterns_to_clear = []
        if '/product' in path or '/material' in path:
            patterns_to_clear.extend(['product:*', 'inventory:*'])
        if '/order' in path or '/staging' in path:
            patterns_to_clear.extend(['order:*'])
        if '/stock' in path or '/case' in path:
            patterns_to_clear.extend(['stock:*', 'inventory:*'])
        if '/customer' in path:
            patterns_to_clear.extend(['customer:*'])
        if '/report' in path:
            patterns_to_clear.extend(['report:*'])
        if '/approval' in path:
            patterns_to_clear.extend(['order:*', 'stock:*'])

        for pattern in patterns_to_clear:
            await redis_cache.delete_pattern(pattern)

    except Exception as e:
        _logger.warning("缓存失效处理失败(path=%s): %s", request.url.path, e)

    return response


def clear_database_session_cache():
    """
    清除数据库session缓存
    注：FastAPI 依赖注入在每个请求结束后通过依赖自动清理 session，
    新请求获取全新 session，无需手动 expire_all()。
    此函数保留为空以维持调用兼容性。
    """
    pass


def add_random_param_to_url(url):
    """
    为URL添加随机参数，防止浏览器缓存
    """
    import random
    import time

    separator = '?' if '?' not in url else '&'
    return f"{url}{separator}_t={int(time.time())}&_r={random.randint(1, 1000000)}"


def ensure_session_committed():
    """
    确保数据库 session 已提交
    注：FastAPI 依赖注入自动管理 session 生命周期。
    """
    try:
        from fastapi_app.core.database import SyncSession
        with SyncSession() as session:
            session.commit()
    except Exception as e:
        _logger.warning("ensure_session_committed 出错: %s", e)
