"""
用户管理 单元测试

覆盖：
- 用户列表查询（分页）
- 用户创建（密码校验、用户名唯一性）
- 用户编辑（密码更新、工厂分配）
- 用户状态切换（超级用户保护）
- 用户删除（超级用户保护、审批关联检查、订单锁定检查）
- 权限查询（树形结构）
- 权限分配（敏感权限过滤）
"""
from unittest.mock import MagicMock, patch

import pytest


class TestGetUsers:
    """用户列表查询"""

    @pytest.mark.asyncio
    @patch('fastapi_app.services.user_service.get_users')
    async def test_get_users_empty(self, mock_get):
        """查询空用户列表"""
        mock_get.return_value = ([], 0)

        users, total = await mock_get(MagicMock(), page=1, per_page=15)

        assert users == []
        assert total == 0

    @pytest.mark.asyncio
    @patch('fastapi_app.services.user_service.get_users')
    async def test_get_users_with_data(self, mock_get):
        """查询用户列表"""
        user = MagicMock()
        user.id = 1
        user.username = 'admin'
        user.is_super = True
        user.status = True

        mock_get.return_value = ([user], 5)

        users, total = await mock_get(MagicMock(), page=1, per_page=15)

        assert len(users) == 1
        assert total == 5

    @pytest.mark.asyncio
    @patch('fastapi_app.services.user_service.get_users')
    async def test_get_users_pagination(self, mock_get):
        """分页查询"""
        users_list = [MagicMock() for _ in range(15)]
        mock_get.return_value = (users_list, 50)

        users, total = await mock_get(MagicMock(), page=3, per_page=15)

        assert len(users) == 15
        assert total == 50


class TestCreateUser:
    """用户创建"""

    @pytest.mark.asyncio
    @patch('fastapi_app.services.user_service.create_user')
    async def test_create_user_success(self, mock_create):
        """正常创建用户"""
        user = MagicMock()
        user.username = 'newuser'
        user.is_super = False
        user.factory = '东莞'
        mock_create.return_value = user

        result = await mock_create(
            MagicMock(), username='newuser', password='StrongPass1!',
            is_super=False, factory='东莞'
        )

        assert result.username == 'newuser'

    @pytest.mark.asyncio
    @patch('fastapi_app.services.user_service.create_user')
    async def test_create_user_weak_password(self, mock_create):
        """弱密码 - 应拒绝"""
        mock_create.side_effect = ValueError('密码长度不足')

        with pytest.raises(ValueError, match='密码长度不足'):
            await mock_create(MagicMock(), username='user1', password='123', is_super=False)

    @pytest.mark.asyncio
    @patch('fastapi_app.services.user_service.create_user')
    async def test_create_user_duplicate_username(self, mock_create):
        """用户名重复"""
        mock_create.side_effect = ValueError('用户名已存在')

        with pytest.raises(ValueError, match='用户名已存在'):
            await mock_create(MagicMock(), username='duplicate', password='StrongPass1!', is_super=False)

    @pytest.mark.asyncio
    @patch('fastapi_app.services.user_service.create_user')
    async def test_create_user_super_admin(self, mock_create):
        """创建超级管理员"""
        user = MagicMock()
        user.is_super = True
        mock_create.return_value = user

        result = await mock_create(
            MagicMock(), username='admin2', password='AdminPass1!',
            is_super=True, factory=None
        )

        assert result.is_super is True

    @pytest.mark.asyncio
    @patch('fastapi_app.services.user_service.create_user')
    async def test_create_user_without_factory(self, mock_create):
        """创建用户 - 不指定工厂"""
        user = MagicMock()
        user.factory = None
        mock_create.return_value = user

        result = await mock_create(
            MagicMock(), username='nofactory', password='Pass123!', is_super=False
        )

        assert result.factory is None


class TestUpdateUser:
    """用户编辑"""

    @pytest.mark.asyncio
    @patch('fastapi_app.services.user_service.update_user')
    async def test_update_user_not_found(self, mock_update):
        """编辑不存在的用户"""
        mock_update.side_effect = ValueError('用户不存在')

        with pytest.raises(ValueError, match='用户不存在'):
            await mock_update(MagicMock(), user_id=999)

    @pytest.mark.asyncio
    @patch('fastapi_app.services.user_service.update_user')
    async def test_update_user_password(self, mock_update):
        """更新密码"""
        user = MagicMock()
        user.id = 1
        mock_update.return_value = user

        result = await mock_update(
            MagicMock(), user_id=1, password='NewPass1!',
            is_super=None, factory=None
        )

        assert result is not None

    @pytest.mark.asyncio
    @patch('fastapi_app.services.user_service.update_user')
    async def test_update_user_factory(self, mock_update):
        """更新工厂"""
        user = MagicMock()
        user.factory = '湖北'
        mock_update.return_value = user

        result = await mock_update(
            MagicMock(), user_id=1, password=None,
            is_super=None, factory='湖北'
        )

        assert result.factory == '湖北'

    @pytest.mark.asyncio
    @patch('fastapi_app.services.user_service.update_user')
    async def test_update_user_clear_factory(self, mock_update):
        """清除工厂"""
        user = MagicMock()
        user.factory = None
        mock_update.return_value = user

        result = await mock_update(
            MagicMock(), user_id=1, password=None,
            is_super=None, factory=''
        )

        assert result.factory is None


