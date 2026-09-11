# -*- coding: utf-8 -*-
"""诊断：一键生成采购单是否已按 BOM 作用域（默认BOM + 各角色）取料。

只读验证 —— 直接调 `_build_items` 的等价路径（即 generate_purchase_orders 内部逻辑），
不 commit、不写库。
"""
import asyncio
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding='utf-8')

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from fastapi_app.core.config import _build_database_uri
from fastapi_app.shared_models import Product, ProductAccessory, ProductFabric, ProductMaterial
from fastapi_app.shared_models.product_material import ProductRole
from fastapi_app.services.purchase_order_generate import (
    _bom_rows_by_scope,
    _iter_source_skus,
    _scope_label,
    _scope_order,
)

PID = 20588  # 蛋仔派对》团子木鱼毛绒挂件盲盒：默认BOM + 呼汇 两个作用域


async def main():
    engine = create_async_engine(_build_database_uri(), echo=False)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as db:
        # === 复刻 generate 内部的作用域装配 ===
        fill = _bom_rows_by_scope((await db.execute(
            select(ProductMaterial).where(ProductMaterial.product_id == PID)
        )).scalars().all())
        fab = _bom_rows_by_scope((await db.execute(
            select(ProductFabric).where(ProductFabric.product_id == PID)
        )).scalars().all())
        acc = _bom_rows_by_scope((await db.execute(
            select(ProductAccessory).where(ProductAccessory.product_id == PID)
        )).scalars().all())

        role_rows = (await db.execute(
            select(ProductRole.id, ProductRole.role_name).where(ProductRole.product_id == PID)
        )).all()
        role_names = {(PID, rid): rn for rid, rn in role_rows}
        role_ids = {rid for rid, _ in role_rows}

        material_roles = {
            row.role_id
            for m in (fill, fab, acc)
            for row in m.get(PID, [])
        } | role_ids | {None}   # None 必须显式补入：product_role 表无「默认BOM」行
        scopes = _scope_order(material_roles)

        print(f'产品 {PID}：物料作用域={sorted(k for k in material_roles if k is not None)} '
              f'角色表={sorted(role_ids)}')
        print(f'  → 装配出的作用域顺序 = {scopes}')
        assert scopes[0] is None, '默认BOM 必须在首位'
        assert 4 in scopes, f'应包含角色 4（呼汇），实际 {scopes}'

        # === 按每个作用域产出明细，验证数量口径 ===
        QTY = 10
        items = []
        for role_id in scopes:
            label = _scope_label(PID, role_id, role_names)
            for row in fill.get(role_id, []):
                items.append(('filling', label, row.specification or '', float(row.cotton_usage or 0) * QTY))
            for row in fab.get(role_id, []):
                items.append(('fabric', label, row.specification or '', float(row.quantity or 0) * QTY))
            for row in acc.get(role_id, []):
                items.append(('accessory', label, row.specification or '', float(row.quantity or 0) * QTY))

        print(f'\n数量 {QTY} 时产出的明细（{len(items)} 条）：')
        by_scope = defaultdict(list)
        for cat, label, spec, q in items:
            by_scope[label].append((cat, spec, q))
        for label, rows in by_scope.items():
            print(f'  [{label}] {len(rows)} 条')
            for cat, spec, q in rows:
                print(f'      {cat:<10} spec={spec!r:<8} 用量={q}')

        assert set(by_scope) == {'默认BOM', '呼汇'}, f'作用域应恰为 默认BOM + 呼汇，实际 {set(by_scope)}'
        # 每个作用域都用总量 10，不是分摊
        hui_hui = [r for r in by_scope['呼汇'] if r[0] == 'fabric']
        assert hui_hui and abs(hui_hui[0][2] - 10.0) < 1e-9, f'呼汇 哈哈 应=10，实际 {hui_hui}'
        chao_rou = [r for r in by_scope['默认BOM'] if r[0] == 'fabric' and r[1] == '12']
        assert chao_rou and abs(chao_rou[0][2] - 0.1) < 1e-9, f'默认BOM 超柔(spec=12) 应=0.1，实际 {chao_rou}'

        print('\n✅ 生成侧作用域装配与数量口径断言全部通过')
    await engine.dispose()


asyncio.run(main())
