"""
采购计划库存相关辅助：库存查找字典缓存

职责：
    - 库存查找字典缓存（_get_inventory_map）

历史：本模块原含实时库存校验链（_fetch_barcode_stock / _fetch_name_stock /
     _aggregate_barcode_demand / _aggregate_name_demand / _collect_insufficient /
     _check_inventory_realtime）。2026-09 用户裁决后，出货计划的准入条件
     由「库存充足」改为「订单余量 > 0」（见 purchase_plan_order_quota.py），
     该链条零调用点，已随本次改动删除。

从 purchase_plan_crud.py 拆分而来，保持函数签名不变。
"""
import asyncio
import json
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.redis_wrapper import safe_get, safe_set
from fastapi_app.services.plan_utils import build_inventory_map

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
