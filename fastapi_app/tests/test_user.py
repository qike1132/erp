"""用户管理模块测试"""
from datetime import UTC, datetime
from types import SimpleNamespace
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
        assert data.department is None

    def test_user_create_with_department(self):
        """部门为固定枚举之一时被接受"""
        from fastapi_app.schemas.user import UserCreate
        data = UserCreate(username="testuser", password="Test123!@", department="采购部")
        assert data.department == "采购部"

    def test_user_create_without_department_defaults_none(self):
        from fastapi_app.schemas.user import UserCreate
        data = UserCreate(username="testuser", password="Test123!@")
        assert data.department is None

    def test_user_create_invalid_department_rejected(self):
        """非法部门值被拒绝（固定枚举，防写法漂移）"""
        from pydantic import ValidationError

        from fastapi_app.schemas.user import UserCreate
        with pytest.raises(ValidationError):
            UserCreate(username="testuser", password="Test123!@", department="生产")  # 应为 生产部

    def test_user_update_department_clear(self):
        """编辑时可传空字符串表示清除部门"""
        from fastapi_app.schemas.user import UserUpdate
        assert UserUpdate(department="").department == ""

    def test_user_update_invalid_department_rejected(self):
        from pydantic import ValidationError

        from fastapi_app.schemas.user import UserUpdate
        with pytest.raises(ValidationError):
            UserUpdate(department="不存在部")

    def test_user_response_includes_department(self):
        from fastapi_app.schemas.user import UserResponse
        resp = UserResponse(id=1, username="admin", is_super=True, status=True, department="仓库")
        assert resp.department == "仓库"

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


# ==================== has_permission 权限继承测试 ====================

def _make_perm(code, parent_id=None, children=None):
    """构造轻量级权限桩对象，避免依赖数据库"""
    return SimpleNamespace(code=code, parent_id=parent_id, children=children or [])


def _make_user(permissions, is_super=False):
    """构造轻量级用户桩对象，绑定真实的 has_permission 方法"""
    from types import MethodType

    from fastapi_app.shared_models.user import User
    stub = SimpleNamespace(is_super=is_super, permissions=permissions)
    stub.has_permission = MethodType(User.has_permission, stub)
    return stub


