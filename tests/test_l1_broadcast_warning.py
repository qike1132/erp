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
