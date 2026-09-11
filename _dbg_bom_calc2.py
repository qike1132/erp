# -*- coding: utf-8 -*-
"""诊断 2：用真实 ORM 层对比『计算器 calculate_material』与『录入页 get_bom』输出"""
import asyncio, json, sys, os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding='utf-8')

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from fastapi_app.core.config import settings
from fastapi_app.services import bom_service, purchase_product_service

PID = 20588


async def main():
    from fastapi_app.core.config import _build_database_uri
    url = _build_database_uri()
    engine = create_async_engine(url, echo=False)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async with Session() as db:
        print('=' * 70)
        print('【A】录入页数据源 get_bom()')
        print('=' * 70)
        bom = await bom_service.get_bom(db, PID)
        mats = (bom or {}).get('materials') or []
        print(f"roles = {bom.get('roles') if bom else None}")
        print(f"materials 共 {len(mats)} 条:")
        for m in mats:
            print(f"  id={m.get('id')!s:<6} role_id={m.get('role_id')!s:<6} cat={m.get('category')!r:<12} "
                  f"name={m.get('material_name')!r:<16} spec={m.get('specification')!r:<8} "
                  f"usage={m.get('unit_usage')} unit={m.get('unit')!r:<4} sup={m.get('supplier_name')!r}")

        print()
        print('=' * 70)
        print('【B】计算器数据源 calculate_material(quantity=1)')
        print('=' * 70)
        calc = await purchase_product_service.calculate_material(db, [{'product_id': PID, 'quantity': 1}])
        total = 0
        for cat in ('filling', 'fabric', 'accessory', 'packaging'):
            arr = calc.get(cat) or []
            total += len(arr)
            print(f"  [{cat}] {len(arr)} 条")
            for r in arr:
                print(f"     name={r['material_name']!r:<16} spec={r['specification']!r:<8} "
                      f"qty={r['total_quantity']} unit={r['unit']!r:<4} sup={r['supplier_name']!r} code={r.get('material_code')!r}")
        print(f"  合计 {total} 条")

        print()
        print('=' * 70)
        print('【C】差异比对（按 (分类,名称,供应商,规格) 键）')
        print('=' * 70)
        keys_a = {}
        for m in mats:
            c = m.get('category') or ''
            if c == 'packaging':
                continue  # 前端录入页过滤 packaging
            k = (c, m.get('material_name') or '', m.get('supplier_name') or '', m.get('specification') or '')
            keys_a[k] = keys_a.get(k, 0) + float(m.get('unit_usage') or 0)
        keys_b = {}
        for cat in ('filling', 'fabric', 'accessory'):
            for r in (calc.get(cat) or []):
                k = (cat, r['material_name'], r['supplier_name'] or '', r['specification'] or '')
                keys_b[k] = keys_b.get(k, 0) + float(r['total_quantity'])
        only_a = set(keys_a) - set(keys_b)
        only_b = set(keys_b) - set(keys_a)
        print(f"  录入页有/计算器无: {len(only_a)} 条")
        for k in only_a:
            print(f"     {k} -> {keys_a[k]}")
        print(f"  计算器有/录入页无: {len(only_b)} 条")
        for k in only_b:
            print(f"     {k} -> {keys_b[k]}")
        diff = [(k, keys_a[k], keys_b[k]) for k in set(keys_a) & set(keys_b) if abs(keys_a[k] - keys_b[k]) > 1e-9]
        print(f"  数量不一致: {len(diff)} 条")
        for k, va, vb in diff:
            print(f"     {k} 录入页={va} 计算器={vb}")
        if not only_a and not only_b and not diff:
            print('  >> 两路数据完全一致')

    await engine.dispose()


asyncio.run(main())
