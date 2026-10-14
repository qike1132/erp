"""一次性清理：删除「来源客户订单已删除」却仍 pending 的采购单。

背景（2026-10-13 生产事故）：报表页删除订单明细走 `DELETE /orders/items/{id}`，
末项删除会转成整单软删，但当时该端点没发 ORDER_DELETED，采购中心订阅不到，
不会撤回该订单已自动生成的 pending 采购单，于是残留在 /purchase
（PO-20261013-23761 / PO-20261013-23763，po id 20500/20501）。
代码侧已在 fedbe26b 补齐事件；本脚本只清历史残留。

判定口径：
  - status='pending' 的采购单；
  - 收集其来源客户订单 id（source_order_ids JSON + source_order_id 列 +
    purchase_order_sku 里 source_record_type='order' 的 source_order_id）；
  - 这些来源订单**全部**不存在或 is_deleted=true → 视为孤儿单。
  没有任何来源订单 id 的 pending 单**不处理**（可能来自备货，无法判定）。

用法（必须从仓库根目录运行）：
  python scripts/cleanup_orphan_purchase_orders_20261013.py            # dry-run，只报告
  python scripts/cleanup_orphan_purchase_orders_20261013.py --execute  # 备份后执行删除
  # --execute 需显式授权写生产库：ERP_ALLOW_PROD_WRITE=1 或 --allow-prod-write

安全措施：
  - --execute 先把 PO 主表 + 明细 + SKU 快照写 JSON 备份到 backups/（误删可手工恢复）
  - 单事务提交：删除失败整体回滚
  - 提交后清 Redis 采购缓存（失败不影响已提交数据）
"""
import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

_HERE = Path(__file__).resolve()
sys.path.insert(0, str(_HERE.parent))       # scripts/：_prod_write_guard
sys.path.insert(0, str(_HERE.parents[1]))   # 仓库根：fastapi_app

from sqlalchemy import select

from fastapi_app.shared_models import (
    Order,
    PurchaseOrder,
    PurchaseOrderItem,
    PurchaseOrderSku,
)
from fastapi_app.shared_models.purchase_order import PurchaseOrderStatus


def _num(value):
    return float(value) if value is not None else None


def _po_row(po: PurchaseOrder) -> dict:
    return {
        'id': po.id,
        'order_no': po.order_no,
        'status': po.status,
        'supplier_id': po.supplier_id,
        'supplier_name': po.supplier_name,
        'customer_id': po.customer_id,
        'customer_name': po.customer_name,
        'order_date': str(po.order_date) if po.order_date else None,
        'remark': po.remark,
        'source_order_id': po.source_order_id,
        'source_order_ids': po.source_order_ids,
        'product_name': po.product_name,
        'product_quantity': _num(po.product_quantity),
        'spare_quantity': _num(po.spare_quantity),
        'spare_rate': _num(po.spare_rate),
        'total_amount': _num(po.total_amount),
        'create_time': str(po.create_time) if po.create_time else None,
        'update_time': str(po.update_time) if po.update_time else None,
        'created_by': po.created_by,
        'completed_at': str(po.completed_at) if po.completed_at else None,
        'completed_by': po.completed_by,
    }


def _item_row(item: PurchaseOrderItem) -> dict:
    return {
        'id': item.id,
        'order_id': item.order_id,
        'product_name': item.product_name,
        'barcode': item.barcode,
        'customer_name': item.customer_name,
        'material_code': item.material_code,
        'material_name': item.material_name,
        'specification': item.specification,
        'unit': item.unit,
        'quantity': _num(item.quantity),
        'unit_usage': _num(item.unit_usage),
        'unit_price': _num(item.unit_price),
        'total_price': _num(item.total_price),
        'material_category': item.material_category,
        'supplier_name': item.supplier_name,
        'remark': item.remark,
    }


def _sku_row(sku: PurchaseOrderSku) -> dict:
    return {
        'id': sku.id,
        'po_id': sku.po_id,
        'product_name': sku.product_name,
        'product_barcode': sku.product_barcode,
        'order_qty': _num(sku.order_qty),
        'spare_qty': _num(sku.spare_qty),
        'spare_rate': _num(sku.spare_rate),
        'source_order_id': sku.source_order_id,
        'source_record_type': sku.source_record_type,
        'create_time': str(sku.create_time) if sku.create_time else None,
    }


def _collect_source_order_ids(po: PurchaseOrder, sku_order_ids: list[int]) -> list[int]:
    ids: set[int] = {int(sid) for sid in sku_order_ids if sid}
    if po.source_order_id:
        ids.add(int(po.source_order_id))
    if po.source_order_ids:
        try:
            for sid in json.loads(po.source_order_ids):
                ids.add(int(sid))
        except (ValueError, TypeError):
            pass
    return sorted(ids)


