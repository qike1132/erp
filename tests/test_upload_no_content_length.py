"""M12：无 Content-Length 的请求体不得借 chunked 绕过导入上限。"""
from fastapi.testclient import TestClient

from fastapi_app.main import app


def test_chunked_body_over_import_limit_rejected(monkeypatch):
    from fastapi_app.core import middleware as mw

    monkeypatch.setattr(mw, "_IMPORT_UPLOAD_BODY_LIMIT", 1024 * 1024)

    def _gen():
        for _ in range(2):
            yield b"x" * (1024 * 1024)

    client = TestClient(app)
    resp = client.post("/api/v1/tasks/import-orders", content=_gen())
    assert resp.status_code == 413, resp.text[:200]


def test_backup_chunked_without_length_returns_411():
    def _gen():
        yield b"x"

    client = TestClient(app)
    resp = client.post("/api/v1/backup/upload", content=_gen())
    assert resp.status_code == 411, resp.text[:200]
