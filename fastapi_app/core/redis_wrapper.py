"""
Redis 缓存操作统一包装器

封装 utils.redis_cache 的常用操作，统一异常处理和日志格式。
所有方法在 Redis 不可用时静默降级，不影响核心业务流程。
"""
import contextlib
import logging
import os
from typing import Any

from fastapi_app.core.exception_handler import INFRA_EXCEPTIONS

logger = logging.getLogger(__name__)


async def safe_get(key: str, fallback: Any = None, context: str = "") -> Any:
    """安全获取 Redis 缓存

    用法:
        cached = await safe_get("active_customer_names", context="客户名称缓存")
    """
    try:
        from utils.redis_cache import redis_cache
        return await redis_cache.get(key)
    except INFRA_EXCEPTIONS as e:
        logger.warning("%s读取失败: %s", _ctx(context, key), e)
        return fallback


async def safe_set(key: str, value: Any, timeout: int = 300, context: str = "") -> bool:
    """安全设置 Redis 缓存

    用法:
        await safe_set("active_customer_names", data, timeout=300, context="客户名称缓存")
    """
    try:
        from utils.redis_cache import redis_cache
        await redis_cache.set(key, value, timeout=timeout)
        return True
    except INFRA_EXCEPTIONS as e:
        logger.warning("%s写入失败: %s", _ctx(context, key), e)
        return False


async def safe_delete(key: str, context: str = "") -> bool:
    """安全删除 Redis 缓存

    用法:
        await safe_delete("active_customer_names", context="客户名称缓存")
    """
    try:
        from utils.redis_cache import redis_cache
        await redis_cache.delete(key)
        return True
    except INFRA_EXCEPTIONS as e:
        logger.warning("%s删除失败: %s", _ctx(context, key), e)
        return False


async def safe_delete_pattern(pattern: str, context: str = "") -> int:
    """安全按模式删除 Redis 缓存

    用法:
        await safe_delete_pattern("pp:monthly:*", context="月度日历缓存")
    """
    try:
        from utils.redis_cache import redis_cache
        return await redis_cache.delete_pattern(pattern)
    except INFRA_EXCEPTIONS as e:
        logger.warning("%s模式删除失败: %s", _ctx(context, pattern), e)
        return 0


async def ping(context: str = "Redis连接检查") -> bool:
    """检查 Redis 是否可用，用于健康检查端点

    Returns:
        bool: 连接可用返回 True，否则返回 False
    """
    try:
        from utils.redis_cache import redis_cache
        client = getattr(redis_cache, 'redis_client', None)
        if client is None:
            return False
        return bool(await client.ping())
    except INFRA_EXCEPTIONS as e:
        logger.warning("%s失败: %s", context, e)
        return False


def get_client():
    """安全获取底层 Redis 客户端实例

    返回 None 表示 Redis 不可用，调用方需进行 None 检查。
    用于需要直接操作 Redis 原生命令（如 pub/sub、list 操作）的场景。

    用法:
        client = get_client()
        if client:
            await client.publish('channel', message)
    """
    try:
        from utils.redis_cache import redis_cache
        # 走 ensure_client() 而非直接读 redis_client：客户端缺失时它会惰性重建（自愈）。
        # 否则「Redis 启动即不可用」会让本进程**永久**拿不到客户端（撤销黑名单、
        # 限流等裸客户端路径全部退化为内存降级）。见 RedisCacheManager 类 docstring。
        return redis_cache.ensure_client()
    except (ImportError, OSError, RuntimeError):
        return None


def note_command_success() -> None:
    """告知缓存管理器一条 Redis 命令成功（复位自愈/退避窗口）。

    「端点/服务不得直接 import utils.redis_cache」是本项目的既有约定
    （守卫见 tests/test_p3_redis_wrapper.py）。需要上报成败时请用本模块的
    `note_command_success` / `note_command_failure`，不要绕过边界。
    """
    with contextlib.suppress(Exception):
        from utils.redis_cache import redis_cache
        redis_cache.note_command_success()


