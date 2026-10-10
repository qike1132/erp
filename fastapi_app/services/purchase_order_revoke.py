"""撤销「已失效来源」对应的 pending 采购单。

**三条来源失效路径共用同一套撤销逻辑**（`_revoke_targets`）：否则会留下拿着已不存在来源
的单，且来源订单停在「已备货」再也无法重生成：

1. **删空某产品 BOM**（`revoke_pending_purchase_orders_for_product`）：该产品的物料没了，
   按旧 BOM 生成的单不该留；只处理「删空」，改 BOM（BOM 还在）不动，避免反复重下单丢损耗率。
2. **删除备货记录 StockIn**（`revoke_pending_purchase_orders_for_stockin`）：来源记录没了，
   引用它的 pending 单是孤儿。**备货删除此前漏了这条清理。**
3. **删除客户订单 Order**（`revoke_pending_purchase_orders_for_order`，ORDER_DELETED 订阅调用）：
   与旧 `cleanup_orphan_pending_purchase_orders` 的区别是**会重算同单其余来源订单的状态**——
   一张采购单按客户聚合、可能覆盖同客户多张订单，删一张会把其余订单永久卡在「已备货」。

撤销后把来源**订单**状态重算回真实值（没备货/出货 → 回「待备货」），订单就能重新出现在
「待生成」里、来源恢复后照常自动生成。**已下单完成**的采购单不动（那是已发生的历史）。
"""
import logging
from functools import partial

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def _revoke_targets(db: AsyncSession, targets: list) -> dict:
    """撤销给定的 pending 采购单，并把其来源订单状态重算回真实值。调用方负责事务。"""
    if not targets:
        return {'revoked': 0, 'orders_reset': 0}

    from fastapi_app.services.order_utils import compute_order_status_from_db
    from fastapi_app.services.purchase_order_crud import delete_purchase_order
    from fastapi_app.shared_models import Order
    from fastapi_app.shared_models.purchase_order import PurchaseOrderSku

    # 受影响来源**订单**：只认 sku 行里 source_record_type='order' 的，
    # 避开 order.id 与 stockin.id 撞号（见 shared_models/purchase_order.py 的说明）。
    order_ids = {
        sid for _po, sid in (await db.execute(
            select(PurchaseOrderSku.po_id, PurchaseOrderSku.source_order_id).where(
                PurchaseOrderSku.po_id.in_([po.id for po in targets]),
                PurchaseOrderSku.source_record_type == 'order',
            )
        )).all() if sid
    }

    for po in targets:
        await delete_purchase_order(db, po.id)  # 一并清明细 + SKU 快照

    orders_reset = 0
    if order_ids:
        orders = list((await db.execute(
            select(Order).where(Order.id.in_(order_ids))
        )).scalars().all())
        for order in orders:
            new_status = await compute_order_status_from_db(db, order)
            if new_status != order.status:
                order.status = new_status
                orders_reset += 1
        await db.flush()

    return {'revoked': len(targets), 'orders_reset': orders_reset}


async def revoke_pending_purchase_orders_for_product(db: AsyncSession, product_id: int) -> dict:
    """若该产品当前**已无任何 BOM 物料**，撤销其 pending 采购单并重算来源订单状态。

    Returns:
        dict: ``{'revoked': 撤销的采购单数, 'orders_reset': 状态被改写的订单数}``。
    """
    from fastapi_app.services.purchase._common import fetch_po_sku_pids_map
    from fastapi_app.services.purchase._unprocessed import _fetch_bom_product_ids
    from fastapi_app.shared_models.purchase_order import PurchaseOrder, PurchaseOrderStatus

    # 仍有 BOM 物料 → 不动（本函数只处理「删空」）。
    # 复用未处理列表的同一口径（三类 BOM 表 UNION ALL 一次查完），单条查询无 N+1。
    if await _fetch_bom_product_ids(db, [product_id]):
        return {'revoked': 0, 'orders_reset': 0}

    # 覆盖该产品的 pending 采购单（按 SKU 快照映射到 product_id，与汇总口径同源）
    pending = list((await db.execute(
        select(PurchaseOrder).where(PurchaseOrder.status == PurchaseOrderStatus.PENDING)
    )).scalars().unique().all())
    if not pending:
        return {'revoked': 0, 'orders_reset': 0}
    pids_map = await fetch_po_sku_pids_map(db, pending)
    targets = [po for po in pending if product_id in pids_map.get(po.id, [])]

    result = await _revoke_targets(db, targets)
    logger.info('删空 BOM 撤销 pending 采购单: product_id=%s %s', product_id, result)
    return result


