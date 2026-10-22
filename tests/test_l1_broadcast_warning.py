"""M1：多 worker 未开 L1 广播时必须告警，避免长期读脏数据无感知。"""
import logging


def test_warns_when_multi_worker_without_broadcast(monkeypatch, caplog):
    from fastapi_app.core import cache

    monkeypatch.setattr(cache, "_L1_BROADCAST_ENABLED", False)
    with caplog.at_level(logging.WARNING):
        cache.warn_if_l1_broadcast_disabled(8)

    assert any(
        "CACHE_L1_BROADCAST_ENABLED" in r.getMessage() for r in caplog.records
    ), caplog.text


def test_no_warning_for_single_worker(monkeypatch, caplog):
    from fastapi_app.core import cache

    monkeypatch.setattr(cache, "_L1_BROADCAST_ENABLED", False)
    with caplog.at_level(logging.WARNING):
        cache.warn_if_l1_broadcast_disabled(1)

    assert not any(
        "CACHE_L1_BROADCAST_ENABLED" in r.getMessage() for r in caplog.records
    )


def test_resolve_worker_count_tolerates_garbage():
    import os

    from fastapi_app.core import cache

    assert cache.resolve_worker_count({"UVICORN_WORKERS": "8"}) == 8
    # 非数字不得让启动期抛 ValueError
    assert cache.resolve_worker_count({"UVICORN_WORKERS": "auto"}) == 1
    # 未设置时与 prod_runner 的默认值一致（min(4, cpu_count)）
    assert cache.resolve_worker_count({}) == min(4, os.cpu_count() or 1)
