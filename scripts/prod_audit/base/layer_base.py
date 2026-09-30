"""审核层执行器基类与公共数据模型。

定义所有层执行器共享的枚举、数据模型与抽象基类。
严禁使用 ``Any`` 类型;所有字段使用强类型标注。
"""

from __future__ import annotations

import enum
from abc import ABC, abstractmethod
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    pass


# ---------------------------------------------------------------------------
# 枚举定义(禁止字符串字面量)
# ---------------------------------------------------------------------------


class Severity(enum.Enum):
    """问题严重度。"""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class LayerStatus(enum.Enum):
    """审核层执行状态。"""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    PASSED = "passed"
    FAILED = "failed"
    BLOCKED = "blocked"
    SKIPPED = "skipped"


class IssueStatus(enum.Enum):
    """问题修复状态。"""

    OPEN = "open"
    IN_PROGRESS = "in_progress"
    FIXED = "fixed"
    VERIFIED = "verified"
    WONTFIX = "wontfix"


class RetestResult(enum.Enum):
    """复测结果。"""

    PASS = "pass"
    FAIL = "fail"
    PENDING = "pending"


class ReleaseDecision(enum.Enum):
    """上线决策。"""

    APPROVED = "approved"
    REJECTED = "rejected"


class EvidenceType(enum.Enum):
    """证据类型,对应 ``evidence/`` 子目录。"""

    CONTRACT_SNAPSHOT = "contract_snapshots"
    PERF_REPORT = "perf_reports"
    COVERAGE_REPORT = "coverage_reports"
    SECURITY_REPORT = "security_reports"
    MANUAL_REVIEW = "manual_reviews"
    GATE_LOG = "gate_logs"


# 阻断上线的严重度集合(check_gate 使用)
BLOCKING_SEVERITIES: frozenset[Severity] = frozenset({Severity.CRITICAL, Severity.HIGH})


# ---------------------------------------------------------------------------
# 数据模型
# ---------------------------------------------------------------------------


class AuditIssue(BaseModel):
    """审核问题。

    ``issue_id`` 格式为 ``L{层号}-{3位序号}``,如 ``L3-001``,
    由 :class:`IssueBuilder` 自动生成。
    """

    issue_id: str = Field(description="问题唯一标识,格式 L{层号}-{3位序号}")
    layer_id: str = Field(description="所属审核层 ID")
    severity: Severity = Field(description="严重度")
    file: str = Field(description="问题所在文件路径")
    line: int = Field(ge=1, description="问题所在行号")
    description: str = Field(description="问题描述")
    suggestion: str = Field(description="修复建议")
    rule_id: str = Field(description="关联规则 ID")
    owner: str = Field(description="责任研发")
    due_date: str = Field(description="修复期限(ISO 日期)")
    status: IssueStatus = Field(default=IssueStatus.OPEN, description="修复状态")
    linked_pr: str | None = Field(default=None, description="关联修复 PR")
    retest_result: RetestResult = Field(
        default=RetestResult.PENDING, description="复测结果"
    )


class LayerResult(BaseModel):
    """单层审核执行结果。"""

    layer_id: str = Field(description="层 ID")
    layer_name: str = Field(description="层名称")
    status: LayerStatus = Field(description="执行状态")
    issues: list[AuditIssue] = Field(default_factory=list, description="发现问题列表")
    evidence_path: str | None = Field(default=None, description="证据归档路径")
    started_at: datetime = Field(description="开始时间")
    finished_at: datetime | None = Field(default=None, description="完成时间")
    error: str | None = Field(default=None, description="执行错误信息")
    layer_score: float | None = Field(
        default=None, ge=0, le=100, description="层得分(0-100)"
    )
    weight: float = Field(ge=0, le=1, description="层权重")


class AuditState(BaseModel):
    """审核运行状态(支持断点恢复)。

    持久化至 ``evidence/audit_state.json``,每层完成后更新。
    """

    audit_run_id: str = Field(description="审核运行唯一标识")
    current_layer: str | None = Field(
        default=None, description="当前正在执行或即将执行的层 ID"
    )
    layer_states: dict[str, LayerResult] = Field(
        default_factory=dict, description="各层状态快照,key 为 layer_id"
    )
    started_at: datetime = Field(description="运行开始时间")
    last_updated: datetime = Field(description="最后更新时间")


class AuditContext(BaseModel):
    """审核执行上下文,传递给每层执行器。

    ``archiver`` 为运行时对象(非 pydantic 字段),通过 ``model_config``
    允许任意类型。此处使用 ``object`` 占位并在运行时注入
    :class:`EvidenceArchiver` 实例。
    """

    model_config = {"arbitrary_types_allowed": True}

    config: object = Field(description="AuditConfig 实例")
    rules: object = Field(description="RulesRegistry 实例")
    archiver: object = Field(description="EvidenceArchiver 实例")
    baseline_dir: Path = Field(description="基线证据目录")
    previous_results: list[LayerResult] = Field(
        default_factory=list, description="上次运行的各层结果(用于 diff)"
    )


# ---------------------------------------------------------------------------
# 抽象基类
# ---------------------------------------------------------------------------


class LayerBase(ABC):
    """层执行器抽象基类。

    所有 12 层执行器(L1~L12)继承本类并实现 :meth:`run` 方法。

    属性:
        layer_id: 层唯一标识(如 ``"L1"``)
        layer_name: 层名称
        weight: 层权重(0-1)
    """

    layer_id: str
    layer_name: str
    weight: float

    @abstractmethod
    async def run(self, context: AuditContext) -> LayerResult:
        """执行本层审核逻辑,返回 :class:`LayerResult`。

        参数:
            context: 审核执行上下文

        返回:
            本层审核结果
        """
        ...

    def check_gate(self, issues: Sequence[AuditIssue], threshold: Severity) -> bool:
        """门禁检查:校验 issues 中不存在 >= threshold 严重度的问题。

        参数:
            issues: 本层发现的问题列表
            threshold: 阻断阈值严重度(如 ``Severity.HIGH`` 表示
                存在 critical 或 high 问题则门禁失败)

        返回:
            ``True`` 表示门禁通过(无阻断问题);
            ``False`` 表示门禁失败(存在阻断问题)
        """
        blocking_levels = _severity_levels_at_or_above(threshold)
        return all(_severity_level(issue.severity) < blocking_levels for issue in issues)


# ---------------------------------------------------------------------------
# 严重度排序辅助
# ---------------------------------------------------------------------------

_SEVERITY_ORDER: dict[Severity, int] = {
    Severity.INFO: 0,
    Severity.LOW: 1,
    Severity.MEDIUM: 2,
    Severity.HIGH: 3,
    Severity.CRITICAL: 4,
}


def _severity_level(severity: Severity) -> int:
    """返回严重度对应的排序值。"""
    return _SEVERITY_ORDER[severity]


def _severity_levels_at_or_above(threshold: Severity) -> int:
    """返回阈值严重度对应的排序值(含该级别及以上均阻断)。"""
    return _severity_level(threshold)
