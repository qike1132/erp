"""生产报表部门范围解析（纯函数，不碰数据库）"""
from fastapi_app.core.production_scope import (
    AGGREGATE_MANAGE_CODE,
    AGGREGATE_VIEW_CODE,
    PRODUCTION_DEPARTMENTS,
    dept_permission_rows,
    manage_code,
    narrow_departments,
    production_scope_of,
    view_code,
)
from fastapi_app.shared_models import Permission, User


def _make_user(codes, *, is_super=False):
    """构造真实 User 实例，权限用游离态的真实 Permission 顶替（不入库）。

    不能用 MagicMock(spec=Permission)：user.permissions 关系带 backref='users'，
    赋值时会访问每个成员的 _sa_instance_state，Mock 直接 AttributeError
    （同 test_purchase_center_permission_alignment.py 的既有做法：真实 Permission 游离实例）。
    """
    user = User(username='t_user', password='x')
    user.is_super = is_super
    user.permissions = [
        _make_perm(code) for code in codes
    ]
    return user


def _make_perm(code, parent_id=None):
    perm = Permission(name=code, code=code)
    perm.parent_id = parent_id
    return perm


class TestCodeNaming:
    def test_dept_permission_rows_covers_three_depts_both_kinds(self):
        rows = dept_permission_rows()
        assert len(rows) == 6
        codes = {code for code, _ in rows}
        assert codes == {
            'production_summary_view_filling',
            'production_summary_view_handcraft',
            'production_summary_view_packaging',
            'production_summary_manage_filling',
            'production_summary_manage_handcraft',
            'production_summary_manage_packaging',
        }

    def test_code_helpers_match_rows(self):
        for dept in PRODUCTION_DEPARTMENTS:
            assert view_code(dept) in {c for c, _ in dept_permission_rows()}
            assert manage_code(dept) in {c for c, _ in dept_permission_rows()}

    def test_every_row_has_chinese_name(self):
        for code, name in dept_permission_rows():
            assert name and name != code


class TestProductionScopeOf:
    def test_aggregate_view_code_means_all_departments(self):
        user = _make_user([AGGREGATE_VIEW_CODE])
        assert production_scope_of(user, write=False) is None

    def test_aggregate_manage_code_means_all_departments_for_read_too(self):
        # 模型自带规则：顶级 xxx_manage 通过 xxx_view 检查
        user = _make_user([AGGREGATE_MANAGE_CODE])
        assert production_scope_of(user, write=False) is None
        assert production_scope_of(user, write=True) is None

    def test_single_view_code_yields_that_department_only(self):
        user = _make_user([view_code('filling')])
        assert production_scope_of(user, write=False) == {'filling'}

    def test_two_view_codes_yield_two_departments(self):
        user = _make_user([view_code('filling'), view_code('packaging')])
        assert production_scope_of(user, write=False) == {'filling', 'packaging'}

    def test_manage_code_grants_read_on_same_department(self):
        # 关键：User.has_permission 的 manage→view 继承只对顶级码生效，
        # 部门级 manage 码不会让 view 码通过，因此必须由解析器补上。
        user = _make_user([manage_code('handcraft')])
        assert user.has_permission(view_code('handcraft')) is False
        assert production_scope_of(user, write=False) == {'handcraft'}

    def test_view_code_does_not_grant_write(self):
        user = _make_user([view_code('filling')])
        assert production_scope_of(user, write=True) == set()

    def test_no_codes_yields_empty_set_not_none(self):
        # 空集与 None 的区分是安全边界（见 Review Focus #2），必须锁住
        user = _make_user([])
        assert production_scope_of(user, write=False) == set()
        assert production_scope_of(user, write=False) is not None

    def test_super_user_gets_everything(self):
        user = _make_user([], is_super=True)
        assert production_scope_of(user, write=False) is None


class TestNarrowDepartments:
    def test_unscoped_user_keeps_requested_department(self):
        assert narrow_departments('filling', None) == {'filling'}

    def test_unscoped_user_without_request_means_no_filter(self):
        assert narrow_departments('', None) is None

    def test_scoped_user_without_request_gets_whole_scope(self):
        assert narrow_departments('', {'filling', 'packaging'}) == {'filling', 'packaging'}

    def test_requested_department_inside_scope_is_honoured(self):
        assert narrow_departments('filling', {'filling', 'packaging'}) == {'filling'}

    def test_requested_department_outside_scope_falls_back_to_scope(self):
        # 忽略而非 403：前端状态残留不应让整页报错
        assert narrow_departments('packaging', {'filling'}) == {'filling'}

    def test_invalid_department_for_unscoped_user_passes_through(self):
        # 非法值不应 500：交给查询返回空集
        assert narrow_departments('xxx', None) == {'xxx'}
