"""customer_sampling（板房打样）读接口的权限回归（P0-6(a)）。

背景：/api/v1/pattern-room 路由树原先只挂 Depends(get_current_user_id)，
任何**登录**用户（含与打样无关的岗位）都能读到全部打样项目/部位/版本/变更日志。

修复口径：**按端点**加 require_any_permission('customer_sampling_view',
'customer_sampling_manage')。前端 PatternRoomView.vue 的 canManage 只认
customer_sampling_manage，故持有它的角色继续可读；将来新增只读角色只发
customer_sampling_view 即可 —— 不整树放开、不整树封死。
"""
import pytest
from starlette.requests import Request

from fastapi_app.api.v1.endpoints import customer_sampling as cs
from fastapi_app.core.deps import _get_user_with_permissions
from fastapi_app.main import app
from fastapi_app.shared_models import Permission, User

_READ_CODES = ('customer_sampling_view', 'customer_sampling_manage')
_PREFIX = '/api/v1/pattern-room'

# (router 内的相对路径, 测试用 HTTP 路径) —— 与下方列出的读端点一一对应
_GET_ROUTES = [
    ('/grouped-list', '/api/v1/pattern-room/grouped-list'),
    ('/projects', '/api/v1/pattern-room/projects'),
    ('/projects/{project_id}', '/api/v1/pattern-room/projects/1'),
    ('/projects/{project_id}/parts', '/api/v1/pattern-room/projects/1/parts'),
    ('/projects/{project_id}/versions', '/api/v1/pattern-room/projects/1/versions'),
    ('/versions/{version_id}', '/api/v1/pattern-room/versions/1'),
    ('/projects/{project_id}/change-logs', '/api/v1/pattern-room/projects/1/change-logs'),
    ('/projects/{project_id}/parts-by-version', '/api/v1/pattern-room/projects/1/parts-by-version'),
    ('/projects/{project_id}/roles', '/api/v1/pattern-room/projects/1/roles'),
    ('/part-field-candidates', '/api/v1/pattern-room/part-field-candidates'),
]
_HTTP_PATHS = [http for _rel, http in _GET_ROUTES]


def _make_user(codes):
    """构造仅持有这些权限码的普通用户。"""
    user = User(username='tmp', password='x', is_super=False, status=True)
    user.permissions = [Permission(name=c, code=c) for c in codes]
    return user


def _use_user_with(codes) -> None:
    """把当前请求的用户替换为「仅持有这些权限码」的普通用户。"""
    async def override():
        return _make_user(codes)
    app.dependency_overrides[_get_user_with_permissions] = override


def _router_get(rel_path):
    """在 customer_sampling 子路由里按相对路径找 GET 路由。

    不遍历 app.routes：FastAPI 0.137 的 include_router 是惰性的
    （app.routes 里是 _IncludedRouter，需 effective_candidates() 才展开），
    直接查子路由更稳。
    """
    for route in cs.router.routes:
        if getattr(route, 'path', None) == rel_path and 'GET' in (getattr(route, 'methods', None) or set()):
            return route
    raise AssertionError(f'customer_sampling 子路由里找不到 GET {rel_path}')


def _read_checkers(route):
    """取出路由上权限依赖声明的权限码 -> [(callable, 权限码元组)]。

    权限码从依赖函数上的 ``__permission_codes__`` 读取（core/deps.py 的工厂挂载），
    不再扒 ``__closure__`` 单元格——闭包单元格的顺序/存在性是 CPython 实现细节，
    工厂一改即失效（这正是该属性存在的理由）。
    """
    found = []
    for dep in getattr(route.dependant, 'dependencies', []):
        call = getattr(dep, 'call', None)
        codes = getattr(call, '__permission_codes__', None)
        if codes:
            found.append((call, codes))
    return found


def _fake_request():
    return Request({
        'type': 'http',
        'http_version': '1.1',
        'method': 'GET',
        'scheme': 'http',
        'path': '/api/v1/pattern-room/projects',
        'raw_path': b'/api/v1/pattern-room/projects',
        'query_string': b'',
        'root_path': '',
        'headers': [],
        'client': ('10.1.2.3', 4711),
        'server': ('testserver', 80),
    })


def test_router_still_exposes_exactly_the_listed_read_endpoints():
    """护栏：本用例覆盖的就是 _GET_ROUTES 点名的读端点，增删读端点必须同步改测试。"""
    gets = sorted(
        route.path
        for route in cs.router.routes
        if 'GET' in (getattr(route, 'methods', None) or set())
    )
    assert gets == sorted(rel for rel, _http in _GET_ROUTES), f'读端点集合变了: {gets}'


@pytest.mark.parametrize('rel_path,http_path', _GET_ROUTES)
def test_every_get_route_is_bound_to_read_permission(rel_path, http_path):
    """全部列出的 GET 都必须挂 require_any_permission(读码, 管理码)。"""
    checkers = _read_checkers(_router_get(rel_path))
    assert checkers, f'{rel_path} 上没有 require_any_permission 依赖（读接口对任何登录用户裸奔）'
    for _call, names in checkers:
        assert set(names) == set(_READ_CODES), f'{rel_path} 的读权限码不匹配: {names}'


@pytest.mark.asyncio
@pytest.mark.parametrize('http_path', _HTTP_PATHS)
async def test_unrelated_permission_is_denied(client, http_path):
    """持无关权限（供应商管理）的账号必须 403，避免放行口径过宽。"""
    _use_user_with(['supplier_manage'])
    resp = await client.get(http_path)
    assert resp.status_code == 403, f'{http_path} 未拦截无权限账号: {resp.status_code} {resp.text[:200]}'


@pytest.mark.asyncio
@pytest.mark.parametrize('code', ['customer_sampling_manage', 'customer_sampling_view'])
@pytest.mark.parametrize('rel_path,http_path', _GET_ROUTES)
async def test_read_permission_holders_pass_the_gate(rel_path, http_path, code):
    """持有管理码（现有角色）或只读码（将来新增只读角色）都要能过权限门。"""
    checkers = _read_checkers(_router_get(rel_path))
    assert checkers, f'{rel_path} 缺少读权限依赖'
    user = _make_user([code])
    for call, _names in checkers:
        assert await call(_fake_request(), user) is user, f'{rel_path} 拒绝了持有 {code} 的用户'
