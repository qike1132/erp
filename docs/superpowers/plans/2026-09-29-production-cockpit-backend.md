# 生产驾驶舱 —— 后端能力与按部门权限 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 `/production` 驾驶舱重构补齐后端能力（跨月趋势接口、明细区间/录单人筛选、删除审计）并落地"按部门拆权限点"的数据范围收窄。

**Architecture:** 部门范围定义收敛到 `fastapi_app/core/production_scope.py` 单一事实来源（权限码命名、范围解析、请求参数收窄都是纯函数，可脱离数据库测试）；FastAPI 依赖层在 `core/deps.py` 暴露两个范围依赖，端点通过 `Depends` 拿到的**不是 User 而是 `set[str] | None`**（`None` = 全部部门），因此测试可以直接覆盖这个依赖注入一个已知范围，不必伪造 `has_permission`。所有收窄在**服务层查询条件**生效，端点只负责把请求参数与范围取交集。

**Tech Stack:** FastAPI / SQLAlchemy 2.0 async / Pydantic v2 / pytest（`asyncio_mode=auto`）/ ruff。

**Spec:** `docs/superpowers/specs/2026-09-29-production-cockpit-design.md`（本计划实现其 §5 权限模型、§6 后端改动、§8.1 测试策略；前端部分见另行的 Plan B）

## Global Constraints

- 部门键固定为 `filling` / `handcraft` / `packaging`，不得引入别名。
- 6 个新权限码必须由 `production_scope.py` 生成（`view_code()` / `manage_code()`），种子脚本与运行时解析器共用同一来源，禁止各写一份字符串。
- `get_monthly_summary_for_auto()` 的行为不得改变（定时任务入口，默认全部门）。
- `production_summary.py`（工艺 / 包装记录）的接口行为与其使用的 `production_summary_view` / `production_summary_manage` 聚合码语义**不得改动** —— 前端已无调用（`productionApi` 全仓零引用），但可能有外部客户端。
- 所有 service 函数新增参数一律带默认值，保证既有调用点不破。
- ruff：`line-length = 120`、`quote-style = single`、`indent-style = space`；`select` 含 `S`（安全规则）→ 非测试文件里不得出现裸 `assert`。
- pytest：`asyncio_mode = auto`（无需 `@pytest.mark.asyncio`，但沿用现有测试里的显式标记也无害）；`filterwarnings = error` → 任何警告即失败。
- 测试运行命令：`command python -m pytest fastapi_app/tests/<file> -q --no-header`（本机 bash 对部分命令有别名故障，需带 `command` 前缀）。
- 提交信息以 `Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>` 结尾。

## Review Focus

以下 5 类输入是规格隐含、但单看每个任务的测试容易漏掉、且最可能真的咬到使用者的（按可能性排序）。每一行都在其后标注的任务里配了测试：

1. **`created_by` 传空串或纯空格**（前端下拉清空后就是 `''`）→ 必须视为"不限"，否则会退化成"只看录单人为空的记录"，在界面上表现为数据凭空消失。→ Task 5
2. **用户范围为空集**（未分配任何生产权限）→ 必须 403。绝不能退化成"范围为空 = 不过滤 = 看到全部部门"，这是本改动最危险的失效方向（fail-open）。→ Task 3
3. **`start_date > end_date`**（使用者把自定义区间选反）→ 必须 400；否则跨度算出 0 或负数，趋势图空白且没有任何提示。→ Task 4 / Task 5
4. **同时传 `year`+`month` 与 `start_date`+`end_date`**（前端在"本月"与"自定义"之间切换时可能两个都带上）→ 区间优先，不报错、不把两个月叠加。→ Task 5
5. **`department` 传非法值或大小写不一致**（`'Filling'`、`'xxx'`）→ 不得 500；无匹配即返回空；对受限用户则回落到其自身范围。→ Task 6

---

### Task 1: 部门范围定义与解析（纯函数）

**Files:**
- Create: `fastapi_app/core/production_scope.py`
- Test: `fastapi_app/tests/test_production_scope.py`

**Interfaces:**
- Consumes: `fastapi_app.shared_models.User`（只调用其 `has_permission(code: str) -> bool`）
- Produces:
  - `PRODUCTION_DEPARTMENTS: tuple[str, ...]` = `('filling', 'handcraft', 'packaging')`
  - `AGGREGATE_VIEW_CODE: str` = `'production_summary_view'`
  - `AGGREGATE_MANAGE_CODE: str` = `'production_summary_manage'`
  - `view_code(department: str) -> str`
  - `manage_code(department: str) -> str`
  - `dept_permission_rows() -> list[tuple[str, str]]` —— `(code, name)`，共 6 行
  - `production_scope_of(user: User, *, write: bool = False) -> set[str] | None` —— `None` 表示全部部门；空集表示无权限
  - `narrow_departments(requested: str, scope: set[str] | None) -> set[str] | None`

- [ ] **Step 1: 写失败的测试**

创建 `fastapi_app/tests/test_production_scope.py`：

```python
"""生产报表部门范围解析（纯函数，不碰数据库）"""
from unittest.mock import MagicMock

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
    """构造真实 User 实例，权限用 MagicMock(spec=Permission) 顶替。

    必须显式给 children=[] —— User.has_permission 会迭代 p.children，
    MagicMock 自动生成的属性不可迭代，会直接 TypeError。
    """
    user = User(username='t_user', password='x')
    user.is_super = is_super
    user.permissions = [
        _make_perm(code) for code in codes
    ]
    return user


def _make_perm(code, parent_id=None):
    perm = MagicMock(spec=Permission)
    perm.code = code
    perm.parent_id = parent_id
    perm.children = []
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
```

- [ ] **Step 2: 跑测试确认失败**

Run: `command python -m pytest fastapi_app/tests/test_production_scope.py -q --no-header`
Expected: FAIL —— `ModuleNotFoundError: No module named 'fastapi_app.core.production_scope'`

- [ ] **Step 3: 写实现**

创建 `fastapi_app/core/production_scope.py`：

```python
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
```

- [ ] **Step 4: 跑测试确认通过**

Run: `command python -m pytest fastapi_app/tests/test_production_scope.py -q --no-header`
Expected: PASS（17 passed）

- [ ] **Step 5: lint**

Run: `command python -m ruff check fastapi_app/core/production_scope.py fastapi_app/tests/test_production_scope.py`
Expected: 无输出（All checks passed）

- [ ] **Step 6: 提交**

```bash
git add fastapi_app/core/production_scope.py fastapi_app/tests/test_production_scope.py
git commit -m "$(cat <<'EOF'
feat(production): 新增部门范围解析（权限码命名与范围收窄单一事实来源）

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: 权限点种子脚本（幂等）

**Files:**
- Create: `scripts/init_production_dept_permissions.py`
- Test: `fastapi_app/tests/test_production_dept_permission_seed.py`

**Interfaces:**
- Consumes: `production_scope.dept_permission_rows()`、`production_scope.AGGREGATE_MANAGE_CODE`（来自 Task 1）
- Produces: `seed_dept_permissions(session) -> tuple[int, int]` —— 返回 `(created, skipped)`；`sync_main() -> int`

- [ ] **Step 1: 写失败的测试**

创建 `fastapi_app/tests/test_production_dept_permission_seed.py`：

```python
"""生产报表部门权限种子脚本（用假 session 验证幂等与父子关系）"""
from fastapi_app.core.production_scope import (
    AGGREGATE_MANAGE_CODE,
    dept_permission_rows,
)
from scripts.init_production_dept_permissions import (
    PARENT_CODE,
    seed_dept_permissions,
)


class _FakeQuery:
    def __init__(self, store):
        self._store = store
        self._code = None

    def filter_by(self, **kwargs):
        self._code = kwargs.get('code')
        return self

    def first(self):
        return self._store.get(self._code)


class _FakeSession:
    """只实现脚本用到的最小接口：query().filter_by().first() / add() / commit()"""

    def __init__(self, store):
        self._store = store
        self.commits = 0

    def query(self, _model):
        return _FakeQuery(self._store)

    def add(self, obj):
        self._store[obj.code] = obj

    def commit(self):
        self.commits += 1


def _fake_permission(code, parent_id=None):
    class _P:
        def __init__(self):
            self.code = code
            self.parent_id = parent_id
            self.id = None
    return _P()


def test_parent_code_is_the_aggregate_manage_code():
    assert PARENT_CODE == AGGREGATE_MANAGE_CODE


def test_first_run_creates_all_six_rows():
    store = {PARENT_CODE: _fake_permission(PARENT_CODE)}
    session = _FakeSession(store)

    created, skipped = seed_dept_permissions(session)

    assert (created, skipped) == (6, 0)
    assert set(store) == {PARENT_CODE} | {code for code, _ in dept_permission_rows()}
    assert session.commits == 1


def test_second_run_is_idempotent():
    store = {PARENT_CODE: _fake_permission(PARENT_CODE)}
    session = _FakeSession(store)

    seed_dept_permissions(session)
    created, skipped = seed_dept_permissions(session)

    assert (created, skipped) == (0, 6)


def test_rows_are_hung_under_parent_and_hidden_from_nav():
    parent = _fake_permission(PARENT_CODE)
    parent.id = 42
    store = {PARENT_CODE: parent}
    session = _FakeSession(store)

    seed_dept_permissions(session)

    for code, name in dept_permission_rows():
        perm = store[code]          # 脚本用真实 Permission 类构造，故这些属性可直接断言
        assert perm.name == name
        assert perm.is_nav is False
        assert perm.parent_id == 42  # 不会写出孤儿权限点


def test_missing_parent_raises_instead_of_writing_orphans():
    session = _FakeSession({})
    try:
        seed_dept_permissions(session)
    except RuntimeError as exc:
        assert AGGREGATE_MANAGE_CODE in str(exc)
    else:
        raise AssertionError('父权限缺失时应抛 RuntimeError')


def test_failed_run_writes_nothing():
    session = _FakeSession({})
    try:
        seed_dept_permissions(session)
    except RuntimeError:
        pass
    assert session.commits == 0
