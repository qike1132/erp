"""
审计日志中间件

拦截所有写操作（POST/PUT/PATCH/DELETE），自动记录到 audit_log 表。
通过 Redis 缓冲队列实现异步批量写入，避免增加请求延迟。
"""
import json
import time
import uuid
from datetime import datetime

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from fastapi_app.core.logger import logger

WRITE_METHODS = {'POST', 'PUT', 'PATCH', 'DELETE'}

RESOURCE_MAP = {
    '/api/v1/orders': 'order',
    '/api/v1/products': 'product',
    '/api/v1/stock': 'stock_in',
    '/api/v1/stock-out': 'stock_out',
    '/api/v1/customers': 'customer',
    '/api/v1/suppliers': 'supplier',
    '/api/v1/users': 'user',
    '/api/v1/permissions': 'permission',
    '/api/v1/approvals': 'approval',
    '/api/v1/backup': 'backup',
    '/api/v1/batch': 'order_batch',
    '/api/v1/cases': 'case',
    '/api/v1/material': 'material_registration',
    '/api/v1/purchase-orders': 'purchase_order',
    '/api/v1/purchase-plan': 'purchase_plan',
    '/api/v1/production-plan': 'production_plan',
    '/api/v1/production': 'production',
    '/api/v1/daily-production': 'daily_production',
    '/api/v1/auth': 'auth',
    '/api/v1/purchase-center': 'purchase_center',
    '/api/v1/dead-letter': 'dead_letter',
}

METHOD_ACTION_MAP = {
    'POST': 'CREATE',
    'PUT': 'UPDATE',
    'PATCH': 'UPDATE',
    'DELETE': 'DELETE',
}

AUDIT_BUFFER_KEY = 'audit_log_buffer'
AUDIT_FLUSH_SIZE = 50
AUDIT_FLUSH_INTERVAL = 5


def _resolve_resource_type(path: str) -> str:
    for prefix, resource in RESOURCE_MAP.items():
        if path.startswith(prefix):
            return resource
    parts = path.strip('/').split('/')
    if len(parts) >= 3:
        return parts[2]
    return 'unknown'


def _extract_resource_id(path: str) -> str | None:
    parts = path.strip('/').split('/')
    for i, part in enumerate(parts):
        if i > 0 and parts[i - 1] in RESOURCE_MAP or (i >= 3 and i == len(parts) - 1):
            try:
                int(part)
                return part
            except ValueError:
                pass
    return None


class AuditLogMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = str(uuid.uuid4())[:8]

        if request.method not in WRITE_METHODS:
            request.state.request_id = request_id
            return await call_next(request)

        request.state.request_id = request_id

        start_time = time.time()
        response: Response = await call_next(request)
        duration_ms = round((time.time() - start_time) * 1000, 2)

        try:
            await self._record_audit(request, response, request_id, duration_ms)
        except Exception as e:
            logger.warning('审计日志记录失败: %s', e)

        return response

    async def _record_audit(self, request: Request, response: Response, request_id: str, duration_ms: float):
        user_id = getattr(request.state, 'user_id', None)
        username = getattr(request.state, 'username', None)

        if user_id is None:
            try:
                from fastapi_app.core.deps import _resolve_user_id
                user_id = _resolve_user_id(request)
            except Exception:
                pass

        action = METHOD_ACTION_MAP.get(request.method, request.method)
        resource_type = _resolve_resource_type(request.scope['path'])
        resource_id = _extract_resource_id(request.scope['path'])

        client_ip = request.client.host if request.client else None
        if forwarded := request.headers.get('x-forwarded-for'):
            client_ip = forwarded.split(',')[0].strip()

        user_agent = request.headers.get('user-agent', '')[:500]

        detail_data = {
            'method': request.method,
            'path': request.scope['path'],
            'status_code': response.status_code,
            'duration_ms': duration_ms,
        }

        audit_entry = {
            'user_id': user_id,
            'username': username,
            'action': action,
            'resource_type': resource_type,
            'resource_id': resource_id,
            'detail': json.dumps(detail_data, ensure_ascii=False) if detail_data else None,
            'ip_address': client_ip,
            'user_agent': user_agent,
            'request_id': request_id,
            'status_code': response.status_code,
            'created_at': datetime.now().isoformat(),
        }

        await _buffer_audit_entry(audit_entry)


async def _buffer_audit_entry(entry: dict):
    try:
        from utils.redis_cache import redis_cache
        if redis_cache.redis_client:
            await redis_cache.redis_client.rpush(AUDIT_BUFFER_KEY, json.dumps(entry, ensure_ascii=False))
            buf_len = await redis_cache.redis_client.llen(AUDIT_BUFFER_KEY)
            if buf_len >= AUDIT_FLUSH_SIZE:
                await flush_audit_buffer()
        else:
            await _write_audit_direct([entry])
    except Exception:
        await _write_audit_direct([entry])


async def flush_audit_buffer():
    try:
        from utils.redis_cache import redis_cache
        if not redis_cache.redis_client:
            return
        entries_raw = await redis_cache.redis_client.lrange(AUDIT_BUFFER_KEY, 0, AUDIT_FLUSH_SIZE - 1)
        if not entries_raw:
            return
        await redis_cache.redis_client.ltrim(AUDIT_BUFFER_KEY, len(entries_raw), -1)
        entries = [json.loads(e) for e in entries_raw]
        await _write_audit_direct(entries)
    except Exception as e:
        logger.warning('审计日志缓冲刷写失败: %s', e)


async def _write_audit_direct(entries: list[dict]):
    if not entries:
        return
    try:
        from fastapi_app.core.database import async_engine
        from sqlalchemy import text as sa_text
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

        if async_engine is None:
            return

        session_factory = async_sessionmaker(bind=async_engine, class_=AsyncSession, expire_on_commit=False)
        async with session_factory() as session:
            for entry in entries:
                await session.execute(sa_text("""
                    INSERT INTO audit_log (user_id, username, action, resource_type, resource_id,
                                          detail, ip_address, user_agent, request_id, status_code, created_at)
                    VALUES (:user_id, :username, :action, :resource_type, :resource_id,
                            :detail, :ip_address, :user_agent, :request_id, :status_code, :created_at)
                """), entry)
            await session.commit()
        logger.debug('审计日志写入 %d 条', len(entries))
    except Exception as e:
        logger.warning('审计日志直接写入失败: %s', e)


async def _audit_flush_loop():
    import asyncio
    while True:
        await asyncio.sleep(AUDIT_FLUSH_INTERVAL)
        try:
            await flush_audit_buffer()
        except Exception as e:
            logger.error('审计日志定时刷写异常: %s', e, exc_info=True)
