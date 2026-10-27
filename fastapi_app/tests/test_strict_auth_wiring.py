"""敏感路由与业务写操作的 fail-closed token 撤销校验。

策略：
- ``/backup``、``/users``、``/permissions``：所有方法严格 fail-closed；
- 其余业务路由：POST/PUT/PATCH/DELETE fail-closed，GET/HEAD/OPTIONS 在
  Redis 撤销存储不可用时保留只读可用性。

Redis 客户端已具备 ``ensure_client()`` 自愈，因此不会出现「启动时没连上就
永久 401」的旧锁死问题。
"""

from __future__ import annotations

import ast
import contextlib
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from fastapi_app.core.auth.token import create_access_token
from fastapi_app.core.deps import (
    get_current_user_id_strict,
    get_current_user_id_write_strict,
)
from fastapi_app.main import app

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ROUTER = PROJECT_ROOT / 'fastapi_app' / 'api' / 'v1' / 'router.py'

STRICT_PREFIXES = ('/backup', '/users', '/permissions')
WRITE_STRICT_PREFIXES = ('/stock', '/orders', '/products')


def _include_router_auth_map() -> dict[str, str | None]:
    """用 AST 解析 include_router，忽略注释中的伪 prefix/dependencies。"""
    tree = ast.parse(ROUTER.read_text(encoding='utf-8'))
    result: dict[str, str | None] = {}
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == 'include_router'
        ):
            continue
        kwargs = {kw.arg: kw.value for kw in node.keywords if kw.arg}
        if 'prefix' not in kwargs:
            continue
        prefix = ast.literal_eval(kwargs['prefix'])
        dep: str | None = None
        deps = kwargs.get('dependencies')
        if deps is not None:
            assert isinstance(deps, ast.List), f'{prefix}: dependencies 必须是列表'
            assert len(deps.elts) == 1, f'{prefix}: 只允许一个统一认证依赖'
            call = deps.elts[0]
            assert (
                isinstance(call, ast.Call)
                and isinstance(call.func, ast.Name)
                and call.func.id == 'Depends'
                and len(call.args) == 1
                and isinstance(call.args[0], ast.Name)
            ), f'{prefix}: dependencies 结构无法识别'
            dep = call.args[0].id
        assert prefix not in result, f'重复的 include 前缀: {prefix}'
        result[prefix] = dep
    return result


def _dependency_for(prefix: str) -> str | None:
    return _include_router_auth_map()[prefix]


_EXPECTED_PREFIXES = {
    '/purchase-center', '/batch', '/staging-orders', '/staging-stockins',
    '/staging-stockouts', '/products', '/orders', '/outsource', '/order-batch',
    '/stock', '/stock-returns', '/users', '/customers', '/suppliers', '/approvals',
    '/reports', '/cases', '/material-registrations', '/aux', '/tasks', '/auth',
    '/ocr-import', '/production-plans', '/plans', '/daily-production',
    '/production-summary', '/dashboard', '/permissions', '/backup', '/monitoring',
    '/dead-letter', '/pattern-room', '/pattern-maker', '/notifications',
    '/numbering-audit', '/finished-stock',
}
_PUBLIC_PREFIXES = {'/auth', '/monitoring'}


@pytest.mark.parametrize('prefix', STRICT_PREFIXES)
def test_sensitive_routes_use_full_fail_closed_dependency(prefix: str) -> None:
    assert _dependency_for(prefix) == 'get_current_user_id_strict'


@pytest.mark.parametrize('prefix', WRITE_STRICT_PREFIXES)
def test_business_routes_use_method_aware_dependency(prefix: str) -> None:
    assert _dependency_for(prefix) == 'get_current_user_id_write_strict'


def test_every_prefix_has_exact_auth_policy() -> None:
    """前缀集合与鉴权策略都必须精确；AST 保证注释掉依赖/整段都会判红。"""
    actual = _include_router_auth_map()
    assert set(actual) == _EXPECTED_PREFIXES, {
        'missing': sorted(_EXPECTED_PREFIXES - set(actual)),
        'unexpected': sorted(set(actual) - _EXPECTED_PREFIXES),
    }

    expected: dict[str, str | None] = {}
    for prefix in actual:
        if prefix in _PUBLIC_PREFIXES:
            expected[prefix] = None
        elif prefix in STRICT_PREFIXES:
            expected[prefix] = 'get_current_user_id_strict'
        else:
            expected[prefix] = 'get_current_user_id_write_strict'
    assert actual == expected, {
        'wrong': {k: (actual[k], expected[k]) for k in actual if actual[k] != expected[k]}
    }


def _bearer_token() -> str:
    return create_access_token({'sub': '1', 'username': 'admin'})


async def test_backup_returns_401_when_revocation_store_unavailable(client) -> None:
    app.dependency_overrides.pop(get_current_user_id_strict, None)
    with patch('fastapi_app.core.redis_wrapper.get_client', return_value=None):
        resp = await client.get(
            '/api/v1/backup/ping',
            headers={'Authorization': f'Bearer {_bearer_token()}'},
        )
    assert resp.status_code == 401


async def test_users_reads_fail_closed_when_revocation_store_unavailable(client) -> None:
    """用户管理可导致提权，连 GET 也不能接受不可判定的撤销状态。"""
    app.dependency_overrides.pop(get_current_user_id_strict, None)
    with patch('fastapi_app.core.redis_wrapper.get_client', return_value=None):
        resp = await client.get(
            '/api/v1/users/list',
            headers={'Authorization': f'Bearer {_bearer_token()}'},
        )
    assert resp.status_code == 401


@pytest.mark.parametrize(
    ('path', 'payload'),
    [
        ('/api/v1/orders/create', {'product_id': 1, 'quantity': 1, 'customer': '测试客户'}),
        ('/api/v1/stock/in/create', {'product_id': 1, 'quantity': 1}),
    ],
)
async def test_business_write_fails_closed_when_revocation_store_unavailable(
    client, path: str, payload: dict,
) -> None:
    """Redis 故障时不得用已撤销 token 写订单或库存。"""
    seen: list[bool] = []

    async def spy(jti, *, fail_closed: bool = False):
        seen.append(fail_closed)
        if fail_closed:
            raise HTTPException(status_code=401, detail='令牌状态校验不可用，请重新登录')
        return False

    app.dependency_overrides.pop(get_current_user_id_write_strict, None)
    with patch('fastapi_app.core.deps.is_token_revoked', spy), patch(
        'fastapi_app.core.redis_wrapper.get_client', return_value=None
    ):
        resp = await client.post(
            path,
            json=payload,
            headers={'Authorization': f'Bearer {_bearer_token()}'},
        )

    assert seen == [True]
    assert resp.status_code == 401


async def test_business_read_remains_available_when_revocation_store_unavailable(client) -> None:
    """安全读方法保留可用性；只要求传给撤销检查的是 fail_open=False。"""
    seen: list[bool] = []

    async def spy(jti, *, fail_closed: bool = False):
        seen.append(fail_closed)
        return False

    app.dependency_overrides.pop(get_current_user_id_write_strict, None)
    with patch('fastapi_app.core.deps.is_token_revoked', spy), patch(
        'fastapi_app.core.redis_wrapper.get_client', return_value=None
    ), contextlib.suppress(Exception):
        await client.get(
            '/api/v1/orders/list',
            headers={'Authorization': f'Bearer {_bearer_token()}'},
        )

    assert seen
    assert all(value is False for value in seen)
