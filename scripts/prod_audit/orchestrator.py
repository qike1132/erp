"""审核编排器。

顺序编排 12 层审核执行器,实现门禁递进、断点恢复与层禁用跳过,
汇总生产就绪评分与上线签字单。

CLI 入口::

    python -m scripts.prod_audit.orchestrator --config <path> --resume-from <layer_id>

退出码:
    - 0 — 正常完成
    - 1 — 层门禁阻断(:class:`AuditLayerBlockedError`)
    - 2 — 配置错误(:class:`AuditConfigError`)
"""

from __future__ import annotations

import argparse
import asyncio
import importlib
import sys
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from pydantic import BaseModel, Field

from scripts.prod_audit.base.layer_base import (
    AuditContext,
    AuditIssue,
    AuditState,
    EvidenceType,
    LayerBase,
    LayerResult,
    LayerStatus,
    ReleaseDecision,
    Severity,
)
from scripts.prod_audit.config_loader import (
    AuditConfig,
    ConfigLoader,
    LayerConfig,
    RulesRegistry,
)
from scripts.prod_audit.evidence_archiver import EvidenceArchiver
from scripts.prod_audit.exceptions import (
    AuditConfigError,
    AuditLayerBlockedError,
    EvidenceArchiveError,
    ScoreCalculationError,
    SignOffGenerationError,
)
from scripts.prod_audit.layers import LAYER_MODULE_NAMES, LAYER_ORDER

# 重新导出异常,满足任务 1.7 "定义自定义异常" 的接口要求
__all__ = [
    "AuditConfigError",
    "AuditDiff",
    "AuditLayerBlockedError",
    "AuditOrchestrator",
    "AuditRunResult",
    "AuditState",
    "EvidenceArchiveError",
    "LayerScoreEntry",
    "LayerSignOffEntry",
    "ProductionReadinessScore",
    "ReleaseSignOff",
    "ScoreCalculationError",
    "SignOffGenerationError",
    "WeightEntry",
    "main",
]

# ---------------------------------------------------------------------------
# 严重度阈值映射
# ---------------------------------------------------------------------------

_SEVERITY_THRESHOLD_MAP: dict[str, Severity] = {
    "critical": Severity.CRITICAL,
    "high": Severity.HIGH,
    "medium": Severity.MEDIUM,
    "low": Severity.LOW,
    "info": Severity.INFO,
}


# ---------------------------------------------------------------------------
# 评分与签字数据模型
# ---------------------------------------------------------------------------


class LayerScoreEntry(BaseModel):
    """单层得分条目。"""

    layer_id: str = Field(description="层 ID")
    score: float = Field(ge=0, le=100, description="层得分")
    basis: str = Field(description="得分依据说明")


class WeightEntry(BaseModel):
    """单层权重条目。"""

    layer_id: str = Field(description="层 ID")
    weight: float = Field(ge=0, le=1, description="层权重")


class ProductionReadinessScore(BaseModel):
    """生产就绪评分。"""

    total_score: float = Field(ge=0, le=100, description="总分(0-100)")
    layer_scores: list[LayerScoreEntry] = Field(
        min_length=12, max_length=12, description="各层得分(共 12 项)"
    )
    weights: list[WeightEntry] = Field(
        min_length=12, max_length=12, description="各层权重(共 12 项,Σweight = 1)"
    )
    calculation_time: datetime = Field(description="评分计算时间")
    is_ready: bool = Field(description="是否就绪")
    score_basis: str = Field(description="评分依据说明")


class LayerSignOffEntry(BaseModel):
    """单层签字条目。"""

    layer_id: str = Field(description="层 ID")
    reviewer: str = Field(description="审核员")
    signed_at: datetime = Field(description="签字时间")
    result: str = Field(description="签字结果:approved / rejected / conditional")


class ReleaseSignOff(BaseModel):
    """上线就绪签字单。"""

    signoff_id: str = Field(description="签字单唯一标识")
    audit_run_id: str = Field(description="关联审核运行 ID")
    layer_signoffs: list[LayerSignOffEntry] = Field(
        min_length=12, max_length=12, description="各层签字(共 12 项)"
    )
    release_manager: str = Field(description="发布负责人")
    release_decision: ReleaseDecision = Field(description="上线决策")
    decision_reason: str = Field(description="决策理由")
    signed_at: datetime | None = Field(default=None, description="签字时间")
    conditions: list[str] = Field(default_factory=list, description="放行条件列表")


