# -*- coding: utf-8 -*-
"""端到端（真实库、真实事务、真实回滚）：一键生成采购单的 BOM 作用域落库验证。

⚠️ 全程在单个事务内完成并在结束时 **rollback**，不污染生产数据。
验证链路：generate_purchase_orders_from_customer_orders
          → _build_items（作用域展开）
          → create_purchase_order（明细落库 + remark 写入）

断言重点：
  1. 默认 BOM 与角色 BOM 的明细都出现（历史缺陷：默认 BOM 被整个漏掉）
  2. 每个作用域都用 SKU 完整数量，不分摊
  3. 明细 remark 标注来源作用域，采购员能看出「这条由谁产生」
  4. 订单状态被推进（与旧行为一致）
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
from fastapi_app.services.purchase_order_generate import (
    generate_purchase_orders_from_customer_orders,
)
from fastapi_app.shared_models.order import ORDER_STATUS_PENDING_STOCK, Order

PID = 20588   # 蛋仔派对》团子木鱼毛绒挂件盲盒：默认BOM + 角色「呼汇」
QTY = 10

failed: list[str] = []
total: list[str] = []


def check(name: str, ok: bool, detail: str = '') -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f' — {detail}' if detail else ''))
    total.append(name)
    if not ok:
        failed.append(name)


async def main():
    engine = create_async_engine(_build_database_uri(), echo=False)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as db:
        # 1) 造一张 pending 客户订单（不 commit，后续整体回滚）
        #    product_id/quantity 是非空兼容字段（多 SKU 下为首 item 兼容值），必须填
        order = Order(
            order_no='E2E-SCOPE-0001',
            customer='E2E测试客户',
            status=ORDER_STATUS_PENDING_STOCK,
            product_id=PID,
            quantity=QTY,
        )
        db.add(order)
        await db.flush()

        from fastapi_app.shared_models.order_item import OrderItem
        db.add(OrderItem(
            order_id=order.id, product_id=PID, product_name='蛋仔派对》团子木鱼毛绒挂件盲盒',
            quantity=QTY, order_type='regular',
        ))
        await db.flush()

        print(f'\n临时订单 id={order.id} 产品={PID} 数量={QTY}')

        # 2) 真实调用生成函数（内部会 flush，但外层不 commit）
        result = await generate_purchase_orders_from_customer_orders(
            db, [f'order:{order.id}'],
        )

        orders = result.get('orders', [])
        check('生成了采购单', len(orders) == 1, f"实际 {len(orders)} 个")

        # 3) 回查落库明细
        from fastapi_app.shared_models.purchase_order import PurchaseOrder, PurchaseOrderItem
        po_id = orders[0]['id']
        items = (await db.execute(
            select(PurchaseOrderItem).where(PurchaseOrderItem.order_id == po_id)
        )).scalars().all()

        by_scope = defaultdict(list)
        for it in items:
            label = (it.remark or '').replace('来源BOM：', '') or '(无标注)'
            by_scope[label].append(it)

        print(f'\n落库明细 {len(items)} 条，按来源作用域分组：')
        for label, rows in sorted(by_scope.items()):
            print(f'  [{label}] {len(rows)} 条')
            for it in rows:
                print(f'      {it.material_category:<10} {it.material_name!r:<28} '
                      f'spec={it.specification!r:<6} 数量={float(it.quantity)} {it.unit}')

        # --- 断言 ---
        check('默认 BOM 的明细没有被漏掉', '默认BOM' in by_scope,
              f"作用域集合={sorted(by_scope)}")
        check('角色「呼汇」的明细已落库', '呼汇' in by_scope,
              f"作用域集合={sorted(by_scope)}")
        check('两个作用域的明细都在同一张采购单里',
              set(by_scope) == {'默认BOM', '呼汇'}, f"实际 {sorted(by_scope)}")

        if '默认BOM' in by_scope:
            check('默认BOM 9 条明细（填充1/面料7/辅料1）',
                  len(by_scope['默认BOM']) == 9, f"实际 {len(by_scope['默认BOM'])}")
            chao_rou = [i for i in by_scope['默认BOM']
                        if i.material_category == 'fabric' and i.specification == '12']
            check('默认BOM 超柔 0.01×10 = 0.1（用总量，未分摊）',
                  chao_rou and abs(float(chao_rou[0].quantity) - 0.1) < 1e-9,
                  f"实际 {[float(i.quantity) for i in chao_rou]}")
            filling = [i for i in by_scope['默认BOM'] if i.material_category == 'filling']
            check('默认BOM 填充物 500×10 = 5000',
                  filling and abs(float(filling[0].quantity) - 5000.0) < 1e-6,
                  f"实际 {[float(i.quantity) for i in filling]}")

        if '呼汇' in by_scope:
            check('角色「呼汇」1 条明细', len(by_scope['呼汇']) == 1,
                  f"实际 {len(by_scope['呼汇'])}")
            check('角色「呼汇」哈哈 1×10 = 10（用总量，未分摊）',
                  abs(float(by_scope['呼汇'][0].quantity) - 10.0) < 1e-9,
                  f"实际 {float(by_scope['呼汇'][0].quantity)}")

        # 4) 状态推进与旧行为一致
        await db.refresh(order)
        check('源订单状态推进为已备货', order.status != ORDER_STATUS_PENDING_STOCK, order.status)

        # 5) 回滚，不留痕
        await db.rollback()
        print('\n已回滚，未写入生产数据')

        # 回滚后再查一次，确认真的没落库
        left = (await db.execute(
            select(PurchaseOrder).where(PurchaseOrder.order_no.like('CG-%'))
            .where(PurchaseOrder.customer_name == 'E2E测试客户')
        )).scalars().all()
        check('回滚后无残留采购单', len(left) == 0, f"实际残留 {len(left)} 条")

    await engine.dispose()


asyncio.run(main())

print(f'\n共 {len(total)} 项断言，失败 {len(failed)} 项')
if failed:
    print('失败项: ' + '; '.join(failed))
    sys.exit(1)
print('✅ 一键生成端到端（真实库 + 真实事务 + 回滚）全部通过')
