"""restore 实现的收敛与护栏（审计 P1-34 + F1-7）。

P1-34
    - DROP DATABASE 前必须先成功创建恢复前备份，否则中止；
    - psql 恢复失败必须 exit 1，不能打印「恢复完成」假装成功。

F1-7
    恢复逻辑收敛到 `scripts/database/restore_core.py` **一份实现**：
    `restore_db.py`（CLI）与 `db_manager.py`（库）都只是它的调用方。
    收敛前两边各持一套实现且互不调用，任何修复只会落在一侧 —— P1-34 正是这么漏的
    （db_manager 侧有「恢复后表数校验」，restore_db 侧没有）。

本文件分三组：
    ① restore_core 的行为契约（备份 fail-closed / ON_ERROR_STOP / 落地校验）；
    ② restore_db.py CLI 的行为契约（失败 exit 1、假成功禁令、写库授权）；
    ③ 收敛性（两个入口都走 restore_core，CLI 里不再自带恢复序列）。
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_CORE = _ROOT / 'scripts' / 'database' / 'restore_core.py'
_CLI = _ROOT / 'scripts' / 'database' / 'restore_db.py'
_DB_MANAGER = _ROOT / 'scripts' / 'database' / 'db_manager.py'


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # 注册进 sys.modules：restore_db.py 内部 `from restore_core import ...`
    # 必须拿到**同一个**模块对象，否则打桩打不到它。
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def core(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv('DB_PASSWORD', 'secret')
    monkeypatch.setenv('DB_NAME', 'erp_system')
    return _load('restore_core', _CORE)


@pytest.fixture
def cli(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv('DB_PASSWORD', 'secret')
    monkeypatch.setenv('DB_NAME', 'erp_system')
    _load('restore_core', _CORE)  # 保证 sys.modules['restore_core'] 已就位
    return _load('restore_db', _CLI)


def _completed(args, code=0, stdout=b'', stderr=b''):
    return subprocess.CompletedProcess(args, code, stdout, stderr)


# ---------------------------------------------------------------------------
# ① restore_core 行为契约
# ---------------------------------------------------------------------------


def test_pre_restore_backup_failure_aborts_before_drop(core, monkeypatch):
    """恢复前备份失败 → 立刻中止，绝不往下走 DROP/恢复。"""
    monkeypatch.setattr(
        core, 'create_pre_restore_backup',
        lambda *a, **k: (_ for _ in ()).throw(core.RestoreError('pg_dump 失败')),
    )

    def must_not_run(args, **kwargs):
        raise AssertionError('备份失败后不得执行 DROP/恢复')

    monkeypatch.setattr(core.subprocess, 'run', must_not_run)

    outcome = core.restore_postgres(sql_bytes=b'SELECT 1;', require_consent=False)

    assert outcome.ok is False
    assert '已中止恢复' in outcome.message


def test_pre_restore_backup_failure_can_be_overridden(core, monkeypatch):
    """显式允许后仍可继续（但必须留下告警）。"""
    monkeypatch.setattr(
        core, 'create_pre_restore_backup',
        lambda *a, **k: (_ for _ in ()).throw(core.RestoreError('pg_dump 失败')),
    )
    monkeypatch.setattr(core, 'terminate_connections', lambda *a, **k: None)
    monkeypatch.setattr(core, 'drop_and_recreate_db', lambda *a, **k: None)
    monkeypatch.setattr(core, '_psql_restore', lambda *a, **k: _completed(['psql']))
    monkeypatch.setattr(core, 'count_public_tables', lambda *a, **k: 3)

    outcome = core.restore_postgres(
        sql_bytes=b'SELECT 1;', require_consent=False, allow_missing_pre_backup=True)

    assert outcome.ok is True
    assert outcome.table_count == 3


def test_failed_restore_returns_not_ok_and_never_claims_success(core, monkeypatch):
    """psql 失败 → ok=False，message 里带上 psql 退出码与错误行。"""
    monkeypatch.setattr(core, 'create_pre_restore_backup', lambda *a, **k: Path('pre.dump'))
    monkeypatch.setattr(core, 'terminate_connections', lambda *a, **k: None)
    monkeypatch.setattr(core, 'drop_and_recreate_db', lambda *a, **k: None)
    monkeypatch.setattr(
        core, '_psql_restore',
        lambda *a, **k: _completed(['psql'], 3, b'', b'ERROR: syntax error at "("'),
    )

    outcome = core.restore_postgres(sql_bytes=b'bad', require_consent=False)

    assert outcome.ok is False
    assert '恢复失败' in outcome.message
    assert '退出码=3' in outcome.message


def test_psql_restore_always_sets_on_error_stop(core, monkeypatch):
    """psql 一律 ON_ERROR_STOP=1 —— 否则 SQL 错误不会让 psql 返回非零退出码，失败判定假绿。"""
    seen: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        seen.append(list(cmd))
        return _completed(cmd)

    monkeypatch.setattr(core.subprocess, 'run', fake_run)

    core._psql_restore(core.db_config(), sql_bytes=b'SELECT 1;')

    assert seen, 'psql 未被调用'
    assert 'ON_ERROR_STOP=1' in seen[0]


def test_restore_fails_when_no_tables_landed(core, monkeypatch):
    """psql 退出码 0 但 public schema 一张表都没有 → 判失败（dump 可能是空的）。"""
    monkeypatch.setattr(core, 'create_pre_restore_backup', lambda *a, **k: Path('pre.dump'))
    monkeypatch.setattr(core, 'terminate_connections', lambda *a, **k: None)
    monkeypatch.setattr(core, 'drop_and_recreate_db', lambda *a, **k: None)
    monkeypatch.setattr(core, '_psql_restore', lambda *a, **k: _completed(['psql']))
    monkeypatch.setattr(core, 'count_public_tables', lambda *a, **k: 0)

    outcome = core.restore_postgres(sql_bytes=b'', require_consent=False)

    assert outcome.ok is False
    assert '无任何表' in outcome.message


def test_create_pre_restore_backup_writes_nonempty_dump(core, monkeypatch, tmp_path):
    monkeypatch.setattr(core, 'PRE_RESTORE_DIR', tmp_path / 'pre_restore')

    def fake_run(args, **kwargs):
        out = Path(args[args.index('-f') + 1])
        out.write_bytes(b'PGDMP')
        return _completed(args, 0, b'', b'')

    monkeypatch.setattr(core.subprocess, 'run', fake_run)

    path = core.create_pre_restore_backup()

    assert path.parent == tmp_path / 'pre_restore'
    assert path.exists() and path.stat().st_size > 0


def test_create_pre_restore_backup_failure_raises(core, monkeypatch, tmp_path):
    monkeypatch.setattr(core, 'PRE_RESTORE_DIR', tmp_path / 'pre_restore')
    monkeypatch.setattr(
        core.subprocess, 'run',
        lambda args, **kwargs: _completed(args, 1, b'', b'boom'),
    )

    with pytest.raises(core.RestoreError, match='pg_dump 失败'):
        core.create_pre_restore_backup()


def test_create_pre_restore_backup_rejects_empty_dump(core, monkeypatch, tmp_path):
    monkeypatch.setattr(core, 'PRE_RESTORE_DIR', tmp_path / 'pre_restore')
    monkeypatch.setattr(
        core.subprocess, 'run',
        lambda args, **kwargs: _completed(args, 0, b'', b''),
    )

    with pytest.raises(core.RestoreError, match='产物为空'):
        core.create_pre_restore_backup()


def test_zip_with_json_export_is_rejected(core, tmp_path):
    """ZIP 内是 JSON 格式导出 → 明确报错，不当作可恢复的 SQL 处理。"""
    import zipfile

    zpath = tmp_path / 'backup.zip'
    with zipfile.ZipFile(zpath, 'w') as zf:
        zf.writestr('database/dump.json', '{}')

    with pytest.raises(core.UnsupportedBackupFormatError):
        core.read_backup_sql(zpath)


# ---------------------------------------------------------------------------
# ② restore_db.py CLI 行为契约
# ---------------------------------------------------------------------------


def _prepare_cli(monkeypatch, cli, tmp_path, *, consent=True):
    dump = tmp_path / 'dump.sql'
    dump.write_text('-- dummy dump', encoding='utf-8')
    monkeypatch.setattr(sys, 'argv', ['restore_db.py', str(dump)])
    monkeypatch.setattr('builtins.input', lambda _prompt='': 'yes')
    if consent:
        monkeypatch.setenv('ERP_ALLOW_PROD_WRITE', '1')
    else:
        monkeypatch.delenv('ERP_ALLOW_PROD_WRITE', raising=False)
    return dump


def test_cli_failed_restore_exits_1_and_never_claims_success(cli, monkeypatch, tmp_path, capsys):
    _prepare_cli(monkeypatch, cli, tmp_path)
    outcome_cls = sys.modules['restore_core'].RestoreOutcome
    monkeypatch.setattr(
        cli, 'restore_from_file',
        lambda *a, **k: outcome_cls(ok=False, message='PostgreSQL 恢复失败'),
    )

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert '数据库恢复成功' not in out
    assert '恢复完成' not in out


def test_cli_success_restore_prints_success(cli, monkeypatch, tmp_path, capsys):
    _prepare_cli(monkeypatch, cli, tmp_path)
    outcome_cls = sys.modules['restore_core'].RestoreOutcome
    monkeypatch.setattr(
        cli, 'restore_from_file',
        lambda *a, **k: outcome_cls(ok=True, message='ok', table_count=12),
    )

    cli.main()

    assert '数据库恢复成功!' in capsys.readouterr().out


def test_cli_requires_prod_write_consent(cli, monkeypatch, tmp_path):
    """未授权写生产库 → SystemExit(3)，且不得调用恢复实现。"""
    _prepare_cli(monkeypatch, cli, tmp_path, consent=False)

    def must_not_run(*a, **k):
        raise AssertionError('未授权时不得进入恢复流程')

    monkeypatch.setattr(cli, 'restore_from_file', must_not_run)

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 3


def test_cli_rejects_invalid_db_name(cli, monkeypatch, tmp_path):
    """库名不是合法标识符 → 直接拒绝（避免被拼进 SQL）。"""
    dump = tmp_path / 'dump.sql'
    dump.write_text('-- dummy dump', encoding='utf-8')
    monkeypatch.setattr(sys, 'argv', ['restore_db.py', str(dump)])
    monkeypatch.setenv('DB_NAME', 'bad-name; DROP DATABASE x')

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 1


# ---------------------------------------------------------------------------
# ③ 收敛性：两个入口都走 restore_core
# ---------------------------------------------------------------------------


def test_cli_has_no_own_restore_sequence():
    """CLI 里不得再自带恢复序列（DROP/psql/备份）——那会重新长出第二份实现。

    按 AST 判定：只看**代码**（字符串字面量与 import），不看文档字符串 ——
    模块说明里出现「psql」是正常的。
    """
    import ast

    source = _CLI.read_text(encoding='utf-8')
    tree = ast.parse(source)

    imports = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    assert 'subprocess' not in imports, 'restore_db.py 不该自己起子进程执行 psql/pg_dump'

    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            doc = ast.get_docstring(node, clean=False)
            if doc:
                docstrings.add(doc)

    literals = {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and node.value not in docstrings
    }
    for token in ('DROP DATABASE', 'ON_ERROR_STOP', 'pg_dump', 'terminate_backend'):
        assert not any(token in s for s in literals), \
            f'restore_db.py 仍自带恢复实现片段: {token}'


def test_db_manager_restore_delegates_to_restore_core(monkeypatch):
    """db_manager.restore_postgresql 必须调 restore_core.restore_from_file。"""
    db_manager = _load('db_manager_under_test', _DB_MANAGER)
    core = sys.modules.get('restore_core') or _load('restore_core', _CORE)

    calls: list[tuple] = []

    def fake_restore_from_file(path, **kwargs):
        calls.append((path, kwargs))
        return core.RestoreOutcome(ok=True, message='ok', table_count=7)

    monkeypatch.setattr(core, 'restore_from_file', fake_restore_from_file)

    stub = SimpleNamespace(
        db_type='postgresql',
        get_db_config=lambda: {'host': 'h', 'port': '5432', 'user': 'u',
                               'password': 'p', 'database': 'd'},
        log=lambda *a, **k: None,
    )
    ok, message = db_manager.DatabaseManager.restore_postgresql(stub, Path('b.sql'))

    assert ok is True
    assert 'ok' in message
    assert len(calls) == 1
    assert calls[0][0] == Path('b.sql')
    assert calls[0][1]['config']['database'] == 'd'


def test_db_manager_restore_mysql_aborts_when_pre_backup_fails(monkeypatch):
    """MySQL 路径同样 fail-closed：恢复前备份失败不得继续恢复。"""
    db_manager = _load('db_manager_mysql_test', _DB_MANAGER)

    stub = SimpleNamespace(
        db_type='mysql',
        get_db_config=lambda: {'host': 'h', 'port': '3306', 'user': 'u',
                               'password': 'p', 'database': 'd'},
        log=lambda *a, **k: None,
        backup_mysql=lambda *a, **k: (False, '备份失败', None),
    )

    ok, message = db_manager.DatabaseManager.restore_mysql(stub, Path('b.sql'))

    assert ok is False
    assert '已中止恢复' in message


# ---------------------------------------------------------------------------
# ② 合并前审查 H3：恢复成功不得被 stderr 噪音误报成失败
# ---------------------------------------------------------------------------


def test_restore_success_with_noisy_stderr_is_not_reported_failed(core, monkeypatch):
    """psql 退出码 0 + stderr 含非致命 ERROR 行（must be owner / role 不存在）
    → 恢复**成功**，不得 ok=False 诱导运维对好库重放。

    ON_ERROR_STOP=1 下真错误必然非零退出，故失败判定只看 returncode；
    ERROR 噪音行降级为日志告警。
    """
    noisy_stderr = (
        b'psql: WARNING: there is already a transaction in progress\n'
        b'ERROR: must be owner of table public.foo\n'
        b'ERROR: role "app_rw" does not exist\n'
    )
    monkeypatch.setattr(core, 'create_pre_restore_backup', lambda *a, **k: Path('pre.dump'))
    monkeypatch.setattr(core, 'terminate_connections', lambda *a, **k: None)
    monkeypatch.setattr(core, 'drop_and_recreate_db', lambda *a, **k: None)
    monkeypatch.setattr(
        core, '_psql_restore',
        lambda *a, **k: _completed(['psql'], 0, b'', noisy_stderr),
    )
    monkeypatch.setattr(core, 'count_public_tables', lambda *a, **k: 42)

    logs: list[str] = []
    outcome = core.restore_postgres(sql_bytes=b'SELECT 1;', require_consent=False, log=logs.append)

    assert outcome.ok is True
    assert outcome.table_count == 42
    # 噪音行以警告形式留痕，方便运维排查，但不改变结论
    assert any('[警告]' in line and 'must be owner' in line for line in logs)


def test_restore_nonzero_exit_still_reports_failed(core, monkeypatch):
    """对照：退出码非 0（真错误）必须维持 ok=False——防止把 H3 修成放水。"""
    monkeypatch.setattr(core, 'create_pre_restore_backup', lambda *a, **k: Path('pre.dump'))
    monkeypatch.setattr(core, 'terminate_connections', lambda *a, **k: None)
    monkeypatch.setattr(core, 'drop_and_recreate_db', lambda *a, **k: None)
    monkeypatch.setattr(
        core, '_psql_restore',
        lambda *a, **k: _completed(['psql'], 1, b'', b'ERROR: syntax error at or near "xxx"'),
    )
    monkeypatch.setattr(core, 'count_public_tables', lambda *a, **k: 0)

    outcome = core.restore_postgres(sql_bytes=b'bad', require_consent=False)

    assert outcome.ok is False
    assert '恢复失败' in outcome.message
    assert '退出码=1' in outcome.message
