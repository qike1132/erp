"""
FastAPI 应用主入口 - 全异步模式

中间件 → core/middleware.py
健康检查 → core/health.py
WebSocket → api/ws.py
"""

# 1. 标准库
import asyncio
import os
import pathlib
from contextlib import asynccontextmanager, suppress
from typing import cast

# 2. 第三方库
import msgspec
import uvicorn
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from sqlalchemy.pool import QueuePool
from starlette.exceptions import HTTPException as StarletteHTTPException

# 3. 项目内部
from fastapi_app.api.v1.router import api_router
from fastapi_app.api.ws import register_websocket
from fastapi_app.core.config import settings
from fastapi_app.core.database import async_engine, dispose_async_engines
from fastapi_app.core.db_health import db_health_checker
from fastapi_app.core.exceptions import AppError, current_iso_timestamp, new_request_id
from fastapi_app.core.health import register_health_routes
from fastapi_app.core.limiter import default_limits, limiter
from fastapi_app.core.logger import logger, setup_logging
from fastapi_app.core.middleware import setup_middleware


class MsgspecResponse(JSONResponse):
    """使用 msgspec 高性能 JSON 编码器替代 orjson"""

    def render(self, content: object) -> bytes:
        return msgspec.json.encode(content)


_sentry_dsn = os.getenv("SENTRY_DSN")
if _sentry_dsn:
    try:
        import sentry_sdk
        sentry_sdk.init(
            dsn=_sentry_dsn,
            traces_sample_rate=float(os.getenv("SENTRY_TRACES_RATE", "0.1")),
            profiles_sample_rate=float(os.getenv("SENTRY_PROFILES_RATE", "0.1")),
            environment=os.getenv("APP_ENV", "development"),
            release=f"binfa-erp@{settings.APP_VERSION}",
            enable_tracing=True,
        )
    except (ValueError, ImportError):
        pass  # defensive: 异常静默处理,不影响主流程


async def _setup_database():
    """数据库连接验证与连接池预热"""
    if async_engine is None:
        return
    from fastapi_app.core.database import verify_db_connectivity
    if not await verify_db_connectivity():
        logger.error("异步数据库连接验证失败")
        raise RuntimeError("异步数据库引擎无法连接数据库")
    # 运行时连接池恒为 AsyncAdaptedQueuePool（QueuePool 子类）；engine.execute 的类型声明只给出基类 Pool，故在此收窄
    pool = cast(QueuePool, async_engine.pool)
    warmup_count = min(5, pool.size())
    from sqlalchemy import text as warmup_text
    for _ in range(warmup_count):
        async with async_engine.connect() as warmup_conn:
            await warmup_conn.execute(warmup_text('SELECT 1'))
    logger.info("异步数据库连接验证成功，连接池预热完成 (%d 个连接)", warmup_count)


async def _setup_redis_caches():
    """Redis 预热与缓存初始化"""
    from fastapi_app.services.notification_service import _warmup_async_redis
    try:
        await _warmup_async_redis()
    except (RuntimeError, OSError, ValueError) as e:
        logger.warning("异步 Redis 客户端预热失败: %s", e)

    # 与 ARQ worker 共用同一初始化（2026-10-11：worker 此前从不初始化 redis_cache，
    # 死信队列写不进、worker 侧 Redis 缓存全部静默降级）
    from fastapi_app.core.redis_wrapper import init_redis_cache_manager
    await init_redis_cache_manager()

    from fastapi_app.core.nav_context import invalidate_nav_cache
    try:
        await invalidate_nav_cache()
    except (OSError, ValueError) as e:
        logger.warning("导航缓存清除失败: %s", e)


# 库存缓存保热（见 _warm_inventory_cache）：启动延迟给连接池留就绪时间；间隔必须
# 显著小于 inventory:paginated 的 L2 TTL(120s)，否则会出现「缓存刚过期、刷新还没
# 跑」的空窗。两个值都是模块常量，便于测试改写。
_INVENTORY_WARMUP_STARTUP_DELAY_SECONDS = 2
_INVENTORY_WARMUP_INTERVAL_SECONDS = 60


