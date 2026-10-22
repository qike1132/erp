"""L2：备份状态时间戳用 aware UTC；文件名/保留期仍用本地时间（解析方依赖）。"""


def test_backup_status_timestamp_is_utc_aware():
    from pathlib import Path

    from fastapi_app.services.backup import records

    src = Path(records.__file__).read_text(encoding='utf-8')
    assert 'datetime.now(UTC).isoformat()' in src
    assert "'timestamp': datetime.now().strftime" not in src