class TestUserHasPermission:
    """User.has_permission 权限继承逻辑测试

    覆盖核心场景：
    - 超级管理员拥有所有权限
    - user_ 前缀敏感权限仅超级管理员可访问
    - 拥有 xxx_manage 顶级权限时自动继承 xxx_view
    - view 不能向上继承 manage
    - delete/edit/create 不自动继承
    """

    def test_super_user_has_all_permissions(self):
        user = _make_user([], is_super=True)
        assert user.has_permission('product_view') is True
        assert user.has_permission('product_manage') is True
        assert user.has_permission('any_permission') is True

    def test_normal_user_no_permissions(self):
        user = _make_user([], is_super=False)
        assert user.has_permission('product_view') is False
        assert user.has_permission('product_manage') is False

    def test_manage_inherits_view(self):
        """拥有 xxx_manage 时自动通过 xxx_view 检查（本次修复的核心场景）"""
        user = _make_user([_make_perm('product_manage', parent_id=None)], is_super=False)
        assert user.has_permission('product_view') is True
        assert user.has_permission('product_manage') is True

    def test_view_does_not_inherit_manage(self):
        """view 不能向上继承 manage"""
        user = _make_user([_make_perm('product_view', parent_id=None)], is_super=False)
        assert user.has_permission('product_view') is True
        assert user.has_permission('product_manage') is False

    def test_manage_does_not_inherit_delete_edit_create(self):
        """拥有 xxx_manage 时不自动通过 delete/edit/create"""
        user = _make_user([_make_perm('product_manage', parent_id=None)], is_super=False)
        assert user.has_permission('product_delete') is False
        assert user.has_permission('product_edit') is False
        assert user.has_permission('product_create') is False

    def test_non_top_level_manage_does_not_inherit_view(self):
        """非顶级（parent_id 不为 None）的 manage 权限不触发 view 继承"""
        user = _make_user([_make_perm('sub_product_manage', parent_id=1)], is_super=False)
        assert user.has_permission('sub_product_view') is False

    def test_exact_permission_match(self):
        """精确权限匹配"""
        user = _make_user([_make_perm('order_manage', parent_id=None)], is_super=False)
        assert user.has_permission('order_manage') is True
        assert user.has_permission('order_view') is True
        assert user.has_permission('stock_view') is False

    def test_child_permission_match(self):
        """子权限匹配"""
        child_perm = _make_perm('product_view')
        parent_perm = _make_perm('product_manage', parent_id=None, children=[child_perm])
        user = _make_user([parent_perm], is_super=False)
        assert user.has_permission('product_view') is True

    def test_sensitive_user_permission_requires_super(self):
        """user_ 前缀敏感权限仅超级管理员可访问"""
        normal_user = _make_user([_make_perm('user_manage', parent_id=None)], is_super=False)
        assert normal_user.has_permission('user_manage') is False
        assert normal_user.has_permission('user_view') is False

        super_user = _make_user([], is_super=True)
        assert super_user.has_permission('user_manage') is True
        assert super_user.has_permission('user_view') is True

    def test_multiple_manage_permissions(self):
        """拥有多个 manage 权限时各自独立继承对应 view"""
        user = _make_user([
            _make_perm('product_manage', parent_id=None),
            _make_perm('order_manage', parent_id=None),
        ], is_super=False)
        assert user.has_permission('product_view') is True
        assert user.has_permission('order_view') is True
        assert user.has_permission('stock_view') is False


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

        users, _total = await get_users(mock_db)
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
        # Z09-R2：断言被 add 的用户字段（漏设 password/status 等错误会被抓住）
        added = mock_db.add.call_args.args[0]
        assert added.username == "newuser"
        assert added.password == "hashed"
        assert added.is_super is False
        assert added.status is True
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
    async def test_create_user_with_department(self, mock_db):
        """创建用户时写入部门"""
        from fastapi_app.services.user_service import create_user
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        with patch('fastapi_app.core.security.hash_password', return_value='hashed'):
            await create_user(mock_db, "newuser", "Test123!@", False, None, "业务部")
        added = mock_db.add.call_args.args[0]
        assert added.department == "业务部"

    @pytest.mark.asyncio
    async def test_update_user_department_none_keeps(self, mock_db, mock_user):
        """department 传 None 表示不修改（区别于空字符串清除）"""
        from fastapi_app.services.user_service import update_user
        mock_user.department = "仓库"
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_user
        mock_db.execute = AsyncMock(return_value=mock_result)

        await update_user(mock_db, 1, None, None, None, None)
        assert mock_user.department == "仓库"

    @pytest.mark.asyncio
    async def test_update_user_department_empty_clears(self, mock_db, mock_user):
        """department 传空字符串表示清除为 NULL"""
        from fastapi_app.services.user_service import update_user
        mock_user.department = "仓库"
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_user
        mock_db.execute = AsyncMock(return_value=mock_result)

        await update_user(mock_db, 1, None, None, None, "")
        assert mock_user.department is None

    @pytest.mark.asyncio
    async def test_update_user_department_changes(self, mock_db, mock_user):
        """换部门：写入新值"""
        from fastapi_app.services.user_service import update_user
        mock_user.department = "仓库"
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_user
        mock_db.execute = AsyncMock(return_value=mock_result)

        await update_user(mock_db, 1, None, None, None, "采购部")
        assert mock_user.department == "采购部"

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
        # Z09-R2：校验删除目标就是查出的用户，而不是任意对象
        from fastapi_app.shared_models import User
        mock_db.get.assert_awaited_once_with(User, 1)
        mock_db.delete.assert_awaited_once_with(mock_user)
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
    async def test_delete_user_with_approval_history_raises(self, mock_db, mock_user):
        """存在审批历史（任意状态、审批人或申请人）时拒绝删除（A-M26）。

        旧实现只统计 status=pending 的申请：已审批的历史在 flush 阶段撞
        NO ACTION 外键，直接把 500 抛给前端；而且完全没统计 approver_id。
        """
        from fastapi_app.services.user_service import delete_user
        mock_db.get = AsyncMock(return_value=mock_user)
        mock_db.scalar = AsyncMock(return_value=3)

        with pytest.raises(ValueError, match="审批历史"):
            await delete_user(mock_db, 1)
        mock_db.delete.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_delete_user_maps_integrity_error_to_value_error(self, mock_db, mock_user):
        """仍有其它 NO ACTION 外键时给可解释的 4xx，而不是 500（A-M26）。"""
        from sqlalchemy.exc import IntegrityError

        from fastapi_app.services.user_service import delete_user
        mock_db.get = AsyncMock(return_value=mock_user)
        mock_db.scalar = AsyncMock(return_value=0)
        mock_db.flush = AsyncMock(
            side_effect=IntegrityError('DELETE FROM "user"', {}, Exception('FK violation'))
        )

        with pytest.raises(ValueError, match="无法删除"):
            await delete_user(mock_db, 1)
        mock_db.rollback.assert_awaited()

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
        assert mock_user.permissions.clear.called
        # 真断言（2026-10-03 第七轮审计）：此前只断言 clear 被调用 —— 即使删掉
        # user_service 里的 `if permission.code in SENSITIVE_PERMISSIONS: continue`
        # 守卫，测试仍绿（假信心）。这里校验敏感权限 user_manage **未被授予**。
        appended = [c.args[0] for c in mock_user.permissions.append.call_args_list]
        assert sensitive_perm not in appended, '敏感权限 user_manage 不应被授予'
        assert mock_permission in appended, '非敏感权限应被授予'

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
        # db.info 必须是真实 dict（与 conftest.mock_db 一致），否则
        # db_transaction 的 db.info.pop(...) 会返回 coroutine 导致迭代失败
        db.info = {}
        return db

    @pytest.mark.asyncio
    async def test_list_users_success(self, client, mock_db, mock_current_user):
        mock_user = MagicMock()
        mock_user.id = 1
        mock_user.username = "admin"
        mock_user.is_super = True
        mock_user.status = True
        mock_user.factory = None
        mock_user.department = None
        # 真实 aware datetime：序列化已改走 fmt_business（astimezone 链），
        # MagicMock+strftime.return_value 夹具会断链返回裸 mock 导致 pydantic 拒收
        mock_user.create_time = datetime(2024, 1, 1, 0, 0, tzinfo=UTC)
        mock_user.permissions = []

        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = [mock_user]
        mock_result.unique.return_value = mock_result
        mock_result.scalars.return_value = mock_scalars
        mock_result.scalar_one.return_value = 1
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
    async def test_create_user_with_department(self, client, mock_db):
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        with patch('fastapi_app.core.security.hash_password', return_value='hashed'):
            response = await client.post("/api/v1/users/create", json={
                "username": "newuser", "password": "Test123!@", "is_super": False, "department": "采购部"
            })
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_create_user_with_invalid_department_rejected(self, client, mock_db):
        """非法部门值在 schema 层被拒（422），不会落库"""
        response = await client.post("/api/v1/users/create", json={
            "username": "newuser", "password": "Test123!@", "is_super": False, "department": "不存在的部门"
        })
        assert response.status_code == 422

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
        # 两次 scalar 依次为：待处理审批数、锁定订单数，均为 0 才允许删除
        mock_db.scalar = AsyncMock(side_effect=[0, 0])

        response = await client.delete("/api/v1/users/delete/2")
        assert response.status_code == 200
        assert "删除" in response.json()["message"]


