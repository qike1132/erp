"""测试库 URL 硬闸（可复用版）——AUD-14，2026-10-24 审计。

根树 tests/conftest.py 的 _assert_is_test_database 只在收集 tests/ 子树时加载；
AGENTS §4 推荐的聚焦跑 `pytest fastapi_app/tests/<文件>` 不经过它，本树自建
连接串的夹具（三份 _test_db_url 复制件 + test_restore_real_roundtrip 的
scratch URL）此前在此跑法下零校验——TEST_DATABASE_URL 误指生产或
str.replace 的 no-op 失败模式会把 create_all/DELETE 打到生产库。

本模块与根闸同源同语义；判定必须按 SQLAlchemy make_url 口径（PG 方言的
create_connect_args 会 opts.update(url.query)，?database=erp_system 会覆盖
路径库名）。两边改动须同步（根闸由 tests/test_test_db_url_guard.py 锁定）。
"""
from __future__ import annotations


def assert_is_test_database(url: str, *, exit_fn=None) -> None:
    """断言 url 指向 *_test 库且无 query 覆盖参数，否则终止会话。

    exit_fn 默认 pytest.exit（聚焦跑时未加载根 conftest 也能终止）。
    """
    import pytest

    _exit = exit_fn or pytest.exit

    from sqlalchemy.engine import make_url

    try:
        parsed = make_url(url)
    except Exception as exc:  # broad-except: 解析失败本身即终止条件，类型不限
        _exit(
            f"拒绝运行：无法解析测试库 URL（{type(exc).__name__}: {exc}）：{url!r}",
            returncode=2,
        )
        return

    forbidden = {'database', 'host', 'port'} & set(parsed.query.keys())
    if forbidden:
        _exit(
            f"拒绝运行：测试库 URL 带了会覆盖连接目标的 query 参数 "
            f"{sorted(forbidden)}（SQLAlchemy 的 PG 方言会让它们覆盖 URL 路径上的"
            f"库名/主机）。请把它们写进 URL 路径本身，不要用 query 参数。",
            returncode=2,
        )
        return

    if not (parsed.database or '').rstrip('/').endswith('_test'):
        _exit(
            f"拒绝运行：测试库 URL 指向非测试库 {(parsed.database or '')!r}"
            f"（夹具会对它执行建表/删除数据）。请检查 DB_NAME 与"
            f" ASYNC_DATABASE_URL 的库名是否一致，或显式设置指向 *_test 库的"
            f" TEST_DATABASE_URL。",
            returncode=2,
        )
