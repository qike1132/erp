"""
订单条目 → 采购计划（出货计划）同步服务

设计依据：docs/designs/2026-10-06-order-shipment-plan-sync-design.md
工作流：docs/plans/2026-10-06-shipment-plan-sync-workflow.md

职责：把批量订单创建中带 shipment_plans 分批计划的条目，同步为采购计划系统的
计划明细（每批一条：plan_date=批次出货日期、quantity=批次数量）。仅做「计划写入」这一件事：

- 同事务语义由调用方保证：本函数在 order_batch_create 的每客户 savepoint 内被
  调用，抛 ValueError 会触发该客户订单组整体回滚（订单与计划同生共死）。
- 客户+月 find-or-create：同客户同月已有计划（如采购计划页手工建的）→ add_details
  追加明细；没有 → create_plan 新建主单。计划主单唯一约束 uq_ppl_month_customer
  在并发首建竞态下会让后到组回滚报错，用户重试即转追加路径（内网低频，可接受）。
- 溯源：明细 remark 记「来源订单:{order_no}」弱关联（Odoo origin 模式），
  计划主单 remark 记「订单 xxx 自动同步」；不新增表/列，不动订单模型。
- 权限：服务层直调，不经过 /plans/create 端点的 production_plan_manage 检查 ——
  录单员只需 order_manage（设计稿 Decision #6）；审计靠 plan.created_by=提交人。
- 删除联动（2026-10-06）：订单删除时按 remark 边界匹配级联清理其明细，
  被删空的计划主单一并移除（见 purge_shipment_plan_details_for_order）。
"""
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.services.plan_utils import normalize_plan_date
from fastapi_app.services.purchase_plan_crud_ops import add_details, create_plan
from fastapi_app.shared_models import Customer, PurchasePlan, PurchasePlanDetail

logger = logging.getLogger(__name__)


async def sync_order_items_to_plans(
    db: AsyncSession,
    *,
    customer_name: str,
    order_no: str,
    validated_items: list,
    created_by: str = '',
) -> int:
    """把带出货计划标记的订单条目同步为采购计划明细。

    Args:
        db: 异步会话（处于调用方的 savepoint/事务内，本函数不 commit）。
        customer_name: 订单客户名（order.customer，自由文本）。
        order_no: 本次创建的主订单号，用于明细 remark 溯源。
        validated_items: order_batch_create 校验后的条目列表，需含
            shipment_plans / product_id / product / quantity。
        created_by: 提交订单的用户名，写入 plan.created_by 审计。

    Returns:
        同步的明细批次数（无计划条目时为 0，且不产生任何写操作）。

    Raises:
        ValueError: 客户名不在客户档案；或底层 create_plan/add_details 的
            校验失败（跨月、产品不存在等）——调用方据此回滚整组。
    """
    plan_items = [it for it in validated_items if it.get('shipment_plans')]
    if not plan_items:
        return 0

    # 客户名 → Customer.id（PurchasePlan.customer_id 是 customer 表外键）。
    # order.customer 是自由文本，历史数据可能不在档案中：报错让整组回滚，
    # 不做「自动建档」兜底（避免脏档案，见设计稿 Risks）。
    customer_row = await db.execute(select(Customer).where(Customer.name == customer_name))
    customer = customer_row.scalar_one_or_none()
    if customer is None:
        raise ValueError(f'客户档案中不存在客户「{customer_name}」，无法同步出货计划')

    # 分批版（2026-10-06 v2）：每个批次一条明细，按出货日期所在月分组
    # （计划明细不允许跨月，主单以月为单位）
    details_by_month: dict[str, list[dict]] = {}
    detail_count = 0
    for it in plan_items:
        for split in it['shipment_plans']:
            plan_date = normalize_plan_date(split['plan_date'])
            month = plan_date.strftime('%Y-%m')
            remark = f'来源订单:{order_no}'
            if split.get('note'):
                remark += f'；{split["note"]}'
            details_by_month.setdefault(month, []).append({
                'product_id': it['product_id'],
                'product_name': it['product'].name,
                'barcode': getattr(it['product'], 'barcode', '') or '',
                'quantity': split['quantity'],
                'plan_date': split['plan_date'],
                'remark': remark,
            })
            detail_count += 1

    # 一次性查齐涉及月份的既有计划（避免循环内逐月查询，N+1 门禁口径）
    plan_rows = await db.execute(
        select(PurchasePlan).where(
            PurchasePlan.customer_id == customer.id,
            PurchasePlan.plan_month.in_(list(details_by_month)),
        )
    )
    existing_by_month = {p.plan_month: p for p in plan_rows.scalars().all()}

    for month, details in details_by_month.items():
        existing = existing_by_month.get(month)
        if existing is not None:
            await add_details(db, existing.id, details)
            logger.info(
                '出货计划追加明细：%s 追加 %d 条（订单 %s）', existing.plan_no, len(details), order_no,
            )
        else:
            await create_plan(
                db,
                customer_id=customer.id,
                customer_name=customer_name,
                plan_month=month,
                details=details,
                remark=f'订单 {order_no} 自动同步',
                created_by=created_by,
            )

    return detail_count


