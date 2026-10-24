"""F3-9 / F3-8：危险写脚本必须接统一护栏；affected_rows 拒绝多语句。"""
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_affected_rows_rejects_multi_statement():
    guard = _load('_prod_write_guard_f38', ROOT / 'scripts' / '_prod_write_guard.py')

    class _DB:
        def execute(self, _stmt):
            raise AssertionError('非法多语句不得下发到数据库')

    with pytest.raises(ValueError, match='单条'):
        guard.affected_rows(_DB(), 'DELETE FROM a; DELETE FROM b', dry_run=True)


@pytest.mark.parametrize('rel', [
    'scripts/database/db_manager.py',
    'scripts/database/restore_db.py',
    'scripts/init_permissions.py',
    'scripts/backfill_purchase_order_sku.py',
    # 审查 H13 补齐的 5 个直写生产库脚本
    'scripts/reset_admin_password.py',
    'scripts/migrate_password_hashes.py',
    'scripts/perf_add_indexes.py',
    'scripts/cleanup_duplicate_purchase_orders.py',
    'scripts/backfill_production_stock_20261006.py',
    # AUD-18（2026-10-24 审计）：9 个经 SyncSessionLocal 直写生产库的导航/权限脚本
    'scripts/seed_nav.py',
    'scripts/fix_production_nav.py',
    'scripts/fix_purchase_center_nav.py',
    'scripts/hide_stockin_manage_nav.py',
    'scripts/rename_dev_section.py',
    'scripts/update_case_nav_name.py',
    'scripts/update_report_nav_name.py',
    'scripts/add_outsource_ship_receive_perms.py',
    'scripts/init_production_dept_permissions.py',
])
def test_dangerous_write_scripts_wire_the_guard(rel):
    """F3-9 / AUD-18：危险写入口必须出现 require_prod_write_consent。"""
    source = (ROOT / rel).read_text(encoding='utf-8')
    assert 'require_prod_write_consent' in source
    assert '_prod_write_guard' in source or 'from _prod_write_guard import' in source


def test_restart_backend_wires_git_branch_guard():
    """AUD-17：restart_backend 重启生产前必须过 git 分支/脏区闸门。

    生产直接吃工作区源码（AGENTS §6.1-6/9），其余全部重启路径均已接
    check_production_branch，唯此脚本曾漏接——非 main/半改状态重启会把
    坏代码跑进生产（2026-10-14/10-22 两次实害事故的旁路入口）。
    """
    source = (ROOT / 'scripts' / 'restart_backend.py').read_text(encoding='utf-8')
    assert 'check_production_branch' in source
    assert 'git_guard' in source


def test_restart_backend_refuses_on_guard_denial(monkeypatch):
    """AUD-17 行为锁：闸门拒绝时 main() 返回 2 且不得触碰 nssm。"""
    import sys
    import types

    mod = _load('restart_backend_aud17', ROOT / 'scripts' / 'restart_backend.py')
    fake_mod = types.ModuleType('server_manager.git_guard')
    calls = []

    def _deny(root):
        calls.append(root)
        return False, '工作区不在 main 分支'

    fake_mod.check_production_branch = _deny
    monkeypatch.setitem(sys.modules, 'server_manager.git_guard', fake_mod)
    nssm_called = []
    monkeypatch.setattr(mod, '_find_nssm',
                        lambda: nssm_called.append(1) or r'C:\nssm\nssm.exe')

    rc = mod.main()

    assert rc == 2, '闸门拒绝必须以 2 退出且不进入重启流程'
    assert len(calls) == 1, '闸门必须被调用恰好一次'
    assert not nssm_called, '闸门拒绝后不得触碰 nssm'


def test_prod_write_guard_ratchet_covers_all_db_scripts():
    """AUD-18 棘轮：凡带 __main__ 且触碰 DB 的 scripts/*.py 必须接写守卫。

    新脚本静默逃逸的口子被堵死（原固定名单测试不随新增脚本增长）。只读
    脚本（无 commit 写库语义）登记在白名单，archive/ 历史归档不在此列。
    """
    import re

    scripts_dir = ROOT / 'scripts'
    # 只读/分析类（无 .commit() 写库语义），经 2026-10-24 全量核查登记
    readonly_allowlist = {
        'scripts/analyze_dependencies.py',
        'scripts/check_order_indexes.py',
        'scripts/contract_snapshot.py',
        'scripts/db_baseline_probe.py',
        'scripts/diag/migration_drift_probe.py',
        'scripts/perf_benchmark.py',
        'scripts/perf_optimization/db_query_analyzer.py',
        'scripts/_prod_write_guard.py',
        'scripts/_selftest_hook.py',
    }
    offenders = []
    for py in sorted(scripts_dir.rglob('*.py')):
        rel = py.relative_to(ROOT).as_posix()
        if 'archive' in py.parts or rel in readonly_allowlist:
            continue
        src = py.read_text(encoding='utf-8', errors='replace')
        if "if __name__" not in src:
            continue
        if not re.search(r'(Sync)?SessionLocal|create_engine\(|psycopg|asyncpg', src):
            continue
        if 'require_prod_write_consent' not in src:
            offenders.append(rel)
    assert not offenders, (
        f'这些直连 DB 的脚本未接 require_prod_write_consent 写守卫（AUD-18 棘轮）：'
        f'{offenders}——写生产库前必须打目标库+显式授权；确属只读请登记白名单'
    )
