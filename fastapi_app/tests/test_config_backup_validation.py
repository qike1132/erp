"""生产环境备份/监控配置强校验（S3，2026-09-30）单测。

覆盖 fastapi_app/core/config.py 的 _validate_production_backup_config：
「已启用备份加密却拿不到可用密钥 ⇒ 拒绝启动」这条 fail-fast、分级告警，
以及 STRICT_CONFIG_CHECK 开关与「测试进程豁免」两项刻意设计。

注意：调用时一律传 force=True。默认参数下该函数在 pytest 进程内会整体跳过
（见 _is_test_process 的 docstring：本仓库多处测试为验证别的生产闸门而伪造
APP_ENV=production，且无 .env 的 CI 拿不到 BACKUP_* 值），该豁免本身也被下面的
test_default_call_is_skipped_inside_pytest 显式钉住。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from fastapi_app.core.config import (
    _is_test_process,
    _probe_dir_writable,
    _validate_production_backup_config,
)

_ENCRYPTION_KEYS = (
    "BACKUP_ENCRYPTION_ENABLED",
    "BACKUP_ENCRYPTION_PASSWORD",
    "BACKUP_ENCRYPTION_KEY",
)
_OTHER_KEYS = (
    "STRICT_CONFIG_CHECK",
    "BACKUP_DIR",
    "METRICS_BEARER_TOKEN",
    "BACKUP_ALERT_WEBHOOK_ENABLED",
    "BACKUP_ALERT_WEBHOOK_URL",
    "BACKUP_ALERT_EMAIL_ENABLED",
    "BACKUP_ALERT_SMTP_HOST",
    "BACKUP_STORAGE_LOCATION",
    "BACKUP_FULL_CRON",
)


@pytest.fixture
def backup_env(monkeypatch, tmp_path):
    """先清空所有相关变量（含 .env 注入的），再装一份「正确的生产基线」。

    基线让每个用例只需覆盖自己关心的那一项，且 assert == [] 才真正有意义
    （基线本身干净由 test_baseline_is_clean 钉住）。
    """
    for key in _ENCRYPTION_KEYS + _OTHER_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("BACKUP_ENCRYPTION_ENABLED", "true")
    monkeypatch.setenv("BACKUP_ENCRYPTION_PASSWORD", "baseline-secret")
    monkeypatch.setenv("BACKUP_DIR", str(tmp_path))
    monkeypatch.setenv("BACKUP_STORAGE_LOCATION", str(tmp_path))
    monkeypatch.setenv("BACKUP_FULL_CRON", "0 2 * * *")
    monkeypatch.setenv("METRICS_BEARER_TOKEN", "baseline-token")
    monkeypatch.setenv("BACKUP_ALERT_WEBHOOK_ENABLED", "false")
    monkeypatch.setenv("BACKUP_ALERT_EMAIL_ENABLED", "false")
    return monkeypatch


def _set(env, **kwargs):
    for key, value in kwargs.items():
        env.setenv(key, value)


class TestBackupEncryptionFailFast:
    """生效的备份加密必须拿得到密钥，否则产出无法解密的备份文件。"""

    def test_enabled_without_any_key_raises(self, backup_env):
        _set(backup_env, BACKUP_ENCRYPTION_ENABLED="true", BACKUP_ENCRYPTION_PASSWORD="", BACKUP_ENCRYPTION_KEY="")
        with pytest.raises(RuntimeError, match="备份加密"):
            _validate_production_backup_config(force=True)

    def test_placeholder_password_raises(self, backup_env):
        _set(backup_env, BACKUP_ENCRYPTION_ENABLED="true", BACKUP_ENCRYPTION_PASSWORD="<changeme>", BACKUP_ENCRYPTION_KEY="")
        with pytest.raises(RuntimeError, match="备份加密"):
            _validate_production_backup_config(force=True)

    def test_password_satisfies_check(self, backup_env):
        # 夹具字面值（非真实凭据）：按仓库约定逐行豁免 hook 第 2 层的口令规则
        # secret-scan:allow-next-line
        _set(backup_env, BACKUP_ENCRYPTION_ENABLED="true", BACKUP_ENCRYPTION_PASSWORD="a-real-secret", BACKUP_ENCRYPTION_KEY="")
        assert _validate_production_backup_config(force=True) == []

    def test_master_key_alone_satisfies_check(self, backup_env):
        _set(backup_env, BACKUP_ENCRYPTION_ENABLED="true", BACKUP_ENCRYPTION_PASSWORD="", BACKUP_ENCRYPTION_KEY="0123456789abcdef")
        assert _validate_production_backup_config(force=True) == []

    def test_disabled_encryption_does_not_require_key(self, backup_env):
        _set(backup_env, BACKUP_ENCRYPTION_ENABLED="false", BACKUP_ENCRYPTION_PASSWORD="", BACKUP_ENCRYPTION_KEY="")
        assert _validate_production_backup_config(force=True) == []

    def test_undeclared_flag_warns_but_does_not_raise(self, backup_env):
        """未声明 BACKUP_ENCRYPTION_ENABLED（代码默认 false）只告警，不阻断启动。"""
        backup_env.delenv("BACKUP_ENCRYPTION_ENABLED", raising=False)
        warnings = _validate_production_backup_config(force=True)
        assert any("BACKUP_ENCRYPTION_ENABLED" in w for w in warnings)

    def test_baseline_is_clean(self, backup_env):
        """基线（等价于一份配置正确的生产 .env）必须零告警、不抛错。"""
        assert _validate_production_backup_config(force=True) == []


class TestStrictConfigCheckSwitch:
    def test_false_disables_the_whole_check(self, backup_env):
        _set(
            backup_env,
            BACKUP_ENCRYPTION_ENABLED="true",
            BACKUP_ENCRYPTION_PASSWORD="",
            BACKUP_ENCRYPTION_KEY="",
            STRICT_CONFIG_CHECK="false",
        )
        assert _validate_production_backup_config(force=True) == []

    @pytest.mark.parametrize("value", ["0", "no", "off", "FALSE"])
    def test_other_falsy_spellings_disable_too(self, backup_env, value):
        _set(
            backup_env,
            BACKUP_ENCRYPTION_ENABLED="true",
            BACKUP_ENCRYPTION_PASSWORD="",
            BACKUP_ENCRYPTION_KEY="",
            STRICT_CONFIG_CHECK=value,
        )
        assert _validate_production_backup_config(force=True) == []


class TestBackupDir:
    def test_missing_dir_is_warning_not_error(self, backup_env, tmp_path):
        missing = tmp_path / "not-created-yet"
        _set(backup_env, BACKUP_DIR=str(missing))
        warnings = _validate_production_backup_config(force=True)
        assert any("BACKUP_DIR" in w for w in warnings)
        assert not missing.exists(), "校验不应有副作用（目录由 ensure_backup_dir 在首次使用时创建）"

    def test_existing_writable_dir_passes(self, backup_env, tmp_path):
        _set(backup_env, BACKUP_DIR=str(tmp_path))
        assert _validate_production_backup_config(force=True) == []

    def test_probe_dir_writable_rejects_file_path(self, tmp_path):
        """写探测对「不是目录」的路径必须返回 False（否则会漏判不可写）。"""
        a_file = tmp_path / "a-file.txt"
        a_file.write_text("x", encoding="utf-8")
        assert _probe_dir_writable(a_file) is False
        assert _probe_dir_writable(tmp_path) is True

    def test_unset_dir_warns_about_same_disk(self, backup_env):
        backup_env.delenv("BACKUP_DIR", raising=False)
        warnings = _validate_production_backup_config(force=True)
        assert any("backups/server" in w for w in warnings)


class TestNonFatalWarnings:
    def test_missing_metrics_token_warns(self, backup_env):
        _set(backup_env, METRICS_BEARER_TOKEN="")
        warnings = _validate_production_backup_config(force=True)
        assert any("METRICS_BEARER_TOKEN" in w for w in warnings)

    def test_webhook_enabled_without_url_warns(self, backup_env):
        _set(
            backup_env,
            BACKUP_ALERT_WEBHOOK_ENABLED="true",
            BACKUP_ALERT_WEBHOOK_URL="",
        )
        warnings = _validate_production_backup_config(force=True)
        assert any("BACKUP_ALERT_WEBHOOK_URL" in w for w in warnings)

    def test_email_enabled_without_smtp_host_warns(self, backup_env):
        _set(
            backup_env,
            BACKUP_ALERT_EMAIL_ENABLED="true",
            BACKUP_ALERT_SMTP_HOST="",
        )
        warnings = _validate_production_backup_config(force=True)
        assert any("BACKUP_ALERT_SMTP_HOST" in w for w in warnings)

    def test_missing_cron_keys_warn_with_defaults(self, backup_env):
        _set(backup_env, BACKUP_FULL_CRON="")
        warnings = _validate_production_backup_config(force=True)
        joined = " ".join(warnings)
        assert "BACKUP_FULL_CRON" in joined


class TestPytestExemption:
    """测试进程豁免：这是刻意设计，必须显式钉住，避免被误当漏洞修掉。"""

    def test_is_test_process_true_under_pytest(self):
        assert _is_test_process() is True

    def test_default_call_is_skipped_inside_pytest(self, backup_env):
        _set(backup_env, BACKUP_ENCRYPTION_ENABLED="true", BACKUP_ENCRYPTION_PASSWORD="", BACKUP_ENCRYPTION_KEY="")
        # 不传 force：pytest 进程内直接返回空列表，绝不抛错
        assert _validate_production_backup_config() == []


class TestHelpers:
    def test_placeholder_detection(self):
        from fastapi_app.core.config import _looks_like_placeholder

        for value in ("", "  ", "<your-password>", "CHANGE-ME", "your-secret", "xxx"):
            assert _looks_like_placeholder(value) is True, value
        for value in ("a-real-secret", "s3cr3t-with-<char>", "0123456789abcdef"):
            assert _looks_like_placeholder(value) is False, value

    def test_probe_accepts_pathlike(self, tmp_path: Path):
        assert _probe_dir_writable(Path(tmp_path)) is True
