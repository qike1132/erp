"""Group 15.5 — 上线决策测试。

测试内容:
    - 签字单生成(通过审核)
    - 签字单生成(失败审核)
    - 上线放行条件检查
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from scripts.prod_audit.base.issue_builder import IssueBuilder
from scripts.prod_audit.base.layer_base import (
    AuditIssue,
    LayerResult,
    LayerStatus,
    ReleaseDecision,
    Severity,
)
from scripts.prod_audit.config_loader import AuditConfig, RulesRegistry
from scripts.prod_audit.evidence_archiver import EvidenceArchiver
from scripts.prod_audit.exceptions import AuditLayerBlockedError
from scripts.prod_audit.layers import LAYER_ORDER
from scripts.prod_audit.orchestrator import (
    AuditOrchestrator,
    ProductionReadinessScore,
)
from scripts.prod_audit.tests._helpers import make_issue

# ---------------------------------------------------------------------------
# 辅助:构建编排器并调用 _generate_signoff
# ---------------------------------------------------------------------------


def _build_orchestrator(
    config: AuditConfig,
    archiver: EvidenceArchiver,
) -> AuditOrchestrator:
    rules = RulesRegistry(schema_version="1.0", rules=[])
    return AuditOrchestrator(config, rules, archiver)


def _make_results(
    config: AuditConfig,
    issues_by_layer: dict[str, list[AuditIssue]] | None = None,
    statuses: dict[str, LayerStatus] | None = None,
) -> dict[str, LayerResult]:
    """构建 12 层 LayerResult。"""
    issues_by_layer = issues_by_layer or {}
    statuses = statuses or {}
    now = datetime.now(UTC)
    results: dict[str, LayerResult] = {}
    for lid in LAYER_ORDER:
        results[lid] = LayerResult(
            layer_id=lid,
            layer_name=config.get_layer(lid).layer_name,
            status=statuses.get(lid, LayerStatus.PASSED),
            issues=issues_by_layer.get(lid, []),
            evidence_path=None,
            started_at=now,
            finished_at=now,
            weight=config.get_weight(lid),
        )
    return results


def _make_score(
    config: AuditConfig,
    total: float = 100.0,
    is_ready: bool = True,
) -> ProductionReadinessScore:
    from scripts.prod_audit.orchestrator import LayerScoreEntry, WeightEntry

    now = datetime.now(UTC)
    return ProductionReadinessScore(
        total_score=total,
        layer_scores=[
            LayerScoreEntry(layer_id=lid, score=100.0, basis="ok")
            for lid in LAYER_ORDER
        ],
        weights=[
            WeightEntry(layer_id=lid, weight=config.get_weight(lid))
            for lid in LAYER_ORDER
        ],
        calculation_time=now,
        is_ready=is_ready,
        score_basis="test",
    )


# ---------------------------------------------------------------------------
# 15.5a 签字单生成 — 通过审核
# ---------------------------------------------------------------------------


class TestSignOffPassing:
    """通过审核的签字单。"""

    def test_approved_when_all_pass(
        self,
        audit_config: AuditConfig,
        archiver: EvidenceArchiver,
    ) -> None:
        """全绿时 release_decision=approved。"""
        orchestrator = _build_orchestrator(audit_config, archiver)
        results = _make_results(audit_config)
        score = _make_score(audit_config, total=95.0, is_ready=True)

        signoff = orchestrator._generate_signoff("run-1", results, score)

        assert signoff.release_decision == ReleaseDecision.APPROVED
        assert signoff.signed_at is not None
        assert len(signoff.layer_signoffs) == 12

    def test_all_layer_signoffs_approved(
        self,
        audit_config: AuditConfig,
        archiver: EvidenceArchiver,
    ) -> None:
        """全绿时各层签字结果为 approved。"""
        orchestrator = _build_orchestrator(audit_config, archiver)
        results = _make_results(audit_config)
        score = _make_score(audit_config, total=100.0, is_ready=True)

        signoff = orchestrator._generate_signoff("run-1", results, score)

        for entry in signoff.layer_signoffs:
            assert entry.result == "approved"

    def test_signoff_has_reviewer(
        self,
        audit_config: AuditConfig,
        archiver: EvidenceArchiver,
    ) -> None:
        """各层签字含审核员。"""
        orchestrator = _build_orchestrator(audit_config, archiver)
        results = _make_results(audit_config)
        score = _make_score(audit_config, is_ready=True)

        signoff = orchestrator._generate_signoff("run-1", results, score)

        for entry in signoff.layer_signoffs:
            assert len(entry.reviewer) > 0

    def test_signoff_has_valid_id(
        self,
        audit_config: AuditConfig,
        archiver: EvidenceArchiver,
    ) -> None:
        """签字单含唯一 ID。"""
        orchestrator = _build_orchestrator(audit_config, archiver)
        results = _make_results(audit_config)
        score = _make_score(audit_config, is_ready=True)

        signoff = orchestrator._generate_signoff("run-1", results, score)

        assert signoff.signoff_id.startswith("signoff-")
        assert signoff.audit_run_id == "run-1"

    def test_conditions_when_ready(
        self,
        audit_config: AuditConfig,
        archiver: EvidenceArchiver,
    ) -> None:
        """就绪时 conditions 含全绿说明。"""
        orchestrator = _build_orchestrator(audit_config, archiver)
        results = _make_results(audit_config)
        score = _make_score(audit_config, is_ready=True)

        signoff = orchestrator._generate_signoff("run-1", results, score)

        assert len(signoff.conditions) > 0
        assert any("passed" in c.lower() for c in signoff.conditions)


# ---------------------------------------------------------------------------
# 15.5b 签字单生成 — 失败审核
# ---------------------------------------------------------------------------


class TestSignOffFailing:
    """失败审核的签字单。"""

    def test_rejected_when_score_below_threshold(
        self,
        audit_config: AuditConfig,
        archiver: EvidenceArchiver,
    ) -> None:
        """评分 < 85 时 release_decision=rejected。"""
        orchestrator = _build_orchestrator(audit_config, archiver)
        results = _make_results(audit_config)
        score = _make_score(audit_config, total=70.0, is_ready=False)

        signoff = orchestrator._generate_signoff("run-1", results, score)

        assert signoff.release_decision == ReleaseDecision.REJECTED
        assert signoff.signed_at is None

    def test_rejected_when_blocking_issues(
        self,
        audit_config: AuditConfig,
        archiver: EvidenceArchiver,
    ) -> None:
        """有阻断问题时 release_decision=rejected。"""
        orchestrator = _build_orchestrator(audit_config, archiver)
        results = _make_results(audit_config)
        score = _make_score(audit_config, total=90.0, is_ready=False)

        signoff = orchestrator._generate_signoff("run-1", results, score)

        assert signoff.release_decision == ReleaseDecision.REJECTED

    def test_conditions_list_unmet(
        self,
        audit_config: AuditConfig,
        archiver: EvidenceArchiver,
    ) -> None:
        """未就绪时 conditions 列出未达标项。"""
        from scripts.prod_audit.orchestrator import LayerScoreEntry, WeightEntry

        now = datetime.now(UTC)
        orchestrator = _build_orchestrator(audit_config, archiver)
        results = _make_results(audit_config)
        # 构造含低分层的 score(使 conditions 非空)
        layer_scores = [
            LayerScoreEntry(layer_id=lid, score=50.0 if lid == "L1" else 100.0, basis="L1 has issues")
            for lid in LAYER_ORDER
        ]
        weights = [
            WeightEntry(layer_id=lid, weight=audit_config.get_weight(lid))
            for lid in LAYER_ORDER
        ]
        score = ProductionReadinessScore(
            total_score=70.0,
            layer_scores=layer_scores,
            weights=weights,
            calculation_time=now,
            is_ready=False,
            score_basis="test",
        )

        signoff = orchestrator._generate_signoff("run-1", results, score)

        assert len(signoff.conditions) > 0

    def test_decision_reason_describes_failure(
        self,
        audit_config: AuditConfig,
        archiver: EvidenceArchiver,
    ) -> None:
        """决策理由描述失败原因。"""
        orchestrator = _build_orchestrator(audit_config, archiver)
        results = _make_results(audit_config)
        score = _make_score(audit_config, total=70.0, is_ready=False)

        signoff = orchestrator._generate_signoff("run-1", results, score)

        assert len(signoff.decision_reason) > 0
        assert "not ready" in signoff.decision_reason.lower()

    def test_failed_layer_signoff_rejected(
        self,
        audit_config: AuditConfig,
        archiver: EvidenceArchiver,
    ) -> None:
        """FAILED 层签字结果为 rejected。"""
        orchestrator = _build_orchestrator(audit_config, archiver)
        results = _make_results(
            audit_config,
            statuses={"L3": LayerStatus.FAILED},
        )
        score = _make_score(audit_config, is_ready=False)

        signoff = orchestrator._generate_signoff("run-1", results, score)

        l3_entry = next(e for e in signoff.layer_signoffs if e.layer_id == "L3")
        assert l3_entry.result == "rejected"

    def test_skipped_layer_signoff_conditional(
        self,
        audit_config: AuditConfig,
        archiver: EvidenceArchiver,
    ) -> None:
        """SKIPPED 层签字结果为 conditional。"""
        orchestrator = _build_orchestrator(audit_config, archiver)
        results = _make_results(
            audit_config,
            statuses={"L6": LayerStatus.SKIPPED},
        )
        score = _make_score(audit_config, is_ready=True)

        signoff = orchestrator._generate_signoff("run-1", results, score)

        l6_entry = next(e for e in signoff.layer_signoffs if e.layer_id == "L6")
        assert l6_entry.result == "conditional"


# ---------------------------------------------------------------------------
# 15.5c 上线放行条件
# ---------------------------------------------------------------------------


class TestLaunchApprovalConditions:
    """上线放行条件检查。"""

    async def test_all_conditions_met_approves(
        self,
        audit_config: AuditConfig,
        rules_registry: RulesRegistry,
        archiver: EvidenceArchiver,
        mock_executors_factory,
    ) -> None:
        """全条件满足 → approved。"""
        executors = mock_executors_factory()
        orchestrator = AuditOrchestrator(audit_config, rules_registry, archiver)
        orchestrator._executors = dict(executors)

        result = await orchestrator.run()

        assert result.score.is_ready is True
        assert result.score.total_score >= 85
        assert result.signoff.release_decision == ReleaseDecision.APPROVED

    async def test_blocking_issue_rejects(
        self,
        audit_config: AuditConfig,
        rules_registry: RulesRegistry,
        archiver: EvidenceArchiver,
        mock_executors_factory,
    ) -> None:
        """有阻断问题 → rejected(抛异常)。"""
        builder = IssueBuilder()
        critical = make_issue(
            layer_id="L3",
            severity=Severity.CRITICAL,
            builder=builder,
        )
        executors = mock_executors_factory(issues_per_layer={"L3": [critical]})
        orchestrator = AuditOrchestrator(audit_config, rules_registry, archiver)
        orchestrator._executors = dict(executors)

        with pytest.raises(AuditLayerBlockedError):
            await orchestrator.run()

    async def test_score_below_threshold_rejects(
        self,
        audit_config: AuditConfig,
        rules_registry: RulesRegistry,
        archiver: EvidenceArchiver,
        mock_executors_factory,
    ) -> None:
        """评分 < 85 → rejected(不抛异常,但 is_ready=False)。"""
        # 在所有层制造大量 medium 问题拉低评分(low penalty=0 不扣分,medium penalty=1)
        builder = IssueBuilder()
        issues_by_layer: dict[str, list[AuditIssue]] = {}
        for lid in LAYER_ORDER:
            issues_by_layer[lid] = [
                make_issue(layer_id=lid, severity=Severity.MEDIUM, builder=builder)
                for _ in range(50)
            ]
        executors = mock_executors_factory(issues_per_layer=issues_by_layer)
        orchestrator = AuditOrchestrator(audit_config, rules_registry, archiver)
        orchestrator._executors = dict(executors)

        result = await orchestrator.run()

        assert result.score.total_score < 85
        assert result.score.is_ready is False
        assert result.signoff.release_decision == ReleaseDecision.REJECTED

    async def test_evidence_archived_on_success(
        self,
        audit_config: AuditConfig,
        rules_registry: RulesRegistry,
        archiver: EvidenceArchiver,
        evidence_dir: Path,
        mock_executors_factory,
    ) -> None:
        """成功时门禁日志归档至 evidence/gate_logs/。"""
        executors = mock_executors_factory()
        orchestrator = AuditOrchestrator(audit_config, rules_registry, archiver)
        orchestrator._executors = dict(executors)

        await orchestrator.run()

        gate_logs_dir = evidence_dir / "gate_logs"
        assert gate_logs_dir.exists()
        log_files = list(gate_logs_dir.glob("*_gate.log"))
        assert len(log_files) == 12
