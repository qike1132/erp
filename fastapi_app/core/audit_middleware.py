"""
审计日志中间件

拦截所有写操作（POST/PUT/PATCH/DELETE），自动记录到 audit_log 表。
通过 Redis 缓冲队列实现异步批量写入，避免增加请求延迟。
"""
import json
import time
import uuid
from datetime import UTC, datetime

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

# 授权拒绝（403）的审计动作名，用于与业务写操作的 CREATE/UPDATE/DELETE 区分
ACCESS_DENIED_ACTION = 'ACCESS_DENIED'

_audit_session_factory = None


def _get_audit_session_factory():
    """懒创建并复用 audit session factory，避免每次刷写都新建"""
    global _audit_session_factory
    if _audit_session_factory is None:
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

        from fastapi_app.core.database import async_engine
        if async_engine is not None:
            _audit_session_factory = async_sessionmaker(
                bind=async_engine, class_=AsyncSession, expire_on_commit=False,
            )
    return _audit_session_factory


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
        if (i > 0 and parts[i - 1] in RESOURCE_MAP) or (i >= 3 and i == len(parts) - 1):
            try:
                int(part)
                return part
            except ValueError:
                pass  # defensive: 可选 ValueError 静默处理,不影响主流程
    return None


class AuditLogMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = getattr(request.state, 'request_id', None) or str(uuid.uuid4())[:8]
        request.state.request_id = request_id

        if request.method not in WRITE_METHODS:
            response = await call_next(request)
            # 读方法不走写审计，403 需在此补漏，否则越权尝试不留痕迹
            await _audit_unattributed_denial(request, response)
            return response

        start_time = time.time()
        response: Response = await call_next(request)
        duration_ms = round((time.time() - start_time) * 1000, 2)

        try:
            await self._record_audit(request, response, request_id, duration_ms)
        except Exception as e:  # defensive: 审计记录失败不能影响主请求
            logger.warning('审计日志记录失败: %s', e)

        return response

    async def _record_audit(self, request: Request, response: Response, request_id: str, duration_ms: float):
        user_id = getattr(request.state, 'user_id', None)
        username = getattr(request.state, 'username', None)

        if user_id is None:
            try:
                from fastapi_app.core.deps import _resolve_user_id
                user_id = _resolve_user_id(request)
            except Exception:  # defensive: 用户 ID 解析失败不影响审计记录  # noqa: S110  # nosec B110
                pass  # defensive: 异常静默处理,不影响主流程

        action = METHOD_ACTION_MAP.get(request.method, request.method)
        resource_type = _resolve_resource_type(request.scope['path'])
        resource_id = _extract_resource_id(request.scope['path'])

        client_ip = request.client.host if request.client else None
        if forwarded := request.headers.get('x-forwarded-for'):
            # 取最后一个 IP（最接近服务器的可信代理追加的），
            # 避免客户端伪造 x-forwarded-for 头注入任意 IP（取第一个 IP 会被伪造）
            client_ip = forwarded.split(',')[-1].strip()

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
            'created_at': datetime.now(UTC),
        }

        await _buffer_audit_entry(audit_entry)


def _resolve_actor(request: Request, user: object | None) -> tuple[int | None, str | None, list[str]]:
    """解析拒绝事件的当事人：(user_id, username, 持有的权限码)。

    调用方持有 User 对象时直接取字段；兜底路径（中间件发现未被归因的 403）没有
    User 对象，退化为从请求解析 user_id —— 取法与 AuditLogMiddleware._record_audit 一致。
    """
    if user is not None:
        perms = getattr(user, 'permissions', None) or []
        held = [p.code for p in perms if getattr(p, 'code', None)]
        return getattr(user, 'id', None), getattr(user, 'username', None), held
    try:
        from fastapi_app.core.deps import _resolve_user_id
        return _resolve_user_id(request), None, []
    except Exception:  # defensive: 用户解析失败不影响审计记录
        return None, None, []


