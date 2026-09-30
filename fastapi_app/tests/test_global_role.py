"""全局角色字典测试。

覆盖：
- ``role_service`` 层：create 名称唯一（``lower(trim(name))``）/ rename / delete 被引用保护；
- 端点层：``GET/POST/PUT/DELETE /purchase-center/roles``，其中删除被引用角色返回 **409**
  且文案含引用数（REQ-P0-02 / Q-02）。
"""
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio

from fastapi_app.api.v1.endpoints.purchase_center.role_routes import get_role_service
from fastapi_app.main import app
from fastapi_app.services.product import role_service


def _first_result(value):
    """构造 db.execute(...).scalars().first() == value 的结果桩。"""
    res = MagicMock()
    res.scalars.return_value.first.return_value = value
    return res


def _all_result(values):
    res = MagicMock()
    res.scalars.return_value.all.return_value = list(values)
    return res


# ============================================================
# Service 层
# ============================================================

class TestRoleServiceCRUD:
    async def test_create_trims_and_returns_item(self, mock_db):
        mock_db.execute = AsyncMock(return_value=_first_result(None))
        item = await role_service.create_role(mock_db, '  爸爸  ', 'tester')
        assert item['name'] == '爸爸'
        assert 'id' in item

    async def test_create_rejects_duplicate_lower(self, mock_db):
        existing = MagicMock()
        existing.id = 5
        existing.name = '爸爸'
        mock_db.execute = AsyncMock(return_value=_first_result(existing))
        with pytest.raises(role_service.RoleNameConflictError, match='已存在'):
            await role_service.create_role(mock_db, '爸爸', 'tester')

    async def test_create_rejects_empty_name(self, mock_db):
        with pytest.raises(role_service.RoleNameConflictError, match='不能为空'):
            await role_service.create_role(mock_db, '   ', 'tester')

    async def test_list_roles_shapes(self, mock_db):
        r1, r2 = MagicMock(), MagicMock()
        r1.id, r1.name = 1, '爸爸'
        r2.id, r2.name = 2, '妈妈'
        mock_db.execute = AsyncMock(return_value=_all_result([r1, r2]))
        roles = await role_service.list_roles(mock_db)
        assert roles == [
            {'id': 1, 'global_role_id': None, 'name': '爸爸'},
            {'id': 2, 'global_role_id': None, 'name': '妈妈'},
        ]

    async def test_rename_updates_name(self, mock_db):
        role = MagicMock()
        role.id, role.name = 3, '旧名'
        mock_db.get = AsyncMock(return_value=role)
        mock_db.execute = AsyncMock(side_effect=[
            _first_result(None),   # _find_by_key：无冲突
            MagicMock(),           # apply_global_rename 的 UPDATE
        ])
        item = await role_service.rename_role(mock_db, 3, '新名', 'tester')
        assert item['name'] == '新名'
        assert role.name == '新名'

    async def test_rename_conflict(self, mock_db):
        role = MagicMock()
        role.id, role.name = 3, '旧名'
        other = MagicMock()
        other.id, other.name = 4, '新名'
        mock_db.get = AsyncMock(return_value=role)
        mock_db.execute = AsyncMock(return_value=_first_result(other))
        with pytest.raises(role_service.RoleNameConflictError):
            await role_service.rename_role(mock_db, 3, '新名', 'tester')

    async def test_rename_missing_role(self, mock_db):
        mock_db.get = AsyncMock(return_value=None)
        with pytest.raises(role_service.RoleNotFoundError):
            await role_service.rename_role(mock_db, 999, '新名', 'tester')

    async def test_delete_referenced_is_rejected_with_count(self, mock_db):
        role = MagicMock()
        role.id, role.name = 7, '爸爸'
        mock_db.get = AsyncMock(return_value=role)
        mock_db.scalar = AsyncMock(return_value=2)   # 被 2 个产品引用
        with pytest.raises(role_service.RoleReferencedError) as exc:
            await role_service.delete_role(mock_db, 7, 'tester')
        assert '2' in str(exc.value)
        assert '无法删除' in str(exc.value)
        mock_db.delete.assert_not_called()

    async def test_delete_unreferenced_succeeds(self, mock_db):
        role = MagicMock()
        role.id, role.name = 7, '孤儿角色'
        mock_db.get = AsyncMock(return_value=role)
        mock_db.scalar = AsyncMock(return_value=0)
        message = await role_service.delete_role(mock_db, 7, 'tester')
        assert '已删除' in message
        mock_db.delete.assert_awaited_once_with(role)