async def _warm_inventory_cache():
    """启动预热 + 周期性保热库存缓存（/stock 默认键）。

    预热解决「重启后首次进入 /stock 冷缓存」；周期保热让该键常驻 L1/L2 ——
    命中缓存只读 Redis、不碰 PG，把 /stock 热路径从「主机/DB 争用时可能卡数秒」
    里摘出来。依据（2026-10-13 独立评审）：这条 CTE 本身只要 0.24ms，日志里
    4.99s 的尖刺是主机争用（同刻 products/list 卡到 15s），不是查询复杂度。

    每个 worker 进程各跑一份（lifespan 每进程执行），故各进程自己的 L1 也被刷新。
    失败只记日志、绝不抛出：保热是优化，不该影响服务。
    """
    await asyncio.sleep(_INVENTORY_WARMUP_STARTUP_DELAY_SECONDS)  # 等待数据库连接池就绪
    from fastapi_app.core.database import get_async_db_context
    from fastapi_app.services.stock_service import get_inventory_paginated

    warmed = False
    while True:
        try:
            async with get_async_db_context() as db:
                # per_page 必须与前端 /stock 默认每页条数一致（缓存键含 per_page），
                # 由 fastapi_app/tests/test_inventory_warmup_key_alignment.py 守住。
                await get_inventory_paginated(db, page=1, per_page=20)
            if not warmed:
                # 只报一次成功：否则每 60s × N 个 worker 会把日志刷满
                logger.info("库存缓存预热完成")
                warmed = True
        except asyncio.CancelledError:
            raise  # 关停：交给 background_tasks 的 cancel+gather 回收
        except Exception as e:  # defensive: 保热失败不得影响服务
            logger.warning("库存缓存保热失败: %s", e)
        await asyncio.sleep(_INVENTORY_WARMUP_INTERVAL_SECONDS)


async def _perform_shutdown(background_tasks: list[asyncio.Task]) -> None:
    # B2 评审（2026-10-11）：六步收尾此前无逐项隔离，任一步抛异常会跳过
    # dispose_async_engines 与全部 redis 收尾；且真实异常只被 except
    # TimeoutError 漏接（wait_for 只在超时抛 TimeoutError，协程自身异常
    # 原样传播）→ 静默无日志。现逐步 try/except + 首尾哨兵，保证收尾
    # 全部执行、且被硬杀时也能从日志判定走到哪一步。
    logger.info("shutdown_step_begin pid=%s", os.getpid())

    # 先刷写审计日志缓冲区，防止关闭时丢失数据
    try:
        from fastapi_app.core.audit_middleware import flush_audit_buffer
        await flush_audit_buffer()
    except Exception as e:  # defensive: shutdown audit flush failure must not block graceful shutdown
        logger.warning("审计缓冲区刷写失败: %s", e)

    async def _step(name, coro_fn):
        try:
            await coro_fn()
        except Exception as e:  # defensive: 单步失败不阻塞其余关停步骤
            logger.warning("关停步骤 %s 失败: %s", name, e, exc_info=True)

    # P1-10 短期兜底：异步恢复任务跑在 API 进程内（asyncio.create_task），停机时先取消
    # 并等待其写失败终态 + 释放还原锁；必须在 redis/引擎关闭之前执行。
    async def _cancel_restore_tasks():
        from fastapi_app.api.v1.endpoints.backup._deps import cancel_background_restore_tasks
        cancelled = await cancel_background_restore_tasks(timeout=10.0)
        if cancelled:
            logger.warning("停机：已取消 %d 个在跑的异步恢复任务", cancelled)

    await _step("cancel_restore_tasks", _cancel_restore_tasks)

    # 再取消后台任务
    for task in background_tasks:
        task.cancel()
    await asyncio.gather(*background_tasks, return_exceptions=True)

    logger.info(f"{settings.APP_NAME} 正在关闭...")
    from fastapi_app.core.auth.blacklist import stop_revocation_listener
    from fastapi_app.core.cache import stop_l1_broadcast_listener
    from fastapi_app.core.purchase_cache import stop_purchase_cache_listener
    from fastapi_app.core.redis_client import close_async_redis_client
    from fastapi_app.core.telemetry import shutdown_telemetry
    from fastapi_app.services.notification_service import _get_async_redis_client, manager
    from utils.redis_cache import redis_cache

    await _step("stop_redis_listener", manager.stop_redis_listener)
    await _step("stop_purchase_cache_listener", stop_purchase_cache_listener)
    await _step("stop_l1_broadcast_listener", stop_l1_broadcast_listener)
    await _step("stop_revocation_listener", stop_revocation_listener)
    await _step("db_health_checker_stop", db_health_checker.stop)
    try:
        shutdown_telemetry()  # sync 函数（telemetry.py:147），不可 await
    except Exception as e:  # defensive: 单步失败不阻塞其余关停步骤
        logger.warning("关停步骤 shutdown_telemetry 失败: %s", e, exc_info=True)
    await _step("dispose_async_engines", dispose_async_engines)

    async def _close_notification_redis():
        _notif_redis = await _get_async_redis_client()
        if _notif_redis:
            with suppress(OSError, RuntimeError):
                await _notif_redis.aclose()

    await _step("close_notification_redis", _close_notification_redis)

    async def _close_redis_cache():
        with suppress(OSError, RuntimeError):
            await redis_cache.close()

    await _step("close_redis_cache", _close_redis_cache)
    await _step("close_async_redis_client", close_async_redis_client)

    logger.info("数据库连接池已关闭")
    logger.info("shutdown_step_end pid=%s", os.getpid())


