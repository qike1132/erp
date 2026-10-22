"""L4：/metrics token 必须常数时间比较，前缀不得绕过。"""


def test_metrics_token_compare_rejects_prefix_and_accepts_exact(monkeypatch):
    from fastapi_app.core import health

    monkeypatch.setenv('METRICS_BEARER_TOKEN', 'secret-token')
    assert health._metrics_token_ok('Bearer secret-token') is True
    assert health._metrics_token_ok('Bearer secret-token-extra') is False
    assert health._metrics_token_ok('Bearer secret') is False


def test_metrics_token_compare_false_when_unconfigured(monkeypatch):
    from fastapi_app.core import health

    monkeypatch.delenv('METRICS_BEARER_TOKEN', raising=False)
    assert health._metrics_token_ok('Bearer anything') is False
