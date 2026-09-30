"""后端统一日志策略的接线锁（与桌面壳读同一份 config/log_policy.json）。

历史上同一台机器上「多大该轮转」有三个答案：prod_runner 用 PROD_LOG_ROTATE_MB（50MB）、
ARQ cron 固定 100MB 且只转 nginx、桌面壳 50MB。本测试锁住「三方都走 utils.log_rotation
的共享策略与同一套实现」，防止重构时又退回各自一套。
"""
from __future__ import annotations

import inspect
from pathlib import Path

from fastapi_app.core import prod_runner
from fastapi_app.tasks import maintenance_tasks

PKG_PROD_RUNNER = Path(prod_runner.__file__)
PKG_MAINTENANCE = Path(maintenance_tasks.__file__)


def test_prod_runner_uses_shared_policy_and_maintenance() -> None:
    text = PKG_PROD_RUNNER.read_text(encoding="utf-8")
    assert "from utils.log_rotation import" in text
    assert "load_log_policy" in text and "rotate_oversized_logs" in text
    assert "prune_log_files" in text, "prod_runner 未采用共享的保留清理"
    assert '_get_int_env("PROD_LOG_ROTATE_MB"' not in text, "仍有独立阈值来源，会与共享策略分歧"
    assert "def _log_rotate_bytes" not in text, "仍保留本模块自己的阈值函数"
    assert 'LOG_POLICY_PATH = PROJECT_ROOT / "config" / "log_policy.json"' in text


def test_prod_runner_maintenance_reads_policy() -> None:
    body = inspect.getsource(prod_runner.Supervisor._rotate_logs_if_due)
    assert "load_log_policy(" in body
    assert "rotate_oversized_logs(" in body and "prune_log_files(" in body


def test_arq_task_uses_shared_policy_and_maintenance() -> None:
    text = PKG_MAINTENANCE.read_text(encoding="utf-8")
    assert "load_log_policy" in text and "rotate_oversized_logs" in text
    assert "NGINX_LOG_ROTATE_BYTES =" not in text, "ARQ 仍有独立阈值常量，会与共享策略分歧"
    body = inspect.getsource(maintenance_tasks.maintain_logs_task)
    assert "load_log_policy(" in body and "prune_log_files(" in body


def test_arq_cron_still_scheduled() -> None:
    from fastapi_app.core import arq_app

    entry = next(s for s in arq_app.cron_schedules if s["name"] == "log-maintenance")
    assert entry["func"] is maintenance_tasks.maintain_logs_task