@asynccontextmanager
async def lifespan(application: FastAPI):
    setup_logging()
    logger.info(f"{settings.APP_NAME} v{settings.APP_VERSION} 启动中...")

    # P0-5 / B2：上一次还原是否在「DROP 之后、导入完成之前」中断。
    # 有标记（或标记不可读）= 数据库可能是空壳：启动照常进行（否则再无受控恢复
    # 入口），但业务 readiness 会保持失败，直到运维按标记指引回滚并清除。
    # 必须放在 _setup_database() **之前**：空壳库上建连/初始化可能先抛异常，
    # 那时这条 CRITICAL 就永远打不出来（检查只读文件，不依赖数据库）。
    try:
        from fastapi_app.services.backup.restore_guard import check_interrupted_restore
        check_interrupted_restore()
    except Exception as e:  # defensive: 标记检查失败不得阻断启动
        # 检查自身异常 = 恢复状态未知，按 ERROR 记录（readiness 另有独立判定）
        logger.error('恢复中断标记检查失败，数据库状态未知: %s', e)

    await _setup_database()

    # 编号水位对账（spec 2026-09-29 §5）：GREATEST 只升不降，幂等，失败不阻断启动
    try:
        from fastapi_app.core.database import require_async_session_local
        from fastapi_app.services.numbering_reconcile import reconcile_numbering_counters
        async with require_async_session_local()() as recon_db:
            result = await reconcile_numbering_counters(recon_db)
            await recon_db.commit()  # reconcile 不自行提交；事务边界归调用方
        if result['raised'] or result['inserted']:
            logger.info('编号水位对账: 抬升 %d 行, 补插 %d 行', result['raised'], result['inserted'])
    except Exception as e:  # defensive: 对账失败不得阻断应用启动
        # 记 ERROR（而非 warning）：失败即意味着同键碰撞窗口仍然敞开，必须可见。
        # 仍不 raise —— 对账失败是"降级"，不该让应用起不来。
        logger.error('编号水位启动对账失败（不影响启动）: %s', e, exc_info=True)

    await db_health_checker.start()

    from fastapi_app.core.telemetry import setup_telemetry
    setup_telemetry(application)

    await _setup_redis_caches()

    from fastapi_app.services.notification_service import _register_domain_event_subscriptions, manager
    await manager.start_redis_listener()
    # 领域事件订阅注册（原为 notification_service 模块导入期副作用，批次1 迁移至此显式执行）
    _register_domain_event_subscriptions()

    # L1（2026-10-31 评审）：权限缓存跨 worker 失效。USER_PERMISSION_CHANGED 事件
    # 此前已定义但全链路无生产者/消费者——invalidate_user_permission_cache 只清当前
    # worker，其余 worker 的 L1 最长 TTL 5s 不一致。现 user.py 权限相关端点在
    # post-commit 发布事件，本订阅让每个 worker 消费后失效本进程缓存（发布 worker
    # 已在 publish() 的进程内派发中失效）。事件链路失败时退化为旧行为（TTL 兜底）。
    from fastapi_app.core.deps import register_permission_event_subscriber
    register_permission_event_subscriber()

    # 跨 worker 领域事件监听器（评审 2026-10-10 P0-2）：此前全仓无人调用
    # start_event_listener，多 worker 下非发起 worker 收不到 domain_events
    # 频道事件 → 进程内订阅者（缓存失效/WebSocket 转发）失效。后台任务，
    # 自带重连；关停由下方 background_tasks 的 cancel+gather 统一回收。

    # L1 缓存跨 worker 失效广播（开关默认关，由 CACHE_L1_BROADCAST_ENABLED 启用）
    from fastapi_app.core.cache import (
        resolve_worker_count,
        start_l1_broadcast_listener,
        warn_if_l1_broadcast_disabled,
    )
    await start_l1_broadcast_listener()
    warn_if_l1_broadcast_disabled(resolve_worker_count())

    # 生产限流必须走 Redis：memory:// 回退会让每个 worker 各自计数
    from fastapi_app.core.limiter import assert_production_limiter_storage
    assert_production_limiter_storage()

    # 2026-10-17 审计 F-BE-CORE-08：采购中心跨进程失效监听器原先只有关停钩子、
    # 从未启动（erp:cache_invalidation 频道有发布方无消费方）。与 L1 广播并列启动，
    # 自带重连；关停由下方 stop_purchase_cache_listener 统一回收。
    from fastapi_app.core.purchase_cache import start_purchase_cache_listener
    await start_purchase_cache_listener()

    # token 撤销跨 worker 广播（M9）：登出 jti 只写本进程 LRU 时，其他 worker
    # 在 Redis 故障期会放行已登出 token；监听器让各 worker 同步撤销集合。
    from fastapi_app.core.auth.blacklist import start_revocation_listener
    await start_revocation_listener()

    # 启动时同步备份记录与文件系统（P1+P2：补录缺失/清理孤立/修正僵尸状态）
    try:
        from fastapi_app.services.backup.records import sync_backup_records
        sync_result = await sync_backup_records()
        # N1 评审（2026-10-11）：errors 计数此前无人消费，同步失败时零信号。
        if sync_result.get('errors'):
            logger.error(
                '备份记录同步出现 %d 个错误（详情见 records.py 日志）: %s',
                len(sync_result['errors']), sync_result['errors'][:5],
            )
        if sync_result.get('backfilled', 0) > 0 or sync_result.get('orphaned', 0) > 0 or sync_result.get('errors'):
            logger.info(
                '备份记录同步完成: 补录 %d 条, 清理孤立 %d 条, 修正僵尸 %d 条',
                sync_result['backfilled'], sync_result['orphaned'], sync_result.get('zombie_fixed', 0),
            )
    except Exception as e:  # defensive: 启动容错——备份记录同步失败不得阻断应用启动
        logger.warning('启动时备份记录同步失败（不影响启动）: %s', e)

    # 库存缓存预热 + 周期保热（后台执行，不阻塞启动）
    background_tasks = []
    task = asyncio.create_task(_warm_inventory_cache())
    background_tasks.append(task)

    # 跨 worker 领域事件监听器（评审 2026-10-10 P0-2）：此前全仓无人调用
    # start_event_listener，多 worker 下非发起 worker 收不到 domain_events
    # 频道事件 → 进程内订阅者（缓存失效/WebSocket 转发）失效。后台任务，
    # 自带重连；关停由下方 background_tasks 的 cancel+gather 统一回收。
    from fastapi_app.core.domain_events import start_event_listener
    task = asyncio.create_task(start_event_listener())
    background_tasks.append(task)

    from fastapi_app.core.audit_middleware import _audit_flush_loop
    task = asyncio.create_task(_audit_flush_loop())
    background_tasks.append(task)

    # 2026-10-15：warmup_cache 自根 utils/redis_cache.py 迁入 core/cache_warmup.py
    # （原实现内 import fastapi_app.* 与 fastapi_app→utils 构成包级循环，见其模块 docstring）
    from fastapi_app.core.cache_warmup import warmup_cache
    task = asyncio.create_task(warmup_cache())
    background_tasks.append(task)

    yield

    # 关闭超时保护：防止某步骤 hang 导致整个关闭阻塞
    try:
        await asyncio.wait_for(_perform_shutdown(background_tasks), timeout=15.0)
    except TimeoutError:
        logger.error("优雅关闭超时（15s），强制退出")
    except Exception as e:  # defensive: 关停兜底记录，不再让异常静默逃逸
        # wait_for 会把协程自身异常原样传播（非 TimeoutError），必须显式记录
        logger.error("优雅关闭异常退出: %s", e, exc_info=True)