class AuditDiff(BaseModel):
    """审核差异(与上次运行对比)。"""

    new_issues: list[AuditIssue] = Field(default_factory=list, description="本次新增问题")
    fixed_issues: list[str] = Field(
        default_factory=list, description="已修复问题 issue_id 列表"
    )
    remaining_issues: list[str] = Field(
        default_factory=list, description="遗留问题 issue_id 列表"
    )


class AuditRunResult(BaseModel):
    """审核运行最终结果。"""

    audit_run_id: str = Field(description="审核运行唯一标识")
    layer_results: list[LayerResult] = Field(description="12 层审核结果")
    score: ProductionReadinessScore = Field(description="生产就绪评分")
    signoff: ReleaseSignOff = Field(description="上线签字单")
    diff: AuditDiff = Field(description="审核差异")
    started_at: datetime = Field(description="运行开始时间")
    finished_at: datetime = Field(description="运行完成时间")


# ---------------------------------------------------------------------------
# 层执行器加载
# ---------------------------------------------------------------------------


def _load_layer_executor(layer_id: str) -> LayerBase | None:
    """动态加载层执行器模块。

    参数:
        layer_id: 层 ID(如 ``"L1"``)

    返回:
        :class:`LayerBase` 实例;若模块不存在则返回 ``None``

    抛出:
        AuditConfigError: 模块存在但加载/实例化失败
    """
    module_name = LAYER_MODULE_NAMES.get(layer_id)
    if module_name is None:
        return None

    full_module = f"scripts.prod_audit.layers.{module_name}"

    try:
        module = importlib.import_module(full_module)
    except ModuleNotFoundError:
        # 层执行器尚未实现(后续任务组完成)
        return None
    except Exception as exc:
        raise AuditConfigError(
            f"Failed to import layer executor '{full_module}' for {layer_id}: {exc}"
        ) from exc

    # 在模块中查找 LayerBase 子类
    executor_cls: type[LayerBase] | None = None
    for attr_name in dir(module):
        attr = getattr(module, attr_name)
        if (
            isinstance(attr, type)
            and issubclass(attr, LayerBase)
            and attr is not LayerBase
        ):
            executor_cls = attr
            break

    if executor_cls is None:
        raise AuditConfigError(
            f"Layer executor module '{full_module}' for {layer_id} "
            "does not define a LayerBase subclass."
        )

    try:
        return executor_cls()
    except Exception as exc:
        raise AuditConfigError(
            f"Failed to instantiate layer executor '{executor_cls.__name__}' "
            f"for {layer_id}: {exc}"
        ) from exc


# ---------------------------------------------------------------------------
# AuditOrchestrator
# ---------------------------------------------------------------------------