```

（`_FakeSession` 与假 Permission 只顶替**查询**路径；`session.add` 收到的是脚本用真实 `Permission` 构造的实例，因此 `name` / `is_nav` / `parent_id` 都是真实属性，断言有效。）

- [ ] **Step 2: 跑测试确认失败**

Run: `command python -m pytest fastapi_app/tests/test_production_dept_permission_seed.py -q --no-header`
Expected: FAIL —— `ModuleNotFoundError: No module named 'scripts.init_production_dept_permissions'`

- [ ] **Step 3: 写实现**

创建 `scripts/init_production_dept_permissions.py`：

```python
"""生产报表按部门权限点初始化（幂等）

新增 6 个部门级权限点，挂在「生产报表(全部)」(production_summary_manage) 之下：
    production_summary_view_{filling,handcraft,packaging}
    production_summary_manage_{filling,handcraft,packaging}

幂等：按 code 逐行 upsert，已存在则跳过（不覆盖人工改过的 name）。

用法：
    python scripts/init_production_dept_permissions.py

注意：务必在发布后端范围收窄逻辑**之前**执行，并给对应用户勾选部门码，
否则部门用户会直接 403、导航入口也会消失（见设计规格 §5.5）。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi_app.core.database import SyncSessionLocal
from fastapi_app.core.production_scope import (
    AGGREGATE_MANAGE_CODE,
    dept_permission_rows,
)
from fastapi_app.shared_models import Permission

PARENT_CODE = AGGREGATE_MANAGE_CODE


def seed_dept_permissions(session) -> tuple[int, int]:
    """写入部门权限点，返回 (created, skipped)。

    Args:
        session: 同步 SQLAlchemy Session（或测试用假 session）。

    Returns:
        (新增数量, 跳过数量)

    Raises:
        RuntimeError: 父权限不存在时 —— 宁可失败也不要写出孤儿权限点。
    """
    parent = session.query(Permission).filter_by(code=PARENT_CODE).first()
    if parent is None:
        raise RuntimeError(
            f'未找到父权限 {PARENT_CODE}，请先运行 scripts/init_permissions.py'
        )

    created = 0
    skipped = 0
    for code, name in dept_permission_rows():
        if session.query(Permission).filter_by(code=code).first() is not None:
            skipped += 1
            print(f'[SKIP] {code} 已存在')
            continue
        session.add(Permission(
            name=name,
            code=code,
            parent_id=parent.id,
            is_nav=False,
        ))
        created += 1
        print(f'[OK] 新增 {code} → {name}')

    session.commit()
    print(f'\n完成：新增 {created} 个，跳过 {skipped} 个')
    return created, skipped


def sync_main() -> int:
    session = SyncSessionLocal()
    try:
        seed_dept_permissions(session)
        return 0
    except RuntimeError as exc:
        print(f'[ERROR] {exc}')
        return 1
    finally:
        session.close()


if __name__ == '__main__':
    raise SystemExit(sync_main())
```

- [ ] **Step 4: 跑测试确认通过**

Run: `command python -m pytest fastapi_app/tests/test_production_dept_permission_seed.py -q --no-header`
Expected: PASS（6 passed）

- [ ] **Step 5: 在真实库上执行并核对**

> ⚠️ **先确认目标数据库**：`SyncSessionLocal` 连接的是 `fastapi_app/core/config.py` 配置的环境。本机若直连生产库，这一步就是生产变更 —— 在**生产环境执行属于上线步骤**（Task 10 Step 4 的第 1 条），不要在执行计划的过程中顺手跑。计划期间只需在开发库上验证幂等。

在**开发库**上运行：

Run: `command python scripts/init_production_dept_permissions.py`
Expected 输出包含 6 行 `[OK] 新增 ...`，结尾 `完成：新增 6 个，跳过 0 个`。
再跑一次，Expected：`完成：新增 0 个，跳过 6 个`（幂等）。

- [ ] **Step 6: lint**

Run: `command python -m ruff check scripts/init_production_dept_permissions.py fastapi_app/tests/test_production_dept_permission_seed.py`
Expected: 无输出

- [ ] **Step 7: 提交**

```bash
git add scripts/init_production_dept_permissions.py fastapi_app/tests/test_production_dept_permission_seed.py
git commit -m "$(cat <<'EOF'
feat(production): 新增按部门拆分的 6 个权限点种子（幂等）

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: FastAPI 范围依赖（空集必须 403）

**Files:**
- Modify: `fastapi_app/core/deps.py`（在 `require_any_permission` 之后追加三个依赖）
- Test: `fastapi_app/tests/test_production_scope_dependency.py`

**Interfaces:**
- Consumes: `production_scope.production_scope_of()`（Task 1）
- Produces:
  - `get_current_user_with_permissions(user: User = Depends(_get_user_with_permissions)) -> User`
  - `resolve_production_view_scope(user: User = Depends(_get_user_with_permissions)) -> set[str] | None`
  - `resolve_production_write_scope(user: User = Depends(_get_user_with_permissions)) -> set[str] | None`

- [ ] **Step 1: 写失败的测试**

创建 `fastapi_app/tests/test_production_scope_dependency.py`：

```python
"""范围依赖：空集必须 403（fail-open 是最危险的失效方向）"""
from unittest.mock import MagicMock

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
    perm = MagicMock(spec=Permission)
    perm.code = code
    perm.parent_id = None
    perm.children = []
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
```

- [ ] **Step 2: 跑测试确认失败**

Run: `command python -m pytest fastapi_app/tests/test_production_scope_dependency.py -q --no-header`
Expected: FAIL —— `ImportError: cannot import name 'resolve_production_view_scope'`

- [ ] **Step 3: 写实现**

在 `fastapi_app/core/deps.py` 中找到 `require_any_permission` 函数（约 295 行起）并在其**之后**追加：

```python
async def get_current_user_with_permissions(
    user: User = Depends(_get_user_with_permissions),
) -> User:
    """公开别名。

    `_get_user_with_permissions` 是本模块私有依赖；端点需要「当前用户 + 已加载权限」
    时通过本别名依赖，避免跨模块导入私有名字。FastAPI 会缓存依赖，与
    `resolve_production_*_scope` 同时使用时不会重复查库。
    """
    return user


async def resolve_production_view_scope(
    user: User = Depends(_get_user_with_permissions),
) -> set[str] | None:
    """生产报表可见部门范围。

    Returns:
        None 表示全部部门；否则为可见部门集合。

    Raises:
        HTTPException: 403 —— 用户在生产报表上没有任何可见部门。
            空集绝不允许退化为「不过滤」，否则未授权用户会看到全部数据。
    """
    from fastapi_app.core.production_scope import production_scope_of

    scope = production_scope_of(user, write=False)
    if scope is not None and not scope:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='权限不足')
    return scope


async def resolve_production_write_scope(
    user: User = Depends(_get_user_with_permissions),
) -> set[str] | None:
    """生产报表可写部门范围（语义同上，但只认 manage 码）。"""
    from fastapi_app.core.production_scope import production_scope_of

    scope = production_scope_of(user, write=True)
    if scope is not None and not scope:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='权限不足')
    return scope
```

> 局部 import 是刻意的：`production_scope` 导入 `shared_models.User`，而 `deps.py` 已被大量模块导入，放在函数内可避免任何潜在的循环导入。

- [ ] **Step 4: 跑测试确认通过**

Run: `command python -m pytest fastapi_app/tests/test_production_scope_dependency.py -q --no-header`
Expected: PASS（6 passed）

- [ ] **Step 5: 确认没有回归**

Run: `command python -m pytest fastapi_app/tests/test_production_summary.py fastapi_app/tests/test_auth.py -q --no-header`
Expected: PASS（既有权限相关测试未被破坏）

- [ ] **Step 6: lint + 提交**

Run: `command python -m ruff check fastapi_app/core/deps.py fastapi_app/tests/test_production_scope_dependency.py`
Expected: 无输出

```bash
git add fastapi_app/core/deps.py fastapi_app/tests/test_production_scope_dependency.py
git commit -m "$(cat <<'EOF'
feat(production): 新增生产报表部门范围依赖（空集一律 403）

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: 新增 `GET /daily-production/trend`（跨月按日按部门）

**Files:**
- Modify: `fastapi_app/schemas/daily_production.py:89-99`（在月度汇总段之后追加）
- Modify: `fastapi_app/services/daily_production_service.py`（新增 `MAX_TREND_DAYS`、`get_trend`）
- Modify: `fastapi_app/api/v1/endpoints/daily_production.py`（新增端点）
- Test: `fastapi_app/tests/test_daily_production_trend.py`

**Interfaces:**
- Consumes: `DailyProductionRecord`、`parse_date_with_fallback`、`PRODUCTION_DEPARTMENTS`
- Produces:
  - `get_trend(db: AsyncSession, *, start_date: str, end_date: str, departments: set[str] | None = None) -> dict`，返回 `{'start_date': str, 'end_date': str, 'departments': list[str], 'days': list[dict]}`
  - `TrendResponse`（Pydantic）
  - `GET /api/v1/daily-production/trend`

- [ ] **Step 1: 写失败的测试**

创建 `fastapi_app/tests/test_daily_production_trend.py`：

```python
"""趋势接口：跨月区间、缺失日期补 0、区间长度上限、区间反向"""
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from fastapi_app.services.daily_production_service import (
    MAX_TREND_DAYS,
    get_trend,
)


def _mock_db_returning(rows):
    result = MagicMock()
    result.all.return_value = rows
    db = AsyncMock()
    db.execute = AsyncMock(return_value=result)
    return db


class TestGetTrendService:
    async def test_fills_missing_days_with_zero(self):
        db = _mock_db_returning([
            (date(2026, 9, 1), 'filling', 100),
            (date(2026, 9, 1), 'handcraft', 50),
            (date(2026, 9, 3), 'packaging', 7),
        ])

        out = await get_trend(db, start_date='2026-09-01', end_date='2026-09-03')

        assert len(out['days']) == 3
        assert out['days'][0] == {
            'date': '2026-09-01', 'filling': 100, 'handcraft': 50, 'packaging': 0, 'total': 150,
        }
        assert out['days'][1] == {
            'date': '2026-09-02', 'filling': 0, 'handcraft': 0, 'packaging': 0, 'total': 0,
        }
        assert out['days'][2]['total'] == 7
        assert out['days'][2]['packaging'] == 7

    async def test_reports_unscoped_departments_as_zero_and_lists_only_scope(self):
        db = _mock_db_returning([(date(2026, 9, 1), 'filling', 100)])

        out = await get_trend(
            db, start_date='2026-09-01', end_date='2026-09-01', departments={'filling'},
        )

        assert out['departments'] == ['filling']
        assert out['days'][0]['filling'] == 100
        assert out['days'][0]['handcraft'] == 0
        assert out['days'][0]['total'] == 100

    async def test_reversed_range_raises_value_error(self):
        db = _mock_db_returning([])
        with pytest.raises(ValueError, match='不能早于'):
            await get_trend(db, start_date='2026-09-10', end_date='2026-09-01')

    async def test_range_longer_than_cap_raises_value_error(self):
        db = _mock_db_returning([])
        with pytest.raises(ValueError, match=str(MAX_TREND_DAYS)):
            await get_trend(db, start_date='2026-01-01', end_date='2026-12-31')

    async def test_cap_counts_days_inclusively(self):
        # 92 天必须通过（边界包含），93 天必须拒绝
        db = _mock_db_returning([])
        out = await get_trend(db, start_date='2026-01-01', end_date='2026-04-02')
        assert len(out['days']) == 92
        with pytest.raises(ValueError):
            await get_trend(db, start_date='2026-01-01', end_date='2026-04-03')


class TestTrendEndpoint:
    async def test_endpoint_returns_days(self, client):
        payload = {
            'start_date': '2026-09-01',
            'end_date': '2026-09-02',
            'departments': ['filling', 'handcraft', 'packaging'],
            'days': [
                {'date': '2026-09-01', 'filling': 1, 'handcraft': 0, 'packaging': 0, 'total': 1},
                {'date': '2026-09-02', 'filling': 0, 'handcraft': 0, 'packaging': 0, 'total': 0},
            ],
        }
        with patch(
            'fastapi_app.api.v1.endpoints.daily_production.daily_production_service'
        ) as mock_svc:
            mock_svc.get_trend = AsyncMock(return_value=payload)
            response = await client.get(
                '/api/v1/daily-production/trend',
                params={'start_date': '2026-09-01', 'end_date': '2026-09-02'},
            )
        assert response.status_code == 200
        body = response.json()
        assert body['success'] is True
        assert len(body['days']) == 2

    async def test_endpoint_maps_value_error_to_400(self, client):
        with patch(
            'fastapi_app.api.v1.endpoints.daily_production.daily_production_service'
        ) as mock_svc:
            mock_svc.get_trend = AsyncMock(side_effect=ValueError('查询区间不能超过 92 天'))
            response = await client.get(
                '/api/v1/daily-production/trend',
                params={'start_date': '2026-01-01', 'end_date': '2026-12-31'},
            )
        assert response.status_code == 400
```

- [ ] **Step 2: 跑测试确认失败**

Run: `command python -m pytest fastapi_app/tests/test_daily_production_trend.py -q --no-header`
Expected: FAIL —— `ImportError: cannot import name 'MAX_TREND_DAYS'`

- [ ] **Step 3: 加 Pydantic 响应模型**

在 `fastapi_app/schemas/daily_production.py` 的 `MonthlySummaryResponse` 之后追加：

```python
# ==================== 趋势 ====================

class TrendResponse(BaseModel):
    """按日按部门的数量趋势响应

    departments 只列出调用方可见的部门；days 中不可见部门的键固定为 0
    （保持响应结构稳定，前端按 departments 决定画哪几条序列）。
    """
    success: bool = True
    start_date: str = ''
    end_date: str = ''
    departments: list[str] = []
    days: list[dict] = []
```

- [ ] **Step 4: 写服务实现**

在 `fastapi_app/services/daily_production_service.py`：把文件头部的 `from datetime import date` 改为 `from datetime import date, timedelta`，并在 **`# ==================== 导出 ====================` 之前**插入：

```python
# ==================== 趋势 ====================

MAX_TREND_DAYS = 92


async def get_trend(
    db: AsyncSession,
    *,
    start_date: str,
    end_date: str,
    departments: set[str] | None = None,
) -> dict:
    """按日按部门的生产数量趋势（可跨月）。

    Args:
        db: 只读会话。
        start_date: 起始日期 (YYYY-MM-DD)。
        end_date: 结束日期 (YYYY-MM-DD)，闭区间。
        departments: 可见部门集合；None 表示全部部门。

    Returns:
        {'start_date', 'end_date', 'departments', 'days'}；
        days 中每一天都含三个部门键与 total，无数据的日期补 0（让前端 x 轴连续）。

    Raises:
        ValueError: 区间反向或超过 MAX_TREND_DAYS 天。
    """
    start = parse_date_with_fallback(start_date)
    end = parse_date_with_fallback(end_date)
    if end < start:
        raise ValueError('结束日期不能早于开始日期')

    span = (end - start).days + 1
    if span > MAX_TREND_DAYS:
        raise ValueError(f'查询区间不能超过 {MAX_TREND_DAYS} 天')

    dept_keys = (
        list(PRODUCTION_DEPARTMENTS) if departments is None
        else [d for d in PRODUCTION_DEPARTMENTS if d in departments]
    )

    rows: list = []
    if dept_keys:
        result = await db.execute(
            select(
                DailyProductionRecord.production_date,
                DailyProductionRecord.department,
                func.coalesce(func.sum(DailyProductionRecord.quantity), 0).label('qty'),
            )
            .where(and_(
                DailyProductionRecord.production_date >= start,
                DailyProductionRecord.production_date <= end,
                DailyProductionRecord.department.in_(dept_keys),
            ))
            .group_by(DailyProductionRecord.production_date, DailyProductionRecord.department)
        )
        rows = list(result.all())

    by_day: dict[str, dict[str, int]] = {}
    for prod_date, department, qty in rows:
        by_day.setdefault(prod_date.isoformat(), {})[department] = int(qty)

    days = []
    for offset in range(span):
        key = (start + timedelta(days=offset)).isoformat()
        item: dict = {'date': key}
        total = 0
        day_values = by_day.get(key, {})
        for dept in PRODUCTION_DEPARTMENTS:
            value = day_values.get(dept, 0) if dept in dept_keys else 0
            item[dept] = value
            total += value
        item['total'] = total
        days.append(item)

    return {
        'start_date': start_date,
        'end_date': end_date,
        'departments': dept_keys,
        'days': days,
    }
```

并在文件头部 import 段补上部门常量（与 `DEPARTMENT_LABELS` 并列，避免两处各写一份键名）：

```python
from fastapi_app.core.production_scope import PRODUCTION_DEPARTMENTS
```

- [ ] **Step 5: 跑服务层测试确认通过**

Run: `command python -m pytest fastapi_app/tests/test_daily_production_trend.py::TestGetTrendService -q --no-header`
Expected: PASS（5 passed）

- [ ] **Step 6: 写端点**

在 `fastapi_app/api/v1/endpoints/daily_production.py`：

把既有的 `from fastapi_app.core.deps import require_permission` 改为：

```python
from fastapi_app.core.deps import require_permission, resolve_production_view_scope
```

把既有的 `from fastapi_app.core.production_scope import narrow_departments` 加入（若尚未存在）：

```python
from fastapi_app.core.production_scope import narrow_departments
```

在既有的 `from fastapi_app.schemas.daily_production import (...)` 括号内追加一行 `TrendResponse,`（保持字母序，isort 检查会管）。

在 `monthly_summary` 端点之后插入：

```python
@router.get('/trend', response_model=TrendResponse)
async def trend(
    start_date: str = Query(..., description='起始日期 (YYYY-MM-DD)'),
    end_date: str = Query(..., description='结束日期 (YYYY-MM-DD)'),
    department: str = Query('', description='部门筛选 (filling/handcraft/packaging)'),
    scope: set[str] | None = Depends(resolve_production_view_scope),
    db: AsyncSession = Depends(get_async_read_db),
) -> TrendResponse:
    """获取按日按部门的生产数量趋势（可跨月，最长 92 天）。

    Args:
        start_date: 起始日期。
        end_date: 结束日期（闭区间）。
        department: 部门筛选；超出用户可见范围时忽略该参数。
        scope: 用户可见部门范围（None 表示全部）。
        db: 异步数据库会话（只读副本）。

    Returns:
        TrendResponse: 含 departments 与逐日补零后的 days。

    Raises:
        HTTPException: 400（区间非法）、500（数据库异常）。
    """
    try:
        result = await daily_production_service.get_trend(
            db,
            start_date=start_date,
            end_date=end_date,
            departments=narrow_departments(department, scope),
        )
        return TrendResponse(**result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except (OperationalError, DisconnectionError) as e:
        raise HTTPException(status_code=500, detail=f'获取趋势失败: {settings.sanitize_error(e)}') from e
```

import 段还需补 `narrow_departments`：

```python
from fastapi_app.core.production_scope import narrow_departments
```

- [ ] **Step 7: 跑全部趋势测试确认通过**

Run: `command python -m pytest fastapi_app/tests/test_daily_production_trend.py -q --no-header`
Expected: PASS（7 passed）

- [ ] **Step 8: lint + 提交**

Run: `command python -m ruff check fastapi_app/services/daily_production_service.py fastapi_app/api/v1/endpoints/daily_production.py fastapi_app/schemas/daily_production.py fastapi_app/tests/test_daily_production_trend.py`
Expected: 无输出

```bash
git add fastapi_app/schemas/daily_production.py fastapi_app/services/daily_production_service.py fastapi_app/api/v1/endpoints/daily_production.py fastapi_app/tests/test_daily_production_trend.py
git commit -m "$(cat <<'EOF'
feat(production): 新增跨月趋势接口 GET /daily-production/trend

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: `/records` 扩展筛选（区间 / 录单人 / 排序）

**Files:**
- Modify: `fastapi_app/services/daily_production_service.py:74-154`（`get_records`）
- Modify: `fastapi_app/api/v1/endpoints/daily_production.py:38-79`（`list_records`）
- Test: `fastapi_app/tests/test_daily_production_records_filter.py`

**Interfaces:**
- Consumes: `production_scope.narrow_departments()`、`resolve_production_view_scope`
- Produces:
  - `_build_record_conditions(*, year: int | None, month: int | None, start_date: str, end_date: str, departments: set[str] | None, created_by: str) -> list`（纯函数，供测试断言条件组合）
  - `get_records(db, *, year=None, month=None, departments=None, start_date='', end_date='', created_by='', sort='desc', page=1, per_page=50) -> dict`
  - `GET /records` 新增 query 参数：`start_date`、`end_date`、`created_by`、`sort`

- [ ] **Step 1: 写失败的测试**

创建 `fastapi_app/tests/test_daily_production_records_filter.py`：

```python
"""明细列表筛选：日期区间优先、录单人为空白即不限、区间反向报错"""
import pytest

from fastapi_app.services.daily_production_service import _build_record_conditions


def _texts(conditions):
    return ' | '.join(str(c) for c in conditions)


class TestRecordConditions:
    def test_year_month_only_matches_existing_behaviour(self):
        conditions = _build_record_conditions(
            year=2026, month=9, start_date='', end_date='',
            departments=None, created_by='',
        )
        assert len(conditions) == 2
        assert 'production_date' in _texts(conditions)

    def test_blank_created_by_is_not_applied(self):
        # 前端下拉清空后传 ''，绝不能退化成「只看录单人为空的记录」
        conditions = _build_record_conditions(
            year=2026, month=9, start_date='', end_date='',
            departments=None, created_by='',
        )
        assert 'created_by' not in _texts(conditions)

    def test_whitespace_created_by_is_not_applied(self):
        conditions = _build_record_conditions(
            year=2026, month=9, start_date='', end_date='',
            departments=None, created_by='   ',
        )
        assert 'created_by' not in _texts(conditions)

    def test_real_created_by_is_applied(self):
        conditions = _build_record_conditions(
            year=2026, month=9, start_date='', end_date='',
            departments=None, created_by=' 张三 ',
        )
        assert 'created_by' in _texts(conditions)

    def test_range_takes_precedence_over_year_month(self):
        conditions = _build_record_conditions(
            year=2026, month=9, start_date='2026-08-25', end_date='2026-09-02',
            departments=None, created_by='',
        )
        rendered = _texts(conditions)
        # 只应出现区间的两个边界，不应叠加 9 月的月初/月末
        assert rendered.count('production_date') == 2
        assert len(conditions) == 2

    def test_departments_scoped_is_applied(self):
        conditions = _build_record_conditions(
            year=2026, month=9, start_date='', end_date='',
            departments={'filling'}, created_by='',
        )
        assert 'department' in _texts(conditions)
        assert len(conditions) == 3

    def test_production_date_is_stacked_on_month_conditions(self):
        conditions = _build_record_conditions(
            year=2026, month=9, start_date='', end_date='',
            departments=None, created_by='', production_date='2026-09-15',
        )
        assert len(conditions) == 3

    def test_production_date_is_stacked_on_range_conditions(self):
        conditions = _build_record_conditions(
            year=None, month=None, start_date='2026-09-01', end_date='2026-09-30',
            departments=None, created_by='', production_date='2026-09-15',
        )
        assert len(conditions) == 3

    def test_no_date_input_at_all_raises(self):
        with pytest.raises(ValueError, match='必须提供'):
            _build_record_conditions(
                year=None, month=None, start_date='', end_date='',
                departments=None, created_by='',
            )

    def test_only_start_date_raises(self):
        with pytest.raises(ValueError, match='必须同时提供'):
            _build_record_conditions(
                year=None, month=None, start_date='2026-09-01', end_date='',
                departments=None, created_by='',
            )

    def test_reversed_range_raises(self):
        with pytest.raises(ValueError, match='不能早于'):
            _build_record_conditions(
                year=None, month=None, start_date='2026-09-10', end_date='2026-09-01',
                departments=None, created_by='',
            )
```

- [ ] **Step 2: 跑测试确认失败**

Run: `command python -m pytest fastapi_app/tests/test_daily_production_records_filter.py -q --no-header`
Expected: FAIL —— `ImportError: cannot import name '_build_record_conditions'`

- [ ] **Step 3: 写服务实现**

在 `fastapi_app/services/daily_production_service.py` 中，把 `get_records`（74-154 行）整体替换为下面两个函数：

```python
def _build_record_conditions(
    *,
    year: int | None,
    month: int | None,
    start_date: str,
    end_date: str,
    departments: set[str] | None,
    created_by: str,
    production_date: str = '',
) -> list:
    """构造生产记录查询条件（纯函数，便于单测覆盖组合边界）。

    Args:
        year: 年份；与 month 一起使用。
        month: 月份。
        start_date: 区间起始日 (YYYY-MM-DD)；与 end_date 必须成对，且优先于 year/month。
        end_date: 区间结束日 (YYYY-MM-DD)，闭区间。
        departments: 部门集合；None 表示不限。
        created_by: 录单人；空白视为不限。
        production_date: 指定单日，叠加在日期条件之上。

    Returns:
        SQLAlchemy 条件列表。

    Raises:
        ValueError: 未提供任何日期条件、区间只给一半、或区间反向。
    """
    if start_date or end_date:
        if not (start_date and end_date):
            raise ValueError('start_date 与 end_date 必须同时提供')
        range_start = parse_date_with_fallback(start_date)
        range_end = parse_date_with_fallback(end_date)
        if range_end < range_start:
            raise ValueError('结束日期不能早于开始日期')
        conditions: list = [
            DailyProductionRecord.production_date >= range_start,
            DailyProductionRecord.production_date <= range_end,
        ]
    else:
        if year is None or month is None:
            raise ValueError('必须提供 year/month，或同时提供 start_date/end_date')
        month_start = date(year, month, 1)
        month_end = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
        conditions = [
            DailyProductionRecord.production_date >= month_start,
            DailyProductionRecord.production_date < month_end,
        ]

    if departments is not None:
        conditions.append(DailyProductionRecord.department.in_(sorted(departments)))

    if created_by and created_by.strip():
        conditions.append(DailyProductionRecord.created_by == created_by.strip())

    if production_date:
        conditions.append(
            DailyProductionRecord.production_date == parse_date_with_fallback(production_date)
        )

    return conditions


async def get_records(
    db: AsyncSession,
    *,
    year: int | None = None,
    month: int | None = None,
    departments: set[str] | None = None,
    start_date: str = '',
    end_date: str = '',
    created_by: str = '',
    sort: str = 'desc',
    page: int = 1,
    per_page: int = 50,
    production_date: str = '',
) -> dict:
    """获取生产记录列表（分页 + 统计）。

    Args:
        db: 只读会话。
        year / month: 按自然月筛选；提供区间时被忽略。
        departments: 可见部门集合；None 表示全部部门。
        start_date / end_date: 区间筛选（闭区间，可跨月），必须成对。
        created_by: 录单人筛选，空白视为不限。
        sort: 'desc'（默认，最新在前）或 'asc'。
        page: 页码，从 1 开始。
        per_page: 每页数量，服务端收敛到 1..200。
        production_date: 指定单日，叠加在日期条件之上。

    Returns:
        {'data', 'total', 'page', 'per_page', 'pages', 'stats'}

    Raises:
        ValueError: 日期条件非法或 sort 取值非法。
    """
    if sort not in ('asc', 'desc'):
        raise ValueError("sort 只能是 'asc' 或 'desc'")

    conditions = _build_record_conditions(
        year=year, month=month, start_date=start_date, end_date=end_date,
        departments=departments, created_by=created_by, production_date=production_date,
    )

    per_page = max(1, min(per_page, 200))
    offset = (page - 1) * per_page

    from sqlalchemy import true

    stats_cte = (
        select(
            func.count(DailyProductionRecord.id).label('total_count'),
            func.coalesce(func.sum(DailyProductionRecord.quantity), 0).label('total_qty'),
            func.coalesce(func.sum(DailyProductionRecord.unit_price * DailyProductionRecord.quantity), 0).label('total_val'),
            func.count(func.distinct(DailyProductionRecord.product_name)).label('total_sku'),
        )
        .where(*conditions)
        .cte('stats')
    )

    from sqlalchemy.sql.expression import Join
    cross_from = Join(DailyProductionRecord.__table__, stats_cte, true())

    if sort == 'asc':
        order_by = (
            DailyProductionRecord.production_date,
            DailyProductionRecord.department,
            DailyProductionRecord.id,
        )
    else:
        # 同一天内按 id 倒序，避免同日期内顺序随机
        order_by = (
            DailyProductionRecord.production_date.desc(),
            DailyProductionRecord.id.desc(),
        )

    result = await db.execute(
        select(
            DailyProductionRecord,
            stats_cte.c.total_count,
            stats_cte.c.total_qty,
            stats_cte.c.total_val,
            stats_cte.c.total_sku,
        )
        .select_from(cross_from)
        .where(*conditions)
        .order_by(*order_by)
        .offset(offset)
        .limit(per_page)
    )
    rows = result.all()
    records = [r[0] for r in rows]
    # total 用独立 COUNT 查询获取：请求页越界时 rows 为空，此前从 rows[0] 取值会误报 0
    total = int((await db.execute(select(func.count(DailyProductionRecord.id)).where(*conditions))).scalar() or 0)
    total_qty = rows[0][2] if rows else 0
    total_val = rows[0][3] if rows else 0
    total_sku = rows[0][4] if rows else 0

    price_fallback = await _build_product_price_fallback(db, records)

    return {
        'data': [r.to_dict(price_fallback) for r in records],
        'total': total,
        'page': page,
        'per_page': per_page,
        'pages': calc_total_pages(total, per_page),
        'stats': {
            'total_quantity': int(total_qty),
            'total_value': round_money(float(total_val)),
            'total_sku': int(total_sku),
        },
    }
```

- [ ] **Step 4: 跑服务层测试确认通过**

Run: `command python -m pytest fastapi_app/tests/test_daily_production_records_filter.py -q --no-header`
Expected: PASS（11 passed）

- [ ] **Step 5: 改端点**

在 `fastapi_app/api/v1/endpoints/daily_production.py` 中，把 `list_records`（38-79 行）整体替换为：

```python
@router.get('/records', response_model=ProductionRecordListResponse)
async def list_records(
    year: int | None = Query(None, description='年份；未提供区间时必填'),
    month: int | None = Query(None, ge=1, le=12, description='月份；未提供区间时必填'),
    start_date: str = Query('', description='区间起始日 (YYYY-MM-DD)，与 end_date 成对'),
    end_date: str = Query('', description='区间结束日 (YYYY-MM-DD)，闭区间'),
    department: str = Query('', description='部门筛选 (filling/handcraft/packaging)'),
    production_date: str = Query('', description='指定日期筛选 (YYYY-MM-DD)'),
    created_by: str = Query('', description='录单人筛选；留空为不限'),
    sort: str = Query('desc', description="排序：desc（最新在前，默认）或 asc"),
    page: int = Query(1, ge=1, description='页码'),
    per_page: int = Query(50, ge=1, le=200, description='每页数量'),
    scope: set[str] | None = Depends(resolve_production_view_scope),
    db: AsyncSession = Depends(get_async_read_db),
) -> ProductionRecordListResponse:
    """获取生产记录列表（支持按自然月或日期区间、部门、录单人筛选与分页）。

    Args:
        year: 年份；与 month 搭配。提供区间时忽略。
        month: 月份，1-12。提供区间时忽略。
        start_date: 区间起始日；与 end_date 必须成对。
        end_date: 区间结束日（闭区间）。
        department: 部门筛选；超出用户可见范围时忽略该参数。
        production_date: 指定日期筛选，叠加在日期条件之上。
        created_by: 录单人筛选；空白表示不限。
        sort: 排序方向，'desc' 或 'asc'。
        page: 页码。
        per_page: 每页数量，1-200。
        scope: 用户可见部门范围（None 表示全部）。
        db: 异步数据库会话（只读副本）。

    Returns:
        ProductionRecordListResponse: 记录列表 + 分页信息 + 当前筛选下的统计。

    Raises:
        HTTPException: 400（日期条件或 sort 非法）、500（数据库异常）。
    """
    try:
        conditions_scope = narrow_departments(department, scope)
        result = await daily_production_service.get_records(
            db,
            year=year,
            month=month,
            departments=conditions_scope,
            start_date=start_date,
            end_date=end_date,
            created_by=created_by,
            sort=sort,
            page=page,
            per_page=per_page,
            production_date=production_date,
        )
        return ProductionRecordListResponse(
            data=result['data'], total=result['total'],
            page=result['page'], per_page=result['per_page'],
            pages=result['pages'], stats=result.get('stats'),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except (OperationalError, DisconnectionError) as e:
        raise HTTPException(status_code=500, detail=f'获取数据失败: {settings.sanitize_error(e)}') from e
```

- [ ] **Step 6: 跑全部测试确认通过**

Run: `command python -m pytest fastapi_app/tests/test_daily_production_records_filter.py fastapi_app/tests/test_daily_production_trend.py -q --no-header`
Expected: PASS（11 + 7 passed）

- [ ] **Step 7: lint + 提交**

Run: `command python -m ruff check fastapi_app/services/daily_production_service.py fastapi_app/api/v1/endpoints/daily_production.py fastapi_app/tests/test_daily_production_records_filter.py`
Expected: 无输出

```bash
git add fastapi_app/services/daily_production_service.py fastapi_app/api/v1/endpoints/daily_production.py fastapi_app/tests/test_daily_production_records_filter.py
git commit -m "$(cat <<'EOF'
feat(production): 明细列表支持日期区间、录单人筛选与排序

/records 的 year/month 改为可选，新增 start_date/end_date/created_by/sort。

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: 读接口接入范围收窄

**Files:**
- Modify: `fastapi_app/services/daily_production_service.py`（`get_daily_summary`、`get_monthly_summary`、`export_records`）
- Modify: `fastapi_app/api/v1/endpoints/daily_production.py`（`daily_summary`、`monthly_summary`、`export_records`）
- Test: `fastapi_app/tests/test_daily_production_dept_scope.py`

**Interfaces:**
- Consumes: `resolve_production_view_scope`（Task 3）、`narrow_departments`（Task 1）
- Produces: 三个聚合/导出 service 函数新增 `departments: set[str] | None = None` 参数；`export_records` 的 `department: str` 参数**被 `departments` 取代**

- [ ] **Step 1: 写失败的测试**

创建 `fastapi_app/tests/test_daily_production_dept_scope.py`：

```python
"""读接口的部门范围收窄：受限用户只看得到范围内部门"""
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi_app.core.deps import resolve_production_view_scope
from fastapi_app.main import app


def _scope_override(scope):
    app.dependency_overrides[resolve_production_view_scope] = lambda: scope


class TestDailySummaryScope:
    async def test_scoped_user_passes_departments_to_service(self, client):
        _scope_override({'filling'})
        payload = {
            'date': '2026-09-29',
            'departments': [
                {'department': 'filling', 'department_label': '充棉部',
                 'total_quantity': 10, 'total_value': 70.0, 'sku_count': 1},
            ],
            'overall_quantity': 10,
            'overall_value': 70.0,
            'overall_sku_count': 1,
        }
        with patch(
            'fastapi_app.api.v1.endpoints.daily_production.daily_production_service'
        ) as mock_svc:
            mock_svc.get_daily_summary = AsyncMock(return_value=payload)
            response = await client.get(
                '/api/v1/daily-production/daily-summary', params={'date': '2026-09-29'},
            )
            called_kwargs = mock_svc.get_daily_summary.await_args.kwargs

        assert response.status_code == 200
        assert called_kwargs['departments'] == {'filling'}

    async def test_unscoped_user_passes_none(self, client):
        _scope_override(None)
        with patch(
            'fastapi_app.api.v1.endpoints.daily_production.daily_production_service'
        ) as mock_svc:
            mock_svc.get_daily_summary = AsyncMock(return_value={
                'date': '2026-09-29', 'departments': [],
                'overall_quantity': 0, 'overall_value': 0.0, 'overall_sku_count': 0,
            })
            await client.get(
                '/api/v1/daily-production/daily-summary', params={'date': '2026-09-29'},
            )
            called_kwargs = mock_svc.get_daily_summary.await_args.kwargs

        assert called_kwargs['departments'] is None


class TestMonthlySummaryScope:
    async def test_scoped_user_passes_departments_to_service(self, client):
        _scope_override({'handcraft'})
        with patch(
            'fastapi_app.api.v1.endpoints.daily_production.daily_production_service'
        ) as mock_svc:
            mock_svc.get_monthly_summary = AsyncMock(return_value={
                'year': 2026, 'month': 9, 'daily_data': [], 'monthly_departments': [],
                'monthly_total_quantity': 0, 'monthly_total_value': 0,
            })
            await client.get(
                '/api/v1/daily-production/monthly-summary',
                params={'year': 2026, 'month': 9},
            )
            called_kwargs = mock_svc.get_monthly_summary.await_args.kwargs

        assert called_kwargs['departments'] == {'handcraft'}


class TestRecordsAndExportScope:
    async def test_out_of_scope_department_is_ignored_not_403(self, client):
        # Review Focus #5：前端状态残留不应让整页报错
        _scope_override({'filling'})
        with patch(
            'fastapi_app.api.v1.endpoints.daily_production.daily_production_service'
        ) as mock_svc:
            mock_svc.get_records = AsyncMock(return_value={
                'data': [], 'total': 0, 'page': 1, 'per_page': 50, 'pages': 0, 'stats': None,
            })
            response = await client.get(
                '/api/v1/daily-production/records',
                params={'year': 2026, 'month': 9, 'department': 'packaging'},
            )
            called_kwargs = mock_svc.get_records.await_args.kwargs

        assert response.status_code == 200
        assert called_kwargs['departments'] == {'filling'}

    async def test_invalid_department_for_unscoped_user_does_not_500(self, client):
        _scope_override(None)
        with patch(
            'fastapi_app.api.v1.endpoints.daily_production.daily_production_service'
        ) as mock_svc:
            mock_svc.get_records = AsyncMock(return_value={
                'data': [], 'total': 0, 'page': 1, 'per_page': 50, 'pages': 0, 'stats': None,
            })
            response = await client.get(
                '/api/v1/daily-production/records',
                params={'year': 2026, 'month': 9, 'department': 'Filling'},
            )
            called_kwargs = mock_svc.get_records.await_args.kwargs

        assert response.status_code == 200
        assert called_kwargs['departments'] == {'Filling'}

    async def test_export_receives_narrowed_departments(self, client):
        _scope_override({'packaging'})
        with patch(
            'fastapi_app.api.v1.endpoints.daily_production.daily_production_service'
        ) as mock_svc:
            mock_svc.export_records = AsyncMock(return_value=b'xlsx-bytes')
            response = await client.get(
                '/api/v1/daily-production/export',
                params={'start_date': '2026-09-01', 'end_date': '2026-09-30', 'department': 'filling'},
            )
            called_kwargs = mock_svc.export_records.await_args.kwargs

        assert response.status_code == 200
        assert called_kwargs['departments'] == {'packaging'}

    async def test_missing_scope_dependency_still_403_for_no_permission_user(self, client, mock_current_user):
        # 走真实依赖（不覆盖），has_permission 全 False → 403
        app.dependency_overrides.pop(resolve_production_view_scope, None)
        mock_current_user.has_permission = MagicMock(return_value=False)
        mock_current_user.is_super = False
        response = await client.get(
            '/api/v1/daily-production/daily-summary', params={'date': '2026-09-29'},
        )
        assert response.status_code == 403
```

再创建 `fastapi_app/tests/test_daily_production_monthly_fields.py`（设计规格 §8.1 点名的字段漂移守卫）：

```python
"""锁死月度汇总的字段口径漂移

