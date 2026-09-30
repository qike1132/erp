"""授权拒绝（403）审计事件测试

覆盖两层：
1. record_access_denied 构造的事件字段与 detail 结构（含 x-forwarded-for 取值、
   user-agent 截断、匿名用户、request_id 兜底、审计失败不冒泡）；
2. 三个权限依赖工厂在拒绝分支确实产生该事件，且放行分支不产生。

背景：AuditLogMiddleware 只审计写方法（POST/PUT/PATCH/DELETE），读端点（GET）的
越权尝试不会被中间件捕获，故由权限依赖显式记录（见 core/deps.py）。
"""
import json
from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from starlette.requests import Request
from starlette.responses import Response

from fastapi_app.core import audit_middleware as am
from fastapi_app.core.deps import (
    require_any_permission,
    require_permission,
    require_superuser,
)
from fastapi_app.shared_models import Permission, User


def _make_request(
    path: str = '/api/v1/customers/active-names',
    method: str = 'GET',
    request_id: str | None = 'rid-1',
    headers: list[tuple[bytes, bytes]] | None = None,
    client_host: str = '10.0.0.9',
    user_agent: str = 'pytest-agent',
) -> Request:
    """构造最小可用 Request；request_id 传 None 表示不在 state 上设置（验证兜底）"""
    raw_headers = [(b'user-agent', user_agent.encode())]
    if headers:
        raw_headers.extend(headers)
    request = Request({
        'type': 'http',
        'method': method,
        'path': path,
        'query_string': b'',
        'headers': raw_headers,
        'client': (client_host, 1234),
        'server': ('test', 80),
        'scheme': 'http',
    })
    if request_id is not None:
        request.state.request_id = request_id
    return request


def _make_user(codes: list[str], *, is_super: bool = False) -> User:
    """构造仅持有指定权限码的普通用户"""
    user = User(id=7, username='u7', password='x', is_super=is_super, status=True)
    user.permissions = [Permission(name=c, code=c) for c in codes]
    return user


class _CaptureBuffer:
    """替换 _buffer_audit_entry，捕获事件字典"""

    def __init__(self):
        self.entries: list[dict] = []

    async def __call__(self, entry: dict) -> None:
        self.entries.append(entry)

    @property
    def entry(self) -> dict:
        assert len(self.entries) == 1, f'应恰好产生 1 条审计事件，实际 {len(self.entries)}'
        return self.entries[0]


class TestRecordAccessDenied:
    """record_access_denied 的事件构造"""

    @pytest.mark.asyncio
    async def test_entry_fields_and_detail(self):
        capture = _CaptureBuffer()
        with patch.object(am, '_buffer_audit_entry', capture):
            await am.record_access_denied(
                _make_request(), _make_user(['order_manage', 'report_manage']),
                required_permissions=('customer_manage',),
                reason='missing_any_permission',
            )

        entry = capture.entry
        assert entry['action'] == am.ACCESS_DENIED_ACTION
        assert entry['user_id'] == 7
        assert entry['username'] == 'u7'
        assert entry['resource_type'] == 'customer'
        assert entry['resource_id'] is None
        assert entry['status_code'] == 403
        assert entry['request_id'] == 'rid-1'
        assert entry['user_agent'] == 'pytest-agent'
        assert isinstance(entry['created_at'], datetime)

        detail = json.loads(entry['detail'])
        assert detail['method'] == 'GET'
        assert detail['path'] == '/api/v1/customers/active-names'
        assert detail['required_permissions'] == ['customer_manage']
        assert detail['held_permissions'] == ['order_manage', 'report_manage']
        assert detail['reason'] == 'missing_any_permission'

    @pytest.mark.asyncio
    async def test_resource_id_extracted_from_path(self):
        """路径带数字 ID 时应提取出 resource_id"""
        capture = _CaptureBuffer()
        with patch.object(am, '_buffer_audit_entry', capture):
            await am.record_access_denied(
                _make_request(path='/api/v1/users/permission/4242'), _make_user([]),
                required_permissions=('user_manage',), reason='missing_permission',
            )

        assert capture.entry['resource_type'] == 'user'
        assert capture.entry['resource_id'] == '4242'

    @pytest.mark.asyncio
    async def test_forwarded_for_takes_last_hop(self):
        """x-forwarded-for 取最后一个 IP，避免客户端伪造首个 IP"""
        capture = _CaptureBuffer()
        with patch.object(am, '_buffer_audit_entry', capture):
            await am.record_access_denied(
                _make_request(
                    headers=[(b'x-forwarded-for', b'1.2.3.4, 8.8.8.8')],
                    client_host='10.0.0.9',
                ),
                _make_user([]),
                required_permissions=('customer_manage',), reason='missing_permission',
            )

        assert capture.entry['ip_address'] == '8.8.8.8'

    @pytest.mark.asyncio
    async def test_falls_back_to_client_host_without_forwarded_header(self):
        capture = _CaptureBuffer()
        with patch.object(am, '_buffer_audit_entry', capture):
            await am.record_access_denied(
                _make_request(client_host='192.168.1.50'), _make_user([]),
                required_permissions=('customer_manage',), reason='missing_permission',
            )

        assert capture.entry['ip_address'] == '192.168.1.50'

    @pytest.mark.asyncio
    async def test_user_agent_truncated_to_500(self):
        capture = _CaptureBuffer()
        with patch.object(am, '_buffer_audit_entry', capture):
            await am.record_access_denied(
                _make_request(user_agent='A' * 900), _make_user([]),
                required_permissions=('customer_manage',), reason='missing_permission',
            )

        assert len(capture.entry['user_agent']) == 500

    @pytest.mark.asyncio
    async def test_request_id_falls_back_when_state_missing(self):
        capture = _CaptureBuffer()
        with patch.object(am, '_buffer_audit_entry', capture):
            await am.record_access_denied(
                _make_request(request_id=None), _make_user([]),
                required_permissions=('customer_manage',), reason='missing_permission',
            )

        fallback_id = capture.entry['request_id']
        assert isinstance(fallback_id, str) and len(fallback_id) == 8

    @pytest.mark.asyncio
    async def test_anonymous_user_records_nulls(self):
        """未解析出用户时不得报错，用户字段落空值"""
        capture = _CaptureBuffer()
        with patch.object(am, '_buffer_audit_entry', capture):
            await am.record_access_denied(
                _make_request(), None,
                required_permissions=('customer_manage',), reason='missing_permission',
            )

        entry = capture.entry
        assert entry['user_id'] is None
        assert entry['username'] is None
        assert json.loads(entry['detail'])['held_permissions'] == []

    @pytest.mark.asyncio
    async def test_buffer_failure_does_not_propagate(self):
        """审计写入失败不得影响鉴权结果（调用方仍返回 403）"""
        with patch.object(
            am, '_buffer_audit_entry', AsyncMock(side_effect=RuntimeError('redis down')),
        ):
            await am.record_access_denied(
                _make_request(), _make_user([]),
                required_permissions=('customer_manage',), reason='missing_permission',
            )