def note_command_failure(exc: Exception) -> None:
    """告知缓存管理器一条 Redis 命令失败（连接类错误会 arm 退避窗口）。"""
    with contextlib.suppress(Exception):
        from utils.redis_cache import redis_cache
        redis_cache.note_command_failure(exc)


async def safe_lpush(key: str, *values: Any, context: str = "") -> int:
    """安全向左推入 List"""
    try:
        client = get_client()
        if client is None:
            return 0
        return await client.lpush(key, *values)
    except INFRA_EXCEPTIONS as e:
        logger.warning("%slpush失败: %s", _ctx(context, key), e)
        return 0


async def safe_rpush(key: str, *values: Any, context: str = "") -> int:
    """安全向右推入 List"""
    try:
        client = get_client()
        if client is None:
            return 0
        return await client.rpush(key, *values)
    except INFRA_EXCEPTIONS as e:
        logger.warning("%srpush失败: %s", _ctx(context, key), e)
        return 0


async def safe_lrange(key: str, start: int, end: int, context: str = "") -> list:
    """安全获取 List 范围"""
    try:
        client = get_client()
        if client is None:
            return []
        return await client.lrange(key, start, end)
    except INFRA_EXCEPTIONS as e:
        logger.warning("%slrange失败: %s", _ctx(context, key), e)
        return []


async def safe_ltrim(key: str, start: int, end: int, context: str = "") -> bool:
    """安全裁剪 List"""
    try:
        client = get_client()
        if client is None:
            return False
        await client.ltrim(key, start, end)
        return True
    except INFRA_EXCEPTIONS as e:
        logger.warning("%sltrim失败: %s", _ctx(context, key), e)
        return False


# 释放锁：比对 token 后删除，避免误删他人持有的锁（异常时靠 TTL 兜底）
_RELEASE_LOCK_LUA = (
    "if redis.call('get', KEYS[1]) == ARGV[1] then "
    "return redis.call('del', KEYS[1]) else return 0 end"
)


async def safe_acquire_lock(key: str, token: str, ttl: int = 10, context: str = "") -> bool:
    """尝试获取分布式锁（SET NX EX）。

    拿不到锁（已被他人持有 / Redis 不可用 / 超时）一律返回 False，
    调用方应当**跳过本轮**而不是继续执行 —— 跳过只是推迟，继续才会破坏临界区。

    本机 Redis 为 5.0，没有 LPOP count / LMPOP，无法用原子弹出替代锁，
    故「读一批 + 裁掉一批」这类临界区只能靠本锁互斥。
    """
    try:
        client = get_client()
        if client is None:
            return False
        return bool(await client.set(key, token, nx=True, ex=ttl))
    except INFRA_EXCEPTIONS as e:
        logger.warning("%s获取锁失败: %s", _ctx(context, key), e)
        return False


async def safe_release_lock(key: str, token: str, context: str = "") -> None:
    """释放分布式锁（Lua 比对 token，只删自己持有的；失败依赖 TTL 过期兜底）。"""
    try:
        client = get_client()
        if client is None:
            return
        await client.eval(_RELEASE_LOCK_LUA, 1, key, token)
    except INFRA_EXCEPTIONS as e:
        logger.warning("%s释放锁失败: %s", _ctx(context, key), e)


async def safe_llen_ex(key: str, context: str = "") -> int | None:
    """三态 List 长度：``None`` = 状态不可知（M1，2026-10-25 上线前检查）。

    ``safe_llen`` 把「client 缺失 / 基础设施异常」全部折叠成 0——对缓存类调用
    是合理降级，但对**以 0 为语义**的消费者（死信巡检「队列空 = 一切正常」）
    是假健康：故障被洗成「无残留」。需要区分「真实空队列」与「查不出来」的
    调用方必须用本函数，unknown 分支自行显式失败/告警。
    """
    try:
        client = get_client()
        if client is None:
            return None
        return int(await client.llen(key))
    except INFRA_EXCEPTIONS as e:
        logger.warning("%sllen失败: %s", _ctx(context, key), e)
        return None


