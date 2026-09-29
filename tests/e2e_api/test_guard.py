"""E2E 生产指纹守卫：指向生产库/生产端口必须拒绝运行（fail-fast）。"""
import os
from unittest import mock

import pytest

import tests.e2e_api.conftest as e2e_conftest


def test_unset_target_guards_trigger_skip_marker(monkeypatch):
    # 未显式指定目标 → 指纹不命中，允许走到探活 skip 分支
    monkeypatch.setattr(e2e_conftest, 'BASE_URL', 'http://127.0.0.1:9999')
    monkeypatch.setenv('ERP_E2E_REAL_DATABASE_URL', 'postgresql://u:p@localhost/erp_system_test')
    hit, reason = e2e_conftest._production_fingerprint_hit()
    assert not hit, reason


def test_port_5002_is_fingerprint():
    hit, _ = e2e_conftest._production_fingerprint_hit(
        base_url='http://127.0.0.1:5002', db_url='postgresql://u:p@localhost/erp_system_test')
    assert hit


def test_db_erp_system_is_fingerprint():
    hit, _ = e2e_conftest._production_fingerprint_hit(
        base_url='http://127.0.0.1:9999', db_url='postgresql+psycopg://u:p@localhost:5432/erp_system')
    assert hit


def test_fingerprint_checked_before_backend_alive(monkeypatch):
    # 守卫必须先于探活：生产库+死端口 → fail-fast 而不是静默 skip
    # （探活结果由模块级 _backend_alive() 固化，这里直接验证钩子函数逻辑）
    monkeypatch.setattr(e2e_conftest, '_ALIVE', False)
    monkeypatch.setattr(e2e_conftest, '_ALIVE_REASON', 'unreachable')
    monkeypatch.setattr(e2e_conftest, 'BASE_URL', 'http://127.0.0.1:5002')
    monkeypatch.setenv('ERP_E2E_REAL_DATABASE_URL', 'postgresql://u:p@localhost/erp_system')

    class _Item:
        own_markers = []

        def add_marker(self, m):
            self.own_markers.append(m)

    import pytest as _pytest
    with pytest.raises(_pytest.exit.Exception) as excinfo:
        e2e_conftest.pytest_collection_modifyitems(None, [_Item()])
    assert '生产' in str(excinfo.value) or 'production' in str(excinfo.value)
