"""鉴权与身份契约 —— 覆盖 ``views/login``、``stores/auth`` 依赖的全部接口。

为什么单独立一个文件
--------------------
本项目刚发生过的 ``{user:null}`` 伪用户缺陷（见
``frontend-vite/src/stores/auth.ts::setUserInfo``）说明：
鉴权响应形态的**隐式假设**是最容易出事故的地方。前端假设
``/auth/me`` 返回 ``{user: ...}``，后端实际返回**扁平** ``UserInfoResponse``，
两者一旦不一致，前端不报错、只是渲染出一个"已登录的空壳"。

所以这里不做"状态码对就行"的弱断言，而是**逐字段锁定身份契约**。
"""

from __future__ import annotations

import contextlib

import httpx
import pytest

pytestmark = pytest.mark.e2e_api


class TestAuthContract:
    """/auth/me 的身份契约 —— 前端 authStore 的唯一真相源。"""

    async def test_me_returns_flat_userinfo_not_wrapped(
        self, admin_api: httpx.AsyncClient
    ) -> None:
        """``/auth/me`` 必须是**扁平**结构，不含 ``user`` 包装层。

        这是 ``{user:null}`` 伪用户缺陷的**回归锁**：
        若后端哪天改成返回 ``{user: {...}}``，前端 ``fetchUser`` 的
        ``'user' in res`` 分支会被激活 —— 那条分支此前从未被真实后端走过。
        锁住形态，就等于锁住了那条分支的触发条件。
        """
        resp = await admin_api.get("/api/v1/auth/me")
        assert resp.status_code == 200, resp.text
        body = resp.json()

        assert "user" not in body, (
            "/auth/me 出现了 `user` 包装层。前端 stores/auth.ts::fetchUser 会走 "
            "`'user' in res` 分支；该分支此前从未被真实后端覆盖，形态变更需同步 "
            "前端适配 + 补测试。"
        )

        # 逐字段锁定类型：前端 setUserInfo 直接消费这 5 个键
        for key in ("user_id", "username", "is_super", "factory", "permissions"):
            assert key in body, f"/auth/me 缺少字段 `{key}`（前端 setUserInfo 依赖它）"

        assert isinstance(body["user_id"], int) and body["user_id"] > 0, (
            f"user_id 必须是正整数，实际 {body['user_id']!r}。"
            "前端 setUserInfo 用 `!id` 判定伪用户，0/None 会被拒绝并留空身份。"
        )
        assert isinstance(body["username"], str) and body["username"], (
            f"username 必须是非空字符串，实际 {body['username']!r}"
        )
        assert isinstance(body["is_super"], bool)
        assert body["factory"] is None or isinstance(body["factory"], str)
        assert isinstance(body["permissions"], list)

    async def test_me_without_token_is_401_not_200_empty(
        self, api: httpx.AsyncClient
    ) -> None:
        """无 token 必须 401。

        不允许"200 + 空身份"：那正是伪用户的成因 —— 前端拿到一个
        看起来成功、实际没有身份值的响应，于是"已登录空壳"上线。
        """
        resp = await api.get("/api/v1/auth/me")
        assert resp.status_code == 401, (
            f"未鉴权访问 /auth/me 返回 {resp.status_code}，应为 401。"
            f"若返回 200，前端会把它当成合法身份。body={resp.text[:200]}"
        )

    async def test_me_with_garbage_token_is_401(self, api: httpx.AsyncClient) -> None:
        """伪造 token 必须 401，不能 500（500 会让前端当成网络故障而非登录失效）。"""
        resp = await api.get(
            "/api/v1/auth/me",
            headers={"Authorization": "Bearer not-a-real-token-at-all"},
        )
        assert resp.status_code == 401, (
            f"伪造 token 返回 {resp.status_code}，应为 401。body={resp.text[:200]}"
        )

    async def test_me_error_shape_is_consistent(self, api: httpx.AsyncClient) -> None:
        """错误响应必须是统一信封 ``{success:false, detail, status_code, request_id}``。

        前端 ``apiRequest`` 依赖 ``detail`` 做提示、依赖 ``success`` 判定成败。
        形态不一致会导致错误提示空白。
        """
        resp = await api.get("/api/v1/auth/me")
        assert resp.status_code == 401
        body = resp.json()

        assert body.get("success") is False, f"错误信封缺少 success:false —— {body}"
        assert body.get("detail"), f"错误信封缺少 detail（前端用其做提示）—— {body}"
        assert body.get("status_code") == 401, (
            f"信封内 status_code={body.get('status_code')!r} 与 HTTP 状态码不一致"
        )
        # request_id 是排查线上问题的唯一线索，必须带回
        assert body.get("request_id"), f"错误信封缺少 request_id —— {body}"


