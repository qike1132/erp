"""Group 15.2 — 评分计算测试。

测试内容:
    - ProductionReadinessScore 各种问题组合下的计算
    - is_ready 阈值(≥85 且无 critical/high)
    - 惩罚值(critical=25 / high=15 / medium=1 / low=0 / info=0)
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from scripts.prod_audit.base.layer_base import (
    AuditIssue,
    LayerResult,
    LayerStatus,
    Severity,
)
from scripts.prod_audit.config_loader import AuditConfig, RulesRegistry
from scripts.prod_audit.evidence_archiver import EvidenceArchiver
from scripts.prod_audit.layers import LAYER_ORDER
from scripts.prod_audit.orchestrator import (
    AuditOrchestrator,
    ProductionReadinessScore,
)
from scripts.prod_audit.tests._helpers import make_issue

# ---------------------------------------------------------------------------
# 辅助:构建编排器并调用 _calculate_score
# ---------------------------------------------------------------------------


def _make_results_with_issues(
    config: AuditConfig,
    issues_by_layer: dict[str, list[AuditIssue]],
) -> dict[str, LayerResult]:
    """为 12 层构建 LayerResult,指定层携带问题。"""
    results: dict[str, LayerResult] = {}
    now = datetime.now(UTC)
    for layer_id in LAYER_ORDER:
        issues = issues_by_layer.get(layer_id, [])
        results[layer_id] = LayerResult(
            layer_id=layer_id,
            layer_name=config.get_layer(layer_id).layer_name,
            status=LayerStatus.PASSED,
            issues=issues,
            evidence_path=None,
            started_at=now,
            finished_at=now,
            weight=config.get_weight(layer_id),
        )
    return results


def _calculate_score(
    config: AuditConfig,
    archiver: EvidenceArchiver,
    issues_by_layer: dict[str, list[AuditIssue]],
) -> ProductionReadinessScore:
    """使用编排器._calculate_score 计算评分。"""
    rules = RulesRegistry(schema_version="1.0", rules=[])
    orchestrator = AuditOrchestrator(config, rules, archiver)
    results = _make_results_with_issues(config, issues_by_layer)
    return orchestrator._calculate_score(results, datetime.now(UTC))


# ---------------------------------------------------------------------------
# 15.2a 全绿评分
# ---------------------------------------------------------------------------


class TestScoreAllGreen:
    """全绿情况评分。"""

    def test_no_issues_score_100(
        self,
        audit_config: AuditConfig,
        archiver: EvidenceArchiver,
    ) -> None:
        """无问题时总分 = 100。"""
        score = _calculate_score(audit_config, archiver, {})
        assert score.total_score == pytest.approx(100.0)
        assert score.is_ready is True

    def test_all_layers_scored(
        self,
        audit_config: AuditConfig,
        archiver: EvidenceArchiver,
    ) -> None:
        """12 层均有得分条目。"""
        score = _calculate_score(audit_config, archiver, {})
        assert len(score.layer_scores) == 12
        assert len(score.weights) == 12
        for entry in score.layer_scores:
            assert entry.score == pytest.approx(100.0)


# ---------------------------------------------------------------------------
# 15.2b 惩罚值
# ---------------------------------------------------------------------------


class TestPenaltyValues:
    """各严重度惩罚值。"""

    def test_critical_penalty_25(
        self,
        audit_config: AuditConfig,
        archiver: EvidenceArchiver,
    ) -> None:
        """critical 扣 25 分。"""
        issue = make_issue(layer_id="L1", severity=Severity.CRITICAL)
        score = _calculate_score(audit_config, archiver, {"L1": [issue]})
        l1_entry = next(s for s in score.layer_scores if s.layer_id == "L1")
        assert l1_entry.score == pytest.approx(75.0)  # 100 - 25

    def test_high_penalty_15(
        self,
        audit_config: AuditConfig,
        archiver: EvidenceArchiver,
    ) -> None:
        """high 扣 15 分。"""
        issue = make_issue(layer_id="L1", severity=Severity.HIGH)
        score = _calculate_score(audit_config, archiver, {"L1": [issue]})
        l1_entry = next(s for s in score.layer_scores if s.layer_id == "L1")
        assert l1_entry.score == pytest.approx(85.0)  # 100 - 15

    def test_medium_penalty_1(
        self,
        audit_config: AuditConfig,
        archiver: EvidenceArchiver,
    ) -> None:
        """medium 扣 1 分。"""
        issue = make_issue(layer_id="L1", severity=Severity.MEDIUM)
        score = _calculate_score(audit_config, archiver, {"L1": [issue]})
        l1_entry = next(s for s in score.layer_scores if s.layer_id == "L1")
        assert l1_entry.score == pytest.approx(99.0)  # 100 - 1*1

    def test_low_penalty_0(
        self,
        audit_config: AuditConfig,
        archiver: EvidenceArchiver,
    ) -> None:
        """low 扣 0 分。"""
        issue = make_issue(layer_id="L1", severity=Severity.LOW)
        score = _calculate_score(audit_config, archiver, {"L1": [issue]})
        l1_entry = next(s for s in score.layer_scores if s.layer_id == "L1")
        assert l1_entry.score == pytest.approx(100.0)  # 100 - 0

    def test_info_penalty_0(
        self,
        audit_config: AuditConfig,
        archiver: EvidenceArchiver,
    ) -> None:
        """info 扣 0 分。"""
        issue = make_issue(layer_id="L1", severity=Severity.INFO)
        score = _calculate_score(audit_config, archiver, {"L1": [issue]})
        l1_entry = next(s for s in score.layer_scores if s.layer_id == "L1")
        assert l1_entry.score == pytest.approx(100.0)  # 100 - 0

    def test_multiple_issues_accumulate(
        self,
        audit_config: AuditConfig,
        archiver: EvidenceArchiver,
    ) -> None:
        """多个问题扣分累加。"""
        issues = [
            make_issue(layer_id="L1", severity=Severity.HIGH),
            make_issue(layer_id="L1", severity=Severity.MEDIUM),
            make_issue(layer_id="L1", severity=Severity.LOW),
        ]
        score = _calculate_score(audit_config, archiver, {"L1": issues})
        l1_entry = next(s for s in score.layer_scores if s.layer_id == "L1")
        # 100 - 15 - 1 - 0 = 84
        assert l1_entry.score == pytest.approx(84.0)

    def test_score_floor_at_zero(
        self,
        audit_config: AuditConfig,
        archiver: EvidenceArchiver,
    ) -> None:
        """层得分下限为 0。"""
        issues = [
            make_issue(layer_id="L1", severity=Severity.CRITICAL)
            for _ in range(10)
        ]
        score = _calculate_score(audit_config, archiver, {"L1": issues})
        l1_entry = next(s for s in score.layer_scores if s.layer_id == "L1")
        assert l1_entry.score == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# 15.2c is_ready 阈值
# ---------------------------------------------------------------------------


class TestIsReadyThreshold:
    """is_ready 阈值(≥85 且无 critical/high)。"""

    def test_score_above_threshold_no_blocking_is_ready(
        self,
        audit_config: AuditConfig,
        archiver: EvidenceArchiver,
    ) -> None:
        """评分 ≥ 85 且无阻断问题 → is_ready=True。"""
        issues = [
            make_issue(layer_id="L1", severity=Severity.LOW),
            make_issue(layer_id="L2", severity=Severity.LOW),
        ]
        score = _calculate_score(audit_config, archiver, {"L1": issues[:1], "L2": issues[1:]})
        assert score.total_score >= 85
        assert score.is_ready is True

    def test_critical_makes_not_ready(
        self,
        audit_config: AuditConfig,
        archiver: EvidenceArchiver,
    ) -> None:
        """有 critical → is_ready=False(即使评分 ≥ 85)。"""
        issue = make_issue(layer_id="L12", severity=Severity.CRITICAL)
        score = _calculate_score(audit_config, archiver, {"L12": [issue]})
        assert score.is_ready is False

    def test_high_makes_not_ready(
        self,
        audit_config: AuditConfig,
        archiver: EvidenceArchiver,
    ) -> None:
        """有 high → is_ready=False。"""
        issue = make_issue(layer_id="L12", severity=Severity.HIGH)
        score = _calculate_score(audit_config, archiver, {"L12": [issue]})
        assert score.is_ready is False

    def test_medium_does_not_block_readiness(
        self,
        audit_config: AuditConfig,
        archiver: EvidenceArchiver,
    ) -> None:
        """仅有 medium → is_ready 取决于评分。"""
        issue = make_issue(layer_id="L1", severity=Severity.MEDIUM)
        score = _calculate_score(audit_config, archiver, {"L1": [issue]})
        # 评分应 ≥ 85(仅扣 1 * 0.10 = 0.1)
        assert score.total_score >= 85
        assert score.is_ready is True

    def test_low_score_makes_not_ready(
        self,
        audit_config: AuditConfig,
        archiver: EvidenceArchiver,
    ) -> None:
        """评分 < 85 → is_ready=False。"""
        # 在所有层制造大量 medium 问题拉低评分(low/info 不扣分)
        issues_by_layer: dict[str, list[AuditIssue]] = {}
        for layer_id in LAYER_ORDER:
            issues_by_layer[layer_id] = [
                make_issue(layer_id=layer_id, severity=Severity.MEDIUM)
                for _ in range(50)
            ]
        score = _calculate_score(audit_config, archiver, issues_by_layer)
        assert score.total_score < 85
        assert score.is_ready is False


# ---------------------------------------------------------------------------
# 15.2d 评分模型校验
# ---------------------------------------------------------------------------


class TestScoreModelValidation:
    """ProductionReadinessScore 模型校验。"""

    def test_score_within_0_100(self, audit_config: AuditConfig, archiver: EvidenceArchiver) -> None:
        """总分在 0~100 之间。"""
        score = _calculate_score(audit_config, archiver, {})
        assert 0 <= score.total_score <= 100

    def test_weights_match_config(
        self,
        audit_config: AuditConfig,
        archiver: EvidenceArchiver,
    ) -> None:
        """权重条目与配置一致。"""
        score = _calculate_score(audit_config, archiver, {})
        for w_entry in score.weights:
            assert w_entry.weight == pytest.approx(audit_config.get_weight(w_entry.layer_id))

    def test_calculation_time_set(
        self,
        audit_config: AuditConfig,
        archiver: EvidenceArchiver,
    ) -> None:
        """calculation_time 已设置。"""
        score = _calculate_score(audit_config, archiver, {})
        assert score.calculation_time is not None

    def test_score_basis_not_empty(
        self,
        audit_config: AuditConfig,
        archiver: EvidenceArchiver,
    ) -> None:
        """score_basis 非空。"""
        score = _calculate_score(audit_config, archiver, {})
        assert len(score.score_basis) > 0