async def purge_shipment_plan_details_for_order(db: AsyncSession, order_no: str) -> dict:
    """订单删除时级联清理其同步产生的采购计划明细（2026-10-06 删除联动）。

    匹配边界：remark 等于「来源订单:{order_no}」或以「来源订单:{order_no}；」开头
    （分号边界防止 PO-123 前缀误伤 PO-1234）。命中明细删除后，被删空的计划主单
    一并移除；受影响月份的计划缓存在事务提交后失效。

    必须在订单删除的同一事务内调用——级联失败会随订单删除一起回滚，
    不会出现「订单没了、计划还在」的中间态。

    Returns:
        {'detail_deleted': 明细条数, 'plan_deleted': 被删空移除的主单个数}
    """
    from sqlalchemy import delete, or_

    from fastapi_app.services import escape_like
    from fastapi_app.services.purchase_plan_common import (
        _invalidate_plan_caches,
        _schedule_post_commit,
    )

    prefix = f'来源订单:{escape_like(order_no)}'
    hit_rows = (await db.execute(
        select(PurchasePlanDetail.id, PurchasePlanDetail.plan_id)
        .where(or_(
            PurchasePlanDetail.remark == prefix,
            PurchasePlanDetail.remark.like(prefix + '；%'),
        ))
    )).all()
    if not hit_rows:
        return {'detail_deleted': 0, 'plan_deleted': 0}

    detail_ids = [r.id for r in hit_rows]
    plan_ids = list({r.plan_id for r in hit_rows})

    # 受影响月份先取出（主单删除后就取不到了）
    affected_months = sorted(set((await db.execute(
        select(PurchasePlan.plan_month).where(PurchasePlan.id.in_(plan_ids))
    )).scalars().all()))

    await db.execute(delete(PurchasePlanDetail).where(PurchasePlanDetail.id.in_(detail_ids)))

    # 被删空的计划主单一并移除（月历上留 0 明细的空壳没有意义）
    remaining_plan_ids = set((await db.execute(
        select(PurchasePlanDetail.plan_id)
        .where(PurchasePlanDetail.plan_id.in_(plan_ids))
        .group_by(PurchasePlanDetail.plan_id)
    )).scalars().all())
    emptied_ids = [pid for pid in plan_ids if pid not in remaining_plan_ids]
    plan_deleted = 0
    if emptied_ids:
        result = await db.execute(delete(PurchasePlan).where(PurchasePlan.id.in_(emptied_ids)))
        plan_deleted = result.rowcount or 0

    for month in affected_months:
        _schedule_post_commit(db, lambda m=month: _invalidate_plan_caches(m))

    logger.info(
        '订单删除级联清理出货计划：order_no=%s，明细 %d 条，删空主单 %d 个（%s）',
        order_no, len(detail_ids), plan_deleted, '、'.join(affected_months) or '-',
    )
    return {'detail_deleted': len(detail_ids), 'plan_deleted': plan_deleted}
