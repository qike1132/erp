"""湖北外发「工序预设」细粒度权限码回归测试（缺陷 #5）。

背景：工序预设的增删改端点原先只认 outsource_manage，而该码被
scripts/add_outsource_nav.py 历史上**按 beile_order_view / order_manage /
stockin_manage 批量授予**（贝乐因此持有），等于「能看湖北订单」就「能删工序预设」。
修复：预设写端点改认 outsource_preset_manage（本文件断言端点依赖），且该码必须是
顶层权限行（不挂 outsource_manage 之下），否则父权限的 children 继承会把旧授权
原样放行，拆码等于白拆（本文件第二个用例把这条继承规则钉死）。
"""
from __future__ import annotations

from pathlib import Path

from fastapi_app.api.v1.endpoints.outsource import router
from fastapi_app.shared_models import Permission, User

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SEED_NAV = _REPO_ROOT / 'scripts' / 'seed_nav.py'


def _route_permission(suffix: str, method: str = 'POST') -> str | None:
    """取出该路由声明的权限点名称（require_permission 挂的 __permission_codes__）。

    只认单码声明：多码的 require_any_permission 返回 None，这样路由一旦从单码放宽成
    「任一码」，下面的断言就会失败（与 tests/test_outsource.py 同一手法）。
    """
    for route in router.routes:
        if not getattr(route, 'path', '').endswith(suffix) or method not in route.methods:
            continue
        for dep in route.dependant.dependencies:
            codes = getattr(dep.call, '__permission_codes__', None)
            if codes:
                return codes[0] if len(codes) == 1 else None
    return None


def test_preset_write_endpoints_require_preset_manage():
    """工序预设的增删改端点必须只认 outsource_preset_manage。

    拦哪种错：只改了部分端点，漏掉的那个仍认 outsource_manage（贝乐仍可删预设）。
    """
    assert _route_permission('/process-types', 'POST') == 'outsource_preset_manage'
    assert _route_permission('/process-types/batch', 'POST') == 'outsource_preset_manage'
    assert _route_permission('/process-types/{pt_id}', 'PUT') == 'outsource_preset_manage'
    assert _route_permission('/process-types/{pt_id}', 'DELETE') == 'outsource_preset_manage'
    # 订单级删除工序 **不** 收窄到预设码：删的是某张订单的外发工序（订单级写操作），
    # 不是工序预设维护（评审 F10）。只持 outsource_manage 的集成不该突然 403。
    assert _route_permission('/processes/{process_id}', 'DELETE') == 'outsource_manage'


def test_outsource_manage_alone_is_rejected():
    """只持 outsource_manage 的账号（如贝乐）不得通过预设写端点。

    同时用「假设挂成子权限」的对照说明为什么登记处必须写成顶层行：
    User.has_permission 对父权限的 children 默认放行。
    """
    manage = Permission(id=1, name='湖北外发', code='outsource_manage', parent_id=None)
    holder = User(id=1, username='贝乐', password='x')
    holder.permissions.append(manage)

    assert holder.has_permission('outsource_manage') is True
    # 拆码的核心断言：旧码不派生新码
    assert holder.has_permission('outsource_preset_manage') is False

    # 对照 + 兜底（评审 F8）：即使有人把它挂成 outsource_manage 的子权限，
    # NO_MANAGE_INHERIT 也会挡住父码的 children 无条件继承，缺陷不会原样复活。
    from fastapi_app.shared_models.user import NO_MANAGE_INHERIT

    assert 'outsource_preset_manage' in NO_MANAGE_INHERIT, (
        '该码必须进 NO_MANAGE_INHERIT：否则 parent_id 写错就会经 children 继承放行'
    )
    manage.children.append(
        Permission(id=2, name='维护外发工序预设', code='outsource_preset_manage', parent_id=1)
    )
    assert holder.has_permission('outsource_preset_manage') is False, (
        'NO_MANAGE_INHERIT 里的码不能被父权限的 children 继承放行'
    )


def test_preset_permission_registered_as_top_level_seed():
    """新权限码必须登记在种子脚本里，且是顶层行（parent_id=None / is_nav=False）。"""
    text = _SEED_NAV.read_text(encoding='utf-8')
    line = next(
        (ln for ln in text.splitlines() if "'code': 'outsource_preset_manage'" in ln),
        None,
    )
    assert line is not None, 'outsource_preset_manage 未登记到 scripts/seed_nav.py'
    assert "'is_nav': False" in line, '权限码不应出现在侧边栏导航里'
    assert "'section': None" in line, '顶层按钮级权限码不隶属任何板块'
