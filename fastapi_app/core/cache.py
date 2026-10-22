"""
Redis 缓存装饰器和工具函数

提供三级缓存架构：
L1: 进程内缓存 (TTL 30s)
L2: Redis 缓存 (TTL 可配置)
L3: 数据库
"""
import asyncio
import contextlib
import hashlib
import inspect
import json
import logging
import os
import uuid
from collections import OrderedDict
from collections.abc import Callable
from datetime import datetime, timedelta
from enum import Flag, auto
from functools import wraps
from typing import Any, cast

from fastapi_app.core.cache_keys import PRODUCT_LIST_CACHE_PATTERN
from fastapi_app.core.exception_handler import INFRA_EXCEPTIONS

# 2026-10-17 审计 AUD-10：redis-py 的 ConnectionError/TimeoutError/ResponseError/
# OutOfMemoryError 全部继承 redis.exceptions.RedisError，**不是** Python 内建异常
# （issubclass(redis.exceptions.ConnectionError, ConnectionError) is False）。
# 此前的 except 元组只列内建类，Redis 故障会穿透缓存层把已成功的业务结果变成 500。
# 统一复用 INFRA_EXCEPTIONS（含 OSError/内建 ConnectionError/RedisError 全族）。
# cast：INFRA_EXCEPTIONS 声明为 BaseException 元组（供通用兜底使用），
# 本模块只捕 Exception 子类，收窄注解让 except 变量类型可用。
_CACHE_INFRA_EXCEPTIONS: tuple[type[Exception], ...] = cast(
    'tuple[type[Exception], ...]', INFRA_EXCEPTIONS
)
# 需要同时兜住参数校验错误的调用点（保持原有 ValueError 语义）
_CACHE_INFRA_EXCEPTIONS_WITH_VALUE: tuple[type[Exception], ...] = (
    *_CACHE_INFRA_EXCEPTIONS, ValueError,
)

# Redis 操作超时（秒）：内网 Redis 单次操作 <1ms，0.3s 足够；
# 故障时快速失败（叠加 get+lock+set 最多 ~0.9s），避免每次失败累积 1s 阻塞
CACHE_TIMEOUT = 0.3

logger = logging.getLogger(__name__)

_CACHE_LOCAL_MAX_SIZE = 5000  # L1 缓存最大条目数（从 10000 降至 5000）
_cache_local: OrderedDict[str, tuple[Any, datetime]] = OrderedDict()

# 缓存击穿轮询等待上限（秒）：未获分布式锁的 worker 自旋等持锁方回填，
# 超过即放弃等待自行重算——10s 会让冷缓存高并发请求全部挂起占住连接槽
_CACHE_REFILL_POLL_SECONDS = 2.0
_CACHE_REFILL_POLL_INTERVAL = 0.1

# 击穿锁释放脚本：仅删除自己持有的锁（value=token 比对），防止持锁超过
# lock TTL 后误删后继获锁方的锁。KEYS[1]=完整锁键，ARGV[1]=本方 token。
_RELEASE_LOCK_LUA = (
    "if redis.call('get', KEYS[1]) == ARGV[1] then "
    "return redis.call('del', KEYS[1]) else return 0 end"
)

# 断路器：Redis 连续失败 N 次后短路跳过，避免每次请求浪费超时等待
_redis_fail_count = 0
_REDIS_CIRCUIT_THRESHOLD = 3
_redis_circuit_open_until: datetime | None = None
_REDIS_CIRCUIT_COOLDOWN = timedelta(seconds=30)

# L1 缓存跨 worker 失效广播（Redis Pub/Sub），默认关闭。
# 启用：CACHE_L1_BROADCAST_ENABLED=true，任一 worker 失效缓存时同步清理
# 其他 worker 的 L1，消除多 worker 下最长 local_ttl 的脏数据窗口。
_L1_BROADCAST_ENABLED = os.getenv('CACHE_L1_BROADCAST_ENABLED', '').lower() in ('1', 'true', 'yes')
_L1_BROADCAST_CHANNEL = 'cache:l1:invalidate'
_L1_RECONNECT_BACKOFF = 5  # 断线后重连退避秒数
_broadcast_task: asyncio.Task | None = None


def resolve_worker_count(env=None) -> int:
    """实际 worker 数：环境变量优先，非法值容错，未设置时与 prod_runner 默认一致。"""
    env = os.environ if env is None else env
    raw = (env.get("UVICORN_WORKERS") or "").strip()
    if raw:
        try:
            return int(raw)
        except ValueError:
            return 1
    return min(4, os.cpu_count() or 1)


