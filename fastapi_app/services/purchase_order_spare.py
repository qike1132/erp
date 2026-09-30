"""备品按部位损耗率重算（公式 A：瓶颈部位决定）。

公式与口径见 docs/purchase/备品数量按部位差异化损耗率计算方案.md：

    r_eff(SKU) = max{ 该 SKU 各部位行的 loss_rate }（NULL 行回退订单级 spare_rate）
    spare(SKU) = ceil(N_SKU × r_eff / 1000)
    spare(PO)  = Σ_SKU spare(SKU)

「部位」以采购明细行的粒度承载（一行布料 = 一个部位）——BOM 物料表没有部位字段，
故本模块按「该 SKU 的 BOM 物料集 → 匹配采购明细行」还原 SKU 的生效率集合。

**降级契约（任何一步不可得都不得抛错）**：
- SKU 快照表不可用        → 保持既有订单级口径 calc_spare_quantity(product_quantity, spare_rate)
- 产品/BOM 解析不出/无匹配 → 该 SKU 回退订单级 spare_rate
- 该单无 SKU 快照行        → 同上按订单级口径
"""
from __future__ import annotations

import logging
from collections import defaultdict

from sqlalchemy import or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.services.purchase_order_sku import po_sku_available
from fastapi_app.services.purchase_utils import calc_spare_quantity, normalize_spare_rate
from fastapi_app.shared_models import (
    Product,
    ProductAccessory,
    ProductFabric,
    ProductMaterial,
    PurchaseOrder,
    PurchaseOrderItem,
    PurchaseOrderSku,
)

logger = logging.getLogger(__name__)


def _item_key(item) -> tuple[str, str, str]:
    """采购明细行的「物料名 + 规格 + 单位」键，与 BOM 键同口径比对。"""
    return (item.material_name or '', item.specification or '', item.unit or '')


async def _load_bom_item_keys(
    db: AsyncSession, products: dict[int, str],
) -> dict[int, set[tuple[str, str, str]]]:
    """加载各产品的 BOM 物料键集合。

    Args:
        db: 异步会话。
        products: ``{product_id: 产品名}``（填充类物料名需要产品名拼接）。

    Returns:
        ``{product_id: {(物料名, 规格, 单位), ...}}``；读取失败时返回空 dict。

    命名口径**直接复用生成路径**的 ``_material_row``，避免两套规则静默失配。
    """
    if not products:
        return {}

    # 延迟导入：purchase_order_generate 在模块级导入 purchase_order_crud，
    # 而本模块被 purchase_order_crud 导入 —— 函数级导入解除循环依赖。
    from fastapi_app.services.purchase_order_generate import _MATERIAL_SPECS, _material_row

    pids = list(products)
    try:
        # savepoint 隔离：PG 下语句失败会中止事务，需回滚到保存点后继续
        async with db.begin_nested():
            filling = (await db.execute(
                select(ProductMaterial).where(ProductMaterial.product_id.in_(pids))
            )).scalars().all()
            fabrics = (await db.execute(
                select(ProductFabric).where(ProductFabric.product_id.in_(pids))
            )).scalars().all()
            accessories = (await db.execute(
                select(ProductAccessory).where(ProductAccessory.product_id.in_(pids))
            )).scalars().all()
    except SQLAlchemyError:
        logger.warning('BOM 读取失败，备品重算降级为订单级口径', exc_info=True)
        return {}

    rows_by_category: dict = {
        'filling': filling, 'fabric': fabrics, 'accessory': accessories,
    }
    keys: dict[int, set[tuple[str, str, str]]] = defaultdict(set)
    for spec in _MATERIAL_SPECS:
        for row in rows_by_category[spec.category]:
            product_name = products.get(row.product_id)
            if not product_name:
                continue
            # qty 传 0：本处只取物料名/规格/单位，数量不参与
            material = _material_row(spec, row, 0, product_name, '', '')
            keys[row.product_id].add(
                (material['material_name'], material['specification'], material['unit'])
            )
    return dict(keys)
