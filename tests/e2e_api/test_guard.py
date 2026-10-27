"""E2E 生产指纹守卫：指向生产库/生产入口必须拒绝运行（fail-fast）。"""

import pytest

import tests.e2e_api.conftest as e2e_conftest


@pytest.mark.parametrize(
    ('base_url', 'dsn', 'fragment'),
    [
        ('http://127.0.0.1:9999', 'postgresql://u:p@localhost/erp_system_test', None),
        ('http://127.0.0.1:5002', 'postgresql://u:p@localhost/erp_system_test', '生产入口'),
        ('http://127.0.0.1:3000', 'postgresql://u:p@localhost/erp_system_test', '生产入口'),
        ('http://192.168.0.95:9999', 'postgresql://u:p@localhost/erp_system_test', '回环'),
        ('http://127.0.0.1:9999', 'postgresql://u:p@localhost/erp_system', '非测试库'),
        ('http://127.0.0.1:9999', 'postgresql://u:p@localhost/erp_e2e', '非测试库'),
        (
            'http://127.0.0.1:9999',
            'postgresql://u:p@localhost/erp_system_test?database=erp_system',
            'query 参数',
        ),
        ('http://127.0.0.1:9999', 'not-a-dsn', '无法解析'),
    ],
)
def test_target_guard(base_url, dsn, fragment):
    hit, reason = e2e_conftest._production_fingerprint_hit(base_url=base_url, db_url=dsn)
    if fragment is None:
        assert not hit, reason
    else:
        assert hit
        assert fragment in reason


@pytest.mark.parametrize(
    ('actual', 'expected_dsn', 'fragment'),
    [
        ('erp_system_test', 'postgresql://u:p@localhost/erp_system_test', None),
        ('erp_system', 'postgresql://u:p@localhost/erp_system_test', '非测试库'),
        ('other_test', 'postgresql://u:p@localhost/erp_system_test', '不一致'),
        ('', 'postgresql://u:p@localhost/erp_system_test', '未回报'),
    ],
)
def test_backend_identity_must_match_dsn(actual, expected_dsn, fragment):
    reason = e2e_conftest._identity_database_mismatch(actual, expected_dsn)
    if fragment is None:
        assert reason is None
    else:
        assert reason is not None
        assert fragment in reason


def test_fingerprint_checked_before_backend_alive(monkeypatch):
    monkeypatch.setattr(e2e_conftest, '_ALIVE', False)
    monkeypatch.setattr(e2e_conftest, '_ALIVE_REASON', 'unreachable')
    monkeypatch.setattr(e2e_conftest, 'BASE_URL', 'http://127.0.0.1:3000')
    monkeypatch.setenv(
        'ERP_E2E_REAL_DATABASE_URL',
        'postgresql://u:p@localhost/erp_system_test',
    )

    with pytest.raises(pytest.exit.Exception) as excinfo:
        e2e_conftest.pytest_collection_modifyitems(None, [])
    assert '生产入口' in str(excinfo.value)