def warn_if_l1_broadcast_disabled(workers: int) -> None:
    """多 worker 但未开 L1 广播时告警：否则最长 local_ttl 内会读到脏数据。"""
    if workers >= 2 and not _L1_BROADCAST_ENABLED:
        logger.warning(
            "UVICORN_WORKERS=%d 但 CACHE_L1_BROADCAST_ENABLED=false："
            "多 worker 下 L1 缓存最长 local_ttl 内可能读到脏数据",
            workers,
        )


def _record_cache_op(operation: str) -> None:
    """记录一次缓存访问结果到 Prometheus（供命中率观测）。

    operation 取值：
      l1_hit       — 进程内缓存命中
      l2_hit       — Redis 命中
      miss         — 两级均未命中（需回源计算）
      wait         — 未获击穿锁，等待持锁方回填后命中
      stale        — 未获锁且等待超时，自行重算
      redis_error  — Redis 读写异常

    说明：埋点是观测需求，不应影响主流程；因此吞掉所有异常。
    未安装 prometheus_client 时（如轻量测试环境）静默跳过。
    """
    # 埋点失败绝不影响缓存主流程（未安装 prometheus_client 时静默跳过）
    with contextlib.suppress(Exception):
        from fastapi_app.core.metrics import CACHE_OPERATIONS
        CACHE_OPERATIONS.labels(operation=operation).inc()


class CacheDomain(Flag):
    """缓存域枚举，支持按位或组合"""
    NONE = 0
    ORDER = auto()
    INVENTORY = auto()
    STOCKIN = auto()
    PRODUCT = auto()      # 预留：产品信息变更时失效
    CUSTOMER = auto()     # 预留：客户信息变更时失效
    SEARCH = auto()       # 预留：搜索索引变更时失效

    # 常用组合
    ORDER_AND_INVENTORY = ORDER | INVENTORY
    STOCKOUT = auto()
    MATERIAL = auto()
    REPORT = auto()
    ALL = ORDER | INVENTORY | STOCKIN | STOCKOUT | PRODUCT | CUSTOMER | SEARCH | MATERIAL | REPORT


# 缓存域 → pattern 映射（仅允许单域 key，禁止添加组合域 key，
# 否则 invalidate_related_caches 的按位与判断会导致重复失效）。
# value 为 tuple[str, ...]：一个域可对应多个 pattern。
_DOMAIN_PATTERN_MAP: dict[CacheDomain, tuple[str, ...]] = {
    CacheDomain.ORDER: ("orders:*",),
    # INVENTORY 域同时失效商品列表首屏缓存：product:list 含 current_stock
    # （Product.to_dict），故所有改库存的写路径（含直接发 ORDER_AND_INVENTORY 的
    # order/deduction、order/commands）都应清它；挂在 INVENTORY 域可一劳永逸覆盖。
    # PRODUCT_LIST_CACHE_PATTERN 是带 'erp:' 前缀的形式（单一事实来源）；
    # redis_cache._make_key 对已带 'erp:' 前缀的 key 幂等原样返回
    # （utils/redis_cache.py:110-112，由 test_redis_key_namespace.py:135 断言），
    # 故与相邻的无前缀字面量物理等价；且该缓存走裸 safe_set、无 L1 层，
    # _match_pattern 不受前缀影响。
    CacheDomain.INVENTORY: ("inventory:*", PRODUCT_LIST_CACHE_PATTERN),
    CacheDomain.STOCKIN: ("stockins:*",),
    CacheDomain.PRODUCT: ("products:*",),
    CacheDomain.CUSTOMER: ("customers:*",),
    CacheDomain.SEARCH: ("search:*",),
    CacheDomain.STOCKOUT: ("stockouts:*",),
    CacheDomain.MATERIAL: ("material:*",),
    # 报表流水（reports:order_logs / stockin_logs / stockout_logs / deduction_logs）
    # 由订单、备货、出货数据聚合而来，因此这三类写路径都必须一并失效 REPORT 域，
    # 否则报表页在 TTL 内持续展示写入前的旧数据。
    CacheDomain.REPORT: ("reports:*",),
}


