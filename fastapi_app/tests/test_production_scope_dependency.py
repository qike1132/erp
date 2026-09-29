"""范围依赖：空集必须 403（fail-open 是最危险的失效方向）"""
import pytest
from fastapi import HTTPException

from fastapi_app.core.deps import (
    get_current_user_with_permissions,
    resolve_production_view_scope,
    resolve_production_write_scope,
)
from fastapi_app.core.production_scope import (
    AGGREGATE_VIEW_CODE,
    manage_code,
    view_code,
)
from fastapi_app.shared_models import Permission, User


def _user(codes, *, is_super=False):
    user = User(username='t_user', password='x')
    user.is_super = is_super
    user.permissions = [_perm(c) for c in codes]
    return user


def _perm(code):
    """真实游离态 Permission。

    不能用 MagicMock(spec=Permission)：user.permissions 关系带 backref='users'，
    赋值时会访问每个成员的 _sa_instance_state，Mock 直接 AttributeError
    （同 test_production_scope.py / test_purchase_center_permission_alignment.py 的做法）。
    用真实实例还让 User.has_permission 真正跑起来，测试才不是空转。
    """
    perm = Permission(name=code, code=code)
    perm.parent_id = None
    return perm


class TestViewScopeDependency:
    async def test_aggregate_user_gets_none(self):
        assert await resolve_production_view_scope(_user([AGGREGATE_VIEW_CODE])) is None

    async def test_dept_user_gets_that_department(self):
        assert await resolve_production_view_scope(_user([view_code('filling')])) == {'filling'}

    async def test_empty_scope_raises_403(self):
        with pytest.raises(HTTPException) as exc_info:
            await resolve_production_view_scope(_user([]))
        assert exc_info.value.status_code == 403


class TestWriteScopeDependency:
    async def test_dept_manage_user_gets_that_department(self):
        assert await resolve_production_write_scope(_user([manage_code('packaging')])) == {'packaging'}

    async def test_view_only_user_gets_403(self):
        with pytest.raises(HTTPException) as exc_info:
            await resolve_production_write_scope(_user([view_code('packaging')]))
        assert exc_info.value.status_code == 403


class TestCurrentUserAlias:
    async def test_alias_returns_same_user_object(self):
        user = _user([AGGREGATE_VIEW_CODE])
        assert await get_current_user_with_permissions(user) is user
