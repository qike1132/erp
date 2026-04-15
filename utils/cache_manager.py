"""
缓存管理模块
提供缓存清理和防缓存措施
"""
from functools import wraps
from flask import request, make_response
from app import db


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

                db.session.expire_all()

            except Exception as e:
                print(f"清除缓存时出错: {e}")

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

        # 有任何数据变更时刷新DB session
        if patterns_to_clear:
            db.session.expire_all()

    except Exception:
        pass  # 缓存失效失败不应影响正常响应

    return response


def clear_database_session_cache():
    """
    清除数据库session缓存
    确保每次查询都从数据库获取最新数据
    """
    try:
        db.session.expire_all()
    except Exception as e:
        print(f"清除数据库session缓存时出错: {e}")


def add_random_param_to_url(url):
    """
    为URL添加随机参数，防止浏览器缓存
    """
    import time
    import random

    separator = '?' if '?' not in url else '&'
    return f"{url}{separator}_t={int(time.time())}&_r={random.randint(1, 1000000)}"


def force_refresh_db():
    """
    强制刷新数据库查询
    """
    try:
        db.session.commit()
        db.session.expire_all()
    except Exception:
        pass