async def main(execute: bool) -> int:
    if execute:
        from _prod_write_guard import require_prod_write_consent
        require_prod_write_consent(
            '删除「来源客户订单已删除」却仍 pending 的采购单',
            hint='误操作可依据 backups/ 下的 JSON 备份手工恢复',
        )

    from fastapi_app.core.database import (
        ensure_engine_for_current_loop,
        require_async_session_local,
    )

    await ensure_engine_for_current_loop()
    session_factory = require_async_session_local()

    async with session_factory() as db:
        pending = list((await db.execute(
            select(PurchaseOrder).where(PurchaseOrder.status == PurchaseOrderStatus.PENDING)
        )).scalars().unique().all())
        if not pending:
            print('没有 pending 采购单，无需清理')
            return 0

        po_ids = [po.id for po in pending]
        skus = list((await db.execute(
            select(PurchaseOrderSku).where(PurchaseOrderSku.po_id.in_(po_ids))
        )).scalars().all())
        sku_order_ids: dict[int, list[int]] = {}
        for sku in skus:
            if sku.source_record_type == 'order' and sku.source_order_id:
                sku_order_ids.setdefault(sku.po_id, []).append(int(sku.source_order_id))

        po_sources: dict[int, list[int]] = {}
        all_source_ids: set[int] = set()
        for po in pending:
            ids = _collect_source_order_ids(po, sku_order_ids.get(po.id, []))
            po_sources[po.id] = ids
            all_source_ids.update(ids)

        deleted_or_missing: set[int] = set()
        if all_source_ids:
            rows = (await db.execute(
                select(Order.id, Order.is_deleted).where(Order.id.in_(all_source_ids))
            )).all()
            existing_ids = {row.id for row in rows}
            deleted_or_missing = {row.id for row in rows if row.is_deleted}
            deleted_or_missing |= (all_source_ids - existing_ids)

        orphans = [
            po for po in pending
            if po_sources[po.id] and all(sid in deleted_or_missing for sid in po_sources[po.id])
        ]

        print(f'pending 采购单：{len(pending)} 条')
        print(f'孤儿判定（来源客户订单全部已删除/缺失）：{len(orphans)} 条')
        for po in orphans:
            print(
                f'  - po#{po.id} {po.order_no} 客户={po.customer_name} '
                f'供应商={po.supplier_name} 产品={po.product_name} '
                f'数量={_num(po.product_quantity)} 来源订单={po_sources[po.id]} '
                f'创建={po.create_time}'
            )
        if not orphans:
            print('无孤儿采购单，无需清理')
            return 0
        if not execute:
            print('\n[dry-run] 未做任何修改。确认无误后加 --execute 执行。')
            return 0

        orphan_ids = [po.id for po in orphans]
        items = list((await db.execute(
            select(PurchaseOrderItem).where(PurchaseOrderItem.order_id.in_(orphan_ids))
        )).scalars().all())
        orphan_skus = [sku for sku in skus if sku.po_id in set(orphan_ids)]

        backup_dir = _HERE.parents[1] / 'backups'
        backup_dir.mkdir(exist_ok=True)
        backup_path = backup_dir / (
            f'orphan_purchase_orders_backup_{datetime.now().strftime("%Y%m%d-%H%M%S")}.json'
        )
        backup_path.write_text(json.dumps({
            'schema_version': 1,
            'cleaned_at': datetime.now().isoformat(),
            'reason': 'source customer orders deleted but pending purchase orders remained',
            'purchase_orders': [_po_row(po) for po in orphans],
            'purchase_order_items': [_item_row(item) for item in items],
            'purchase_order_skus': [_sku_row(sku) for sku in orphan_skus],
        }, ensure_ascii=False, indent=2), encoding='utf-8')
        print(f'备份已写入：{backup_path}')

        from fastapi_app.services.purchase_order_crud import delete_purchase_order

        for po in orphans:
            await delete_purchase_order(db, po.id)
        await db.commit()
        print(f'已删除孤儿 pending 采购单 {len(orphans)} 条（事务已提交）')

    try:
        from fastapi_app.services.purchase._auto_generate import invalidate_purchase_caches
        await invalidate_purchase_caches()
        print('采购缓存已失效')
    except Exception as cache_err:  # noqa: BLE001 - 缓存清理失败不影响已提交数据
        print(f'警告：采购缓存失效失败（{cache_err}）；重启 erp-prod + TTL 会兜底。')
    return 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='清理来源客户订单已删除的 pending 采购单')
    parser.add_argument('--execute', action='store_true', help='真正执行删除（默认 dry-run）')
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main(args.execute)))
