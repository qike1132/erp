"""认证接口测试"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestAuthEndpoints:
    @pytest.mark.asyncio
    async def test_login_page_renders(self, client):
        """GET /login 应返回 200 和 HTML 内容"""
        response = await client.get("/login")
        assert response.status_code == 200
        assert "text/html" in response.headers.get("content-type", "")

    @pytest.mark.asyncio
    async def test_login_invalid_credentials(self, client, mock_db):
        """POST /api/v1/auth/login 使用错误凭证应返回 401 或 403"""
        # mock_db.execute 返回空结果，模拟用户不存在
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        response = await client.post("/api/v1/auth/login", json={
            "username": "wronguser",
            "password": "wrongpass",
        })
        assert response.status_code in (401, 403)

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
        mock_user.password = "$2b$12$test_hash"
        mock_user.permissions = []

        mock_result = MagicMock()
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
        assert "Max-Age=2678" in cookie_header or "max-age=2678" in cookie_header, \
            f"记住我应设置约31天的cookie有效期，实际: {cookie_header}"

    @pytest.mark.asyncio
    async def test_login_without_remember_me_sets_short_cookie(self, client, mock_db):
        """POST /api/v1/auth/login 未勾选记住我时应设置1天有效期的cookie"""
        from fastapi_app.shared_models import User

        mock_user = MagicMock(spec=User)
        mock_user.id = 1
        mock_user.username = "admin"
        mock_user.status = True
        mock_user.password = "$2b$12$test_hash"
        mock_user.permissions = []

        mock_result = MagicMock()
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
        assert "Max-Age=86400" in cookie_header or "max-age=86400" in cookie_header, \
            f"未记住我应设置1天的cookie有效期，实际: {cookie_header}"
