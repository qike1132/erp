"""refresh token 轮换 + 幂等重放（P1-3）。

背景（上线前审计）
------------------
`/auth/refresh` 此前只签发新的 access token：**既不轮换也不吊销 refresh token**，
所以被窃的 refresh token 可用满 `REFRESH_TOKEN_EXPIRE_DAYS`（默认 **7 天**）。

为什么是「幂等重放」而不是「一次性」轮换
----------------------------------------
前端 401 单飞是**模块级变量 —— 每个标签页各自单飞**（`api/request.ts:19`）。
ERP 用户常同时开多个标签页，于是「同一 refresh token 被并发使用」是常态。
若做成一次性轮换，后到的标签页必吃 401 → **随机被登出**。

因此 grace 窗口内用旧 token 重放时，必须拿到**与第一次等价**的新 token
（同一个 jti），两个标签页才不会互相踢掉。

为什么 grace 只存 jti 而不是 token
----------------------------------
存 token 等于把凭据短暂落到 Redis（安全评审会指摘）。而**只用 jti 重新签发**
即可得到等价凭据 —— jti 本身不能用于认证，落 Redis 无额外暴露。
"""
from __future__ import annotations

import asyncio

import pytest
import pytest_asyncio

from fastapi_app.core.auth.token import create_refresh_token

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


@pytest_asyncio.fixture(autouse=True)
async def _csrf_header(async_client):
    """`/auth/refresh` 不在 CSRF 豁免名单里（登录/登出/埋点才豁免），
    必须按双击 cookie 模式带上 X-CSRF-Token —— 沿用既有测试的做法：
    先发一个请求让中间件下发 cookie，再把它回填到请求头。"""
    await async_client.get('/api/v1/health')
    token = async_client.cookies.get('fastapi_csrf_token')
    if token:
        async_client.headers['X-CSRF-Token'] = token

_REFRESH_COOKIE = 'refresh_token'


def _mint_refresh(user_id: int) -> str:
    return create_refresh_token({'sub': str(user_id), 'username': 'admin'})


async def test_refresh_issues_new_refresh_token(async_client, admin_user) -> None:
    """刷新必须换发新的 refresh token（与旧的不同）。"""
    old = _mint_refresh(admin_user.id)

    resp = await async_client.post('/api/v1/auth/refresh', json={'refresh_token': old})

    assert resp.status_code == 200, resp.text
    new = resp.cookies.get(_REFRESH_COOKIE)
    assert new, '响应未设置新的 refresh cookie'
    assert new != old, 'refresh token 未被轮换（仍是旧值）'


async def test_refresh_still_returns_access_token(async_client, admin_user) -> None:
    """轮换不得破坏原有行为：仍要返回可用的 access token。"""
    resp = await async_client.post(
        '/api/v1/auth/refresh', json={'refresh_token': _mint_refresh(admin_user.id)},
    )

    assert resp.status_code == 200, resp.text
    assert resp.json().get('access_token'), '未返回 access_token'


async def test_concurrent_refresh_with_same_token_both_succeed(async_client, admin_user) -> None:
    """同一 refresh token 被并发使用（两个标签页）→ **都成功**且拿到等价的 token。

    这是「幂等重放」存在的唯一理由：顺序轮换会把后到的标签页踢成 401。
    """
    token = _mint_refresh(admin_user.id)

    first = await async_client.post('/api/v1/auth/refresh', json={'refresh_token': token})
    second = await async_client.post('/api/v1/auth/refresh', json={'refresh_token': token})

    assert first.status_code == 200, first.text
    assert second.status_code == 200, f'并发重放被拒 → 多标签页会被登出：{second.text}'

    a = first.cookies.get(_REFRESH_COOKIE)
    b = second.cookies.get(_REFRESH_COOKIE)
    assert a and b, '两次都应换发新的 refresh cookie'
    # 等价性以 jti 判定（签发时间不同会导致字符串不同）
    from fastapi_app.core.deps import _decode_jwt_token
    assert _decode_jwt_token(a, expected_type='refresh')['jti'] == \
           _decode_jwt_token(b, expected_type='refresh')['jti'], '两次重放拿到的不是同一个凭据'


