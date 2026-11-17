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
from pathlib import Path

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


def _conftest_code_without_docstrings() -> str:
    """取 tests/conftest.py 的代码（剥掉 docstring/注释），用于接线断言。

    为什么不直接搜源码文本：conftest 的 docstring 里**引用**了那段被否定的旧写法
    当反面样本，直接搜文本会自己撞自己。剥掉 docstring 后剩下的才是真实代码。
    """
    import ast

    tree = ast.parse(
        (Path(__file__).resolve().parent / "conftest.py").read_text(encoding="utf-8")
    )
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = node.body
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                node.body = body[1:]
    return ast.unparse(tree)


def test_conftest_delegates_derivation_to_single_implementation():
    """根树 conftest 的派生链必须是 `_test_db_guard` 那一份（2026-11-17 OCR 复审）。

    为什么用接线断言而不是行为断言：`TEST_DATABASE_URL` 设了值时两条派生链
    **行为完全相同**（都直接返回 env 值），行为断言在 CI 上恒真、抓不到回归。
    真正的失败形态在 env 缺失时才出现——`parsed.path.replace(f"/{db_name}", ...)` 在
    `DB_NAME` 与 URL 实际库名漂移时**静默 no-op**，原样返回生产库 URL。
    故这里锁「接线」：必须调 `resolve_test_db_url`，且不得再出现那份被否定的写法。
    """
    code = _conftest_code_without_docstrings()
    assert "resolve_test_db_url" in code, (
        "tests/conftest.py 没有调用 _test_db_guard.resolve_test_db_url —— "
        "派生链又分叉了（两份实现必然漂移）"
    )
    assert "path.replace" not in code, (
        "tests/conftest.py 又出现了 path.replace 派生：DB_NAME 与实际库名不一致时是静默 "
        "no-op，会把生产库 URL 当测试库 URL 返回"
    )
