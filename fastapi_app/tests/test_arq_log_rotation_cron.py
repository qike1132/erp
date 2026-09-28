"""nginx 日志轮转 cron 注册与任务行为断言(全部打桩/临时目录,不触真实日志)。"""
from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi_app.core import arq_app
from fastapi_app.tasks import maintenance_tasks


def test_cron_registered() -> None:
    names = [s["name"] for s in arq_app.cron_schedules]
    assert "nginx-log-rotation" in names


def test_cron_daily_0430() -> None:
    entry = next(s for s in arq_app.cron_schedules if s["name"] == "nginx-log-rotation")
    assert entry["cron"] == {"hour": 4, "minute": 30}
    assert entry.get("timeout") == 120


def test_task_rotates_nginx_logs(tmp_path: Path, monkeypatch) -> None:
    access = tmp_path / "nginx-access.log"
    error = tmp_path / "nginx-error.log"
    monkeypatch.setattr(maintenance_tasks, "NGINX_LOG_ROTATE_BYTES", 1024)
    access.write_bytes(b"a" * 2048)
    error.write_bytes(b"e" * 2048)
    monkeypatch.setattr(maintenance_tasks, "LOGS_DIR", tmp_path)
    asyncio.run(maintenance_tasks.rotate_nginx_logs_task(None))
    assert access.read_bytes() == b""
    assert (tmp_path / "nginx-access.log.1").exists()
    assert (tmp_path / "nginx-error.log.1").exists()


def test_task_noop_when_small(tmp_path: Path, monkeypatch) -> None:
    access = tmp_path / "nginx-access.log"
    access.write_bytes(b"a" * 10)
    monkeypatch.setattr(maintenance_tasks, "LOGS_DIR", tmp_path)
    monkeypatch.setattr(maintenance_tasks, "NGINX_LOG_ROTATE_BYTES", 1024)
    asyncio.run(maintenance_tasks.rotate_nginx_logs_task(None))
    assert access.read_bytes() == b"a" * 10
    assert not (tmp_path / "nginx-access.log.1").exists()
