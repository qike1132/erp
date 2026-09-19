"""采购单逐 SKU 数量快照（``purchase_order_sku``）的读/写与可用性探测。

方案 C（治本）：把「每个 SKU 各自下单多少」落库，供 /beile-order 逐 SKU 展示，
不再从订单级 ``product_quantity`` 反推（那在数据模型层就已经不存在）。

设计背景见 ``evidence/beile_multisku/多SKU订单数量显示-根因与方案.md``（RC-1/RC-2）。

**口径恒等式**：``Σ order_qty == purchase_order.product_quantity``（同一采集口径）。
同一来源记录内同一产品名的多行会被**合并**为一行（见 ``write_po_sku_rows``），
既满足唯一约束，又保持合计不变，且不采用任何「拆分/摊派/猜测」的方式。

**优雅降级**：本模块所有入口先经 :func:`po_sku_available` 探测目标表是否存在
（结果缓存在 ``db.info``，不跨请求污染）：

- 表缺失（迁移未执行）时，读路径返回空映射 → /beile-list 回退订单级口径、绝不 500；
- 写路径跳过落库并记 warning → 保证「代码先于迁移部署」时下单流程不中断。

用 ``db.info`` 而非模块级全局做缓存，是为了避免测试进程内不同 engine/表结构互相污染。
"""
from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.float_utils import round_qty
from fastapi_app.services.purchase_utils import calc_spare_quantity, normalize_spare_rate
from fastapi_app.shared_models.order import Order
from fastapi_app.shared_models.purchase_order import PurchaseOrderSku

logger = logging.getLogger(__name__)

# db.info 中的缓存键（值：bool）
_AVAIL_KEY = 'po_sku_table_available'


def source_record_type(rec) -> str:
    """判定源记录类型：``order``（客户订单）或 ``stockin``（备货）。

    直接用 isinstance 判定，避免依赖 items 关系是否存在（无 items 的旧订单
    同样回退到 Order 兼容字段，仍属 order）。
    """
    return 'order' if isinstance(rec, Order) else 'stockin'


def iter_source_sku_lines(rec, pid_name_map: dict[int, str] | None = None):
    """逐 SKU 迭代源记录（Order / StockIn），产出**带产品名/条码**的四元组。

    与 ``purchase_order_generate._iter_source_skus`` **同口径**（同一 items 遍历
    与兼容字段回退规则），仅额外携带产品名与条码；**不改变** ``_iter_source_skus``
    的既有行为。

    产品名优先取源记录自身快照（``OrderItem.product_name``），以保证与
    /beile-order 逐 SKU 展示的产品名逐字一致（读路径按 (来源, 产品名) 匹配）；
    缺失时回退 ``pid_name_map``，再回退 ``'未知产品'``。**不访问 rec.product**：
    StockIn 的 product 关系在异步上下文按需加载有 MissingGreenlet 风险。

    Returns:
        [(product_id, product_name, product_barcode, quantity), ...]
    """
    name_map = pid_name_map or {}
    items = getattr(rec, 'items', None)
    if items:
        lines = []
        for it in items:
            name = getattr(it, 'product_name', None) or name_map.get(it.product_id) or '未知产品'
            lines.append((it.product_id, str(name).strip(), getattr(it, 'product_barcode', None), it.quantity))
        return lines
    # StockIn 或无 OrderItem 的旧订单：使用兼容字段
    name = name_map.get(rec.product_id) or '未知产品'
    return [(rec.product_id, str(name).strip(), None, rec.quantity)]


async def _probe_table(db: AsyncSession) -> bool:
    """探测 ``purchase_order_sku`` 是否存在。

    用 SAVEPOINT（``begin_nested``）包裹探测语句：表缺失时仅回滚到该保存点，
    不破坏外层事务的挂起写入（写路径不能因探测失败丢掉已 add 的对象）。
    """
    try:
        async with db.begin_nested():
            await db.execute(sa_text('SELECT 1 FROM purchase_order_sku LIMIT 1'))
        return True
    except Exception:  # noqa: BLE001 - 表缺失/方言差异均视为「不可用」，降级处理
        return False


async def po_sku_available(db: AsyncSession) -> bool:
    """``purchase_order_sku`` 表是否可用于读写（结果缓存在 db.info，同会话只探一次）。"""
    info = getattr(db, 'info', None)
    if isinstance(info, dict):
        cached = info.get(_AVAIL_KEY)
        if cached is not None:
            return bool(cached)
    available = await _probe_table(db)
    if isinstance(info, dict):
        info[_AVAIL_KEY] = available
    if not available:
        logger.warning('purchase_order_sku 表不可用（迁移未执行？），逐 SKU 快照将降级/跳过')
    return available


