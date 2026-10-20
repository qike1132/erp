"""P1-7：损坏/改名的 .xlsx 必须返回友好解析错误，而不是 500。"""
from __future__ import annotations

from pathlib import Path

import pytest

from fastapi_app.services.batch_import_parser import (
    _bad_xlsx_message,
    parse_excel_file_async,
    read_excel_sheets_async,
)

_REPO = Path(__file__).resolve().parents[2]
_SERVICE = _REPO / 'fastapi_app' / 'services' / 'batch_import_service.py'
_FAKE = b'not a zip at all'
_TRUNCATED = b'PK\x03\x04' + b'\x00' * 20


def _write(tmp_path: Path, name: str, data: bytes) -> str:
    path = tmp_path / name
    path.write_bytes(data)
    return str(path)


@pytest.mark.parametrize('func', [parse_excel_file_async, read_excel_sheets_async])
async def test_fake_xlsx_is_rejected_before_parser(tmp_path: Path, func) -> None:
    ok, data, err = await func(_write(tmp_path, 'fake.xlsx', _FAKE))

    assert ok is False
    assert data == []
    assert err == _bad_xlsx_message()


@pytest.mark.parametrize('func', [parse_excel_file_async, read_excel_sheets_async])
async def test_truncated_zip_is_caught(tmp_path: Path, func) -> None:
    ok, data, err = await func(_write(tmp_path, 'truncated.xlsx', _TRUNCATED))

    assert ok is False
    assert data == []
    assert err  # 具体文案来自 openpyxl/fastexcel，关键是不让异常穿透成 500


def test_service_import_paths_catch_bad_zip() -> None:
    src = _SERVICE.read_text(encoding='utf-8')

    assert 'except (OSError, ValueError) as exc:' not in src
    assert 'except (OSError, ValueError, BadZipFile) as exc:' in src
