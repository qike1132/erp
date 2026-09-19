"""auth_service.authenticate_login - 单元测试

覆盖 P1-3 从 auth.py endpoint 下沉的登录核心业务逻辑：
- 用户不存在 / 已禁用 / 密码错误 → 401
- 密码哈希迁移（bcrypt → argon2id）
- 密码哈希参数升级（check_needs_rehash）
- 令牌生成（access + refresh）与 remember 有效期
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from fastapi_app.core.exceptions import UnauthorizedError
from fastapi_app.services import auth_service


def _make_user(user_id=1, username="admin", status=True, password="$2b$12$hash"):
    """构造 mock User"""
    user = MagicMock()
    user.id = user_id
    user.username = username
    user.status = status
    user.password = password
    user.is_super = True
    user.factory = None
    user.permissions = []
    return user


# ============================================================================
# authenticate_login
# ============================================================================
class TestAuthenticateLogin:
    @pytest.mark.asyncio
    async def test_user_not_found_raises_401(self):
        """用户不存在时应抛 401 且执行时序攻击防护"""
        db = AsyncMock()
        with patch('fastapi_app.services.user_service.get_user_with_permissions_by_username',
                    new=AsyncMock(return_value=None)), \
             patch('fastapi_app.core.security.verify_password', return_value=False), \
             patch('fastapi_app.services.auth_service.run_in_threadpool', new=AsyncMock()):
            with pytest.raises(UnauthorizedError) as exc_info:
                await auth_service.authenticate_login(db, "nouser", "pass", False, "1.2.3.4")
        assert exc_info.value.status_code == 401
        assert "用户名或密码错误" in exc_info.value.message

    @pytest.mark.asyncio
    async def test_user_disabled_raises_401(self):
        """用户已禁用时应抛 401"""
        db = AsyncMock()
        disabled_user = _make_user(status=False)
        with patch('fastapi_app.services.user_service.get_user_with_permissions_by_username',
                    new=AsyncMock(return_value=disabled_user)), \
             patch('fastapi_app.services.auth_service.run_in_threadpool', new=AsyncMock()):
            with pytest.raises(UnauthorizedError) as exc_info:
                await auth_service.authenticate_login(db, "admin", "pass", False, "1.2.3.4")
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_wrong_password_raises_401(self):
        """密码校验失败时应抛 401"""
        db = AsyncMock()
        user = _make_user()
        with patch('fastapi_app.services.user_service.get_user_with_permissions_by_username',
                    new=AsyncMock(return_value=user)), \
             patch('fastapi_app.services.auth_service.run_in_threadpool', new=AsyncMock(return_value=False)):
            with pytest.raises(UnauthorizedError) as exc_info:
                await auth_service.authenticate_login(db, "admin", "wrong", False, "1.2.3.4")
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_successful_login_returns_tokens(self):
        """登录成功时应返回 access_token / refresh_token / user"""
        db = AsyncMock()
        user = _make_user()
        with patch('fastapi_app.services.user_service.get_user_with_permissions_by_username',
                    new=AsyncMock(return_value=user)), \
             patch('fastapi_app.services.auth_service.run_in_threadpool', new=AsyncMock(return_value=True)), \
             patch('fastapi_app.core.security.needs_migration', return_value=False), \
             patch('fastapi_app.core.security.check_needs_rehash', return_value=False), \
             patch('fastapi_app.services.auth_service.create_access_token', return_value="access_tok") as mock_at, \
             patch('fastapi_app.services.auth_service.create_refresh_token', return_value="refresh_tok") as mock_rt:
            result = await auth_service.authenticate_login(db, "admin", "pass", False, "1.2.3.4")
        assert result['access_token'] == "access_tok"
        assert result['refresh_token'] == "refresh_tok"
        assert result['user'] is user
        assert result['token_max_age'] == 3600  # 非记住我 → 1 小时
        assert mock_at.called
        assert mock_rt.called

    @pytest.mark.asyncio
    async def test_remember_me_sets_24h_token_max_age(self):
        """remember=True 时 token_max_age 应为 86400（24 小时）"""
        db = AsyncMock()
        user = _make_user()
        with patch('fastapi_app.services.user_service.get_user_with_permissions_by_username',
                    new=AsyncMock(return_value=user)), \
             patch('fastapi_app.services.auth_service.run_in_threadpool', new=AsyncMock(return_value=True)), \
             patch('fastapi_app.core.security.needs_migration', return_value=False), \
             patch('fastapi_app.core.security.check_needs_rehash', return_value=False), \
             patch('fastapi_app.services.auth_service.create_access_token', return_value="at"), \
             patch('fastapi_app.services.auth_service.create_refresh_token', return_value="rt"):
            result = await auth_service.authenticate_login(db, "admin", "pass", True, "1.2.3.4")
        assert result['token_max_age'] == 86400

    @pytest.mark.asyncio
    async def test_password_hash_migration_on_login(self):
        """needs_migration=True 时应迁移哈希并 commit"""
        db = AsyncMock()
        user = _make_user(password="$2b$12$old_bcrypt_hash")
        with patch('fastapi_app.services.user_service.get_user_with_permissions_by_username',
                    new=AsyncMock(return_value=user)), \
             patch('fastapi_app.services.auth_service.run_in_threadpool', new=AsyncMock(side_effect=[True, "$argon2id$new"])), \
             patch('fastapi_app.core.security.needs_migration', return_value=True), \
             patch('fastapi_app.core.security.check_needs_rehash', return_value=False), \
             patch('fastapi_app.services.auth_service.create_access_token', return_value="at"), \
             patch('fastapi_app.services.auth_service.create_refresh_token', return_value="rt"):
            await auth_service.authenticate_login(db, "admin", "pass", False, "1.2.3.4")
        assert user.password == "$argon2id$new"
        assert db.commit.await_count == 1

    @pytest.mark.asyncio
    async def test_password_hash_migration_failure_does_not_block_login(self):
        """哈希迁移失败时应 rollback 但不阻断登录"""
        from sqlalchemy.exc import SQLAlchemyError

        db = AsyncMock()
        db.commit = AsyncMock(side_effect=SQLAlchemyError("commit failed"))
        user = _make_user(password="$2b$12$old_bcrypt_hash")
        with patch('fastapi_app.services.user_service.get_user_with_permissions_by_username',
                    new=AsyncMock(return_value=user)), \
             patch('fastapi_app.services.auth_service.run_in_threadpool', new=AsyncMock(side_effect=[True, "$argon2id$new"])), \
             patch('fastapi_app.core.security.needs_migration', return_value=True), \
             patch('fastapi_app.core.security.check_needs_rehash', return_value=False), \
             patch('fastapi_app.services.auth_service.create_access_token', return_value="at"), \
             patch('fastapi_app.services.auth_service.create_refresh_token', return_value="rt"):
            result = await auth_service.authenticate_login(db, "admin", "pass", False, "1.2.3.4")
        # 登录仍应成功
        assert result['access_token'] == "at"
        assert db.rollback.await_count == 1

    @pytest.mark.asyncio
    async def test_password_rehash_upgrade_on_login(self):
        """check_needs_rehash=True 时应升级哈希参数并 commit"""
        db = AsyncMock()
        user = _make_user(password="$argon2id$v=19$m=1024,t=1,p=1$old")
        with patch('fastapi_app.services.user_service.get_user_with_permissions_by_username',
                    new=AsyncMock(return_value=user)), \
             patch('fastapi_app.services.auth_service.run_in_threadpool', new=AsyncMock(side_effect=[True, "$argon2id$v=19$m=19456,t=2,p=1$new"])), \
             patch('fastapi_app.core.security.needs_migration', return_value=False), \
             patch('fastapi_app.core.security.check_needs_rehash', return_value=True), \
             patch('fastapi_app.services.auth_service.create_access_token', return_value="at"), \
             patch('fastapi_app.services.auth_service.create_refresh_token', return_value="rt"):
            await auth_service.authenticate_login(db, "admin", "pass", False, "1.2.3.4")
        assert "m=19456" in user.password
        assert db.commit.await_count == 1

    @pytest.mark.asyncio
    async def test_password_rehash_upgrade_failure_does_not_block_login(self):
        """check_needs_rehash 升级失败时应 rollback 但不阻断登录"""
        from sqlalchemy.exc import SQLAlchemyError

        db = AsyncMock()
        db.commit = AsyncMock(side_effect=SQLAlchemyError("rehash commit failed"))
        user = _make_user(password="$argon2id$v=19$m=1024,t=1,p=1$old")
        with patch('fastapi_app.services.user_service.get_user_with_permissions_by_username',
                    new=AsyncMock(return_value=user)), \
             patch('fastapi_app.services.auth_service.run_in_threadpool', new=AsyncMock(side_effect=[True, "$argon2id$v=19$m=19456,t=2,p=1$new"])), \
             patch('fastapi_app.core.security.needs_migration', return_value=False), \
             patch('fastapi_app.core.security.check_needs_rehash', return_value=True), \
             patch('fastapi_app.services.auth_service.create_access_token', return_value="at"), \
             patch('fastapi_app.services.auth_service.create_refresh_token', return_value="rt"):
            result = await auth_service.authenticate_login(db, "admin", "pass", False, "1.2.3.4")
        assert result['access_token'] == "at"
        assert db.rollback.await_count == 1
