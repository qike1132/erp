"""测试辅助函数与 mock 工具(供 conftest 与测试文件共享)。"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

# 确保项目根目录在 sys.path 中
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from scripts.prod_audit.base.issue_builder import IssueBuilder
from scripts.prod_audit.base.layer_base import (
    AuditContext,
    AuditIssue,
    LayerBase,
    LayerResult,
    LayerStatus,
    Severity,
)
from scripts.prod_audit.config_loader import AuditConfig
from scripts.prod_audit.layers import LAYER_ORDER

# ---------------------------------------------------------------------------
# 问题与结果工厂
# ---------------------------------------------------------------------------


def make_issue(
    *,
    layer_id: str = "L1",
    severity: Severity = Severity.MEDIUM,
    file: str = "test_file.py",
    line: int = 1,
    description: str = "测试问题",
    suggestion: str = "修复建议",
    rule_id: str = "L1-TEST-001",
    owner: str = "test-owner",
    due_date: str = "2026-12-31",
    builder: IssueBuilder | None = None,
) -> AuditIssue:
    """构造 :class:`AuditIssue`。"""
    b = builder or IssueBuilder()
    return b.build(
        layer_id=layer_id,
        severity=severity,
        file=file,
        line=line,
        description=description,
        suggestion=suggestion,
        rule_id=rule_id,
        owner=owner,
        due_date=due_date,
    )


def make_layer_result(
    *,
    layer_id: str = "L1",
    layer_name: str = "测试层",
    status: LayerStatus = LayerStatus.PASSED,
    issues: list[AuditIssue] | None = None,
    weight: float = 0.1,
    layer_score: float = 100.0,
    error: str | None = None,
) -> LayerResult:
    """构造 :class:`LayerResult`。"""
    now = datetime.now(UTC)
    return LayerResult(
        layer_id=layer_id,
        layer_name=layer_name,
        status=status,
        issues=issues or [],
        evidence_path=None,
        started_at=now,
        finished_at=now,
        error=error,
        layer_score=layer_score,
        weight=weight,
    )


# ---------------------------------------------------------------------------
# Mock 层执行器
# ---------------------------------------------------------------------------


class MockLayerExecutor(LayerBase):
    """可配置的 mock 层执行器,用于编排器测试。"""

    def __init__(
        self,
        *,
        layer_id: str = "L1",
        layer_name: str = "Mock Layer",
        weight: float = 0.1,
        result: LayerResult | None = None,
        issues: list[AuditIssue] | None = None,
        raise_error: Exception | None = None,
    ) -> None:
        self.layer_id = layer_id
        self.layer_name = layer_name
        self.weight = weight
        self._result = result
        self._issues = issues
        self._raise_error = raise_error
        self.run_call_count = 0

    async def run(self, context: AuditContext) -> LayerResult:
        self.run_call_count += 1
        if self._raise_error is not None:
            raise self._raise_error
        if self._result is not None:
            return self._result
        return make_layer_result(
            layer_id=self.layer_id,
            layer_name=self.layer_name,
            issues=self._issues or [],
            weight=self.weight,
        )


def build_mock_executors(
    config: AuditConfig,
    *,
    issues_per_layer: dict[str, list[AuditIssue]] | None = None,
    raise_at: str | None = None,
    raise_error: Exception | None = None,
) -> dict[str, MockLayerExecutor]:
    """为 12 层构建 mock 执行器字典。"""
    issues_per_layer = issues_per_layer or {}
    executors: dict[str, MockLayerExecutor] = {}
    for layer_id in LAYER_ORDER:
        layer_cfg = config.get_layer(layer_id)
        err = raise_error if layer_id == raise_at else None
        executors[layer_id] = MockLayerExecutor(
            layer_id=layer_id,
            layer_name=layer_cfg.layer_name,
            weight=config.get_weight(layer_id),
            issues=issues_per_layer.get(layer_id, []),
            raise_error=err,
        )
    return executors
