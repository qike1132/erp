"""AUD-14 / T2-F1、F7（2026-10-24 审计）回归锁：可复用的测试库 URL 硬闸。

三份 _test_db_url 复制件与 test_restore_real_roundtrip 的 scratch URL 此前在
聚焦跑（pytest fastapi_app/tests/...，不加载根树 conftest）下零校验——
TEST_DATABASE_URL 误指生产或 str.replace no-op 会把 create_all/DELETE 打到
生产库。本文件锁定 _test_db_guard.assert_is_test_database 的判定行为；
接线完整性由 test_write_guard_wiring 的棘轮与根闸测试共同覆盖。
"""
import pytest

from fastapi_app.tests._test_db_guard import assert_is_test_database


class _ExitCalledError(Exception):
    def __init__(self, msg):
        self.msg = msg
        super().__init__(msg)


def _collect_exits():
    """把 pytest.exit 替换为抛异常的桩，捕获 (msg, returncode)。"""
    calls = []

    def _exit(msg, returncode=1):
        calls.append((msg, returncode))
        raise _ExitCalledError(msg)

    return calls, _exit


def test_valid_test_url_passes():
    calls, exit_fn = _collect_exits()
    assert_is_test_database(
        'postgresql+asyncpg://u:p@127.0.0.1:5432/erp_system_test', exit_fn=exit_fn)
    assert calls == [], '指向 *_test 的 URL 必须放行'


def test_non_test_db_rejected():
    calls, exit_fn = _collect_exits()
    with pytest.raises(_ExitCalledError):
        assert_is_test_database(
            'postgresql+asyncpg://u:p@127.0.0.1:5432/erp_system', exit_fn=exit_fn)
    assert calls and calls[0][1] == 2
    assert '非测试库' in calls[0][0]


def test_query_override_rejected():
    """;?database= 会覆盖 path 上的库名（PG create_connect_args 语义）——必须拒。"""
    calls, exit_fn = _collect_exits()
    with pytest.raises(_ExitCalledError):
        assert_is_test_database(
            'postgresql+asyncpg://u:p@127.0.0.1:5432/erp_system_test?database=erp_system',
            exit_fn=exit_fn)
    assert calls and 'query' in calls[0][0]


def test_unparseable_url_rejected():
    calls, exit_fn = _collect_exits()
    with pytest.raises(_ExitCalledError):
        assert_is_test_database(':::not-a-url:::', exit_fn=exit_fn)
    assert calls and calls[0][1] == 2


def test_replace_noop_production_url_would_be_caught():
    """str.replace 的 no-op 失败模式（T2-F1 分支 B）：派生失败返回生产 URL 原文，
    闸门必须拦下——这正是三份复制件此前裸奔的形态。"""
    calls, exit_fn = _collect_exits()
    # DB_NAME 与 URL 库名漂移时 replace 找不到子串 → 原样返回
    noop_result = 'postgresql+asyncpg://u:p@127.0.0.1:5432/erp_system'.replace(
        '/nonexistent_db', '/nonexistent_db_test', 1)
    with pytest.raises(_ExitCalledError):
        assert_is_test_database(noop_result, exit_fn=exit_fn)
    assert calls and '非测试库' in calls[0][0]