async def _revoke_by_source(db: AsyncSession, record_type: str, source_id: int) -> dict:
    """按「来源记录类型 + id」撤销引用它的 pending 采购单（SKU 快照精确匹配）。

    用 ``source_record_type`` 判别而非裸 id：本仓 ``order.id`` 与 ``stockin.id`` 会撞号
    （见 shared_models/purchase_order.py），裸 id 匹配会误删他类来源的单。
    """
    from fastapi_app.shared_models.purchase_order import PurchaseOrder, PurchaseOrderSku, PurchaseOrderStatus

    po_ids = {
        po_id for (po_id,) in (await db.execute(
            select(PurchaseOrderSku.po_id).where(
                PurchaseOrderSku.source_record_type == record_type,
                PurchaseOrderSku.source_order_id == source_id,
            )
        )).all()
    }
    if not po_ids:
        return {'revoked': 0, 'orders_reset': 0}

    targets = list((await db.execute(
        select(PurchaseOrder).where(
            PurchaseOrder.id.in_(po_ids),
            PurchaseOrder.status == PurchaseOrderStatus.PENDING,
        )
    )).scalars().unique().all())

    result = await _revoke_targets(db, targets)
    logger.info('删除来源记录撤销 pending 采购单: %s=%s %s', record_type, source_id, result)
    return result


async def revoke_pending_purchase_orders_for_order(db: AsyncSession, order_id: int) -> dict:
    """删除客户订单后，撤销引用它的 pending 采购单，并重算**其余**来源订单的状态。

    与 ORDER_DELETED 订阅配套。比旧的 ``cleanup_orphan_pending_purchase_orders`` 多一步：
    把同张采购单里**其他**来源订单的状态重算回真实值——否则删一张单会把同客户其余订单
    永久卡在「已备货」（它们不会再有采购单，也回不到「待生成」）。

    Returns:
        dict: ``{'revoked': ..., 'orders_reset': ...}``。
    """
    return await _revoke_by_source(db, 'order', order_id)


async def revoke_pending_purchase_orders_for_stockin(db: AsyncSession, stockin_id: int) -> dict:
    """删除备货记录后，撤销引用它的 pending 采购单并重算来源订单状态。

    与客户订单删除走 ORDER_DELETED 事件清理同款；备货删除此前漏了这条清理。

    Returns:
        dict: ``{'revoked': ..., 'orders_reset': ...}``。
    """
    return await _revoke_by_source(db, 'stockin', stockin_id)


async def _run_stockin_deleted(stockin_id: int) -> None:
    """备货记录删除提交后：撤销其 pending 采购单 + 失效采购缓存（best-effort）。"""
    try:
        from fastapi_app.core.database import require_async_session_local
        from fastapi_app.core.exceptions import db_transaction
        from fastapi_app.services.purchase._auto_generate import invalidate_purchase_caches

        session_factory = require_async_session_local()
        async with session_factory() as db:
            async with db_transaction(db):
                await revoke_pending_purchase_orders_for_stockin(db, stockin_id)
        await invalidate_purchase_caches()
    except Exception:  # broad-except: 清理失败不得影响备货删除主流程
        logger.warning('删除备货记录后撤销采购单失败（不影响本次删除）', exc_info=True)


def schedule_stockin_deleted_side_effects(session, stockin_id: int) -> None:
    """注册「备货记录删除提交成功后」的撤销副作用。

    与 ``_auto_generate.schedule_*`` 同款：回调挂到 ``session.info['post_commit_callbacks']``，
    由 ``db_transaction`` / ``get_async_db`` 在提交成功后执行。
    """
    info = getattr(session, 'info', None)
    if not isinstance(info, dict):
        return
    info.setdefault('post_commit_callbacks', []).append(partial(_run_stockin_deleted, stockin_id))
