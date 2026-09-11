# -*- coding: utf-8 -*-
"""诊断 5：验证 calculate_material 的「按产品 × 作用域分组」输出"""
import asyncio, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding='utf-8')

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from fastapi_app.core.config import _build_database_uri
from fastapi_app.services import purchase_product_service as svc

PID = 20588


def show(title, res):
    print(f'\n--- {title} ---')
    groups = res.get('groups') or []
    assert isinstance(groups, list), 'groups 必须是列表'
    for g in groups:
        n = sum(len(g[c]) for c in ('filling', 'fabric', 'accessory', 'packaging'))
        print(f"  [{g['role_name']}] role_id={g['role_id']} 数量={g['quantity']} 共 {n} 条")
        for c in ('filling', 'fabric', 'accessory', 'packaging'):
            for r in g[c]:
                print(f"      {c:<10} {r['material_name']!r:<14} spec={r['specification']!r:<8} "
                      f"用量={r['total_quantity']:<8} unit={r['unit']!r}")
    print(f'  作用域块数 = {len(groups)}')
    return groups


async def main():
    engine = create_async_engine(_build_database_uri(), echo=False)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as db:
        g1 = show('A. 总数量 1', await svc.calculate_material(db, [{'product_id': PID, 'quantity': 1}]))
        g2 = show('B. 总数量 10', await svc.calculate_material(db, [{'product_id': PID, 'quantity': 10}]))

        assert len(g1) == 2, f'A 应产出 2 个作用域块，实际 {len(g1)}'
        assert g1[0]['role_id'] is None and g1[0]['role_name'] == '默认BOM', 'A 首块应为默认BOM'
        assert g1[1]['role_id'] == 4 and g1[1]['role_name'] == '呼汇', 'A 次块应为呼汇'
        assert len(g1[0]['filling']) == 1 and len(g1[0]['fabric']) == 7 and len(g1[0]['accessory']) == 1, 'A 默认BOM 条数'
        assert len(g1[1]['fabric']) == 1 and g1[1]['fabric'][0]['material_name'] == '哈哈', 'A 呼汇条数'
        # 每个作用域都按总数量计算
        assert abs(g2[0]['fabric'][0]['total_quantity'] - 0.1) < 1e-9, f"B 超柔应为 0.01×10=0.1，实际 {g2[0]['fabric'][0]['total_quantity']}"
        assert abs(g2[1]['fabric'][0]['total_quantity'] - 10.0) < 1e-9, 'B 哈哈应为 10'
        assert g2[0]['quantity'] == 10.0 and g2[1]['quantity'] == 10.0, 'B 各块 quantity 均=10'
        print('\n✅ 全部断言通过')
    await engine.dispose()


asyncio.run(main())
