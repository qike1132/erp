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


# --- 加密备份的凭据闸门（2026-11-18 补口） ---------------------------------
#
# 语义链：`_SUPERUSER_ONLY` 宣称「包内含现役私钥与 .env，备份读写权限不该等价于
# 凭据读取权限」，但 `GET /export-info` 与 `POST /full` 只要 `backup_create`
# （回退 backup_manage）—— 非超管传 encrypt=true 就能生成含凭据的包。
# 修法不是把这两个端点整个收成超管（明文包已排除敏感配置，业务数据在
# backup_create 内合理），而是按「本次是否加密」拦。


class _StubUser:
    def __init__(self, is_super: bool) -> None:
        self.is_super = is_super


def test_encrypted_backup_gate_blocks_non_superuser() -> None:
    """非超管 + 加密 → 403；明文 → 放行（这次改动唯一的行为保证）。"""
    from fastapi import HTTPException

    from fastapi_app.api.v1.endpoints.backup._deps import (
        require_superuser_for_encrypted_backup,
    )

    # 明文（effective_encrypt=False）：不拦 —— 明文包不含敏感配置
    require_superuser_for_encrypted_backup(_StubUser(False), effective_encrypt=False)
    # 加密 + 非超管：必须 403
    with pytest.raises(HTTPException) as exc:
        require_superuser_for_encrypted_backup(_StubUser(False), effective_encrypt=True)
    assert exc.value.status_code == 403
    assert '仅超级管理员' in str(exc.value.detail)
    # 加密 + 超管：放行
    require_superuser_for_encrypted_backup(_StubUser(True), effective_encrypt=True)
    # 缺 is_super 属性的对象（如内部 dummy user）按非超管处理，不能放行
    with pytest.raises(HTTPException):
        require_superuser_for_encrypted_backup(object(), effective_encrypt=True)


def test_both_encrypting_endpoints_call_the_gate() -> None:
    """接线断言：两个会产出加密包的端点必须真的调用守卫。

    只测 `require_superuser_for_encrypted_backup` 本身是不够的 —— 把端点里那行
    调用删掉，函数级用例仍然全绿（这正是上一批踩过的坑：测函数不测接线）。
    """
    expected = {
        'export.py': 'get_backup_info',          # GET /export-info
        'actions.py': 'trigger_full_backup',     # POST /full
    }
    missing: list[str] = []
    for filename, handler in expected.items():
        tree = ast.parse((BACKUP_DIR / filename).read_text(encoding='utf-8'))
        handler_node = next(
            (n for n in ast.walk(tree)
             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == handler),
            None,
        )
        assert handler_node is not None, f'{filename} 里找不到端点函数 {handler}'
        calls_gate = any(
            isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
            and n.func.id == 'require_superuser_for_encrypted_backup'
            for n in ast.walk(handler_node)
        )
        if not calls_gate:
            missing.append(f'{filename}::{handler}')
    assert not missing, (
        '这些端点会产出加密包（含现役私钥与运行时 .env），但没有调用凭据闸门：'
        f'{missing}\n  非超管传 encrypt=true 即可生成含凭据的备份包。'
    )


def test_plaintext_backup_still_excludes_sensitive_config() -> None:
    """前提断言：明文包确实排除敏感配置 —— 否则「只拦加密」这个设计不成立。

    如果哪天 `_write_config_files` 不再按 `include_sensitive_config` 排除，
    「明文包不含凭据」这个前提就塌了，而本文件的放行分支会静默变成漏洞。
    """
    core = (PROJECT_ROOT / 'fastapi_app' / 'services' / 'backup'
            / 'orchestration' / 'core.py').read_text(encoding='utf-8')
    assert 'should_exclude_file(file_path, archive_path, include_sensitive_config)' in core, (
        '明文/加密的敏感配置分流不见了（core.py::_write_config_files）—— '
        '「明文包不含凭据」这个前提失效，请同步收紧 require_superuser_for_encrypted_backup'
    )
    assert 'excluded.append(archive_path)' in core, '被排除清单不再记录，无法审计排除结果'
