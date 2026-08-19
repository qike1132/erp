"""Group 14.2 / 14.3 / 14.4 — 编排器集成测试。

测试内容:
    - 14.2 编排器顺序加载 12 层 / 门禁阻断 / 层禁用跳过
    - 14.3 断点恢复 save_state/load_state / resume_from 跳过已完成层
    - 14.4 CLI 入口 / 退出码
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.prod_audit.base.issue_builder import IssueBuilder
from scripts.prod_audit.base.layer_base import (
    AuditState,
    LayerResult,
    LayerStatus,
    Severity,
)
from scripts.prod_audit.config_loader import AuditConfig, RulesRegistry
from scripts.prod_audit.evidence_archiver import EvidenceArchiver
from scripts.prod_audit.exceptions import (
    AuditConfigError,
    AuditLayerBlockedError,
)
from scripts.prod_audit.layers import LAYER_ORDER
from scripts.prod_audit.orchestrator import (
    AuditDiff,
    AuditOrchestrator,
    AuditRunResult,
    LayerScoreEntry,
    LayerSignOffEntry,
    ProductionReadinessScore,
    ReleaseSignOff,
    main,
)
from scripts.prod_audit.tests._helpers import (
    MockLayerExecutor,
    make_issue,
    make_layer_result,
)

# ---------------------------------------------------------------------------
# 辅助:注入 mock 执行器
# ---------------------------------------------------------------------------


def _inject_executors(
    orchestrator: AuditOrchestrator,
    executors: dict[str, MockLayerExecutor],
) -> None:
    """将 mock 执行器注入编排器缓存。"""
    orchestrator._executors = dict(executors)


def _build_audit_run_result(audit_config: AuditConfig) -> AuditRunResult:
    """构造一个全绿的 :class:`AuditRunResult` 用于 CLI 测试。"""
    now = datetime.now(UTC)
    layer_results = [
        make_layer_result(
            layer_id=lid,
            layer_name=audit_config.get_layer(lid).layer_name,
            weight=audit_config.get_weight(lid),
        )
        for lid in LAYER_ORDER
    ]
    layer_scores = [
        LayerScoreEntry(layer_id=lid, score=100.0, basis="all clean")
        for lid in LAYER_ORDER
    ]
    weights = [
        type("W", (), {"layer_id": lid, "weight": audit_config.get_weight(lid)})()
        for lid in LAYER_ORDER
    ]
    from scripts.prod_audit.orchestrator import WeightEntry

    weights = [
        WeightEntry(layer_id=lid, weight=audit_config.get_weight(lid))
        for lid in LAYER_ORDER
    ]
    score = ProductionReadinessScore(
        total_score=100.0,
        layer_scores=layer_scores,
        weights=weights,
        calculation_time=now,
        is_ready=True,
        score_basis="all layers clean",
    )
    from scripts.prod_audit.base.layer_base import ReleaseDecision

    signoffs = [
        LayerSignOffEntry(
            layer_id=lid,
            reviewer=audit_config.get_layer(lid).reviewer,
            signed_at=now,
            result="approved",
        )
        for lid in LAYER_ORDER
    ]
    signoff = ReleaseSignOff(
        signoff_id="signoff-test",
        audit_run_id="audit-test",
        layer_signoffs=signoffs,
        release_manager=audit_config.get_layer("L12").reviewer,
        release_decision=ReleaseDecision.APPROVED,
        decision_reason="all passed",
        signed_at=now,
        conditions=["All 12 layers passed gate check."],
    )
    diff = AuditDiff()
    return AuditRunResult(
        audit_run_id="audit-test",
        layer_results=layer_results,
        score=score,
        signoff=signoff,
        diff=diff,
        started_at=now,
        finished_at=now,
    )


# ---------------------------------------------------------------------------
# 14.2 编排器顺序执行
# ---------------------------------------------------------------------------


class TestOrchestratorSequentialExecution:
    """14.2 验证编排器 12 层顺序串联。"""

    async def test_loads_all_12_layers_in_order(
        self,
        audit_config: AuditConfig,
        rules_registry: RulesRegistry,
        archiver: EvidenceArchiver,
        mock_executors_factory,
    ) -> None:
        """编排器按 L1~L12 顺序执行 12 层。"""
        executors = mock_executors_factory()
        orchestrator = AuditOrchestrator(audit_config, rules_registry, archiver)
        _inject_executors(orchestrator, executors)

        result = await orchestrator.run()

        assert isinstance(result, AuditRunResult)
        assert len(result.layer_results) == 12
        for idx, layer_id in enumerate(LAYER_ORDER):
            assert result.layer_results[idx].layer_id == layer_id
        for layer_id in LAYER_ORDER:
            assert executors[layer_id].run_call_count == 1

    async def test_all_layers_passed(
        self,
        audit_config: AuditConfig,
        rules_registry: RulesRegistry,
        archiver: EvidenceArchiver,
        mock_executors_factory,
    ) -> None:
        """全绿时所有层状态为 PASSED。"""
        executors = mock_executors_factory()
        orchestrator = AuditOrchestrator(audit_config, rules_registry, archiver)
        _inject_executors(orchestrator, executors)

        result = await orchestrator.run()

        for lr in result.layer_results:
            assert lr.status == LayerStatus.PASSED

    async def test_layer_skip_when_disabled(
        self,
        audit_config: AuditConfig,
        rules_registry: RulesRegistry,
        archiver: EvidenceArchiver,
        mock_executors_factory,
    ) -> None:
        """enabled=false 的层标记 SKIPPED 且不执行。"""
        config = audit_config.model_copy(deep=True)
        l6_cfg = config.get_layer("L6")
        l6_cfg.enabled = False
        l6_cfg.disable_reason = "测试禁用"

        executors = mock_executors_factory()
        orchestrator = AuditOrchestrator(config, rules_registry, archiver)
        _inject_executors(orchestrator, executors)

        result = await orchestrator.run()

        l6_result = next(lr for lr in result.layer_results if lr.layer_id == "L6")
        assert l6_result.status == LayerStatus.SKIPPED
        assert executors["L6"].run_call_count == 0
        assert executors["L1"].run_call_count == 1
        assert executors["L12"].run_call_count == 1


# ---------------------------------------------------------------------------
# 14.2 门禁阻断
# ---------------------------------------------------------------------------


class TestGateBlocking:
    """14.2 验证门禁递进阻断。"""

    async def test_critical_issue_blocks_pipeline(
        self,
        audit_config: AuditConfig,
        rules_registry: RulesRegistry,
        archiver: EvidenceArchiver,
        mock_executors_factory,
    ) -> None:
        """L3 发现 critical 问题时抛 AuditLayerBlockedError 且 L4~L12 未执行。"""
        builder = IssueBuilder()
        critical_issue = make_issue(
            layer_id="L3",
            severity=Severity.CRITICAL,
            description="critical 测试问题",
            builder=builder,
        )

        executors = mock_executors_factory(
            issues_per_layer={"L3": [critical_issue]},
        )
        orchestrator = AuditOrchestrator(audit_config, rules_registry, archiver)
        _inject_executors(orchestrator, executors)

        with pytest.raises(AuditLayerBlockedError) as exc_info:
            await orchestrator.run()

        assert exc_info.value.layer_id == "L3"
        assert executors["L1"].run_call_count == 1
        assert executors["L2"].run_call_count == 1
        assert executors["L3"].run_call_count == 1
        for layer_id in ("L4", "L5", "L6", "L7", "L8", "L9", "L10", "L11", "L12"):
            assert executors[layer_id].run_call_count == 0, (
                f"{layer_id} should not have been executed"
            )

    async def test_high_issue_blocks_pipeline(
        self,
        audit_config: AuditConfig,
        rules_registry: RulesRegistry,
        archiver: EvidenceArchiver,
        mock_executors_factory,
    ) -> None:
        """high 问题也阻断(severity_threshold=high)。"""
        builder = IssueBuilder()
        high_issue = make_issue(
            layer_id="L2",
            severity=Severity.HIGH,
            builder=builder,
        )

        executors = mock_executors_factory(
            issues_per_layer={"L2": [high_issue]},
        )
        orchestrator = AuditOrchestrator(audit_config, rules_registry, archiver)
        _inject_executors(orchestrator, executors)

        with pytest.raises(AuditLayerBlockedError):
            await orchestrator.run()

        assert executors["L3"].run_call_count == 0

    async def test_medium_issue_does_not_block(
        self,
        audit_config: AuditConfig,
        rules_registry: RulesRegistry,
        archiver: EvidenceArchiver,
        mock_executors_factory,
    ) -> None:
        """medium 问题不阻断(threshold=high)。"""
        builder = IssueBuilder()
        medium_issue = make_issue(
            layer_id="L3",
            severity=Severity.MEDIUM,
            builder=builder,
        )

        executors = mock_executors_factory(
            issues_per_layer={"L3": [medium_issue]},
        )
        orchestrator = AuditOrchestrator(audit_config, rules_registry, archiver)
        _inject_executors(orchestrator, executors)

        result = await orchestrator.run()

        for layer_id in LAYER_ORDER:
            assert executors[layer_id].run_call_count == 1
        assert isinstance(result, AuditRunResult)


# ---------------------------------------------------------------------------
# 14.3 断点恢复
# ---------------------------------------------------------------------------


class TestBreakpointRecovery:
    """14.3 验证断点恢复。"""

    async def test_save_load_state_round_trip(
        self,
        archiver: EvidenceArchiver,
    ) -> None:
        """save_state / load_state 往返一致。"""
        now = datetime.now(UTC)
        result = make_layer_result(layer_id="L1", layer_name="测试层")
        state = AuditState(
            audit_run_id="audit-test123",
            current_layer="L1",
            layer_states={"L1": result},
            started_at=now,
            last_updated=now,
        )

        await archiver.save_state(state)
        loaded = await archiver.load_state()

        assert loaded is not None
        assert loaded.audit_run_id == "audit-test123"
        assert loaded.current_layer == "L1"
        assert "L1" in loaded.layer_states
        assert loaded.layer_states["L1"].layer_id == "L1"

    async def test_load_state_returns_none_when_no_file(
        self,
        archiver: EvidenceArchiver,
    ) -> None:
        """无状态文件时 load_state 返回 None。"""
        loaded = await archiver.load_state()
        assert loaded is None

    async def test_resume_from_skips_completed_layers(
        self,
        audit_config: AuditConfig,
        rules_registry: RulesRegistry,
        archiver: EvidenceArchiver,
        mock_executors_factory,
    ) -> None:
        """resume_from=L4 且有前序状态时 L1~L3 不重复执行。"""
        # 预填充 L1~L3 的状态
        now = datetime.now(UTC)
        pre_results: dict[str, LayerResult] = {}
        for lid in ("L1", "L2", "L3"):
            pre_results[lid] = make_layer_result(
                layer_id=lid,
                layer_name=audit_config.get_layer(lid).layer_name,
                weight=audit_config.get_weight(lid),
            )
        state = AuditState(
            audit_run_id="audit-resume-test",
            current_layer="L4",
            layer_states=pre_results,
            started_at=now,
            last_updated=now,
        )
        await archiver.save_state(state)

        executors = mock_executors_factory()
        orchestrator = AuditOrchestrator(audit_config, rules_registry, archiver)
        _inject_executors(orchestrator, executors)

        result = await orchestrator.run(resume_from="L4")

        for layer_id in ("L1", "L2", "L3"):
            assert executors[layer_id].run_call_count == 0, (
                f"{layer_id} should be skipped on resume"
            )
        for layer_id in ("L4", "L5", "L6", "L7", "L8", "L9", "L10", "L11", "L12"):
            assert executors[layer_id].run_call_count == 1
        assert isinstance(result, AuditRunResult)

    async def test_resume_from_invalid_layer_raises(
        self,
        audit_config: AuditConfig,
        rules_registry: RulesRegistry,
        archiver: EvidenceArchiver,
    ) -> None:
        """resume_from 为非法层 ID 时抛 AuditConfigError。"""
        orchestrator = AuditOrchestrator(audit_config, rules_registry, archiver)
        with pytest.raises(AuditConfigError):
            await orchestrator.run(resume_from="L99")

    async def test_state_persisted_after_each_layer(
        self,
        audit_config: AuditConfig,
        rules_registry: RulesRegistry,
        archiver: EvidenceArchiver,
        mock_executors_factory,
    ) -> None:
        """运行完成后状态文件被清理。"""
        executors = mock_executors_factory()
        orchestrator = AuditOrchestrator(audit_config, rules_registry, archiver)
        _inject_executors(orchestrator, executors)

        await orchestrator.run()

        state = await archiver.load_state()
        assert state is None


# ---------------------------------------------------------------------------
# 14.4 CLI 入口
# ---------------------------------------------------------------------------


class TestCLIEntryPoint:
    """14.4 验证 CLI 入口与退出码。"""

    def test_help_flag_works(self) -> None:
        """--help 不报错(argparse 自动处理)。"""
        with pytest.raises(SystemExit) as exc_info:
            main(["--help"])
        assert exc_info.value.code == 0

    def test_config_error_returns_exit_code_2(self, tmp_path: Path) -> None:
        """配置文件不存在时返回退出码 2。"""
        fake_config = tmp_path / "nonexistent.yaml"
        exit_code = main([
            "--config", str(fake_config),
            "--rules", str(fake_config),
        ])
        assert exit_code == 2

    def test_successful_run_returns_exit_code_0(
        self,
        audit_config: AuditConfig,
        rules_registry: RulesRegistry,
        config_path: Path,
        rules_path: Path,
        evidence_dir: Path,
    ) -> None:
        """正常完成返回退出码 0。"""
        mock_result = _build_audit_run_result(audit_config)

        async def mock_run(self, *args, **kwargs):
            return mock_result

        with patch.object(AuditOrchestrator, "run", mock_run):
            exit_code = main([
                "--config", str(config_path),
                "--rules", str(rules_path),
                "--evidence-dir", str(evidence_dir),
            ])
        assert exit_code == 0

    def test_blocked_returns_exit_code_1(
        self,
        audit_config: AuditConfig,
        rules_registry: RulesRegistry,
        config_path: Path,
        rules_path: Path,
        evidence_dir: Path,
    ) -> None:
        """门禁阻断返回退出码 1。"""

        async def mock_run(self, *args, **kwargs):
            raise AuditLayerBlockedError("L3", "test blocking")

        with patch.object(AuditOrchestrator, "run", mock_run):
            exit_code = main([
                "--config", str(config_path),
                "--rules", str(rules_path),
                "--evidence-dir", str(evidence_dir),
            ])
        assert exit_code == 1

    def test_config_validation_error_returns_exit_code_2(
        self,
        config_path: Path,
        rules_path: Path,
        evidence_dir: Path,
    ) -> None:
        """配置校验错误返回退出码 2。"""
        with patch(
            "scripts.prod_audit.orchestrator.ConfigLoader.load",
            side_effect=AuditConfigError("test error"),
        ):
            exit_code = main([
                "--config", str(config_path),
                "--rules", str(rules_path),
                "--evidence-dir", str(evidence_dir),
            ])
        assert exit_code == 2
