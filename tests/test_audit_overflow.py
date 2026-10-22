"""M10：审计写库失败必须可观测（指标 + 本地溢出文件），不能静默丢弃。"""
import json

import pytest

from fastapi_app.core import audit_middleware


@pytest.mark.asyncio
async def test_db_failure_writes_overflow(monkeypatch, tmp_path):
    overflow = tmp_path / "audit_overflow.jsonl"
    monkeypatch.setattr(audit_middleware, "_OVERFLOW_PATH", overflow)
    monkeypatch.setattr(audit_middleware, "_get_audit_session_factory", lambda: None)

    ok = await audit_middleware._write_audit_direct([
        {"action": "CREATE", "resource_type": "order", "resource_id": "1"}
    ])

    assert ok is False
    lines = overflow.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["resource_type"] == "order"


def test_overflow_file_is_covered_by_log_rotation():
    """溢出文件必须是 *.log，否则 utils.log_rotation 的 *.log glob 管不到它。"""
    assert audit_middleware._OVERFLOW_PATH.suffix == ".log"


@pytest.mark.asyncio
async def test_redis_fallback_counts_redis_stage(monkeypatch):
    stages = []

    async def _rpush(*args, **kwargs):
        return 0  # 缓冲写不进去 → 走直写兜底

    async def _direct(entries):
        return True

    monkeypatch.setattr("fastapi_app.core.redis_wrapper.safe_rpush", _rpush)
    monkeypatch.setattr(audit_middleware, "_write_audit_direct", _direct)
    monkeypatch.setattr(
        audit_middleware, "_inc_audit_write_failure", lambda stage: stages.append(stage)
    )

    await audit_middleware._buffer_audit_entries([
        {"action": "CREATE", "resource_type": "order", "resource_id": "1"}
    ])

    assert "redis" in stages
