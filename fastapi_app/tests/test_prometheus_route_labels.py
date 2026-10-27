"""Prometheus endpoint 标签只能使用低基数路由模板。"""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from fastapi_app.core import metrics
from fastapi_app.core import middleware as middleware_module


class _Metric:
    def __init__(self):
        self.calls = []

    def labels(self, **labels):
        self.calls.append(labels)
        return self

    def inc(self):
        pass

    def dec(self):
        pass

    def observe(self, _value):
        pass


def test_dynamic_and_unmatched_paths_never_become_label_values(monkeypatch):
    monkeypatch.setattr(metrics, 'METRICS_AVAILABLE', True)
    request_count = _Metric()
    in_progress = _Metric()
    latency = _Metric()
    monkeypatch.setattr(metrics, 'REQUEST_COUNT', request_count)
    monkeypatch.setattr(metrics, 'REQUESTS_IN_PROGRESS', in_progress)
    monkeypatch.setattr(metrics, 'REQUEST_LATENCY', latency)

    app = FastAPI()
    middleware_module._setup_prometheus(app)

    @app.get('/items/{item_id}')
    async def get_item(item_id: str):
        return {'item_id': item_id}

    client = TestClient(app)
    assert client.get('/items/arbitrary-user-value').status_code == 200
    assert client.get('/not-a-route/arbitrary-user-value').status_code == 404

    endpoints = [call['endpoint'] for call in request_count.calls]
    assert endpoints == ['/items/{item_id}', '{unmatched}']
    assert all('arbitrary-user-value' not in endpoint for endpoint in endpoints)
