"""备份包的产出/下载/还原端点仅超管可用，且**闸门真的接线到端点**。

备份包内含运行时 .env、现役 JWT 私钥、上传签名密钥与全库用户口令哈希，
「备份读写权限」不该等价于「凭据读取权限」。只读列表/状态保持原细粒度权限。

2026-11-18 审计 F1【P0】
-----------------------
本文件的原始版本只有两个 `assert name in _SUPERUSER_ONLY` —— 只断言集合成员，
**不断言闸门接线**。把某个端点的
`Depends(require_backup_permission('download_server_backup'))` 改成
`Depends(require_any_permission('backup_read'))`，测试仍全绿，而那就是
「非超管能导出含私钥的整库备份」这条红线本身。同理，往集合里加一个没人挂的
名字也会让人误以为它受保护。

现在锁四件事，缺任一条都能让红线静默失效：

1. **正向接线**：`_SUPERUSER_ONLY` 里每个名字都必须真有端点在用（AST 扫端点文件）。
   「集合里有名字、端点没挂」= 假保护。
2. **行为判据**：每个敏感名字的依赖工厂真的走 `require_superuser` 分支 ——
   按闭包 `__qualname__` 断言（`require_superuser.<locals>.superuser_checker`）。
   这是行为级的：把 `_deps.py:151` 的 `if endpoint_name in _SUPERUSER_ONLY`
   判断改坏，本用例立刻红。
3. **反向行为**：只读端点仍走细粒度分支
   （`require_any_permission.<locals>.permission_checker`）—— 防「过度收紧把只读
   用户全挡在门外」这种反向事故。
4. **拼写守卫**：端点里出现的每个 `require_backup_permission('<name>')` 实参必须
   在 `_get_backup_permission` 的映射表里、或在 `_SUPERUSER_ONLY` 里、或在下面
   显式登记的回退名单里。否则一个拼写错会静默回退到 `backup_manage`，
   门禁看起来有权限、实际是错的语义。
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKUP_DIR = PROJECT_ROOT / 'fastapi_app' / 'api' / 'v1' / 'endpoints' / 'backup'
DEPS_FILE = BACKUP_DIR / '_deps.py'

#: 依赖 `_get_backup_permission` 的默认回退（`backup_manage`）的端点。
#: 这三个是备份**调度**的增改删，仓库既有设计让它们落到 `backup_manage`
#: （见 `_deps.py` 里「生产 permission 表只有 backup_manage」的说明）。
#: 显式登记而不是让它们静默回退：将来有人写错别的名字时要能红。
KNOWN_PERMISSION_FALLBACK: frozenset[str] = frozenset({
    'create_backup_schedule',
    'update_backup_schedule',
    'delete_backup_schedule',
})

_SUPERUSER_QUALNAME = 'require_superuser.<locals>.superuser_checker'
_ANY_PERMISSION_QUALNAME = 'require_any_permission.<locals>.permission_checker'


def _const_str_set(tree: ast.AST, name: str) -> set[str]:
    """取 `NAME = frozenset({...})` / `NAME = {...}` 里的字符串常量。"""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
            continue
        value = node.value
        if isinstance(value, ast.Call) and isinstance(value.func, ast.Name) \
                and value.func.id == 'frozenset' and value.args:
            value = value.args[0]
        if isinstance(value, (ast.Set, ast.List, ast.Tuple)):
            return {e.value for e in value.elts if isinstance(e, ast.Constant)}
    raise AssertionError(f'未能在 {DEPS_FILE} 找到 {name} 的字面量定义（结构已变）')


def _permission_map_keys() -> set[str]:
    """`_get_backup_permission` 里 `permission_map = {...}` 的键集合。"""
    tree = ast.parse(DEPS_FILE.read_text(encoding='utf-8'))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(t, ast.Name) and t.id == 'permission_map' for t in node.targets):
            continue
        if isinstance(node.value, ast.Dict):
            return {k.value for k in node.value.keys if isinstance(k, ast.Constant)}
    raise AssertionError(f'未能在 {DEPS_FILE} 找到 permission_map 的 dict 字面量')


def _wired_endpoint_names() -> dict[str, list[str]]:
    """扫端点文件，返回 {权限名: [挂载它的文件名]}。

    只认 `Depends(require_backup_permission('<字面量>'))` 形态；参数不是字面量时
    无法静态判定，此时**不**记账（下一条用例会因为它既不在映射表也不在回退名单
    而报出来，不会静默放过）。
    """
    wired: dict[str, list[str]] = {}
    files = sorted(p for p in BACKUP_DIR.glob('*.py') if p.name != '__init__.py')
    assert files, f'{BACKUP_DIR} 下没有端点文件（目录改名会让本测试静默空转）'
    for path in files:
        tree = ast.parse(path.read_text(encoding='utf-8'))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == 'require_backup_permission'):
                continue
            if node.args and isinstance(node.args[0], ast.Constant) \
                    and isinstance(node.args[0].value, str):
                wired.setdefault(node.args[0].value, []).append(path.name)
    return wired


def _superuser_only() -> set[str]:
    return _const_str_set(ast.parse(DEPS_FILE.read_text(encoding='utf-8')), '_SUPERUSER_ONLY')


# --- 1. 正向接线：集合里每个名字都真有端点挂 ---------------------------------

def test_every_superuser_name_is_wired_to_an_endpoint() -> None:
    """集合里有名字但没人挂 = 假保护（审计 F1 的核心指控）。"""
    wired = _wired_endpoint_names()
    unwired = sorted(_superuser_only() - set(wired))
    assert not unwired, (
        f'这些名字在 _SUPERUSER_ONLY 里，却没有任何端点用 '
        f'require_backup_permission 挂它们：{unwired}\n'
        '  要么端点漏挂闸门（非超管可下载含私钥的备份包），'
        '要么名字该从集合里删掉。'
    )


def test_superuser_only_is_not_empty() -> None:
    """集合本身不能退化成空集 —— 空集能让上面那条断言恒真。"""
    assert len(_superuser_only()) >= 9, sorted(_superuser_only())


# --- 2/3. 行为判据：真的走 require_superuser，只读端点真的不走 ------------

def test_sensitive_endpoints_resolve_to_superuser_dependency() -> None:
    """行为级：把 `_deps.py` 里的 `if endpoint_name in _SUPERUSER_ONLY` 改坏即红。"""
    from fastapi_app.api.v1.endpoints.backup._deps import (
        _SUPERUSER_ONLY,
        require_backup_permission,
    )

    wrong = []
    for name in sorted(_SUPERUSER_ONLY):
        dep = require_backup_permission(name)
        qualname = getattr(dep, '__qualname__', '')
        if qualname != _SUPERUSER_QUALNAME:
            wrong.append((name, qualname))
    assert not wrong, (
        f'这些端点没有走 require_superuser 分支（实际闭包：{wrong}）—— '
        '非超管能触达含运行时 .env 与私钥的备份包。'
    )


@pytest.mark.parametrize('name', ['list_server_backups', 'backup_status', 'get_backup_records'])
def test_read_only_endpoints_stay_fine_grained(name: str) -> None:
    """反向：只读端点不得被收窄成超管（否则只读运维全被 403 挡死）。"""
    from fastapi_app.api.v1.endpoints.backup._deps import require_backup_permission

    dep = require_backup_permission(name)
    assert getattr(dep, '__qualname__', '') == _ANY_PERMISSION_QUALNAME, name


# --- 4. 拼写守卫：实参必须在映射表 / 超管集合 / 显式回退名单里 --------------

def test_every_wired_name_has_a_defined_permission_semantics() -> None:
    """拼错的 name 会静默回退到 `backup_manage`，门禁看起来有权限、语义是错的。"""
    known = _permission_map_keys() | _superuser_only() | set(KNOWN_PERMISSION_FALLBACK)
    unknown = sorted(set(_wired_endpoint_names()) - known)
    assert not unknown, (
        f'这些 require_backup_permission 实参既不在 _get_backup_permission 的映射表，'
        f'也不在 _SUPERUSER_ONLY 或 KNOWN_PERMISSION_FALLBACK 里：{unknown}\n'
        '  它们会静默回退到 backup_manage（权限语义错误，且无人察觉）。'
    )


def test_known_fallback_is_not_stale() -> None:
    """回退名单不允许腐烂：端点改名/补进映射表后必须删掉条目。"""
    wired = set(_wired_endpoint_names())
    mapped = _permission_map_keys() | _superuser_only()
    stale = sorted(n for n in KNOWN_PERMISSION_FALLBACK if n not in wired or n in mapped)
    assert not stale, f'KNOWN_PERMISSION_FALLBACK 里的条目已失效，请删除：{stale}'
