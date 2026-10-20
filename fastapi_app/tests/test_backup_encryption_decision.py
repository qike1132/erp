"""Z05-R5：备份加密决策单点化（端点/服务层/ARQ 任务共用一套语义）。"""
import pytest

from fastapi_app.services.backup import crypto
from fastapi_app.services.backup.exceptions import BackupError


@pytest.fixture
def enabled(monkeypatch):
    monkeypatch.setattr(crypto, 'is_encryption_enabled', lambda: True)
    monkeypatch.setattr(crypto, 'get_backup_encryption_password', lambda: None)


@pytest.fixture
def disabled(monkeypatch):
    monkeypatch.setattr(crypto, 'is_encryption_enabled', lambda: False)
    monkeypatch.setattr(crypto, 'get_backup_encryption_password', lambda: None)


def test_switch_off_always_plaintext(disabled):
    assert crypto.resolve_encryption_decision(True, 'pw', degrade_when_missing=False) == (False, None)


def test_explicit_password_wins(enabled):
    assert crypto.resolve_encryption_decision(True, 'pw', degrade_when_missing=False) == (True, 'pw')


def test_encrypt_true_without_password_degrades_only_when_allowed(enabled):
    assert crypto.resolve_encryption_decision(True, None, degrade_when_missing=True) == (False, None)
    with pytest.raises(BackupError):
        crypto.resolve_encryption_decision(True, None, degrade_when_missing=False)


def test_encrypt_none_with_enabled_but_no_password_fails_closed(enabled):
    with pytest.raises(BackupError, match='拒绝产出不加密备份'):
        crypto.resolve_encryption_decision(None, None, degrade_when_missing=True)


def test_encrypt_false_is_plaintext_even_with_env_password(monkeypatch):
    monkeypatch.setattr(crypto, 'is_encryption_enabled', lambda: True)
    monkeypatch.setattr(crypto, 'get_backup_encryption_password', lambda: 'env-pw')
    assert crypto.resolve_encryption_decision(False, None, degrade_when_missing=False) == (False, None)
