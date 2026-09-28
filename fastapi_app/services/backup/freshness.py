"""备份新鲜度判定 —— 以产物时间戳为权威,不读 backup_schedule.last_status。

为什么独立于 validation._check_last_backup:那个端点保留自己的 24h 契约与
`within_24h` 键(三个测试文件锁定),本模块供 /api/health 复用,阈值 25h
(全量每日 02:00、增量 06-22 每小时,25h 宽松且几乎不误报)。

权威性说明:runbook 明确「不要据 last_status 判断备份失败,应核对 backups/ 产物
时间戳」。ARQ 一旦停摆就无人产出新文件,age 会持续增长 —— 这就是本模块的信号。
"""
from __future__ import annotations

import logging
from datetime import datetime

logger = logging.getLogger(__name__)

#: 超过该小时数无新产物即视为异常
BACKUP_STALE_HOURS = 25.0


def backup_freshness(threshold_hours: float = BACKUP_STALE_HOURS) -> dict:
    """返回 ``{'ok': bool, 'age_hours': float | None, 'last_at': str | None}``。

    扫描失败或无产物一律 ``ok=False``,且本函数**绝不抛** —— 健康端点不得因
    备份异常而返回 5xx(它同时是 prod_runner 的后端存活判据)。
    """
    try:
        from fastapi_app.services.backup.records import list_backup_files

        files = list_backup_files()
        if not files:
            return {"ok": False, "age_hours": None, "last_at": None}
        latest = max(files, key=lambda f: f.get("mtime", 0))
        mtime = latest.get("mtime") or 0
        last_dt = datetime.fromtimestamp(mtime)
        age_hours = (datetime.now() - last_dt).total_seconds() / 3600
        return {
            "ok": age_hours <= threshold_hours,
            "age_hours": round(age_hours, 2),
            "last_at": last_dt.isoformat(),
        }
    except Exception as exc:  # defensive: 健康端点不得因备份扫描异常而失败
        logger.warning("备份新鲜度扫描失败: %s", exc)
        return {"ok": False, "age_hours": None, "last_at": None}
