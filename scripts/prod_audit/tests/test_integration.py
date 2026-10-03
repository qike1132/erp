"""Group 15.4 — 集成测试(dry run)。

测试内容:
    - L1 层隔离运行(mock subprocess + mock 归档)
    - L12 层配合 mock 层结果运行(mock 归档)
    - 全 pipeline 所有层 mock
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from scripts.prod_audit.base.issue_builder import IssueBuilder
from scripts.prod_audit.base.layer_base import (
    LayerResult,
    LayerStatus,
    Severity,
)
from scripts.prod_audit.config_loader import AuditConfig, RulesRegistry
from scripts.prod_audit.evidence_archiver import EvidenceArchiver
from scripts.prod_audit.exceptions import AuditLayerBlockedError
from scripts.prod_audit.layers import LAYER_ORDER
from scripts.prod_audit.layers.l1_static import L1StaticAnalysis
from scripts.prod_audit.layers.l12_report import L12Report
from scripts.prod_audit.orchestrator import (
    AuditOrchestrator,
    AuditRunResult,
)
from scripts.prod_audit.tests._helpers import (
    make_issue,
    make_layer_result,
)

# ---------------------------------------------------------------------------
# 15.4a L1 隔离运行(mock subprocess + mock 归档)
# ---------------------------------------------------------------------------


class TestL1Isolation:
    """L1 层隔离运行。"""

    async def test_l1_runs_with_mocked_subprocess(
        self,
        audit_config: AuditConfig,
        rules_registry: RulesRegistry,
        archiver: EvidenceArchiver,
        audit_context_factory,
    ) -> None:
        """L1 在 mock subprocess 下运行并返回 LayerResult。"""
        mock_proc = MagicMock()
        mock_proc.stdout = ""
        mock_proc.stderr = ""
        mock_proc.returncode = 0

        context = audit_context_factory()
        executor = L1StaticAnalysis()

        with patch("asyncio.to_thread", new_callable=AsyncMock, return_value=mock_proc), \
             patch.object(L1StaticAnalysis, "_archive_evidence", new_callable=AsyncMock, return_value="mock_path"):
            result = await executor.run(context)

        assert isinstance(result, LayerResult)
        assert result.layer_id == "L1"
        assert result.layer_name == "静态分析门禁审核"
        assert result.started_at is not None
        assert result.finished_at is not None

    async def test_l1_collects_issues_from_ruff_output(
        self,
        audit_config: AuditConfig,
        rules_registry: RulesRegistry,
        archiver: EvidenceArchiver,
        audit_context_factory,
    ) -> None:
        """L1 解析 ruff 输出并生成 issue。"""
        ruff_output = (
            "fastapi_app/foo.py:42:5: E501 Line too long (130 > 120)\n"
            "fastapi_app/bar.py:10:1: F401 Unused import\n"
        )
        mock_proc = MagicMock()
        mock_proc.stdout = ruff_output
        mock_proc.stderr = ""
        mock_proc.returncode = 1

        context = audit_context_factory()
        executor = L1StaticAnalysis()

        empty_proc = MagicMock()
        empty_proc.stdout = ""
        empty_proc.stderr = ""
        empty_proc.returncode = 0

        call_count = 0

        async def mock_to_thread(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return mock_proc
            return empty_proc

        with patch("asyncio.to_thread", side_effect=mock_to_thread), \
             patch.object(L1StaticAnalysis, "_archive_evidence", new_callable=AsyncMock, return_value="mock_path"):
            result = await executor.run(context)

        assert isinstance(result, LayerResult)
        assert result.layer_id == "L1"
        # 真断言（2026-10-03 第六轮审计）：此前只断言 layer_id —— 造了 2 行 ruff 输出
        # 却从不检查是否真的解析成 issue，属空洞测试。这里校验两行都被解析出来。
        found = {(i.file, i.line) for i in result.issues}
        assert ("fastapi_app/foo.py", 42) in found, result.issues
        assert ("fastapi_app/bar.py", 10) in found, result.issues


# ---------------------------------------------------------------------------
# 15.4b L12 配合 mock 层结果运行
# ---------------------------------------------------------------------------


class TestL12WithMockResults:
    """L12 层配合 mock 层结果。"""

    async def test_l12_aggregates_11_layer_results(
        self,
        audit_config: AuditConfig,
        rules_registry: RulesRegistry,
        archiver: EvidenceArchiver,
        audit_context_factory,
    ) -> None:
        """L12 聚合前 11 层结果并生成报告。"""
        previous_results = [
            make_layer_result(
                layer_id=lid,
                layer_name=audit_config.get_layer(lid).layer_name,
                weight=audit_config.get_weight(lid),
            )
            for lid in LAYER_ORDER[:11]
        ]
        context = audit_context_factory(previous_results=previous_results)
        executor = L12Report()

        with patch.object(L12Report, "_archive_evidence", new_callable=AsyncMock, return_value="mock_path"):
            result = await executor.run(context)

        assert isinstance(result, LayerResult)
        assert result.layer_id == "L12"
        assert result.layer_name == "报告与上线决策"

    async def test_l12_with_blocking_issues(
        self,
        audit_config: AuditConfig,
        rules_registry: RulesRegistry,
        archiver: EvidenceArchiver,
        audit_context_factory,
    ) -> None:
        """L12 输入含 critical 问题时状态为 BLOCKED。"""
        builder = IssueBuilder()
        critical_issue = make_issue(
            layer_id="L3",
            severity=Severity.CRITICAL,
            builder=builder,
        )
        previous_results = [
            make_layer_result(
                layer_id=lid,
                layer_name=audit_config.get_layer(lid).layer_name,
                weight=audit_config.get_weight(lid),
                issues=[critical_issue] if lid == "L3" else [],
            )
            for lid in LAYER_ORDER[:11]
        ]
        context = audit_context_factory(previous_results=previous_results)
        executor = L12Report()

        with patch.object(L12Report, "_archive_evidence", new_callable=AsyncMock, return_value="mock_path"):
            result = await executor.run(context)

        assert isinstance(result, LayerResult)
        assert result.status == LayerStatus.BLOCKED


# ---------------------------------------------------------------------------
# 15.4c 全 pipeline mock
# ---------------------------------------------------------------------------


class TestFullPipelineMocked:
    """全 pipeline 所有层 mock。"""

    async def test_full_pipeline_all_green(
        self,
        audit_config: AuditConfig,
        rules_registry: RulesRegistry,
        archiver: EvidenceArchiver,
        mock_executors_factory,
    ) -> None:
        """全绿 pipeline 返回 AuditRunResult。"""
        executors = mock_executors_factory()
        orchestrator = AuditOrchestrator(audit_config, rules_registry, archiver)
        orchestrator._executors = dict(executors)

        result = await orchestrator.run()

        assert isinstance(result, AuditRunResult)
        assert len(result.layer_results) == 12
        assert result.score.total_score == pytest.approx(100.0)
        assert result.score.is_ready is True

    async def test_full_pipeline_with_medium_issues(
        self,
        audit_config: AuditConfig,
        rules_registry: RulesRegistry,
        archiver: EvidenceArchiver,
        mock_executors_factory,
    ) -> None:
        """medium 问题不阻断 pipeline。"""
        builder = IssueBuilder()
        issues = {
            "L1": [make_issue(layer_id="L1", severity=Severity.MEDIUM, builder=builder)],
            "L3": [make_issue(layer_id="L3", severity=Severity.LOW, builder=builder)],
        }
        executors = mock_executors_factory(issues_per_layer=issues)
        orchestrator = AuditOrchestrator(audit_config, rules_registry, archiver)
        orchestrator._executors = dict(executors)

        result = await orchestrator.run()

        assert isinstance(result, AuditRunResult)
        assert result.score.total_score < 100.0
        assert result.score.is_ready is True

    async def test_full_pipeline_blocked_at_l3(
        self,
        audit_config: AuditConfig,
        rules_registry: RulesRegistry,
        archiver: EvidenceArchiver,
        mock_executors_factory,
    ) -> None:
        """L3 critical 阻断 pipeline。"""
        builder = IssueBuilder()
        critical = make_issue(
            layer_id="L3",
            severity=Severity.CRITICAL,
            builder=builder,
        )
        executors = mock_executors_factory(issues_per_layer={"L3": [critical]})
        orchestrator = AuditOrchestrator(audit_config, rules_registry, archiver)
        orchestrator._executors = dict(executors)

        with pytest.raises(AuditLayerBlockedError) as exc_info:
            await orchestrator.run()

        assert exc_info.value.layer_id == "L3"

    async def test_full_pipeline_with_disabled_layer(
        self,
        audit_config: AuditConfig,
        rules_registry: RulesRegistry,
        archiver: EvidenceArchiver,
        mock_executors_factory,
    ) -> None:
        """禁用 L6 时 pipeline 跳过 L6。"""
        config = audit_config.model_copy(deep=True)
        config.get_layer("L6").enabled = False
        config.get_layer("L6").disable_reason = "测试禁用"

        executors = mock_executors_factory()
        orchestrator = AuditOrchestrator(config, rules_registry, archiver)
        orchestrator._executors = dict(executors)

        result = await orchestrator.run()

        l6 = next(lr for lr in result.layer_results if lr.layer_id == "L6")
        assert l6.status == LayerStatus.SKIPPED
        assert executors["L6"].run_call_count == 0

    async def test_full_pipeline_resume_from_with_state(
        self,
        audit_config: AuditConfig,
        rules_registry: RulesRegistry,
        archiver: EvidenceArchiver,
        mock_executors_factory,
    ) -> None:
        """resume_from=L7 且有前序状态时 L1~L6 不重复执行。"""
        from datetime import UTC, datetime

        from scripts.prod_audit.base.layer_base import AuditState

        # 预填充 L1~L6 的状态
        now = datetime.now(UTC)
        pre_results: dict[str, LayerResult] = {}
        for lid in ("L1", "L2", "L3", "L4", "L5", "L6"):
            pre_results[lid] = make_layer_result(
                layer_id=lid,
                layer_name=audit_config.get_layer(lid).layer_name,
                weight=audit_config.get_weight(lid),
            )
        state = AuditState(
            audit_run_id="audit-resume-test",
            current_layer="L7",
            layer_states=pre_results,
            started_at=now,
            last_updated=now,
        )
        await archiver.save_state(state)

        executors = mock_executors_factory()
        orchestrator = AuditOrchestrator(audit_config, rules_registry, archiver)
        orchestrator._executors = dict(executors)

        result = await orchestrator.run(resume_from="L7")

        for lid in ("L1", "L2", "L3", "L4", "L5", "L6"):
            assert executors[lid].run_call_count == 0
        for lid in ("L7", "L8", "L9", "L10", "L11", "L12"):
            assert executors[lid].run_call_count == 1
        assert isinstance(result, AuditRunResult)
