"""restore_db.py CLI 的安全护栏（审计 P1-34）。

- DROP DATABASE 前必须先成功创建恢复前备份，否则中止；
- psql 恢复失败必须 exit 1，不能打印「恢复完成」假装成功。
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / 'scripts' / 'database' / 'restore_db.py'


def _load(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv('DB_PASSWORD', 'secret')
    monkeypatch.setenv('DB_NAME', 'erp_system')
    spec = importlib.util.spec_from_file_location('restore_db_cli_test', _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _prepare(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, module, name: str = 'dump.sql') -> Path:
    dump = tmp_path / name
    dump.write_text('-- dummy dump', encoding='utf-8')
    monkeypatch.setattr(sys, 'argv', ['restore_db.py', str(dump)])
    monkeypatch.setattr('builtins.input', lambda _prompt='': 'yes')
    monkeypatch.setattr(module, 'create_pre_restore_backup', lambda: tmp_path / 'pre.dump')
    return dump


def _fake_run(restore_code: int = 0, restore_stderr: bytes = b''):
    def run(args, **kwargs):
        is_restore = (
            '-v' in args
            and 'ON_ERROR_STOP=1' in args
            and ('stdin' in kwargs or 'input' in kwargs)
        )
        if is_restore:
            return subprocess.CompletedProcess(args, restore_code, b'', restore_stderr)
        return subprocess.CompletedProcess(args, 0, b'', b'')

    return run


def test_failed_restore_exits_1_and_never_claims_success(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    module = _load(monkeypatch)
    _prepare(monkeypatch, tmp_path, module)
    monkeypatch.setattr(module.subprocess, 'run', _fake_run(3, b'ERROR: syntax error at "("'))

    with pytest.raises(SystemExit) as exc:
        module.main()

    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert '恢复失败' in out
    assert '数据库恢复成功' not in out
    assert '恢复完成' not in out


def test_success_restore_prints_success(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    module = _load(monkeypatch)
    _prepare(monkeypatch, tmp_path, module)
    monkeypatch.setattr(module.subprocess, 'run', _fake_run())

    module.main()

    assert '数据库恢复成功!' in capsys.readouterr().out


def test_pre_restore_backup_failure_aborts_before_drop(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    module = _load(monkeypatch)
    _prepare(monkeypatch, tmp_path, module)

    def boom() -> Path:
        raise RuntimeError('pg_dump 失败')

    monkeypatch.setattr(module, 'create_pre_restore_backup', boom)

    def must_not_run(args, **kwargs):
        raise AssertionError('备份失败后不得执行 DROP/恢复')

    monkeypatch.setattr(module.subprocess, 'run', must_not_run)

    with pytest.raises(SystemExit) as exc:
        module.main()

    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert '中止恢复' in out


def test_pre_restore_backup_failure_can_be_overridden(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    module = _load(monkeypatch)
    dump = _prepare(monkeypatch, tmp_path, module)
    monkeypatch.setattr(
        sys, 'argv',
        ['restore_db.py', '--allow-missing-pre-restore-backup', str(dump)],
    )
    monkeypatch.setattr(module, 'create_pre_restore_backup', lambda: (_ for _ in ()).throw(RuntimeError('pg_dump 失败')))
    monkeypatch.setattr(module.subprocess, 'run', _fake_run())

    module.main()

    out = capsys.readouterr().out
    assert '--allow-missing-pre-restore-backup' in out
    assert '数据库恢复成功!' in out


def test_create_pre_restore_backup_writes_nonempty_dump(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _load(monkeypatch)
    monkeypatch.setattr(module, 'PRE_RESTORE_DIR', tmp_path / 'pre_restore')

    def fake_run(args, **kwargs):
        out = Path(args[args.index('-f') + 1])
        out.write_bytes(b'PGDMP')
        return subprocess.CompletedProcess(args, 0, b'', b'')

    monkeypatch.setattr(module.subprocess, 'run', fake_run)

    path = module.create_pre_restore_backup()

    assert path.parent == tmp_path / 'pre_restore'
    assert path.exists() and path.stat().st_size > 0


def test_create_pre_restore_backup_failure_raises(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _load(monkeypatch)
    monkeypatch.setattr(module, 'PRE_RESTORE_DIR', tmp_path / 'pre_restore')
    monkeypatch.setattr(
        module.subprocess, 'run',
        lambda args, **kwargs: subprocess.CompletedProcess(args, 1, b'', b'boom'),
    )

    with pytest.raises(RuntimeError, match='pg_dump 失败'):
        module.create_pre_restore_backup()


def test_create_pre_restore_backup_rejects_empty_dump(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _load(monkeypatch)
    monkeypatch.setattr(module, 'PRE_RESTORE_DIR', tmp_path / 'pre_restore')
    monkeypatch.setattr(
        module.subprocess, 'run',
        lambda args, **kwargs: subprocess.CompletedProcess(args, 0, b'', b''),
    )

    with pytest.raises(RuntimeError, match='产物为空'):
        module.create_pre_restore_backup()
