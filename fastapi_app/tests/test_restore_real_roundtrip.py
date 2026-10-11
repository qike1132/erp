"""restore 路径真跑特征测试（2026-10-11 复核 P2-14④）。

背景：backup 域现有测试全是 monkeypatch 替身（test_backup_m0_hotfix.py:82 替
restore_database_via_psql、test_backup_p0.py:108 替 verify_restore），没有一个
真跑过 restore 路径——拆分/重构无回归保护。

本测试真跑整链：**专用 scratch 库**建表灌数 → pg_dump 导出 → 组 ZIP →
restore_database_via_psql（DROP/CREATE + psql 导入）→ 数据往返断言。

隔离（OCR 评审 Medium 修正）：全程只操作一个**临时 scratch 库**
（`<主库>_restore_test`，跑完即 DROP），绝不触碰共享测试库或生产库——
restore 会 DROP DATABASE ... WITH (FORCE) 并清空目标库，用共享库会打挂同会话
其它测试（顺序敏感）。scratch 库名强制 `_test` 结尾（安全闸）。
"""
from __future__ import annotations

import gzip
import os
import tempfile
import zipfile
from pathlib import Path
from urllib.parse import unquote, urlparse, urlunparse

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
def restore_env(monkeypatch):
    """把 restore 依赖的 env 钉到专用 scratch 库；teardown 交由 monkeypatch。

    服务器/凭据来自 TEST_DATABASE_URL（CI 权威）或 settings（本机派生）；
    scratch 库名 = 测试库名去掉尾部 `_test` 再拼 `_restore_test`，
    保证与共享测试库不同且仍以 `_test` 结尾。
    """
    env_test_url = os.environ.get('TEST_DATABASE_URL', '').strip()
    base_url = env_test_url or settings.ASYNC_DATABASE_URL
    parsed = urlparse(base_url)
    base_db = parsed.path.rsplit('/', 1)[-1]
    assert base_db, "安全闸：无法解析测试库名"

    stem = base_db[:-len('_test')] if base_db.endswith('_test') else base_db
    scratch_db = f"{stem}_restore_test"
    assert scratch_db.endswith('_test') and scratch_db != base_db, (
        f"安全闸：scratch 库名非法（{scratch_db!r}）"
    )

    scratch_url = urlunparse(parsed._replace(path=f"/{scratch_db}"))
    userinfo = parsed.netloc.rsplit('@', 1)[0]
    db_user, _, encoded_password = userinfo.partition(':')
    db_password = unquote(encoded_password)  # urlparse 不做 percent-decode（OCR 评审 M3）
    host = parsed.hostname or '127.0.0.1'
    port = str(parsed.port or 5432)
    admin_url = urlunparse(parsed._replace(path='/postgres'))

    monkeypatch.setenv('DB_HOST', host)
    monkeypatch.setenv('DB_PORT', port)
    monkeypatch.setenv('DB_USER', db_user)
    monkeypatch.setenv('DB_NAME', scratch_db)
    monkeypatch.setenv('DB_PASSWORD', db_password)
    monkeypatch.setenv('TEST_DATABASE_URL', scratch_url)
    yield {'scratch_db': scratch_db, 'scratch_url': scratch_url,
           'admin_url': admin_url, 'base_db': base_db}


@pytest.fixture()
def _require_pg_tools():
    if not _pg_tools_available():
        pytest.skip('pg_dump/psql 不可用')


def _engine(url: str, *, autocommit: bool = False):
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool

    kwargs = {'poolclass': NullPool}
    if autocommit:
        kwargs['isolation_level'] = 'AUTOCOMMIT'
    return create_async_engine(url, **kwargs)


async def _drop_scratch(admin_url: str, name: str) -> None:
    from sqlalchemy import text

    engine = _engine(admin_url, autocommit=True)
    try:
        async with engine.connect() as conn:
            await conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
    finally:
        await engine.dispose()


async def _create_scratch(admin_url: str, name: str) -> None:
    from sqlalchemy import text

    engine = _engine(admin_url, autocommit=True)
    try:
        async with engine.connect() as conn:
            await conn.execute(text(f'CREATE DATABASE "{name}"'))
    finally:
        await engine.dispose()


