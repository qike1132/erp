"""维护模式（M3）。

还原执行期间开启维护模式，拒绝非备份域写请求（返回 503 MAINTENANCE），
把「执行期间系统停止写入」从文案升级为工程保障。READ 与备份域 GET 放行。

客户端来源与已知缺口（2026-09-28）
----------------------------------
**改动**：读取路径此前走 `backup_progress._get_redis()` →
`core/redis_client.get_async_redis_client()` —— 那是**另一个**模块级缓存客户端，
既不参与自愈、也不参与 `utils/redis_cache` 的降级/退避。现统一到
`redis_wrapper.get_client()`（自愈 + 退避），并在读写后告知成败。

**证据边界（重要，勿过度解读）**：症状是测试日志里反复出现
`读取维护模式失败: Event loop is closed`（约 2.4k 条）。经核查这些**全部来自
进程内测试套件**，而非生产：

* 真正的生产 stdout（`logs/后端(uvicorn).out.log`）在 09-17→09-28 全区间内
  **0 条**该类记录；
* `logs/erp.log` 并非生产日志 —— 其格式对应 `utils/logger.py`，唯一导入者是
  `tests/test_logger.py`，内含约 8.9k 行 `http://test`（httpx TestClient）；
* 机制上：`core/redis_client._async_redis_client` 是无复位的模块级全局，而
  pytest 按函数切换 event loop，于是测试 N 的客户端在测试 N+1 上必然报
  `Event loop is closed`。

**因此本改动带来的是**：与缓存层统一为一个受生命周期管理的客户端、失败进入退避、
日志有界。**它不是一次生产故障修复。**

**已知缺口（未修，需产品决策）**：`enter_maintenance()` / `exit_maintenance()`
**在生产代码里没有任何调用方** —— 还原流程用的是 `acquire_restore_lock`，
并不开启维护模式。因此「还原期间禁止写入」这个保证**目前并不存在**：
标志从未被置上，闸门自然不生效。要落实它，需要把这两个函数接进还原流程
（并确保结束时一定清除，TTL 30 分钟只是兜底）。
"""
from __future__ import annotations

import logging
import time

from starlette.datastructures import URL
from starlette.requests import Request
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)

_MAINTENANCE_KEY = 'erp:maintenance_mode'

# 备份域前缀：还原/备份相关写请求放行（其余业务写请求在维护期被拒绝）
_BACKUP_PATH_PREFIXES = ('/api/v1/backup/',)

# 读取失败日志的节流（秒）。维护模式在**每个写请求**上被读取，不节流会无界增长。
# ⚠️ 只按**同一异常类型**节流：不同异常类型必须照常记录 —— 否则一个刚出现的、
# 更严重的错误（认证失败、协议错误）会恰好落在上一个错误的窗口里被静默吞掉，
# 而恰恰是这类错误**不会**被退避短路。
_FAILURE_LOG_INTERVAL = 60.0
_last_failure_log: tuple[type[BaseException], float] | None = None


async def _get_client():
    """取**自愈**客户端（见模块 docstring：不再用另一个孤立客户端）。"""
    from fastapi_app.core.redis_wrapper import get_client
    return get_client()


def _report_success() -> None:
    """告知缓存管理器命令成功（复位退避）。通知失败不得影响业务。"""
    from fastapi_app.core.redis_wrapper import note_command_success
    note_command_success()


def _notify_failure(exc: Exception) -> None:
    """告知缓存管理器命令失败（连接类错误会 arm 退避）。不做日志。"""
    from fastapi_app.core.redis_wrapper import note_command_failure
    note_command_failure(exc)


def _report_read_failure(exc: Exception) -> None:
    """读取路径专用：通知 + 按「异常类型 + 窗口」节流记日志。

    维护模式在**每个写请求**上被读取，日志必须节流；但 enter/exit 是低频的
    显式操作，各自单独记日志（措辞也不同），故不复用本函数。
    """
    global _last_failure_log

    _notify_failure(exc)

    now = time.monotonic()
    prev = _last_failure_log
    same_class_recently = (
        prev is not None and prev[0] is type(exc) and now - prev[1] < _FAILURE_LOG_INTERVAL
    )
    if not same_class_recently:
        _last_failure_log = (type(exc), now)
        logger.warning(
            '读取维护模式失败（同类 %d 秒内只记一次）: %s', int(_FAILURE_LOG_INTERVAL), exc,
        )


async def is_maintenance_mode() -> bool:
    """当前是否处于维护模式。Redis 不可用时读取兜底为 False（不阻塞业务）。

    ⚠️ 刻意**不**加本地缓存来"省掉这次读取"：维护模式是还原期间禁止写入的
    安全闸门，本地缓存会让它**延迟生效** —— 等于留下一个仍能写入的窗口。
    """
    try:
        client = await _get_client()
        if client is None:
            return False
        value = await client.get(_MAINTENANCE_KEY)
        _report_success()
        return bool(value)
    except Exception as e:  # broad-except: 维护状态探测不允许中断请求
        _report_read_failure(e)
        return False


async def enter_maintenance() -> bool:
    """开启维护模式（TTL 兜底自动清除，防止崩溃遗留）。"""
    try:
        client = await _get_client()
        if client is None:
            logger.warning('Redis 不可用，无法开启维护模式')
            return False
        await client.set(_MAINTENANCE_KEY, '1', ex=30 * 60)
        _report_success()
        return True
    except Exception as e:  # broad-except: 维护开关失败不抛出
        _notify_failure(e)
        logger.warning(f'开启维护模式失败: {e}')
        return False


async def exit_maintenance() -> None:
    """关闭维护模式。"""
    try:
        client = await _get_client()
        if client is not None:
            await client.delete(_MAINTENANCE_KEY)
            _report_success()
    except Exception as e:  # broad-except: 维护开关失败不抛出
        _notify_failure(e)
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