async def invalidate_related_caches(domains: CacheDomain) -> int:
    """根据缓存域枚举失效相关缓存

    Args:
        domains: 缓存域枚举，支持按位或组合，如 CacheDomain.ORDER | CacheDomain.INVENTORY

    Returns:
        失效的缓存条目数
    """
    if domains == CacheDomain.NONE:
        logger.debug("invalidate_related_caches: 传入 NONE，跳过缓存失效")
        return 0

    deleted = 0
    for domain, patterns in _DOMAIN_PATTERN_MAP.items():
        # 仅匹配单域：跳过组合域 key，防止按位与导致重复失效
        if domain.value & (domain.value - 1) != 0:
            continue
        if domains & domain:
            for pattern in patterns:
                try:
                    deleted += await invalidate_cache(pattern)
                except (RuntimeError, OSError, ValueError) as e:
                    logger.warning("缓存域 %s 失效失败，继续处理其他域: %s", domain.name, e)
    return deleted


def _evict_local_cache() -> int:
    """清理过期条目并淘汰超限条目（O(1) LRU）"""
    now = datetime.now()
    # 先清理过期条目
    expired_keys = [k for k, (_, exp) in _cache_local.items() if now >= exp]
    for k in expired_keys:
        _cache_local.pop(k, None)
    # 淘汰最旧的条目（FIFO 端）
    while len(_cache_local) > _CACHE_LOCAL_MAX_SIZE:
        _cache_local.popitem(last=False)
    return len(expired_keys)


def _get_redis_cache():
    """获取 Redis 缓存实例（延迟导入避免循环依赖）"""
    try:
        from utils.redis_cache import redis_cache
        return redis_cache
    except (ImportError, OSError):
        return None


async def _acquire_stampede_lock(redis, lock_key: str, token: str) -> bool:
    """尝试获取缓存击穿分布式锁（SET NX EX 10，value=属主 token）"""
    client = getattr(redis, 'redis_client', None)
    if client is None:
        return False
    try:
        full_lock_key = redis._make_key(lock_key)
        got = await asyncio.wait_for(
            client.set(full_lock_key, token, nx=True, ex=10),
            timeout=CACHE_TIMEOUT,
        )
        return bool(got)
    except _CACHE_INFRA_EXCEPTIONS_WITH_VALUE:
        return False


async def _release_stampede_lock(redis, lock_key: str, token: str) -> None:
    """释放击穿锁（Lua 比对 token，仅删除自己持有的锁；失败依赖 TTL 过期兜底）"""
    client = getattr(redis, 'redis_client', None)
    if client is None:
        return
    try:
        full_lock_key = redis._make_key(lock_key)
        await asyncio.wait_for(
            client.eval(_RELEASE_LOCK_LUA, 1, full_lock_key, token),
            timeout=CACHE_TIMEOUT,
        )
    except _CACHE_INFRA_EXCEPTIONS_WITH_VALUE:
        pass  # 释放失败无害：锁 10s 后自动过期


async def _poll_for_refill(redis, cache_key: str, local_ttl: int) -> Any | None:
    """自旋等待持锁 worker 回填缓存，命中即回填 L1 并返回；超时/失败返回 None"""
    deadline = datetime.now() + timedelta(seconds=_CACHE_REFILL_POLL_SECONDS)
    while datetime.now() < deadline:
        await asyncio.sleep(_CACHE_REFILL_POLL_INTERVAL)
        try:
            cached = await asyncio.wait_for(redis.get(cache_key), timeout=CACHE_TIMEOUT)
        except _CACHE_INFRA_EXCEPTIONS:
            return None
        if cached is not None:
            _cache_local.pop(cache_key, None)
            _cache_local[cache_key] = (cached, datetime.now() + timedelta(seconds=local_ttl))
            return cached
    return None


def _build_cache_key(key_prefix: str, key_builder: Callable | None,
                     sig: inspect.Signature, args: tuple, kwargs: dict) -> str:
    """构建缓存键：有 key_builder 用参数名绑定；否则对参数做 md5 摘要。"""
    if key_builder:
        # 把位置参数绑定到参数名，key_builder 始终通过 kwargs 访问
        bound = sig.bind(*args, **kwargs)
        bound.apply_defaults()
        return f"{key_prefix}:{key_builder(**bound.arguments)}"
    params_str = json.dumps({'args': args, 'kwargs': kwargs}, sort_keys=True, default=str)
    params_hash = hashlib.md5(params_str.encode(), usedforsecurity=False).hexdigest()[:10]
    return f"{key_prefix}:{params_hash}"