async def record_access_denied(
    request: Request,
    user: object | None,
    *,
    required_permissions: tuple[str, ...],
    reason: str,
) -> None:
    """记录一次授权拒绝（403）审计事件。

    与 AuditLogMiddleware 共用同一套缓冲/落库管线。本函数自带异常兜底，
    审计失败不影响鉴权结果（调用方仍正常返回 403）。

    为什么不能只靠中间件：AuditLogMiddleware 只审计写方法（POST/PUT/PATCH/DELETE），
    读端点（GET）的越权尝试不会被捕获，故在权限依赖的拒绝分支显式记录。
    """
    try:
        request_id = getattr(request.state, 'request_id', None) or str(uuid.uuid4())[:8]
        path = request.scope.get('path', '')

        client_ip = request.client.host if request.client else None
        if forwarded := request.headers.get('x-forwarded-for'):
            # 取最后一个 IP（最接近服务器的可信代理追加的），避免客户端伪造
            client_ip = forwarded.split(',')[-1].strip()

        user_id, username, held_permissions = _resolve_actor(request, user)

        detail_data = {
            'method': request.method,
            'path': path,
            'required_permissions': list(required_permissions),
            'held_permissions': held_permissions,
            'reason': reason,
        }

        entry = {
            'user_id': user_id,
            'username': username,
            'action': ACCESS_DENIED_ACTION,
            'resource_type': _resolve_resource_type(path),
            'resource_id': _extract_resource_id(path),
            'detail': json.dumps(detail_data, ensure_ascii=False),
            'ip_address': client_ip,
            'user_agent': request.headers.get('user-agent', '')[:500],
            'request_id': request_id,
            'status_code': 403,
            'created_at': datetime.now(UTC),
        }

        # 置位去重标记：本次 403 已有语义化审计，中间件兜底不得重复写入
        request.state.access_denied_audited = True
        await _buffer_audit_entry(entry)
    except Exception as e:  # defensive: 审计记录失败不能影响主请求
        logger.warning('授权拒绝审计记录失败: %s', e)


async def _audit_unattributed_denial(request: Request, response: Response) -> None:
    """读端点 403 的兜底审计。

    权限依赖（core/deps.py）已在拒绝分支写入带「所需/持有权限码」的事件并置位
    request.state.access_denied_audited；此处只补漏 —— 覆盖不经过依赖工厂的 403
    （业务层直接抛 HTTPException(403)，或 AppError 体系的 PermissionDeniedError 逃逸）。

    写方法的 403 不在此处理：AuditLogMiddleware.dispatch 的写审计已记录 status_code=403。
    """
    if response.status_code != 403:
        return
    if getattr(request.state, 'access_denied_audited', False):
        return
    await record_access_denied(
        request, None,
        required_permissions=(), reason='unattributed_denial',
    )


async def _buffer_audit_entry(entry: dict):
    try:
        from fastapi_app.core.redis_wrapper import safe_llen, safe_rpush
        pushed = await safe_rpush(AUDIT_BUFFER_KEY, json.dumps(entry, ensure_ascii=False), context="审计缓冲")
        if pushed > 0:
            buf_len = await safe_llen(AUDIT_BUFFER_KEY, context="审计缓冲")
            if buf_len >= AUDIT_FLUSH_SIZE:
                await flush_audit_buffer()
        else:
            await _write_audit_direct([entry])
    except Exception:  # defensive: Redis 缓冲失败时降级为直接写入
        await _write_audit_direct([entry])


async def flush_audit_buffer():
    try:
        from fastapi_app.core.redis_wrapper import safe_lrange, safe_ltrim
        entries_raw = await safe_lrange(AUDIT_BUFFER_KEY, 0, AUDIT_FLUSH_SIZE - 1, context="审计缓冲")
        if not entries_raw:
            return
        await safe_ltrim(AUDIT_BUFFER_KEY, len(entries_raw), -1, context="审计缓冲")
        entries = [json.loads(e) for e in entries_raw]
        await _write_audit_direct(entries)
    except Exception as e:  # defensive: 缓冲刷写失败记录日志，不中断请求
        logger.warning('审计日志缓冲刷写失败: %s', e)


async def _write_audit_direct(entries: list[dict]):
    if not entries:
        return
    try:
        from sqlalchemy import text as sa_text

        session_factory = _get_audit_session_factory()
        if session_factory is None:
            return

        async with session_factory() as session:
            for entry in entries:
                # 兜底：无论来自 Redis 缓冲（JSON 反序列化会丢 datetime 类型）还是直接路径，
                # 都保证 created_at 是 datetime 实例，asyncpg 不接受 timestamp 列的字符串
                if not isinstance(entry.get('created_at'), datetime):
                    entry['created_at'] = datetime.now(UTC)
                await session.execute(sa_text("""
                    INSERT INTO audit_log (user_id, username, action, resource_type, resource_id,
                                          detail, ip_address, user_agent, request_id, status_code, created_at)
                    VALUES (:user_id, :username, :action, :resource_type, :resource_id,
                            :detail, :ip_address, :user_agent, :request_id, :status_code, :created_at)
                """), entry)
            await session.commit()
        logger.debug('审计日志写入 %d 条', len(entries))
    except Exception as e:  # defensive: 审计日志写入失败不能影响主请求
        logger.warning('审计日志直接写入失败: %s', e)


async def _audit_flush_loop():
    import asyncio
    while True:
        await asyncio.sleep(AUDIT_FLUSH_INTERVAL)
        try:
            await flush_audit_buffer()
        except Exception as e:  # defensive: 后台定时任务不能因单次异常退出
            logger.error('审计日志定时刷写异常: %s', e, exc_info=True)
