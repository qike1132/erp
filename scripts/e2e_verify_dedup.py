"""端到端验证：模拟一键审核流程，确认只生成 1 个采购单（而非 4 个）。"""
import asyncio
import sys
from pathlib import Path

# 让 `python scripts/e2e_verify_dedup.py` 能直接跑（原先缺这段，会 ModuleNotFoundError）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from _prod_write_guard import require_prod_write_consent
from sqlalchemy import select

from fastapi_app.core.database import _AsyncSessionLocal
from fastapi_app.services.purchase_order_generate import generate_purchase_orders_from_customer_orders
from fastapi_app.shared_models import PurchaseOrder
from fastapi_app.shared_models.order import Order

require_prod_write_consent('对生产库创建/重建采购单')


async def main():
    async with _AsyncSessionLocal() as db:
        # 1. 查找一个"待备货"状态的订单
        result = await db.execute(
            select(Order).where(Order.status == '待备货').limit(1)
        )
        order = result.scalars().first()
        if not order:
            print('SKIP  没有"待备货"状态的订单，跳过测试')
            return

        composite_id = f'order:{order.id}'
        print(f'测试订单: id={order.id} order_no={order.order_no} customer={order.customer} status={order.status}')
        print(f'composite_id: {composite_id}')
        print()

        # 记录调用前的 pending 采购单数量
        result = await db.execute(
            select(PurchaseOrder).where(
                PurchaseOrder.status == 'pending',
                PurchaseOrder.source_order_ids == f'[{order.id}]'
            )
        )
        before_orders = result.scalars().all()
        print(f'调用前: 该订单的 pending 采购单数量 = {len(before_orders)}')

        # 2. 第一次调用
        print()
        print('=== 第一次调用 generate_purchase_orders_from_customer_orders ===')
        try:
            result1 = await generate_purchase_orders_from_customer_orders(db, [composite_id])
            await db.commit()
            print(f'结果: success={result1["success"]} created_count={result1["created_count"]}')
            print(f'  orders: {[(o["id"], o["order_no"]) for o in result1.get("orders", [])]}')
        except Exception as e:
            await db.rollback()
            print(f'异常: {type(e).__name__}: {e}')
            return

        # 3. 验证只创建了 1 个采购单
        result = await db.execute(
            select(PurchaseOrder).where(
                PurchaseOrder.status == 'pending',
                PurchaseOrder.source_order_ids == f'[{order.id}]'
            )
        )
        after_orders = result.scalars().all()
        print()
        print(f'调用后: 该订单的 pending 采购单数量 = {len(after_orders)}')
        for po in after_orders:
            print(f'  id={po.id} no={po.order_no} supp_id={po.supplier_id} supp_name={po.supplier_name}')

        if len(after_orders) == 1:
            print()
            print('OK  只创建了 1 个采购单，修复有效！')
        else:
            print()
            print(f'FAIL  创建了 {len(after_orders)} 个采购单，期望 1 个')

        # 4. 第二次调用（测试 cleanup 幂等性）
        print()
        print('=== 第二次调用（应清理旧单并重建 1 个）===')
        try:
            result2 = await generate_purchase_orders_from_customer_orders(db, [composite_id])
            await db.commit()
            print(f'结果: success={result2["success"]} created_count={result2["created_count"]}')
        except Exception as e:
            await db.rollback()
            print(f'异常: {type(e).__name__}: {e}')

        # 最终验证
        result = await db.execute(
            select(PurchaseOrder).where(
                PurchaseOrder.status == 'pending',
                PurchaseOrder.source_order_ids == f'[{order.id}]'
            )
        )
        final_orders = result.scalars().all()
        print()
        print(f'=== 最终结果: {len(final_orders)} 个 pending 采购单 ===')
        for po in final_orders:
            print(f'  id={po.id} no={po.order_no} supp_id={po.supplier_id} supp_name={po.supplier_name} src={po.source_order_ids}')


asyncio.run(main())
