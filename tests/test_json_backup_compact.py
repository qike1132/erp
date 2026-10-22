"""H2：JSON 备份使用紧凑序列化，去掉 indent 造成的体积放大。"""
import json


def test_backup_json_is_compact():
    from fastapi_app.services.backup.json_backup import _encode_backup_json

    payload = {"tables": {"t": {"columns": ["a"], "rows": [{"a": 1}], "count": 1}}}
    raw = _encode_backup_json(payload)

    assert b"\n" not in raw, "紧凑格式不应有换行"
    assert b'": ' not in raw, "紧凑格式不应有缩进空格"
    assert json.loads(raw)["tables"]["t"]["rows"][0]["a"] == 1