# ============================================================
# 端点层（路由 + 状态码映射）
# ============================================================

class _FakeRoleService:
    """可注入容器 override 的假服务，用于校验端点契约与状态码映射。"""

    def __init__(self, *, roles=None, delete_exc=None, create_exc=None):
        self._roles = roles or []
        self._delete_exc = delete_exc
        self._create_exc = create_exc

    async def list_roles(self, db):
        return self._roles

    async def create_role(self, db, name, username='system'):
        if self._create_exc:
            raise self._create_exc
        return {'id': 1, 'global_role_id': None, 'name': name}

    async def rename_role(self, db, role_id, name, username='system'):
        return {'id': role_id, 'global_role_id': None, 'name': name}

    async def delete_role(self, db, role_id, username='system'):
        if self._delete_exc:
            raise self._delete_exc
        return f'角色 {role_id} 已删除'


@pytest.fixture
def role_override():
    """用 FastAPI dependency_overrides 注入角色服务替身（原 core.container 已删除）。"""
    def _install(fake):
        app.dependency_overrides[get_role_service] = lambda: fake
        return fake

    yield _install
    app.dependency_overrides.pop(get_role_service, None)


class TestRoleEndpoints:
    @pytest_asyncio.fixture(autouse=True)
    async def _csrf_origin(self, client):
        """端点测试显式携带「允许的 Origin」。

        本机为生产环境，CSRF cookie 以 ``Secure`` 下发，纯 ``http://test`` 测试客户端
        不会回传该 cookie，导致 Bearer 请求落入「Origin 校验」分支（历史全仓非 GET
        端点测试同因失败）。显式提供允许的本地 Origin 使 Bearer 校验通过，聚焦验证
        角色端点的状态码映射（200/400/404/409）。
        """
        client.headers['Origin'] = 'http://localhost'
        yield

    async def test_list_roles(self, client, role_override):
        role_override(_FakeRoleService(roles=[{'id': 1, 'global_role_id': None, 'name': '爸爸'}]))
        resp = await client.get('/api/v1/purchase-center/roles')
        assert resp.status_code == 200
        body = resp.json()
        assert body['success'] is True
        assert body['roles'][0]['name'] == '爸爸'

    async def test_create_role(self, client, role_override):
        role_override(_FakeRoleService())
        resp = await client.post('/api/v1/purchase-center/roles', json={'name': '新角色'})
        assert resp.status_code == 200
        assert resp.json()['role']['name'] == '新角色'

    async def test_create_conflict_returns_400(self, client, role_override):
        role_override(_FakeRoleService(
            create_exc=role_service.RoleNameConflictError('角色「爸爸」已存在（名称比较不区分大小写）'),
        ))
        resp = await client.post('/api/v1/purchase-center/roles', json={'name': '爸爸'})
        assert resp.status_code == 400

    async def test_rename_role(self, client, role_override):
        role_override(_FakeRoleService())
        resp = await client.put('/api/v1/purchase-center/roles/1', json={'name': '新名'})
        assert resp.status_code == 200
        assert resp.json()['role']['name'] == '新名'

    async def test_delete_referenced_returns_409_with_count(self, client, role_override):
        role_override(_FakeRoleService(
            delete_exc=role_service.RoleReferencedError('角色「爸爸」已被 3 个产品关联，无法删除；请先在相关产品中解绑'),
        ))
        resp = await client.delete('/api/v1/purchase-center/roles/1')
        assert resp.status_code == 409
        assert '3' in resp.json()['detail']

    async def test_delete_unreferenced_returns_200(self, client, role_override):
        role_override(_FakeRoleService())
        resp = await client.delete('/api/v1/purchase-center/roles/1')
        assert resp.status_code == 200