class TestAuthEndpointsAlive:
    """登录/登出/刷新/检查 —— views/login 走的就是这几条。"""

    async def test_login_rejects_wrong_password(self, api: httpx.AsyncClient) -> None:
        """错误口令必须 401 且不回 token。

        不能"200 + 空 token"：前端会存一个空 token，之后每个请求都 401，
        表现为"登录成功但进去啥都看不到"。
        """
        resp = await api.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "__definitely_wrong_password__"},
        )
        assert resp.status_code == 401, (
            f"错误口令返回 {resp.status_code}，应为 401。body={resp.text[:200]}"
        )
        assert "access_token" not in resp.text or not resp.json().get("access_token")

    async def test_login_response_carries_user_object(self, api: httpx.AsyncClient) -> None:
        """登录成功时 ``user`` 必须是完整身份对象，而非 null。

        这是伪用户缺陷的**另一条路径**：若 login 返回 ``user: null``，
        前端 ``setUserInfo(null)`` 会构造出 id=0 的空壳身份。
        这里用现造临时用户来验证，避免依赖真实库里的口令。
        """
        created = await _create_temp_user(api)
        if created is None:
            pytest.skip("无法创建临时用户（可能缺少用户创建权限或写库受限）")
        username, password = created
        try:
            resp = await api.post(
                "/api/v1/auth/login", json={"username": username, "password": password}
            )
            assert resp.status_code == 200, resp.text
            body = resp.json()

            assert body.get("access_token"), "登录成功却未返回 access_token"
            assert body.get("user") is not None, (
                "登录返回 user=null。前端 stores/auth.ts::setUserInfo 会因此构造 "
                "id=0 的伪用户（已登录空壳）。后端必须回完整身份对象。"
            )
            user = body["user"]
            assert user.get("user_id"), f"登录返回的 user 缺少 user_id —— {user}"
            assert user.get("username"), f"登录返回的 user 缺少 username —— {user}"
        finally:
            await _delete_temp_user(api, username)

    async def test_refresh_requires_auth(self, api: httpx.AsyncClient) -> None:
        """``/auth/refresh`` 未鉴权必须被拒（不能靠它绕过登录）。

        断言的是**安全性质**（拿不到新令牌），不是某个具体状态码。两种拒绝都合法：

        - **401**：中间件放行到端点，端点因「缺少刷新令牌」拒绝；
        - **403**：被 CSRF 中间件拦下 —— ``/auth/refresh`` 不在豁免名单
          （只有 login / logout / vitals 豁免），无 Bearer 且无 CSRF
          cookie/header 的裸请求在此被拒。

        实测生产后端返回 403（CSRF 先于端点生效）。两者都满足「不能绕过登录」，
        故不断言具体码，只锁定真正要防的失效模式：**返回 200 且发出令牌**。
        """
        resp = await api.post("/api/v1/auth/refresh")
        assert resp.status_code in (401, 403), (
            f"未鉴权 refresh 返回 {resp.status_code}，应为 401 或 403（均属拒绝）。"
            f"body={resp.text[:200]}"
        )
        body = resp.text
        assert "access_token" not in body, (
            f"未鉴权 refresh 竟返回了令牌 —— 可绕过登录。body={body[:300]}"
        )

    async def test_check_endpoint_reports_auth_state(self, api: httpx.AsyncClient) -> None:
        """``/auth/check`` 是登录态探测接口，views/login 首屏会打它。

        只要求它**不 5xx**：未登录时回 200（authenticated 字段）或 401
        都是合理契约，但绝不能 500 —— 500 会让登录页卡在加载态。
        """
        resp = await api.get("/api/v1/auth/check")
        assert resp.status_code < 500, (
            f"/auth/check 返回 {resp.status_code}（5xx 会让登录页卡死在加载态）。"
            f"body={resp.text[:200]}"
        )
        assert resp.status_code in (200, 401), (
            f"/auth/check 返回 {resp.status_code}，契约允许 200 或 401。"
        )


# ============================================================
# 临时用户 —— 仅用于验证登录链路，用完即删
# ============================================================
_TEMP_PREFIX = "__e2e_api_tmp__"


async def _create_temp_user(api: httpx.AsyncClient) -> tuple[str, str] | None:
    """造一个临时用户。返回 (username, password)；失败返回 None。

    走 ``/api/v1/users/create`` 需要管理员 token，所以这里先用
    admin token 覆盖 header，再还原 —— 保持 ``api`` fixture 的"无鉴权"语义。
    """
    import time

    from tests.e2e_api.conftest import _mint_token

    token = _mint_token("admin").token
    if not token:
        return None

    username = f"{_TEMP_PREFIX}{int(time.time())}"
    password = "E2eApiTmp!2026"

    try:
        resp = await api.post(
            "/api/v1/users/create",
            json={"username": username, "password": password, "is_super": False},
            headers={"Authorization": f"Bearer {token}"},
        )
    except httpx.HTTPError:
        return None
    if resp.status_code not in (200, 201):
        return None
    return username, password


async def _delete_temp_user(api: httpx.AsyncClient, username: str) -> None:
    """按 username 查 id 后删除。失败静默 —— 清理失败不应让用例变红，但会留痕。"""
    from sqlalchemy import create_engine, text

    from tests.e2e_api.conftest import _mint_token, real_database_url

    token = _mint_token("admin").token
    if not token:
        return
    headers = {"Authorization": f"Bearer {token}"}

    # 清理尽力而为：失败不应让用例变红
    with contextlib.suppress(Exception):
        # real_database_url()：不能用 settings.DATABASE_URL（已被 autouse fixture
        # 改成空测试库），否则查不到刚创建的用户，临时用户会留在真实库里。
        engine = create_engine(real_database_url())
        with engine.connect() as conn:
            row = conn.execute(
                text('SELECT id FROM "user" WHERE username = :u'), {"u": username}
            ).fetchone()
        if row is None:
            return
        await api.delete(f"/api/v1/users/delete/{row[0]}", headers=headers)
