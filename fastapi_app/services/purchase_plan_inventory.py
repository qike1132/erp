"""
采购计划库存相关辅助：库存映射与实时库存校验

职责：
    - 库存查找字典缓存（_get_inventory_map）
    - 实时库存校验链（_fetch_barcode_stock / _fetch_name_stock /
      _aggregate_barcode_demand / _aggregate_name_demand / _collect_insufficient /
      _check_inventory_realtime）

从 purchase_plan_crud.py 拆分而来，保持函数签名不变。
"""
import asyncio
import json
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.redis_wrapper import safe_get, safe_set
from fastapi_app.services.plan_utils import build_inventory_map
from fastapi_app.shared_models import Product

# 与原 purchase_plan_crud 模块共享同一 logger 实例，保持日志行为不变
logger = logging.getLogger('fastapi_app.services.purchase_plan_crud')

INVENTORY_CACHE_PREFIX = 'inventory'
INVENTORY_CACHE_TTL = 300


async def _get_inventory_map(db: AsyncSession) -> dict:
    """
    获取库存查找字典 key=(customer_name, product_name) value=total_stock
    优先从 Redis 缓存读取，缓存未命中则查询 stock_service
    超时保护：asyncio.timeout(8) 防止 _fetch_inventory 的4条聚合SQL长时间阻塞
    """
    cached = await safe_get(f'{INVENTORY_CACHE_PREFIX}:map', context='库存映射缓存')  # sql-safe: escape_like/绑定参数/常量片段
    if cached is not None:
        return {tuple(json.loads(k)): v for k, v in cached.items()}
    try:
        async with asyncio.timeout(8):
            from fastapi_app.services import stock_service
            inventory_result = await stock_service.get_inventory(db)
        mapping = build_inventory_map(inventory_result['inventory_data'])
    except TimeoutError:
        logger.error('库存查询超时(8s)，返回空映射降级')
        return {}
    except (ValueError, TypeError, OSError) as e:
        logger.warning(f'获取库存数据失败: {e}')
        return {}
    cacheable = {json.dumps(k): v for k, v in mapping.items()}
    await safe_set(f'{INVENTORY_CACHE_PREFIX}:map', cacheable, timeout=INVENTORY_CACHE_TTL, context='库存映射缓存')  # sql-safe: escape_like/绑定参数/常量片段
    return mapping


async def _fetch_barcode_stock(db: AsyncSession, barcode_items: list[dict], *, with_for_update: bool=False) -> dict[str, dict]:
    """通过 barcode 查询库存, 返回 {barcode: {'name': str, 'current_stock': int}}

    B1 修复：with_for_update=True 时附加 SELECT ... FOR UPDATE 行级锁，
    防止 TOCTOU 竞态（校验通过后并发请求仍能修改库存）。
    """
    if not barcode_items:
        return {}
    barcodes = list({item['barcode'] for item in barcode_items})
    stmt = select(Product.id, Product.barcode, Product.name, Product.current_stock).where(Product.barcode.in_(barcodes))
    if with_for_update:
        stmt = stmt.with_for_update()
    result = await db.execute(stmt)
    return {row.barcode: {'name': row.name, 'current_stock': row.current_stock or 0} for row in result.all()}


async def _fetch_name_stock(db: AsyncSession, name_items: list[dict], *, with_for_update: bool=False) -> dict[str, dict]:
    """通过 product_name 查询库存(barcode 为空时), 返回 {name: {'current_stock': int}}

    B1 修复：with_for_update=True 时附加 SELECT ... FOR UPDATE 行级锁。
    """
    if not name_items:
        return {}
    names = list({item['product_name'] for item in name_items if item.get('product_name')})
    if not names:
        return {}
    stmt = select(Product.id, Product.name, Product.current_stock).where(Product.name.in_(names))
    if with_for_update:
        stmt = stmt.with_for_update()
    result = await db.execute(stmt)
    return {row.name: {'current_stock': row.current_stock or 0} for row in result.all()}


def _aggregate_barcode_demand(barcode_items: list[dict], product_stock_map: dict[str, dict]) -> dict[str, dict]:
    """按 barcode 汇总需求量"""
    demand_map: dict[str, dict] = {}
    for item in barcode_items:
        barcode = item['barcode']
        if barcode not in demand_map:
            info = product_stock_map.get(barcode)
            demand_map[barcode] = {'product_name': item.get('product_name', '') or (info['name'] if info else ''), 'total_quantity': 0, 'current_stock': info['current_stock'] if info else 0}
        demand_map[barcode]['total_quantity'] += item['quantity']
    return demand_map


def _aggregate_name_demand(name_items: list[dict], name_stock_map: dict[str, dict]) -> dict[str, dict]:
    """按 product_name 汇总无 barcode 的项"""
    name_demand_map: dict[str, dict] = {}
    for item in name_items:
        pname = item.get('product_name', '')
        if not pname:
            continue
        if pname not in name_demand_map:
            info = name_stock_map.get(pname)
            name_demand_map[pname] = {'product_name': pname, 'total_quantity': 0, 'current_stock': info['current_stock'] if info else 0}
        name_demand_map[pname]['total_quantity'] += item['quantity']
    return name_demand_map


def _collect_insufficient(demand_map: dict[str, dict], name_demand_map: dict[str, dict]) -> list[dict]:
    """收集库存不足项"""
    insufficient = []
    for barcode, demand in demand_map.items():
        if demand['current_stock'] < demand['total_quantity']:
            insufficient.append({'barcode': barcode, 'product_name': demand['product_name'], 'total_quantity': demand['total_quantity'], 'current_stock': demand['current_stock']})
    for pname, demand in name_demand_map.items():
        if demand['current_stock'] < demand['total_quantity']:
            insufficient.append({'barcode': '', 'product_name': pname, 'total_quantity': demand['total_quantity'], 'current_stock': demand['current_stock']})
    return insufficient


async def _check_inventory_realtime(db: AsyncSession, items: list[dict], *, with_for_update: bool=False) -> list[dict]:
    """
    实时库存校验（直接查数据库，不经过缓存）
    同一 barcode 多条记录会汇总需求量后与库存比较
    无 barcode 时按 product_name 匹配

    参数:
        items: [{'barcode': str, 'product_name': str, 'quantity': int}, ...]
        with_for_update: True 时附加 SELECT ... FOR UPDATE 行级锁，防止
                         TOCTOU 竞态（写入路径 create_plan/add_details/update_detail/
                         confirm_staging 必须传 True）。读取路径（validate_staging
                         仅作提示）可传 False。
    返回:
        库存不足项列表 [{'barcode': str, 'product_name': str, 'total_quantity': int, 'current_stock': int}, ...]
    """
    if not items:
        return []

    barcode_items = [item for item in items if item.get('barcode')]
    name_items = [item for item in items if not item.get('barcode')]

    product_stock_map = await _fetch_barcode_stock(db, barcode_items, with_for_update=with_for_update)
    name_stock_map = await _fetch_name_stock(db, name_items, with_for_update=with_for_update)

    demand_map = _aggregate_barcode_demand(barcode_items, product_stock_map)
    name_demand_map = _aggregate_name_demand(name_items, name_stock_map)

    return _collect_insufficient(demand_map, name_demand_map)
