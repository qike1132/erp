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

#: Redis 客户端的公共构造参数（两条构造分支共用，避免两处漂移）。
#: 放模块级而非类属性：可变对象作类属性会被 RUF012 判为风险默认值。
_CLIENT_OPTS: dict[str, Any] = {
    'decode_responses': True,
    'socket_connect_timeout': 5,
    'socket_timeout': 5,
    'retry_on_timeout': True,
    'max_connections': 100,
}

# 大 value 的 JSON 序列化/反序列化是 CPU 密集操作，下沉线程池；小 value 保持同步
_SERIALIZE_OFFLOAD_ITEMS = 1000
_SERIALIZE_OFFLOAD_CHARS = 64 * 1024


def _needs_offload(value: Any) -> bool:
    if isinstance(value, str):
        return len(value) >= _SERIALIZE_OFFLOAD_CHARS
    if isinstance(value, (list, tuple, dict, set)):
        return len(value) >= _SERIALIZE_OFFLOAD_ITEMS
    return False


async def _serialize_async(value: Any) -> str:
    if _needs_offload(value):
        return await asyncio.to_thread(json.dumps, value, ensure_ascii=False)
    return json.dumps(value, ensure_ascii=False)


async def _deserialize_async(raw) -> Any:
    if len(raw) >= _SERIALIZE_OFFLOAD_CHARS:
        return await asyncio.to_thread(json.loads, raw)
    return json.loads(raw)


