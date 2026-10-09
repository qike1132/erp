"""恢复「重建数据库」的权限逻辑：无建库权必须**先拒绝**，绝不能先删库再建库失败。

背景（2026-10-09，新机恢复丢库）：dump.py 曾用应用角色 erp_app 同时执行 DROP 与 CREATE，
而该角色默认无 CREATEDB（deploy/install_package.ps1 建角色时未授予），于是
DROP 成功 → CREATE 失败 → 库停在「已删未建」。修复：重建改走超级用户，
并在 DROP 之前做建库权限预检（预检不过即中止，且不删除任何数据库）。
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from fastapi_app.services.backup import dump


def _proc(rc: int = 0, stdout: bytes = b'', stderr: bytes = b'') -> SimpleNamespace:
    return SimpleNamespace(returncode=rc, stdout=stdout, stderr=stderr)


def _install_fake_run_proc(monkeypatch, handler):
    """替换 dump.run_proc，记录每次调用的 (argv 拼接串, kwargs)。"""
    calls: list[tuple[str, dict]] = []

    async def _run(args, **kwargs):
        joined = ' '.join(list(args))
        calls.append((joined, kwargs))
        return handler(joined, kwargs)

    monkeypatch.setattr(dump, 'run_proc', _run)
    return calls


def test_admin_credentials_prefer_super_user() -> None:
    user, pw = dump._resolve_admin_credentials('erp_app', 'app-pw', {'PG_SUPER_PASSWORD': 'super-pw'})
    assert (user, pw) == ('postgres', 'super-pw')
    user, pw = dump._resolve_admin_credentials(
        'erp_app', 'app-pw', {'PG_SUPER_PASSWORD': 'super-pw', 'PG_SUPER_USER': 'dba'},
    )
    assert (user, pw) == ('dba', 'super-pw')


def test_admin_credentials_fall_back_to_app_role() -> None:
    user, pw = dump._resolve_admin_credentials('erp_app', 'app-pw', {})
    assert (user, pw) == ('erp_app', 'app-pw')


def test_admin_user_empty_value_falls_back_to_postgres() -> None:
    """PG_SUPER_USER= （空值而非缺键）不能让 psql -U '' 失败。"""
    user, pw = dump._resolve_admin_credentials(
        'erp_app', 'app-pw', {'PG_SUPER_PASSWORD': 'super-pw', 'PG_SUPER_USER': ''},
    )
    assert (user, pw) == ('postgres', 'super-pw')


@pytest.mark.asyncio
async def test_preflight_refuses_and_never_drops_without_createdb(monkeypatch) -> None:
    """角色无 CREATEDB → 返回错误，且**绝不发出** DROP/CREATE。"""
    calls = _install_fake_run_proc(monkeypatch, lambda joined, kw: _proc(0, b'false\n'))

    err = await dump._rebuild_database_with_admin(
        db_host='localhost', db_port='5432', admin_user='erp_app',
        admin_env={'PGPASSWORD': 'app'}, db_user='erp_app', db_name='erp_system',
    )

    assert err is not None and err['status'] == 'error'
    assert '缺少建库权限' in err['error']
    all_sql = ' '.join(joined for joined, _ in calls).upper()
    assert 'DROP DATABASE' not in all_sql
    assert 'CREATE DATABASE' not in all_sql


@pytest.mark.asyncio
async def test_preflight_psql_failure_aborts_before_drop(monkeypatch) -> None:
    calls = _install_fake_run_proc(monkeypatch, lambda joined, kw: _proc(1, b'', b'auth failed'))

    err = await dump._rebuild_database_with_admin(
        db_host='localhost', db_port='5432', admin_user='postgres',
        admin_env={'PGPASSWORD': 'wrong'}, db_user='erp_app', db_name='erp_system',
    )

    assert err is not None and err['status'] == 'error'
    assert len(calls) == 1  # 只做了权限预检，未继续 DROP/CREATE


@pytest.mark.asyncio
async def test_happy_path_uses_admin_creds_and_keeps_app_owner(monkeypatch) -> None:
    def handler(joined: str, kw):
        if 'rolsuper' in joined:
            return _proc(0, b'true\n')
        if 'SHOW server_version' in joined:
            return _proc(0, b'15.4\n')
        return _proc(0)

    calls = _install_fake_run_proc(monkeypatch, handler)

    err = await dump._rebuild_database_with_admin(
        db_host='localhost', db_port='5432', admin_user='postgres',
        admin_env={'PGPASSWORD': 'super'}, db_user='erp_app', db_name='erp_system',
    )

    assert err is None
    create = [joined for joined, _ in calls if 'CREATE DATABASE' in joined]
    assert create, '应发出 CREATE DATABASE'
    assert 'OWNER "erp_app"' in create[0]
    drop = [joined for joined, _ in calls if 'DROP DATABASE' in joined]
    assert drop and 'WITH (FORCE)' in drop[0]  # PG15+ 走 FORCE 断开残留连接
    # 全部重建命令都使用管理员身份与管理员口令（而非应用角色）
    assert all('-U postgres' in joined for joined, _ in calls)
    assert all(kw.get('env', {}).get('PGPASSWORD') == 'super' for _, kw in calls)
