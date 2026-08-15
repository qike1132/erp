"""
Redis 缓存操作统一包装器

封装 utils.redis_cache 的常用操作，统一异常处理和日志格式。
所有方法在 Redis 不可用时静默降级，不影响核心业务流程。
"""
import logging
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
        client = getattr(redis_cache, 'redis_client', None)
        return client
    except (ImportError, OSError, RuntimeError):
        return None


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


async def safe_llen(key: str, context: str = "") -> int:
    """安全获取 List 长度"""
    try:
        client = get_client()
        if client is None:
            return 0
        return await client.llen(key)
    except INFRA_EXCEPTIONS as e:
        logger.warning("%sllen失败: %s", _ctx(context, key), e)
        return 0


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
        from redis.sentinel import Sentinel
        import redis.asyncio as aioredis

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
    except Exception as e:
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
