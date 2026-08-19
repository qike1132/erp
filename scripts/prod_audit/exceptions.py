"""审核 pipeline 自定义异常。

所有异常在此统一定义,避免 ``orchestrator`` ↔ ``config_loader`` /
``evidence_archiver`` 之间的循环导入。``orchestrator`` 模块会重新导出本模块
的全部异常。

退出码约定:
    - ``AuditConfigError`` → 退出码 2
    - ``AuditLayerBlockedError`` → 退出码 1
    - 正常完成 → 退出码 0
"""

from __future__ import annotations


class AuditError(Exception):
    """所有审核异常的基类。"""


class AuditConfigError(AuditError):
    """配置错误(文件不存在 / 格式非法 / Σweight ≠ 1 等)。

    对应退出码 2。
    """


class AuditLayerBlockedError(AuditError):
    """层门禁阻断错误(存在 critical/high 问题,不进入下一层)。

    对应退出码 1。携带 ``layer_id`` 与阻断问题列表。
    """

    def __init__(self, layer_id: str, issues_summary: str) -> None:
        self.layer_id = layer_id
        self.issues_summary = issues_summary
        super().__init__(f"Layer {layer_id} blocked: {issues_summary}")


class EvidenceArchiveError(AuditError):
    """证据归档错误(归档失败 / 脱敏失败)。"""


class ScoreCalculationError(AuditError):
    """评分计算错误。"""


class SignOffGenerationError(AuditError):
    """签字单生成错误。"""
