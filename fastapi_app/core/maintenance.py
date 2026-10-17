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

**接线状态（2026-09-29 已修，H-1）**：`enter_maintenance()` / `exit_maintenance()`
此前在生产代码里没有任何调用方 —— 「还原期间禁止写入」只是文案。现已在
`services/backup/restore.py` 的还原锁三处接好：

* 取锁成功 → `enter_maintenance()`（fail-open：开不上只告警，能否还原由锁 fail-closed 决定）；
* **由持锁者**释放 → `exit_maintenance()`（非持锁者不得关，否则替并发中的还原开了门）；
* 锁续期成功 → `renew_maintenance()`（否则长还原超过 TTL 后闸门中途失效）。

同步路径与异步任务路径共用这三个函数，故单点接线即全覆盖。TTL 30 分钟仍作崩溃兜底。
"""
from __future__ import annotations

import logging
import time
from pathlib import Path

from starlette.datastructures import URL
from starlette.requests import Request
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)

_MAINTENANCE_TTL_SECONDS = 30 * 60

_MAINTENANCE_KEY = 'erp:maintenance_mode'
# 2026-10-17 审计 F-BE-CORE-09：Redis fail-open 的本地哨兵——还原流程 enter 时
# 落盘、exit 时删除；Redis 读不到时以文件为准（fail-safe），避免还原窗口被
# broker 抖动静默打穿。文件带 mtime 过期（2×TTL）防崩溃遗留。
_MAINTENANCE_SENTINEL = Path(__file__).resolve().parents[2] / 'logs' / 'maintenance_mode.sentinel'
_SENTINEL_MAX_AGE = _MAINTENANCE_TTL_SECONDS * 2

# 维护模式 TTL（兜底自动解除，防崩溃遗留）。2026-09-29（H-1）起由
# `renew_maintenance()` 随还原锁一起续期，长还原不会再中途失效。
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


def _sentinel_active() -> bool:
    """本地哨兵是否有效（存在且未过期）。读失败视为无效（与 Redis 路径同等宽容）。"""
    try:
        return _MAINTENANCE_SENTINEL.is_file() and \
            (time.time() - _MAINTENANCE_SENTINEL.stat().st_mtime) < _SENTINEL_MAX_AGE
    except OSError:
        return False


def _write_sentinel(on: bool) -> None:
    try:
        _MAINTENANCE_SENTINEL.parent.mkdir(parents=True, exist_ok=True)
        if on:
            _MAINTENANCE_SENTINEL.write_text(time.strftime('%Y-%m-%dT%H:%M:%S'), encoding='utf-8')
        else:
            _MAINTENANCE_SENTINEL.unlink(missing_ok=True)
    except OSError as e:
        logger.warning('维护模式哨兵文件写入失败（不影响 Redis 通道）: %s', e)


async def is_maintenance_mode() -> bool:
    """当前是否处于维护模式。

    Redis 正常时以 Redis 为准（TTL 兜底）；**Redis 读不到时改以本地哨兵为准**
    （F-BE-CORE-09：原先任何异常都返回 False——还原期间 broker 抖动会把写闸门
    静默打穿，写请求落在正在被替换的库上）。哨兵由 enter/exit 维护、mtime 过期
    （2×TTL）兜底防崩溃遗留。Redis 正常时哨兵不参与判定（避免双真相源漂移）。

    ⚠️ 刻意**不**加本地缓存来"省掉这次读取"：维护模式是还原期间禁止写入的
    安全闸门，本地缓存会让它**延迟生效** —— 等于留下一个仍能写入的窗口。
    """
    try:
        client = await _get_client()
        if client is None:
            return _sentinel_active()
        value = await client.get(_MAINTENANCE_KEY)
        _report_success()
        return bool(value)
    except Exception as e:  # broad-except: 维护状态探测不允许中断请求
        _report_read_failure(e)
        return _sentinel_active()


async def enter_maintenance() -> bool:
    """开启维护模式（TTL 兜底自动清除，防止崩溃遗留）。"""
    try:
        client = await _get_client()
        if client is None:
            logger.warning('Redis 不可用，无法开启维护模式')
            return False
        await client.set(_MAINTENANCE_KEY, '1', ex=_MAINTENANCE_TTL_SECONDS)
        _write_sentinel(True)
        _report_success()
        return True
    except Exception as e:  # broad-except: 维护开关失败不抛出
        _notify_failure(e)
        logger.warning(f'开启维护模式失败: {e}')
        return False


async def renew_maintenance() -> bool:
    """续期维护模式 TTL（H-1：还原长任务与还原锁同步续期）。

    没有它的话，还原超过 `_MAINTENANCE_TTL_SECONDS` 后闸门会中途失效 ——
    长还原正是最需要"禁止写入"的时候。仅当标志仍在时才续期，返回是否续期成功。
    """
    try:
        client = await _get_client()
        if client is None:
            return False
        if not await client.get(_MAINTENANCE_KEY):
            return False
        await client.expire(_MAINTENANCE_KEY, _MAINTENANCE_TTL_SECONDS)
        _report_success()
        return True
    except Exception as e:  # broad-except: 续期失败不抛出，由 TTL 兜底
        _notify_failure(e)
        logger.warning(f'续期维护模式失败: {e}')
        return False


async def exit_maintenance() -> None:
    """关闭维护模式。"""
    _write_sentinel(False)
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
