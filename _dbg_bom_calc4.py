# -*- coding: utf-8 -*-
"""诊断 4：验证 calculate_material 的角色（作用域）维度过滤"""
import asyncio, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding='utf-8')

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from fastapi_app.core.config import _build_database_uri
from fastapi_app.services import purchase_product_service as svc

PID = 20588


def show(title, calc):
    total = 0
    print(f'\n--- {title} ---')
    for cat in ('filling', 'fabric', 'accessory', 'packaging'):
        arr = calc.get(cat) or []
        total += len(arr)
        for r in arr:
            print(f"  [{cat}] {r['material_name']!r:<14} spec={r['specification']!r:<8} "
                  f"qty={r['total_quantity']:<8} unit={r['unit']!r:<4} 作用域={r.get('role_names')}")
    print(f'  合计 {total} 条')


async def main():
    engine = create_async_engine(_build_database_uri(), echo=False)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as db:
        r1 = await svc.calculate_material(db, [{'product_id': PID, 'quantity': 1, 'role_id': None}])
        show('A. 仅默认 BOM（role_id=null）', r1)

        r2 = await svc.calculate_material(db, [{'product_id': PID, 'quantity': 10, 'role_id': 4}])
        show('B. 仅角色「呼汇」（role_id=4，数量10）', r2)

        r3 = await svc.calculate_material(db, [
            {'product_id': PID, 'quantity': 1, 'role_id': None},
            {'product_id': PID, 'quantity': 10, 'role_id': 4},
        ])
        show('C. 默认BOM×1 + 角色呼汇×10（跨作用域合并）', r3)

        r4 = await svc.calculate_material(db, [{'product_id': PID, 'quantity': 1}])
        show('D. 未传 role_id（向后兼容：仅默认BOM）', r4)

        # 断言
        assert len(r1['fabric']) == 7 and len(r1['filling']) == 1 and len(r1['accessory']) == 1, 'A 失败'
        assert len(r2['fabric']) == 1 and r2['fabric'][0]['material_name'] == '哈哈', 'B 失败'
        assert abs(r2['fabric'][0]['total_quantity'] - 10.0) < 1e-9, 'B 数量失败'
        assert len(r3['fabric']) == 8, 'C 面料应为 8 条'
        haha = [r for r in r3['fabric'] if r['material_name'] == '哈哈'][0]
        assert haha['role_names'] == ['呼汇'], f"C 作用域标注失败: {haha['role_names']}"
        超柔 = [r for r in r3['fabric'] if r['material_name'] == '超柔'][0]
        assert 超柔['role_names'] == ['默认BOM'], f"C 默认BOM标注失败: {超柔['role_names']}"
        assert len(r4['fabric']) == 7, 'D 向后兼容失败'
        print('\n✅ 全部断言通过')
    await engine.dispose()


asyncio.run(main())
