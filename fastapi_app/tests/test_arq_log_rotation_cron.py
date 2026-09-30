"""日志维护 cron 注册与任务行为断言(全部打桩/临时目录,不触真实日志)。"""
from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi_app.core import arq_app
from fastapi_app.tasks import maintenance_tasks
from utils.log_rotation import LogPolicy


def test_cron_registered() -> None:
    names = [s["name"] for s in arq_app.cron_schedules]
    assert "log-maintenance" in names


def test_cron_daily_0430() -> None:
    entry = next(s for s in arq_app.cron_schedules if s["name"] == "log-maintenance")
    assert entry["cron"] == {"hour": 4, "minute": 30}
    assert entry.get("timeout") == 120


def _stub_policy(monkeypatch, rotate_bytes: int = 1024) -> None:
    """桩接策略读取，隔离机器上的真实 config/log_policy.json（MB 粒度放不下 1KB）。"""
    monkeypatch.setattr(maintenance_tasks, "load_log_policy",
                        lambda path=None: LogPolicy(rotate_bytes=rotate_bytes))


def test_task_rotates_over_limit_logs(tmp_path: Path, monkeypatch) -> None:
    access = tmp_path / "nginx-access.log"
    error = tmp_path / "nginx-error.log"
    access.write_bytes(b"a" * 2048)
    error.write_bytes(b"e" * 2048)
    _stub_policy(monkeypatch)
    monkeypatch.setattr(maintenance_tasks, "LOGS_DIR", tmp_path)
    asyncio.run(maintenance_tasks.maintain_logs_task(None))
    assert access.read_bytes() == b""
    assert (tmp_path / "nginx-access.log.1").exists()
    assert (tmp_path / "nginx-error.log.1").exists()


def test_task_noop_when_small(tmp_path: Path, monkeypatch) -> None:
    access = tmp_path / "nginx-access.log"
    access.write_bytes(b"a" * 10)
    _stub_policy(monkeypatch)
    monkeypatch.setattr(maintenance_tasks, "LOGS_DIR", tmp_path)
    asyncio.run(maintenance_tasks.maintain_logs_task(None))
    assert access.read_bytes() == b"a" * 10
    assert not (tmp_path / "nginx-access.log.1").exists()