def _redis_circuit_check(now: datetime) -> bool:
    """断路器：Redis 连续失败超过阈值时跳过。返回 Redis 是否可用。"""
    global _redis_circuit_open_until, _redis_fail_count
    if _redis_circuit_open_until is not None:
        if now < _redis_circuit_open_until:
            return False
        _redis_circuit_open_until = None
        _redis_fail_count = 0
    return True


def _note_redis_failure(now: datetime, e: Exception | None, *, record_op: str | None = None) -> None:
    """记录一次 Redis 失败，达阈值开断路器（P2-14 从 wrapper 内三处重复提取）。

    record_op：调用方如需打点（读路径打 redis_error）自行指定；写路径原实现
    不打点，保持 None 以维持 metrics 语义不变。
    """
    global _redis_fail_count, _redis_circuit_open_until
    _redis_fail_count += 1
    if record_op:
        _record_cache_op(record_op)
    if _redis_fail_count >= _REDIS_CIRCUIT_THRESHOLD:
        _redis_circuit_open_until = now + _REDIS_CIRCUIT_COOLDOWN
        logger.warning("Redis 断路器开启，%s秒内跳过Redis: %s",
                       _REDIS_CIRCUIT_COOLDOWN.total_seconds(), e)


def _l1_get(cache_key: str, now: datetime) -> tuple[bool, Any]:
    """L1 命中检查。返回 (命中?, 值)。过期条目不回插。"""
    if cache_key in _cache_local:
        value, expire_at = _cache_local.pop(cache_key)  # 移除
        if now < expire_at:
            _cache_local[cache_key] = (value, expire_at)  # 移到末尾（最近使用）
            _record_cache_op('l1_hit')
            return True, value
        # 已过期，不回插
    return False, None


def _l1_put(cache_key: str, value: Any, local_ttl: int) -> None:
    """写入 L1：先移除再插入，保证 OrderedDict 顺序，并做容量驱逐。"""
    _cache_local.pop(cache_key, None)
    _cache_local[cache_key] = (value, datetime.now() + timedelta(seconds=local_ttl))
    _evict_local_cache()


async def _compute_and_fill(func, args, kwargs, cache_key: str, local_ttl: int,
                            redis, redis_available: bool, ttl: int = 60) -> Any:
    """重算并回填 L1+L2（获锁路径与无 Redis 路径共用，P2-14 提取）。

    L2 写失败按写路径语义处理：计数 + 断路器，不打点、不抛出。
    """
    result = await func(*args, **kwargs)
    _l1_put(cache_key, result, local_ttl)
    if redis and redis_available:
        try:
            await asyncio.wait_for(
                redis.set(cache_key, result, timeout=int(ttl)),
                timeout=CACHE_TIMEOUT
            )
            global _redis_fail_count
            _redis_fail_count = 0
        except _CACHE_INFRA_EXCEPTIONS_WITH_VALUE as e:
            _note_redis_failure(datetime.now(), e)
    return result


async def _read_l2(redis, cache_key: str) -> tuple[bool, Any]:
    """L2 读取 + 断路器记账（P2-14 提取）。返回 (命中?, 值)。"""
    global _redis_fail_count
    try:
        cached = await asyncio.wait_for(redis.get(cache_key), timeout=CACHE_TIMEOUT)
        if cached is not None:
            _redis_fail_count = 0
            return True, cached
        _redis_fail_count = 0
    except _CACHE_INFRA_EXCEPTIONS_WITH_VALUE as e:
        _note_redis_failure(datetime.now(), e, record_op='redis_error')
        logger.warning("Redis 缓存读取失败(timeout=%ss)，降级到数据库查询: %s", CACHE_TIMEOUT, e)
    return False, None


async def _stampede_resolve(redis, redis_available: bool, cache_key: str,
                            local_ttl: int, lock_token: str) -> tuple[bool, Any]:
    """击穿保护：未获锁时先轮询等持锁方回填，超时再试一次拿锁（P2-14 提取）。

    返回 (是否最终持锁, 轮询得到的值)。轮询命中时 (False, value)——调用方直接返回。
    """
    global _redis_fail_count
    lock_acquired = False
    if redis and redis_available:
        lock_acquired = await _acquire_stampede_lock(redis, f"{cache_key}:lock", lock_token)

    if not lock_acquired and redis and redis_available:
        # 未获锁：先轮询等持锁方回填（上限 _CACHE_REFILL_POLL_SECONDS），命中直接返回
        polled = await _poll_for_refill(redis, cache_key, local_ttl)
        if polled is not None:
            _redis_fail_count = 0
            _record_cache_op('wait')
            return False, polled
        # 轮询超时（持锁方还没写完）：再试一次拿锁，拿到就自己重算
        lock_acquired = await _acquire_stampede_lock(redis, f"{cache_key}:lock", lock_token)
    return lock_acquired, None


