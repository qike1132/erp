"""
缓存管理模块
提供缓存清理和防缓存措施
"""
import logging
from functools import wraps
from flask import request, make_response
from app import db

_logger = logging.getLogger(__name__)


def no_cache(view_func):
    """
    防缓存装饰器
    添加HTTP响应头，防止浏览器和服务器缓存数据
    """
    @wraps(view_func)
    def decorated_function(*args, **kwargs):
        response = make_response(view_func(*args, **kwargs))
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate, max-age=0'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
        response.headers['Last-Modified'] = 'Mon, 26 Jul 1997 05:00:00 GMT'
        return response
    return decorated_function


def clear_cache_after_change():
    """
    数据变更后清除相关缓存的装饰器
    """
    def decorator(view_func):
        @wraps(view_func)
        def decorated_function(*args, **kwargs):
            result = view_func(*args, **kwargs)

            try:
                from utils.redis_cache import redis_cache

                redis_cache.delete_pattern('inventory:*')
                redis_cache.delete_pattern('stock:*')
                redis_cache.delete_pattern('order:*')
                redis_cache.delete_pattern('product:*')
                redis_cache.delete_pattern('report:*')
                redis_cache.delete_pattern('customer:*')

                # 不再调用 db.session.expire_all()，原因同 invalidate_cache_on_write

            except Exception as e:
                _logger.warning("清除缓存时出错: %s", e)

            return result
        return decorated_function
    return decorator


def invalidate_cache_on_write(response):
    """
    响应后缓存失效处理
    对 POST/PUT/DELETE/PATCH 且成功的请求, 按URL路径清除对应缓存
    在 create_app() 的 after_request 中调用
    """
    if request.method not in ('POST', 'PUT', 'DELETE', 'PATCH'):
        return response

    # 只对成功响应(2xx/3xx)做缓存失效
    if response.status_code >= 400:
        return response

    try:
        from utils.redis_cache import redis_cache

        path = request.path.lower()

        # 根据URL路径匹配缓存模式
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
            redis_cache.delete_pattern(pattern)

        # 不再调用 db.session.expire_all()
        # 原因：expire_all() 会使 SQLAlchemy Identity Map 中所有对象过期，
        # 导致后续请求访问时触发逐条 lazy-load (N+1 问题)。
        # Redis 缓存已清除，scoped_session 在请求结束后自动清理，
        # 写操作本身已 commit/flush，数据一致性无需额外 expire。

    except Exception as e:
        _logger.warning("缓存失效处理失败(path=%s): %s", request.path, e)

    return response


def clear_database_session_cache():
    """
    清除数据库session缓存
    注：Flask scoped_session 在每个请求结束后通过 db.session.remove() 自动清理，
    新请求获取全新 session，无需手动 expire_all()。
    此函数保留为空以维持调用兼容性。
    """
    pass


def add_random_param_to_url(url):
    """
    为URL添加随机参数，防止浏览器缓存
    """
    import time
    import random

    separator = '?' if '?' not in url else '&'
    return f"{url}{separator}_t={int(time.time())}&_r={random.randint(1, 1000000)}"


def ensure_session_committed():
    """
    确保数据库 session 已提交
    注：移除 expire_all()，原因同 clear_database_session_cache()。
    """
    try:
        db.session.commit()
    except Exception as e:
        _logger.warning("ensure_session_committed 出错: %s", e)
