"""scripts/_prod_write_guard.py 的回归测试（2026-10-02 P6 审计）。

护栏的语义：**默认拒绝**写生产库，只有显式授权（环境变量 ERP_ALLOW_PROD_WRITE
或命令行 --allow-prod-write）才放行。本测试钉住这条 fail-closed 语义。
"""
import importlib.util
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
GUARD_PATH = ROOT / 'scripts' / '_prod_write_guard.py'


def _load():
    spec = importlib.util.spec_from_file_location('_prod_write_guard', GUARD_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def guard():
    return _load()


def test_guard_refuses_without_authorization(guard, monkeypatch):
    monkeypatch.delenv('ERP_ALLOW_PROD_WRITE', raising=False)
    monkeypatch.setattr(sys, 'argv', ['some_script.py'])
    assert guard.prod_write_allowed() is False
    with pytest.raises(SystemExit) as ei:
        guard.require_prod_write_consent('测试动作')
    assert ei.value.code == 3, '未授权必须以退出码 3 拒绝'


def test_guard_allows_via_env(guard, monkeypatch):
    monkeypatch.setenv('ERP_ALLOW_PROD_WRITE', '1')
    monkeypatch.setattr(sys, 'argv', ['some_script.py'])
    assert guard.prod_write_allowed() is True
    guard.require_prod_write_consent('测试动作')  # 不抛


def test_guard_allows_via_argv_flag(guard, monkeypatch):
    monkeypatch.delenv('ERP_ALLOW_PROD_WRITE', raising=False)
    monkeypatch.setattr(sys, 'argv', ['some_script.py', '--allow-prod-write'])
    assert guard.prod_write_allowed() is True
    guard.require_prod_write_consent('测试动作')  # 不抛


@pytest.mark.parametrize('value', ['0', 'false', 'no', 'off', ''])
def test_guard_env_truthiness_is_strict(guard, monkeypatch, value):
    """非真值不得放行（避免 ERP_ALLOW_PROD_WRITE=0 被误当成授权）。"""
    monkeypatch.setenv('ERP_ALLOW_PROD_WRITE', value)
    monkeypatch.setattr(sys, 'argv', ['some_script.py'])
    assert guard.prod_write_allowed() is False


def test_target_db_description_masks_password(guard):
    """目标库描述必须可读且**不含口令明文**。"""
    desc = guard.describe_target_db()
    assert desc  # 非空
    # 口令若出现在描述里即为泄漏；正常形态只有 host:port/db + 用户名
    assert '口令已脱敏' in desc or '无法解析' in desc


def test_guarded_scripts_actually_call_the_guard():
    """防"护栏没插进脚本"：盘点应当受保护的脚本确实调用了它。"""
    must_guard = [
        'simple_clear.py', 'cleanup_preserve_users.py', 'create_test_orders.py',
        'create_beile_test_data.py', 'create_multi_sku_test.py', 'seed_pattern_room.py',
        'insert_1_3_version.py', 'insert_test_app_versions.py',
        'insert_test_app_versions_simple.py', 'simulate_stockout.py',
        'verify_dedup_index.py', 'e2e_verify_dedup.py', 'concurrency_stress_test.py',
        'test_available_stock.py', 'perf_seed_data.py', 'clear_all_data.py',
        'clear_purchase_center_data.py', 'diagnose_production.py',
        'perf_optimization/generate_test_data.py', 'perf_optimization/benchmark_core_ops.py',
        'test_ota_flow.py',  # 会触发全设备 OTA（第二轮审计补接）
    ]
    missing = [
        name for name in must_guard
        if 'require_prod_write_consent'
        not in (ROOT / 'scripts' / name).read_text(encoding='utf-8')
    ]
    assert not missing, f'这些脚本没有接入生产写护栏: {missing}'
