"""E2E 造临时用户的 skip 边界回归（2026-10-30 审计 A-M46）。

原实现 `_create_temp_user` 对任何非 2xx（含 500）都返回 None，调用方随即
`pytest.skip`——于是「登录返回 user=null」这条**唯一**E2E 守卫可以在服务端
真的坏掉时合法地不跑（绿着但没测）。

修复后只有「环境性缺失」（缺 admin token / 端点在本环境不可用 401·403·404·405）
才 skip；端点可达却返回 4xx 业务错或 5xx 必须让用例变红。
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


def _api(post):
    api = MagicMock()
    api.post = post
    return api


@pytest.fixture(autouse=True)
def _stub_token(monkeypatch):
    import tests.e2e_api.conftest as e2e_conftest

    token = MagicMock()
    token.token = 'admin-token'
    monkeypatch.setattr(e2e_conftest, '_mint_token', lambda *a, **kw: token)


@pytest.mark.asyncio
async def test_missing_admin_token_is_environment_skip():
    import tests.e2e_api.conftest as e2e_conftest

    e2e_conftest._mint_token = lambda *a, **kw: MagicMock(token='')
    with pytest.raises(mod.TempUserUnavailableError, match='admin token'):
        await mod._create_temp_user(_api(AsyncMock()))


@pytest.mark.asyncio
async def test_unreachable_endpoint_is_environment_skip():
    api = _api(AsyncMock(side_effect=httpx.ConnectError('boom')))
    with pytest.raises(mod.TempUserUnavailableError, match='请求失败'):
        await mod._create_temp_user(api)


@pytest.mark.parametrize('status', [401, 403, 404, 405])
@pytest.mark.asyncio
async def test_endpoint_unavailable_statuses_are_environment_skip(status):
    api = _api(AsyncMock(return_value=_resp(status)))
    with pytest.raises(mod.TempUserUnavailableError):
        await mod._create_temp_user(api)


@pytest.mark.parametrize('status', [500, 502, 422, 409])
@pytest.mark.asyncio
async def test_reachable_endpoint_failure_must_fail_the_test(status):
    """端点可达但创建失败 → 真回归，不能 skip 掉唯一守卫。"""
    api = _api(AsyncMock(return_value=_resp(status, 'server error')))
    with pytest.raises(BaseException) as ei:  # pytest.fail 抛 Failed
        await mod._create_temp_user(api)
    assert ei.type.__name__ == 'Failed'


@pytest.mark.asyncio
async def test_success_returns_credentials():
    api = _api(AsyncMock(return_value=_resp(201)))
    username, password = await mod._create_temp_user(api)
    assert username.startswith(mod._TEMP_PREFIX)
    assert password
