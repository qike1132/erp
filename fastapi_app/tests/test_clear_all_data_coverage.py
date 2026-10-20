"""P1-35 回归：clear_all_data.py 表清单与 ORM / dry-run 预览的一致性。

缺陷：脚本自称「完整」，但六个清库脚本各自硬编码表清单，板房 7 张、湖北外发 5 张、
notification / numbering_counter 等 22 张表长期漏清，且 --dry-run 预览同样不显示。
修复：CLEARED_TABLES 显式登记 + KEEP_TABLES 显式保留 + 启动时 ORM 覆盖校验；
本文件钉住「清单 = 实际 DELETE 语句 = ORM 全覆盖」三者一致，且 dry-run 可见。
"""
import ast
import importlib.util
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPT = ROOT / 'scripts' / 'clear_all_data.py'


def _load_named(filename: str, subdir: str = ''):
    import sys
    for path in (ROOT, ROOT / 'scripts'):
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))
    path = ROOT / 'scripts' / subdir / f'{filename}.py'
    spec = importlib.util.spec_from_file_location(f'{filename}_p135', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_script():
    return _load_named('clear_all_data')


@pytest.fixture(scope='module')
def script():
    return _load_script()


class _FakeResult:
    rowcount = 3

    def scalar(self):
        return 7


class _FakeSession:
    def __init__(self):
        self.statements: list[str] = []

    def execute(self, stmt):
        self.statements.append(str(stmt))
        return _FakeResult()


def _sql_tables() -> set[str]:
    tree = ast.parse(SCRIPT.read_text(encoding='utf-8'))
    tables = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            for m in re.finditer(r'DELETE\s+FROM\s+"?([A-Za-z_][A-Za-z0-9_]*)"?', node.value, re.I):
                tables.add(m.group(1))
    return tables


# 2026-10-17 审计 P1-35 点名漏清的 22 张表（order_item 依赖级联，修复后也显式化）
AUDIT_MISSING_TABLES = {
    'customer_sampling_change_log', 'customer_sampling_fabric_version',
    'customer_sampling_part', 'customer_sampling_role', 'customer_sampling_project',
    'pattern_maker', 'file_records',
    'outsource_shipment_item', 'outsource_shipment', 'order_outsource_process_flow',
    'order_outsource_process', 'outsource_process_type',
    'notification', 'order_batch_audit_log', 'purchase_order_sku',
    'product_role', 'role', 'audit_log', 'web_vital', 'backup_record',
    'numbering_counter', 'order_item',
}


def test_manifest_matches_actual_delete_statements(script):
    """清单与代码里真实执行的 DELETE 必须一一对应（防二次漂移）。"""
    assert _sql_tables() == script.CLEARED_TABLES


def test_orm_tables_fully_classified(script):
    assert script.verify_table_coverage() == []
    assert script.verify_manifest_consistency() == []


def test_keep_and_clear_are_disjoint(script):
    assert not (script.CLEARED_TABLES & script.KEEP_TABLES)


def test_audit_missing_tables_are_covered(script):
    assert AUDIT_MISSING_TABLES <= script.CLEARED_TABLES


def test_coverage_guard_detects_unclassified_table(script, monkeypatch):
    """注入一颗未分类表名：guard 必须报出来（证明守卫有牙，而非恒空）。"""
    monkeypatch.setattr(script, 'CLEARED_TABLES', script.CLEARED_TABLES - {'notification'})
    assert 'notification' in script.verify_table_coverage()


def test_dry_run_previews_newly_added_tables_without_delete(script, capsys):
    db = _FakeSession()
    script.clear_purchase_center(db, dry_run=True)
    script.clear_core_business(db, dry_run=True)
    script.clear_system_management(db, dry_run=True)

    out = capsys.readouterr().out
    for label in ('采购单 SKU', '板房管理/文件', '湖北外发', '导入指纹/通知/批次审计',
                  '产品关联', '审计/埋点/备份记录', '编号计数器/巡检'):
        assert label in out, f'dry-run 预览缺少 {label}'
    # dry-run 不得发出任何 DELETE（affected_rows 会转成 COUNT）
    assert db.statements
    assert not any(s.lstrip().upper().startswith('DELETE') for s in db.statements)
    for table in ('customer_sampling_project', 'notification', 'numbering_counter', 'purchase_order_sku'):
        assert any(table in s for s in db.statements), f'dry-run 未统计 {table}'


@pytest.mark.parametrize('filename', ['simple_clear', 'cleanup_preserve_users'])
def test_drifted_clear_scripts_refuse_by_default(filename, monkeypatch, capsys):
    """P1-35：清单已漂移的旧脚本默认拒绝运行，避免「自称彻底清除」的静默残留。

    审计 F1-6 追加：这两个脚本已移入 scripts/archive/，且**无条件**拒绝执行 ——
    连原来的 --allow-deprecated-clear 逃生口也不再有（那份清单漏 28 张表，
    却会打印「其他数据已彻底清除」）。
    """
    import sys

    monkeypatch.setattr(sys, 'argv', [f'{filename}.py'])
    module = _load_named(filename, 'archive')
    with pytest.raises(SystemExit) as exc:
        module.main()
    assert exc.value.code == 2
    assert 'purge_simulated_data.py' in capsys.readouterr().out


@pytest.mark.parametrize('filename', ['simple_clear', 'cleanup_preserve_users'])
def test_archived_clear_scripts_refuse_even_with_legacy_escape_hatch(filename, monkeypatch, capsys):
    """归档脚本的旧逃生口（--allow-deprecated-clear）必须已失效。"""
    import sys

    monkeypatch.setattr(sys, 'argv', [f'{filename}.py', '--allow-deprecated-clear'])
    module = _load_named(filename, 'archive')
    with pytest.raises(SystemExit) as exc:
        module.main()
    assert exc.value.code == 2
    assert 'purge_simulated_data.py' in capsys.readouterr().out


@pytest.mark.parametrize('filename', ['simple_clear', 'cleanup_preserve_users'])
def test_drifted_clear_scripts_not_in_active_scripts_dir(filename):
    """漂移脚本不得留在 scripts/ 根目录（唯一入口收敛的前提）。"""
    assert not (ROOT / 'scripts' / f'{filename}.py').exists()
    assert (ROOT / 'scripts' / 'archive' / f'{filename}.py').exists()


@pytest.mark.parametrize('filename', ['simple_clear', 'cleanup_preserve_users'])
def test_archived_clear_scripts_have_no_delete_statements(filename):
    """归档脚本里不得再残留任何 DELETE / TRUNCATE 语句。"""
    source = (ROOT / 'scripts' / 'archive' / f'{filename}.py').read_text(encoding='utf-8')
    for token in ('DELETE FROM', 'TRUNCATE', 'drop_table', 'unlink('):
        assert token not in source, f'归档脚本 {filename} 仍残留破坏性语句: {token}'