class AuditOrchestrator:
    """审核编排器。

    顺序执行 12 层审核,实现门禁递进、断点恢复与层禁用跳过。

    参数:
        config: 审核配置
        rules: 规则注册表
        archiver: 证据归档器

    使用示例::

        config = ConfigLoader.load("audit_config.yaml")
        rules = RulesRegistry.load("rules_registry.yaml")
        archiver = EvidenceArchiver(Path("evidence"))
        orchestrator = AuditOrchestrator(config, rules, archiver)
        result = await orchestrator.run()
    """

    def __init__(
        self,
        config: AuditConfig,
        rules: RulesRegistry,
        archiver: EvidenceArchiver,
    ) -> None:
        self.config: AuditConfig = config
        self.rules: RulesRegistry = rules
        self.archiver: EvidenceArchiver = archiver
        self._executors: dict[str, LayerBase | None] = {}

    def _get_executor(self, layer_id: str) -> LayerBase | None:
        """获取层执行器(惰性加载并缓存)。"""
        if layer_id not in self._executors:
            self._executors[layer_id] = _load_layer_executor(layer_id)
        return self._executors[layer_id]

    async def run(self, resume_from: str | None = None) -> AuditRunResult:
        """执行 12 层审核 pipeline。

        参数:
            resume_from: 断点恢复层 ID(如 ``"L4"``),``None`` 表示从头开始。
                也可从 ``config.resume_from`` 读取。

        返回:
            :class:`AuditRunResult`

        抛出:
            AuditLayerBlockedError: 某层门禁阻断(存在 critical/high 问题)
            NotImplementedError: 层执行器未实现
            ScoreCalculationError: 评分计算失败
            SignOffGenerationError: 签字单生成失败
            EvidenceArchiveError: 状态持久化失败
        """
        run_id = f"audit-{uuid.uuid4().hex[:12]}"
        started_at = datetime.now(UTC)

        # 确定断点恢复起始层
        effective_resume = resume_from or self.config.resume_from
        if effective_resume is not None and effective_resume not in LAYER_ORDER:
            raise AuditConfigError(
                f"resume_from '{effective_resume}' is not a valid layer ID"
            )

        # 尝试加载已有状态(断点恢复)
        previous_state = await self.archiver.load_state()
        layer_results: dict[str, LayerResult] = {}

        if previous_state is not None and effective_resume is not None:
            # 从已有状态恢复已完成的层
            layer_results = dict(previous_state.layer_states)
            run_id = previous_state.audit_run_id
            started_at = previous_state.started_at

        # 确定执行起始索引
        start_idx = 0
        if effective_resume is not None:
            start_idx = LAYER_ORDER.index(effective_resume)

        # 构造审核上下文
        previous_results = list(layer_results.values())
        context = AuditContext(
            config=self.config,
            rules=self.rules,
            archiver=self.archiver,
            baseline_dir=self.archiver.evidence_dir,
            previous_results=previous_results,
        )

        # 顺序执行各层
        blocking_threshold = _SEVERITY_THRESHOLD_MAP.get(
            self.config.severity_threshold, Severity.HIGH
        )

        for idx in range(start_idx, len(LAYER_ORDER)):
            layer_id = LAYER_ORDER[idx]
            layer_cfg = self.config.get_layer(layer_id)
            await self._execute_layer(
                layer_id,
                layer_cfg,
                context,
                run_id,
                layer_results,
                started_at,
                blocking_threshold,
            )

        # 计算评分
        score = self._calculate_score(layer_results, started_at)

        # 生成签字单
        signoff = self._generate_signoff(run_id, layer_results, score)

        # 计算差异
        diff = self._calculate_diff(layer_results, previous_results)

        finished_at = datetime.now(UTC)

        # 清理状态文件
        await self.archiver.clear_state()

        return AuditRunResult(
            audit_run_id=run_id,
            layer_results=[layer_results[layer_id] for layer_id in LAYER_ORDER],
            score=score,
            signoff=signoff,
            diff=diff,
            started_at=started_at,
            finished_at=finished_at,
        )

    async def _execute_layer(
        self,
        layer_id: str,
        layer_cfg: LayerConfig,
        context: AuditContext,
        run_id: str,
        layer_results: dict[str, LayerResult],
        started_at: datetime,
        blocking_threshold: Severity,
    ) -> None:
        """执行单层审核：跳过/失败/门禁阻断的处理与状态持久化。"""
        # 层禁用跳过
        if not layer_cfg.enabled:
            layer_results[layer_id] = LayerResult(
                layer_id=layer_id,
                layer_name=layer_cfg.layer_name,
                status=LayerStatus.SKIPPED,
                issues=[],
                evidence_path=None,
                started_at=datetime.now(UTC),
                finished_at=datetime.now(UTC),
                error=None,
                layer_score=100.0,
                weight=self.config.get_weight(layer_id),
            )
            await self._save_state(run_id, layer_id, layer_results, started_at)
            return

        # 加载层执行器
        executor = self._get_executor(layer_id)
        if executor is None:
            # 层执行器尚未实现
            raise NotImplementedError(
                f"Layer executor for {layer_id} ({layer_cfg.layer_name}) "
                f"is not implemented. Module "
                f"'scripts.prod_audit.layers.{LAYER_MODULE_NAMES[layer_id]}' "
                "not found. Implement the layer executor in a subsequent task group."
            )

        # 同步上下文：将已完成层结果注入 context，供后续层（如 L12）读取
        context.previous_results = list(layer_results.values())

        # 执行层审核
        layer_started = datetime.now(UTC)
        try:
            result = await executor.run(context)
        except AuditLayerBlockedError:
            raise
        except Exception as exc:
            result = LayerResult(
                layer_id=layer_id,
                layer_name=layer_cfg.layer_name,
                status=LayerStatus.FAILED,
                issues=[],
                evidence_path=None,
                started_at=layer_started,
                finished_at=datetime.now(UTC),
                error=str(exc),
                layer_score=0.0,
                weight=self.config.get_weight(layer_id),
            )
            layer_results[layer_id] = result
            await self._save_state(run_id, layer_id, layer_results, started_at)
            raise

        result.weight = self.config.get_weight(layer_id)
        layer_results[layer_id] = result

        # 持久化状态
        await self._save_state(run_id, layer_id, layer_results, started_at)

        # 归档门禁日志
        await self._archive_gate_log(layer_id, result)

        # 门禁检查
        self._enforce_layer_gate(layer_id, executor, result, blocking_threshold)

    def _enforce_layer_gate(
        self,
        layer_id: str,
        executor: LayerBase,
        result: LayerResult,
        blocking_threshold: Severity,
    ) -> None:
        """层门禁检查：存在阻断问题时抛出 AuditLayerBlockedError。"""
        if executor.check_gate(result.issues, blocking_threshold):
            return
        blocking_issues = [
            i
            for i in result.issues
            if _SEVERITY_THRESHOLD_MAP.get(
                self.config.severity_threshold, Severity.HIGH
            )
            in (Severity.CRITICAL, Severity.HIGH)
            and i.severity in (Severity.CRITICAL, Severity.HIGH)
        ]
        summary = (
            f"{len(blocking_issues)} blocking issue(s) at "
            f"{self.config.severity_threshold}+ severity"
        )
        raise AuditLayerBlockedError(layer_id, summary)

    async def _save_state(
        self,
        run_id: str,
        current_layer: str,
        layer_results: dict[str, LayerResult],
        started_at: datetime,
    ) -> None:
        """持久化当前运行状态。"""
        state = AuditState(
            audit_run_id=run_id,
            current_layer=current_layer,
            layer_states=dict(layer_results),
            started_at=started_at,
            last_updated=datetime.now(UTC),
        )
        await self.archiver.save_state(state)

    async def _archive_gate_log(self, layer_id: str, result: LayerResult) -> None:
        """归档门禁日志。"""
        log_content = (
            f"Layer: {layer_id}\n"
            f"Status: {result.status.value}\n"
            f"Issues: {len(result.issues)}\n"
            f"Score: {result.layer_score}\n"
            f"Started: {result.started_at.isoformat()}\n"
            f"Finished: {result.finished_at.isoformat() if result.finished_at else 'N/A'}\n"
        )
        if result.error:
            log_content += f"Error: {result.error}\n"
        for issue in result.issues:
            log_content += (
                f"  [{issue.severity.value}] {issue.issue_id} "
                f"{issue.file}:{issue.line} - {issue.description}\n"
            )

        await self.archiver.archive(
            layer_id=layer_id,
            evidence_type=EvidenceType.GATE_LOG,
            content=log_content,
            filename=f"{layer_id}_gate.log",
        )

    def _calculate_score(
        self,
        layer_results: dict[str, LayerResult],
        started_at: datetime,
    ) -> ProductionReadinessScore:
        """计算生产就绪评分。

        每层起始 100 分,按问题严重度扣分:
        critical=25 / high=15 / medium=8 / low=3 / info=1。
        层得分 = max(0, 100 - Σpenalty)。
        总分 = Sigma(layer_score * weight).
        """
        penalty = self.config.issue_penalty
        penalty_map = {
            Severity.CRITICAL: penalty.critical,
            Severity.HIGH: penalty.high,
            Severity.MEDIUM: penalty.medium,
            Severity.LOW: penalty.low,
            Severity.INFO: penalty.info,
        }

        layer_scores: list[LayerScoreEntry] = []
        weights: list[WeightEntry] = []
        total_score = 0.0
        has_blocking = False
        basis_parts: list[str] = []

        for layer_id in LAYER_ORDER:
            result = layer_results.get(layer_id)
            weight = self.config.get_weight(layer_id)
            weights.append(WeightEntry(layer_id=layer_id, weight=weight))
            delta, layer_blocking = self._score_single_layer(
                layer_id, result, weight, penalty_map, layer_scores, basis_parts
            )
            total_score += delta
            has_blocking = has_blocking or layer_blocking

        total_score = round(total_score, 2)
        is_ready = total_score >= self.config.readiness_threshold and not has_blocking

        score_basis = (
            f"Total: {total_score:.2f} (threshold: {self.config.readiness_threshold}). "
            f"{'No blocking issues.' if not has_blocking else 'Has critical/high blocking issues.'} "
            f"Layer details: {'; '.join(basis_parts) if basis_parts else 'all layers clean.'}"
        )

        try:
            return ProductionReadinessScore(
                total_score=total_score,
                layer_scores=layer_scores,
                weights=weights,
                calculation_time=datetime.now(UTC),
                is_ready=is_ready,
                score_basis=score_basis,
            )
        except Exception as exc:
            raise ScoreCalculationError(f"Failed to build ProductionReadinessScore: {exc}") from exc

    def _score_single_layer(
        self,
        layer_id: str,
        result: LayerResult | None,
        weight: float,
        penalty_map: dict[Severity, int],
        layer_scores: list[LayerScoreEntry],
        basis_parts: list[str],
    ) -> tuple[float, bool]:
        """计算单层得分，返回 (总分增量, 是否含阻断问题)。"""
        if result is None or result.status == LayerStatus.SKIPPED:
            # F3-6：禁用一层不应等价于该层满分——否则改一行 config 即可绕过上线判定。
            # SKIPPED 不再给分且计为阻断，迫使发布方显式处理。
            layer_scores.append(
                LayerScoreEntry(
                    layer_id=layer_id,
                    score=0.0,
                    basis="Layer skipped (disabled) — treated as blocking, no score.",
                )
            )
            basis_parts.append(f"{layer_id}: SKIPPED (blocking)")
            return 0.0, True

        if result.status == LayerStatus.FAILED:
            layer_scores.append(
                LayerScoreEntry(
                    layer_id=layer_id,
                    score=0.0,
                    basis=f"Layer failed: {result.error or 'unknown error'}",
                )
            )
            basis_parts.append(f"{layer_id}: FAILED (0)")
            return 0.0, True

        # 计算扣分
        deduction = 0
        issue_count_by_severity: dict[Severity, int] = {}
        layer_blocking = False
        for issue in result.issues:
            p = penalty_map.get(issue.severity, 0)
            deduction += p
            issue_count_by_severity[issue.severity] = (
                issue_count_by_severity.get(issue.severity, 0) + 1
            )
            if issue.severity in (Severity.CRITICAL, Severity.HIGH):
                layer_blocking = True

        layer_score = max(0.0, 100.0 - deduction)
        layer_scores.append(
            LayerScoreEntry(
                layer_id=layer_id,
                score=layer_score,
                basis=(
                    f"100 - {deduction} (deduction: "
                    f"{', '.join(f'{s.value}={c}' for s, c in issue_count_by_severity.items())})"
                ),
            )
        )
        if deduction > 0:
            basis_parts.append(f"{layer_id}: {layer_score:.1f} (-{deduction})")
        return layer_score * weight, layer_blocking

    def _generate_signoff(
        self,
        run_id: str,
        layer_results: dict[str, LayerResult],
        score: ProductionReadinessScore,
    ) -> ReleaseSignOff:
        """生成上线签字单。"""
        now = datetime.now(UTC)
        layer_signoffs: list[LayerSignOffEntry] = []

        for layer_id in LAYER_ORDER:
            result = layer_results.get(layer_id)
            reviewer = self.config.get_layer(layer_id).reviewer

            if result is None:
                result_str = "conditional"
            elif result.status == LayerStatus.PASSED:
                result_str = "approved"
            elif result.status == LayerStatus.SKIPPED:
                result_str = "conditional"
            elif result.status == LayerStatus.FAILED:
                result_str = "rejected"
            else:
                result_str = "conditional"

            layer_signoffs.append(
                LayerSignOffEntry(
                    layer_id=layer_id,
                    reviewer=reviewer,
                    signed_at=now,
                    result=result_str,
                )
            )

        release_manager = self.config.get_layer("L12").reviewer
        decision = ReleaseDecision.APPROVED if score.is_ready else ReleaseDecision.REJECTED
        reason = (
            f"Total readiness score {score.total_score:.2f} >= "
            f"threshold {self.config.readiness_threshold} and no blocking issues."
            if score.is_ready
            else f"Not ready: {'score below threshold' if score.total_score < self.config.readiness_threshold else 'has blocking issues'} "
            f"(score: {score.total_score:.2f}, threshold: {self.config.readiness_threshold})."
        )

        conditions: list[str] = []
        if not score.is_ready:
            for entry in score.layer_scores:
                if entry.score < 100:
                    conditions.append(f"{entry.layer_id}: {entry.basis}")
        else:
            conditions.append("All 12 layers passed gate check.")

        try:
            return ReleaseSignOff(
                signoff_id=f"signoff-{uuid.uuid4().hex[:12]}",
                audit_run_id=run_id,
                layer_signoffs=layer_signoffs,
                release_manager=release_manager,
                release_decision=decision,
                decision_reason=reason,
                signed_at=now if score.is_ready else None,
                conditions=conditions,
            )
        except Exception as exc:
            raise SignOffGenerationError(f"Failed to build ReleaseSignOff: {exc}") from exc

    def _calculate_diff(
        self,
        layer_results: dict[str, LayerResult],
        previous_results: Sequence[LayerResult],
    ) -> AuditDiff:
        """计算与上次运行的差异。"""
        current_issue_ids: set[str] = set()
        current_issues: dict[str, AuditIssue] = {}
        for result in layer_results.values():
            for issue in result.issues:
                current_issue_ids.add(issue.issue_id)
                current_issues[issue.issue_id] = issue

        previous_issue_ids: set[str] = set()
        for result in previous_results:
            for issue in result.issues:
                previous_issue_ids.add(issue.issue_id)

        new_ids = current_issue_ids - previous_issue_ids
        fixed_ids = previous_issue_ids - current_issue_ids
        remaining_ids = current_issue_ids & previous_issue_ids

        return AuditDiff(
            new_issues=[current_issues[i] for i in sorted(new_ids)],
            fixed_issues=sorted(fixed_ids),
            remaining_issues=sorted(remaining_ids),
        )


