"""共享异步 Redis 客户端（core 层基础设施）

批次1（2026-08-22）自 services/notification_service.py 上提：此前 5 个 core
模块（健康检查/备份进度/采购缓存/恢复进度）懒加载服务层私有函数获取客户端，
使 notification_service 成为 core 的隐性依赖中心。现统一依赖本模块，
notification_service 转为消费方（保留兼容转发）。
"""
import logging

logger = logging.getLogger(__name__)

_async_redis_client = None


def redis_infra_exceptions():
    """基础设施异常元组（含 redis.exceptions.RedisError）。

    注意：redis-py 的 ConnectionError/AuthenticationError 继承自 RedisError
    而非 Python 内置 ConnectionError，必须显式纳入，否则 Redis 不可用/认证
    失败会在启动预热时逃逸并导致应用启动崩溃。

    历史：本函数曾手工拼接 (*INFRA_EXCEPTIONS, RedisError) 作为局部绕过。
    RedisError 现已收进 exception_handler.INFRA_EXCEPTIONS 根定义，
    本函数保留为兼容转发（notification_service 等仍在调用）。
    """
    from fastapi_app.core.exception_handler import INFRA_EXCEPTIONS
    return INFRA_EXCEPTIONS


async def get_async_redis_client():
    """获取或创建模块级共享异步 Redis 客户端（初始化失败返回 None）"""
    global _async_redis_client
    if _async_redis_client is not None:
        return _async_redis_client

    try:
        from urllib.parse import quote_plus

        import redis.asyncio as aioredis

        from fastapi_app.core.config import settings

        url = settings.REDIS_URL
        if settings.REDIS_PASSWORD and settings.REDIS_PASSWORD not in url:
            # 使用 quote_plus 对密码进行 URL 编码，避免密码中包含
            # 特殊字符（如 @ : / ? # %）破坏 URL 解析或被注入攻击
            encoded_password = quote_plus(settings.REDIS_PASSWORD)
            if url.startswith("rediss://"):
                url = url.replace("rediss://", f"rediss://:{encoded_password}@")
            elif url.startswith("redis://"):
                url = url.replace("redis://", f"redis://:{encoded_password}@")
        # 双超时（评审 2026-10-10 P1-7）：裸 from_url 无超时，Redis 挂起（而非
        # 拒绝连接）时备份进度 WebSocket 等消费方可无限阻塞。正常内网往返毫秒级，
        # 2s 预算足够宽裕；调用方均有 try/except 兜底，超时异常等价于"Redis 不可用"。
        _async_redis_client = aioredis.from_url(
            url,
            socket_timeout=2.0,
            socket_connect_timeout=2.0,
            max_connections=50,
        )
        return _async_redis_client
    except redis_infra_exceptions() as e:
        logger.warning("异步 Redis 客户端初始化失败: %s", e)
        return None


async def close_async_redis_client():
    """关闭并丢弃共享客户端（main.py 关停序调用，防泄漏连接）。"""
    global _async_redis_client
    if _async_redis_client is not None:
        try:
            await _async_redis_client.aclose()
        except Exception as e:  # defensive: 关停路径，失败仅记日志
            logger.warning("共享 Redis 客户端关闭失败: %s", e)
    _async_redis_client = None


def reset_async_redis_client():
    """丢弃当前客户端实例（预热失败时强制下次重建）"""
    global _async_redis_client
    _async_redis_client = None