class TestPermissionFactoriesEmitAudit:
    """三个权限依赖工厂的拒绝/放行分支"""

    @pytest.mark.asyncio
    async def test_require_permission_denied_emits(self):
        checker = require_permission('customer_manage')
        with patch('fastapi_app.core.deps.record_access_denied', AsyncMock()) as mock_audit:
            with pytest.raises(HTTPException) as exc:
                await checker(_make_request(), _make_user(['order_manage']))

        assert exc.value.status_code == 403
        mock_audit.assert_awaited_once()
        assert mock_audit.call_args.kwargs['reason'] == 'missing_permission'
        assert mock_audit.call_args.kwargs['required_permissions'] == ('customer_manage',)

    @pytest.mark.asyncio
    async def test_require_any_permission_denied_emits(self):
        checker = require_any_permission('customer_manage', 'order_manage')
        with patch('fastapi_app.core.deps.record_access_denied', AsyncMock()) as mock_audit:
            with pytest.raises(HTTPException) as exc:
                await checker(_make_request(), _make_user(['supplier_manage']))

        assert exc.value.status_code == 403
        mock_audit.assert_awaited_once()
        assert mock_audit.call_args.kwargs['reason'] == 'missing_any_permission'
        assert mock_audit.call_args.kwargs['required_permissions'] == (
            'customer_manage', 'order_manage',
        )

    @pytest.mark.asyncio
    async def test_require_superuser_not_super_emits(self):
        """非超管即使持有所需业务权限，仍被拒且留下审计"""
        checker = require_superuser('order_manage')
        with patch('fastapi_app.core.deps.record_access_denied', AsyncMock()) as mock_audit:
            with pytest.raises(HTTPException) as exc:
                await checker(_make_request(), _make_user(['order_manage'], is_super=False))

        assert exc.value.status_code == 403
        assert exc.value.detail == '仅超级用户可访问'
        mock_audit.assert_awaited_once()
        assert mock_audit.call_args.kwargs['reason'] == 'not_superuser'

    @pytest.mark.asyncio
    async def test_require_permission_allowed_does_not_emit(self):
        """放行分支不得产生审计事件"""
        checker = require_permission('customer_manage')
        user = _make_user(['customer_manage'])
        with patch('fastapi_app.core.deps.record_access_denied', AsyncMock()) as mock_audit:
            returned = await checker(_make_request(), user)

        assert returned is user
        mock_audit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_require_any_permission_allowed_does_not_emit(self):
        checker = require_any_permission('customer_manage', 'order_manage')
        user = _make_user(['order_manage'])
        with patch('fastapi_app.core.deps.record_access_denied', AsyncMock()) as mock_audit:
            returned = await checker(_make_request(), user)

        assert returned is user
        mock_audit.assert_not_awaited()


