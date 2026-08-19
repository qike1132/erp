"""Group 15.3 — 证据归档器测试。

测试内容:
    - archive() 创建文件至正确子目录
    - sanitize() 各种敏感模式脱敏
    - save_state/load_state 一致性
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from scripts.prod_audit.base.layer_base import (
    AuditState,
    EvidenceType,
)
from scripts.prod_audit.evidence_archiver import EvidenceArchiver
from scripts.prod_audit.tests._helpers import make_layer_result

# ---------------------------------------------------------------------------
# 15.3a archive() 子目录
# ---------------------------------------------------------------------------


class TestArchiveSubdirectories:
    """archive() 将文件写入正确子目录。"""

    @pytest.mark.parametrize(
        "evidence_type,subdir",
        [
            (EvidenceType.CONTRACT_SNAPSHOT, "contract_snapshots"),
            (EvidenceType.PERF_REPORT, "perf_reports"),
            (EvidenceType.COVERAGE_REPORT, "coverage_reports"),
            (EvidenceType.SECURITY_REPORT, "security_reports"),
            (EvidenceType.MANUAL_REVIEW, "manual_reviews"),
            (EvidenceType.GATE_LOG, "gate_logs"),
        ],
    )
    async def test_archive_creates_file_in_subdir(
        self,
        archiver: EvidenceArchiver,
        evidence_dir: Path,
        evidence_type: EvidenceType,
        subdir: str,
    ) -> None:
        """archive() 在对应子目录创建文件。"""
        path = await archiver.archive(
            layer_id="L1",
            evidence_type=evidence_type,
            content="test content",
            filename="test.txt",
        )
        assert path == evidence_dir / subdir / "test.txt"
        assert path.exists()
        assert path.read_text(encoding="utf-8") == "test content"

    async def test_archive_bytes_content(
        self,
        archiver: EvidenceArchiver,
        evidence_dir: Path,
    ) -> None:
        """bytes 内容原样写入(不脱敏)。"""
        content = b"\x89PNG\r\n\x1a\n"
        path = await archiver.archive(
            layer_id="L1",
            evidence_type=EvidenceType.PERF_REPORT,
            content=content,
            filename="report.png",
        )
        assert path.read_bytes() == content

    async def test_archive_str_content_sanitized(
        self,
        archiver: EvidenceArchiver,
        evidence_dir: Path,
    ) -> None:
        """str 内容脱敏后写入。"""
        path = await archiver.archive(
            layer_id="L1",
            evidence_type=EvidenceType.GATE_LOG,
            content='password = "secret123"',
            filename="gate.log",
        )
        written = path.read_text(encoding="utf-8")
        assert "secret123" not in written
        assert "[REDACTED]" in written

    async def test_archive_overwrites_existing(
        self,
        archiver: EvidenceArchiver,
    ) -> None:
        """同名文件覆盖。"""
        await archiver.archive(
            layer_id="L1",
            evidence_type=EvidenceType.GATE_LOG,
            content="old",
            filename="log.txt",
        )
        path = await archiver.archive(
            layer_id="L1",
            evidence_type=EvidenceType.GATE_LOG,
            content="new",
            filename="log.txt",
        )
        assert path.read_text(encoding="utf-8") == "new"

    def test_subdir_method_returns_correct_path(
        self,
        archiver: EvidenceArchiver,
        evidence_dir: Path,
    ) -> None:
        """subdir() 返回正确路径。"""
        assert archiver.subdir(EvidenceType.GATE_LOG) == evidence_dir / "gate_logs"
        assert archiver.subdir(EvidenceType.PERF_REPORT) == evidence_dir / "perf_reports"


# ---------------------------------------------------------------------------
# 15.3b sanitize() 敏感模式
# ---------------------------------------------------------------------------


class TestSanitizePatterns:
    """sanitize() 各种敏感模式。"""

    def test_quoted_double_value(self) -> None:
        """key="value" 脱敏。"""
        result = EvidenceArchiver.sanitize('password = "my_secret"')
        assert "my_secret" not in result
        assert "[REDACTED]" in result

    def test_quoted_single_value(self) -> None:
        """key='value' 脱敏。"""
        result = EvidenceArchiver.sanitize("password = 'my_secret'")
        assert "my_secret" not in result
        assert "[REDACTED]" in result

    def test_bare_value(self) -> None:
        """key=value 脱敏。"""
        result = EvidenceArchiver.sanitize("api_key=ABC123")
        assert "ABC123" not in result
        assert "[REDACTED]" in result

    def test_colon_separator(self) -> None:
        """key: value 脱敏。"""
        result = EvidenceArchiver.sanitize("token: my_token_value")
        assert "my_token_value" not in result
        assert "[REDACTED]" in result

    def test_url_with_credentials(self) -> None:
        """URL 内嵌凭证脱敏。"""
        result = EvidenceArchiver.sanitize(
            "postgres://user:password123@host:5432/db"
        )
        assert "password123" not in result
        assert "[REDACTED]" in result

    def test_database_url(self) -> None:
        """DATABASE_URL 脱敏。"""
        result = EvidenceArchiver.sanitize(
            "DATABASE_URL=postgres://admin:secret@localhost/mydb"
        )
        assert "secret" not in result

    def test_no_false_positive_for_normal_text(self) -> None:
        """普通文本不误脱敏。"""
        raw = "The quick brown fox jumps over the lazy dog."
        result = EvidenceArchiver.sanitize(raw)
        assert result == raw

    def test_preserves_structure(self) -> None:
        """脱敏保留键名结构。"""
        result = EvidenceArchiver.sanitize('password = "secret"')
        assert "password" in result
        assert "=" in result


# ---------------------------------------------------------------------------
# 15.3c save_state / load_state 一致性
# ---------------------------------------------------------------------------


class TestStatePersistence:
    """save_state / load_state 一致性。"""

    async def test_round_trip_single_layer(
        self,
        archiver: EvidenceArchiver,
    ) -> None:
        """单层状态往返一致。"""
        now = datetime.now(UTC)
        result = make_layer_result(layer_id="L3", layer_name="业务逻辑")
        state = AuditState(
            audit_run_id="audit-abc",
            current_layer="L3",
            layer_states={"L3": result},
            started_at=now,
            last_updated=now,
        )
        await archiver.save_state(state)
        loaded = await archiver.load_state()

        assert loaded is not None
        assert loaded.audit_run_id == "audit-abc"
        assert loaded.current_layer == "L3"
        assert "L3" in loaded.layer_states
        assert loaded.layer_states["L3"].layer_id == "L3"
        assert loaded.layer_states["L3"].layer_name == "业务逻辑"

    async def test_round_trip_multiple_layers(
        self,
        archiver: EvidenceArchiver,
    ) -> None:
        """多层状态往返一致。"""
        now = datetime.now(UTC)
        results = {
            "L1": make_layer_result(layer_id="L1", layer_name="静态分析"),
            "L2": make_layer_result(layer_id="L2", layer_name="架构"),
            "L3": make_layer_result(layer_id="L3", layer_name="业务逻辑"),
        }
        state = AuditState(
            audit_run_id="audit-multi",
            current_layer="L3",
            layer_states=results,
            started_at=now,
            last_updated=now,
        )
        await archiver.save_state(state)
        loaded = await archiver.load_state()

        assert loaded is not None
        assert len(loaded.layer_states) == 3
        for layer_id in ("L1", "L2", "L3"):
            assert layer_id in loaded.layer_states
            assert loaded.layer_states[layer_id].layer_id == layer_id

    async def test_load_state_none_when_no_file(
        self,
        archiver: EvidenceArchiver,
    ) -> None:
        """无文件时 load_state 返回 None。"""
        assert await archiver.load_state() is None

    async def test_clear_state_removes_file(
        self,
        archiver: EvidenceArchiver,
    ) -> None:
        """clear_state 删除状态文件。"""
        now = datetime.now(UTC)
        state = AuditState(
            audit_run_id="audit-clear",
            current_layer="L1",
            layer_states={},
            started_at=now,
            last_updated=now,
        )
        await archiver.save_state(state)
        assert await archiver.load_state() is not None

        await archiver.clear_state()
        assert await archiver.load_state() is None

    async def test_clear_state_no_file_is_noop(
        self,
        archiver: EvidenceArchiver,
    ) -> None:
        """无文件时 clear_state 不报错。"""
        await archiver.clear_state()  # 不应抛异常

    async def test_save_state_updates_last_updated(
        self,
        archiver: EvidenceArchiver,
    ) -> None:
        """save_state 更新 last_updated。"""
        old_time = datetime(2020, 1, 1, tzinfo=UTC)
        result = make_layer_result(layer_id="L1")
        state = AuditState(
            audit_run_id="audit-time",
            current_layer="L1",
            layer_states={"L1": result},
            started_at=old_time,
            last_updated=old_time,
        )
        await archiver.save_state(state)
        loaded = await archiver.load_state()

        assert loaded is not None
        assert loaded.last_updated > old_time


# ---------------------------------------------------------------------------
# 15.3d 证据目录结构
# ---------------------------------------------------------------------------


class TestEvidenceDirectoryStructure:
    """证据目录结构。"""

    def test_all_subdirs_created(self, archiver: EvidenceArchiver, evidence_dir: Path) -> None:
        """所有子目录被创建。"""
        expected = [
            "contract_snapshots",
            "perf_reports",
            "coverage_reports",
            "security_reports",
            "manual_reviews",
            "gate_logs",
        ]
        for subdir in expected:
            assert (evidence_dir / subdir).exists()
            assert (evidence_dir / subdir).is_dir()
