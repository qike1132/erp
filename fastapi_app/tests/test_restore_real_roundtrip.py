"""restore 路径真跑特征测试（2026-10-11 复核 P2-14④）。

背景：backup 域现有测试全是 monkeypatch 替身（test_backup_m0_hotfix.py:82 替
restore_database_via_psql、test_backup_p0.py:108 替 verify_restore），没有一个
真跑过 restore 路径——拆分/重构无回归保护。

本测试真跑整链：测试库建表灌数 → pg_dump 导出 → 组 ZIP →
restore_database_via_psql（DROP/CREATE + psql 导入）→ 数据往返断言。

安全边界（最重要）：
- restore 的 DROP/CREATE 目标由 DB_NAME 决定。目标库判定见 restore_env
  （TEST_DATABASE_URL 优先，派生兜底，安全闸强制 _test 后缀）。
- restore 用 DROP DATABASE ... WITH (FORCE)：会杀掉测试库上所有活跃连接，
  并**清空测试库全部数据**（从 dump 重建）。本测试独占测试库运行，不可与
  其它 pytest 会话/人工会话并行（OCR 评审 Low-6）；且须保持文件名字母序
  靠后（CI 单进程跑 pytest tests fastapi_app/tests 时，本文件在 tests/ 树
  之后执行，不破坏其会话级种子——未来重命名文件须重新核对此序）。
- 需要 PG_SUPER_PASSWORD（DROP/CREATE 用超级用户）或 DB_USER 有 CREATEDB；
  缺权限/缺 pg 工具时 skip 而非失败——环境不具备不是代码缺陷。
"""

from __future__ import annotations

import os
import zipfile
from pathlib import Path

import pytest

from fastapi_app.core.config import settings

pytestmark = [pytest.mark.asyncio]


def _pg_tools_available() -> bool:
    from fastapi_app.services.backup.dump import resolve_pg_tool

    try:
        return (Path(resolve_pg_tool('psql')).is_file()
                and Path(resolve_pg_tool('pg_dump')).is_file())
    except OSError:
        return False


@pytest.fixture()
def restore_env(monkeypatch, tmp_path):
    """把 restore 依赖的 env 全部钉到测试库；teardown 交由 monkeypatch 自动恢复。

    目标库判定（安全闸，OCR 评审 H1/H2 修正）：
    1. TEST_DATABASE_URL 环境变量已设 → 直接用它（CI 的权威口径，erp_test）；
    2. 否则从 settings.ASYNC_DATABASE_URL 派生「{主库}_test」（本机口径）。
    无论哪条路径，最终库名必须非空且以 _test 结尾——restore 会真 DROP/CREATE
    该库，绝不允许打到生产库。
    """
    from urllib.parse import unquote, urlparse, urlunparse

    env_test_url = os.environ.get('TEST_DATABASE_URL', '').strip()
    if env_test_url:
        test_url = env_test_url
    else:
        main_url = settings.ASYNC_DATABASE_URL
        parsed = urlparse(main_url)
        main_db = parsed.path.rsplit('/', 1)[-1]
        # 防二次派生：主库名本身不能已是 _test 库（那说明 URL 配置就有问题）
        assert main_db and not main_db.endswith('_test'), (
            f"安全闸：ASYNC_DATABASE_URL 的库名异常（{main_db!r}），拒绝派生"
        )
        test_url = urlunparse(parsed._replace(path=f"/{main_db}_test"))

    parsed = urlparse(test_url)
    test_name = parsed.path.rsplit('/', 1)[-1]
    assert test_name and test_name.endswith('_test'), (
        f"安全闸：restore 目标库必须是 <name>_test 测试库，得到 {test_name!r}"
    )

    userinfo = parsed.netloc.rsplit('@', 1)[0]
    db_user, _, encoded_password = userinfo.partition(':')
    # urlparse 不做 percent-decode（OCR 评审 M3）
    db_password = unquote(encoded_password)
    host = parsed.hostname or '127.0.0.1'
    port = str(parsed.port or 5432)

    monkeypatch.setenv('DB_HOST', host)
    monkeypatch.setenv('DB_PORT', port)
    monkeypatch.setenv('DB_USER', db_user)
    monkeypatch.setenv('DB_NAME', test_name)
    monkeypatch.setenv('DB_PASSWORD', db_password)
    monkeypatch.setenv('TEST_DATABASE_URL', test_url)
    # 超级用户凭据不在此注入：restore 用环境已有值（本机若配了 PG_SUPER_PASSWORD
    # 则走超级用户路径，否则回退 DB_USER——其无 CREATEDB 时 restore 干净拒绝）。
    yield {'db_name': test_name, 'db_user': db_user}