# ---------------------------------------------------------------------------
# CLI 入口
# ---------------------------------------------------------------------------

_DEFAULT_CONFIG_PATH = "scripts/prod_audit/audit_config.yaml"
_DEFAULT_REGISTRY_PATH = "scripts/prod_audit/rules_registry.yaml"
_DEFAULT_EVIDENCE_DIR = "evidence"


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """解析 CLI 参数。"""
    parser = argparse.ArgumentParser(
        prog="python -m scripts.prod_audit.orchestrator",
        description="ERP 生产代码审核 pipeline(12 层)编排器",
    )
    parser.add_argument(
        "--config",
        type=str,
        default=_DEFAULT_CONFIG_PATH,
        help=f"审核配置文件路径(默认: {_DEFAULT_CONFIG_PATH})",
    )
    parser.add_argument(
        "--rules",
        type=str,
        default=_DEFAULT_REGISTRY_PATH,
        help=f"规则注册表文件路径(默认: {_DEFAULT_REGISTRY_PATH})",
    )
    parser.add_argument(
        "--evidence-dir",
        type=str,
        default=_DEFAULT_EVIDENCE_DIR,
        help=f"证据归档目录(默认: {_DEFAULT_EVIDENCE_DIR})",
    )
    parser.add_argument(
        "--resume-from",
        type=str,
        default=None,
        help="断点恢复层 ID(如 L4),从指定层开始执行",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """CLI 主入口。

    返回退出码:
        - 0 — 正常完成
        - 1 — 层门禁阻断
        - 2 — 配置错误
    """
    args = _parse_args(argv)

    try:
        config = ConfigLoader.load(args.config)
        rules = ConfigLoader.load_rules(args.rules)
        archiver = EvidenceArchiver(args.evidence_dir)
    except AuditConfigError as exc:
        print(f"[AuditConfigError] {exc}", file=sys.stderr)
        return 2

    orchestrator = AuditOrchestrator(config, rules, archiver)

    try:
        result = asyncio.run(orchestrator.run(resume_from=args.resume_from))
    except AuditLayerBlockedError as exc:
        print(f"[AuditLayerBlockedError] {exc}", file=sys.stderr)
        return 1
    except AuditConfigError as exc:
        print(f"[AuditConfigError] {exc}", file=sys.stderr)
        return 2
    except NotImplementedError as exc:
        print(f"[NotImplementedError] {exc}", file=sys.stderr)
        return 1

    print(
        f"Audit run '{result.audit_run_id}' completed. "
        f"Score: {result.score.total_score:.2f} "
        f"(ready: {result.score.is_ready}). "
        f"Decision: {result.signoff.release_decision.value}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
