"""采购单子表清理（删除路径的唯一实现）。

背景（2026-10-30 审计 A-M19）：采购单有三条删除路径——
``purchase_order_crud.delete_purchase_order``（单张）、
``purchase_bom_copy_service.batch_delete_purchase_orders``（批量）、
``purchase_order_query.cleanup_orphan_pending_purchase_orders``（订单删除兜底）——
子表清理方式各写一遍，其中两处直接 ``db.delete(po)`` 依赖 ORM 级联。

问题在于 ``PurchaseOrder.items`` / ``skus`` 都是 ``lazy='raise'``：级联删除需要
先把集合加载出来，flush 时会抛 ``InvalidRequestError``（不是 FK 冲突，报文也更难懂）；
而 ``purchase_order_item`` 的 FK 是 NO ACTION，一旦没删干净就是 409/500。

因此把「删子表」收敛成一份**批量显式 DELETE**：不触碰 ORM 集合、不依赖数据库
外键级联开关（SQLite 测试库默认不开），三条路径都先调它再删主表。
"""
import logging

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.shared_models import PurchaseOrderItem, PurchaseOrderSku

logger = logging.getLogger(__name__)


async def purge_purchase_order_children(db: AsyncSession, order_ids: list[int]) -> int:
    """删除给定采购单的全部子表行（明细 + 逐 SKU 快照），返回最小影响行数。

    调用方必须**先**校验来料登记等阻断条件：``purchase_order_item`` 被
    ``material_registration_item`` 以 NO ACTION 引用，带登记的单据本来就该拒绝删除。
    """
    ids = [int(i) for i in order_ids if i is not None]
    if not ids:
        return 0
    items = await db.execute(
        delete(PurchaseOrderItem).where(PurchaseOrderItem.order_id.in_(ids))
    )
    await db.execute(
        delete(PurchaseOrderSku).where(PurchaseOrderSku.po_id.in_(ids))
    )
    # rowcount 只用于日志：某些异步驱动/替身不提供该属性，不能因此让删除失败
    affected = int(getattr(items, 'rowcount', 0) or 0)
    logger.debug('采购单子表清理: orders=%s items=%d', ids, affected)
    return affected
