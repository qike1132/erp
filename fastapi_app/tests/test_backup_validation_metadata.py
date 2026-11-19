"""备份校验接口的元数据提取（P2-4，2026-10-17 审计备份区）。

`_extract_backup_metadata` 是「选中/上传备份后先给用户看摘要」的唯一入口：表数、行数、
导出时间。此前 JSON 分支数的是 ``table_data['data']`` —— 而 JSON 备份从不产出 ``data`` 键
（导出侧写 ``columns``/``rows``/``count``，见 ``json_backup.execute_legacy_backup_to_bytes``），
于是 ``total_rows`` 恒为 0：一个装了 12 万行的备份在预览里显示「0 行」，
用户据以判断「这包是空的」——灾备可信度直接失真。
"""
from __future__ import annotations

import io
import json
import zipfile

from fastapi_app.api.v1.endpoints.backup.validation import _extract_backup_metadata


def _json_bytes(tables: dict) -> bytes:
    return json.dumps({
        'version': '1.0',
        'exported_at': '2026-11-19 10:00:00',
        'tables': tables,
    }).encode('utf-8')


def test_json_total_rows_prefers_count() -> None:
    """有 ``count`` 时以它为准（导出侧已经算过，不必再数 rows）。"""
    content = _json_bytes({
        'product': {'columns': ['id'], 'count': 120000, 'rows': [{'id': 1}]},
    })

    fmt, table_count, total_rows, created_at = _extract_backup_metadata(
        content, 'erp_backup_20261119.json'
    )

    assert fmt == '1.0'
    assert table_count == 1
    assert total_rows == 120000
    assert created_at == '2026-11-19 10:00:00'


def test_json_total_rows_falls_back_to_row_length() -> None:
    """没有 ``count`` 时按 ``rows`` 长度算 —— 这是「不能恒为 0」的底线。"""
    content = _json_bytes({
        'customer': {'columns': ['id'], 'rows': [{'id': 1}, {'id': 2}, {'id': 3}]},
    })

    _fmt, _tc, total_rows, _created = _extract_backup_metadata(content, 'x.json')

    assert total_rows == 3


def test_json_total_rows_sums_all_tables() -> None:
    content = _json_bytes({
        'a': {'count': 5, 'rows': []},
        'b': {'rows': [1, 2]},
        'c': {'error': 'read timeout', 'count': 0, 'rows': []},
    })

    _fmt, table_count, total_rows, _created = _extract_backup_metadata(content, 'x.json')

    assert table_count == 3
    assert total_rows == 7, '导出失败的表按 0 计，但不能让整包行数算错'


def test_zip_manifest_total_rows_still_used() -> None:
    """ZIP 分支取 manifest.total_rows（回归：改 JSON 分支不能影响它）。"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as zf:
        zf.writestr('manifest.json', json.dumps({
            'format_version': '2.0', 'table_count': 4, 'total_rows': 9876,
            'exported_at': '2026-11-19 09:00:00',
        }))

    fmt, table_count, total_rows, created_at = _extract_backup_metadata(buf.getvalue(), 'b.zip')

    assert (fmt, table_count, total_rows, created_at) == ('2.0', 4, 9876, '2026-11-19 09:00:00')


def test_corrupt_payload_yields_none_without_raising() -> None:
    """元数据提取失败不能打断校验主流程（返回全 None，由调用方按「未知」展示）。"""
    fmt, table_count, total_rows, created_at = _extract_backup_metadata(
        b'{not json', 'broken.json'
    )

    assert (fmt, table_count, total_rows, created_at) == (None, None, None, None)
