"""一次性清理：删除订单后残留的出货计划明细（2026-10-06 删除联动上线前的历史残留）。

背景：删除联动（purge_shipment_plan_details_for_order）上线前删除的订单，
其同步产生的采购计划明细仍残留在 purchase_plan_details 中。

判定口径：
  - 明细 remark 以「来源订单:」开头（仅同步链路会写此前缀）
  - 提取来源订单号后查 order 表：订单不存在，或 is_deleted=true → 视为孤儿明细
  - 孤儿明细删除后，被清空的计划主单一并移除（与删除联动同口径）

用法（必须从仓库根目录运行）：
  python scripts/cleanup_orphan_plan_details_20261006.py            # dry-run，只报告
  python scripts/cleanup_orphan_plan_details_20261006.py --execute  # 备份后执行删除

安全措施：
  - --execute 前先写备份快照到 logs/（误操作可依据备份手工恢复）
  - 单事务提交：删除失败整体回滚
  - 提交后尽力清除 Redis 中的 erp:pp:* / erp:plan_fifo:* 缓存键（失败不影响数据，重启 + TTL 兜底）
"""
import argparse
import asyncio
import json
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import delete, func, select

_REMARK_PREFIX = '来源订单:'
# 同步链路只写全角「；」，半角「;」一并兼容（防御性）
_NOTE_SEP = re.compile(r'[;；]')


def extract_order_no(remark: str) -> str:
    """从明细 remark 提取来源订单号：'来源订单:PO-xxx；备注' → 'PO-xxx'"""
    body = remark.removeprefix(_REMARK_PREFIX)
    return _NOTE_SEP.split(body, 1)[0].strip()