def resolve_docs_urls(is_production: bool):
    """DOCS/OpenAPI URL 的唯一求值入口（在 app 创建期调用）。"""
    if is_production:
        return None, None, None
    return '/api/docs', '/api/redoc', '/api/openapi.json'


_docs_url, _redoc_url, _openapi_url = resolve_docs_urls(settings.is_production)

app = FastAPI(
    title=settings.APP_NAME,
    description="滨发协同系统 - API服务",
    version=settings.APP_VERSION,
    docs_url=_docs_url,
    redoc_url=_redoc_url,
    openapi_url=_openapi_url,
    default_response_class=MsgspecResponse,
    lifespan=lifespan,
)

# limiter 单例由 fastapi_app.core.limiter 提供（避免循环导入）；限流键 rate_limit_key 在该模块
# 构造 Limiter 时就已定死（P0-6(d)：slowapi 在装饰时绑定 key_func，事后覆盖 limiter.key_func
# 对已装饰路由无效，原覆盖写法只是静默地什么都改不到）。
app.state.limiter = limiter


@app.exception_handler(RateLimitExceeded)
async def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded):
    request_id = getattr(request.state, 'request_id', None) or new_request_id()
    return MsgspecResponse(
        content={
            "success": False,
            "detail": "请求过于频繁，请稍后再试",
            "status_code": 429,
            "code": "RATE_LIMIT_EXCEEDED",
            "request_id": request_id,
            "timestamp": current_iso_timestamp(),
        },
        status_code=429,
        headers={"Retry-After": "60"},
    )


