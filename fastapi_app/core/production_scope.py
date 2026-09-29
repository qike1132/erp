"""生产报表的部门范围定义与解析

单一事实来源：权限码命名、范围解析、请求参数收窄。
种子脚本（scripts/init_production_dept_permissions.py）与运行时解析器共用本模块，
避免两边各写一份字符串导致漂移。

范围语义（务必区分）：
    None  —— 全部部门（持有聚合码）
    set() —— 无任何可见部门，调用方应拒绝请求（不可当作"不过滤"）
"""
from fastapi_app.shared_models import User

PRODUCTION_DEPARTMENTS: tuple[str, ...] = ('filling', 'handcraft', 'packaging')

DEPARTMENT_LABELS: dict[str, str] = {
    'filling': '充棉部',
    'handcraft': '手工部',
    'packaging': '包装部',
}

AGGREGATE_VIEW_CODE = 'production_summary_view'
AGGREGATE_MANAGE_CODE = 'production_summary_manage'


def view_code(department: str) -> str:
    """部门只读权限码"""
    return f'{AGGREGATE_VIEW_CODE}_{department}'


def manage_code(department: str) -> str:
    """部门可写权限码"""
    return f'{AGGREGATE_MANAGE_CODE}_{department}'


def dept_permission_rows() -> list[tuple[str, str]]:
    """种子脚本要写入的 (code, name) 列表，共 6 行"""
    rows: list[tuple[str, str]] = []
    for dept in PRODUCTION_DEPARTMENTS:
        label = DEPARTMENT_LABELS[dept]
        rows.append((view_code(dept), f'生产报表-{label}(查看)'))
        rows.append((manage_code(dept), f'生产报表-{label}(管理)'))
    return rows


def production_scope_of(user: User, *, write: bool = False) -> set[str] | None:
    """解析用户在生产报表上的部门范围。

    Args:
        user: 已加载权限的当前用户。
        write: True 解析可写范围，False 解析可见范围。

    Returns:
        None 表示全部部门；set 表示仅这些部门；空集表示无权限。
    """
    aggregate = AGGREGATE_MANAGE_CODE if write else AGGREGATE_VIEW_CODE
    if user.has_permission(aggregate):
        return None

    scope: set[str] = set()
    for dept in PRODUCTION_DEPARTMENTS:
        if user.has_permission(manage_code(dept)):
            # 部门级 manage 蕴含同部门 view —— User.has_permission 的
            # manage→view 继承只对顶级码生效，这里必须显式补上。
            scope.add(dept)
        elif not write and user.has_permission(view_code(dept)):
            scope.add(dept)
    return scope


def narrow_departments(requested: str, scope: set[str] | None) -> set[str] | None:
    """把请求的单个 department 参数与用户范围取交集。

    范围外的取值一律**忽略**而不是报 403：前端筛选状态残留不应让整页报错。

    Returns:
        None 表示不加部门条件；set 表示查询需限定在这些部门。
    """
    if scope is None:
        return {requested} if requested else None
    if requested and requested in scope:
        return {requested}
    return scope
