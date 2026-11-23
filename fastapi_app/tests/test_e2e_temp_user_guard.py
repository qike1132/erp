"""E2E 造临时用户的 skip 边界回归（2026-10-30 审计 A-M46；2026-11-23 收紧）。

历史：原实现 `_create_temp_user` 对任何非 2xx（含 500）都返回 None，调用方随即
`pytest.skip`——于是「登录返回 user=null」这条**唯一** E2E 守卫可以在服务端
真的坏掉时合法地不跑（绿着但没测）。

现实现更进一步：**不再有环境性 skip**。缺 admin token、CSRF 拿不到、创建用户
返回非 2xx，全部让用例变红；否则 CI 里造数失败会再次把正向守卫静默跳过
（2026-11-23 实测：造数 403 后整条用例 skipped）。
"""
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from tests.e2e_api import test_auth_flow as mod


def _resp(status: int, text: str = ''):
    r = MagicMock()
    r.status_code = status
    r.text = text
    return r


def _api(post=None, get=None, csrf: str | None = None):
    api = MagicMock()
    api.post = post or AsyncMock()
    api.get = get or AsyncMock(return_value=_resp(200))
    api.cookies.get = MagicMock(return_value=csrf)
    return api


def _token(value: str, db_reachable: bool = True):
    outcome = MagicMock()
    outcome.token = value
    outcome.db_reachable = db_reachable
    return outcome


def test_helpers_never_skip() -> None:
    """造数链路上不允许出现 pytest.skip —— 跳过等于「绿着但没测」。"""
    import inspect

    for helper in (mod._temp_user_admin_headers, mod._create_temp_user):
        assert 'pytest.skip' not in inspect.getsource(helper), f'{helper.__name__} 仍会跳过用例'


@pytest.mark.asyncio
async def test_missing_admin_token_fails_the_test(monkeypatch):
    import tests.e2e_api.conftest as e2e_conftest

    monkeypatch.setattr(e2e_conftest, '_mint_token', lambda *a, **kw: _token(''))
    with pytest.raises(BaseException) as ei:
        await mod._temp_user_admin_headers(_api())
    assert ei.type.__name__ == 'Failed'


@pytest.mark.asyncio
async def test_missing_csrf_cookie_fails_the_test(monkeypatch):
    import tests.e2e_api.conftest as e2e_conftest

    monkeypatch.setattr(e2e_conftest, '_mint_token', lambda *a, **kw: _token('admin-token'))
    with pytest.raises(AssertionError, match='CSRF'):
        await mod._temp_user_admin_headers(_api(csrf=None))


@pytest.mark.asyncio
async def test_unhealthy_backend_during_csrf_setup_fails_the_test(monkeypatch):
    import tests.e2e_api.conftest as e2e_conftest

    monkeypatch.setattr(e2e_conftest, '_mint_token', lambda *a, **kw: _token('admin-token'))
    api = _api(get=AsyncMock(return_value=_resp(503)), csrf='token')
    with pytest.raises(AssertionError, match='CSRF 初始化失败'):
        await mod._temp_user_admin_headers(api)


@pytest.mark.parametrize('status', [403, 404, 500, 502, 422, 409])
@pytest.mark.asyncio
async def test_create_failure_always_fails_the_test(status):
    """端点不可达或服务端故障都不得退化成 skip。"""
    api = _api(post=AsyncMock(return_value=_resp(status, 'boom')))
    with pytest.raises(AssertionError, match='创建临时用户失败'):
        await mod._create_temp_user(api, {'Authorization': 'Bearer admin-token'})


@pytest.mark.asyncio
async def test_create_sends_csrf_headers_and_random_password():
    post = AsyncMock(return_value=_resp(201))
    api = _api(post=post)
    headers = {'Authorization': 'Bearer admin-token', 'X-CSRF-Token': 'csrf'}
    username1, password1 = await mod._create_temp_user(api, headers)
    username2, password2 = await mod._create_temp_user(api, headers)

    assert username1.startswith(mod._TEMP_PREFIX) and username1 != username2
    assert password1 and password1 != password2, '临时口令必须每次随机，不能是固定值'
    assert post.await_args.kwargs['headers'] == headers


@pytest.mark.asyncio
async def test_network_error_is_not_swallowed():
    """连接失败也要冒出来（否则调用方可能又把它当环境问题吞掉）。"""
    api = _api(post=AsyncMock(side_effect=httpx.ConnectError('boom')))
    with pytest.raises(httpx.ConnectError):
        await mod._create_temp_user(api, {'Authorization': 'Bearer admin-token'})
