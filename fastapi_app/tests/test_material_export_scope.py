"""P1-25：来料导出按页面 tab 口径过滤（history=completed / progress=非 completed）。"""
from __future__ import annotations

from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from fastapi_app.api.v1.endpoints import material_registration as ep
from fastapi_app.schemas.material_registration import ExportRequest
from fastapi_app.services.material_registration._export import _apply_export_scope
from fastapi_app.shared_models import MaterialRegistration


def _where_sql(scope: str) -> str:
    stmt = _apply_export_scope(select(MaterialRegistration), scope)
    sql = str(stmt.compile(dialect=postgresql.dialect(), compile_kwargs={'literal_binds': True}))
    return sql.split('WHERE', 1)[1] if 'WHERE' in sql else ''


def test_schema_accepts_scope_and_rejects_unknown() -> None:
    assert ExportRequest(scope='history').scope == 'history'
    with pytest.raises(ValidationError):
        ExportRequest(scope='bogus')


def test_history_scope_filters_completed() -> None:
    assert "status = 'completed'" in _where_sql('history')


def test_progress_scope_excludes_completed() -> None:
    assert "status != 'completed'" in _where_sql('progress')


def test_all_scope_has_no_status_filter() -> None:
    assert 'status' not in _where_sql('all').lower()


async def test_endpoint_forwards_scope(monkeypatch) -> None:
    svc = AsyncMock(return_value=BytesIO(b'x'))
    monkeypatch.setattr(ep.mr_service, 'export_registrations', svc)

    await ep.export_registrations(
        data=ExportRequest(scope='history'), user=SimpleNamespace(), db=AsyncMock(),
    )

    svc.assert_awaited_once()
    assert svc.await_args.args[-1] == 'history'
