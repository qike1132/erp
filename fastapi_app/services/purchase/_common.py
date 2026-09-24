"""采购查询公共辅助

从 purchase_order_query_helpers.py 按主题拆出,行为与原实现完全一致。
"""
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.services.purchase_utils import parse_source_order_ids

logger = logging.getLogger(__name__)


def _parse_source_order_ids(po) -> list[int]:
    """解析采购订单关联的客户订单ID列表

    合并单值字段 source_order_id 与多值字段 source_order_ids（JSON/list）。
    多值字段的解析委托给 purchase_utils.parse_source_order_ids。
    """
    ids: list[int] = []
    if po.source_order_id:
        ids.append(po.source_order_id)
    ids.extend(parse_source_order_ids(po.source_order_ids))
    return ids


async def fetch_po_sku_pids_map(db: AsyncSession, orders) -> dict[int, list[int]]:
    """采购单 → 该采购单覆盖的**全部 SKU** 的 product_id（去重、保持出现顺序）。

    为什么必须遍历 ``OrderItem``：多 SKU 模型下 ``Order.product_id`` 只是
    **首个** SKU 的兼容值（``Order.quantity`` 是所有 SKU 之和）。任何「按采购单
    展开 BOM 物料 / 解析产品名」的汇总口径若读这两个兼容字段，就只会得到首个
    SKU 的物料与名称 —— 表现为「汇总下单只有一个 SKU」且其余 SKU 的物料漏出采购单。

    回退链与 ``_list._build_po_source_sku_map`` 同口径：OrderItem → Order 兼容
    字段 → StockIn 兼容字段；仅对**没有任何 OrderItem 覆盖**的 source id 回退，
    避免 Order/StockIn 的 id 空间重叠造成串号。

    Returns:
        ``{po_id: [product_id, ...]}``；无任何来源时对应空列表。
    """
    po_source_ids_map: dict[int, list[int]] = {}
    all_source_ids: set[int] = set()
    for po in orders:
        ids = _parse_source_order_ids(po)
        po_source_ids_map[po.id] = ids
        all_source_ids.update(ids)

    result: dict[int, list[int]] = {po_id: [] for po_id in po_source_ids_map}
    if not all_source_ids:
        return result

    from fastapi_app.shared_models import StockIn
    from fastapi_app.shared_models.order import Order
    from fastapi_app.shared_models.order_item import OrderItem

    pids_by_source: dict[int, list[int]] = {}
    covered: set[int] = set()

    item_rows = await db.execute(
        select(OrderItem.order_id, OrderItem.product_id)
        .where(OrderItem.order_id.in_(all_source_ids))
        .order_by(OrderItem.order_id, OrderItem.id)
    )
    for sid, pid in item_rows.all():
        pids_by_source.setdefault(sid, []).append(pid)
        covered.add(sid)

    fallback_ids = all_source_ids - covered
    if fallback_ids:
        order_rows = await db.execute(
            select(Order.id, Order.product_id).where(Order.id.in_(fallback_ids))
        )
        for sid, pid in order_rows.all():
            pids_by_source.setdefault(sid, []).append(pid)
            covered.add(sid)

        stockin_ids = fallback_ids - covered
        if stockin_ids:
            stockin_rows = await db.execute(
                select(StockIn.id, StockIn.product_id).where(StockIn.id.in_(stockin_ids))
            )
            for sid, pid in stockin_rows.all():
                pids_by_source.setdefault(sid, []).append(pid)

    for po_id, source_ids in po_source_ids_map.items():
        ordered: list[int] = []
        for sid in source_ids:
            for pid in pids_by_source.get(sid, []):
                if pid and pid not in ordered:
                    ordered.append(pid)
        result[po_id] = ordered
    return result


async def fetch_po_sku_lines_map(db: AsyncSession, orders) -> dict[int, list[dict]]:
    """采购单 → 逐 SKU 明细（**回退口径**，用于 ``purchase_order_sku`` 无快照时）。

    Why：``purchase_order_sku`` 是迁移 047 之后才落库的（且历史单靠回填脚本补齐），
    对没有快照的采购单必须仍能给出逐 SKU 明细，否则前端「逐 SKU 分行」会突然空掉。

    口径与 ``_list._build_po_source_sku_map`` 同源：OrderItem 优先（带产品名与条码
    快照），无 OrderItem 的 source id 回退 Order → StockIn 兼容字段。
    同一采购单内按 (产品名, 条码) 合并、数量相加。

    Returns:
        ``{po_id: [{'product_name', 'product_barcode', 'order_qty'}, ...]}``
    """
    from fastapi_app.services.purchase_order_sku import merge_sku_lines

    po_source_ids_map: dict[int, list[int]] = {}
    all_source_ids: set[int] = set()
    for po in orders:
        ids = _parse_source_order_ids(po)
        po_source_ids_map[po.id] = ids
        all_source_ids.update(ids)

    result: dict[int, list[dict]] = {po_id: [] for po_id in po_source_ids_map}
    if not all_source_ids:
        return result

    from fastapi_app.shared_models import Product, StockIn
    from fastapi_app.shared_models.order import Order
    from fastapi_app.shared_models.order_item import OrderItem

    lines_by_source: dict[int, list[dict]] = {}
    covered: set[int] = set()

    item_rows = await db.execute(
        select(
            OrderItem.order_id, OrderItem.product_name,
            OrderItem.product_barcode, OrderItem.quantity,
        )
        .where(OrderItem.order_id.in_(all_source_ids))
        .order_by(OrderItem.order_id, OrderItem.id)
    )
    for sid, name, barcode, qty in item_rows.all():
        lines_by_source.setdefault(sid, []).append({
            'product_name': name or '', 'product_barcode': barcode or '', 'order_qty': qty,
        })
        covered.add(sid)

    fallback_ids = all_source_ids - covered
    if fallback_ids:
        order_rows = await db.execute(
            select(Order.id, Product.name, Product.barcode, Order.quantity)
            .join(Product, Order.product_id == Product.id)
            .where(Order.id.in_(fallback_ids))
        )
        for sid, name, barcode, qty in order_rows.all():
            lines_by_source.setdefault(sid, []).append({
                'product_name': name or '', 'product_barcode': barcode or '', 'order_qty': qty,
            })
            covered.add(sid)

        stockin_ids = fallback_ids - covered
        if stockin_ids:
            stockin_rows = await db.execute(
                select(StockIn.id, Product.name, Product.barcode, StockIn.quantity)
                .join(Product, StockIn.product_id == Product.id)
                .where(StockIn.id.in_(stockin_ids))
            )
            for sid, name, barcode, qty in stockin_rows.all():
                lines_by_source.setdefault(sid, []).append({
                    'product_name': name or '', 'product_barcode': barcode or '', 'order_qty': qty,
                })

    for po_id, source_ids in po_source_ids_map.items():
        flat: list[dict] = []
        for sid in source_ids:
            flat.extend(lines_by_source.get(sid, []))
        result[po_id] = merge_sku_lines(flat)
    return result