async def test_restore_roundtrip_and_verify(restore_env, _require_pg_tools):
    """真跑 灌数→pg_dump→组ZIP→restore→探针数据往返（scratch 库，跑完即弃）。"""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.orm import sessionmaker

    from fastapi_app.services.backup.dump import restore_database_via_psql, run_pg_dump
    from fastapi_app.shared_models import Base

    admin_url = restore_env['admin_url']
    scratch_db = restore_env['scratch_db']

    try:
        try:
            await _create_scratch(admin_url, scratch_db)
        except Exception as e:  # noqa: BLE001 - 建库权限/环境不具备 → skip 而非失败
            pytest.skip(f'无法创建 scratch 库（{type(e).__name__}）: {e}')

        engine = _engine(restore_env['scratch_url'])
        async with engine.begin() as conn:
            # pg_trgm：customer 等模型的 trgm GIN 索引依赖（与 tests/conftest.py 同源）
            await conn.execute(text('CREATE EXTENSION IF NOT EXISTS pg_trgm'))
            await conn.run_sync(Base.metadata.create_all)
            await conn.execute(text(
                "INSERT INTO customer (name, status) VALUES ('restore_feature_probe', true)"
            ))
        await engine.dispose()

        # 真实 pg_dump（DB_NAME 已指向 scratch）
        tmpdir = Path(tempfile.mkdtemp(prefix='restore_probe_'))
        dump_gz = tmpdir / 'dump.sql.gz'
        dump_result = await run_pg_dump(dump_gz)
        assert isinstance(dump_result, dict), dump_result
        assert dump_gz.is_file() and dump_gz.stat().st_size > 0, dump_result

        # 组 restore 可消费的 ZIP（成员名 database/dump.sql.gz）
        # run_pg_dump 输出本身已是 gzip，ZIP 成员直接放 .gz 原始字节（不再解压）
        zip_path = tmpdir / 'probe_backup.zip'
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            zf.write(dump_gz, 'database/dump.sql.gz')

        # restore：独立一次性引擎/会话（restore 会 close 传入 db 并 dispose 应用引擎）
        probe_engine = _engine(restore_env['scratch_url'])
        ProbeSession = sessionmaker(bind=probe_engine, class_=AsyncSession, expire_on_commit=False)
        async with ProbeSession() as db:
            with zipfile.ZipFile(zip_path) as zf:
                result = await restore_database_via_psql(zf, db)
        await probe_engine.dispose()

        assert result.get('status') == 'ok', f"restore 应完全成功，得到: {result}"

        # 探针数据必须回来
        engine = _engine(restore_env['scratch_url'])
        async with engine.begin() as conn:
            count = (await conn.execute(text(
                "SELECT COUNT(*) FROM customer WHERE name = 'restore_feature_probe'"
            ))).scalar()
        await engine.dispose()
        assert count == 1, f"restore 后探针数据丢失（count={count}）"
    finally:
        await _drop_scratch(admin_url, scratch_db)


async def test_restore_refuses_without_createdb(restore_env, _require_pg_tools):
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

    # 造一个最小合法 ZIP（含 dump 成员）；scratch 库不存在，restore 的建库权预检
    # 应在 DROP 之前拒绝（本机有权限时会 skip）。
    tmpdir = Path(tempfile.mkdtemp(prefix='restore_probe_refuse_'))
    zip_path = tmpdir / 'probe.zip'
    with zipfile.ZipFile(zip_path, 'w') as zf:
        zf.writestr('database/dump.sql.gz', gzip.compress(b'SELECT 1;'))

    engine = _engine(restore_env['scratch_url'])
    ProbeSession = sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with ProbeSession() as db:
        with zipfile.ZipFile(zip_path) as zf:
            result = await restore_database_via_psql(zf, db)
    await engine.dispose()

    if result.get('status') == 'ok':
        pytest.skip('DB_USER 实际具备建库权（本机环境特殊），拒绝路径无法触发')
    assert '建库权限' in (result.get('error') or '') or 'CREATEDB' in (result.get('error') or ''), result
