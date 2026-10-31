"""M12：无 Content-Length 的请求体不得借 chunked 绕过任何路径级上限。"""
from fastapi.testclient import TestClient

from fastapi_app.main import app


def test_chunked_body_over_streaming_budget_rejected(monkeypatch):
    """M1（2026-10-31 评审）：chunked 独立预算（默认 2MB，与路径级上限解耦）。

    原实现把无 CL 请求的计数上限设为 min(路径上限, 64MB 导入预算)——导入路径的
    chunked 请求可在中间件内缓冲 ~2×64MB。现改为 min(路径上限, _CHUNKED_BODY_LIMIT)，
    直连客户端超预算即 413；正常大上传走 nginx（HTTP/1.0 反代必带 CL），不受影响。
    """
    from fastapi_app.core import middleware as mw

    monkeypatch.setattr(mw, "_CHUNKED_BODY_LIMIT", 1024 * 1024)

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
