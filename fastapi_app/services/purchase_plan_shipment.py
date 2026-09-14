"""
采购计划出货重算与 FIFO 读路径封装

职责：出货记录创建/删除后的计划重算（_recalc_plans_common 及关联 helper）、
    明细出货数量重分配（_update_shipped_qty）、状态推算（_recalc_plan_status /
    _recalc_plan_statuses）、日志构建（_build_recalc_log_values）、
    FIFO 读路径安全包装（_get_shipped_fifo_map_safe）。

从 purchase_plan_crud.py 拆分而来，保持函数签名不变。
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.services.fifo_allocation import _get_shipped_fifo_map
from fastapi_app.services.purchase_plan_common import (
    _invalidate_plan_caches,
    _log_action,
    _schedule_post_commit,
    logger,
)
from fastapi_app.shared_models import PurchasePlan, PurchasePlanDetail


async def _get_shipped_fifo_map_safe(
    db: AsyncSession, details: list, customer_name_map: dict | None = None, plan_month: str = '',
) -> tuple[dict[int, int], bool]:
    """FIFO 分配的读路径包装：查询不可用时返回显式降级标记，而非全 0 误导值。

    fifo_allocation 在超时/异常时抛 RuntimeError('FIFO_ALLOCATION_UNAVAILABLE')；
    读路径（列表/详情/进度/日历/汇总）在此捕获并降级：
    返回空映射（不预填 0 值，调用方 .get(id, 0) 兜底）+ fifo_degraded=True 标记，
    由响应显式告知前端数据不可信。写路径（_update_shipped_qty）不经过本包装，
    保持异常传播以中止事务，避免把错误的 0 写入 shipped_qty。
    """
    try:
        return await _get_shipped_fifo_map(db, details, customer_name_map, plan_month), False
    except RuntimeError:
        return {}, True


def _recalc_plan_status(details: list[PurchasePlanDetail], shipped_map: dict[int, int], current_status: str = 'confirmed') -> str:
    """根据明细出货情况推算计划状态：全部完成→completed，否则 confirmed。pending/cancelled 保持不变"""
    if current_status in ('pending', 'cancelled'):
        return current_status
    if not details:
        return 'confirmed'
    for d in details:
        if shipped_map.get(d.id, 0) < d.quantity:
            return 'confirmed'
    return 'completed'


async def _fetch_affected_plans_and_details(
    db: AsyncSession,
    customer_name: str,
    product_name: str,
) -> tuple[list, list, list]:
    """查询受影响的计划、明细和相关明细"""
    plan_result = await db.execute(
        select(PurchasePlan).where(PurchasePlan.customer_name == customer_name)
    )
    affected_plans = plan_result.scalars().all()
    if not affected_plans:
        return [], [], []

    affected_plan_ids = [p.id for p in affected_plans]
    detail_result = await db.execute(
        select(PurchasePlanDetail)
        .where(PurchasePlanDetail.plan_id.in_(affected_plan_ids))
        .order_by(PurchasePlanDetail.plan_date, PurchasePlanDetail.id)
        .with_for_update()
    )
    all_affected_details = detail_result.scalars().all()
    related_details = [d for d in all_affected_details if d.product_name == product_name]
    return affected_plans, all_affected_details, related_details


async def _update_shipped_qty(
    db: AsyncSession,
    related_details: list,
    affected_plans: list,
) -> None:
    """重新 FIFO 分配并更新 shipped_qty"""
    customer_name_map = {p.id: p.customer_name for p in affected_plans}
    shipped_fifo_map = await _get_shipped_fifo_map(db, related_details, customer_name_map)
    for detail in related_details:
        detail.shipped_qty = shipped_fifo_map.get(detail.id, 0)
    await db.flush()


def _recalc_plan_statuses(
    affected_plans: list,
    all_affected_details: list,
    product_name: str,
) -> dict[int, dict]:
    """重新计算受影响计划的状态, 返回状态变更字典"""
    details_by_plan: dict[int, list[PurchasePlanDetail]] = {}
    for detail in all_affected_details:
        details_by_plan.setdefault(detail.plan_id, []).append(detail)

    status_changes: dict[int, dict] = {}
    for plan in affected_plans:
        plan_details = details_by_plan.get(plan.id, [])
        has_related = any(detail.product_name == product_name for detail in plan_details)
        if not has_related:
            continue
        old_status = plan.status
        shipped_map = {detail.id: detail.shipped_qty for detail in plan_details}
        new_status = _recalc_plan_status(plan_details, shipped_map, current_status=old_status)
        if old_status != new_status:
            plan.status = new_status
            status_changes[plan.id] = {'old_status': old_status, 'new_status': new_status}
    return status_changes


def _build_recalc_log_values(
    action_type: str,
    snapshot_before: dict[int, dict] | None,
    extra_old_value: dict | None,
    product_name: str,
    plan_id: int,
    plan_related: list,
    status_changes: dict[int, dict],
    plan_details_snap: list,
) -> tuple[dict, dict]:
    """构建重算日志的 old_value 和 new_value"""
    if action_type == 'rollback_stockout' and snapshot_before:
        old_value = {'product_name': product_name, **(extra_old_value or {})}
        old_value['details_before'] = [snapshot_before[d.id] for d in plan_related]
        old_value['status_change'] = status_changes.get(plan_id)
        new_value = {
            'details_after': plan_details_snap,
            'status_change': status_changes.get(plan_id),
        }
    else:
        old_value = {'product_name': product_name}
        new_value = {'details': plan_details_snap, 'status_change': status_changes.get(plan_id)}
    return old_value, new_value


async def _recalc_plans_common(
    db: AsyncSession,
    customer_name: str,
    product_name: str,
    action_type: str,
    *,
    operator: str = '',
    snapshot_before: dict[int, dict] | None = None,
    extra_old_value: dict | None = None,
    prefetched: tuple[list, list, list] | None = None,
) -> tuple[dict[int, dict], int, set[str]]:
    """
    采购计划重算的公共逻辑（出货记录创建/删除后重新计算 shipped_qty 和状态）

    参数:
        db: 数据库会话
        customer_name: 客户名称
        product_name: 产品名称
        action_type: 操作类型 ('recalc_stockout' 或 'rollback_stockout')
        operator: 操作者
        snapshot_before: 回滚前的快照（仅用于 rollback_stockout）
        extra_old_value: 追加到日志 old_value 的额外字段（如 stockout_no、quantity）
        prefetched: 预查询数据 (affected_plans, all_affected_details, related_details)，
                    传入时跳过内部查询以避免重复 DB 访问

    返回:
        (状态变更字典, 受影响计划数, 受影响计划月份集合)

    ⚠️ 三处 return 必须元数一致（均为 3 元组），调用方统一按 3 元组解包。
    `affected_plan_months` 是后加的返回项，早退路径必须返回 set() 而不是省略它 ——
    2026-09-10 生产曾因此抛 ValueError 并被上层 except 吞成 ERROR 日志，
    导致出货成功但采购计划 shipped_qty 未重算的静默数据不一致。
    """
    if not customer_name or not product_name:
        return {}, 0, set()

    if prefetched is not None:
        affected_plans, all_affected_details, related_details = prefetched
    else:
        affected_plans, all_affected_details, related_details = await _fetch_affected_plans_and_details(db, customer_name, product_name)

    if not affected_plans or not related_details:
        return {}, len(affected_plans), set()

    affected_plan_ids = [p.id for p in affected_plans]

    await _update_shipped_qty(db, related_details, affected_plans)

    status_changes = _recalc_plan_statuses(affected_plans, all_affected_details, product_name)
    await db.flush()

    # 6. 记录操作日志(预分组避免嵌套循环)
    related_by_plan: dict[int, list] = {}
    for detail in related_details:
        related_by_plan.setdefault(detail.plan_id, []).append(detail)

    for plan_id in affected_plan_ids:
        plan_related = related_by_plan.get(plan_id, [])
        if not plan_related:
            continue
        plan_details_snap = [
            {'id': d.id, 'shipped_qty': d.shipped_qty}
            for d in plan_related
        ]
        old_value, new_value = _build_recalc_log_values(
            action_type, snapshot_before, extra_old_value, product_name,
            plan_id, plan_related, status_changes, plan_details_snap,
        )
        await _log_action(db, plan_id, action_type, old_value, new_value, operator or 'system')

    affected_plan_months = {p.plan_month for p in affected_plans if p.plan_month}
    return status_changes, len(affected_plans), affected_plan_months


async def recalc_plans_after_stockout_delete(db: AsyncSession, customer_name: str, product_name: str, stockout_no: str, deleted_quantity: int, *, operator: str = '') -> None:
    """
    出货记录删除后，重新计算关联出货计划的 shipped_qty 和状态

    由 stock_service.delete_stockout() 在删除出货记录后调用。
    不负责删除出货记录或提交事务——这些由调用方处理。

    流程：
    1. 找到受影响的计划：按 customer_name 匹配
    2. 重新 FIFO 分配，更新明细 shipped_qty
    3. 重新计算计划状态（completed → confirmed 回退）
    4. 记录回滚操作日志
    """
    # 先查询以获取快照，再调用公共逻辑（传入预查询数据避免重复 DB 访问）
    if not customer_name or not product_name:
        return

    plan_result = await db.execute(
        select(PurchasePlan).where(PurchasePlan.customer_name == customer_name)
    )
    affected_plans = plan_result.scalars().all()
    if not affected_plans:
        return

    affected_plan_ids = [p.id for p in affected_plans]

    detail_result = await db.execute(
        select(PurchasePlanDetail)
        .where(PurchasePlanDetail.plan_id.in_(affected_plan_ids))
        .order_by(PurchasePlanDetail.plan_date, PurchasePlanDetail.id)
        .with_for_update()
    )
    all_affected_details = detail_result.scalars().all()

    related_details = [d for d in all_affected_details if d.product_name == product_name]
    if not related_details:
        return

    # 快照回滚前的状态（用于日志）
    snapshot_before: dict[int, dict] = {}
    for d in related_details:
        snapshot_before[d.id] = {'id': d.id, 'plan_id': d.plan_id, 'quantity': d.quantity,
                                  'shipped_qty': d.shipped_qty, 'plan_date': str(d.plan_date)}

    status_changes, _, affected_plan_months = await _recalc_plans_common(
        db, customer_name, product_name,
        action_type='rollback_stockout',
        operator=operator,
        snapshot_before=snapshot_before,
        extra_old_value={'stockout_no': stockout_no, 'quantity': deleted_quantity},
        prefetched=(affected_plans, all_affected_details, related_details),
    )

    if affected_plan_months:
        async def _post_commit():
            for pm in affected_plan_months:
                await _invalidate_plan_caches(pm)
        _schedule_post_commit(db, _post_commit)

    logger.info(
        f'出货计划回滚完成：stockout_no={stockout_no}, '
        f'客户={customer_name}, 产品={product_name}, 数量={deleted_quantity}, '
        f'影响计划={len(affected_plans)}, 状态变更={status_changes}'
    )


async def recalc_plans_after_stockout_create(
    db: AsyncSession, customer_name: str, product_name: str, *, operator: str = ''
) -> None:
    """
    出货记录创建后，重新计算关联出货计划的 shipped_qty 和状态

    由 stock_service.create_stockout() 在创建出货记录后调用。
    不负责提交事务——这些由调用方处理。
    """
    status_changes, affected_count, affected_plan_months = await _recalc_plans_common(
        db, customer_name, product_name,
        action_type='recalc_stockout',
        operator=operator,
    )

    if affected_plan_months:
        async def _post_commit():
            for pm in affected_plan_months:
                await _invalidate_plan_caches(pm)
        _schedule_post_commit(db, _post_commit)

    logger.info(
        f'出货计划重算完成：客户={customer_name}, 产品={product_name}, '
        f'影响计划={affected_count}, 状态变更={status_changes}'
    )
