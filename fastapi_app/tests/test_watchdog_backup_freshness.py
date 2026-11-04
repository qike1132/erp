"""看门狗备份新鲜度阈值（2026-11-04 修复回归）。

缺陷
----
`WATCHDOG_BACKUP_MAX_AGE_MINUTES` 默认 90 分钟，但生产 `backup_schedule` 里
只有**每日一次全量**（full=`42 8 * * *`），没有小时级增量产物。于是每天
10:12 之后、直到次日 08:45 之间 `backup_freshness` 必然 fail（约 22 小时/天）。
生产 `.env` 甚至把它调到了 540（9h），仍然每天从 17:45 红到次日 08:45。

后果不是"多一条日志"，而是**恒红信号淹没真故障**：真正的备份停摆与这条
误报长得一模一样，值班人只能选择忽略它。

修复契约（本文件逐条锁定）
--------------------------
1. 默认阈值改为 1500 分钟（25h），与 `fastapi_app/services/backup/freshness.py`
   的 `BACKUP_STALE_HOURS=25.0` 同口径；
2. `.env` 显式配置仍然优先（将来启用小时级增量时可调回 90）；
3. 判定只认归档后缀，`*.meta` / `backup_metrics_*.json` 不能把检查刷绿；
4. fail 的 detail 必须写出真实年龄与阈值，便于判断是"漏跑"还是"阈值配错"。
"""
from __future__ import annotations

import importlib.util
import os
import sys
import time
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]
HOUR = 3600.0


@pytest.fixture(scope="module")
def watchdog() -> ModuleType:
    """按路径加载零依赖脚本（与 test_watchdog_alert_cooldown.py 同款加载方式）。"""
    spec = importlib.util.spec_from_file_location(
        "erp_watchdog_freshness_under_test", ROOT / "scripts" / "ops" / "watchdog.py",
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _archive(directory: Path, name: str, age_hours: float) -> Path:
    path = directory / name
    path.write_bytes(b'x')
    stamp = time.time() - age_hours * HOUR
    os.utime(path, (stamp, stamp))
    return path


def test_default_threshold_matches_daily_backup_cadence(watchdog, monkeypatch) -> None:
    monkeypatch.delenv("WATCHDOG_BACKUP_MAX_AGE_MINUTES", raising=False)

    options = watchdog.build_options([])

    assert options.backup_max_age_minutes == 1500.0
    assert watchdog.DEFAULT_BACKUP_MAX_AGE_MINUTES == 1500.0


def test_env_override_still_wins(watchdog, monkeypatch) -> None:
    monkeypatch.setenv("WATCHDOG_BACKUP_MAX_AGE_MINUTES", "90")

    assert watchdog.build_options([]).backup_max_age_minutes == 90.0


def test_daily_backup_older_than_9h_is_not_a_failure(watchdog, tmp_path) -> None:
    """生产 540 分钟阈值下的误报场景：日备 12 小时前不应判失败。"""
    _archive(tmp_path, "erp_auto_daily_20261104_084509196.zip", age_hours=12)

    result = watchdog.check_backup_freshness(tmp_path, watchdog.DEFAULT_BACKUP_MAX_AGE_MINUTES)

    assert result.status == watchdog.OK
    assert '小时' in result.detail


def test_missing_a_daily_run_fails_the_next_day(watchdog, tmp_path) -> None:
    _archive(tmp_path, "erp_auto_daily_20261103_084508976.zip", age_hours=26)

    result = watchdog.check_backup_freshness(tmp_path, watchdog.DEFAULT_BACKUP_MAX_AGE_MINUTES)

    assert result.status == watchdog.FAIL
    assert '26' in result.detail or '25.0 小时' in result.detail
    assert '超过阈值' in result.detail


def test_sidecar_files_do_not_refresh_freshness(watchdog, tmp_path) -> None:
    """`*.meta` 与指标 JSON 每天都会被写，不能让空备份目录看起来"新鲜"。"""
    _archive(tmp_path, "erp_auto_daily_20261104_084509196.zip", age_hours=30)
    (tmp_path / "erp_auto_daily_20261104_084509196.zip.meta").write_text('{}', encoding='utf-8')
    metrics = tmp_path / "metrics"
    metrics.mkdir()
    (metrics / "backup_metrics_20261104.json").write_text('{}', encoding='utf-8')

    result = watchdog.check_backup_freshness(tmp_path, watchdog.DEFAULT_BACKUP_MAX_AGE_MINUTES)

    assert result.status == watchdog.FAIL, '伴随文件不得被当成归档'


def test_empty_and_missing_dirs_fail(watchdog, tmp_path) -> None:
    assert watchdog.check_backup_freshness(tmp_path, 1500.0).status == watchdog.FAIL
    assert watchdog.check_backup_freshness(tmp_path / "nope", 1500.0).status == watchdog.FAIL