@pytest.fixture()
def _require_pg_tools():
    if not _pg_tools_available():
        pytest.skip('pg_dump/psql 不可用')


async def _make_engine():
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool
    return create_async_engine(os.environ['TEST_DATABASE_URL'], poolclass=NullPool)


async def test_restore_roundtrip_and_verify(restore_env, _require_pg_tools, tmp_path):
    """真跑 灌数→pg_dump→组ZIP→restore→探针数据往返。"""

    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.orm import sessionmaker

    from fastapi_app.services.backup.dump import restore_database_via_psql, run_pg_dump
    from fastapi_app.shared_models import Base

    engine = await _make_engine()
    async with engine.begin() as conn:
        # pg_trgm：customer 等模型的 trgm GIN 索引依赖（与 tests/conftest.py 同源）
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text(
            "INSERT INTO customer (name, status) VALUES ('restore_feature_probe', true)"
        ))
    await engine.dispose()

    # 真实 pg_dump
    dump_gz = tmp_path / 'dump.sql.gz'
    dump_result = await run_pg_dump(dump_gz)
    assert isinstance(dump_result, dict), dump_result
    assert dump_gz.is_file() and dump_gz.stat().st_size > 0, dump_result

    # 组 restore 可消费的 ZIP（成员名 database/dump.sql.gz）
    # run_pg_dump 输出本身已是 gzip，ZIP 成员直接放 .gz 原始字节（不再解压）
    zip_path = tmp_path / 'probe_backup.zip'
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.write(dump_gz, 'database/dump.sql.gz')

    # restore：独立一次性引擎/会话（restore 会 close 传入 db 并 dispose 应用引擎）
    probe_engine = await _make_engine()
    ProbeSession = sessionmaker(bind=probe_engine, class_=AsyncSession, expire_on_commit=False)
    async with ProbeSession() as db:
        with zipfile.ZipFile(zip_path) as zf:
            result = await restore_database_via_psql(zf, db)
    await probe_engine.dispose()

    assert result.get('status') == 'ok', f"restore 应完全成功，得到: {result}"

    # 探针数据必须回来
    engine = await _make_engine()
    async with engine.begin() as conn:
        count = (await conn.execute(text(
            "SELECT COUNT(*) FROM customer WHERE name = 'restore_feature_probe'"
        ))).scalar()
    await engine.dispose()
    assert count == 1, f"restore 后探针数据丢失（count={count}）"


async def test_restore_refuses_without_createdb(restore_env, _require_pg_tools, tmp_path):
    """无 CREATEDB/超级用户时 restore 必须在建库权预检处干净拒绝（不先删库）。

    已知覆盖缺口（OCR 评审 Low-5）：本机 DB_USER 历史手工角色碰巧有 CREATEDB，
    本测试在本机恒 skip——「拒绝路径已测」不能计入覆盖结论。伪造无权限场景
    （如 PG_SUPER_USER 指向不存在角色）会让预检前的连接检查先失败，错误文案
    不同，无法等价替代；真验证需一个无 CREATEDB 的专用角色，留待 CI 环境补。
    """
    if os.environ.get('PG_SUPER_PASSWORD'):
        pytest.skip('PG_SUPER_PASSWORD 已配置，走超级用户路径')
    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.orm import sessionmaker

    from fastapi_app.services.backup.dump import restore_database_via_psql

    # 造一个最小合法 ZIP（含 dump 成员）
    zip_path = tmp_path / 'probe.zip'
    with zipfile.ZipFile(zip_path, 'w') as zf:
        import gzip
        zf.writestr('database/dump.sql.gz', gzip.compress(b'SELECT 1;'))

    engine = await _make_engine()
    ProbeSession = sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with ProbeSession() as db:
        with zipfile.ZipFile(zip_path) as zf:
            result = await restore_database_via_psql(zf, db)
    await engine.dispose()

    if result.get('status') == 'ok':
        pytest.skip('DB_USER 实际具备建库权（本机环境特殊），拒绝路径无法触发')
    assert '建库权限' in (result.get('error') or '') or 'CREATEDB' in (result.get('error') or ''), result
