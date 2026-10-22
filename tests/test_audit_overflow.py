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
