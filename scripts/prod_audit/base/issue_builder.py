"""问题构造器,自动生成唯一 ``issue_id``。

``issue_id`` 格式为 ``L{层号}-{3位序号}``(如 ``L3-001``),
层内序号自增,保证同层内唯一。
"""

from __future__ import annotations

from datetime import date

from scripts.prod_audit.base.layer_base import AuditIssue, IssueStatus, RetestResult, Severity


class IssueBuilder:
    """构造 :class:`AuditIssue` 并自动分配 ``issue_id``。

    每个 :class:`IssueBuilder` 实例维护一个 ``layer_id → 序号`` 的计数器,
    同层连续调用 ``build`` 时序号自增。

    使用示例::

        builder = IssueBuilder()
        issue = builder.build(
            layer_id="L3",
            severity=Severity.HIGH,
            file="fastapi_app/services/order_service.py",
            line=42,
            description="循环内执行数据库查询",
            suggestion="改为批量查询或使用 IN 子句",
            rule_id="L3-LOOP-QUERY-001",
            owner="zhang_san",
            due_date="2026-09-01",
        )
        assert issue.issue_id == "L3-001"
    """

    def __init__(self) -> None:
        self._counters: dict[str, int] = {}

    def build(
        self,
        *,
        layer_id: str,
        severity: Severity,
        file: str,
        line: int,
        description: str,
        suggestion: str,
        rule_id: str,
        owner: str,
        due_date: str | date,
        status: IssueStatus = IssueStatus.OPEN,
        linked_pr: str | None = None,
        retest_result: RetestResult = RetestResult.PENDING,
    ) -> AuditIssue:
        """构造 :class:`AuditIssue`,自动生成 ``issue_id``。

        参数:
            layer_id: 所属审核层 ID(如 ``"L3"``)
            severity: 严重度
            file: 问题所在文件路径
            line: 问题所在行号(≥ 1)
            description: 问题描述
            suggestion: 修复建议
            rule_id: 关联规则 ID
            owner: 责任研发
            due_date: 修复期限(ISO 日期字符串或 ``date`` 对象)
            status: 修复状态,默认 :attr:`IssueStatus.OPEN`
            linked_pr: 关联修复 PR,默认 ``None``
            retest_result: 复测结果,默认 :attr:`RetestResult.PENDING`

        返回:
            构造好的 :class:`AuditIssue`
        """
        seq = self._counters.get(layer_id, 0) + 1
        self._counters[layer_id] = seq
        issue_id = f"{layer_id}-{seq:03d}"

        due_date_str = due_date.isoformat() if isinstance(due_date, date) else due_date

        return AuditIssue(
            issue_id=issue_id,
            layer_id=layer_id,
            severity=severity,
            file=file,
            line=line,
            description=description,
            suggestion=suggestion,
            rule_id=rule_id,
            owner=owner,
            due_date=due_date_str,
            status=status,
            linked_pr=linked_pr,
            retest_result=retest_result,
        )

    def reset(self, layer_id: str | None = None) -> None:
        """重置序号计数器。

        参数:
            layer_id: 指定层 ID 则仅重置该层计数器;``None`` 则重置所有层
        """
        if layer_id is None:
            self._counters.clear()
        else:
            self._counters.pop(layer_id, None)

    def current_seq(self, layer_id: str) -> int:
        """返回指定层当前已分配的最大序号(未分配则返回 0)。"""
        return self._counters.get(layer_id, 0)
