"""
健康检查端点模块

从 main.py 提取，包含：
- /api/health - 服务健康检查（10s 缓存）
- /api/health/db - 数据库详细状态
- /metrics - Prometheus 指标
"""

import json
import logging
import time

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
            from fastapi_app.services.notification_service import _get_async_redis_client
            client = await _get_async_redis_client()
            if client:
                try:
                    await client.ping()
                except (OSError, ConnectionError):
                    redis_ok = False
            else:
                redis_ok = False
        except (OSError, ImportError):
            redis_ok = False

        internal_checks = {
            "database": {"status": "ok"} if overall_healthy else {"status": "error"},
            "redis": {"status": "ok"} if redis_ok else {"status": "warning"},
        }
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
        result = {
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
            db_status = {row[0]: str(row[1]) for row in rows2.all()}

            result["db_variables"] = db_vars
            result["db_status"] = db_status
        except (OperationalError, DisconnectionError) as e:
            result["db_error"] = str(e)[:200]

        return result

    try:
        from fastapi_app.core.metrics import get_content_type, get_metrics

        @app.get("/metrics", tags=["监控"])
        async def metrics(request: Request):
            # 生产环境要求 Bearer Token 或内网 IP 访问
            import os as _os
            if _os.getenv('APP_ENV') == 'production':
                auth = request.headers.get('authorization', '')
                metrics_token = _os.getenv('METRICS_BEARER_TOKEN', '')
                if metrics_token and not auth.startswith(f'Bearer {metrics_token}'):
                    from starlette.responses import JSONResponse
                    return JSONResponse(status_code=401, content={'detail': '未授权访问'})
            return Response(content=get_metrics(), media_type=get_content_type())
    except (ImportError, AttributeError):
        pass

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
            from fastapi_app.services.notification_service import _get_async_redis_client
            client = await _get_async_redis_client()
            if client:
                await client.ping()
            else:
                redis_ok = False
        except (OSError, ConnectionError, ImportError):
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
            pass
        return Response(
            content=json.dumps({"status": "starting"}, ensure_ascii=False),
            status_code=503,
            media_type="application/json",
        )
