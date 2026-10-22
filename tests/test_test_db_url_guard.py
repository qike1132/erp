"""测试库硬闸：URL 里的 query 参数不得把连接改指到生产库。

背景：PG 方言的 ``create_connect_args`` 会 ``opts.update(url.query)``，
``?database=erp_system`` / ``?host=…`` 会**覆盖** URL 路径上的库名与主机。
只看 path 的校验会让
``postgresql+asyncpg://u:p@h:5432/erp_system_test?database=erp_system``
一路放行，而测试会话会 ``DROP SCHEMA public CASCADE`` ⇒ 直接打生产库。

⚠️ 硬闸用 ``pytest.exit()`` 终止会话，它抛的是 ``_pytest.outcomes.Exit``
（``Exception`` 子类，**不是** ``SystemExit``）——用 ``pytest.raises(SystemExit)``
接不住，异常会逃逸出用例并把整个 pytest 会话中断（全量套件只跑到该用例就停）。
"""
import pytest
from _pytest.outcomes import Exit
from conftest import _assert_is_test_database


class TestAssertIsTestDatabase:
    def test_accepts_plain_test_db_url(self):
        """普通 *_test 库 URL 放行。"""
        _assert_is_test_database('postgresql+asyncpg://u:p@h:5432/erp_system_test')

    def test_rejects_production_db_url(self):
        with pytest.raises(Exit) as exc:
            _assert_is_test_database('postgresql+asyncpg://u:p@h:5432/erp_system')
        assert exc.value.returncode == 2

    def test_rejects_database_query_override(self):
        """路径写着 _test、query 里改指生产库 —— 必须拒绝。"""
        with pytest.raises(Exit) as exc:
            _assert_is_test_database(
                'postgresql+asyncpg://u:p@h:5432/erp_system_test?database=erp_system'
            )
        assert exc.value.returncode == 2

    def test_rejects_host_query_override(self):
        with pytest.raises(Exit) as exc:
            _assert_is_test_database(
                'postgresql+asyncpg://u:p@h:5432/erp_system_test?host=10.0.0.95'
            )
        assert exc.value.returncode == 2

    def test_rejects_port_query_override(self):
        with pytest.raises(Exit) as exc:
            _assert_is_test_database(
                'postgresql+asyncpg://u:p@h:5432/erp_system_test?port=6543'
            )
        assert exc.value.returncode == 2