def cache_result(
    key_prefix: str,
    ttl: int = 60,
    local_ttl: int = 30,
    key_builder: Callable | None = None,
):
    """
    缓存装饰器 - 支持 L1(内存) + L2(Redis) 两级缓存

    key_builder 签名约定：始终通过 **kwargs 接收参数（参数名与被装饰函数签名一致）。
    装饰器内部用 inspect.signature.bind 把位置参数绑定到参数名，因此无论调用方
    使用位置参数还是关键字参数，key_builder 都能通过 kwargs.get('param_name') 正确读取。
    """
    def decorator(func):
        # 预编译函数签名，避免每次调用重复解析
        sig = inspect.signature(func)

        @wraps(func)
        async def wrapper(*args, **kwargs):
            global _redis_fail_count
            try:
                cache_key = _build_cache_key(key_prefix, key_builder, sig, args, kwargs)
                now = datetime.now()

                hit, l1_value = _l1_get(cache_key, now)
                if hit:
                    return l1_value

                # 断路器：Redis 连续失败超过阈值时跳过
                redis_available = _redis_circuit_check(now)

                redis = _get_redis_cache() if redis_available else None
                if redis:
                    l2_hit, cached = await _read_l2(redis, cache_key)
                    if l2_hit:
                        _l1_put(cache_key, cached, local_ttl)
                        _record_cache_op('l2_hit')
                        return cached

                # 缓存击穿保护：分布式锁防止雪崩（stampede）
                # 获得锁的 worker 重算并回填；未获锁的 worker 短暂轮询后放弃等待自行重算
                lock_token = uuid.uuid4().hex
                lock_acquired, polled = await _stampede_resolve(
                    redis, redis_available, cache_key, local_ttl, lock_token
                )
                if polled is not None:
                    return polled

                if lock_acquired:
                    # 获得锁：重算并回填缓存
                    try:
                        _record_cache_op('miss')
                        result = await _compute_and_fill(
                            func, args, kwargs, cache_key, local_ttl,
                            redis, redis_available, ttl=ttl,
                        )
                        return result
                    finally:
                        if redis is not None:
                            # 释锁失败绝不能吞掉已算好的业务结果（此前 Redis 在
                            # 重算期间死亡时，释锁抛异常会覆盖 return 值 → 500）
                            with contextlib.suppress(Exception):
                                await _release_stampede_lock(redis, f"{cache_key}:lock", lock_token)

                # 未获锁且轮询未命中（或 Redis 不可用）：直接重算，保证请求总能返回
                _record_cache_op('stale')
                return await _compute_and_fill(
                    func, args, kwargs, cache_key, local_ttl,
                    redis, redis_available, ttl=ttl,
                )

            except _CACHE_INFRA_EXCEPTIONS as e:
                logger.error("缓存装饰器执行失败: %s", e, exc_info=True)
                return await func(*args, **kwargs)

        return wrapper
    return decorator


async def invalidate_cache(pattern: str) -> int:
    """使缓存失效（先删 L2 Redis，再删 L1 本地，缩小竞态窗口）"""
    try:
        deleted = 0

        # 先删 L2 Redis，防止其他进程/协程从 Redis 读到旧数据回填 L1
        redis = _get_redis_cache()
        if redis:
            try:
                redis_deleted = await redis.delete_pattern(pattern)
                deleted += redis_deleted
                logger.info("Redis 缓存失效: pattern=%s, deleted=%d", pattern, redis_deleted)
            except _CACHE_INFRA_EXCEPTIONS_WITH_VALUE as e:
                logger.warning("Redis 缓存失效失败: %s", e)

        # 再删 L1 本地缓存
        keys_to_remove = [k for k in _cache_local if _match_pattern(k, pattern)]
        for k in keys_to_remove:
            _cache_local.pop(k, None)
        deleted += len(keys_to_remove)

        # 广播给其他 worker 同步失效 L1（开关默认关，失败不影响主流程）
        await _publish_l1_invalidation(pattern)

        return deleted
    except _CACHE_INFRA_EXCEPTIONS_WITH_VALUE as e:
        logger.error("缓存失效失败: %s", e, exc_info=True)
        return 0


