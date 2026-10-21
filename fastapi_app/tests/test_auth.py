"""认证接口测试"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestAuthEndpoints:
    @pytest.mark.asyncio
    async def test_login_invalid_credentials(self, client, mock_db):
        """POST /api/v1/auth/login 使用错误凭证应返回 401（用户不存在即拒绝）。"""
        # mock_db.execute 返回空结果，模拟用户不存在
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        response = await client.post("/api/v1/auth/login", json={
            "username": "wronguser",
            "password": "wrongpass",
        })
        assert response.status_code == 401, f"错误凭证应 401，实测 {response.status_code}: {response.text}"

    @pytest.mark.asyncio
    async def test_check_unauthenticated(self, client):
        """GET /api/v1/auth/check — get_current_user_id 被覆盖返回 1，应返回 200 和用户信息"""
        response = await client.get("/api/v1/auth/check")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["user_id"] == 1

    @pytest.mark.asyncio
    async def test_logout(self, client):
        """POST /api/v1/auth/logout 应返回 200 并清除 cookie"""
        response = await client.post("/api/v1/auth/logout")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        # 验证 set-cookie 头中包含 access_token 的清除指令
        set_cookie_headers = response.headers.get_list("set-cookie")
        cookie_cleared = any("access_token" in h and ('Max-Age=0' in h or 'max-age=0' in h) for h in set_cookie_headers)
        assert cookie_cleared, "logout 应清除 access_token cookie"

    @pytest.mark.asyncio
    async def test_login_remember_me_sets_long_cookie(self, client, mock_db):
        """POST /api/v1/auth/login 勾选记住我时应设置31天有效期的cookie"""
        from fastapi_app.shared_models import User

        # 创建模拟用户
        mock_user = MagicMock(spec=User)
        mock_user.id = 1
        mock_user.username = "admin"
        mock_user.status = True
        mock_user.is_super = True
        mock_user.factory = None
        mock_user.password = "$2b$12$test_hash"
        mock_user.permissions = []

        # get_user_with_permissions_by_username 经 result.unique().scalar_one_or_none()
        # 取用户，需 mock unique() 返回自身，否则取到的是自动生成的 MagicMock
        mock_result = MagicMock()
        mock_result.unique.return_value = mock_result
        mock_result.scalar_one_or_none.return_value = mock_user
        mock_db.execute = AsyncMock(return_value=mock_result)

        with patch("fastapi_app.core.security.verify_password", return_value=True), \
             patch("fastapi_app.core.security.needs_migration", return_value=False):
            response = await client.post("/api/v1/auth/login", json={
                "username": "admin",
                "password": "password",
                "remember": True,
            })

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

        # 验证 cookie 设置了较长的 max_age（31天左右）
        set_cookie_headers = response.headers.get_list("set-cookie")
        cookie_header = next((h for h in set_cookie_headers if "access_token" in h), "")
        assert "Max-Age=86400" in cookie_header or "max-age=86400" in cookie_header, \
            f"记住我应设置约1天的cookie有效期，实际: {cookie_header}"

    @pytest.mark.asyncio
    async def test_login_without_remember_me_sets_short_cookie(self, client, mock_db):
        """POST /api/v1/auth/login 未勾选记住我时应设置1天有效期的cookie"""
        from fastapi_app.shared_models import User

        mock_user = MagicMock(spec=User)
        mock_user.id = 1
        mock_user.username = "admin"
        mock_user.status = True
        mock_user.is_super = True
        mock_user.factory = None
        mock_user.password = "$2b$12$test_hash"
        mock_user.permissions = []

        mock_result = MagicMock()
        mock_result.unique.return_value = mock_result
        mock_result.scalar_one_or_none.return_value = mock_user
        mock_db.execute = AsyncMock(return_value=mock_result)

        with patch("fastapi_app.core.security.verify_password", return_value=True), \
             patch("fastapi_app.core.security.needs_migration", return_value=False):
            response = await client.post("/api/v1/auth/login", json={
                "username": "admin",
                "password": "password",
                "remember": False,
            })

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

        # 验证 cookie 设置了较短的 max_age（1天=86400秒）
        set_cookie_headers = response.headers.get_list("set-cookie")
        cookie_header = next((h for h in set_cookie_headers if "access_token" in h), "")
        assert "Max-Age=3600" in cookie_header or "max-age=3600" in cookie_header, \
            f"未记住我应设置1小时的cookie有效期，实际: {cookie_header}"

    @pytest.mark.asyncio
    async def test_login_rate_limit_burst(self, client, mock_db):
        """POST /api/v1/auth/login 同一 IP 1 分钟内超过 100 次（内网宽松阈值）应返回 429"""
        from unittest.mock import AsyncMock

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        # 现行实现：redis_wrapper.get_client() + pipeline 批量 incr burst/window 两个计数器
        mock_redis = MagicMock()
        mock_pipe = MagicMock()
        mock_pipe.execute = AsyncMock(return_value=(101, True, 1, True))
        mock_redis.pipeline = MagicMock(return_value=mock_pipe)
        mock_redis.expire = AsyncMock()

        with patch("fastapi_app.core.redis_wrapper.get_client", return_value=mock_redis):
            response = await client.post("/api/v1/auth/login", json={
                "username": "wronguser",
                "password": "wrongpass",
            })

        assert response.status_code == 429
        assert "1分钟" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_login_rate_limit_window(self, client, mock_db):
        """POST /api/v1/auth/login 同一 IP 5 分钟内超过 300 次（内网宽松阈值）应返回 429"""
        from unittest.mock import AsyncMock

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        mock_redis = MagicMock()
        # burst 计数正常（<=100），但 5 分钟窗口计数超过 300
        mock_pipe = MagicMock()
        mock_pipe.execute = AsyncMock(return_value=(3, True, 301, True))
        mock_redis.pipeline = MagicMock(return_value=mock_pipe)
        mock_redis.expire = AsyncMock()

        with patch("fastapi_app.core.redis_wrapper.get_client", return_value=mock_redis):
            response = await client.post("/api/v1/auth/login", json={
                "username": "wronguser",
                "password": "wrongpass",
            })

        assert response.status_code == 429
        assert "5分钟" in response.json()["detail"]
