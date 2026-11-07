"""定向修复：按「采购明细 + BOM 补全行」重建指定采购单的来料登记明细。

**背景**：2026-11-07 前创建来料登记时只拷贝采购明细，BOM 中后补的物料行没有进
登记（``PO-20261107-0003`` 只有 2 行，产品 BOM 有 8 行）。新代码已在创建路径
补全（``services/material_registration/_bom_items.py``），历史登记需回填。

**安全约束**：
1. 默认 dry-run，只有显式 ``--apply`` 才写库，且必须显式授权生产写；
2. 仅当该登记**所有明细已收货数量为 0** 时才重建（有收货记录的不动，避免丢数据）；
3. 幂等：按登记「先删后插」，可重复执行。

用法::

    python scripts/backfill_material_registration_items.py --order-no PO-20261107-0003
    python scripts/backfill_material_registration_items.py --order-no PO-20261107-0003 --apply --allow-prod-write
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (_REPO_ROOT, os.path.join(_REPO_ROOT, 'scripts')):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import selectinload, sessionmaker

from fastapi_app.core.cache import CacheDomain
from fastapi_app.core.cache_invalidation import InvalidationStrategy, cache_mgr
from fastapi_app.core.config import settings
from fastapi_app.services.material_registration._bom_items import build_registration_items
from fastapi_app.shared_models import (
    MaterialRegistration,
    MaterialRegistrationItem,
    PurchaseOrder,
)


def _key(row: dict) -> tuple[str, str, str]:
    return (row['material_name'], row['specification'], row['unit'])


async def _repair(db: AsyncSession, order_no: str, apply: bool) -> int:
    po = (await db.execute(
        select(PurchaseOrder)
        .options(selectinload(PurchaseOrder.items))
        .where(PurchaseOrder.order_no == order_no)
    )).scalars().first()
    if not po:
        print(f'[FAIL] 采购单不存在: {order_no}')
        return 2

    regs = (await db.execute(
        select(MaterialRegistration)
        .options(selectinload(MaterialRegistration.items))
        .where(MaterialRegistration.purchase_order_no == order_no)
    )).scalars().all()
    if not regs:
        print(f'[SKIP] 该采购单没有来料登记: {order_no}')
        return 0

    expected = await build_registration_items(db, po, po.items)
    print(f'采购单 {order_no}: 采购明细 {len(po.items)} 行，期望登记明细 {len(expected)} 行')

    exit_code = 0
    for reg in regs:
        old = list(reg.items)
        received = sum(float(i.received_quantity or 0) for i in old)
        print(f'\n登记 id={reg.id} 供应商={reg.supplier_name} 现状 {len(old)} 行，已收货合计 {received}')
        for i in old:
            print(f'  - {i.material_name} / {i.specification} / {i.unit} '
                  f'ordered={float(i.ordered_quantity or 0)} received={float(i.received_quantity or 0)} '
                  f'supplier={i.supplier_name or ""}')
        print('  期望:')
        for row in expected:
            print(f'  + {row["material_name"]} / {row["specification"]} / {row["unit"]} '
                  f'ordered={row["ordered_quantity"]} supplier={row["supplier_name"]}')

        if {_key({'material_name': i.material_name, 'specification': i.specification or '',
                  'unit': i.unit or ''}) for i in old} == {_key(r) for r in expected} \
                and all(i.supplier_name for i in old):
            print('  [OK] 明细已与期望一致，无需重建')
            continue

        if received != 0:
            print('  [SKIP] 已有收货记录，拒绝重建（请人工处理）')
            exit_code = 3
            continue

        if not apply:
            print('  [dry-run] 将删除旧明细并写入期望明细')
            continue

        await db.execute(
            delete(MaterialRegistrationItem).where(MaterialRegistrationItem.registration_id == reg.id)
        )
        for row in expected:
            db.add(MaterialRegistrationItem(
                registration_id=reg.id,
                order_item_id=row['order_item_id'],
                material_code=row['material_code'],
                material_name=row['material_name'],
                specification=row['specification'],
                unit=row['unit'],
                ordered_quantity=row['ordered_quantity'],
                received_quantity=row['received_quantity'],
                material_category=row['material_category'],
                supplier_name=row['supplier_name'],
                remark=row['remark'],
            ))
        reg.update_status()
        await db.flush()
        print(f'  [APPLIED] 已重建 {len(expected)} 行')

    if apply:
        await db.commit()
        await cache_mgr.invalidate(InvalidationStrategy.DOMAIN, CacheDomain.MATERIAL)
        print('\n[APPLIED] 已提交并失效物料缓存')
    else:
        print('\n[dry-run] 未写库。加 --apply --allow-prod-write 才实际写入。')
    return exit_code


async def _main(args: argparse.Namespace) -> int:
    engine = create_async_engine(settings.ASYNC_DATABASE_URL, echo=False)
    maker = sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with maker() as db:
            return await _repair(db, args.order_no, args.apply)
    finally:
        await engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description='按采购单重建来料登记明细（默认 dry-run）')
    parser.add_argument('--order-no', required=True, help='采购单号，如 PO-20261107-0003')
    parser.add_argument('--apply', action='store_true', help='实际写库（默认只对账）')
    args, _unknown = parser.parse_known_args()

    if args.apply:
        from _prod_write_guard import require_prod_write_consent
        require_prod_write_consent(f'重建来料登记明细（{args.order_no}）')
    return asyncio.run(_main(args))


if __name__ == '__main__':
    sys.exit(main())