class TestUnattributedDenialBackstop:
    """中间件对「未被依赖工厂归因」的 403 的兜底审计。

    依赖工厂之外的 403（业务层直接抛 HTTPException(403) / AppError 体系
    PermissionDeniedError 逃逸）也必须留下审计记录。
    """

    @pytest.mark.asyncio
    async def test_backstop_records_when_not_attributed(self):
        capture = _CaptureBuffer()
        with patch.object(am, '_buffer_audit_entry', capture):
            await am._audit_unattributed_denial(_make_request(), Response(status_code=403))

        assert capture.entry['action'] == am.ACCESS_DENIED_ACTION
        assert capture.entry['status_code'] == 403
        assert json.loads(capture.entry['detail'])['reason'] == 'unattributed_denial'

    @pytest.mark.asyncio
    async def test_backstop_skips_when_already_attributed(self):
        """依赖工厂已记账时必须跳过，避免同一次 403 记两条"""
        capture = _CaptureBuffer()
        request = _make_request()
        request.state.access_denied_audited = True

        with patch.object(am, '_buffer_audit_entry', capture):
            await am._audit_unattributed_denial(request, Response(status_code=403))

        assert capture.entries == []

    @pytest.mark.asyncio
    async def test_backstop_skips_non_403(self):
        capture = _CaptureBuffer()
        with patch.object(am, '_buffer_audit_entry', capture):
            await am._audit_unattributed_denial(_make_request(), Response(status_code=200))

        assert capture.entries == []

    @pytest.mark.asyncio
    async def test_backstop_resolves_user_id_from_request(self):
        """兜底路径没有 User 对象，应从请求解析当事人"""
        capture = _CaptureBuffer()
        with patch.object(am, '_buffer_audit_entry', capture), patch(
            'fastapi_app.core.deps._resolve_user_id', return_value=99,
        ):
            await am._audit_unattributed_denial(_make_request(), Response(status_code=403))

        assert capture.entry['user_id'] == 99
        assert capture.entry['username'] is None

    @pytest.mark.asyncio
    async def test_dependency_denial_recorded_exactly_once(self, client):
        """端到端：依赖工厂拒绝 + 中间件兜底不得重复记账

        端点选 /ocr-import/progress/{task_id}（require_any_permission 保护、GET、
        依赖先于任何 DB 访问）。原用 /customers/active-names，但该端点后来放宽为
        「仅要求登录」，无权限用户不再 403，已不适用。
        """
        from fastapi_app.core.deps import _get_user_with_permissions
        from fastapi_app.main import app

        async def _override():
            return _make_user([])

        app.dependency_overrides[_get_user_with_permissions] = _override
        capture = _CaptureBuffer()
        with patch.object(am, '_buffer_audit_entry', capture):
            response = await client.get('/api/v1/ocr-import/progress/test-task')

        assert response.status_code == 403
        assert len(capture.entries) == 1, f'应恰好 1 条审计，实际 {len(capture.entries)}'
        assert json.loads(capture.entries[0]['detail'])['reason'] == 'missing_any_permission'

    @pytest.mark.asyncio
    async def test_dispatch_fires_backstop_on_read_403(self):
        """接线验证：dispatch 的读方法分支确实调用兜底（否则兜底形同虚设）"""
        from fastapi_app.core.audit_middleware import AuditLogMiddleware

        middleware = AuditLogMiddleware(app=None)
        capture = _CaptureBuffer()
        with patch.object(am, '_buffer_audit_entry', capture):
            response = await middleware.dispatch(
                _make_request(), AsyncMock(return_value=Response(status_code=403)),
            )

        assert response.status_code == 403
        assert len(capture.entries) == 1
        assert json.loads(capture.entries[0]['detail'])['reason'] == 'unattributed_denial'

    @pytest.mark.asyncio
    async def test_dispatch_write_403_uses_write_audit_not_backstop(self):
        """写方法的 403 由写审计覆盖，不重复走兜底"""
        from fastapi_app.core.audit_middleware import AuditLogMiddleware

        middleware = AuditLogMiddleware(app=None)
        capture = _CaptureBuffer()
        with patch.object(am, '_buffer_audit_entry', capture):
            await middleware.dispatch(
                _make_request(method='POST'), AsyncMock(return_value=Response(status_code=403)),
            )

        assert len(capture.entries) == 1
        assert capture.entries[0]['action'] == 'CREATE'
        assert capture.entries[0]['status_code'] == 403
