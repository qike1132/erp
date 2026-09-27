import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from fastapi_app.api import ws as ws_module
from fastapi_app.api.ws import register_websocket


@pytest.fixture()
def app(monkeypatch):
    application = FastAPI()
    register_websocket(application)

    class Result:
        def first(self):
            return (1, True)

    class Connection:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def execute(self, *_args, **_kwargs):
            return Result()

    monkeypatch.setattr(ws_module, "async_engine", type("Engine", (), {"connect": Connection})())
    return application


def test_ticket_is_single_use(app, monkeypatch):
    monkeypatch.setattr(ws_module, "_origin_allowed", lambda _origin: True)
    client = TestClient(app)
    ws_module._WS_PENDING_TICKETS["ticket"] = 1
    with client.websocket_connect("/ws/notifications?ticket=ticket") as websocket:
        websocket.send_text("ping")
        assert websocket.receive_text() == "pong"
    with pytest.raises(Exception):  # noqa: BLE001 - TestClient 对拒绝握手封装为任意运行时异常
        with client.websocket_connect("/ws/notifications?ticket=ticket"):
            pass
