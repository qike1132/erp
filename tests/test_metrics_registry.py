"""L7：metrics 去重必须用自有登记表，不依赖 prometheus_client 私有属性。"""
from pathlib import Path


def test_duplicate_counter_returns_same_collector():
    from fastapi_app.core.metrics import _get_or_create_counter

    a = _get_or_create_counter('audit_dup_probe_total', 'probe', ['x'])
    b = _get_or_create_counter('audit_dup_probe_total', 'probe', ['x'])
    assert a is b


def test_metrics_does_not_use_private_registry():
    from fastapi_app.core import metrics

    src = Path(metrics.__file__).read_text(encoding='utf-8')
    assert '_names_to_collectors' not in src
