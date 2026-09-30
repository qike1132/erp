"""还原前安全备份闸门：默认 fail-closed，显式开关才放行。

背景（/backup 审计，high）
-------------------------
`create_pre_restore_backup()` 失败时返回 `{'success': False, ...}` 而**不抛异常**
（服务层注释明写「不阻塞恢复」，是有意设计）。三个端点此前都把这个结果**原样塞进
响应体**就继续走破坏性还原 —— 界面从不读 `pre_restore_backup.success === false`，
于是「整库被覆盖且没有任何回滚点」在无人知情的情况下发生。

修法尊重原设计意图（不禁止放行），只把**静默**变成**知情选择**：默认拒绝（428），
显式传 `allow_missing_pre_restore_backup=true` 才继续。

本文件锁两件事：
1. `_require_pre_restore_backup` 自身的判定边界（含缺字段的 fail-closed）；
2. 每个 `create_pre_restore_backup` 调用点**后面**都紧跟一次闸门调用 —— 静态守卫，
   防止将来新增还原路径时漏掉这一道。
"""
from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest
from fastapi import HTTPException

from fastapi_app.api.v1.endpoints.backup import restore as restore_mod
from fastapi_app.api.v1.endpoints.backup.restore import _require_pre_restore_backup

_RESTORE_PY = Path(restore_mod.__file__)


# ---------------------------------------------------------------------------
# 判定边界
# ---------------------------------------------------------------------------

def test_success_backup_passes() -> None:
    _require_pre_restore_backup({'success': True, 'filename': 'pre.zip'}, allowed=False)


def test_failed_backup_blocks_by_default() -> None:
    with pytest.raises(HTTPException) as ei:
        _require_pre_restore_backup({'success': False, 'error': '磁盘已满'}, allowed=False)

    assert ei.value.status_code == 428
    detail = str(ei.value.detail)
    assert '磁盘已满' in detail, '必须把失败原因透传给运维'
    assert 'allow_missing_pre_restore_backup=true' in detail, '必须给出显式放行的方法'


def test_failed_backup_passes_when_explicitly_allowed() -> None:
    _require_pre_restore_backup({'success': False, 'error': '磁盘已满'}, allowed=True)


@pytest.mark.parametrize('pre_info', [{}, {'error': 'x'}, {'success': None}])
def test_missing_success_flag_is_treated_as_failure(pre_info: dict) -> None:
    """fail-closed：只有**显式** `success is True` 才算成功。

    缺字段/None/空字典都当作「没做成」，而不是「没报错所以没事」。
    """
    with pytest.raises(HTTPException):
        _require_pre_restore_backup(pre_info, allowed=False)


def test_missing_success_flag_unknown_reason_still_actionable() -> None:
    with pytest.raises(HTTPException) as ei:
        _require_pre_restore_backup({}, allowed=False)

    assert '未知原因' in str(ei.value.detail)


# ---------------------------------------------------------------------------
# 每个调用点后面都跟着闸门（静态守卫）
# ---------------------------------------------------------------------------

def _function_spans(tree: ast.Module) -> list[tuple[str, int, int]]:
    spans = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            spans.append((node.name, node.lineno, node.end_lineno or node.lineno))
    return spans


def _call_lines(tree: ast.Module, func_name: str) -> list[int]:
    """被调函数名为 `func_name` 的调用所在行号。"""
    lines = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, (ast.Name, ast.Attribute)):
            name = node.func.id if isinstance(node.func, ast.Name) else node.func.attr
            if name == func_name:
                lines.append(node.lineno)
    return sorted(lines)


_RESTORE_ENTRY_POINTS = (
    'import_backup',
    'restore_server_backup',
    '_run_async_file_restore',
)


def test_pre_restore_backup_has_a_single_guarded_chokepoint() -> None:
    """落安全备份 + 过闸门只能有一处实现（`_pre_restore_info_or_fail`），且闸门在里面。

    三个还原入口各自复制 try/except 时，任何一条路径漏写闸门就是一条**无回滚点的
    破坏性还原**；集中成一个函数后，"漏掉"变成不可能，除非有人绕开它直接调
    `create_pre_restore_backup` —— 那正是本测试要拦的。
    """
    tree = ast.parse(_RESTORE_PY.read_text(encoding='utf-8'))

    create_lines = _call_lines(tree, 'create_pre_restore_backup')
    assert len(create_lines) == 1, (
        f'create_pre_restore_backup 应只在闸门函数里调用一次，实际行 {create_lines} —— '
        '多出来的调用点绕过了闸门'
    )

    helper_span = next((lo, hi) for name, lo, hi in _function_spans(tree)
                       if name == '_pre_restore_info_or_fail')
    assert helper_span[0] <= create_lines[0] <= helper_span[1], (
        'create_pre_restore_backup 必须写在 _pre_restore_info_or_fail 内部'
    )

    guard_lines = _call_lines(tree, '_require_pre_restore_backup')
    assert len(guard_lines) == 1 and guard_lines[0] > create_lines[0], (
        '同一函数内必须在落完备份后立刻过闸门'
    )
    assert helper_span[0] <= guard_lines[0] <= helper_span[1]


def test_guard_does_not_call_itself_directly() -> None:
    """闸门函数内不得再调 create —— 否则"唯一调用点"断言被自我满足。"""
    tree = ast.parse(_RESTORE_PY.read_text(encoding='utf-8'))
    span = next((lo, hi) for name, lo, hi in _function_spans(tree)
                if name == '_require_pre_restore_backup')

    assert not [ln for ln in _call_lines(tree, 'create_pre_restore_backup')
                if span[0] <= ln <= span[1]]


@pytest.mark.parametrize('entry', _RESTORE_ENTRY_POINTS)
def test_every_restore_entry_goes_through_the_chokepoint(entry: str) -> None:
    """三个还原入口都必须经过闸门，一个都不能自己动手落备份。"""
    tree = ast.parse(_RESTORE_PY.read_text(encoding='utf-8'))
    span = next(((lo, hi) for name, lo, hi in _function_spans(tree) if name == entry), None)
    assert span is not None, f'{entry} 不存在'

    in_fn = [ln for ln in _call_lines(tree, '_pre_restore_info_or_fail') if span[0] <= ln <= span[1]]
    assert in_fn, f'{entry} 没有走 _pre_restore_info_or_fail —— 该路径没有安全备份闸门'


# ---------------------------------------------------------------------------
# 显式开关确实暴露在端点上（否则闸门就成了死路）
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    'endpoint',
    ['import_backup', 'restore_server_backup',
     'async_import_backup', 'async_restore_server_backup'],
)
def test_endpoint_exposes_escape_hatch(endpoint: str) -> None:
    fn = getattr(restore_mod, endpoint)

    assert 'allow_missing_pre_restore_backup' in inspect.signature(fn).parameters, (
        f'{endpoint} 没有暴露 allow_missing_pre_restore_backup —— '
        '安全备份失败时将无路可走（闸门必须可被显式越过）'
    )
