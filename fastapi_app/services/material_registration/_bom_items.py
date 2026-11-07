"""来料登记明细构建：采购明细 + BOM 补全行

采购单明细不一定覆盖产品 BOM 的全部物料（建单后 BOM 才补齐、或按供应商拆分时
只保留了部分行）。这里按工厂汇总同一口径把 BOM 行补进登记，供 /material 按
明细级供应商分组展示与收货。

数量口径与 ``services/purchase/_factory.py`` 的 BOM-only 行一致：
``单件用量 × 该 SKU 数量``（不含损耗加放），多 SKU 按物料聚合累加。
"""
from __future__ import annotations

import logging
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.float_utils import round_qty
from fastapi_app.services.purchase._common import (
    _resolve_pids_from_sku_lines,
    fetch_po_sku_lines_map,
    fetch_po_sku_pids_map,
)
from fastapi_app.services.purchase._list import _fetch_bom_data
from fastapi_app.services.purchase_order_sku import fetch_po_sku_map
from fastapi_app.shared_models import Product

logger = logging.getLogger(__name__)


def _material_key(material_name, specification, unit) -> tuple[str, str, str]:
    return (
        (material_name or '').strip(),
        (specification or '').strip(),
        (unit or '').strip(),
    )


def _po_item_row(item, default_supplier: str) -> dict:
    return {
        'order_item_id': item.id,
        'material_code': item.material_code or '',
        'material_name': item.material_name,
        'specification': item.specification or '',
        'unit': item.unit or '',
        'ordered_quantity': float(item.quantity or 0),
        'received_quantity': 0,
        'material_category': item.material_category or '',
        'supplier_name': item.supplier_name or default_supplier,
        'remark': item.remark or '',
    }


def _bom_row(bom: dict, quantity: float, default_supplier: str) -> dict:
    return {
        'order_item_id': None,
        'material_code': '',
        'material_name': bom['material_name'],
        'specification': bom['specification'],
        'unit': bom['unit'],
        'ordered_quantity': quantity,
        'received_quantity': 0,
        'material_category': bom['category'],
        'supplier_name': bom['supplier_name'] or default_supplier,
        'remark': '',
    }


async def aggregate_bom_rows(db: AsyncSession, order) -> list[dict]:
    """按用量×SKU数量聚合该采购单产品的全部 BOM 行（无采购明细也会返回）。"""
    sku_rows = await fetch_po_sku_map(db, [order.id])
    if not sku_rows.get(order.id):
        sku_rows = await fetch_po_sku_lines_map(db, [order])
    skus = sku_rows.get(order.id) or []

    pids_map = await fetch_po_sku_pids_map(db, [order])
    await _resolve_pids_from_sku_lines(db, pids_map, sku_rows)
    product_ids = pids_map.get(order.id) or []
    if not product_ids:
        return []

    name_rows = (await db.execute(
        select(Product.id, Product.name).where(Product.id.in_(product_ids))
    )).all()
    prod_name_map: dict[int, str] = {}
    for pid, name in name_rows:
        prod_name_map[pid] = name
    bom_data = await _fetch_bom_data(db, product_ids, prod_name_map)

    pid_by_name = {name: pid for pid, name in prod_name_map.items()}
    qty_by_pid: dict[int, float] = {}
    for sku in skus:
        pid = pid_by_name.get((sku.get('product_name') or '').strip())
        if pid:
            qty_by_pid[pid] = qty_by_pid.get(pid, 0.0) + float(sku.get('order_qty') or 0)

    if not qty_by_pid:
        # 无 SKU 快照：按订单总量回退到首个产品（与工厂汇总回退口径一致）
        qty_by_pid = {product_ids[0]: float(order.product_quantity or 0)}

    aggregated: dict[tuple[tuple[str, str, str], str], dict] = {}
    for pid, qty in qty_by_pid.items():
        for bom in bom_data.get(pid, []):
            key = (_material_key(bom['material_name'], bom['specification'], bom['unit']),
                   bom['supplier_name'] or '')
            amount = round_qty(float(bom['quantity'] or 0) * qty)
            existing = aggregated.get(key)
            if existing:
                existing['ordered_quantity'] = round_qty(existing['ordered_quantity'] + amount)
            else:
                aggregated[key] = _bom_row(bom, amount, '')
    return list(aggregated.values())


async def build_registration_items(
    db: AsyncSession, order, po_items: Sequence,
) -> list[dict]:
    """采购明细行 + BOM 中未被采购明细覆盖的物料行（明细级供应商）。"""
    default_supplier = order.supplier_name or ''
    rows = [_po_item_row(item, default_supplier) for item in po_items]
    covered = {
        _material_key(item.material_name, item.specification, item.unit)
        for item in po_items
    }

    try:
        bom_rows = await aggregate_bom_rows(db, order)
    except Exception:  # broad-except: BOM 补全失败不能阻断采购完成/登记创建
        logger.warning(
            '来料登记补全 BOM 行失败，仅保留采购明细 order_id=%s', order.id, exc_info=True,
        )
        return rows

    for bom in bom_rows:
        if _material_key(
            bom['material_name'], bom['specification'], bom['unit'],
        ) in covered:
            continue
        if not bom['supplier_name']:
            bom['supplier_name'] = default_supplier
        rows.append(bom)
    return rows