背景（设计规格 §1.2 D-2 缺陷）：前端曾读 `overall_quantity`、而后端返回
`monthly_total_quantity`，`?? 0` 兜底掩盖了字段名不匹配，导致月报两个
头部 KPI 恒为 0。本文件把"三个口径必须一致"钉死。

注意：部门范围过滤在 SQL 的 WHERE 里完成，mock 会话不会执行它，因此
"范围外部门被排除"的断言在 test_daily_production_dept_scope.py 用端点
层测试覆盖；本文件只锁服务层输出的内部一致性与结构契约。
"""
from datetime import date
from unittest.mock import AsyncMock, MagicMock

from fastapi_app.services.daily_production_service import get_monthly_summary


def _mock_db_returning(rows):
    result = MagicMock()
    result.all.return_value = rows
    db = AsyncMock()
    db.execute = AsyncMock(return_value=result)
    return db


class TestMonthlySummaryFieldConsistency:
    async def test_monthly_total_matches_daily_and_department_sums(self):
        rows = [
            (date(2026, 9, 1), 'filling', 100, 700.0, 2),
            (date(2026, 9, 1), 'handcraft', 40, 360.0, 1),
            (date(2026, 9, 2), 'packaging', 7, 35.0, 1),
        ]
        db = _mock_db_returning(rows)

        out = await get_monthly_summary(db, 2026, 9)

        assert out['monthly_total_quantity'] == 147
        assert sum(d['total']['quantity'] for d in out['daily_data']) == 147
        assert sum(d['total_quantity'] for d in out['monthly_departments']) == 147

    async def test_every_day_carries_all_department_keys_and_total(self):
        # 前端按固定键名取数，键缺失会让整页崩在 Undefined 上
        db = _mock_db_returning([])

        out = await get_monthly_summary(db, 2026, 2)

        assert len(out['daily_data']) == 28
        for day in out['daily_data']:
            for key in ('filling', 'handcraft', 'packaging', 'total'):
                assert key in day
```

- [ ] **Step 2: 跑测试确认失败**

Run: `command python -m pytest fastapi_app/tests/test_daily_production_dept_scope.py fastapi_app/tests/test_daily_production_monthly_fields.py -q --no-header`
Expected: FAIL —— 范围测试因服务被调用时缺少 `departments` 关键字（`KeyError: 'departments'`）或 403 而失败；字段守卫文件**应当直接通过**（它锁的是既有行为，不是新行为）

- [ ] **Step 3: 改 `get_daily_summary`**

在 `fastapi_app/services/daily_production_service.py` 中把 `get_daily_summary` 的签名与首尾改为：

```python
async def get_daily_summary(
    db: AsyncSession,
    target_date: str,
    departments: set[str] | None = None,
) -> dict:
    """获取指定日期的各部门汇总

    Args:
        db: 只读会话。
        target_date: 目标日期 (YYYY-MM-DD)。
        departments: 可见部门集合；None 表示全部部门。范围外部门不出现在结果里。
    """
    d = parse_date_with_fallback(target_date)
    dept_keys = (
        list(PRODUCTION_DEPARTMENTS) if departments is None
        else [k for k in PRODUCTION_DEPARTMENTS if k in departments]
    )
    result = await db.execute(
        select(DailyProductionRecord)
        .where(
            DailyProductionRecord.production_date == d,
            DailyProductionRecord.department.in_(dept_keys),
        )
        .order_by(DailyProductionRecord.department, DailyProductionRecord.id)
    )
    records = list(result.scalars().all())
    price_fallback = await _build_product_price_fallback(db, records)
```

（`effective_unit_price` 与 `dept_data` 累加逻辑原样保留）

并把末尾的部门循环从 `for dept_key in ('filling', 'handcraft', 'packaging'):` 改为：

```python
    for dept_key in dept_keys:
```

**边界处理（不要加特判）**：`dept_keys` 在这两个函数里**不可能为空** —— `resolve_production_view_scope` 已在空集时 403，而 `narrow_departments` 返回的集合要么是用户的非空范围、要么是 `{requested}`，其中的部门键都来自 `PRODUCTION_DEPARTMENTS`。因此无需为空集写守卫；更重要的是**绝不能**把空集当作"不过滤"处理（那是 fail-open）。`/trend` 是唯一可能收到非法部门键的读接口（它接受原始 `department` 参数），其空集守卫见 Task 4。

- [ ] **Step 4: 改 `get_monthly_summary`**

签名与查询改为：

```python
async def get_monthly_summary(
    db: AsyncSession,
    year: int,
    month: int,
    departments: set[str] | None = None,
) -> dict:
    """获取月度汇总数据

    Args:
        db: 只读会话。
        year: 年份。
        month: 月份。
        departments: 可见部门集合；None 表示全部部门。
            注：daily_data 的每日条目仍保留三个部门键（范围外固定为 0），
            因此每日 total 自动只含范围内部门；monthly_departments 只列范围内部门。
    """
    start = date(year, month, 1)
    end = date(year, month, calendar.monthrange(year, month)[1])
    days_in_month = calendar.monthrange(year, month)[1]
    dept_keys = (
        list(PRODUCTION_DEPARTMENTS) if departments is None
        else [k for k in PRODUCTION_DEPARTMENTS if k in departments]
    )
```

查询的 `where(and_(...))` 追加一个条件：

```python
        .where(and_(
            DailyProductionRecord.production_date >= start,
            DailyProductionRecord.production_date <= end,
            DailyProductionRecord.department.in_(dept_keys),
        ))
```

并把月度部门汇总的循环从 `for dept_key in ('filling', 'handcraft', 'packaging'):` 改为：

```python
    for dept_key in dept_keys:
```

**约束**：`get_monthly_summary_for_auto()` 不传 `departments`，因此仍等价于全部门，行为不变。

- [ ] **Step 5: 改 `export_records`**

把 `department: str = ''` 参数替换为 `departments: set[str] | None = None`，并把条件构造改为：

```python
async def export_records(
    db: AsyncSession,
    *,
    start_date: str = '',
    end_date: str = '',
    departments: set[str] | None = None,
) -> bytes:
    """导出生产记录为 Excel（企业标准格式）

    Args:
        db: 只读会话。
        start_date: 区间起始日 (YYYY-MM-DD)。
        end_date: 区间结束日 (YYYY-MM-DD)，闭区间。
        departments: 可见部门集合；None 表示全部部门。
    """
    conditions = []
    range_start = parse_date_with_fallback(start_date) if start_date else None
    range_end = parse_date_with_fallback(end_date) if end_date else None
    if range_start and range_end and range_end < range_start:
        raise ValueError('结束日期不能早于开始日期')
    if range_start:
        conditions.append(DailyProductionRecord.production_date >= range_start)
    if range_end:
        conditions.append(DailyProductionRecord.production_date <= range_end)
    if departments is not None:
        conditions.append(DailyProductionRecord.department.in_(sorted(departments)))
```

（文件其余部分不变；若 `department` 变量在后续代码里还有引用，一并改为对 `conditions` 的使用）

- [ ] **Step 6: 改三个端点**

在 `fastapi_app/api/v1/endpoints/daily_production.py` 中：

`daily_summary` 与 `monthly_summary`：把 `_user: User = Depends(require_permission('production_summary_view'))` 替换为 `scope: set[str] | None = Depends(resolve_production_view_scope)`，并在调用处补 `departments=scope`。

`export_records` 端点：同样替换依赖，并把调用改为：

```python
        content = await daily_production_service.export_records(
            db,
            start_date=start_date,
            end_date=end_date,
            departments=narrow_departments(department, scope),
        )
```

- [ ] **Step 7: 跑测试确认通过**

Run: `command python -m pytest fastapi_app/tests/test_daily_production_dept_scope.py fastapi_app/tests/test_daily_production_monthly_fields.py -q --no-header`
Expected: PASS（9 passed）

- [ ] **Step 8: 确认没有回归**

Run: `command python -m pytest fastapi_app/tests/test_production_summary.py fastapi_app/tests/test_daily_production_trend.py fastapi_app/tests/test_daily_production_records_filter.py -q --no-header`
Expected: PASS

- [ ] **Step 9: lint + 提交**

Run: `command python -m ruff check fastapi_app/services/daily_production_service.py fastapi_app/api/v1/endpoints/daily_production.py`
Expected: 无输出

```bash
git add fastapi_app/services/daily_production_service.py fastapi_app/api/v1/endpoints/daily_production.py fastapi_app/tests/test_daily_production_dept_scope.py fastapi_app/tests/test_daily_production_monthly_fields.py
git commit -m "$(cat <<'EOF'
feat(production): 读接口按用户部门范围收窄

daily-summary / monthly-summary / records / trend / export 全部接入范围解析；
范围外部门参数被忽略而非 403。

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 7: 写入口范围校验（录入 / 编辑）

**Files:**
- Modify: `fastapi_app/services/daily_production_service.py`（新增 `get_record`）
- Modify: `fastapi_app/api/v1/endpoints/daily_production.py`（`create_record`、`update_record`）
- Test: `fastapi_app/tests/test_daily_production_write_scope.py`

**Interfaces:**
- Consumes: `resolve_production_write_scope`（Task 3）、`get_current_user_with_permissions`（Task 3）
- Produces:
  - `get_record(db: AsyncSession, record_id: int) -> DailyProductionRecord | None`
  - `_assert_department_writable(department: str, scope: set[str] | None) -> None`（端点模块内的辅助函数，越权时抛 403）

- [ ] **Step 1: 写失败的测试**

创建 `fastapi_app/tests/test_daily_production_write_scope.py`：

```python
"""写入口的部门范围校验"""
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi_app.core.deps import resolve_production_write_scope
from fastapi_app.main import app


def _write_scope_override(scope):
    app.dependency_overrides[resolve_production_write_scope] = lambda: scope


def _record(department):
    record = MagicMock()
    record.id = 7
    record.department = department
    return record


class TestCreateRecordScope:
    async def test_in_scope_department_is_accepted(self, client):
        _write_scope_override({'filling'})
        with patch(
            'fastapi_app.api.v1.endpoints.daily_production.daily_production_service'
        ) as mock_svc:
            mock_svc.create_record = AsyncMock(return_value=MagicMock())
            response = await client.post(
                '/api/v1/daily-production/records',
                json={
                    'department': 'filling', 'product_name': '白兔公仔',
                    'barcode': '690', 'unit_price': 7, 'quantity': 10,
                    'production_date': '2026-09-29', 'remark': '',
                },
            )
        assert response.status_code == 200

    async def test_out_of_scope_department_is_rejected_403(self, client):
        _write_scope_override({'filling'})
        with patch(
            'fastapi_app.api.v1.endpoints.daily_production.daily_production_service'
        ) as mock_svc:
            mock_svc.create_record = AsyncMock(return_value=MagicMock())
            response = await client.post(
                '/api/v1/daily-production/records',
                json={
                    'department': 'packaging', 'product_name': '白兔公仔',
                    'barcode': '690', 'unit_price': 7, 'quantity': 10,
                    'production_date': '2026-09-29', 'remark': '',
                },
            )
            mock_svc.create_record.assert_not_awaited()
        assert response.status_code == 403

    async def test_unscoped_user_can_write_any_department(self, client):
        _write_scope_override(None)
        with patch(
            'fastapi_app.api.v1.endpoints.daily_production.daily_production_service'
        ) as mock_svc:
            mock_svc.create_record = AsyncMock(return_value=MagicMock())
            response = await client.post(
                '/api/v1/daily-production/records',
                json={
                    'department': 'packaging', 'product_name': '白兔公仔',
                    'barcode': '690', 'unit_price': 7, 'quantity': 10,
                    'production_date': '2026-09-29', 'remark': '',
                },
            )
        assert response.status_code == 200


class TestUpdateRecordScope:
    async def test_records_own_department_governs_authorization(self, client):
        # 记录属于 packaging，用户只有 filling → 403
        _write_scope_override({'filling'})
        with patch(
            'fastapi_app.api.v1.endpoints.daily_production.daily_production_service'
        ) as mock_svc:
            mock_svc.get_record = AsyncMock(return_value=_record('packaging'))
            mock_svc.update_record = AsyncMock(return_value=MagicMock())
            response = await client.put(
                '/api/v1/daily-production/records/7',
                json={'quantity': 20},
            )
            mock_svc.update_record.assert_not_awaited()
        assert response.status_code == 403

    async def test_moving_record_into_out_of_scope_department_is_rejected(self, client):
        # 记录属于 filling（可写），但请求把部门改成 packaging → 403
        _write_scope_override({'filling'})
        with patch(
            'fastapi_app.api.v1.endpoints.daily_production.daily_production_service'
        ) as mock_svc:
            mock_svc.get_record = AsyncMock(return_value=_record('filling'))
            mock_svc.update_record = AsyncMock(return_value=MagicMock())
            response = await client.put(
                '/api/v1/daily-production/records/7',
                json={'department': 'packaging'},
            )
            mock_svc.update_record.assert_not_awaited()
        assert response.status_code == 403

    async def test_in_scope_update_succeeds(self, client):
        _write_scope_override({'filling'})
        with patch(
            'fastapi_app.api.v1.endpoints.daily_production.daily_production_service'
        ) as mock_svc:
            mock_svc.get_record = AsyncMock(return_value=_record('filling'))
            mock_svc.update_record = AsyncMock(return_value=MagicMock())
            response = await client.put(
                '/api/v1/daily-production/records/7',
                json={'quantity': 20},
            )
        assert response.status_code == 200

    async def test_missing_record_returns_404(self, client):
        _write_scope_override({'filling'})
        with patch(
            'fastapi_app.api.v1.endpoints.daily_production.daily_production_service'
        ) as mock_svc:
            mock_svc.get_record = AsyncMock(return_value=None)
            mock_svc.update_record = AsyncMock(return_value=MagicMock())
            response = await client.put(
                '/api/v1/daily-production/records/999',
                json={'quantity': 20},
            )
        assert response.status_code == 404
```

- [ ] **Step 2: 跑测试确认失败**

Run: `command python -m pytest fastapi_app/tests/test_daily_production_write_scope.py -q --no-header`
Expected: FAIL —— 越权请求返回 200（未校验）或 `AttributeError`

- [ ] **Step 3: 加 `get_record` 到服务层**

在 `fastapi_app/services/daily_production_service.py` 的 `# ==================== CRUD ====================` 段内、`create_record` 之前插入：

```python
async def get_record(db: AsyncSession, record_id: int) -> DailyProductionRecord | None:
    """按 id 取单条生产记录（不存在返回 None，不抛异常）。

    供端点做写权限校验与删除前快照使用。
    """
    result = await db.execute(
        select(DailyProductionRecord).where(DailyProductionRecord.id == record_id)
    )
    return result.scalar_one_or_none()
```

- [ ] **Step 4: 改端点**

在 `fastapi_app/api/v1/endpoints/daily_production.py` 中，import 段补：

```python
from fastapi_app.core.deps import (
    get_current_user_with_permissions,
    require_permission,
    resolve_production_view_scope,
    resolve_production_write_scope,
)
```

在 `router = APIRouter()` 之后加入辅助函数：

```python
def _assert_department_writable(department: str, scope: set[str] | None) -> None:
    """校验部门是否在用户可写范围内。

    Raises:
        HTTPException: 403 —— scope 非 None 且部门不在其中。
    """
    if scope is not None and department not in scope:
        raise HTTPException(
            status_code=403,
            detail=f'无权操作该部门（{department}）的生产数据',
        )
```

把 `create_record` 替换为：

```python
@router.post('/records', response_model=ProductionRecordActionResponse)
async def create_record(
    data: ProductionRecordCreate,
    scope: set[str] | None = Depends(resolve_production_write_scope),
    user: User = Depends(get_current_user_with_permissions),
    db: AsyncSession = Depends(get_async_db),
) -> ProductionRecordActionResponse:
    """创建生产记录。

    Args:
        data: 生产记录创建参数（部门、产品、条码、单价、数量、日期等）。
        scope: 用户可写部门范围（None 表示全部）。
        user: 当前登录用户，作为记录创建人。
        db: 异步数据库会话（读写主库）。

    Returns:
        ProductionRecordActionResponse: 包含成功标志和提示消息的响应。

    Raises:
        HTTPException: 403（部门越权）。
    """
    _assert_department_writable(data.department, scope)
    async with db_transaction(db):
        await daily_production_service.create_record(
            db,
            department=data.department,
            product_id=data.product_id,
            product_name=data.product_name,
            barcode=data.barcode,
            unit_price=data.unit_price,
            quantity=data.quantity,
            production_date_str=data.production_date,
            remark=data.remark or '',
            created_by=user.username if hasattr(user, 'username') else '',
        )
    return ProductionRecordActionResponse(success=True, message='生产记录创建成功')
```

把 `update_record` 替换为：

```python
@router.put('/records/{record_id}', response_model=ProductionRecordActionResponse)
async def update_record(
    record_id: int,
    data: ProductionRecordUpdate,
    scope: set[str] | None = Depends(resolve_production_write_scope),
    user: User = Depends(get_current_user_with_permissions),
    db: AsyncSession = Depends(get_async_db),
) -> ProductionRecordActionResponse:
    """更新生产记录。

    Args:
        record_id: 生产记录 ID。
        data: 生产记录更新参数（仅包含需要修改的字段）。
        scope: 用户可写部门范围（None 表示全部）。
        user: 当前登录用户，作为操作人。
        db: 异步数据库会话（读写主库）。

    Returns:
        ProductionRecordActionResponse: 包含成功标志和提示消息的响应。

    Raises:
        HTTPException: 404（记录不存在）、403（原部门或目标部门越权）。
    """
    async with db_transaction(db):
        record = await daily_production_service.get_record(db, record_id)
        if record is None:
            raise HTTPException(status_code=404, detail='记录不存在')
        # 原部门与目标部门都必须可写：既不能改别部门的数据，
        # 也不能把自己的数据「搬」到无权写入的部门
        _assert_department_writable(record.department, scope)
        if data.department is not None:
            _assert_department_writable(data.department, scope)
        update_data = data.model_dump(exclude_unset=True)
        await daily_production_service.update_record(
            db, record_id, created_by=user.username if hasattr(user, 'username') else '', **update_data
        )
    return ProductionRecordActionResponse(success=True, message='生产记录更新成功')
```

- [ ] **Step 5: 跑测试确认通过**

Run: `command python -m pytest fastapi_app/tests/test_daily_production_write_scope.py -q --no-header`
Expected: PASS（7 passed）

- [ ] **Step 6: lint + 提交**

Run: `command python -m ruff check fastapi_app/services/daily_production_service.py fastapi_app/api/v1/endpoints/daily_production.py`
Expected: 无输出

```bash
git add fastapi_app/services/daily_production_service.py fastapi_app/api/v1/endpoints/daily_production.py fastapi_app/tests/test_daily_production_write_scope.py
git commit -m "$(cat <<'EOF'
feat(production): 录入与编辑按部门范围校验

原部门与目标部门都必须可写，防止跨部门改数据或把数据搬到无权部门。

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 8: 删除 —— 范围校验 + 删除前审计快照

**Files:**
- Modify: `fastapi_app/services/daily_production_service.py:238-247`（`delete_record`）
- Modify: `fastapi_app/api/v1/endpoints/daily_production.py:139-157`（`delete_record` 端点）
- Test: `fastapi_app/tests/test_daily_production_delete_audit.py`

**Interfaces:**
- Consumes: `get_record`（Task 7）、`resolve_production_write_scope`、`_assert_department_writable`（Task 7）
- Produces: `delete_record(db: AsyncSession, record_id: int, *, operator: str = '') -> None`

- [ ] **Step 1: 写失败的测试**

创建 `fastapi_app/tests/test_daily_production_delete_audit.py`：

```python
"""删除：范围校验 + 删除前审计快照（物理删除，日志是唯一追溯手段）"""
import logging
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi_app.core.deps import resolve_production_write_scope
from fastapi_app.main import app
from fastapi_app.services.daily_production_service import delete_record


def _record(department='filling'):
    record = MagicMock()
    record.id = 7
    record.department = department
    record.product_name = '白兔公仔 40cm'
    record.barcode = '6901234'
    record.quantity = 620
    record.unit_price = 7
    record.production_date = date(2026, 9, 29)
    record.created_by = '张三'
    return record


class TestDeleteRecordAudit:
    async def test_snapshot_and_operator_are_logged_before_delete(self, caplog):
        db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = _record()
        db.execute = AsyncMock(return_value=result)

        with caplog.at_level(
            logging.INFO, logger='fastapi_app.services.daily_production_service',
        ):
            await delete_record(db, 7, operator='李四')

        text = caplog.text
        assert '白兔公仔 40cm' in text
        assert '6901234' in text
        assert '620' in text
        assert '2026-09-29' in text
        assert '张三' in text   # 原录单人
        assert '李四' in text   # 本次操作人
        db.delete.assert_awaited_once()

    async def test_missing_record_raises_value_error(self):
        db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=result)

        try:
            await delete_record(db, 999, operator='李四')
        except ValueError as exc:
            assert '不存在' in str(exc)
        else:
            raise AssertionError('记录不存在时应抛 ValueError')

        db.delete.assert_not_awaited()


class TestDeleteEndpointScope:
    async def test_out_of_scope_record_is_rejected_403(self, client):
        app.dependency_overrides[resolve_production_write_scope] = lambda: {'filling'}
        with patch(
            'fastapi_app.api.v1.endpoints.daily_production.daily_production_service'
        ) as mock_svc:
            mock_svc.get_record = AsyncMock(return_value=_record('packaging'))
            mock_svc.delete_record = AsyncMock(return_value=None)
            response = await client.delete('/api/v1/daily-production/records/7')
            mock_svc.delete_record.assert_not_awaited()
        assert response.status_code == 403

    async def test_in_scope_record_is_deleted_with_operator(self, client):
        app.dependency_overrides[resolve_production_write_scope] = lambda: {'filling'}
        with patch(
            'fastapi_app.api.v1.endpoints.daily_production.daily_production_service'
        ) as mock_svc:
            mock_svc.get_record = AsyncMock(return_value=_record('filling'))
            mock_svc.delete_record = AsyncMock(return_value=None)
            response = await client.delete('/api/v1/daily-production/records/7')
            called_kwargs = mock_svc.delete_record.await_args.kwargs
        assert response.status_code == 200
        assert called_kwargs['operator'] == 'admin'

    async def test_missing_record_returns_404(self, client):
        app.dependency_overrides[resolve_production_write_scope] = lambda: {'filling'}
        with patch(
            'fastapi_app.api.v1.endpoints.daily_production.daily_production_service'
        ) as mock_svc:
            mock_svc.get_record = AsyncMock(return_value=None)
            mock_svc.delete_record = AsyncMock(return_value=None)
            response = await client.delete('/api/v1/daily-production/records/999')
        assert response.status_code == 404
```

- [ ] **Step 2: 跑测试确认失败**

Run: `command python -m pytest fastapi_app/tests/test_daily_production_delete_audit.py -q --no-header`
Expected: FAIL —— `delete_record() got an unexpected keyword argument 'operator'`

- [ ] **Step 3: 改服务层**

把 `fastapi_app/services/daily_production_service.py` 中的 `delete_record` 替换为：

```python
async def delete_record(db: AsyncSession, record_id: int, *, operator: str = '') -> None:
    """删除生产记录（物理删除）。

    注意：本表没有软删除列，删除不可恢复；审计日志是事后唯一的追溯手段，
    因此**必须在 delete 之前**把完整快照写进日志。

    Args:
        db: 读写会话。
        record_id: 记录 ID。
        operator: 本次操作人用户名。

    Raises:
        ValueError: 记录不存在。
    """
    result = await db.execute(
        select(DailyProductionRecord).where(DailyProductionRecord.id == record_id)
    )
    record = result.scalar_one_or_none()
    if not record:
        raise ValueError('记录不存在')

    logger.info(
        f'生产记录删除: id={record.id} department={record.department} '
        f'product_name={record.product_name} barcode={record.barcode} '
        f'quantity={record.quantity} unit_price={record.unit_price} '
        f'production_date={record.production_date} record_created_by={record.created_by} '
        f'operator={operator}'
    )
    await db.delete(record)
```

- [ ] **Step 4: 改端点**

在 `fastapi_app/api/v1/endpoints/daily_production.py` 中把 `delete_record` 端点替换为：

```python
@router.delete('/records/{record_id}', response_model=ProductionRecordActionResponse)
async def delete_record(
    record_id: int,
    scope: set[str] | None = Depends(resolve_production_write_scope),
    user: User = Depends(get_current_user_with_permissions),
    db: AsyncSession = Depends(get_async_db),
) -> ProductionRecordActionResponse:
    """删除生产记录（不可恢复）。

    Args:
        record_id: 生产记录 ID。
        scope: 用户可写部门范围（None 表示全部）。
        user: 当前登录用户，作为操作人写入审计日志。
        db: 异步数据库会话（读写主库）。

    Returns:
        ProductionRecordActionResponse: 包含成功标志和提示消息的响应。

    Raises:
        HTTPException: 404（记录不存在）、403（部门越权）。
    """
    operator = user.username if hasattr(user, 'username') else ''
    async with db_transaction(db):
        record = await daily_production_service.get_record(db, record_id)
        if record is None:
            raise HTTPException(status_code=404, detail='记录不存在')
        _assert_department_writable(record.department, scope)
        await daily_production_service.delete_record(db, record_id, operator=operator)
    return ProductionRecordActionResponse(success=True, message='生产记录删除成功')
```

- [ ] **Step 5: 跑测试确认通过**

Run: `command python -m pytest fastapi_app/tests/test_daily_production_delete_audit.py -q --no-header`
Expected: PASS（5 passed）

- [ ] **Step 6: lint + 提交**

Run: `command python -m ruff check fastapi_app/services/daily_production_service.py fastapi_app/api/v1/endpoints/daily_production.py`
Expected: 无输出

```bash
git add fastapi_app/services/daily_production_service.py fastapi_app/api/v1/endpoints/daily_production.py fastapi_app/tests/test_daily_production_delete_audit.py
git commit -m "$(cat <<'EOF'
feat(production): 删除前写审计快照，并按部门范围校验

物理删除不可恢复，日志是唯一追溯手段，快照必须早于 delete 落盘。

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 9: 导航可见性（只有部门码的用户也能看到入口）

**Files:**
- Modify: `fastapi_app/core/nav_context.py:19-21`（`SPECIAL_PERMISSION_MAP`）与 `:127-132`（抽出纯函数 `nav_permission_codes`）
- Test: `fastapi_app/tests/test_production_nav_visibility.py`

**Interfaces:**
- Consumes: `production_scope.PRODUCTION_DEPARTMENTS`、`view_code()`（Task 1）
- Produces: `nav_permission_codes(code: str) -> list[str]`

- [ ] **Step 1: 写失败的测试**

创建 `fastapi_app/tests/test_production_nav_visibility.py`：

```python
"""导航权限码展开：部门码用户也要能看到「生产报表」入口"""
from fastapi_app.core.nav_context import nav_permission_codes


class TestNavPermissionCodes:
    def test_production_nav_lists_aggregate_and_three_dept_codes(self):
        codes = nav_permission_codes('production_summary_view')
        assert codes == [
            'production_summary_view',
            'production_summary_view_filling',
            'production_summary_view_handcraft',
            'production_summary_view_packaging',
        ]

    def test_outsource_mapping_unchanged(self):
        # 既有映射行为不得改变
        assert nav_permission_codes('outsource_manage') == ['outsource_manage', 'outsource_view']

    def test_unmapped_code_falls_back_to_itself(self):
        assert nav_permission_codes('product_manage') == ['product_manage']

    def test_code_always_present_in_result(self):
        for code in ('production_summary_view', 'outsource_manage', 'permission_manage'):
            assert code in nav_permission_codes(code)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `command python -m pytest fastapi_app/tests/test_production_nav_visibility.py -q --no-header`
Expected: FAIL —— `ImportError: cannot import name 'nav_permission_codes'`

- [ ] **Step 3: 写实现**

在 `fastapi_app/core/nav_context.py` 中：

a) 把 `SPECIAL_PERMISSION_MAP`（19-21 行）替换为：

```python
SPECIAL_PERMISSION_MAP = {
    'outsource_manage': ['outsource_manage', 'outsource_view'],
    # 生产报表按部门拆权限后，只有部门码的用户也要能看到导航入口；
    # 任持其一即可见（前端侧栏按 permission_codes 做「任一命中」判断）。
    'production_summary_view': [
        'production_summary_view',
        'production_summary_view_filling',
        'production_summary_view_handcraft',
        'production_summary_view_packaging',
    ],
}


def nav_permission_codes(code: str) -> list[str]:
    """展开某导航项允许的权限码集合（任一命中即显示该入口）。

    Args:
        code: 导航项自身的权限码。

    Returns:
        权限码列表，**必然包含 code 自身**（这样被单独分配了具体权限、
        而没有父级权限的用户也能看到对应导航项）。
    """
    mapped = SPECIAL_PERMISSION_MAP.get(code, [code])
    codes = mapped if isinstance(mapped, list) else [mapped]
    if code not in codes:
        codes = [code, *codes]
    return codes
```

b) 把 `get_nav_sections_async` 内联的那段（原来的 127-132 行）替换为对该函数的调用：

```python
            perm_codes = nav_permission_codes(item.code)
```

（删除原有的 `if not isinstance(...)` 与 `if item.code not in perm_codes:` 两段 —— 逻辑已移入纯函数，行为逐字保持）

- [ ] **Step 4: 跑测试确认通过**

Run: `command python -m pytest fastapi_app/tests/test_production_nav_visibility.py -q --no-header`
Expected: PASS（4 passed）

- [ ] **Step 5: 确认没有回归**

Run: `command python -m pytest fastapi_app/tests/ -q --no-header -k "nav or auth or permission"`
Expected: PASS

- [ ] **Step 6: lint + 提交**

Run: `command python -m ruff check fastapi_app/core/nav_context.py fastapi_app/tests/test_production_nav_visibility.py`
Expected: 无输出

```bash
git add fastapi_app/core/nav_context.py fastapi_app/tests/test_production_nav_visibility.py
git commit -m "$(cat <<'EOF'
feat(production): 生产报表导航对部门权限码用户可见

把导航权限码展开抽成纯函数 nav_permission_codes，行为保持不变。

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 10: 收尾 —— 全量回归与上线顺序核对

**Files:**
- 无代码改动（如回归暴露问题，回到对应任务修复）

- [ ] **Step 1: 跑全部相关测试**

Run: `command python -m pytest fastapi_app/tests/ -q --no-header -k "production or scope or nav"`
Expected: PASS

- [ ] **Step 2: 跑更宽的回归（确认没碰坏别的模块）**

Run: `command python -m pytest fastapi_app/tests/ -q --no-header`
Expected: 与改动前**完全相同的**通过 / 失败集合。

> 本机存在与本次改动无关的既有失败（环境差异所致）。判定方法：对每个失败先确认它是否触及 `daily_production` / `production_scope` / `nav_context`；若否，再到改动前的基线提交上跑同一个测试，确认它本来就失败。**既有失败不要修**，也不要在本次改动里"顺手"改掉 —— 只需在 PR 描述里点名列出（含测试名与失败原因一句话）。

- [ ] **Step 3: ruff 全量检查改动涉及的文件**

Run: `command python -m ruff check fastapi_app/core/production_scope.py fastapi_app/core/deps.py fastapi_app/core/nav_context.py fastapi_app/services/daily_production_service.py fastapi_app/api/v1/endpoints/daily_production.py fastapi_app/schemas/daily_production.py scripts/init_production_dept_permissions.py`
Expected: 无输出

- [ ] **Step 4: 逐条核对设计规格的上线顺序（§5.5）**

手工确认，逐条打勾，**任何一条不满足就不得发布**：

- [ ] 6 个部门权限点已在目标环境写入（`python scripts/init_production_dept_permissions.py` 输出 `完成：新增 6 个，跳过 0 个`）
- [ ] 每个部门用户已被勾选对应部门码（在用户管理页核对，或直连生产库 `SELECT u.username, p.code FROM user u JOIN user_permission up ON up.user_id=u.id JOIN permission p ON p.id=up.permission_id WHERE p.code LIKE 'production_summary_%'`）
- [ ] 厂长/老板类账号仍持有聚合码 `production_summary_view`（否则会从"全部部门"降级成空范围 → 403）
- [ ] 用一个**只有充棉部码**的测试账号验证：导航能看到「生产报表」、日报只出现充棉部、录入`packaging` 返回 403
- [ ] 用聚合码账号验证：三个部门都可见、录入任意部门成功
- [ ] 用**没有任何生产权限**的账号验证：接口 403、导航无入口

- [ ] **Step 5: 记录遗留技术债（不实现，只登记）**

在设计规格 `docs/superpowers/specs/2026-09-29-production-cockpit-design.md` 的 §9.1 追加一行已知技术债：

```markdown
| R7 | `daily_production_record` 无软删除列，删除不可恢复 | 本期以「删除前审计快照 + 二次确认 + 不做批量删除」控制风险（§6.5 / D12）；软删除（`is_deleted` + 全部读路径过滤）列入后续 |
```

- [ ] **Step 6: 提交**

```bash
git add docs/superpowers/specs/2026-09-29-production-cockpit-design.md
git commit -m "$(cat <<'EOF'
docs: 登记生产记录软删除技术债（R7）

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## 规格中不在本计划范围内的部分（交由 Plan B）

明确划出边界，避免执行者去找这些内容：

| 规格位置 | 内容 | 归属 |
|---|---|---|
| §4 信息架构 | PC 一屏驾驶舱、明细抽屉、移动端 M2、旧日报/月报内容的去向 | Plan B |
| §6.4 | 月报字段一致性修正的**前端**一半（`frontend-vite/src/types/index.ts:428-430` 两行"历史兼容字段"注释删除、面板改读 `monthly_total_quantity`） | Plan B（后端侧无改动 —— `MonthlySummaryResponse` 本身没有 `overall_*` 字段，无需"移除误导"；后端只需 Task 6 的月度字段守卫测试） |
| §7 | 前端文件清单、token 统一、空态/骨架、组件拆分 | Plan B |
| §8.2 | 前端 vitest 用例 | Plan B |
| §8.3 | 全链路手工验证（PC + 移动 + 三账号 + 两种分辨率） | Plan B（Task 10 Step 4 只覆盖后端接口层的三账号核对） |
| §3 D9 / D10 | 移动端形态与范围 | Plan B |

---

## 完成标准

Plan A 完成的判定（全部满足）：

1. 10 个任务的测试全部通过，且 `ruff check` 无输出。
2. 用聚合码账号、部门码账号、无权限账号三种身份，对 `daily-summary` / `monthly-summary` / `records` / `trend` / `export` 的可见数据符合各自范围；`POST`/`PUT`/`DELETE` 的越权路径返回 403。
3. `GET /records` 支持日期区间（可跨月）、录单人筛选、排序，且 `year/month` 省略时行为与规格 §6.3 一致。
4. `GET /trend` 跨月返回逐日补零数据，区间上限 92 天、反向区间 400。
5. 删除前的日志里能找到 id / 部门 / 产品名 / 69码 / 数量 / 单价 / 日期 / 原录单人 / 本次操作人。
6. Task 10 的上线顺序 6 条核对全部打勾。

**本计划不含**：任何前端改动（`.vue` / `api/production.ts` / `types`）与移动端 —— 见 Plan B。
