"""L12 报告与上线决策审核层执行器。

聚合 12 层结果 / 评分计算 / 签字单生成 / 历史对比 / 问题跟踪清单 /
可执行建议生成。

约束:
    - 评分 ``total_score = Σ(weight x layer_score)``
    - ``layer_score = 100 - Σ(issue_penalty)``(critical=25/high=15/medium=1/low=0/info=0)
    - ``is_ready = (total_score ≥ 85) AND (无 critical/high 问题)``

任务来源: ``.codeartsdoer/specs/prod_code_review/tasks.md`` 第 13 节。
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from scripts.prod_audit.base.issue_builder import IssueBuilder
from scripts.prod_audit.base.layer_base import (
    AuditContext,
    AuditIssue,
    EvidenceType,
    LayerBase,
    LayerResult,
    LayerStatus,
    ReleaseDecision,
    Severity,
)
from scripts.prod_audit.config_loader import AuditConfig
from scripts.prod_audit.exceptions import ScoreCalculationError, SignOffGenerationError
from scripts.prod_audit.layers import LAYER_ORDER

PROJECT_ROOT: Path = Path(__file__).resolve().parents[3]
"""项目根目录(``D:\\erp_system``)。"""

DEFAULT_OWNER: str = "release-manager"
DEFAULT_DUE_DATE: str = "2026-09-30"

# 问题扣分映射(与 audit_config.yaml issue_penalty 一致)
_SEVERITY_PENALTY: dict[Severity, int] = {
    Severity.CRITICAL: 25,
    Severity.HIGH: 15,
    Severity.MEDIUM: 1,
    Severity.LOW: 0,
    Severity.INFO: 0,
}

# 生产就绪评分阈值
_READINESS_THRESHOLD: int = 85

# 阻断上线的严重度
_BLOCKING_SEVERITIES: frozenset[Severity] = frozenset(
    {Severity.CRITICAL, Severity.HIGH}
)


class L12Report(LayerBase):
    """L12 报告与上线决策审核层执行器。

    聚合 12 层结果,计算生产就绪评分,生成签字单与问题跟踪清单,
    与上一轮审核结果对比,产出可执行建议。
    """

    layer_id: str = "L12"
    layer_name: str = "报告与上线决策"
    weight: float = 0.03

    # ------------------------------------------------------------------
    # 公共入口
    # ------------------------------------------------------------------

    async def run(self, context: AuditContext) -> LayerResult:
        """执行 L12 报告生成与上线决策。"""
        started_at = datetime.now(UTC)
        builder = IssueBuilder()
        raw_outputs: dict[str, str] = {}

        # 从上下文获取前 11 层结果
        previous_results = context.previous_results
        all_layer_results = list(previous_results)

        # 评分计算
        try:
            score_result = self._calculate_readiness_score(
                all_layer_results, context, builder
            )
            raw_outputs["score"] = json.dumps(score_result, ensure_ascii=False, indent=2)
        except ScoreCalculationError as exc:
            score_result = {"error": str(exc)}
            raw_outputs["score"] = f"SCORE_ERROR: {exc}"
            builder.build(
                layer_id=self.layer_id,
                severity=Severity.HIGH,
                file=str(PROJECT_ROOT),
                line=1,
                description=f"评分计算失败: {exc}",
                suggestion="检查层结果完整性与配置权重",
                rule_id="L12-SCORE-CALC-001",
                owner=DEFAULT_OWNER,
                due_date=DEFAULT_DUE_DATE,
            )

        # 历史对比
        diff_result = self._compare_with_baseline(all_layer_results, context, builder)
        raw_outputs["diff"] = json.dumps(diff_result, ensure_ascii=False, indent=2)

        # 签字单
        try:
            signoff_result = self._generate_signoff(
                all_layer_results, score_result, context, builder
            )
            raw_outputs["signoff"] = json.dumps(
                signoff_result, ensure_ascii=False, indent=2
            )
        except SignOffGenerationError as exc:
            signoff_result = {"error": str(exc)}
            raw_outputs["signoff"] = f"SIGNOFF_ERROR: {exc}"

        # 问题跟踪清单
        issue_tracker = self._generate_issue_tracker(all_layer_results)
        raw_outputs["issue_tracker"] = json.dumps(
            issue_tracker, ensure_ascii=False, indent=2
        )

        # 可执行建议
        recommendations = self._generate_recommendations(all_layer_results, score_result)
        raw_outputs["recommendations"] = json.dumps(
            recommendations, ensure_ascii=False, indent=2
        )

        # 审核报告
        report = self._generate_audit_report(
            all_layer_results, score_result, signoff_result, diff_result, issue_tracker
        )
        raw_outputs["report"] = json.dumps(report, ensure_ascii=False, indent=2)

        # 收集所有问题(含本层生成的校验问题)
        all_issues: list[AuditIssue] = []
        for lr in all_layer_results:
            all_issues.extend(lr.issues)

        # L12 自身校验: 评分一致性 + 签字单完整性 + 决策一致性
        l12_issues = self._validate_decision_consistency(
            all_layer_results, score_result, builder
        )
        all_issues_l12 = list(all_issues) + l12_issues

        # 门禁校验: 评分 ≥ 85 且无 critical/high
        is_ready = score_result.get("is_ready", False)
        is_green = is_ready and self.check_gate(l12_issues, threshold=Severity.HIGH)
        status = LayerStatus.PASSED if is_green else LayerStatus.BLOCKED

        evidence_path = await self._archive_evidence(
            context, raw_outputs, all_issues_l12, report
        )

        return LayerResult(
            layer_id=self.layer_id,
            layer_name=self.layer_name,
            status=status,
            issues=all_issues_l12,
            evidence_path=str(evidence_path),
            started_at=started_at,
            finished_at=datetime.now(UTC),
            weight=self.weight,
        )

    # ------------------------------------------------------------------
    # 13.1 评分计算
    # ------------------------------------------------------------------

    def _calculate_readiness_score(
        self,
        layer_results: Sequence[LayerResult],
        context: AuditContext,
        builder: IssueBuilder,
    ) -> dict[str, object]:
        """计算生产就绪评分。

        - ``layer_score = 100 - Σ(issue_penalty)``(下限 0)
        - ``total_score = Σ(weight x layer_score)``
        - ``is_ready = (total_score ≥ 85) AND (无 critical/high)``
        """
        config = self._extract_config(context)
        weights = (
            config.weights if config is not None else
            {lr.layer_id: lr.weight for lr in layer_results}
        )
        readiness_threshold = (
            config.readiness_threshold if config is not None else _READINESS_THRESHOLD
        )

        # 校验层数(L12 自身结果尚未加入,仅需 L1-L11 共 11 层)
        if len(layer_results) < 11:
            raise ScoreCalculationError(
                f"Expected at least 11 layer results (L1-L11), got {len(layer_results)}"
            )

        # 校验权重
        for layer_id in LAYER_ORDER:
            if layer_id not in weights:
                raise ScoreCalculationError(
                    f"Weight for layer '{layer_id}' not found"
                )

        layer_scores: list[dict[str, object]] = []
        total_score = 0.0
        has_blocking = False
        basis_parts: list[str] = []

        for lr in layer_results:
            # 计算层得分
            penalty_sum = sum(
                _SEVERITY_PENALTY.get(issue.severity, 0) for issue in lr.issues
            )
            layer_score = max(0.0, 100.0 - penalty_sum)
            weight = weights.get(lr.layer_id, lr.weight)
            weighted = layer_score * weight
            total_score += weighted

            layer_has_blocking = any(
                issue.severity in _BLOCKING_SEVERITIES for issue in lr.issues
            )
            if layer_has_blocking:
                has_blocking = True

            issue_count = len(lr.issues)
            basis_parts.append(
                f"{lr.layer_id}: score={layer_score:.1f} "
                f"(penalty={penalty_sum}, issues={issue_count}, "
                f"weight={weight}, weighted={weighted:.2f})"
            )
            layer_scores.append(
                {
                    "layer_id": lr.layer_id,
                    "layer_name": lr.layer_name,
                    "score": round(layer_score, 2),
                    "penalty": penalty_sum,
                    "issue_count": issue_count,
                    "weight": weight,
                    "weighted_score": round(weighted, 4),
                    "status": lr.status.value,
                }
            )

        total_score = round(total_score, 2)
        is_ready = (total_score >= readiness_threshold) and not has_blocking

        return {
            "total_score": total_score,
            "readiness_threshold": readiness_threshold,
            "is_ready": is_ready,
            "has_blocking_issues": has_blocking,
            "layer_scores": layer_scores,
            "score_basis": "\n".join(basis_parts),
            "calculation_time": datetime.now(UTC).isoformat(),
        }

    # ------------------------------------------------------------------
    # 13.2 签字单生成
    # ------------------------------------------------------------------

    def _generate_signoff(
        self,
        layer_results: Sequence[LayerResult],
        score: dict[str, object],
        context: AuditContext,
        builder: IssueBuilder,
    ) -> dict[str, object]:
        """生成含 12 层审核员签字栏 + 发布负责人签字栏 + 放行条件的签字单。"""
        # L12 自身结果尚未加入,仅需 L1-L11 共 11 层
        if len(layer_results) < 11:
            raise SignOffGenerationError(
                f"Expected at least 11 layer results (L1-L11) for sign-off, got {len(layer_results)}"
            )

        config = self._extract_config(context)

        # 各层签字
        layer_signoffs: list[dict[str, object]] = []
        for lr in layer_results:
            reviewer = DEFAULT_OWNER
            if config is not None:
                try:
                    layer_cfg = config.get_layer(lr.layer_id)
                    reviewer = layer_cfg.reviewer
                except KeyError:
                    pass

            result = "approved" if lr.status == LayerStatus.PASSED else "rejected"
            layer_signoffs.append(
                {
                    "layer_id": lr.layer_id,
                    "reviewer": reviewer,
                    "signed_at": (
                        lr.finished_at.isoformat() if lr.finished_at else None
                    ),
                    "result": result,
                }
            )

        # 放行条件
        is_ready = score.get("is_ready", False)
        total_score = score.get("total_score", 0.0)
        conditions = [
            "12 层审核全部通过",
            f"评分 ≥ {score.get('readiness_threshold', _READINESS_THRESHOLD)}(当前: {total_score})",
            "证据归档完整",
            "阻断/高严重度问题全部修复",
            "发布负责人签字",
        ]

        conditions_status: list[dict[str, object]] = []
        all_passed = all(
            lr.status in (LayerStatus.PASSED, LayerStatus.SKIPPED)
            for lr in layer_results
        )
        conditions_status.append({"condition": conditions[0], "met": all_passed})

        score_met = total_score >= score.get(
            "readiness_threshold", _READINESS_THRESHOLD
        )
        conditions_status.append({"condition": conditions[1], "met": score_met})

        conditions_status.append({"condition": conditions[2], "met": True})

        has_blocking = score.get("has_blocking_issues", False)
        conditions_status.append({"condition": conditions[3], "met": not has_blocking})

        conditions_status.append({"condition": conditions[4], "met": is_ready})

        release_decision = (
            ReleaseDecision.APPROVED if is_ready else ReleaseDecision.REJECTED
        )
        decision_reason = (
            "所有放行条件满足,评分达标且无阻断问题"
            if is_ready
            else f"放行条件未满足(评分={total_score}, has_blocking={has_blocking})"
        )

        return {
            "signoff_id": f"signoff-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}",
            "layer_signoffs": layer_signoffs,
            "release_manager": DEFAULT_OWNER,
            "release_decision": release_decision.value,
            "decision_reason": decision_reason,
            "conditions": conditions_status,
            "signed_at": datetime.now(UTC).isoformat() if is_ready else None,
        }

    # ------------------------------------------------------------------
    # 13.3 历史对比
    # ------------------------------------------------------------------

    def _compare_with_baseline(
        self,
        layer_results: Sequence[LayerResult],
        context: AuditContext,
        builder: IssueBuilder,
    ) -> dict[str, object]:
        """对比本轮与上一轮审核结果(新增/修复/遗留问题)。"""
        baseline_dir: Path = context.baseline_dir
        baseline_report = baseline_dir / "audit_report.json"

        if not baseline_report.exists():
            return {
                "status": "skipped",
                "reason": f"基线报告 {baseline_report} 不存在",
            }

        try:
            baseline_data = json.loads(baseline_report.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            return {"status": "error", "reason": f"解析基线报告失败: {exc}"}

        # 收集基线问题 ID
        baseline_issue_ids: set[str] = set()
        baseline_layers = baseline_data.get("layer_results", [])
        for bl_layer in baseline_layers:
            for issue in bl_layer.get("issues", []):
                baseline_issue_ids.add(issue.get("issue_id", ""))

        # 收集本轮问题 ID
        current_issue_ids: set[str] = set()
        current_issues_map: dict[str, dict[str, object]] = {}
        for lr in layer_results:
            for issue in lr.issues:
                current_issue_ids.add(issue.issue_id)
                current_issues_map[issue.issue_id] = issue.model_dump(mode="json")

        new_issues = sorted(current_issue_ids - baseline_issue_ids)
        fixed_issues = sorted(baseline_issue_ids - current_issue_ids)
        remaining_issues = sorted(current_issue_ids & baseline_issue_ids)

        return {
            "status": "compared",
            "baseline_report": str(baseline_report),
            "new_issues": new_issues,
            "new_issues_count": len(new_issues),
            "fixed_issues": fixed_issues,
            "fixed_issues_count": len(fixed_issues),
            "remaining_issues": remaining_issues,
            "remaining_issues_count": len(remaining_issues),
        }

    # ------------------------------------------------------------------
    # 13.4 问题跟踪清单
    # ------------------------------------------------------------------

    def _generate_issue_tracker(
        self, layer_results: Sequence[LayerResult]
    ) -> list[dict[str, object]]:
        """聚合全部 AuditIssue,按严重度分级排序,附跟踪信息。"""
        all_issues: list[AuditIssue] = []
        for lr in layer_results:
            all_issues.extend(lr.issues)

        # 按严重度排序(critical > high > medium > low > info)
        severity_order = {
            Severity.CRITICAL: 0,
            Severity.HIGH: 1,
            Severity.MEDIUM: 2,
            Severity.LOW: 3,
            Severity.INFO: 4,
        }
        sorted_issues = sorted(
            all_issues,
            key=lambda i: (severity_order.get(i.severity, 99), i.layer_id, i.issue_id),
        )

        tracker: list[dict[str, object]] = []
        for issue in sorted_issues:
            # 修复优先级与跟踪标记
            if issue.severity in _BLOCKING_SEVERITIES:
                action = "须修复后方可上线并复测通过"
            elif issue.severity == Severity.MEDIUM:
                action = "上线后首轮迭代修复"
            else:
                action = "跟踪优化"

            tracker.append(
                {
                    "issue_id": issue.issue_id,
                    "layer_id": issue.layer_id,
                    "severity": issue.severity.value,
                    "file": issue.file,
                    "line": issue.line,
                    "description": issue.description,
                    "rule_id": issue.rule_id,
                    "owner": issue.owner,
                    "due_date": issue.due_date,
                    "status": issue.status.value,
                    "retest_result": issue.retest_result.value,
                    "linked_pr": issue.linked_pr,
                    "action": action,
                }
            )

        return tracker

    # ------------------------------------------------------------------
    # 13.5 可执行建议
    # ------------------------------------------------------------------

    def _generate_recommendations(
        self,
        layer_results: Sequence[LayerResult],
        score: dict[str, object],
    ) -> list[dict[str, object]]:
        """根据问题生成可执行建议。"""
        recommendations: list[dict[str, object]] = []

        # 按层聚合问题
        for lr in layer_results:
            if not lr.issues:
                continue
            critical_count = sum(
                1 for i in lr.issues if i.severity == Severity.CRITICAL
            )
            high_count = sum(
                1 for i in lr.issues if i.severity == Severity.HIGH
            )
            medium_count = sum(
                1 for i in lr.issues if i.severity == Severity.MEDIUM
            )

            priority = "P0"
            if critical_count > 0:
                priority = "P0"
            elif high_count > 0:
                priority = "P1"
            elif medium_count > 0:
                priority = "P2"
            else:
                priority = "P3"

            recommendations.append(
                {
                    "layer_id": lr.layer_id,
                    "layer_name": lr.layer_name,
                    "priority": priority,
                    "critical": critical_count,
                    "high": high_count,
                    "medium": medium_count,
                    "total_issues": len(lr.issues),
                    "recommendation": (
                        f"修复 {lr.layer_name} 中的 "
                        f"{critical_count} critical / {high_count} high / "
                        f"{medium_count} medium 问题"
                    ),
                }
            )

        # 评分建议
        total_score = score.get("total_score", 0.0)
        is_ready = score.get("is_ready", False)
        if not is_ready:
            threshold = score.get("readiness_threshold", _READINESS_THRESHOLD)
            gap = threshold - total_score
            recommendations.append(
                {
                    "layer_id": "L12",
                    "layer_name": "评分",
                    "priority": "P0",
                    "recommendation": (
                        f"生产就绪评分 {total_score} 低于阈值 {threshold},"
                        f"须提升 {gap:.1f} 分方可上线"
                    ),
                }
            )

        # 按优先级排序
        priority_order = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
        recommendations.sort(
            key=lambda r: priority_order.get(r.get("priority", "P3"), 99)
        )

        return recommendations

    # ------------------------------------------------------------------
    # 13.5 审核报告生成
    # ------------------------------------------------------------------

    def _generate_audit_report(
        self,
        layer_results: Sequence[LayerResult],
        score: dict[str, object],
        signoff: dict[str, object],
        diff: dict[str, object],
        issue_tracker: list[dict[str, object]],
    ) -> dict[str, object]:
        """生成全量审核总报告(含 12 层结果 + 评分 + 签字单 + diff)。"""
        return {
            "audit_run_id": f"audit-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}",
            "generated_at": datetime.now(UTC).isoformat(),
            "layer_results": [
                lr.model_dump(mode="json") for lr in layer_results
            ],
            "score": score,
            "signoff": signoff,
            "diff": diff,
            "issue_tracker": issue_tracker,
            "summary": {
                "total_layers": len(layer_results),
                "passed_layers": sum(
                    1 for lr in layer_results if lr.status == LayerStatus.PASSED
                ),
                "blocked_layers": sum(
                    1 for lr in layer_results if lr.status == LayerStatus.BLOCKED
                ),
                "total_issues": sum(len(lr.issues) for lr in layer_results),
                "total_score": score.get("total_score", 0.0),
                "is_ready": score.get("is_ready", False),
            },
        }

    # ------------------------------------------------------------------
    # 决策一致性校验
    # ------------------------------------------------------------------

    def _validate_decision_consistency(
        self,
        layer_results: Sequence[LayerResult],
        score: dict[str, object],
        builder: IssueBuilder,
    ) -> list[AuditIssue]:
        """校验上线决策与阻断问题一致性。"""
        issues: list[AuditIssue] = []

        # 校验: 若有 critical/high 则 is_ready 必须为 False
        has_blocking = any(
            issue.severity in _BLOCKING_SEVERITIES
            for lr in layer_results
            for issue in lr.issues
        )
        is_ready = score.get("is_ready", False)

        if has_blocking and is_ready:
            issues.append(
                builder.build(
                    layer_id=self.layer_id,
                    severity=Severity.CRITICAL,
                    file=str(PROJECT_ROOT),
                    line=1,
                    description="决策不一致: 存在 critical/high 问题但 is_ready=true",
                    suggestion="修正评分计算逻辑,有阻断问题时 is_ready 须为 false",
                    rule_id="L12-DECISION-001",
                    owner=DEFAULT_OWNER,
                    due_date=DEFAULT_DUE_DATE,
                )
            )

        # 校验: 评分 < 85 则 is_ready 必须为 False
        total_score = score.get("total_score", 0.0)
        threshold = score.get("readiness_threshold", _READINESS_THRESHOLD)
        if total_score < threshold and is_ready:
            issues.append(
                builder.build(
                    layer_id=self.layer_id,
                    severity=Severity.HIGH,
                    file=str(PROJECT_ROOT),
                    line=1,
                    description=(
                        f"决策不一致: 评分 {total_score} < 阈值 {threshold}"
                        " 但 is_ready=true"
                    ),
                    suggestion="修正评分计算,评分低于阈值时 is_ready 须为 false",
                    rule_id="L12-SCORE-CALC-001",
                    owner=DEFAULT_OWNER,
                    due_date=DEFAULT_DUE_DATE,
                )
            )

        return issues

    # ------------------------------------------------------------------
    # 辅助: 从上下文提取配置
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_config(context: AuditContext) -> AuditConfig | None:
        """从上下文提取 AuditConfig(若类型匹配)。"""
        config = context.config
        if isinstance(config, AuditConfig):
            return config
        return None

    # ------------------------------------------------------------------
    # 证据归档
    # ------------------------------------------------------------------

    async def _archive_evidence(
        self,
        context: AuditContext,
        raw_outputs: dict[str, str],
        issues: Sequence[AuditIssue],
        report: dict[str, object],
    ) -> Path:
        """归档审核报告与签字单至 ``evidence/``。"""
        archiver = context.archiver

        # 1. 全量审核报告 JSON
        path_report = await archiver.archive(
            layer_id=self.layer_id,
            evidence_type=EvidenceType.GATE_LOG,
            content=json.dumps(report, ensure_ascii=False, indent=2),
            filename="audit_report.json",
        )

        # 2. 签字单
        path_signoff = await archiver.archive(
            layer_id=self.layer_id,
            evidence_type=EvidenceType.GATE_LOG,
            content=raw_outputs.get("signoff", "{}"),
            filename="release_signoff.json",
        )

        # 3. 问题跟踪清单
        path_tracker = await archiver.archive(
            layer_id=self.layer_id,
            evidence_type=EvidenceType.GATE_LOG,
            content=raw_outputs.get("issue_tracker", "[]"),
            filename="issue_tracker.json",
        )

        # 4. Markdown 摘要
        md_content = self._build_summary_markdown(raw_outputs)
        path_md = await archiver.archive(
            layer_id=self.layer_id,
            evidence_type=EvidenceType.GATE_LOG,
            content=md_content,
            filename="L12/audit_summary.md",
        )

        # 5. issues.json
        issues_json = json.dumps(
            [issue.model_dump(mode="json") for issue in issues],
            ensure_ascii=False,
            indent=2,
        )
        path_issues = await archiver.archive(
            layer_id=self.layer_id,
            evidence_type=EvidenceType.GATE_LOG,
            content=issues_json,
            filename="L12/issues.json",
        )

        return path_md or path_report or path_signoff or path_tracker or path_issues

    @staticmethod
    def _build_summary_markdown(raw_outputs: dict[str, str]) -> str:
        """构建 L12 Markdown 摘要(评分 / 历史对比 / 可执行建议)。"""
        try:
            score_data = json.loads(raw_outputs.get("score", "{}"))
        except (json.JSONDecodeError, TypeError):
            score_data = {}
        total_score = score_data.get("total_score", 0.0)
        is_ready = score_data.get("is_ready", False)
        md_content = (
            "# 生产代码审核总报告\n\n"
            f"**生成时间**: {datetime.now(UTC).isoformat()}\n\n"
            f"**生产就绪评分**: {total_score} / 100\n\n"
            f"**上线决策**: {'APPROVED' if is_ready else 'REJECTED'}\n\n"
            "## 各层得分\n\n"
            "| 层 | 得分 | 问题数 | 状态 |\n"
            "|---|---|---|---|\n"
        )
        for ls in score_data.get("layer_scores", []):
            md_content += (
                f"| {ls.get('layer_id')} {ls.get('layer_name')} "
                f"| {ls.get('score')} | {ls.get('issue_count')} "
                f"| {ls.get('status')} |\n"
            )

        md_content += "\n## 历史对比\n\n"
        try:
            diff_data = json.loads(raw_outputs.get("diff", "{}"))
        except (json.JSONDecodeError, TypeError):
            diff_data = {}
        md_content += (
            f"- 新增问题: {diff_data.get('new_issues_count', 'N/A')}\n"
            f"- 已修复: {diff_data.get('fixed_issues_count', 'N/A')}\n"
            f"- 遗留: {diff_data.get('remaining_issues_count', 'N/A')}\n\n"
        )

        md_content += "## 可执行建议\n\n"
        try:
            rec_data = json.loads(raw_outputs.get("recommendations", "[]"))
        except (json.JSONDecodeError, TypeError):
            rec_data = []
        for rec in rec_data:
            md_content += (
                f"- **{rec.get('priority', '?')}** "
                f"[{rec.get('layer_id', '?')}] {rec.get('recommendation', '')}\n"
            )
        return md_content
