"""关键链路的真库证明不得再被「环境缺失」静默 skip（2026-10-17 审计 TEST-BE-B §3.1 / P1-3）。

背景
----
这 8 个文件里的用例是若干 P0/P1 链路**唯一**的真库证明。原先它们都用
`pytest.skip('测试库不可达…')` 处理环境前提，于是非提权 / `.env` 不可读 /
PG 端口没开时全部变绿（skip），全量数字仍是「全绿 + N skipped」——
没人会去看 N 的构成。本仓在 `test_import_idempotency_constraints.py:301-303`
已经写下了这个教训的原话。

修法（审计 §3.1 修法③）：换用 `fastapi_app.tests._required_env.require_test_db`，
默认 **fail**，只有显式 `ALLOW_MISSING_TEST_DB=1` 才 skip —— 缺口必须有人签字。

本文件锁三件事：
1. helper 的行为（未签字 fail / 签字 skip）—— 否则它可能退化成永远 skip；
2. 那 8 个文件里不得再出现**裸** `pytest.skip` 掩盖「测试库不可达」；
3. 白名单里的文件必须真的存在（目录改名不能让本测试静默空转）。
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from fastapi_app.tests import _required_env
from fastapi_app.tests._required_env import ALLOW_ENV, allow_missing_test_db, require_test_db

PROJECT_ROOT = Path(__file__).resolve().parent.parent

#: 这些文件承载 P0/P1 链路的唯一真库证明。新增条目请写明是哪条链路。
CRITICAL_PROOF_FILES: tuple[str, ...] = (
    'fastapi_app/tests/test_audit_retention_pg.py',              # 审计留存（真库 DELETE/边界）
    'fastapi_app/tests/test_numbering_audit_retention_pg.py',     # 编号审计留存
    'fastapi_app/tests/test_order_batch_lock_order.py',           # P1-5 行锁顺序
    'fastapi_app/tests/test_order_deduction_completeness.py',     # P1-8 抵扣事务反证
    'fastapi_app/tests/test_product_stock_check_constraint.py',   # 库存非负 CHECK 约束
    'fastapi_app/tests/test_recovery_validation_fixes.py',        # 恢复校验修复
    'fastapi_app/tests/test_import_idempotency_constraints.py',   # 导入幂等唯一约束
    'tests/test_p3_health_check.py',                              # 健康检查可 await 语义
)

#: 「测试库不可达」类理由。刻意**不**匹配「测试库已有 N 行历史数据，跳过以免误删」
#: —— 那是保护措施，不是覆盖缺口。
_UNREACHABLE_REASON = re.compile(
    r'测试库不可达|测试库不可用|测试库端口不可达|测试库缺|无法从配置推导测试库名'
    r'|真实 PostgreSQL 不可用|数据库不可达'
)


def test_allow_flag_defaults_to_off(monkeypatch) -> None:
    """默认必须「没签字」—— 否则 helper 退化成永远 skip。"""
    monkeypatch.delenv(ALLOW_ENV, raising=False)
    assert allow_missing_test_db() is False
    monkeypatch.setenv(ALLOW_ENV, '0')
    assert allow_missing_test_db() is False
    monkeypatch.setenv(ALLOW_ENV, '1')
    assert allow_missing_test_db() is True


def test_require_test_db_fails_without_signature(monkeypatch) -> None:
    """未签字时必须 fail（而不是 skip）—— 这是本改动唯一的行为保证。

    注意不能用 `with pytest.raises(pytest.fail.Exception)`：helper 若退化成
    `pytest.skip(...)`，`Skipped` 不是 `Failed` 的子类，会**冒泡把本用例标成
    skipped** —— 于是「缺口又变成静默跳过」这件事在报告里长成一条 skip，
    守卫自己成了它要防的那种假绿。必须显式区分三种结局。
    """
    monkeypatch.delenv(ALLOW_ENV, raising=False)
    try:
        require_test_db('测试库端口不可达（单测）')
    except pytest.skip.Exception:  # type: ignore[attr-defined]
        pytest.fail(
            '未签字时 require_test_db 竟然 skip 了 —— 缺口又变回静默跳过，'
            f'这正是本仓 2026-11-03 踩过的坑（需要 {ALLOW_ENV} 才允许 skip）'
        )
    except pytest.fail.Exception as exc:  # type: ignore[attr-defined]
        assert ALLOW_ENV in str(exc), str(exc)
    else:
        pytest.fail('require_test_db 既没 fail 也没 skip —— 行为不可预期')


def test_require_test_db_skips_with_signature(monkeypatch) -> None:
    """显式签字后才允许 skip，且理由里必须留下签字痕迹。"""
    monkeypatch.setenv(ALLOW_ENV, '1')
    with pytest.raises(pytest.skip.Exception) as excinfo:  # type: ignore[attr-defined]
        require_test_db('测试库端口不可达（单测）')
    message = str(excinfo.value)
    assert ALLOW_ENV in message, message


def test_helper_module_has_no_other_mode() -> None:
    """helper 只有「fail」与「显式签字后 skip」两种出口，不得新增静默通过分支。"""
    src = Path(_required_env.__file__).read_text(encoding='utf-8')
    tree = ast.parse(src)
    fn = next(
        (n for n in ast.walk(tree)
         if isinstance(n, ast.FunctionDef) and n.name == 'require_test_db'),
        None,
    )
    assert fn is not None, 'require_test_db 不见了'
    # `pytest.skip(...)` / `pytest.fail(...)` 是 Attribute 调用，`allow_missing_test_db()`
    # 是 Name 调用 —— 两种都要收。
    calls = {
        n.func.attr if isinstance(n.func, ast.Attribute) else n.func.id
        for n in ast.walk(fn)
        if isinstance(n, ast.Call) and isinstance(n.func, (ast.Attribute, ast.Name))
    }
    assert calls == {'allow_missing_test_db', 'skip', 'fail'}, (
        f'require_test_db 里出现了意料之外的调用：{sorted(calls)}'
        '（它只应有「已签字 → skip」「未签字 → fail」两条出口）'
    )


def test_critical_proof_files_exist() -> None:
    """白名单文件必须存在 —— 目录改名不能让下面那条守卫静默空转。"""
    missing = [rel for rel in CRITICAL_PROOF_FILES if not (PROJECT_ROOT / rel).is_file()]
    assert not missing, f'白名单里的文件不存在（改名/挪动后请同步本表）：{missing}'


def test_no_bare_test_db_skip_left_in_critical_proofs() -> None:
    """关键证明里不得再出现裸 `pytest.skip('测试库不可达…')`。

    这条是防回退的棘轮：把某处 `require_test_db(...)` 改回 `pytest.skip(...)`，
    它立刻红。判据是 AST 实参文本，不是行内 grep —— 注释里提到这些词不算。
    """
    offenders: list[str] = []
    for rel in CRITICAL_PROOF_FILES:
        path = PROJECT_ROOT / rel
        tree = ast.parse(path.read_text(encoding='utf-8'))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == 'skip'
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == 'pytest'):
                continue
            arg = node.args[0] if node.args else None
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str) \
                    and _UNREACHABLE_REASON.search(arg.value):
                offenders.append(f'{rel}:{node.lineno}: {arg.value[:60]}')
    assert not offenders, (
        '这些位置又把「测试库不可达」降级成静默 skip 了（应改用 '
        f'require_test_db，缺口需 {ALLOW_ENV}=1 才放行）：\n  ' + '\n  '.join(offenders)
    )


def test_critical_proofs_call_require_test_db() -> None:
    """接线检查：这些文件必须真的调用 `require_test_db`，不只是 import 了它。

    为什么不起子进程跑一遍再断言「0 skipped」：pytest 的测试库咨询锁是按库互斥的
    （`tests/conftest.py::_exclusive_test_db_lock`，第二个实例直接 exit 2），
    在用例内部再起一个 pytest 会撞锁，断言的是锁不是行为。
    「这 8 个文件在本机跑出 94 passed / 0 skipped」由提交信息里的当场输出承担。
    """
    not_wired: list[str] = []
    for rel in CRITICAL_PROOF_FILES:
        tree = ast.parse((PROJECT_ROOT / rel).read_text(encoding='utf-8'))
        called = any(
            isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
            and n.func.id == 'require_test_db'
            for n in ast.walk(tree)
        )
        if not called:
            not_wired.append(rel)
    assert not not_wired, (
        '这些文件只 import 了 require_test_db 却没调用（环境缺失仍会被静默 skip）：\n  '
        + '\n  '.join(not_wired)
    )