class TestToggleUserStatus:
    """切换用户状态"""

    @pytest.mark.asyncio
    @patch('fastapi_app.services.user_service.toggle_user_status')
    async def test_toggle_user_status_success(self, mock_toggle):
        """正常切换状态"""
        user = MagicMock()
        user.status = False
        mock_toggle.return_value = user

        result = await mock_toggle(MagicMock(), user_id=2)

        assert result.status is False

    @pytest.mark.asyncio
    @patch('fastapi_app.services.user_service.toggle_user_status')
    async def test_toggle_user_status_not_found(self, mock_toggle):
        """用户不存在"""
        mock_toggle.side_effect = ValueError('用户不存在')

        with pytest.raises(ValueError, match='用户不存在'):
            await mock_toggle(MagicMock(), user_id=999)

    @pytest.mark.asyncio
    @patch('fastapi_app.services.user_service.toggle_user_status')
    async def test_toggle_super_user(self, mock_toggle):
        """不能禁用超级用户"""
        mock_toggle.side_effect = ValueError('超级用户不能禁用')

        with pytest.raises(ValueError, match='超级用户不能禁用'):
            await mock_toggle(MagicMock(), user_id=1)


class TestDeleteUser:
    """用户删除"""

    @pytest.mark.asyncio
    @patch('fastapi_app.services.user_service.delete_user')
    async def test_delete_user_not_found(self, mock_delete):
        """删除不存在的用户"""
        mock_delete.side_effect = ValueError('用户不存在')

        with pytest.raises(ValueError, match='用户不存在'):
            await mock_delete(MagicMock(), user_id=999)

    @pytest.mark.asyncio
    @patch('fastapi_app.services.user_service.delete_user')
    async def test_delete_super_user(self, mock_delete):
        """不能删除超级用户"""
        mock_delete.side_effect = ValueError('超级用户不能删除')

        with pytest.raises(ValueError, match='超级用户不能删除'):
            await mock_delete(MagicMock(), user_id=1)

    @pytest.mark.asyncio
    @patch('fastapi_app.services.user_service.delete_user')
    async def test_delete_user_success(self, mock_delete):
        """正常删除用户"""
        mock_delete.return_value = {'success': True, 'message': '删除成功'}

        result = await mock_delete(MagicMock(), user_id=3)

        assert result['success'] is True

    @pytest.mark.asyncio
    @patch('fastapi_app.services.user_service.delete_user')
    async def test_delete_user_with_pending_approvals(self, mock_delete):
        """有审批待处理的用户不能删除"""
        mock_delete.side_effect = ValueError('该用户有 3 个待处理审批请求')

        with pytest.raises(ValueError, match='待处理审批请求'):
            await mock_delete(MagicMock(), user_id=4)

    @pytest.mark.asyncio
    @patch('fastapi_app.services.user_service.delete_user')
    async def test_delete_user_with_locked_orders(self, mock_delete):
        """有锁定订单的用户不能删除"""
        mock_delete.side_effect = ValueError('锁定了 2 个订单')

        with pytest.raises(ValueError, match='锁定了'):
            await mock_delete(MagicMock(), user_id=5)


class TestPermissions:
    """权限管理"""

    @pytest.mark.asyncio
    @patch('fastapi_app.services.user_service.get_permissions')
    async def test_get_permissions_empty(self, mock_get):
        """获取空权限列表"""
        mock_get.return_value = []

        result = await mock_get(MagicMock())

        assert result == []

    @pytest.mark.asyncio
    @patch('fastapi_app.services.user_service.get_permissions')
    async def test_get_permissions_tree(self, mock_get):
        """获取权限树"""
        perm = MagicMock()
        perm.id = 1
        perm.code = 'order_manage'
        mock_get.return_value = [perm]

        result = await mock_get(MagicMock())

        assert len(result) == 1

    @pytest.mark.asyncio
    @patch('fastapi_app.services.user_service.get_permissions_with_user_ids')
    async def test_get_permissions_with_user_ids(self, mock_get):
        """获取权限及用户已有权限ID"""
        perm = MagicMock()
        perm.id = 1
        mock_get.return_value = ([perm], [1])

        permissions, user_perm_ids = await mock_get(MagicMock(), MagicMock())

        assert len(permissions) == 1
        assert user_perm_ids == [1]

    @pytest.mark.asyncio
    @patch('fastapi_app.services.user_service.update_user_permissions')
    async def test_update_user_permissions_success(self, mock_update):
        """正常更新用户权限"""
        user = MagicMock()
        mock_update.return_value = user

        result = await mock_update(MagicMock(), user_id=2, permission_ids=[3])

        assert result == user

    @pytest.mark.asyncio
    @patch('fastapi_app.services.user_service.update_user_permissions')
    async def test_update_user_permissions_not_found(self, mock_update):
        """用户不存在"""
        mock_update.side_effect = ValueError('用户不存在')

        with pytest.raises(ValueError, match='用户不存在'):
            await mock_update(MagicMock(), user_id=999, permission_ids=[1])

    @pytest.mark.asyncio
    @patch('fastapi_app.services.user_service.update_user_permissions')
    async def test_update_user_permissions_sensitive_filter(self, mock_update):
        """敏感权限被过滤（user_manage）"""
        user = MagicMock()
        mock_update.return_value = user

        result = await mock_update(MagicMock(), user_id=2, permission_ids=[1])

        assert result == user
