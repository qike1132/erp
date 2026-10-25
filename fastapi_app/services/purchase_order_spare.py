"""备品按部位损耗率重算（公式 A：瓶颈部位决定）。

公式与口径见 docs/purchase/备品数量按部位差异化损耗率计算方案.md：

    r_eff(SKU) = max{ 该 SKU 各部位行的 loss_rate }（NULL 行回退订单级 spare_rate）
    spare(SKU) = ceil(N_SKU × r_eff / 1000)
    spare(PO)  = Σ_SKU spare(SKU)

「部位」以采购明细行的粒度承载（一行布料 = 一个部位）——BOM 物料表没有部位字段，
故本模块按「该 SKU 的 BOM 物料集 → 匹配采购明细行」还原 SKU 的生效率集合。

**降级契约（任何一步不可得都不得抛错）**：
- SKU 快照表不可用        → 保持既有订单级口径 calc_spare_quantity(product_quantity, spare_rate)
- 产品/BOM 解析不出/无匹配 → 该 SKU 降级为「该单全部明细的 max」（spec §2.2/§4），记 warning
- 该单无 SKU 快照行        → 保持既有订单级口径（合法旧单，不属降级噪声源，静默）

**未接线（L-5 判定，2026-10-25 上线前审计）**：``recompute_po_spare_from_item_rates``
当前仅被 fastapi_app/tests/services/test_po_spare_from_part_rates.py 引用，
生产导入图不可达（check_orphan_modules 亦如实 WARN）。本模块是已实现待接线的
特性（规格文档 + 3 个特性提交 + 全套降级链），**不是死代码，勿删**；何时在
采购完成/保存链路调用属产品决策，接线前保持本模块 lint-clean + 测试绿，
孤儿检查的 WARN 即其"未接线"状态的显式标记。
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


async def _resolve_products(db: AsyncSession, skus) -> tuple[dict, dict, dict]:
    """按 SKU 快照解析产品：条码优先、名称回退（``product.name`` 全局唯一）。

    Returns:
        ``(by_barcode, by_name, name_by_pid)``；任何查询失败返回三个空 dict。
    """
    names = {(s.product_name or '').strip() for s in skus if s.product_name}
    barcodes = {(s.product_barcode or '').strip() for s in skus if s.product_barcode}
    clauses = []
    if names:
        clauses.append(Product.name.in_(names))
    if barcodes:
        clauses.append(Product.barcode.in_(barcodes))
    if not clauses:
        return {}, {}, {}
    try:
        async with db.begin_nested():
            rows = (await db.execute(
                select(Product.id, Product.name, Product.barcode).where(or_(*clauses))
            )).all()
    except SQLAlchemyError:
        logger.warning('产品解析失败，备品重算降级为订单级口径', exc_info=True)
        return {}, {}, {}
    by_barcode = {r.barcode: r.id for r in rows if r.barcode}
    by_name = {r.name: r.id for r in rows if r.name}
    name_by_pid = {r.id: r.name for r in rows if r.name}
    return by_barcode, by_name, name_by_pid


def _match_part_items(items, keys) -> list:
    """明细行中「物料键命中该 SKU BOM 键集合」的子集（无键时为空列表）。"""
    return [it for it in items if _item_key(it) in keys] if keys else []


def _rates_max(rows, order_rate: float | None) -> float:
    """一组明细行的损耗率最大值。

    行为空 → 0.0；行率为 NULL → 回退 ``order_rate``，仍为 NULL 者不参与 max；
    ``normalize_spare_rate`` 负责截断 / 负值归零。全无有效率 → 0.0。
    """
    norm = [
        r for r in (
            normalize_spare_rate(it.loss_rate if it.loss_rate is not None else order_rate)
            for it in rows
        ) if r is not None
    ]
    return max(norm) if norm else 0.0


def _effective_rate(
    items, keys, order_rate: float | None,
) -> tuple[float, str | None]:
    """该 SKU 的部位生效率；未匹配到部位行时降级为「该单全部明细的 max」。

    口径（spec §2.2/§4）：

    1. ``keys`` 非空且明细中有键命中 → ``max(命中行的率)``；
    2. 否则（**产品无法解析 / BOM 键为空 / BOM 匹配为空**）→ 降级为**该采购单
       全部明细**的 max（不是订单级率），两条路径共用同一套「行率为 NULL →
       ``order_rate`` 兜底」规则；全无有效率 → 0；
    3. 绝不抛错。

    Args:
        items: 该采购单的**全部**明细行（降级分支也要用整单明细取 max）。
        keys: 该 SKU 的 BOM 键集合；产品无法解析时为 falsy。
        order_rate: 订单级 ``spare_rate``，仅作 NULL 行的回退基线。

    Returns:
        ``(rate, degraded_reason)``：命中部位行时原因为 ``None``；降级时给出原因
        （供调用方汇总成**每次调用一条**的 warning）。
    """
    matched = _match_part_items(items, keys)
    if matched:
        return _rates_max(matched, order_rate), None
    reason = 'BOM 匹配为空' if keys else '产品无法解析或无 BOM 物料'
    return _rates_max(items, order_rate), reason


async def recompute_po_spare_from_item_rates(db: AsyncSession, po_ids) -> int:
    """按「部位率 max」重算所涉采购单的备品（公式 A）。返回被处理的采购单数。

    写入 ``purchase_order.spare_quantity``（= Σ 逐 SKU 备品）与
    ``purchase_order_sku.spare_qty / spare_rate``。

    降级链（任一环节不可得即回退，绝不抛错）：
    1. SKU 快照表不可用            → 保持既有订单级口径；
    2. 该单无 SKU 快照行            → 同上（合法旧单，静默）；
    3. 产品/BOM 解析不出 / BOM 匹配为空 → 该 SKU 降级为「该单全部明细的
       max」（spec §2.2/§4，不是订单级率），汇总一条 warning。
    """
    ids = [i for i in dict.fromkeys(po_ids or []) if i]
    if not ids:
        return 0
    orders = (await db.execute(
        select(PurchaseOrder).where(PurchaseOrder.id.in_(ids))
    )).scalars().all()
    if not orders:
        return 0

    if not await po_sku_available(db):
        for order in orders:
            order.spare_quantity = calc_spare_quantity(order.product_quantity, order.spare_rate)
        return len(orders)

    items_by_po: dict[int, list] = defaultdict(list)
    for item in (await db.execute(
        select(PurchaseOrderItem).where(PurchaseOrderItem.order_id.in_(ids))
    )).scalars().all():
        items_by_po[item.order_id].append(item)
    skus_by_po: dict[int, list] = defaultdict(list)
    for sku in (await db.execute(
        select(PurchaseOrderSku).where(PurchaseOrderSku.po_id.in_(ids))
    )).scalars().all():
        skus_by_po[sku.po_id].append(sku)

    all_skus = [s for rows in skus_by_po.values() for s in rows]
    by_barcode, by_name, name_by_pid = await _resolve_products(db, all_skus)
    keys_by_pid = await _load_bom_item_keys(db, name_by_pid)

    degraded: list[tuple[str, str]] = []
    for order in orders:
        skus = skus_by_po.get(order.id) or []
        if not skus:
            # 无逐 SKU 快照：保持既有订单级口径（零回归；L2 不属降级噪声源，不打告警）
            order.spare_quantity = calc_spare_quantity(order.product_quantity, order.spare_rate)
            continue
        items = items_by_po.get(order.id) or []
        total = 0
        for sku in skus:
            pid = by_barcode.get(sku.product_barcode or '') or by_name.get(
                (sku.product_name or '').strip()
            )
            part_keys = keys_by_pid.get(pid) if pid is not None else None
            rate, reason = _effective_rate(items, part_keys, order.spare_rate)
            if reason is not None:
                # 产品无法解析 / BOM 匹配为空（L3）：本 SKU 降级为该单明细 max，留痕
                degraded.append((sku.product_name or sku.product_barcode or '未知SKU', reason))
            sku.spare_rate = rate
            sku.spare_qty = calc_spare_quantity(sku.order_qty, rate)
            total += int(sku.spare_qty or 0)
        order.spare_quantity = total
    if degraded:
        # 汇总一次（非逐 SKU）：保存路径会去抖重入，逐条会变噪声
        unique = list(dict.fromkeys(degraded))
        logger.warning(
            '备品重算：%d 个 SKU 未匹配到部位明细行，已降级为该单全部明细 max：%s',
            len(unique), '、'.join(f'{name}（{reason}）' for name, reason in unique),
        )
    return len(orders)
