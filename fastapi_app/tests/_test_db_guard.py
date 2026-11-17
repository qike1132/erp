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


def derive_test_db_url(main_url: str) -> str:
    """把主库 URL 派生为 `*_test` 库 URL（幂等：已是 `_test` 就原样返回）。

    2026-11-16 上线前审计 H-6：两棵测试树里共有 13 处自建的派生链，两种失败形态——

    - `os.getenv('TEST_DATABASE_URL') or settings.ASYNC_DATABASE_URL`：环境变量缺失时
      **直接落到生产库 URL**（`.env` 里没有这个键时就是这种情形）；
    - `path.replace(f'/{DB_NAME}', f'/{DB_NAME}_test')`：`DB_NAME` 与 URL 实际库名不一致时
      是**静默 no-op**，同样返回生产库 URL。

    两者都会被上面的硬闸拦下（这点是对的），但拦法是把**整场会话** `pytest.exit(2)`——
    一个模块拿不到 URL 就让全量 6080 条一条都跑不了（实测 8% 处中断）。

    本函数改为按 **URL 里实际的库名** 追加 `_test`：不依赖 `DB_NAME` 是否正确，
    也不可能 no-op。query 参数原样保留，`?database=` 这类覆盖参数仍由
    `assert_is_test_database` 拒绝。
    """
    from urllib.parse import urlparse, urlunparse

    parsed = urlparse(main_url)
    current = (parsed.path or '').lstrip('/').rstrip('/')
    if current.endswith('_test'):
        return main_url
    if not current:
        raise RuntimeError(f'无法从 URL 解析库名，拒绝派生测试库：{main_url!r}')
    return urlunparse(parsed._replace(path=f'/{current}_test'))


def resolve_test_db_url() -> str:
    """`TEST_DATABASE_URL` 优先；缺失时由 `settings.ASYNC_DATABASE_URL` 派生，返回前过硬闸。

    单点收敛：两棵测试树的 13 处 `_test_db_url()` 都改调这里（2026-11-16 审计 H-6），
    新增测试直接用它，别再复制派生链（历史上复制出 13 份、其中 5 份连闸门都没有）。
    """
    import os

    url = (os.getenv('TEST_DATABASE_URL') or '').strip()
    if not url:
        from fastapi_app.core.config import settings

        url = derive_test_db_url(str(settings.ASYNC_DATABASE_URL))
    assert_is_test_database(url)
    return url

