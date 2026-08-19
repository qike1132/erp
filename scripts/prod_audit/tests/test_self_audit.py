"""Group 15.1 — 审核工程自测。

测试内容:
    - EvidenceArchiver.sanitize() 脱敏覆盖各模式
    - IssueBuilder issue_id 唯一性与层内序号自增
    - check_gate 各严重度阈值逻辑
    - ConfigLoader 配置校验(权重之和 / 缺失文件 / 非法配置)
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from scripts.prod_audit.base.issue_builder import IssueBuilder
from scripts.prod_audit.base.layer_base import (
    AuditIssue,
    LayerBase,
    Severity,
)
from scripts.prod_audit.config_loader import ConfigLoader
from scripts.prod_audit.evidence_archiver import EvidenceArchiver
from scripts.prod_audit.exceptions import AuditConfigError

# ---------------------------------------------------------------------------
# 15.1a EvidenceArchiver.sanitize 脱敏
# ---------------------------------------------------------------------------


class TestSanitize:
    """测试 :meth:`EvidenceArchiver.sanitize` 脱敏覆盖。"""

    @pytest.mark.parametrize(
        "raw,should_not_contain",
        [
            ('password = "my_secret_123"', "my_secret_123"),
            ("password: 'my_secret_123'", "my_secret_123"),
            ("api_key=ABCDEF123456", "ABCDEF123456"),
            ("api_key: ABCDEF123456", "ABCDEF123456"),
            ("token: \"eyJhbGciOiJIUzI1\"", "eyJhbGciOiJIUzI1"),
            ("secret = topsecret_value", "topsecret_value"),
            ("DATABASE_URL=postgres://user:pass@host/db", "pass"),
            ("dsn: 'postgres://user:pass@host/db'", "pass"),
            ("private_key: -----BEGIN RSA PRIVATE KEY-----", "-----BEGIN RSA PRIVATE KEY-----"),
            ("access_key: AKIAIOSFODNN7EXAMPLE", "AKIAIOSFODNN7EXAMPLE"),
        ],
    )
    def test_sensitive_patterns_redacted(self, raw: str, should_not_contain: str) -> None:
        """敏感模式被替换为 [REDACTED]。"""
        result = EvidenceArchiver.sanitize(raw)
        assert should_not_contain not in result
        assert "[REDACTED]" in result

    def test_non_sensitive_content_unchanged(self) -> None:
        """非敏感内容不变。"""
        raw = "layer_id: L1\nstatus: passed\nscore: 100"
        result = EvidenceArchiver.sanitize(raw)
        assert result == raw

    def test_multiple_sensitive_fields(self) -> None:
        """多个敏感字段同时脱敏。"""
        raw = (
            'password = "secret1"\n'
            'api_key = "key2"\n'
            'token = "tok3"\n'
        )
        result = EvidenceArchiver.sanitize(raw)
        assert "secret1" not in result
        assert "key2" not in result
        assert "tok3" not in result
        assert result.count("[REDACTED]") >= 3

    def test_url_embedded_credentials(self) -> None:
        """URL 内嵌凭证脱敏。"""
        raw = "postgres://admin:hunter2@db.example.com:5432/mydb"
        result = EvidenceArchiver.sanitize(raw)
        assert "hunter2" not in result
        assert "[REDACTED]" in result

    def test_sanitize_idempotent(self) -> None:
        """脱敏后再次脱敏结果不变。"""
        raw = 'password = "secret123"'
        once = EvidenceArchiver.sanitize(raw)
        twice = EvidenceArchiver.sanitize(once)
        assert once == twice


# ---------------------------------------------------------------------------
# 15.1b IssueBuilder 自增与唯一性
# ---------------------------------------------------------------------------


class TestIssueBuilder:
    """测试 :class:`IssueBuilder` issue_id 自增与唯一性。"""

    def test_auto_increment_within_layer(self) -> None:
        """同层 issue_id 自增。"""
        builder = IssueBuilder()
        issue1 = builder.build(
            layer_id="L3",
            severity=Severity.HIGH,
            file="a.py",
            line=1,
            description="d1",
            suggestion="s1",
            rule_id="r1",
            owner="o",
            due_date="2026-12-31",
        )
        issue2 = builder.build(
            layer_id="L3",
            severity=Severity.HIGH,
            file="b.py",
            line=2,
            description="d2",
            suggestion="s2",
            rule_id="r2",
            owner="o",
            due_date="2026-12-31",
        )
        assert issue1.issue_id == "L3-001"
        assert issue2.issue_id == "L3-002"

    def test_independent_counters_per_layer(self) -> None:
        """不同层计数器独立。"""
        builder = IssueBuilder()
        i1 = builder.build(
            layer_id="L1", severity=Severity.LOW, file="a", line=1,
            description="d", suggestion="s", rule_id="r", owner="o", due_date="2026-12-31",
        )
        i2 = builder.build(
            layer_id="L2", severity=Severity.LOW, file="a", line=1,
            description="d", suggestion="s", rule_id="r", owner="o", due_date="2026-12-31",
        )
        i3 = builder.build(
            layer_id="L1", severity=Severity.LOW, file="a", line=1,
            description="d", suggestion="s", rule_id="r", owner="o", due_date="2026-12-31",
        )
        assert i1.issue_id == "L1-001"
        assert i2.issue_id == "L2-001"
        assert i3.issue_id == "L1-002"

    def test_issue_id_uniqueness(self) -> None:
        """100 次构造 issue_id 唯一。"""
        builder = IssueBuilder()
        ids = set()
        for i in range(100):
            issue = builder.build(
                layer_id="L5", severity=Severity.LOW, file="a", line=1,
                description=f"d{i}", suggestion="s", rule_id="r", owner="o", due_date="2026-12-31",
            )
            ids.add(issue.issue_id)
        assert len(ids) == 100

    def test_reset_layer(self) -> None:
        """reset(layer_id) 重置指定层计数器。"""
        builder = IssueBuilder()
        builder.build(
            layer_id="L1", severity=Severity.LOW, file="a", line=1,
            description="d", suggestion="s", rule_id="r", owner="o", due_date="2026-12-31",
        )
        builder.reset("L1")
        assert builder.current_seq("L1") == 0

    def test_reset_all(self) -> None:
        """reset() 重置所有层计数器。"""
        builder = IssueBuilder()
        builder.build(
            layer_id="L1", severity=Severity.LOW, file="a", line=1,
            description="d", suggestion="s", rule_id="r", owner="o", due_date="2026-12-31",
        )
        builder.build(
            layer_id="L2", severity=Severity.LOW, file="a", line=1,
            description="d", suggestion="s", rule_id="r", owner="o", due_date="2026-12-31",
        )
        builder.reset()
        assert builder.current_seq("L1") == 0
        assert builder.current_seq("L2") == 0


# ---------------------------------------------------------------------------
# 15.1c check_gate 严重度阈值逻辑
# ---------------------------------------------------------------------------


class _DummyLayer(LayerBase):
    layer_id = "L1"
    layer_name = "dummy"
    weight = 0.1

    async def run(self, context):
        ...


def _make_issue(severity: Severity) -> AuditIssue:
    builder = IssueBuilder()
    return builder.build(
        layer_id="L1",
        severity=severity,
        file="test.py",
        line=1,
        description="test",
        suggestion="fix",
        rule_id="L1-TEST",
        owner="o",
        due_date="2026-12-31",
    )


class TestCheckGate:
    """测试 :meth:`LayerBase.check_gate` 各严重度阈值。"""

    def test_empty_issues_passes(self) -> None:
        """无问题门禁通过。"""
        layer = _DummyLayer()
        assert layer.check_gate([], threshold=Severity.HIGH) is True

    def test_info_below_high_threshold(self) -> None:
        """info 问题低于 high 阈值,门禁通过。"""
        layer = _DummyLayer()
        assert layer.check_gate([_make_issue(Severity.INFO)], threshold=Severity.HIGH) is True

    def test_low_below_high_threshold(self) -> None:
        """low 问题低于 high 阈值,门禁通过。"""
        layer = _DummyLayer()
        assert layer.check_gate([_make_issue(Severity.LOW)], threshold=Severity.HIGH) is True

    def test_medium_below_high_threshold(self) -> None:
        """medium 问题低于 high 阈值,门禁通过。"""
        layer = _DummyLayer()
        assert layer.check_gate([_make_issue(Severity.MEDIUM)], threshold=Severity.HIGH) is True

    def test_high_at_high_threshold_blocks(self) -> None:
        """high 问题达 high 阈值,门禁失败。"""
        layer = _DummyLayer()
        assert layer.check_gate([_make_issue(Severity.HIGH)], threshold=Severity.HIGH) is False

    def test_critical_above_high_threshold_blocks(self) -> None:
        """critical 问题超 high 阈值,门禁失败。"""
        layer = _DummyLayer()
        assert layer.check_gate([_make_issue(Severity.CRITICAL)], threshold=Severity.HIGH) is False

    def test_mixed_issues_blocks(self) -> None:
        """混合问题中有 high 则门禁失败。"""
        layer = _DummyLayer()
        issues = [
            _make_issue(Severity.INFO),
            _make_issue(Severity.LOW),
            _make_issue(Severity.HIGH),
        ]
        assert layer.check_gate(issues, threshold=Severity.HIGH) is False

    def test_medium_threshold_blocks_medium(self) -> None:
        """medium 阈值下 medium 问题阻断。"""
        layer = _DummyLayer()
        assert layer.check_gate([_make_issue(Severity.MEDIUM)], threshold=Severity.MEDIUM) is False

    def test_critical_threshold_only_blocks_critical(self) -> None:
        """critical 阈值下 high 不阻断。"""
        layer = _DummyLayer()
        assert layer.check_gate([_make_issue(Severity.HIGH)], threshold=Severity.CRITICAL) is True
        assert layer.check_gate([_make_issue(Severity.CRITICAL)], threshold=Severity.CRITICAL) is False


# ---------------------------------------------------------------------------
# 15.1d ConfigLoader 校验
# ---------------------------------------------------------------------------


class TestConfigLoaderValidation:
    """测试 :class:`ConfigLoader` 配置校验。"""

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        """文件不存在抛 AuditConfigError。"""
        with pytest.raises(AuditConfigError):
            ConfigLoader.load(tmp_path / "nonexistent.yaml")

    def test_valid_config_loads(self, config_path: Path) -> None:
        """合法配置成功加载。"""
        config = ConfigLoader.load(config_path)
        assert len(config.layers) == 12
        assert len(config.weights) == 12

    def test_weights_sum_to_one(self, config_path: Path) -> None:
        """权重之和 = 1.0。"""
        config = ConfigLoader.load(config_path)
        assert sum(config.weights.values()) == pytest.approx(1.0)

    def test_invalid_weights_sum_raises(self, tmp_path: Path, config_path: Path) -> None:
        """权重之和 ≠ 1.0 抛 AuditConfigError。"""
        config = ConfigLoader.load(config_path)
        bad_config = config.model_dump()
        bad_config["weights"]["L1"] = 0.5  # 破坏权重之和
        bad_path = tmp_path / "bad_config.yaml"
        bad_path.write_text(yaml.dump(bad_config, allow_unicode=True), encoding="utf-8")

        with pytest.raises(AuditConfigError):
            ConfigLoader.load(bad_path)

    def test_missing_layer_raises(self, tmp_path: Path, config_path: Path) -> None:
        """缺少层配置抛 AuditConfigError。"""
        config = ConfigLoader.load(config_path)
        bad_config = config.model_dump()
        bad_config["layers"] = bad_config["layers"][:11]  # 只保留 11 层
        bad_path = tmp_path / "bad_config.yaml"
        bad_path.write_text(yaml.dump(bad_config, allow_unicode=True), encoding="utf-8")

        with pytest.raises(AuditConfigError):
            ConfigLoader.load(bad_path)

    def test_rules_registry_loads(self, rules_path: Path) -> None:
        """规则注册表成功加载。"""
        rules = ConfigLoader.load_rules(rules_path)
        assert len(rules.rules) > 0

    def test_missing_rules_raises(self, tmp_path: Path) -> None:
        """规则文件不存在抛 AuditConfigError。"""
        with pytest.raises(AuditConfigError):
            ConfigLoader.load_rules(tmp_path / "nonexistent_rules.yaml")