def build_po_sku_rows(records, pid_name_map: dict[int, str] | None = None,
                      spare_rate: float | None = None) -> list[dict]:
    """把多条源记录的 SKU 行合并为「一行一个 (来源类型, 来源id, 产品名)」的字典列表。

    合并键与唯一约束一致；同一来源同产品名的多行数量相加（**不拆分 / 不摊派 /
    不猜测**——同一 SKU 的同一来源记录多行本就应视为其合计）。返回的字典**不含
    po_id**，便于写路径与历史回填脚本共用（回填脚本按采购单逐张插入）。

    Returns:
        [{'product_name', 'product_barcode', 'order_qty', 'spare_qty',
          'spare_rate', 'source_order_id', 'source_record_type'}, ...]
    """
    rate = normalize_spare_rate(spare_rate)
    buckets: dict[tuple[str, int, str], dict] = {}
    for rec in records:
        rtype = source_record_type(rec)
        rid = int(rec.id)
        for _pid, name, barcode, qty in iter_source_sku_lines(rec, pid_name_map):
            sname = (name or '').strip()
            key = (rtype, rid, sname)
            bucket = buckets.get(key)
            amount = float(qty or 0)
            if bucket is None:
                buckets[key] = {'name': sname, 'barcode': barcode, 'qty': amount}
            else:
                bucket['qty'] += amount
                if not bucket['barcode'] and barcode:
                    bucket['barcode'] = barcode

    rows: list[dict] = []
    for (rtype, sid, _sname), bucket in buckets.items():
        rows.append({
            'product_name': bucket['name'],
            'product_barcode': bucket['barcode'],
            'order_qty': round_qty(bucket['qty']),
            'spare_qty': calc_spare_quantity(bucket['qty'], rate),
            'spare_rate': rate,
            'source_order_id': sid,
            'source_record_type': rtype,
        })
    return rows


async def write_po_sku_rows(
    db: AsyncSession, po_id: int | None, records,
    pid_name_map: dict[int, str] | None = None, spare_rate: float | None = None,
) -> int:
    """为一张采购单写入逐 SKU 快照行；返回写入行数（表不可用时返回 0）。

    ``records`` 为该采购单的来源记录集合（Order / StockIn）。
    ``order_qty`` = 该 SKU 在其来源记录中的数量；``spare_qty`` =
    ``calc_spare_quantity(order_qty, spare_rate)``；``source_order_id`` /
    ``source_record_type`` 来自来源记录。
    """
    if po_id is None or not await po_sku_available(db):
        return 0
    rows = build_po_sku_rows(records, pid_name_map=pid_name_map, spare_rate=spare_rate)
    for row in rows:
        db.add(PurchaseOrderSku(po_id=po_id, **row))
    return len(rows)


def merge_sku_lines(rows) -> list[dict]:
    """按 (产品名, 条码) 合并逐 SKU 行，数量相加；返回 ``[{product_name, product_barcode, order_qty}]``。

    合并理由与表唯一约束一致：同一采购单内同一产品名可能来自多条来源记录
    （``source_order_id`` 不同），展示时应合并为一行，合计不变。
    """
    buckets: dict[tuple[str, str], dict] = {}
    for row in rows:
        name = (row.get('product_name') or '').strip()
        barcode = row.get('product_barcode') or ''
        key = (name, barcode)
        amount = float(row.get('order_qty') or 0)
        if key in buckets:
            buckets[key]['order_qty'] += amount
        else:
            buckets[key] = {'product_name': name, 'product_barcode': barcode, 'order_qty': amount}
    return list(buckets.values())


async def fetch_po_sku_map(db: AsyncSession, po_ids) -> dict[int, list[dict]]:
    """读取多张采购单的逐 SKU 快照（方案 C 权威口径）。

    Returns:
        ``{po_id: [{'product_name', 'product_barcode', 'order_qty'}, ...]}``（同名单条码已合并）。

    **优雅降级**：表不可用（迁移未执行）时返回空 dict，由调用方回退到 OrderItem /
    订单级口径 —— 绝不能因此 500。
    """
    ids = [pid for pid in dict.fromkeys(po_ids or []) if pid]
    if not ids or not await po_sku_available(db):
        return {}
    result = await db.execute(
        select(
            PurchaseOrderSku.po_id, PurchaseOrderSku.product_name,
            PurchaseOrderSku.product_barcode, PurchaseOrderSku.order_qty,
        )
        .where(PurchaseOrderSku.po_id.in_(ids))
        .order_by(PurchaseOrderSku.po_id, PurchaseOrderSku.id)
    )
    grouped: dict[int, list[dict]] = {}
    for po_id, name, barcode, qty in result.all():
        grouped.setdefault(po_id, []).append({
            'product_name': name or '', 'product_barcode': barcode or '', 'order_qty': qty,
        })
    return {po_id: merge_sku_lines(rows) for po_id, rows in grouped.items()}


async def resync_po_sku_spare(db: AsyncSession, po_ids, spare_rate: float | None) -> int:
    """损耗率变更后，按新率重算所涉**采购单**的逐 SKU 备品（保持逐 SKU 行与主表同步）。

    主表 ``spare_quantity`` 由 ``_apply_spare_rate`` 按订单级 ``product_quantity``
    重算；逐 SKU 行必须同步重算，否则读路径的逐 SKU 生产数量会与主表口径不一致。

    Args:
        po_ids: **采购单 id 集合**（不是客户订单 id）——调用方传入的全部是
            ``PurchaseOrder.id``（见 purchase_order_crud 各写路径）。
    Returns:
        被更新的快照行数。
    """
    if spare_rate is None:
        return 0
    ids = [oid for oid in dict.fromkeys(po_ids or []) if oid]
    if not ids or not await po_sku_available(db):
        return 0
    rate = normalize_spare_rate(spare_rate)
    rows = (await db.execute(
        select(PurchaseOrderSku).where(PurchaseOrderSku.po_id.in_(ids))
    )).scalars().all()
    for row in rows:
        row.spare_rate = rate
        row.spare_qty = calc_spare_quantity(row.order_qty, rate)
    return len(rows)
