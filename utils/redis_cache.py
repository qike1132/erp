"""
Redis 缓存管理器 - 全异步版本

使用 redis.asyncio.Redis 替代同步 redis.Redis，
消除 FastAPI 异步事件循环中的阻塞调用。
"""
import asyncio
import hashlib
import json
import logging
import os
import time
from functools import wraps
from typing import Any

import redis
import redis.asyncio as aioredis

logger = logging.getLogger(__name__)


class RedisCacheManager:
    """异步 Redis 缓存管理器"""

    FALLBACK_MAX_SIZE = 1000

    def __init__(self):
        self.redis_client: aioredis.Redis | None = None
        self.default_timeout = 300
        # key_prefix 的权威赋值点是 init_app()（默认 'erp:'，可被 CACHE_KEY_PREFIX 覆盖）。
        # 此处只提供与 init_app 默认值一致的初值，避免"初始化前"使用产生无前缀 key。
        #
        # 历史：本属性曾用 f'erp:{HOSTNAME}:' 做实例隔离，但 init_app() 的默认参数
        # key_prefix='erp:' 会将其整个覆盖，该隔离从未生效（死代码，2026-09-14 清理）。
        # 若将来确需按实例隔离，必须同时改 init_app 的默认值与调用方传参，否则仍是空转。
        self.key_prefix = 'erp:'
        self._fallback_cache: dict[str, Any] = {}
        self._fallback_timestamps: dict[str, float] = {}
        self._lock = asyncio.Lock()

    async def init_app(self, app=None, redis_url: str | None = None, redis_host: str = 'localhost',
                       redis_port: int = 6379, redis_db: int = 0, redis_password: str | None = None,
                       default_timeout: int = 300, key_prefix: str = 'erp:'):
        if app is not None:
            redis_url = redis_url or app.config.get('REDIS_CACHE_URL') or app.config.get('REDIS_URL') or os.getenv('REDIS_CACHE_URL') or os.getenv('REDIS_URL')
            redis_host = app.config.get('REDIS_HOST', os.getenv('REDIS_HOST', 'localhost'))
            redis_port = int(app.config.get('REDIS_PORT', os.getenv('REDIS_PORT', 6379)))
            redis_db = int(app.config.get('REDIS_DB', os.getenv('REDIS_DB', 0)))
            redis_password = app.config.get('REDIS_PASSWORD', os.getenv('REDIS_PASSWORD'))
            default_timeout = app.config.get('CACHE_DEFAULT_TIMEOUT', 300)
            key_prefix = app.config.get('CACHE_KEY_PREFIX', 'erp:')

        if redis_url:
            try:
                self.redis_client = aioredis.from_url(
                    redis_url,
                    decode_responses=True,
                    socket_connect_timeout=5,
                    socket_timeout=5,
                    retry_on_timeout=True,
                    max_connections=100
                )
                await self.redis_client.ping()
                # 日志脱敏：REDIS_URL 可能内嵌口令（redis://:pwd@host），不得明文入日志
                from urllib.parse import urlsplit, urlunsplit
                _parts = urlsplit(redis_url)
                _safe_netloc = _parts.hostname or ''
                if _parts.port:
                    _safe_netloc += f':{_parts.port}'
                logger.info("Redis 异步连接成功: %s", urlunsplit((_parts.scheme, _safe_netloc, _parts.path, '', '')))
            except (redis.ConnectionError, Exception) as e:
                logger.warning("Redis 异步连接失败，将使用内存缓存: %s", e)
                self.redis_client = None
        else:
            try:
                self.redis_client = aioredis.Redis(
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
                await self.redis_client.ping()
                logger.info("Redis 异步连接成功: %s:%s", redis_host, redis_port)
            except (redis.ConnectionError, Exception) as e:
                logger.warning("Redis 异步连接失败，将使用内存缓存: %s", e)
                self.redis_client = None

        self.default_timeout = default_timeout
        self.key_prefix = key_prefix

    def _make_key(self, key: str) -> str:
        """把业务 key 转换为带前缀的物理 key。

        ⚠️ 前缀契约（2026-09-14 明确）：
        本方法对"已带 erp: 前缀"的 key 原样返回，对未带的补前缀。这个隐式判断
        意味着**同一个逻辑 key 走不同路径会落到不同物理位置**：

            redis_cache.get('token_blacklist:x')  ->  erp:token_blacklist:x
            裸 client  .set('token_blacklist:x')  ->  token_blacklist:x   ← 读不到上面那个

        因此**读写必须走同一层**（都经本类，或都用裸 client），否则数据互不可见。
        现存裸 client 调用点（get_client() 直连）与本类不互通，属已知现状：
        - core/auth/blacklist.py     token_blacklist:{jti}
        - endpoints/auth.py          login_attempt:*/login_burst:*
        - core/maintenance.py        erp:maintenance_mode（自带前缀，恰好两路一致）

        新增 Redis 访问请一律走本类或 core/redis_wrapper 的 safe_* 封装，
        不要用 get_client() 直连——否则会引入第三套命名空间。
        防腐检查见 fastapi_app/tests/test_redis_key_namespace.py
        """
        if key.startswith(self.key_prefix):
            return key
        return f"{self.key_prefix}{key}"

    def _cleanup_fallback(self):
        # 惰性清理：仅在缓存条目数超过阈值的 80% 时才执行过期清理
        if len(self._fallback_cache) < int(self.FALLBACK_MAX_SIZE * 0.8):
            return

        now = time.time()
        expired_keys = [k for k, ts in self._fallback_timestamps.items()
                        if now - ts > self.default_timeout]
        for k in expired_keys:
            self._fallback_cache.pop(k, None)
            del self._fallback_timestamps[k]

        if len(self._fallback_cache) > self.FALLBACK_MAX_SIZE:
            sorted_keys = sorted(self._fallback_timestamps.items(), key=lambda x: x[1])
            keys_to_remove = sorted_keys[:len(sorted_keys) // 2]
            for k, _ in keys_to_remove:
                self._fallback_cache.pop(k, None)
                del self._fallback_timestamps[k]

    async def get(self, key: str) -> Any | None:
        full_key = self._make_key(key)

        if self.redis_client:
            try:
                value = await self.redis_client.get(full_key)
                if value:
                    return json.loads(value)
            except Exception as e:
                logger.warning("Redis async get error: %s", e)

        async with self._lock:
            ts = self._fallback_timestamps.get(full_key)
            if ts is not None and time.time() - ts > self.default_timeout:
                self._fallback_cache.pop(full_key, None)
                del self._fallback_timestamps[full_key]
                return None
            return self._fallback_cache.get(full_key)

    async def set(self, key: str, value: Any, timeout: int | None = None) -> bool:
        full_key = self._make_key(key)
        timeout = timeout or self.default_timeout

        if self.redis_client:
            try:
                serialized = json.dumps(value, ensure_ascii=False)
                return await self.redis_client.setex(full_key, timeout, serialized)
            except Exception as e:
                logger.warning("Redis async set error: %s", e)

        async with self._lock:
            self._fallback_cache[full_key] = value
            self._fallback_timestamps[full_key] = time.time()
            self._cleanup_fallback()
        return True

    async def delete(self, key: str) -> bool:
        full_key = self._make_key(key)

        if self.redis_client:
            try:
                await self.redis_client.unlink(full_key)
            except Exception as e:
                logger.warning("Redis async unlink error: %s", e)

        async with self._lock:
            self._fallback_cache.pop(full_key, None)
            self._fallback_timestamps.pop(full_key, None)
        return True

    async def delete_pattern(self, pattern: str) -> int:
        full_pattern = self._make_key(pattern)
        deleted_count = 0

        if self.redis_client:
            try:
                cursor = 0
                max_iterations = 1000
                iterations = 0
                while True:
                    cursor, keys = await self.redis_client.scan(
                        cursor=cursor, match=full_pattern, count=100
                    )
                    if keys:
                        deleted_count += await self.redis_client.unlink(*keys)
                    iterations += 1
                    if cursor == 0 or iterations >= max_iterations:
                        break
                if iterations >= max_iterations:
                    logger.warning("delete_pattern 达到迭代上限 %d，模式: %s", max_iterations, full_pattern)
            except Exception as e:
                logger.warning("Redis async delete_pattern error: %s", e)

        async with self._lock:
            prefix = full_pattern.replace('*', '')
            keys_to_delete = [k for k in self._fallback_cache if k.startswith(prefix)]
            for key in keys_to_delete:
                del self._fallback_cache[key]
                self._fallback_timestamps.pop(key, None)
                deleted_count += 1

        return deleted_count

    async def exists(self, key: str) -> bool:
        full_key = self._make_key(key)

        if self.redis_client:
            try:
                return bool(await self.redis_client.exists(full_key))
            except Exception as e:
                logger.warning("Redis async exists error: %s", e)

        async with self._lock:
            ts = self._fallback_timestamps.get(full_key)
            if ts is not None and time.time() - ts > self.default_timeout:
                self._fallback_cache.pop(full_key, None)
                del self._fallback_timestamps[full_key]
                return False
            return full_key in self._fallback_cache

    async def incr(self, key: str) -> int:
        full_key = self._make_key(key)

        if self.redis_client:
            try:
                return await self.redis_client.incr(full_key)
            except Exception as e:
                logger.warning("Redis async incr error: %s", e)

        async with self._lock:
            current = self._fallback_cache.get(full_key, 0)
            new_value = current + 1
            self._fallback_cache[full_key] = new_value
            self._fallback_timestamps[full_key] = time.time()
            return new_value

    async def get_stats(self) -> dict:
        stats = {
            'backend': 'redis' if self.redis_client else 'memory',
            'connected': self.redis_client is not None
        }

        if self.redis_client:
            try:
                info = await self.redis_client.info()
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

    async def close(self):
        if self.redis_client:
            try:
                await self.redis_client.aclose()
            except Exception as e:
                logger.warning("Redis async close error: %s", e)
            self.redis_client = None


redis_cache = RedisCacheManager()


def cache_invalidate(*key_patterns):
    """缓存失效装饰器，支持 async 和 sync 函数"""
    def decorator(f):
        is_async = asyncio.iscoroutinefunction(f)

        if is_async:
            @wraps(f)
            async def async_wrapper(*args, **kwargs):
                result = await f(*args, **kwargs)
                for pattern in key_patterns:
                    await redis_cache.delete_pattern(pattern)
                return result
            return async_wrapper
        else:
            @wraps(f)
            def sync_wrapper(*args, **kwargs):
                result = f(*args, **kwargs)
                import asyncio as _aio
                try:
                    loop = _aio.get_running_loop()
                except RuntimeError:
                    loop = None
                for pattern in key_patterns:
                    if loop and loop.is_running():
                        _aio.run_coroutine_threadsafe(
                            redis_cache.delete_pattern(pattern), loop
                        )
                    else:
                        _aio.run(redis_cache.delete_pattern(pattern))
                return result
            return sync_wrapper
    return decorator


def _generate_cache_key(f, key_prefix: str, args: tuple, kwargs: dict) -> str:
    if key_prefix is None:
        key_prefix = f.__name__
    args_str = _hash_args(args, kwargs)
    return f"{key_prefix}:{args_str}"


def _hash_args(args: tuple, kwargs: dict) -> str:
    try:
        args_json = json.dumps({'args': args, 'kwargs': kwargs}, sort_keys=True)
        return hashlib.sha256(args_json.encode()).hexdigest()[:16]
    except Exception:
        raw = str(args) + str(kwargs)
        return hashlib.md5(raw.encode()).hexdigest()[:16]


class CacheConfig:
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
    DASHBOARD_STATS = ('dashboard:stats', 120)
    DAILY_PRODUCTION = ('daily:production', 300)
    PURCHASE_PLAN = ('purchase:plan', 300)
    APPROVAL_PENDING = ('approval:pending', 60)



async def warmup_cache():
    """缓存预热 - 应用启动时加载热点数据到Redis

    优先级: 权限 > 产品列表 > 仪表盘 > 库存统计
    """
    logger.info('开始缓存预热...')
    warmed = 0

    try:
        from fastapi_app.core.database import get_async_db_context
        async with get_async_db_context() as db:
            from sqlalchemy import select

            from fastapi_app.shared_models import Permission, Product, User, user_permission

            try:
                # 批量 JOIN 查询：一次获取所有活跃用户及其权限，消除 N+1 问题
                result = await db.execute(
                    select(User.id, Permission.code)
                    .join(user_permission, User.id == user_permission.c.user_id)
                    .join(Permission, Permission.id == user_permission.c.permission_id)
                    .where(User.status.is_(True))  # SQLAlchemy 表达式，语义为 SQL 布尔比较
                )
                user_perms: dict[int, list[str]] = {}
                for uid, code in result.all():
                    user_perms.setdefault(uid, []).append(code)
                for uid, codes in user_perms.items():
                    await redis_cache.set(
                        f'user:permissions:uid_{uid}',
                        codes,
                        3600,
                    )
                    warmed += 1
            except Exception as e:
                logger.warning('权限缓存预热失败: %s', e)

            try:
                from sqlalchemy import func as sa_func
                count_result = await db.execute(select(sa_func.count()).select_from(Product))
                product_count = count_result.scalar() or 0
                await redis_cache.set('product:list:count', product_count, 600)
                warmed += 1
            except Exception as e:
                logger.warning('产品计数缓存预热失败: %s', e)

    except Exception as e:
        logger.warning('缓存预热数据库连接失败: %s', e)

    logger.info('缓存预热完成，预热 %d 项', warmed)
    return warmed
