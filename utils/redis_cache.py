"""
Redis缓存管理器
提供高性能的Redis缓存功能
"""
import redis
import json
import hashlib
import os
import time
import logging
import threading
from functools import wraps
from typing import Any, Optional

logger = logging.getLogger(__name__)


class RedisCacheManager:
    """Redis缓存管理器"""

    # 内存降级缓存最大条目数
    FALLBACK_MAX_SIZE = 1000

    def __init__(self):
        self.redis_client = None
        self.default_timeout = 300
        # 命名空间包含主机名，避免多实例部署时缓存键冲突
        import socket
        instance_id = os.getenv("HOSTNAME", socket.gethostname())[:20]
        self.key_prefix = f'erp:{instance_id}:'
        self._fallback_cache = {}
        self._fallback_timestamps = {}
        self._lock = threading.Lock()

    def init_app(self, app=None, redis_url: str = None, redis_host: str = 'localhost',
                 redis_port: int = 6379, redis_db: int = 0, redis_password: str = None,
                 default_timeout: int = 300, key_prefix: str = 'erp:'):
        """
        初始化Redis连接 - 支持 Flask app 或直接参数配置

        Args:
            app: Flask 应用实例（可选）
            redis_url: Redis URL（可选，直接配置时使用）
            redis_host: Redis 主机
            redis_port: Redis 端口
            redis_db: Redis 数据库编号
            redis_password: Redis 密码
            default_timeout: 默认缓存超时时间（秒）
            key_prefix: 缓存键前缀
        """
        if app is not None:
            redis_url = redis_url or app.config.get('REDIS_URL') or os.getenv('REDIS_URL')
            redis_host = app.config.get('REDIS_HOST', os.getenv('REDIS_HOST', 'localhost'))
            redis_port = int(app.config.get('REDIS_PORT', os.getenv('REDIS_PORT', 6379)))
            redis_db = int(app.config.get('REDIS_DB', os.getenv('REDIS_DB', 0)))
            redis_password = app.config.get('REDIS_PASSWORD', os.getenv('REDIS_PASSWORD'))
            default_timeout = app.config.get('CACHE_DEFAULT_TIMEOUT', 300)
            key_prefix = app.config.get('CACHE_KEY_PREFIX', 'erp:')

        if redis_url:
            try:
                self.redis_client = redis.from_url(
                    redis_url,
                    decode_responses=True,
                    socket_connect_timeout=5,
                    socket_timeout=5,
                    retry_on_timeout=True,
                    max_connections=100
                )
                self.redis_client.ping()
                logger.info(f"Redis连接成功: {redis_url}")
            except (redis.ConnectionError, Exception) as e:
                logger.warning(f"Redis连接失败，将使用内存缓存: {e}")
                self.redis_client = None
        else:
            try:
                self.redis_client = redis.Redis(
                    host=redis_host,
                    port=redis_port,
                    db=redis_db,
                    password=redis_password,
                    decode_responses=True,
                    socket_connect_timeout=5,
                    socket_timeout=5,
                    retry_on_timeout=True,
                    max_connections=100
                )
                self.redis_client.ping()
                logger.info(f"Redis连接成功: {redis_host}:{redis_port}")
            except (redis.ConnectionError, Exception) as e:
                logger.warning(f"Redis连接失败，将使用内存缓存: {e}")
                self.redis_client = None

        self.default_timeout = default_timeout
        self.key_prefix = key_prefix

    def _make_key(self, key: str) -> str:
        """生成完整的缓存键"""
        return f"{self.key_prefix}{key}"

    def _cleanup_fallback(self):
        """清理过期的内存缓存条目，防止无限增长"""
        now = time.time()
        expired_keys = [k for k, ts in self._fallback_timestamps.items()
                        if now - ts > self.default_timeout]
        for k in expired_keys:
            self._fallback_cache.pop(k, None)
            del self._fallback_timestamps[k]

        # 超过最大容量时淘汰最早的一半
        if len(self._fallback_cache) > self.FALLBACK_MAX_SIZE:
            sorted_keys = sorted(self._fallback_timestamps.items(), key=lambda x: x[1])
            keys_to_remove = sorted_keys[:len(sorted_keys) // 2]
            for k, _ in keys_to_remove:
                self._fallback_cache.pop(k, None)
                del self._fallback_timestamps[k]

    def get(self, key: str) -> Optional[Any]:
        """获取缓存值"""
        full_key = self._make_key(key)

        if self.redis_client:
            try:
                value = self.redis_client.get(full_key)
                if value:
                    return json.loads(value)
            except Exception as e:
                logger.warning(f"Redis get error: {e}")

        # 内存降级缓存：检查TTL过期
        with self._lock:
            ts = self._fallback_timestamps.get(full_key)
            if ts is not None and time.time() - ts > self.default_timeout:
                self._fallback_cache.pop(full_key, None)
                del self._fallback_timestamps[full_key]
                return None
            return self._fallback_cache.get(full_key)

    def set(self, key: str, value: Any, timeout: int = None) -> bool:
        """设置缓存值"""
        full_key = self._make_key(key)
        timeout = timeout or self.default_timeout

        if self.redis_client:
            try:
                serialized = json.dumps(value, ensure_ascii=False)
                return self.redis_client.setex(full_key, timeout, serialized)
            except Exception as e:
                logger.warning(f"Redis set error: {e}")

        with self._lock:
            self._fallback_cache[full_key] = value
            self._fallback_timestamps[full_key] = time.time()
            self._cleanup_fallback()
        return True

    def delete(self, key: str) -> bool:
        """删除缓存"""
        full_key = self._make_key(key)

        if self.redis_client:
            try:
                self.redis_client.delete(full_key)
            except Exception as e:
                logger.warning(f"Redis delete error: {e}")

        with self._lock:
            self._fallback_cache.pop(full_key, None)
            self._fallback_timestamps.pop(full_key, None)
        return True

    def delete_pattern(self, pattern: str) -> int:
        """删除匹配模式的所有键（使用 SCAN 替代 KEYS，避免阻塞 Redis）"""
        full_pattern = self._make_key(pattern)
        deleted_count = 0

        if self.redis_client:
            try:
                cursor = 0
                max_iterations = 1000  # 安全上限，防止 key 空间异常时无限扫描
                iterations = 0
                while True:
                    cursor, keys = self.redis_client.scan(
                        cursor=cursor, match=full_pattern, count=100
                    )
                    if keys:
                        deleted_count += self.redis_client.delete(*keys)
                    iterations += 1
                    if cursor == 0 or iterations >= max_iterations:
                        break
                if iterations >= max_iterations:
                    logger.warning(f"delete_pattern 达到迭代上限 {max_iterations}，模式: {full_pattern}")
            except Exception as e:
                logger.warning(f"Redis delete_pattern error: {e}")

        with self._lock:
            prefix = full_pattern.replace('*', '')
            keys_to_delete = [k for k in self._fallback_cache.keys() if k.startswith(prefix)]
            for key in keys_to_delete:
                del self._fallback_cache[key]
                self._fallback_timestamps.pop(key, None)
                deleted_count += 1

        return deleted_count

    def exists(self, key: str) -> bool:
        """检查键是否存在"""
        full_key = self._make_key(key)

        if self.redis_client:
            try:
                return bool(self.redis_client.exists(full_key))
            except Exception as e:
                logger.warning(f"Redis exists error: {e}")

        with self._lock:
            ts = self._fallback_timestamps.get(full_key)
            if ts is not None and time.time() - ts > self.default_timeout:
                self._fallback_cache.pop(full_key, None)
                del self._fallback_timestamps[full_key]
                return False
            return full_key in self._fallback_cache

    def incr(self, key: str) -> int:
        """递增计数器"""
        full_key = self._make_key(key)

        if self.redis_client:
            try:
                return self.redis_client.incr(full_key)
            except Exception as e:
                logger.warning(f"Redis incr error: {e}")

        with self._lock:
            current = self._fallback_cache.get(full_key, 0)
            new_value = current + 1
            self._fallback_cache[full_key] = new_value
            self._fallback_timestamps[full_key] = time.time()
            return new_value

    def get_stats(self) -> dict:
        """获取Redis统计信息"""
        stats = {
            'backend': 'redis' if self.redis_client else 'memory',
            'connected': self.redis_client is not None
        }

        if self.redis_client:
            try:
                info = self.redis_client.info()
                stats.update({
                    'connected_clients': info.get('connected_clients', 0),
                    'used_memory_human': info.get('used_memory_human', '0B'),
                    'total_commands_processed': info.get('total_commands_processed', 0),
                    'keyspace_hits': info.get('keyspace_hits', 0),
                    'keyspace_misses': info.get('keyspace_misses', 0),
                })
            except Exception as e:
                stats['error'] = str(e)
        else:
            stats['fallback_cache_size'] = len(self._fallback_cache)

        return stats


# 全局Redis管理器实例
redis_cache = RedisCacheManager()


def redis_cached(timeout: int = 300, key_prefix: str = None):
    """Redis缓存装饰器"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            cache_key = _generate_cache_key(f, key_prefix, args, kwargs)

            result = redis_cache.get(cache_key)
            if result is not None:
                return result

            result = f(*args, **kwargs)

            if result is not None:
                redis_cache.set(cache_key, result, timeout)

            return result

        return decorated_function
    return decorator


def cache_invalidate(*key_patterns):
    """缓存失效装饰器"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            result = f(*args, **kwargs)

            for pattern in key_patterns:
                redis_cache.delete_pattern(pattern)

            return result

        return decorated_function
    return decorator


def _generate_cache_key(f, key_prefix: str, args: tuple, kwargs: dict) -> str:
    """生成缓存键"""
    if key_prefix is None:
        key_prefix = f.__name__

    args_str = _hash_args(args, kwargs)
    return f"{key_prefix}:{args_str}"


def _hash_args(args: tuple, kwargs: dict) -> str:
    """将参数哈希化"""
    try:
        args_json = json.dumps({'args': args, 'kwargs': kwargs}, sort_keys=True)
        return hashlib.sha256(args_json.encode()).hexdigest()[:16]
    except Exception:
        # fallback: 使用 md5 替代内置 hash()，因为 hash() 跨进程不一致(PYTHONHASHSEED)
        import hashlib as _hl
        raw = str(args) + str(kwargs)
        return _hl.md5(raw.encode()).hexdigest()[:16]


class CacheConfig:
    """缓存配置常量"""

    PRODUCT_LIST = ('product:list', 600)
    PRODUCT_DETAIL = ('product:detail', 1800)
    PRODUCT_SEARCH = ('product:search', 300)
    INVENTORY_STATS = ('inventory:stats', 300)
    STOCK_LIST = ('stock:list', 600)
    ORDER_LIST = ('order:list', 300)
    ORDER_STATS = ('order:stats', 300)
    USER_PERMISSIONS = ('user:permissions', 3600)
    USER_PROFILE = ('user:profile', 1800)
    REPORT_DATA = ('report:data', 600)
