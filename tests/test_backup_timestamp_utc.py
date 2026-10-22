"""L2：备份状态时间戳用 aware UTC；文件名/保留期仍用本地时间（解析方依赖）。"""


def test_backup_status_timestamp_is_utc_aware():
    from datetime import datetime
    from pathlib import Path

    from fastapi_app.services.backup import records

    # 行为断言：接口返回值必须可解析为带时区的时间
    ts = records.get_backup_status()['timestamp']
    assert datetime.fromisoformat(ts).tzinfo is not None

    # 源码守卫：避免有人把 UTC 调用写进无关行骗绿
    src = Path(records.__file__).read_text(encoding='utf-8')
    assert 'datetime.now(UTC).isoformat()' in src
    assert "'timestamp': datetime.now().strftime" not in src
