"""用户管理模块测试"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ==================== Schema 测试 ====================

class TestUserSchemas:
    def test_user_create_valid(self):
        from fastapi_app.schemas.user import UserCreate
        data = UserCreate(username="testuser", password="Test123!@", is_super=False)
        assert data.username == "testuser"
        assert data.password == "Test123!@"
        assert data.is_super is False

    def test_user_create_default_super(self):
        from fastapi_app.schemas.user import UserCreate
        data = UserCreate(username="testuser", password="Test123!@")
        assert data.is_super is False

    def test_user_update_optional_fields(self):
        from fastapi_app.schemas.user import UserUpdate
        data = UserUpdate()
        assert data.password is None
        assert data.is_super is None

    def test_user_permission_update(self):
        from fastapi_app.schemas.user import UserPermissionUpdate
        data = UserPermissionUpdate(permission_ids=[1, 2, 3])
        assert len(data.permission_ids) == 3

    def test_user_response(self):
        from fastapi_app.schemas.user import UserResponse
        resp = UserResponse(id=1, username="admin", is_super=True, status=True)
        assert resp.id == 1
        assert resp.username == "admin"

    def test_permission_response(self):
        from fastapi_app.schemas.user import PermissionResponse
        perm = PermissionResponse(id=1, name="产品管理", code="product_manage", children=[])
        assert perm.code == "product_manage"
        assert perm.children == []


# ==================== Service 测试 ====================

class TestUserService:
    @pytest.fixture
    def mock_db(self):
        db = AsyncMock()
        db.commit = AsyncMock()
        db.flush = AsyncMock()
        db.refresh = AsyncMock()
        db.delete = AsyncMock()
        db.add = MagicMock()
        db.execute = AsyncMock()
        db.get = AsyncMock()
        return db

    @pytest.fixture
    def mock_user(self):
        user = MagicMock()
        user.id = 1
        user.username = "testuser"
        user.is_super = False
        user.status = True
        user.permissions = []
        return user

    @pytest.fixture
    def mock_permission(self):
        perm = MagicMock()
        perm.id = 1
        perm.code = "product_manage"
        perm.children = []
        return perm

    @pytest.mark.asyncio
    async def test_get_users(self, mock_db, mock_user):
        from fastapi_app.services.user_service import get_users
        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = [mock_user]
        mock_result.unique.return_value = mock_result
        mock_result.scalars.return_value = mock_scalars
        mock_db.execute = AsyncMock(return_value=mock_result)

        users, total = await get_users(mock_db)
        assert len(users) == 1

    @pytest.mark.asyncio
    async def test_create_user_success(self, mock_db):
        from fastapi_app.services.user_service import create_user
        # No existing user
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        with patch('fastapi_app.core.security.hash_password', return_value='hashed'):
            await create_user(mock_db, "newuser", "Test123!@", False)
        assert mock_db.add.called
        assert mock_db.flush.called

    @pytest.mark.asyncio
    async def test_create_user_duplicate(self, mock_db, mock_user):
        from fastapi_app.services.user_service import create_user
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_user
        mock_db.execute = AsyncMock(return_value=mock_result)

        with pytest.raises(ValueError, match="用户名已存在"):
            await create_user(mock_db, "testuser", "Test123!@", False)

    @pytest.mark.asyncio
    async def test_update_user_not_found(self, mock_db):
        from fastapi_app.services.user_service import update_user
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        with pytest.raises(ValueError, match="用户不存在"):
            await update_user(mock_db, 999, "Test123!@", None)

    @pytest.mark.asyncio
    async def test_update_user_password(self, mock_db, mock_user):
        from fastapi_app.services.user_service import update_user
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_user
        mock_db.execute = AsyncMock(return_value=mock_result)

        with patch('fastapi_app.core.security.hash_password', return_value='new_hashed'):
            await update_user(mock_db, 1, "Test123!@", None)
        assert mock_user.password == 'new_hashed'
        assert mock_db.flush.called

    @pytest.mark.asyncio
    async def test_toggle_user_status_success(self, mock_db, mock_user):
        from fastapi_app.services.user_service import toggle_user_status
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_user
        mock_db.execute = AsyncMock(return_value=mock_result)

        await toggle_user_status(mock_db, 1)
        assert mock_user.status is False  # toggled from True to False

    @pytest.mark.asyncio
    async def test_toggle_super_user_raises(self, mock_db):
        from fastapi_app.services.user_service import toggle_user_status
        super_user = MagicMock()
        super_user.is_super = True
        super_user.status = True
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = super_user
        mock_db.execute = AsyncMock(return_value=mock_result)

        with pytest.raises(ValueError, match="超级用户不能禁用"):
            await toggle_user_status(mock_db, 1)

    @pytest.mark.asyncio
    async def test_delete_user_success(self, mock_db, mock_user):
        from fastapi_app.services.user_service import delete_user
        mock_db.get = AsyncMock(return_value=mock_user)
        mock_db.scalar = AsyncMock(return_value=0)

        await delete_user(mock_db, 1)
        assert mock_db.delete.called
        assert mock_db.flush.called

    @pytest.mark.asyncio
    async def test_delete_super_user_raises(self, mock_db):
        from fastapi_app.services.user_service import delete_user
        super_user = MagicMock()
        super_user.is_super = True
        mock_db.get = AsyncMock(return_value=super_user)

        with pytest.raises(ValueError, match="超级用户不能删除"):
            await delete_user(mock_db, 1)

    @pytest.mark.asyncio
    async def test_update_user_permissions_skips_sensitive(self, mock_db, mock_user, mock_permission):
        from fastapi_app.services.user_service import update_user_permissions

        sensitive_perm = MagicMock()
        sensitive_perm.id = 2
        sensitive_perm.code = "user_manage"
        sensitive_perm.children = []

        # First execute call: load user with permissions
        mock_user_result = MagicMock()
        mock_user_result.unique.return_value = mock_user_result
        mock_user_result.scalar_one_or_none.return_value = mock_user
        mock_user.permissions = MagicMock()
        mock_user.permissions.clear = MagicMock()

        # Second execute call: load permissions by IDs
        mock_perm_result = MagicMock()
        mock_perm_scalars = MagicMock()
        mock_perm_scalars.all.return_value = [mock_permission, sensitive_perm]
        mock_perm_result.scalars.return_value = mock_perm_scalars

        mock_db.execute = AsyncMock(side_effect=[mock_user_result, mock_perm_result])

        await update_user_permissions(mock_db, 1, [1, 2])
        # sensitive permission should not be added
        assert mock_user.permissions.clear.called

    @pytest.mark.asyncio
    async def test_get_permissions(self, mock_db, mock_permission):
        from fastapi_app.services.user_service import get_permissions
        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = [mock_permission]
        mock_result.unique.return_value = mock_result
        mock_result.scalars.return_value = mock_scalars
        mock_db.execute = AsyncMock(return_value=mock_result)

        perms = await get_permissions(mock_db)
        assert len(perms) == 1


# ==================== Endpoint 测试 ====================

class TestUserEndpoints:
    @pytest.fixture
    def mock_db(self):
        db = AsyncMock()
        db.commit = AsyncMock()
        db.flush = AsyncMock()
        db.refresh = AsyncMock()
        db.delete = AsyncMock()
        db.add = MagicMock()
        db.execute = AsyncMock()
        db.get = AsyncMock()
        return db

    @pytest.mark.asyncio
    async def test_list_users_success(self, client, mock_db, mock_current_user):
        mock_user = MagicMock()
        mock_user.id = 1
        mock_user.username = "admin"
        mock_user.is_super = True
        mock_user.status = True
        mock_user.create_time = MagicMock()
        mock_user.create_time.strftime.return_value = "2024-01-01 00:00"
        mock_user.permissions = []

        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = [mock_user]
        mock_result.unique.return_value = mock_result
        mock_result.scalars.return_value = mock_scalars
        mock_db.execute = AsyncMock(return_value=mock_result)

        response = await client.get("/api/v1/users/list")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert len(data["users"]) == 1

    @pytest.mark.asyncio
    async def test_create_user_success(self, client, mock_db):
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        with patch('fastapi_app.core.security.hash_password', return_value='hashed'):
            response = await client.post("/api/v1/users/create", json={
                "username": "newuser", "password": "Test123!@", "is_super": False
            })
        assert response.status_code == 200
        assert response.json()["message"] == "用户添加成功"

    @pytest.mark.asyncio
    async def test_create_user_duplicate(self, client, mock_db):
        mock_user = MagicMock()
        mock_user.id = 1
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_user
        mock_db.execute = AsyncMock(return_value=mock_result)

        with patch('fastapi_app.core.security.hash_password', return_value='hashed'):
            response = await client.post("/api/v1/users/create", json={
                "username": "testuser", "password": "Test123!@", "is_super": False
            })
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_toggle_user_status(self, client, mock_db):
        mock_user = MagicMock()
        mock_user.is_super = False
        mock_user.status = True
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_user
        mock_db.execute = AsyncMock(return_value=mock_result)

        response = await client.post("/api/v1/users/toggle/2")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_delete_user_success(self, client, mock_db):
        mock_user = MagicMock()
        mock_user.is_super = False
        mock_db.get = AsyncMock(return_value=mock_user)
        mock_db.scalar = AsyncMock(side_effect=[2, 0, 0])

        response = await client.delete("/api/v1/users/delete/2")
        assert response.status_code == 200
        assert "删除" in response.json()["message"]
