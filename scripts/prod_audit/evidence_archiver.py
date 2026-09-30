"""证据归档器。

负责将各层审核证据归档至 ``evidence/`` 对应子目录,
对含敏感信息的内容进行脱敏,并持久化/加载审核运行状态以支持断点恢复。

证据子目录:
    - ``contract_snapshots/``  — API 契约快照
    - ``perf_reports/``        — 性能报告
    - ``coverage_reports/``    — 覆盖率报告
    - ``security_reports/``    — 安全扫描报告
    - ``manual_reviews/``      — 人工审核记录
    - ``gate_logs/``           — 门禁日志
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

from scripts.prod_audit.base.layer_base import AuditState, EvidenceType
from scripts.prod_audit.exceptions import EvidenceArchiveError

# ---------------------------------------------------------------------------
# 脱敏正则模式
# ---------------------------------------------------------------------------

# 敏感字段名(不区分大小写)
_SENSITIVE_KEYS = (
    r"password|passwd|pwd|secret|token|api[_-]?key|apikey|"
    r"database[_-]?url|dsn|access[_-]?key|private[_-]?key"
)

# 1. 引号包裹的值:key="value" / key: "value" / key='value'
_QUOTED_VALUE_PATTERN = re.compile(
    rf"(?i)\b({_SENSITIVE_KEYS})\b(\s*[:=]\s*)([\"'])([^\"']*?)(\3)"
)

# 2. 裸值:key=value / key: value(排除引号开头,避免与模式 1 重复匹配)
_BARE_VALUE_PATTERN = re.compile(
    rf"(?i)\b({_SENSITIVE_KEYS})\b(\s*[:=]\s*)(?!['\"])([^\s,;)}}\]]+)"
)

# 3. URL 内嵌凭证:scheme://user:password@host
_URL_CRED_PATTERN = re.compile(
    r"([a-zA-Z][a-zA-Z0-9+.-]*://)([^:@/\s]+):([^@/\s]+)@"
)

# 4. JSON 键值对:"key": "value"  或  "key": value
_JSON_QUOTED_PATTERN = re.compile(
    rf'(?i)("({_SENSITIVE_KEYS})"\\s*:\\s*)(["\'])([^"\']*?)(\\3)'
)
_JSON_BARE_PATTERN = re.compile(
    rf'(?i)("({_SENSITIVE_KEYS})"\\s*:\\s*)(?!["\'])([^\\s,}}\\]]+)'
)


# ---------------------------------------------------------------------------
# 证据子目录映射
# ---------------------------------------------------------------------------

_EVIDENCE_SUBDIRS: dict[EvidenceType, str] = {
    EvidenceType.CONTRACT_SNAPSHOT: "contract_snapshots",
    EvidenceType.PERF_REPORT: "perf_reports",
    EvidenceType.COVERAGE_REPORT: "coverage_reports",
    EvidenceType.SECURITY_REPORT: "security_reports",
    EvidenceType.MANUAL_REVIEW: "manual_reviews",
    EvidenceType.GATE_LOG: "gate_logs",
}

_STATE_FILENAME: str = "audit_state.json"


# ---------------------------------------------------------------------------
# EvidenceArchiver
# ---------------------------------------------------------------------------


class EvidenceArchiver:
    """证据归档器。

    参数:
        evidence_dir: 证据根目录(``evidence/``)

    使用示例::

        archiver = EvidenceArchiver(Path("scripts/prod_audit/evidence"))
        path = await archiver.archive(
            layer_id="L1",
            evidence_type=EvidenceType.GATE_LOG,
            content="gate check passed",
            filename="L1_gate.txt",
        )
    """

    def __init__(self, evidence_dir: str | Path) -> None:
        self.evidence_dir: Path = Path(evidence_dir)
        self._ensure_subdirs()

    def _ensure_subdirs(self) -> None:
        """创建证据根目录及所有子目录。"""
        try:
            self.evidence_dir.mkdir(parents=True, exist_ok=True)
            for subdir in _EVIDENCE_SUBDIRS.values():
                (self.evidence_dir / subdir).mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise EvidenceArchiveError(
                f"Failed to create evidence directories at '{self.evidence_dir}': {exc}"
            ) from exc

    def subdir(self, evidence_type: EvidenceType) -> Path:
        """返回指定证据类型对应的子目录路径。"""
        return self.evidence_dir / _EVIDENCE_SUBDIRS[evidence_type]

    async def archive(
        self,
        *,
        layer_id: str,
        evidence_type: EvidenceType,
        content: bytes | str,
        filename: str,
    ) -> Path:
        """归档证据至对应子目录。

        参数:
            layer_id: 所属层 ID(用于日志,不参与路径)
            evidence_type: 证据类型(决定子目录)
            content: 证据内容(``str`` 会先脱敏再写入;``bytes`` 原样写入)
            filename: 文件名

        返回:
            归档文件路径

        抛出:
            EvidenceArchiveError: 归档失败或脱敏失败
        """
        target_dir = self.subdir(evidence_type)
        target_path = target_dir / filename

        try:
            target_path.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(content, str):
                sanitized = self.sanitize(content)
                target_path.write_text(sanitized, encoding="utf-8")
            else:
                target_path.write_bytes(content)
        except EvidenceArchiveError:
            raise
        except OSError as exc:
            raise EvidenceArchiveError(
                f"Failed to archive evidence for layer {layer_id} to '{target_path}': {exc}"
            ) from exc
        except Exception as exc:
            raise EvidenceArchiveError(
                f"Failed to sanitize content for layer {layer_id}: {exc}"
            ) from exc

        return target_path

    @staticmethod
    def sanitize(content: str) -> str:
        """脱敏处理:将敏感信息替换为 ``[REDACTED]``。

        覆盖模式:
            - ``password=xxx`` / ``password: xxx`` / ``password: "xxx"``
            - ``secret`` / ``token`` / ``api_key`` / ``apikey``
            - ``DATABASE_URL`` / ``dsn`` / ``access_key`` / ``private_key``
            - URL 内嵌凭证 ``scheme://user:pass@host``
            - JSON 键值对 ``"password": "xxx"``

        参数:
            content: 原始内容

        返回:
            脱敏后的内容

        抛出:
            EvidenceArchiveError: 脱敏处理异常
        """
        try:
            result = content

            # 1. 引号包裹的值:key="value" / key: 'value'
            result = _QUOTED_VALUE_PATTERN.sub(r"\1\2\3[REDACTED]\5", result)

            # 2. 裸值:key=value / key: value (先于 URL, 避免值中 URL 干扰)
            result = _BARE_VALUE_PATTERN.sub(r"\1\2[REDACTED]", result)

            # 3. URL 内嵌凭证:scheme://user:password@host → scheme://user:[REDACTED]@
            result = _URL_CRED_PATTERN.sub(r"\1\2:[REDACTED]@", result)

            return result
        except re.error as exc:
            raise EvidenceArchiveError(f"Sanitize regex error: {exc}") from exc
        except Exception as exc:
            raise EvidenceArchiveError(f"Sanitize failed: {exc}") from exc

    async def save_state(self, state: AuditState) -> None:
        """持久化审核运行状态至 ``evidence/audit_state.json``。

        参数:
            state: 审核运行状态

        抛出:
            EvidenceArchiveError: 写入失败
        """
        state_path = self.evidence_dir / _STATE_FILENAME
        try:
            state.last_updated = datetime.now(UTC)
            state_path.write_text(state.model_dump_json(indent=2), encoding="utf-8")
        except OSError as exc:
            raise EvidenceArchiveError(
                f"Failed to save audit state to '{state_path}': {exc}"
            ) from exc
        except Exception as exc:
            raise EvidenceArchiveError(f"Failed to serialize audit state: {exc}") from exc

    async def load_state(self) -> AuditState | None:
        """从 ``evidence/audit_state.json`` 加载审核运行状态。

        返回:
            :class:`AuditState` 或 ``None``(文件不存在时)

        抛出:
            EvidenceArchiveError: 文件存在但解析失败
        """
        state_path = self.evidence_dir / _STATE_FILENAME
        if not state_path.exists():
            return None

        try:
            raw = state_path.read_text(encoding="utf-8")
            return AuditState.model_validate_json(raw)
        except OSError as exc:
            raise EvidenceArchiveError(
                f"Failed to read audit state from '{state_path}': {exc}"
            ) from exc
        except Exception as exc:
            raise EvidenceArchiveError(
                f"Failed to parse audit state from '{state_path}': {exc}"
            ) from exc

    async def clear_state(self) -> None:
        """删除审核运行状态文件(若存在)。"""
        state_path = self.evidence_dir / _STATE_FILENAME
        if state_path.exists():
            try:
                state_path.unlink()
            except OSError as exc:
                raise EvidenceArchiveError(
                    f"Failed to clear audit state at '{state_path}': {exc}"
                ) from exc