async def safe_llen(key: str, context: str = "") -> int:
    """安全获取 List 长度（不可知折叠为 0；需要三态语义请用 ``safe_llen_ex``）"""
    n = await safe_llen_ex(key, context)
    return n if n is not None else 0


async def safe_lrem(key: str, count: int, value: Any, context: str = "") -> int:
    """安全从 List 中移除元素"""
    try:
        client = get_client()
        if client is None:
            return 0
        return await client.lrem(key, count, value)
    except INFRA_EXCEPTIONS as e:
        logger.warning("%slrem失败: %s", _ctx(context, key), e)
        return 0


async def safe_publish(channel: str, message: Any, context: str = "") -> int:
    """安全发布 Pub/Sub 消息"""
    try:
        client = get_client()
        if client is None:
            return 0
        return await client.publish(channel, message)
    except INFRA_EXCEPTIONS as e:
        logger.warning("[%s] publish失败(channel=%s): %s", context, channel, e)
        return 0


async def safe_incr(key: str, context: str = "") -> int:
    """安全原子递增计数器"""
    try:
        client = get_client()
        if client is None:
            return 0
        return await client.incr(key)
    except INFRA_EXCEPTIONS as e:
        logger.warning("%sincr失败: %s", _ctx(context, key), e)
        return 0


async def safe_expire(key: str, seconds: int, context: str = "") -> bool:
    """安全设置键过期时间"""
    try:
        client = get_client()
        if client is None:
            return False
        return await client.expire(key, seconds)
    except INFRA_EXCEPTIONS as e:
        logger.warning("%sexpire失败: %s", _ctx(context, key), e)
        return False


async def safe_exists(key: str, context: str = "") -> bool:
    """安全检查键是否存在"""
    try:
        client = get_client()
        if client is None:
            return False
        return bool(await client.exists(key))
    except INFRA_EXCEPTIONS as e:
        logger.warning("%sexists失败: %s", _ctx(context, key), e)
        return False


async def safe_get_stats(context: str = "Redis统计") -> dict:
    """安全获取Redis服务器统计信息"""
    stats = {'backend': 'memory', 'connected': False}
    try:
        from utils.redis_cache import redis_cache
        client = get_client()
        if client is None:
            stats['fallback_cache_size'] = len(getattr(redis_cache, '_fallback_cache', {}))
            return stats
        info = await client.info()
        stats.update({
            'backend': 'redis',
            'connected': True,
            'connected_clients': info.get('connected_clients', 0),
            'used_memory_human': info.get('used_memory_human', '0B'),
            'total_commands_processed': info.get('total_commands_processed', 0),
            'keyspace_hits': info.get('keyspace_hits', 0),
            'keyspace_misses': info.get('keyspace_misses', 0),
        })
    except INFRA_EXCEPTIONS as e:
        stats['error'] = str(e)
        logger.warning("%s失败: %s", context, e)
    return stats


def _ctx(context: str, key: str) -> str:
    if context:
        return f"[{context}] key={key}"
    return f"key={key}"


# ==================== Redis Sentinel 支持 ====================