# ==================== 权限缓存失效时机测试 ====================

class TestPermissionCacheInvalidationOrdering:
    """权限变更后，权限缓存必须在事务提交成功之后才失效。

    背景：原先在 db_transaction 块内（提交前）失效缓存，并发请求可能在提交前读到旧权限
    并回填缓存，而提交后不再失效，导致该用户最长在缓存 TTL 内持续被判权限不足（403）。
    回归口径：提交前缓存不得被清空，提交后必须被清空。
    """

    @pytest.mark.asyncio
    async def test_update_permissions_invalidates_cache_after_commit(self, client, mock_db):
        from fastapi_app.core.database import get_async_db
        from fastapi_app.core.deps import _PERMISSION_CACHE
        from fastapi_app.main import app

        user_id = 4242
        await _PERMISSION_CACHE.set(user_id, object())

        # 提交时刻的探针：记录缓存是否仍在、已登记的回调数
        cache_present_at_commit: list[bool] = []
        callbacks_at_commit: list[int] = []

        async def _spy_commit() -> None:
            cache_present_at_commit.append(await _PERMISSION_CACHE.get(user_id) is not None)
            callbacks_at_commit.append(len(mock_db.info.get('post_commit_callbacks', [])))

        mock_db.commit = AsyncMock(side_effect=_spy_commit)

        async def _override_db():
            yield mock_db

        app.dependency_overrides[get_async_db] = _override_db
        try:
            with patch(
                'fastapi_app.services.user_service.update_user_permissions',
                AsyncMock(return_value=MagicMock()),
            ):
                response = await client.post(
                    f'/api/v1/users/permission/{user_id}', json={'permission_ids': []},
                )
        finally:
            app.dependency_overrides.pop(get_async_db, None)
            await _PERMISSION_CACHE.pop(user_id)

        assert response.status_code == 200, response.text
        # 提交时刻：缓存仍在（失效未提前），且回调已登记
        assert cache_present_at_commit == [True], '提交前不得失效权限缓存'
        assert callbacks_at_commit == [1], '提交时应已登记恰好一个 post-commit 回调'
        # 提交成功后：缓存已被清除
        assert await _PERMISSION_CACHE.get(user_id) is None, '提交后必须失效权限缓存'