async def main(execute: bool) -> int:
    if execute:
        from _prod_write_guard import require_prod_write_consent
        require_prod_write_consent('删除孤儿采购计划明细及其被清空的计划主单',
                                   hint='误操作可依据 logs/ 下的备份手工恢复')
    # 不设置 APP_ENV：config 读取 .env（生产库）
    from fastapi_app.core.database import (
        ensure_engine_for_current_loop,
        require_async_session_local,
    )
    from fastapi_app.shared_models import Order, PurchasePlan, PurchasePlanDetail

    await ensure_engine_for_current_loop()
    session_factory = require_async_session_local()

    async with session_factory() as db:
        details = (await db.execute(
            select(PurchasePlanDetail).where(PurchasePlanDetail.remark.like(_REMARK_PREFIX + '%'))
        )).scalars().all()
        if not details:
            print('没有带「来源订单:」remark 的计划明细，无事可做')
            return 0

        order_nos = sorted({extract_order_no(d.remark) for d in details})
        order_rows = (await db.execute(
            select(Order.order_no, Order.is_deleted).where(Order.order_no.in_(order_nos))
        )).all()
        deleted_or_missing = {
            row.order_no for row in order_rows
            if row.is_deleted  # None/False 视为存活
        }
        missing = set(order_nos) - {row.order_no for row in order_rows}
        deleted_or_missing |= missing

        orphans = [
            d for d in details
            if extract_order_no(d.remark) in deleted_or_missing
        ]
        alive_nos = set(order_nos) - deleted_or_missing

        plan_ids = list({d.plan_id for d in orphans})
        plans = (await db.execute(
            select(PurchasePlan).where(PurchasePlan.id.in_(plan_ids))
        )).scalars().all() if plan_ids else []

        print(f'带来源 remark 的明细总数：{len(details)}')
        print(f'涉及订单号：{len(order_nos)} 个；其中已删除/缺失：{len(deleted_or_missing)} 个，仍存活：{len(alive_nos)} 个')
        print(f'孤儿明细（将删除）：{len(orphans)} 条，分布在 {len(plan_ids)} 个计划主单')
        for d in orphans[:20]:
            print(f'  - detail#{d.id} plan#{d.plan_id} {d.plan_date} x{d.quantity} remark={d.remark!r}')
        if len(orphans) > 20:
            print(f'  ...（其余 {len(orphans) - 20} 条略）')

        if not orphans:
            print('无孤儿明细，无需清理')
            return 0

        # 计算删除孤儿后哪些主单会被清空。
        # 注意：不能从「带 remark 的明细」里数存活者 —— 同一主单还可能有手工明细
        # （remark 为空），漏数会把非空主单判成空、连带其手工明细被 CASCADE 删掉。
        # 与服务层（shipment_plan_sync）同口径：删完孤儿后回查 DB 每个主单的真实剩余数。
        remaining_by_plan: dict[int, int] = {}
        if plan_ids:
            rows = (await db.execute(
                select(PurchasePlanDetail.plan_id, func.count(PurchasePlanDetail.id))
                .where(PurchasePlanDetail.plan_id.in_(plan_ids))
                .group_by(PurchasePlanDetail.plan_id)
            )).all()
            remaining_by_plan = {row[0]: row[1] for row in rows}
        emptied_plans = [p for p in plans if remaining_by_plan.get(p.id, 0) == 0]
        affected_months = sorted({p.plan_month for p in plans})

        print(f'将被移除的空计划主单：{len(emptied_plans)} 个'
              + (f'（{", ".join(p.plan_no for p in emptied_plans[:10])}）' if emptied_plans else ''))
        print(f'受影响月份：{"、".join(affected_months)}')

        if not execute:
            print('\n[dry-run] 未做任何修改。确认无误后加 --execute 执行。')
            return 0

        # ---- 备份（先于任何删除）----
        backup_dir = Path('logs')
        backup_dir.mkdir(exist_ok=True)
        backup_path = backup_dir / f'orphan_plan_details_backup_{datetime.now().strftime("%Y%m%d-%H%M%S")}.json'
        backup_path.write_text(json.dumps({
            'schema_version': 1,
            'cleaned_at': datetime.now().isoformat(),
            'orphan_details': [d.to_dict() for d in orphans],
            'removed_plans': [p.to_dict() for p in emptied_plans],
        }, ensure_ascii=False, indent=2), encoding='utf-8')
        print(f'备份已写入：{backup_path}')

        # ---- 删除（单事务：session autobegin 已开启，显式 commit 提交）----
        await db.execute(delete(PurchasePlanDetail).where(
            PurchasePlanDetail.id.in_([d.id for d in orphans])))
        plan_deleted = 0
        if emptied_plans:
            result = await db.execute(delete(PurchasePlan).where(
                PurchasePlan.id.in_([p.id for p in emptied_plans])))
            plan_deleted = result.rowcount or 0
        await db.commit()

        print(f'已删除孤儿明细 {len(orphans)} 条、空计划主单 {plan_deleted} 个（事务已提交）')

    # ---- 提交后清 Redis 计划缓存（尽力而为）----
    try:
        import redis

        from fastapi_app.core.config import settings
        cache_url = settings.REDIS_CACHE_URL or settings.REDIS_URL
        client = redis.Redis.from_url(cache_url, decode_responses=True)
        removed = 0
        for pattern in ('erp:pp:*', 'erp:plan_fifo:*'):
            keys = list(client.scan_iter(match=pattern, count=500))
            if keys:
                removed += client.delete(*keys)
        client.close()
        print(f'Redis 计划缓存已清除 {removed} 个键')
    except Exception as cache_err:  # noqa: BLE001 - 缓存清理失败不应影响清理结果
        print(f'警告：Redis 缓存清除失败（{cache_err}）。重启 erp-prod + 缓存 TTL 会兜底。')

    print('完成。建议重启 erp-prod 以清空各 worker 的 L1 进程内缓存。')
    return 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='清理已删订单残留的出货计划明细')
    parser.add_argument('--execute', action='store_true', help='真正执行删除（默认 dry-run）')
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main(args.execute)))
