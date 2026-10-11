"""连接预算纳入副本池测试（2026-10-11 复核 N2）。

原 _get_pool_config 只算主池（8 worker → 64），副本池减半另算（8 worker → 24），
峰值 64+24=88 > 预留 80。预算必须两个池一起算。
"""

from __future__ import annotations

from fastapi_app.core import database


def _peak(monkeypatch, workers: int, pgbouncer: str = "false", replica: bool = True):
    monkeypatch.setenv("UVICORN_WORKERS", str(workers))
    monkeypatch.setenv("DB_MAX_CONNECTIONS", "100")
    monkeypatch.setenv("PGBOUNCER_ENABLED", pgbouncer)
    if replica:
        monkeypatch.setenv("ASYNC_DATABASE_REPLICA_URL", "postgresql+asyncpg://r@h/replica")
    else:
        monkeypatch.delenv("ASYNC_DATABASE_REPLICA_URL", raising=False)
    cfg = database._get_pool_config()
    per = cfg["pool_size"] + cfg["max_overflow"]
    # 副本池 = 主池减半（_init_read_engine 的规则），无副本 URL 时为 0
    replica_per = max(2, cfg["pool_size"] // 2) + max(1, cfg["max_overflow"] // 2)
    return workers * per, workers * replica_per


def test_main_plus_replica_within_budget(monkeypatch) -> None:
    """8 worker：主池+副本池峰值不得超过 available（80）。"""
    main_peak, replica_peak = _peak(monkeypatch, 8)
    assert main_peak + replica_peak <= 80, (
        f"主池 {main_peak} + 副本池 {replica_peak} 超出预留 80（N2 连接预算超配）"
    )


def test_no_replica_url_keeps_full_pool(monkeypatch) -> None:
    """未配置副本 URL 时不收缩（主池回到原下限 5+3，不白降 20% 容量）。"""
    monkeypatch.setenv("UVICORN_WORKERS", "8")
    monkeypatch.setenv("DB_MAX_CONNECTIONS", "100")
    monkeypatch.setenv("PGBOUNCER_ENABLED", "false")
    monkeypatch.delenv("ASYNC_DATABASE_REPLICA_URL", raising=False)
    cfg = database._get_pool_config()
    # 8 worker 无副本：available//(8*2)=5 → max(5,5)=5，overflow max(3, 80//24)=3
    assert (cfg["pool_size"], cfg["max_overflow"]) == (5, 3), cfg


def test_budget_holds_across_worker_counts(monkeypatch) -> None:
    """1/2/4/8/16 worker 全档位主+副本都在预算内。"""
    for w in (1, 2, 4, 8, 16):
        main_peak, replica_peak = _peak(monkeypatch, w)
        assert main_peak + replica_peak <= 80, f"workers={w}: {main_peak}+{replica_peak}>80"


def test_pgbouncer_mode_also_within_budget(monkeypatch) -> None:
    """PgBouncer 模式同样两池合计不超预算。"""
    main_peak, replica_peak = _peak(monkeypatch, 8, pgbouncer="true")
    assert main_peak + replica_peak <= 80, f"{main_peak}+{replica_peak}>80"
