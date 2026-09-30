"""系统维护任务

职责：
- 刷新仪表盘物化视图
- 日志维护：按共享策略轮转 + 保留清理（与桌面壳/prod_runner 同一套实现与策略）
- 其他低频率维护型任务
"""
import asyncio
import logging
from pathlib import Path

from sqlalchemy import text

from fastapi_app.core.database import get_async_db_context
from utils.log_rotation import load_log_policy, prune_log_files, rotate_oversized_logs

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
LOGS_DIR = PROJECT_ROOT / "logs"
# 策略文件的显式路径：与桌面壳/prod_runner 共用同一份（config/log_policy.json）。
LOG_POLICY_PATH = PROJECT_ROOT / "config" / "log_policy.json"


async def maintain_logs_task(ctx) -> dict:
    """ARQ 定时任务：按共享策略轮转超限日志并清理过期日志。

    此前这里是「只转 nginx 两个文件、固定 100MB、不做保留清理」的独立一套，
    于是同一台机器上「多大该轮转」有三个答案，且 nginx 的轮转责任全押在这个
    每日 cron 上（ARQ 停摆就没人管）。现在读同一份 ``config/log_policy.json``、
    调同一套 ``utils.log_rotation`` —— 它只是三处调度（桌面壳 / prod_runner /
    本任务）里的兜底之一，行为完全一致。
    纯文件操作,async 仅为满足 ARQ cron() 对协程函数的要求。
    """
    policy = load_log_policy(LOG_POLICY_PATH)
    rotation = rotate_oversized_logs(LOGS_DIR, max_bytes=policy.rotate_bytes)
    prune = prune_log_files(LOGS_DIR, keep_days=policy.keep_days,
                            max_total_bytes=policy.max_total_bytes)
    return {"success": True, "message": f"{rotation.summary()}；{prune.summary()}"}


async def _refresh_single_mv(db, mv_name: str) -> None:
    """刷新单个物化视图（CONCURRENTLY 不阻塞读）。

    独立 session 中执行，各 MV 之间无表关联，可安全并行 asyncio.gather。
    CONCURRENTLY 要求 MV 有唯一索引（已在对应 migration 中创建）。
    视图不存在时（迁移未执行）记录警告并跳过，不影响其他视图。
    """
    exists = (await db.execute(
        text("SELECT to_regclass(:name)"), {"name": mv_name}
    )).scalar()
    if exists is None:
        logger.warning("物化视图 %s 不存在，跳过刷新（请确认迁移 pg_standalone_017 已执行）", mv_name)
        return
    await db.execute(text(f"REFRESH MATERIALIZED VIEW CONCURRENTLY {mv_name}"))  # nosec B608: 常量字符串
    await db.commit()


# 全部物化视图（含日统计 + 产品聚合）
_DASHBOARD_MV_NAMES = [
    "mv_daily_order_quantity",
    "mv_daily_stockin_quantity",
    "mv_daily_stockout_quantity",
]
_PRODUCT_MV_NAMES = [
    "mv_product_aggregate",
]


async def _refresh_materialized_views(mv_names: list[str], label: str) -> None:
    """并行刷新一组物化视图（CONCURRENTLY 不阻塞读）。

    mv_names 内各 MV 基于不同基表或不同聚合维度，CONCURRENTLY 刷新互不
    冲突（产品聚合 MV 与日统计 MV 无共享写锁），可安全并行。
    每个 MV 使用独立 session（get_async_db_context），通过 asyncio.gather 并行。
    """
    async def _refresh_one(mv_name: str) -> None:
        async with get_async_db_context() as db:
            await _refresh_single_mv(db, mv_name)

    await asyncio.gather(*(_refresh_one(name) for name in mv_names))
    logger.info("%s物化视图刷新完成（%d 个并行）", label, len(mv_names))


async def refresh_dashboard_mv_task(ctx) -> dict:
    """ARQ 任务入口：刷新全部物化视图（日统计 + 产品聚合）。"""
    try:
        await _refresh_materialized_views(_DASHBOARD_MV_NAMES, "仪表盘")
        await _refresh_materialized_views(_PRODUCT_MV_NAMES, "产品聚合")
        return {"success": True, "message": "物化视图刷新完成"}
    except Exception as exc:  # broad-except: 定时任务容错，异常不传播以避免调度器崩溃
        logger.exception("refresh_dashboard_mv_task 失败")
        raise exc


async def ensure_readonly_grants_task(ctx) -> dict:
    """ARQ 任务：对账只读副本 erp_readonly 授权，缺失时自愈。

    数据库恢复会清空只读授权（只读接口 500），此处周期对账兜底，
    与「恢复完成即自愈」形成双保险。
    """
    from fastapi_app.services.backup.ro_grants import ensure_readonly_grants

    try:
        healed = await ensure_readonly_grants()
        if healed:
            logger.warning("只读授权对账：检测到缺失并已重新授予 erp_readonly")
        return {"success": True, "healed": healed}
    except Exception as exc:  # broad-except: 定时任务容错，避免调度器崩溃
        logger.exception("ensure_readonly_grants_task 失败")
        raise exc