def create_sentinel_client(
    sentinel_hosts: str,
    master_name: str = "mymaster",
    password: str = "",
    db: int = 0,
    socket_timeout: float = 0.5,
) -> Any:
    """创建 Redis Sentinel 客户端

    Args:
        sentinel_hosts: Sentinel 节点列表，逗号分隔 (host1:port1,host2:port2)
        master_name: Sentinel master 名称
        password: Redis 认证密码
        db: Redis 数据库编号
        socket_timeout: 连接超时

    Returns:
        Redis 客户端实例（指向 master）

    用法:
        # 在 config.py 或启动脚本中
        if settings.REDIS_SENTINEL_HOSTS:
            client = create_sentinel_client(
                settings.REDIS_SENTINEL_HOSTS,
                password=settings.REDIS_PASSWORD,
            )
    """
    try:
        import redis.asyncio as aioredis
        from redis.sentinel import Sentinel

        sentinel_nodes = [
            (h.strip(), int(p.strip()))
            for h, p in [
                addr.split(":") for addr in sentinel_hosts.split(",")
            ]
        ]

        sentinel = Sentinel(sentinel_nodes, socket_timeout=socket_timeout)

        # 获取 master 地址
        master_host, master_port = sentinel.discover_master(master_name)

        # 创建异步客户端连接 master
        client = aioredis.Redis(
            host=master_host,
            port=master_port,
            password=password if password else None,
            db=db,
            socket_timeout=socket_timeout,
            decode_responses=True,
        )

        logger.info(
            "Redis Sentinel 客户端已创建: master=%s:%d (sentinels=%d)",
            master_host, master_port, len(sentinel_nodes)
        )
        return client

    except ImportError:
        logger.warning("redis.sentinel 不可用，请安装 redis[hiredis]")
        return None
    except Exception as e:  # broad-except: Redis 连接容错，失败时降级处理
        logger.error("Redis Sentinel 客户端创建失败: %s", e)
        return None


async def get_sentinel_aware_client() -> Any:
    """获取 Sentinel 感知的 Redis 客户端

    优先使用 Sentinel 模式（如果配置了 REDIS_SENTINEL_HOSTS），
    否则回退到普通客户端。
    """
    from fastapi_app.core.config import settings

    if settings.REDIS_SENTINEL_HOSTS:
        return create_sentinel_client(
            sentinel_hosts=settings.REDIS_SENTINEL_HOSTS,
            password=settings.REDIS_PASSWORD,
            db=settings.REDIS_DB,
        )

    # 回退到普通客户端
    return get_client()


# ==================== 共享缓存管理器初始化 ====================

async def init_redis_cache_manager() -> None:
    """初始化 ``utils.redis_cache`` 的共享缓存管理器（API 与 ARQ worker 共用）。

    ``redis_cache`` 必须在**每个使用它的进程**启动时 ``init_app()`` 一次，否则
    ``ensure_client()`` 恒返回 ``None``，经本模块的所有路径静默降级
    （返回 ``None``/``0``/空）。2026-10-11 发现：只有 API 进程的 lifespan 调用过
    它，**ARQ worker 进程从不调用** —— 于是 worker 里 ``safe_lpush`` 写不进死信队列
    （``arq:dead_letter`` 恒空）、worker 侧一切 Redis 缓存形同虚设。

    API 的 ``main.py`` lifespan 与 worker 的 ``WorkerSettings.on_startup`` 都调用
    本函数。失败静默降级（与 ``init_app`` 语义一致）：Redis 不可用不得阻断启动。
    """
    from fastapi_app.core.config import settings
    from utils.redis_cache import redis_cache

    try:
        redis_url = (
            settings.REDIS_CACHE_URL
            or os.getenv('REDIS_CACHE_URL')
            or os.getenv('REDIS_URL')
        )
        if redis_url:
            await redis_cache.init_app(redis_url=redis_url)
        else:
            await redis_cache.init_app(
                redis_host=settings.REDIS_HOST,
                redis_port=settings.REDIS_PORT,
                redis_db=settings.REDIS_DB,
                redis_password=settings.REDIS_PASSWORD or None,
            )
        stats = await redis_cache.get_stats()
        logger.info("Redis缓存管理器初始化完成: %s", stats.get('backend', 'unknown'))
    except (OSError, ValueError) as e:
        logger.warning("Redis缓存初始化失败: %s", e)
