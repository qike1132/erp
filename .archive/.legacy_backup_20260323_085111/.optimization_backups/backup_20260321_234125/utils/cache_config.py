"""
缓存系统配置
提供查询结果缓存和热点数据缓存
"""
from flask_caching import Cache
import os


def setup_cache(app):
    """
    配置缓存系统
    
    Args:
        app: Flask应用实例
    
    Returns:
        Cache: 缓存实例
    """
    # 根据环境选择缓存类型
    cache_type = os.getenv('CACHE_TYPE', 'SimpleCache')
    
    cache_config = {
        'CACHE_TYPE': cache_type,
        'CACHE_DEFAULT_TIMEOUT': 300,  # 默认缓存5分钟
    }
    
    # Redis缓存配置
    if cache_type == 'RedisCache':
        redis_host = os.getenv('REDIS_HOST', 'localhost')
        redis_port = os.getenv('REDIS_PORT', 6379)
        redis_db = os.getenv('REDIS_DB', 0)
        
        cache_config.update({
            'CACHE_REDIS_HOST': redis_host,
            'CACHE_REDIS_PORT': redis_port,
            'CACHE_REDIS_DB': redis_db,
            'CACHE_KEY_PREFIX': 'erp_',
        })
    
    # 文件系统缓存配置
    elif cache_type == 'FileSystemCache':
        cache_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'cache')
        os.makedirs(cache_dir, exist_ok=True)
        
        cache_config.update({
            'CACHE_DIR': cache_dir,
            'CACHE_THRESHOLD': 500,  # 最大缓存文件数
        })
    
    app.config.from_mapping(cache_config)
    cache = Cache(app)
    
    return cache


# 缓存装饰器
def cache_key_prefix(prefix):
    """
    缓存键前缀装饰器
    
    Args:
        prefix: 键前缀
    
    Returns:
        装饰器函数
    """
    def decorator(f):
        def wrapper(*args, **kwargs):
            return f(*args, **kwargs)
        wrapper.__name__ = f.__name__
        wrapper._cache_key_prefix = prefix
        return wrapper
    return decorator


# 预定义的缓存配置
CACHE_CONFIGS = {
    # 产品列表缓存 - 10分钟
    'product_list': {
        'timeout': 600,
        'key_prefix': 'product_list'
    },
    
    # 产品详情缓存 - 30分钟
    'product_detail': {
        'timeout': 1800,
        'key_prefix': 'product_detail'
    },
    
    # 库存统计缓存 - 5分钟
    'inventory_stats': {
        'timeout': 300,
        'key_prefix': 'inventory_stats'
    },
    
    # 用户权限缓存 - 1小时
    'user_permissions': {
        'timeout': 3600,
        'key_prefix': 'user_permissions'
    },
    
    # 订单统计缓存 - 5分钟
    'order_stats': {
        'timeout': 300,
        'key_prefix': 'order_stats'
    }
}


class CacheManager:
    """缓存管理器"""
    
    def __init__(self, cache):
        self.cache = cache
    
    def get(self, key):
        """获取缓存"""
        return self.cache.get(key)
    
    def set(self, key, value, timeout=None):
        """设置缓存"""
        return self.cache.set(key, value, timeout=timeout)
    
    def delete(self, key):
        """删除缓存"""
        return self.cache.delete(key)
    
    def clear(self):
        """清空所有缓存"""
        return self.cache.clear()
    
    def get_product_list(self):
        """获取产品列表缓存"""
        return self.get('product_list')
    
    def set_product_list(self, products):
        """设置产品列表缓存"""
        return self.set('product_list', products, timeout=600)
    
    def invalidate_product_cache(self):
        """使产品缓存失效"""
        self.delete('product_list')
        # 删除所有产品详情缓存
        # 这里可以添加更精确的缓存清理逻辑
    
    def get_user_permissions(self, user_id):
        """获取用户权限缓存"""
        return self.get(f'user_permissions_{user_id}')
    
    def set_user_permissions(self, user_id, permissions):
        """设置用户权限缓存"""
        return self.set(f'user_permissions_{user_id}', permissions, timeout=3600)
    
    def invalidate_user_cache(self, user_id):
        """使用户缓存失效"""
        self.delete(f'user_permissions_{user_id}')
