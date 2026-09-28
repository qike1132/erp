"""
健康检查端点模块

从 main.py 提取，包含：
- /api/health - 服务健康检查（10s 缓存）
- /api/health/db - 数据库详细状态
- /metrics - Prometheus 指标
"""

import json
import logging
import os
import time
from typing import Any

import redis.exceptions
from fastapi import Depends, FastAPI, Request, Response
from sqlalchemy import text
from sqlalchemy.exc import DisconnectionError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.config import settings
from fastapi_app.core.database import get_async_db, verify_db_connectivity
from fastapi_app.core.db_health import db_health_checker
from fastapi_app.core.deps import get_current_user_id

logger = logging.getLogger(__name__)

_health_cache: dict = {"public_data": None, "internal_data": None, "cached_at": 0.0, "ttl": 10}


def _get_cached_health() -> dict | None:
    if _health_cache["public_data"] is not None and (time.time() - _health_cache["cached_at"]) < _health_cache["ttl"]:
        return _health_cache["public_data"]
    return None


def _set_cached_health(public_data: dict, internal_data: dict) -> None:
    _health_cache["public_data"] = public_data
    _health_cache["internal_data"] = internal_data
    _health_cache["cached_at"] = time.time()


async def _get_optional_user(
    request: Request,
    db: AsyncSession = Depends(get_async_db),
) -> int | None:
    try:
        return await get_current_user_id(request, db)
    except Exception:  # defensive: optional user resolution, any auth failure returns None
        return None


async def _backup_signal() -> dict:
    """备份可观测性:产物新鲜度(权威) + ARQ 在线。

    ARQ 探测走**隔离短命连接**(1s 上限):既不碰绑定事件循环的全局池
    (会让 /api/health 在不同 loop 下复用已关闭连接),也不会因 broker 故障
    把响应拖过 prod_runner 的 5s 探测窗而引发误判重启。
    ``ok`` 是给消费方(服务器管理器徽章)的单一判据:新鲜且 ARQ 在线。
    """
    from fastapi_app.services.backup.freshness import backup_freshness

    fresh = backup_freshness()  # 绝不抛
    arq_ok = False
    try:
        from fastapi_app.core.arq_app import probe_worker_health_isolated

        arq_ok = await probe_worker_health_isolated(timeout=1.0)
    except Exception as exc:  # defensive: 健康端点不得因探测异常而失败
        logger.warning("ARQ 健康探测异常: %s", exc)
    return {
        "ok": bool(fresh["ok"]) and arq_ok,
        "age_hours": fresh["age_hours"],
        "arq_ok": arq_ok,
    }