async def test_replay_after_grace_window_is_rejected(async_client, admin_user, monkeypatch) -> None:
    """grace 窗口**真正过期后**，旧 refresh token 必须失效。

    ⚠️ 不要用「把 grace 设成 0」来测这条：那会让 `_remember_rotation` 直接 return、
    `_rotation_grace_jti` 直接短路 —— 根本没碰过存储，测的是"grace 被禁用"，
    而不是"窗口过期"。所以这里把窗口设成 1 秒并**真的等过去**。
    """
    from fastapi_app.api.v1.endpoints import auth as auth_endpoint

    monkeypatch.setattr(auth_endpoint, 'REFRESH_ROTATION_GRACE_SECONDS', 1.0)

    old = _mint_refresh(admin_user.id)
    first = await async_client.post('/api/v1/auth/refresh', json={'refresh_token': old})
    assert first.status_code == 200, first.text
    # 窗口内重放应当仍然成功（多标签页）
    assert (await async_client.post('/api/v1/auth/refresh', json={'refresh_token': old})).status_code == 200

    await asyncio.sleep(1.2)  # 让窗口过期

    replay = await async_client.post('/api/v1/auth/refresh', json={'refresh_token': old})

    assert replay.status_code == 401, '窗口过期后重放旧 token 必须被拒（否则等于没轮换）'


async def test_replay_rejected_after_rotated_token_revoked(async_client, admin_user) -> None:
    """新 jti 在 grace 窗口内被吊销（例如用户登出）→ 旧 token 重放必须 401。

    漏掉这条复查，持有旧 refresh token 的人就能在登出后再换到一枚**仍然有效**的
    access token —— 登出后最长 ACCESS_TOKEN_EXPIRE_MINUTES 的未授权访问窗口。
    """
    from fastapi_app.core.deps import _decode_jwt_token, revoke_token

    old = _mint_refresh(admin_user.id)
    first = await async_client.post('/api/v1/auth/refresh', json={'refresh_token': old})
    assert first.status_code == 200, first.text

    rotated = _decode_jwt_token(first.cookies.get(_REFRESH_COOKIE), expected_type='refresh')
    await revoke_token(rotated['jti'], rotated['exp'])  # 模拟"轮换后用户登出"

    replay = await async_client.post('/api/v1/auth/refresh', json={'refresh_token': old})

    assert replay.status_code == 401, '登出后旧 token 仍能换到有效 access token'


async def test_concurrent_refresh_does_not_lock_out_a_tab(async_client, admin_user) -> None:
    """**真正并发**（asyncio.gather）使用同一 refresh token → 两个标签页都不得被登出。

    这是幂等设计存在的唯一理由；顺序调用测不出竞争。
    """
    token = _mint_refresh(admin_user.id)

    results = await asyncio.gather(*[
        async_client.post('/api/v1/auth/refresh', json={'refresh_token': token}) for _ in range(2)
    ])

    assert [r.status_code for r in results] == [200, 200], [r.status_code for r in results]
    for r in results:
        assert r.cookies.get(_REFRESH_COOKIE), '并发下也应换发新的 refresh cookie'


async def test_body_supplied_refresh_returns_new_token(async_client, admin_user) -> None:
    """请求体传入 refresh token 的客户端（移动端/API）必须拿回新 token。

    这类客户端读不到 httpOnly cookie；只回 cookie 的话它仍持旧 token，
    grace 窗口过后必然 401。
    """
    resp = await async_client.post(
        '/api/v1/auth/refresh', json={'refresh_token': _mint_refresh(admin_user.id)},
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body.get('refresh_token'), '响应体未回传轮换后的 refresh token'
    assert body['refresh_token'] != _mint_refresh(admin_user.id)  # 是新的（不是原样回显）
