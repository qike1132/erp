"""
出货计划准入校验：订单余量（取代原库存校验）

背景（2026-09 用户裁决）：
    「排产日历」上的计划只要对应订单还有数量（订单余量 > 0）就允许添加，
    不再因库存不足而拦截。库存是生产/备货进度问题，不是「能不能排产」的
    准入条件 —— 原 `_check_inventory_realtime` 把两件事混在一起，导致
    「有订单、没备货」的正当计划无法录入。

口径（与 /stock 页「订单数量」列同源，见 stock_inventory_service）：
    订单余量 = GREATEST(0, 订单量 - 独立出货量)
      · 订单量：order_item 优先，无明细的兼容订单回退 order.quantity
      · 已软删除订单（is_deleted）不计入
      · 扣减量为 stock_out 中 stockin_id IS NULL 的全部出货（无论是否关联
        order_id）；备货抵扣出货（stockin_id 非空）消耗的是备货而非订单，
        故不扣减。与库存 CTE 的 stockout_agg 过滤条件一致。

判定粒度：
    按 (客户名, 产品名) 维度聚合 —— 与计划明细的 (customer_name, product_name)
    一一对应，也与此前库存校验的 key 粒度一致。
"""
import logging

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.shared_models import Order, OrderItem, Product, StockOut

logger = logging.getLogger(__name__)


async def get_order_remaining_map(db: AsyncSession, pairs: list[tuple[str, str]]) -> dict[tuple[str, str], int]:
    """批量查询 (客户名, 产品名) 维度的订单余量

    Args:
        db: 异步数据库会话。
        pairs: [(客户名, 产品名), ...]，空项会被忽略。

    Returns:
        {(客户名, 产品名): 余量}；只包含余量 > 0 的键 —— 余量为 0 与
        「查不到订单」对调用方是同一结论（不可添加），无需区分。
    """
    wanted = {(c, p) for c, p in pairs if c and p}
    if not wanted:
        return {}
    order_map = await _fetch_order_qty(db, wanted)
    if not order_map:
        return {}
    shipped_map = await _fetch_shipped_qty(db, wanted)
    remaining: dict[tuple[str, str], int] = {}
    for key, order_qty in order_map.items():
        left = order_qty - shipped_map.get(key, 0)
        if left > 0:
            remaining[key] = left
    return remaining


async def _fetch_order_qty(db: AsyncSession, wanted: set[tuple[str, str]]) -> dict[tuple[str, str], int]:
    """订单量：多 SKU 按 OrderItem 聚合，无明细订单回退订单级数量

    与库存 CTE 的 order_agg 同口径：COALESCE(oi.quantity, o.quantity) 按
    (客户, 产品) 求和。有明细的订单走 OrderItem 分支，仅有订单级产品的
    兼容订单（批量导入路径）走 Order.quantity 回退 —— 两者由 COALESCE 统一，
    不会重复计数。

    Product 用内连接：这是「按产品名聚合」的载体，同时天然剔除
    产品 ID 全为空的订单行（无需额外的 WHERE 谓词）。
    """
    customers = {c for c, _ in wanted}
    names = {p for _, p in wanted}
    stmt = (
        select(
            Order.customer,
            Product.name.label('product_name'),
            func.sum(func.coalesce(OrderItem.quantity, Order.quantity)).label('order_qty'),
        )
        .select_from(Order)
        .outerjoin(OrderItem, OrderItem.order_id == Order.id)
        .join(Product, Product.id == func.coalesce(OrderItem.product_id, Order.product_id))
        .where(
            Order.is_deleted.isnot(True),
            Order.customer.in_(customers),
            Product.name.in_(names),
        )
        .group_by(Order.customer, Product.name)
    )
    rows = (await db.execute(stmt)).all()
    return {
        (row.customer, row.product_name): int(row.order_qty or 0)
        for row in rows
        if (row.customer, row.product_name) in wanted
    }


async def _fetch_shipped_qty(db: AsyncSession, wanted: set[tuple[str, str]]) -> dict[tuple[str, str], int]:
    """已抵消订单的出货量

    只取 stockin_id IS NULL 的行（独立出货）；stockin_id 非空的出货是
    「备货抵扣」，扣的是备货而非订单 —— 与库存 CTE 的 stockout_agg 同过滤条件。
    """
    customers = {c for c, _ in wanted}
    names = {p for _, p in wanted}
    stmt = (
        select(
            StockOut.customer,
            Product.name.label('product_name'),
            func.sum(StockOut.quantity - StockOut.returned_quantity).label('shipped_qty'),
        )
        .join(Product, Product.id == StockOut.product_id)
        .where(
            StockOut.stockin_id.is_(None),
            StockOut.customer.in_(customers),
            Product.name.in_(names),
        )
        .group_by(StockOut.customer, Product.name)
    )
    rows = (await db.execute(stmt)).all()
    return {
        (row.customer, row.product_name): int(row.shipped_qty or 0)
        for row in rows
        if (row.customer, row.product_name) in wanted
    }


def collect_without_order(
    remaining_map: dict[tuple[str, str], int],
    items: list[dict],
) -> list[dict]:
    """收集「无订单余量」的明细行

    Args:
        remaining_map: get_order_remaining_map 的返回值。
        items: [{'customer_name': str, 'product_name': str}, ...]

    Returns:
        [{'customer_name': str, 'product_name': str}, ...]，按输入顺序、去重。
    """
    missing: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for it in items:
        key = (it.get('customer_name', ''), it.get('product_name', ''))
        if not key[0] or not key[1]:
            continue
        if remaining_map.get(key, 0) > 0:
            continue
        if key in seen:
            continue
        seen.add(key)
        missing.append({'customer_name': key[0], 'product_name': key[1]})
    return missing


def format_without_order_error(missing: list[dict]) -> str:
    """格式化「无订单余量」错误信息（面向用户的单行文案）"""
    parts = [f"{it['customer_name']} / {it['product_name']}" for it in missing]
    return '、'.join(parts)


async def check_order_remaining(db: AsyncSession, items: list[dict]) -> list[dict]:
    """出货计划准入校验：明细必须对应「订单余量 > 0」的客户+产品

    Args:
        db: 异步数据库会话。
        items: [{'customer_name': str, 'product_name': str}, ...]。

    Returns:
        无订单余量的明细项列表；空列表表示全部通过。
    """
    pairs = [(it.get('customer_name', ''), it.get('product_name', '')) for it in items]
    remaining_map = await get_order_remaining_map(db, pairs)
    return collect_without_order(remaining_map, items)