def register_health_routes(app: FastAPI) -> None:
    """注册健康检查和监控路由"""

    @app.get("/api/health", tags=["健康检查"])
    async def health_check(user_id: int | None = Depends(_get_optional_user)):
        cached_public = _get_cached_health()
        if cached_public is not None:
            if user_id is None:
                if cached_public.get("status") == "unhealthy":
                    return Response(
                        content=json.dumps(cached_public, ensure_ascii=False),
                        status_code=503,
                        media_type="application/json",
                    )
                return cached_public

            health_data = dict(cached_public)
            health_data["version"] = settings.APP_VERSION
            health_data["checks"] = dict(_health_cache["internal_data"])
            try:
                pool_status = db_health_checker.get_pool_status()
                health_stats = db_health_checker.get_stats()
                health_data["checks"]["db_pool"] = pool_status
                health_data["checks"]["db_health_stats"] = health_stats
            except (OperationalError, DisconnectionError) as e:
                health_data["checks"]["db_pool"] = {"error": str(e)[:100]}

            if cached_public.get("status") == "unhealthy":
                return Response(
                    content=json.dumps(health_data, ensure_ascii=False),
                    status_code=503,
                    media_type="application/json",
                )
            return health_data

        health_data = {
            "status": "healthy",
            "app": settings.APP_NAME,
        }
        overall_healthy = await verify_db_connectivity()

        redis_ok = True
        try:
            from fastapi_app.core.redis_client import get_async_redis_client
            client = await get_async_redis_client()
            if client:
                try:
                    await client.ping()
                except (OSError, ConnectionError, redis.exceptions.RedisError):
                    redis_ok = False
            else:
                redis_ok = False
        except (OSError, ImportError, redis.exceptions.RedisError):
            redis_ok = False

        internal_checks = {
            "database": {"status": "ok"} if overall_healthy else {"status": "error"},
            "redis": {"status": "ok"} if redis_ok else {"status": "warning"},
        }
        health_data["backup"] = await _backup_signal()
        if not overall_healthy:
            health_data["status"] = "unhealthy"
        _set_cached_health(public_data=dict(health_data), internal_data=internal_checks)

        if user_id is not None:
            health_data["version"] = settings.APP_VERSION
            health_data["checks"] = dict(internal_checks)
            try:
                pool_status = db_health_checker.get_pool_status()
                health_stats = db_health_checker.get_stats()
                health_data["checks"]["db_pool"] = pool_status
                health_data["checks"]["db_health_stats"] = health_stats
            except (OperationalError, DisconnectionError) as e:
                health_data["checks"]["db_pool"] = {"error": str(e)[:100]}

        if not overall_healthy:
            health_data["status"] = "unhealthy"
            return Response(
                content=json.dumps(health_data, ensure_ascii=False),
                status_code=503,
                media_type="application/json",
            )

        return health_data

    @app.get("/api/health/db", tags=["健康检查"])
    async def db_health_detail(
        user_id: int = Depends(get_current_user_id),
        db: AsyncSession = Depends(get_async_db),
    ):
        result: dict[str, Any] = {
            "pool_status": db_health_checker.get_pool_status(),
            "health_stats": db_health_checker.get_stats(),
        }

        try:
            rows = await db.execute(text(
                "SELECT name, setting FROM pg_settings WHERE name IN "
                "('listen_addresses','max_connections','shared_buffers',"
                "'effective_cache_size','work_mem','maintenance_work_mem',"
                "'checkpoint_completion_target','wal_buffers')"
            ))
            db_vars = {row[0]: row[1] for row in rows.all()}

            rows2 = await db.execute(text(
                "SELECT state, COUNT(*) FROM pg_stat_activity GROUP BY state"
            ))
            # state 为 NULL 的是后台进程（checkpointer/walwriter 等），
            # NULL 不能直接当字典键（msgspec.json.encode 拒绝非字符串键），故显式命名
            db_status = {(row[0] or 'background'): str(row[1]) for row in rows2.all()}

            result["db_variables"] = db_vars
            result["db_status"] = db_status
        except (OperationalError, DisconnectionError) as e:
            result["db_error"] = str(e)[:200]

        return result

    try:
        from fastapi_app.core.metrics import get_content_type, get_metrics

        @app.get("/metrics", tags=["监控"])
        async def metrics(request: Request):
            # 生产环境要求 Bearer Token（fail-closed：未配置 token 即不暴露）
            from starlette.responses import JSONResponse

            from fastapi_app.core.config import settings as _settings
            if _settings.is_production:
                auth = request.headers.get('authorization', '')
                metrics_token = os.getenv('METRICS_BEARER_TOKEN', '')
                if not metrics_token:
                    # fail-closed：历史 fail-open 实测无鉴权 200，指标面直接暴露
                    return JSONResponse(status_code=503, content={'detail': '监控端点未启用（未配置 METRICS_BEARER_TOKEN）'})
                if not auth.startswith(f'Bearer {metrics_token}'):
                    return JSONResponse(status_code=401, content={'detail': '未授权访问'})
            return Response(content=get_metrics(), media_type=get_content_type())
    except (ImportError, AttributeError):
        pass  # defensive: 异常静默处理,不影响主流程

    @app.get("/api/health/live", tags=["健康检查"])
    async def liveness_probe():
        """K8s liveness probe - 无缓存，检测进程僵死

        失败时K8s重启容器。仅检查进程存活，不检查外部依赖。
        """
        return {"status": "alive"}

    @app.get("/api/health/ready", tags=["健康检查"])
    async def readiness_probe():
        """K8s readiness probe - 检查所有依赖就绪

        失败时K8s将Pod从Service摘除，不接收流量。
        无缓存，实时检查DB+Redis。
        """
        db_ok = await verify_db_connectivity()
        redis_ok = True
        try:
            from fastapi_app.core.redis_client import get_async_redis_client
            client = await get_async_redis_client()
            if client:
                await client.ping()
            else:
                redis_ok = False
        except (OSError, ConnectionError, ImportError, redis.exceptions.RedisError):
            redis_ok = False

        ready = db_ok and redis_ok
        result = {
            "status": "ready" if ready else "not_ready",
            "database": db_ok,
            "redis": redis_ok,
        }
        if not ready:
            return Response(
                content=json.dumps(result, ensure_ascii=False),
                status_code=503,
                media_type="application/json",
            )
        return result

    @app.get("/api/health/startup", tags=["健康检查"])
    async def startup_probe():
        """K8s startup probe - 应用初始化完成检查

        用于慢启动应用，startup成功前liveness/readiness不生效。
        """
        try:
            db_ok = await verify_db_connectivity()
            if db_ok:
                return {"status": "started"}
        except (OperationalError, DisconnectionError):
            pass  # defensive: 异常静默处理,不影响主流程
        return Response(
            content=json.dumps({"status": "starting"}, ensure_ascii=False),
            status_code=503,
            media_type="application/json",
        )

    @app.get("/api/health/arq", tags=["健康检查"])
    async def arq_health_probe():
        """ARQ worker 专用健康探针（严格：离线即 503）。供外部监控轮询。

        ⛔ 为什么单开一个端点，而不是把 ARQ 并进 /api/health（2026-09-17 审计 S3）
        -------------------------------------------------------------------------
        1. `/api/health` 被 `prod_runner.py:663` 当作**后端健康门**每 3s 轮询。
           若把 ARQ 状态并进去，ARQ 一旦掉线就会让 `/api/health` 变成不健康，
           ⇒ 把「ARQ 故障」**误标成「后端故障」**，把运维引向重启一个完全正常的服务
           （本仓库已有此类误判先例）。
        2. ARQ broker 不可达时探测最长耗时 `_HEALTH_PROBE_TIMEOUT=2s`；
           并入 `/api/health` 会拖慢 prod_runner 的健康轮询（其单次超时仅 5s）。

        ⇒ 因此本端点**只做增量暴露**，不改变任何既有端点的语义。

        ⚠️ 为什么要监控它：`erp-arq` 是**定时备份的唯一调度者**（`scheduler_poller`
        每 5 分钟扫 `backup_schedule`）。ARQ 静默停摆 = 数据保护静默失效，
        而在本端点存在之前，该故障**没有任何对外信号**（`/api/health` 依旧 healthy）。

        三态语义（复用仓内唯一判活契约 `core/arq_app.check_worker_health`，
        即 ARQ 官方哨兵键 `queue_name + ':health-check'`，端口在 broker 实例上）：

        | status          | HTTP | 含义                                    | 监控应做什么            |
        |-----------------|------|-----------------------------------------|-------------------------|
        | `running`       | 200  | 哨兵键存在且心跳新鲜                    | 正常                    |
        | `not_running`   | 503  | 键不存在 ⇒ worker 确实不在线            | 拉起 `erp-arq`          |
        | `probe_unknown` | 503  | **探测自身**失败（连不上 broker/超时）  | 查 broker，**勿**判定 ARQ 已死 |

        ⚠️ `probe_unknown` 与 `not_running` 必须区分：文案与语义都不同，
        否则会把运维引向「重启一个正常的 worker」而忽略真正出问题的 broker。
        """
        from fastapi_app.core.arq_app import check_worker_health

        try:
            is_healthy, message = await check_worker_health()
        except Exception as exc:  # broad-except: 健康探测自身不得抛出，任何异常都须转成"未知"态
            logger.warning('ARQ 健康端点探测自身异常: %s', exc)
            return Response(
                content=json.dumps(
                    {"status": "probe_unknown",
                     "message": f"ARQ 健康探测自身异常: {type(exc).__name__}"},
                    ensure_ascii=False,
                ),
                status_code=503,
                media_type="application/json",
            )

        if is_healthy:
            return {"status": "running", "message": message}

        # check_worker_health 用**文案**区分「未运行」与「探测失败」（它只返回 bool），
        # 故此处按文案分流。若将来该契约改为结构化返回，应同步替换此处判断。
        state = "not_running" if "未运行" in message else "probe_unknown"
        return Response(
            content=json.dumps({"status": state, "message": message}, ensure_ascii=False),
            status_code=503,
            media_type="application/json",
        )
