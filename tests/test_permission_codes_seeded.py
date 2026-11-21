"""权限码覆盖门禁（审计 Top30 #29）：端点 require_* 的每个字面码必须「可达」。

背景（2026-11-20 审计）：`require_permission('beile_order_confirm')` 这类码只由
迁移 `pg_standalone_044/048` 的 `INSERT..SELECT` 依赖父码种入，而父码
`beile_order_view` 只由 seed_nav 种——空库按「alembic → init_permissions --yes →
seed_nav」重建时 INSERT..SELECT 静默零行，码永久缺失，页面全员 403（M-8）。
同类问题历史上还有 report 行内码（2026-10-09 High-2，已由 init_permissions 补齐）。

可达性判据（三选一，缺一即红）：
1. **种子链定义**：`scripts/init_permissions.py::PERMISSIONS_CONFIG`（父+子）
   或 `scripts/seed_nav.py::NAV_SEED` 有该码；
2. **迁移种入**：在下方 ALLOWLIST 显式登记（条目必须注明迁移文件名）；
3. **命名派生**：`<x>_view` 可由已种入的 `<x>_manage` 经
   `User.has_permission`（shared_models/user.py:106-112）放行——不依赖权限表行。

新增端点字面码不满足任一条 → 本测试红：「重建环境全员 403」在 CI 就拦下，
不再等新机部署才爆。只认 require_permission / require_any_permission /
require_superuser 的**字面量**实参（经模块常量传入的形态见
fastapi_app/tests/test_customer_sampling_permission.py 等专项测试）。
"""
from __future__ import annotations

import ast
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENDPOINTS_DIR = PROJECT_ROOT / 'fastapi_app' / 'api' / 'v1' / 'endpoints'
INIT_PERM_FILE = PROJECT_ROOT / 'scripts' / 'init_permissions.py'
SEED_NAV_FILE = PROJECT_ROOT / 'scripts' / 'seed_nav.py'

#: 迁移种入、init_permissions/seed_nav 均不含的字面码（条目注明种入来源）。
#: 新增条目前先确认该迁移在空库上确实能种出此码（不依赖更上游的父码行）。
MIGRATION_SEED_ALLOWLIST: dict[str, str] = {
    'batch_import': 'migrations/versions/pg_standalone_043_seed_missing_permissions.py'
    '（batch_manage 的子权限，父码由 init_permissions/迁移种入）',
}

_GATE_HELPERS = {'require_permission', 'require_any_permission', 'require_superuser'}


def _collect_code_keys(value: object, out: set[str]) -> None:
    """递归收集结构里所有 'code' 键的字符串值（兼容两种种子形状：
    PERMISSIONS_CONFIG 是 {模块: {parent:{code}, children:[{code}]}}；
    NAV_SEED 是 [{code: ...}]）。"""
    if isinstance(value, dict):
        code = value.get('code')
        if isinstance(code, str):
            out.add(code)
        for v in value.values():
            _collect_code_keys(v, out)
    elif isinstance(value, (list, tuple, set)):
        for item in value:
            _collect_code_keys(item, out)


def _literal_codes_from_assign(tree: ast.AST, name: str) -> set[str]:
    """取模块级 `NAME = <纯字面量容器>`（含 `NAME: T = ...` 注解赋值）里的全部权限码。"""
    for node in tree.body:  # 只看模块级赋值
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets = [node.target]
        else:
            continue
        if not any(isinstance(t, ast.Name) and t.id == name for t in targets):
            continue
        try:
            value = ast.literal_eval(node.value)
        except (ValueError, SyntaxError):
            continue
        out: set[str] = set()
        _collect_code_keys(value, out)
        return out
    raise AssertionError(f'未能在种子文件里找到 {name} 的模块级字面量定义（结构已变）')


def _seeded_codes() -> set[str]:
    config_codes = _literal_codes_from_assign(
        ast.parse(INIT_PERM_FILE.read_text(encoding='utf-8')), 'PERMISSIONS_CONFIG')
    seed_codes = _literal_codes_from_assign(
        ast.parse(SEED_NAV_FILE.read_text(encoding='utf-8')), 'NAV_SEED')
    return config_codes | seed_codes


def _endpoint_literal_codes() -> set[str]:
    codes: set[str] = set()
    files = sorted(ENDPOINTS_DIR.rglob('*.py'))
    assert files, f'{ENDPOINTS_DIR} 下没有端点文件（目录改名会让本测试静默空转）'
    for path in files:
        tree = ast.parse(path.read_text(encoding='utf-8'))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id in _GATE_HELPERS):
                continue
            for arg in node.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    codes.add(arg.value)
    return codes


def test_every_endpoint_literal_code_is_reachable() -> None:
    """每个字面码要么有种、要么迁移种入、要么 manage→view 命名派生可达。"""
    seeded = _seeded_codes()
    assert 'order_manage' in seeded, '种子集提取失败（结构探测哨兵）'
    unreachable = []
    for code in sorted(_endpoint_literal_codes()):
        if code in seeded or code in MIGRATION_SEED_ALLOWLIST:
            continue
        # manage→view 命名派生：持 <x>_manage 即通过 <x>_view（user.py:106-112），
        # 不需要权限表里真的有 <x>_view 行。
        if code.endswith('_view') and (code[:-len('_view')] + '_manage') in seeded:
            continue
        unreachable.append(code)
    assert not unreachable, (
        '这些端点权限码在「空库重建链」（alembic → init_permissions --yes → seed_nav）'
        f'上不可达，重建后对应端点对非超管全员 403：{unreachable}\n'
        '  修法三选一：①加入 init_permissions.PERMISSIONS_CONFIG（父或子）；'
        '②加入 seed_nav.NAV_SEED（顶层行，参考 outsource_view 的职责分离注释）；'
        '③确认由迁移种入 → 登记进 MIGRATION_SEED_ALLOWLIST 并注明迁移文件。'
    )


def test_gate_helper_names_still_match() -> None:
    """守卫自身的哨兵：依赖工厂改名时让本文件显式红，而不是静默空转。"""
    sample = ast.parse(
        (ENDPOINTS_DIR / 'product.py').read_text(encoding='utf-8'))
    found = {n.func.id for n in ast.walk(sample)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
             and n.func.id in _GATE_HELPERS}
    assert found, 'product.py 里找不到任何 require_* 调用——_GATE_HELPERS 名单已过期'
