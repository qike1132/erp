"""维护模式（M3）。

还原执行期间开启维护模式，拒绝非备份域写请求（返回 503 MAINTENANCE），
把「执行期间系统停止写入」从文案升级为工程保障。READ 与备份域 GET 放行。
"""
from __future__ import annotations

import logging

from starlette.datastructures import URL
from starlette.requests import Request
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)

_MAINTENANCE_KEY = 'erp:maintenance_mode'

# 备份域前缀：还原/备份相关写请求放行（其余业务写请求在维护期被拒绝）
_BACKUP_PATH_PREFIXES = ('/api/v1/backup/',)


async def _get_client():
    from fastapi_app.core.backup_progress import _get_redis
    return await _get_redis()


async def is_maintenance_mode() -> bool:
    """当前是否处于维护模式。Redis 不可用时读取兜底为 False（不阻塞业务）。"""
    try:
        client = await _get_client()
        if client is None:
            return False
        return bool(await client.get(_MAINTENANCE_KEY))
    except Exception as e:  # broad-except: 维护状态探测不允许中断请求
        logger.warning(f'读取维护模式失败: {e}')
        return False


async def enter_maintenance() -> bool:
    """开启维护模式（TTL 兜底自动清除，防止崩溃遗留）。"""
    try:
        client = await _get_client()
        if client is None:
            logger.warning('Redis 不可用，无法开启维护模式')
            return False
        await client.set(_MAINTENANCE_KEY, '1', ex=30 * 60)
        return True
    except Exception as e:  # broad-except: 维护开关失败不抛出
        logger.warning(f'开启维护模式失败: {e}')
        return False


async def exit_maintenance() -> None:
    """关闭维护模式。"""
    try:
        client = await _get_client()
        if client is not None:
            await client.delete(_MAINTENANCE_KEY)
    except Exception as e:  # broad-except: 维护开关失败不抛出
        logger.warning(f'关闭维护模式失败: {e}')


async def maintenance_middleware(
    request: Request,
    call_next,  # type: ignore[no-untyped-def]
):
    """维护模式中间件：开启期间，非备份域写请求返回 503 MAINTENANCE。"""
    if request.method in ('POST', 'PUT', 'PATCH', 'DELETE'):
        url: URL = request.url
        if not url.path.startswith(_BACKUP_PATH_PREFIXES) and await is_maintenance_mode():
            return JSONResponse(
                status_code=503,
                content={'detail': {'code': 'MAINTENANCE', 'message': '系统正在还原，暂时停止写入，请稍后重试'}},
            )
    return await call_next(request)