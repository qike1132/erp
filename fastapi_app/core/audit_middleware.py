"""
审计日志中间件

拦截所有写操作（POST/PUT/PATCH/DELETE），自动记录到 audit_log 表。

写入路径（P1-9：审计写库不落在请求热路径上逐条往返）：
1. 请求级收集：一个请求产生的全部审计事件（写审计 + 403 拒绝审计）先入
   request.state.audit_pending_entries，请求结束时一次性投递；
2. 首选异步：批量投递到 Redis 缓冲队列，由后台任务/关停钩子批量落库；
3. 降级直写：Redis 不可用时按批直写 —— 整批合并为**单条多行 INSERT**，
   一次 session.execute + 一次 commit；失败只记日志，绝不影响主请求响应。
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

# audit_log 落库列顺序（批量 INSERT 的单一来源，与 audit_log 表结构一致）
AUDIT_LOG_COLUMNS = (
    'user_id', 'username', 'action', 'resource_type', 'resource_id',
    'detail', 'ip_address', 'user_agent', 'request_id', 'status_code', 'created_at',
)

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
        # P1-9：请求级审计收集桶 —— 本请求内产生的所有审计事件先入桶，
        # 请求结束时一次性批量投递，直写降级路径的写库次数恒为 1（与事件数无关）。
        request.state.audit_pending_entries = []

        try:
            if request.method not in WRITE_METHODS:
                response = await call_next(request)
                # 读方法不走写审计，403 需在此补漏，否则越权尝试不留痕迹
                await _audit_unattributed_denial(request, response)
                return response

            start_time = time.time()
            response = await call_next(request)
            duration_ms = round((time.time() - start_time) * 1000, 2)

            try:
                await self._record_audit(request, response, request_id, duration_ms)
            except Exception as e:  # defensive: 审计记录失败不能影响主请求
                logger.warning('审计日志记录失败: %s', e)

            return response
        finally:
            try:
                await _flush_request_audit_entries(request)
            except Exception as e:  # defensive: 审计批量投递失败不能影响主请求响应
                logger.warning('审计日志批量投递失败: %s', e)

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

        await _submit_audit_entry(request, audit_entry)


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
        await _submit_audit_entry(request, entry)
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


async def _submit_audit_entry(request: Request, entry: dict) -> None:
    """提交一条审计事件。

    请求级收集桶存在（请求经 AuditLogMiddleware.dispatch）时只入桶，由请求结束时
    的 _flush_request_audit_entries 统一批量投递；否则立即走单条管线 ——
    无中间件上下文的直接调用方（如 backup/export.py）语义不变。
    """
    pending = getattr(request.state, 'audit_pending_entries', None)
    if pending is None:
        await _buffer_audit_entry(entry)
    else:
        pending.append(entry)


async def _flush_request_audit_entries(request: Request) -> None:
    """请求结束时一次性投递收集桶内的全部审计事件（P1-9：每请求至多一次直写）。"""
    pending = getattr(request.state, 'audit_pending_entries', None)
    if not pending:
        return
    request.state.audit_pending_entries = []
    if len(pending) == 1:
        # 单条与既有单条管线完全等价（同样只有一次写库）
        await _buffer_audit_entry(pending[0])
    else:
        await _buffer_audit_entries(pending)


async def _buffer_audit_entries(entries: list[dict]):
    """把一批审计事件投递到 Redis 缓冲队列；缓冲不可用时整批一次性直写。"""
    if not entries:
        return
    try:
        from fastapi_app.core.redis_wrapper import safe_llen, safe_rpush
        pushed = 0
        for entry in entries:
            # default=str：created_at 是 datetime，不兜底会 TypeError —— 原实现因此
            # 每轮都跌进 except 直写，Redis 缓冲路径实际从未生效（P1-9 顺带修复）
            pushed += await safe_rpush(
                AUDIT_BUFFER_KEY,
                json.dumps(entry, ensure_ascii=False, default=str),
                context="审计缓冲",
            )
        if pushed > 0:
            buf_len = await safe_llen(AUDIT_BUFFER_KEY, context="审计缓冲")
            if buf_len >= AUDIT_FLUSH_SIZE:
                await flush_audit_buffer()
        else:
            await _write_audit_direct(entries)
    except Exception:  # defensive: Redis 缓冲失败时降级为按批直接写入
        await _write_audit_direct(entries)


async def _buffer_audit_entry(entry: dict):
    """单条投递入口（对外兼容 API：backup/export.py 等直接调用方共用同一管线）"""
    await _buffer_audit_entries([entry])


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


def _build_batch_insert(entries: list[dict]) -> tuple[str, dict]:
    """构造单条多行 INSERT 及其绑定参数（P1-9：整批一次 execute，不再逐条往返）。

    绑定参数上限 65535（Postgres），本批最多 AUDIT_FLUSH_SIZE(50) 行 / 11 列，
    远低于上限，无需分片。
    """
    rows = []
    params: dict = {}
    for index, entry in enumerate(entries):
        placeholders = []
        for column in AUDIT_LOG_COLUMNS:
            key = f'{column}_{index}'
            params[key] = entry.get(column)
            placeholders.append(f':{key}')
        rows.append('(' + ', '.join(placeholders) + ')')
    sql = (
        'INSERT INTO audit_log (' + ', '.join(AUDIT_LOG_COLUMNS) + ') VALUES '
        + ', '.join(rows)
    )
    return sql, params


async def _write_audit_direct(entries: list[dict]):
    if not entries:
        return
    try:
        from sqlalchemy import text as sa_text

        session_factory = _get_audit_session_factory()
        if session_factory is None:
            return

        for entry in entries:
            # 兜底：无论来自 Redis 缓冲（JSON 反序列化丢掉 datetime 类型）还是直接路径，
            # 都保证 created_at 是 datetime 实例，asyncpg 不接受 timestamp 列的字符串；
            # 缓冲来的 ISO 字符串优先还原原时间戳，避免审计时间被刷写时刻覆盖
            created_at = entry.get('created_at')
            if not isinstance(created_at, datetime):
                if created_at:
                    try:
                        entry['created_at'] = datetime.fromisoformat(str(created_at))
                        continue
                    except (TypeError, ValueError):  # defensive: 时间戳不可解析时用当前时间兜底
                        pass
                entry['created_at'] = datetime.now(UTC)

        sql, params = _build_batch_insert(entries)
        async with session_factory() as session:
            # 单次 execute 写入整批（原实现循环内逐条 execute，N 条 = N 次往返）
            await session.execute(sa_text(sql), params)
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