class RedisCacheManager:
    """异步 Redis 缓存管理器

    客户端自愈（2026-09-28）
    ------------------------
    `init_app()` 在 `ping()` 失败时会把 `redis_client` 置 None，此前**永不重试** ——
    于是「Redis 启动即不可用」会让整个进程生命周期都只用内存降级（缓存、撤销黑名单、
    限流全受影响）；与 fail-closed 鉴权叠加时更表现为**永久 401**，只能重启进程。

    `redis.asyncio.Redis` 的连接池自带重连，所以只要能拿到客户端对象，Redis 恢复后
    命令就会自动成功 —— 根因只是"对象被丢成 None 后再没重建"。`ensure_client()`
    负责惰性重建（构造是惰性的、不建连，连通性交给首条命令验证），并用指数退避
    避免长时间故障期间每个请求都重建一次连接池。

    裸客户端契约（重要）
    --------------------
    `note_command_success()` / `note_command_failure()` 只在**走本类包装方法**时
    自动触发。经 `core/redis_wrapper.get_client()` 直连的调用不经过包装方法，
    需调用方**自行**告知，否则不进入降级/退避（故障期间会每个请求真连一次）：

    - 已接通：`core/auth/blacklist.py`（撤销黑名单 —— fail-closed 路由的路径）、
      `api/v1/endpoints/auth.py`（登录限流）、`core/maintenance.py`（维护模式闸门，
      2026-09-28 后续从另一个孤立客户端迁入）。
    - 未接通 · 走 get_client()：`dead_letter`、`domain_events`（后者每次失败后
      `sleep 5s` 自带节流），以及 `redis_wrapper` 中直接用裸客户端的那些 `safe_*`。
      影响有限：任一路径 armed 退避后，`ensure_client()` 会对**所有**调用方返回
      None，未接通的路径也会被同一窗口顺带短路。
    - 未接通 · 且**结构上不在本机制内**：`backup_progress` 用的是
      `core/redis_client.get_async_redis_client()` —— **另一个**客户端，既不自愈
      也不退避（`get_client()` 对它只是几乎走不到的兜底）。补 `note_*` 只会替
      get_client() 的消费者 arm 窗口，约束不了它自己的重试，故不改。
    """

    FALLBACK_MAX_SIZE = 1000

    #: 自愈重连的退避：初始 1s，每次重建后翻倍，封顶 60s。
    #: 封顶不能太大，否则 Redis 恢复后仍要等很久才再尝试一次。
    RETRY_INITIAL_DELAY = 1.0
    RETRY_MAX_DELAY = 60.0

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
        # 降级缓存每条的**过期时刻**（time.time() 基准）。必须逐条记，
        # 不能用全局 default_timeout —— 否则 set(timeout=30) 在降级路径下会
        # 按 300 秒过期（安全复审 2026-09-28 指出的真实缺陷）。
        self._fallback_timestamps: dict[str, float] = {}
        self._lock = asyncio.Lock()
        # --- 自愈重连状态（见类 docstring）---
        #: init_app 时记住的连接参数；为 None 表示从未初始化过，不可凭空重建。
        self._connect_kwargs: dict[str, Any] | None = None
        #: 下次允许重建的时间点（time.monotonic）。
        self._next_retry_at: float = 0.0
        #: 当前退避时长，重建一次翻倍。
        self._retry_delay: float = self.RETRY_INITIAL_DELAY

    # 默认 127.0.0.1 而非 localhost：Windows 上 localhost 解析优先 ::1，而 redis
    # 只 bind IPv4，漏配环境变量时会连 ::1 超时（评审 2026-10-11）。
    async def init_app(self, app=None, redis_url: str | None = None, redis_host: str = '127.0.0.1',
                       redis_port: int = 6379, redis_db: int = 0, redis_password: str | None = None,
                       default_timeout: int = 300, key_prefix: str = 'erp:'):
        if app is not None:
            redis_url = redis_url or app.config.get('REDIS_CACHE_URL') or app.config.get('REDIS_URL') or os.getenv('REDIS_CACHE_URL') or os.getenv('REDIS_URL')
            redis_host = app.config.get('REDIS_HOST', os.getenv('REDIS_HOST', '127.0.0.1'))
            redis_port = int(app.config.get('REDIS_PORT', os.getenv('REDIS_PORT', 6379)))
            redis_db = int(app.config.get('REDIS_DB', os.getenv('REDIS_DB', 0)))
            redis_password = app.config.get('REDIS_PASSWORD', os.getenv('REDIS_PASSWORD'))
            default_timeout = app.config.get('CACHE_DEFAULT_TIMEOUT', 300)
            key_prefix = app.config.get('CACHE_KEY_PREFIX', 'erp:')

        # 记住连接参数：init 失败后 ensure_client() 靠它惰性重建 —— 自愈的前提。
        if redis_url:
            self._connect_kwargs = {'url': redis_url}
        else:
            self._connect_kwargs = {
                'host': redis_host, 'port': redis_port,
                'db': redis_db, 'password': redis_password,
            }

        if redis_url:
            try:
                self.redis_client = aioredis.from_url(redis_url, **_CLIENT_OPTS)
                await self.redis_client.ping()
                # 日志脱敏：REDIS_URL 可能内嵌口令（redis://:pwd@host），不得明文入日志
                from urllib.parse import urlsplit, urlunsplit
                _parts = urlsplit(redis_url)
                _safe_netloc = _parts.hostname or ''
                if _parts.port:
                    _safe_netloc += f':{_parts.port}'
                logger.info("Redis 异步连接成功: %s", urlunsplit((_parts.scheme, _safe_netloc, _parts.path, '', '')))
            except Exception as e:  # defensive: 连接失败不得阻断启动，降级到内存缓存
                logger.warning("Redis 异步连接失败，将使用内存缓存: %s", e)
                self.redis_client = None
        else:
            try:
                self.redis_client = self._build_client()
                await self.redis_client.ping()
                logger.info("Redis 异步连接成功: %s:%s", redis_host, redis_port)
            except Exception as e:  # defensive: 连接失败不得阻断启动，降级到内存缓存
                logger.warning("Redis 异步连接失败，将使用内存缓存: %s", e)
                self.redis_client = None

        self.default_timeout = default_timeout
        self.key_prefix = key_prefix

        if self.redis_client is not None:
            # 连上了 → 复位退避，避免上次故障的残余延迟拖慢后续重建
            self._retry_delay = self.RETRY_INITIAL_DELAY
            self._next_retry_at = 0.0

    def _build_client(self) -> aioredis.Redis | None:
        """按记住的参数构造客户端。构造是**惰性**的：不建连、不 ping。"""
        kwargs = self._connect_kwargs
        if not kwargs:
            return None
        if 'url' in kwargs:
            return aioredis.from_url(kwargs['url'], **_CLIENT_OPTS)
        return aioredis.Redis(
            host=kwargs['host'], port=kwargs['port'], db=kwargs['db'],
            password=kwargs['password'], **_CLIENT_OPTS,
        )

    def ensure_client(self) -> aioredis.Redis | None:
        """客户端缺失时惰性重建（自愈）；已有则原样返回。

        **同步且无 await** —— 在 asyncio 单线程下即是原子的，无需加锁。
        返回 None 表示当前不可用，调用方照旧走既有降级路径。

        注意不需要"重建后 ping 成功才算数"：redis-py 的连接池自带重连，
        对象一旦拿到，Redis 恢复后的命令就会自动成功。

        退避与 `note_command_failure()` 是一对：后者在命令遇连接类错误时把客户端
        降回 None 并按同一个退避窗口排下一次重试 —— 两者合起来才构成
        「检测到不可用 → 退避 → 到期再试」的完整循环，也让持续故障期间的
        重试频率与日志量有界。
        """
        if self.redis_client is not None:
            return self.redis_client
        if self._connect_kwargs is None:
            return None  # 从未初始化过，不可凭空重建

        now = time.monotonic()
        if now < self._next_retry_at:
            return None  # 退避窗口内：避免长时间故障时每个请求都重建连接池

        try:
            client = self._build_client()
        except Exception as e:  # defensive: 连接参数异常不得让每个请求都抛
            logger.warning("Redis 客户端重建失败（将等待下个退避窗口）: %s", e)
            self._next_retry_at = now + self._retry_delay
            self._retry_delay = min(self._retry_delay * 2, self.RETRY_MAX_DELAY)
            return None
        if client is None:
            return None

        self.redis_client = client
        self._next_retry_at = now + self._retry_delay
        self._retry_delay = min(self._retry_delay * 2, self.RETRY_MAX_DELAY)
        logger.info("Redis 客户端已惰性重建（连通性由首条命令验证）")
        return client

    def note_command_success(self) -> None:
        """命令成功 → 复位退避。

        为什么必须有它：退避只在 `init_app` 成功时复位。若失败期间退避涨到上限
        （60s）后 Redis 恢复，退避仍停在 60s —— 于是**之后一次偶发抖动**就要等
        60s 才再尝试，而这段时间里 fail-closed 路由（如 `/backup`）会因
        `get_client()` 为 None + 本地缓存未命中而对**合法用户**返回 401。
        改动前，一次抖动只损失大约一个请求。

        复位成本极低：正常运行时该分支只做一次比较。
        """
        if self._retry_delay == self.RETRY_INITIAL_DELAY and self._next_retry_at == 0.0:
            return
        self._retry_delay = self.RETRY_INITIAL_DELAY
        self._next_retry_at = 0.0

    def note_command_failure(self, exc: Exception) -> None:
        """命令失败且属**连接类**错误时降级并进入退避。

        为什么需要它：惰性重建只保证"拿到客户端对象"，而对象一旦被赋给
        `redis_client` 就不会再回到 None —— 于是 Redis 持续不可用期间，
        **每个**缓存读/黑名单查询都会真的去连一次（最多 `socket_connect_timeout`
        秒）并各自打一条 warning。旧实现在这种情形下是 `redis_client is None`
        直接短路：零 I/O、零日志。本方法把那个短路行为恢复回来，同时让退避
        真正承担"重试节奏"的职责。

        只对连接/超时类错误降级：协议类错误（如 WRONGTYPE）不是连通性问题，
        不该把客户端丢掉。
        """
        if not isinstance(exc, (redis.exceptions.ConnectionError, redis.exceptions.TimeoutError)):
            return
        if self.redis_client is None:
            return  # 已经降级过，避免重复刷新退避窗口
        self.redis_client = None
        self._next_retry_at = time.monotonic() + self._retry_delay
        logger.warning(
            "Redis 连接不可用，已降级到内存缓存（%.0fs 后重试）: %s",
            self._retry_delay, exc,
        )
        self._retry_delay = min(self._retry_delay * 2, self.RETRY_MAX_DELAY)

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
        expired_keys = [k for k, expires_at in self._fallback_timestamps.items()
                        if now > expires_at]
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

        client = self.ensure_client()
        if client:
            try:
                value = await client.get(full_key)
                self.note_command_success()
                if value:
                    return await _deserialize_async(value)
            except Exception as e:
                logger.warning("Redis async get error: %s", e)
                self.note_command_failure(e)

        async with self._lock:
            expires_at = self._fallback_timestamps.get(full_key)
            if expires_at is not None and time.time() > expires_at:
                self._fallback_cache.pop(full_key, None)
                del self._fallback_timestamps[full_key]
                return None
            return self._fallback_cache.get(full_key)

    async def set(self, key: str, value: Any, timeout: int | None = None) -> bool:
        full_key = self._make_key(key)
        timeout = timeout or self.default_timeout

        client = self.ensure_client()
        if client:
            try:
                serialized = await _serialize_async(value)
                ok = await client.setex(full_key, timeout, serialized)
                self.note_command_success()
                return ok
            except Exception as e:
                logger.warning("Redis async set error: %s", e)
                self.note_command_failure(e)

        async with self._lock:
            self._fallback_cache[full_key] = value
            self._fallback_timestamps[full_key] = time.time() + timeout
            self._cleanup_fallback()
        return True

    async def delete(self, key: str) -> bool:
        full_key = self._make_key(key)

        client = self.ensure_client()
        if client:
            try:
                await client.unlink(full_key)
                self.note_command_success()
            except Exception as e:
                logger.warning("Redis async unlink error: %s", e)
                self.note_command_failure(e)

        async with self._lock:
            self._fallback_cache.pop(full_key, None)
            self._fallback_timestamps.pop(full_key, None)
        return True

    async def delete_pattern(self, pattern: str) -> int:
        full_pattern = self._make_key(pattern)
        deleted_count = 0

        client = self.ensure_client()
        if client:
            try:
                cursor = 0
                max_iterations = 1000
                iterations = 0
                while True:
                    cursor, keys = await client.scan(
                        cursor=cursor, match=full_pattern, count=100
                    )
                    if keys:
                        deleted_count += await client.unlink(*keys)
                    iterations += 1
                    if cursor == 0 or iterations >= max_iterations:
                        break
                self.note_command_success()
                if iterations >= max_iterations:
                    logger.warning("delete_pattern 达到迭代上限 %d，模式: %s", max_iterations, full_pattern)
            except Exception as e:
                logger.warning("Redis async delete_pattern error: %s", e)
                self.note_command_failure(e)

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

        client = self.ensure_client()
        if client:
            try:
                found = bool(await client.exists(full_key))
                self.note_command_success()
                return found
            except Exception as e:
                logger.warning("Redis async exists error: %s", e)
                self.note_command_failure(e)

        async with self._lock:
            expires_at = self._fallback_timestamps.get(full_key)
            if expires_at is not None and time.time() > expires_at:
                self._fallback_cache.pop(full_key, None)
                del self._fallback_timestamps[full_key]
                return False
            return full_key in self._fallback_cache

    async def incr(self, key: str) -> int:
        full_key = self._make_key(key)

        client = self.ensure_client()
        if client:
            try:
                value = await client.incr(full_key)
                self.note_command_success()
                return value
            except Exception as e:
                logger.warning("Redis async incr error: %s", e)
                self.note_command_failure(e)

        async with self._lock:
            current = self._fallback_cache.get(full_key, 0)
            new_value = current + 1
            self._fallback_cache[full_key] = new_value
            self._fallback_timestamps[full_key] = time.time() + self.default_timeout
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

        # 关停后不得再惰性重建：迟到的在飞请求会造出一个永不 aclose 的连接池，
        # 并在正在关闭的 event loop 上打错误日志。
        # ⚠️ 必须在 if **之外**：客户端本就为 None（例如 init 失败过）时同样要清掉
        #    连接参数，否则 close() 之后仍会被重建。
        self._connect_kwargs = None


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


# warmup_cache 已于 2026-10-15 迁至 fastapi_app/core/cache_warmup.py：
# 它需要 import fastapi_app.core.database 与 fastapi_app.shared_models，留在本模块
# 会构成「utils → fastapi_app」与「fastapi_app → utils」的包级循环（此前双向都靠
# 函数内延迟 import 才不炸）。迁移后本模块是纯 Redis 客户端，零 fastapi_app 依赖。
