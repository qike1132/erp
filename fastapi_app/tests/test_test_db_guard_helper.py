"""AUD-14 / T2-F1、F7（2026-10-24 审计）回归锁：可复用的测试库 URL 硬闸。

三份 _test_db_url 复制件与 test_restore_real_roundtrip 的 scratch URL 此前在
聚焦跑（pytest fastapi_app/tests/...，不加载根树 conftest）下零校验——
TEST_DATABASE_URL 误指生产或 str.replace no-op 会把 create_all/DELETE 打到
生产库。本文件锁定 _test_db_guard.assert_is_test_database 的判定行为；
接线完整性由 test_write_guard_wiring 的棘轮与根闸测试共同覆盖。
"""
import pytest

from fastapi_app.tests._test_db_guard import assert_is_test_database, derive_test_db_url


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


# ---------------------------------------------------------------------------
# derive_test_db_url：派生必须幂等、保留驱动、保留 query
# （2026-11-17 OCR 复审：根树 tests/conftest.py::_build_test_db_url 已改为调这一份实现）
# ---------------------------------------------------------------------------
def test_derive_is_idempotent_for_test_db():
    """已是 *_test 的 URL 必须原样返回。

    为什么：派生链会被串联调用（resolve 里 derive、夹具再 derive 一次）。
    若对 _test 库再追加一次（erp_system_test_test），就会连到不存在的库。
    """
    url = "postgresql+asyncpg://u:p@127.0.0.1:5432/erp_system_test"
    assert derive_test_db_url(url) == url


def test_derive_keeps_asyncpg_driver_and_appends_suffix():
    """按 URL 里实际的库名追加 _test，驱动（+asyncpg）原样保留。

    为什么：旧写法 path.replace(f"/{DB_NAME}", ...) 依赖 DB_NAME 与 URL 库名一致，
    不一致时静默 no-op 返回生产库 URL。这里断言派生结果只认 URL 里的库名，
    且驱动不能丢（丢成 postgresql:// 会退化成同步驱动，异步引擎建不起来）。
    """
    derived = derive_test_db_url("postgresql+asyncpg://u:p@127.0.0.1:5432/erp_system")
    assert derived == "postgresql+asyncpg://u:p@127.0.0.1:5432/erp_system_test"


def test_derive_preserves_query_parameters():
    """query 参数（如 ?sslmode=...）原样保留，只改路径上的库名。

    为什么：生产 DSN 常带 sslmode=require / application_name=...；派生时丢 query
    会让测试连接因缺 SSL 参数被拒或被静默降级。覆盖型参数（?database=/?host=/?port=）
    不在此列：它们由 assert_is_test_database 直接拒绝（见 test_query_override_rejected）。
    """
    derived = derive_test_db_url(
        "postgresql+asyncpg://u:p@127.0.0.1:5432/erp_system"
        "?sslmode=require&application_name=erp_probe"
    )
    assert derived == (
        "postgresql+asyncpg://u:p@127.0.0.1:5432/erp_system_test"
        "?sslmode=require&application_name=erp_probe"
    )