# P0-6(e)：SlowAPIMiddleware 只对「未装饰」路由生效（slowapi/middleware.py:110-111 对已装饰路由直接放行），
# 且它依赖 limiter.default_limits —— 未配置 RATE_LIMIT_DEFAULT 时为空，注册后纯粹是每请求一层空转开销。
# 故只在确实配置了全局默认限流时才注册（当前 .env 无该键 ⇒ 等价于删除；配置后自动生效）。
if default_limits:
    app.add_middleware(SlowAPIMiddleware)

# 维护模式（M3）：还原执行期间拒绝非备份域写请求
from starlette.middleware.base import BaseHTTPMiddleware

from fastapi_app.core.maintenance import maintenance_middleware

app.add_middleware(BaseHTTPMiddleware, dispatch=maintenance_middleware)


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError):
    request_id = getattr(request.state, 'request_id', None) or new_request_id()
    logger.warning(
        "业务异常: code=%s status=%d request_id=%s path=%s msg=%s",
        exc.code, exc.status_code, request_id, request.url.path, exc.message,
    )
    return MsgspecResponse(
        content={
            "success": False,
            "detail": exc.message,
            "code": exc.code,
            "status_code": exc.status_code,
            "request_id": request_id,
            "timestamp": current_iso_timestamp(),
        },
        status_code=exc.status_code,
    )


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    if 300 <= exc.status_code < 400 and exc.headers and "location" in {k.lower(): v for k, v in exc.headers.items()}:
        location = {k.lower(): v for k, v in exc.headers.items()}["location"]
        return RedirectResponse(url=location, status_code=exc.status_code)
    request_id = getattr(request.state, 'request_id', None) or new_request_id()
    logger.warning(
        "HTTP异常: status=%d request_id=%s path=%s detail=%s",
        exc.status_code, request_id, request.url.path, exc.detail,
    )
    return MsgspecResponse(
        content={
            "success": False,
            "detail": exc.detail,
            "status_code": exc.status_code,
            "request_id": request_id,
            "timestamp": current_iso_timestamp(),
        },
        status_code=exc.status_code,
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    if settings.is_production:
        detail = "请求参数验证失败"
    else:
        detail = f"请求参数验证失败: {exc.errors()}"
    request_id = getattr(request.state, 'request_id', None) or new_request_id()
    return MsgspecResponse(
        content={
            "success": False,
            "detail": detail,
            "status_code": 422,
            "code": "VALIDATION_ERROR",
            "request_id": request_id,
            "timestamp": current_iso_timestamp(),
        },
        status_code=422,
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    request_id = getattr(request.state, 'request_id', None) or new_request_id()
    logger.error(
        "未处理异常: request_id=%s type=%s path=%s",
        request_id, type(exc).__name__, request.url.path, exc_info=exc,
    )
    return MsgspecResponse(
        content={
            "success": False,
            "detail": "服务器内部错误，请稍后重试",
            "status_code": 500,
            "code": "INTERNAL_ERROR",
            "request_id": request_id,
            "timestamp": current_iso_timestamp(),
        },
        status_code=500,
    )


setup_middleware(app)

from fastapi_app.core.audit_middleware import AuditLogMiddleware

app.add_middleware(AuditLogMiddleware)

register_health_routes(app)
register_websocket(app)

app.include_router(api_router, prefix=settings.API_PREFIX)

_static_dir = pathlib.Path(__file__).resolve().parent.parent / "static"

# 确保 static 子目录存在并挂载，避免因目录未预创建导致静态文件 404
# static/ 不存在时创建并挂载 uploads/releases/files
if not _static_dir.is_dir():
    _static_dir.mkdir(parents=True, exist_ok=True)

_uploads_dir = _static_dir / "uploads"
_uploads_dir.mkdir(parents=True, exist_ok=True)
app.mount("/static/uploads", StaticFiles(directory=str(_uploads_dir)), name="static-uploads")

_files_dir = _static_dir / "files"
_files_dir.mkdir(parents=True, exist_ok=True)
app.mount("/static/files", StaticFiles(directory=str(_files_dir)), name="static-files")

_releases_dir = _static_dir / "releases"
_releases_dir.mkdir(parents=True, exist_ok=True)
app.mount("/static/releases", StaticFiles(directory=str(_releases_dir)), name="static-releases")


@app.get("/", tags=["根路径"])
async def root():
    return {
        "message": f"欢迎使用 {settings.APP_NAME}",
        "version": settings.APP_VERSION,
        "docs": app.docs_url,
    }


if __name__ == "__main__":
    # 生产环境默认绑定 127.0.0.1（仅本机回环），开发环境绑定 :: （所有接口）
    # 可通过 FASTAPI_HOST 环境变量显式覆盖
    # M3 修复：原 == "prod" 漏判 start.py 设置的 "production"，改用统一的 settings.is_production
    _host = os.getenv(
        "FASTAPI_HOST",
        "127.0.0.1" if settings.is_production else "::",
    )
    uvicorn.run(
        "fastapi_app.main:app",
        host=_host,  # nosec B104
        port=5002,
        reload=settings.FASTAPI_DEBUG,
    )
