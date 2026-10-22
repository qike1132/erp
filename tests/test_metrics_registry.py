"""L7：metrics 去重必须用自有登记表，不依赖 prometheus_client 私有属性。"""
import contextlib
from pathlib import Path


def test_duplicate_counter_returns_same_collector():
    from prometheus_client import REGISTRY

    from fastapi_app.core import metrics

    try:
        a = metrics._get_or_create_counter('audit_dup_probe_total', 'probe', ['x'])
        b = metrics._get_or_create_counter('audit_dup_probe_total', 'probe', ['x'])
        assert a is b
    finally:
        collector = metrics._CREATED_COLLECTORS.pop('audit_dup_probe_total', None)
        if collector is not None:
            with contextlib.suppress(KeyError):
                REGISTRY.unregister(collector)


def test_metrics_does_not_use_private_registry():
    from fastapi_app.core import metrics

    src = Path(metrics.__file__).read_text(encoding='utf-8')
    assert '_names_to_collectors' not in src