def invalidate_local_cache(pattern: str) -> int:
    """仅使进程内 L1 缓存失效"""
    keys_to_remove = [k for k in _cache_local if _match_pattern(k, pattern)]
    for k in keys_to_remove:
        _cache_local.pop(k, None)
    return len(keys_to_remove)


async def _publish_l1_invalidation(pattern: str) -> None:
    """发布 L1 失效广播（fire-and-forget，失败仅告警不阻断主流程）"""
    if not _L1_BROADCAST_ENABLED:
        return
    redis = _get_redis_cache()
    client = getattr(redis, 'redis_client', None) if redis else None
    if client is None:
        return
    try:
        await asyncio.wait_for(
            client.publish(redis._make_key(_L1_BROADCAST_CHANNEL), pattern),
            timeout=CACHE_TIMEOUT,
        )
    except _CACHE_INFRA_EXCEPTIONS_WITH_VALUE as e:
        logger.warning("发布 L1 缓存失效广播失败: %s", e)


async def _close_pubsub(pubsub, channel: str) -> None:
    """安全关闭 pubsub（unsubscribe 与 aclose 独立容错，避免前者失败泄漏连接）"""
    with contextlib.suppress(*_CACHE_INFRA_EXCEPTIONS):
        await pubsub.unsubscribe(channel)
    with contextlib.suppress(*_CACHE_INFRA_EXCEPTIONS):
        await pubsub.aclose()


async def _l1_broadcast_listener() -> None:
    """订阅 L1 失效广播，同步清理本进程 L1（幂等，含自身发布的消息）

    Redis 断线/重启后自动退避重连，避免监听静默永久失效。
    """
    while True:
        redis = _get_redis_cache()
        client = getattr(redis, 'redis_client', None) if redis else None
        if client is None:
            logger.warning("Redis 不可用，L1 失效广播监听器 %ss 后重试", _L1_RECONNECT_BACKOFF)
            await asyncio.sleep(_L1_RECONNECT_BACKOFF)
            continue
        pubsub = client.pubsub()
        channel = redis._make_key(_L1_BROADCAST_CHANNEL)
        try:
            await pubsub.subscribe(channel)
            async for message in pubsub.listen():
                if message.get('type') != 'message':
                    continue
                try:
                    data = message['data']
                    pattern = data.decode('utf-8', errors='replace') if isinstance(data, bytes) else str(data)
                    removed = invalidate_local_cache(pattern)
                    if removed:
                        logger.debug("L1 缓存失效广播同步清理 %d 条: %s", removed, pattern)
                except (KeyError, UnicodeDecodeError) as e:
                    logger.warning("解析 L1 失效广播消息失败: %s", e)
        except asyncio.CancelledError:
            await _close_pubsub(pubsub, channel)
            raise
        except _CACHE_INFRA_EXCEPTIONS as e:
            logger.warning("L1 失效广播监听断线，%ss 后重连: %s", _L1_RECONNECT_BACKOFF, e)
            await _close_pubsub(pubsub, channel)
            await asyncio.sleep(_L1_RECONNECT_BACKOFF)


async def start_l1_broadcast_listener() -> None:
    """启动 L1 失效广播监听器（仅 CACHE_L1_BROADCAST_ENABLED=true 时生效）"""
    global _broadcast_task
    if not _L1_BROADCAST_ENABLED:
        return
    if _broadcast_task is None or _broadcast_task.done():
        _broadcast_task = asyncio.create_task(_l1_broadcast_listener(), name='l1-cache-broadcast')
        logger.info("L1 缓存跨 worker 失效广播监听器已启动")


async def stop_l1_broadcast_listener() -> None:
    """停止 L1 失效广播监听器"""
    global _broadcast_task
    if _broadcast_task is not None and not _broadcast_task.done():
        _broadcast_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await _broadcast_task
    _broadcast_task = None


def _match_pattern(key: str, pattern: str) -> bool:
    import fnmatch
    return fnmatch.fnmatch(key, pattern)


async def invalidate_dashboard_cache():
    """失效 dashboard 相关缓存，确保数据同步"""
    try:
        await invalidate_cache('dashboard:*')
        await invalidate_cache('dashboard:stats')
        await invalidate_cache('dashboard:activities')
        logger.info("Dashboard 缓存已失效")
    except _CACHE_INFRA_EXCEPTIONS as e:
        logger.warning(f"失效 Dashboard 缓存失败: {e}")
