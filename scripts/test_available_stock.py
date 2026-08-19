r"""
实时可用库存计算 - Mock 数据验证脚本

使用方法：
  cd d:\erp_system
  python scripts/test_available_stock.py

脚本会：
1. 插入测试产品、订单、入库、出库、生产记录
2. 调用 get_inventory_paginated 验证 available_stock 计算
3. 清理所有测试数据

计算公式：
  available_stock = SUM(daily_production_record.quantity) - SUM(stock_out.quantity - stock_out.returned_quantity)
"""
import asyncio
import os
import sys

# 确保项目根目录在 sys.path 中
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from datetime import UTC, date, datetime

# ============ Mock 数据定义 ============

TEST_TAG = '__test_avail__'

# 3 个测试产品
MOCK_PRODUCTS = [
    {'name': f'{TEST_TAG}产品A', 'barcode': 'TST0000001', 'price': 10.00},
    {'name': f'{TEST_TAG}产品B', 'barcode': 'TST0000002', 'price': 20.00},
    {'name': f'{TEST_TAG}产品C', 'barcode': 'TST0000003', 'price': 30.00},
]

# 客户
MOCK_CUSTOMER = f'{TEST_TAG}客户X'

# 订单（产品A: 常规100, 产品B: 定制50, 产品C: 常规80）
MOCK_ORDERS = [
    {'product_idx': 0, 'quantity': 100, 'order_type': 'regular', 'customer': MOCK_CUSTOMER},
    {'product_idx': 1, 'quantity': 50,  'order_type': 'custom',  'customer': MOCK_CUSTOMER, 'country': '美国'},
    {'product_idx': 2, 'quantity': 80,  'order_type': 'regular', 'customer': MOCK_CUSTOMER},
]

# 入库（产品A: 60, 产品B: 30, 产品C: 40）
MOCK_STOCKINS = [
    {'product_idx': 0, 'quantity': 60, 'customer': MOCK_CUSTOMER},
    {'product_idx': 1, 'quantity': 30, 'customer': MOCK_CUSTOMER},
    {'product_idx': 2, 'quantity': 40, 'customer': MOCK_CUSTOMER},
]

# 出库（产品A: 20, 产品B: 10, 产品C: 15）
MOCK_STOCKOUTS = [
    {'product_idx': 0, 'quantity': 20, 'customer': MOCK_CUSTOMER, 'returned_quantity': 0},
    {'product_idx': 1, 'quantity': 10, 'customer': MOCK_CUSTOMER, 'returned_quantity': 2},  # 退货2
    {'product_idx': 2, 'quantity': 15, 'customer': MOCK_CUSTOMER, 'returned_quantity': 0},
]

# 生产记录（产品A: 200, 产品B: 80, 产品C: 120）
MOCK_PRODUCTIONS = [
    {'product_idx': 0, 'quantity': 200, 'department': 'filling'},
    {'product_idx': 0, 'quantity': 50,  'department': 'packaging'},
    {'product_idx': 1, 'quantity': 80,  'department': 'handcraft'},
    {'product_idx': 2, 'quantity': 70,  'department': 'filling'},
    {'product_idx': 2, 'quantity': 50,  'department': 'packaging'},
]

# ============ 预期计算结果 ============
# 产品A: production_qty=250, total_stockout=20, available_stock=230
# 产品B: production_qty=80,  total_stockout=10-2=8, available_stock=72
# 产品C: production_qty=120, total_stockout=15, available_stock=105
EXPECTED = {
    0: {'production_qty': 250, 'available_stock': 230},
    1: {'production_qty': 80,  'available_stock': 72},
    2: {'production_qty': 120, 'available_stock': 105},
}


async def run_test():
    from sqlalchemy import delete, select, text

    from fastapi_app.core.database import _AsyncSessionLocal, async_engine
    from fastapi_app.services.stock_service import get_inventory_paginated
    from fastapi_app.shared_models import (
        InventoryLog,
        Order,
        Product,
        StockIn,
        StockOut,
    )
    from fastapi_app.shared_models.daily_production_record import DailyProductionRecord

    product_ids: list[int] = []
    order_ids: list[int] = []
    stockin_ids: list[int] = []
    stockout_ids: list[int] = []
    production_ids: list[int] = []

    async with _AsyncSessionLocal() as db:
        try:
            # ---- 1. 插入产品 ----
            for p in MOCK_PRODUCTS:
                product = Product(
                    name=p['name'],
                    barcode=p['barcode'],
                    price=p['price'],
                    current_stock=0,
                    initial_stock=0,
                )
                db.add(product)
            await db.flush()
            result = await db.execute(
                select(Product).where(Product.name.startswith(TEST_TAG))
            )
            products = result.scalars().all()
            product_ids = [p.id for p in products]
            print(f'[1] 插入 {len(products)} 个测试产品: {product_ids}')

            # ---- 2. 插入订单 ----
            for o in MOCK_ORDERS:
                order = Order(
                    order_no=f'TST-O-{product_ids[o["product_idx"]]}',
                    customer=o['customer'],
                    product_id=product_ids[o['product_idx']],
                    quantity=o['quantity'],
                    order_type=o['order_type'],
                    country=o.get('country'),
                    order_date=datetime.now(UTC),
                    status='待备货',
                )
                db.add(order)
            await db.flush()
            result = await db.execute(
                select(Order).where(Order.customer == MOCK_CUSTOMER)
            )
            orders = result.scalars().all()
            order_ids = [o.id for o in orders]
            print(f'[2] 插入 {len(orders)} 个测试订单: {order_ids}')

            # ---- 3. 插入入库 ----
            for si in MOCK_STOCKINS:
                stockin = StockIn(
                    stockin_no=f'TST-SI-{product_ids[si["product_idx"]]}',
                    product_id=product_ids[si['product_idx']],
                    quantity=si['quantity'],
                    customer=si['customer'],
                    stockin_date=datetime.now(UTC),
                    order_type='regular',
                    note='test',
                )
                db.add(stockin)
                # 更新产品库存
                product = await db.get(Product, product_ids[si['product_idx']])
                if product:
                    product.current_stock += si['quantity']
            await db.flush()
            result = await db.execute(
                select(StockIn).where(StockIn.customer == MOCK_CUSTOMER)
            )
            stockins = result.scalars().all()
            stockin_ids = [s.id for s in stockins]
            print(f'[3] 插入 {len(stockins)} 条入库记录: {stockin_ids}')

            # ---- 4. 插入出库 ----
            for so in MOCK_STOCKOUTS:
                stockout = StockOut(
                    stockout_no=f'TST-SO-{product_ids[so["product_idx"]]}',
                    product_id=product_ids[so['product_idx']],
                    quantity=so['quantity'],
                    returned_quantity=so['returned_quantity'],
                    customer=so['customer'],
                    stockout_date=datetime.now(UTC),
                    order_id=order_ids[so['product_idx']] if so['product_idx'] < len(order_ids) else None,
                    note='test',
                )
                db.add(stockout)
                # 更新产品库存
                product = await db.get(Product, product_ids[so['product_idx']])
                if product:
                    product.current_stock -= so['quantity'] - so['returned_quantity']
            await db.flush()
            result = await db.execute(
                select(StockOut).where(StockOut.customer == MOCK_CUSTOMER)
            )
            stockouts = result.scalars().all()
            stockout_ids = [s.id for s in stockouts]
            print(f'[4] 插入 {len(stockouts)} 条出库记录: {stockout_ids}')

            # ---- 5. 插入生产记录 ----
            today = date.today()
            for pr in MOCK_PRODUCTIONS:
                production = DailyProductionRecord(
                    product_id=product_ids[pr['product_idx']],
                    product_name=MOCK_PRODUCTS[pr['product_idx']]['name'],
                    barcode=MOCK_PRODUCTS[pr['product_idx']]['barcode'],
                    unit_price=MOCK_PRODUCTS[pr['product_idx']]['price'],
                    quantity=pr['quantity'],
                    department=pr['department'],
                    production_date=today,
                )
                db.add(production)
            await db.flush()
            result = await db.execute(
                select(DailyProductionRecord).where(
                    DailyProductionRecord.product_name.startswith(TEST_TAG)
                )
            )
            productions = result.scalars().all()
            production_ids = [p.id for p in productions]
            print(f'[5] 插入 {len(productions)} 条生产记录: {production_ids}')

            await db.commit()
            print('\n--- Mock 数据插入完成 ---\n')

            # ---- 6. 调用 get_inventory_paginated 验证 ----
            print('[6] 调用 get_inventory_paginated ...')
            result = await get_inventory_paginated(
                db, search_customer=MOCK_CUSTOMER, page=1, per_page=50
            )

            print(f'    total_items: {result["total_items"]}')
            print(f'    total_available_stock: {result["total_available_stock"]}')
            print()

            # ---- 7. 逐行验证 ----
            all_pass = True
            for item in result['inventory_data']:
                prod_name = item['product_name']
                production_qty = item.get('production_qty', '')
                available_stock = item.get('available_stock', '')
                total_stock = item.get('total_stock', '')

                # 找到对应的产品索引
                idx = None
                for i, p in enumerate(MOCK_PRODUCTS):
                    if p['name'] == prod_name:
                        idx = i
                        break

                print(f'  产品: {prod_name}')
                print(f'    订单数量:     {item["order_quantity"]}')
                print(f'    备货数量:     {item["stockin_quantity"]}')
                print(f'    总订单:       {total_stock}')
                print(f'    累计生产:     {production_qty}')
                print(f'    可用库存:     {available_stock}')

                if idx is not None and idx in EXPECTED:
                    exp = EXPECTED[idx]
                    pq_ok = int(production_qty or 0) == exp['production_qty']
                    as_ok = int(available_stock or 0) == exp['available_stock']
                    status_pq = 'PASS' if pq_ok else f'FAIL (expected {exp["production_qty"]})'
                    status_as = 'PASS' if as_ok else f'FAIL (expected {exp["available_stock"]})'
                    print(f'    累计生产验证: {status_pq}')
                    print(f'    可用库存验证: {status_as}')
                    if not (pq_ok and as_ok):
                        all_pass = False
                print()

            # 验证 total_available_stock（按产品去重求和）
            expected_total = sum(e['available_stock'] for e in EXPECTED.values())
            total_ok = result['total_available_stock'] == expected_total
            status_total = 'PASS' if total_ok else f'FAIL (expected {expected_total}, got {result["total_available_stock"]})'
            print(f'  总可用库存验证: {status_total}')
            if not total_ok:
                all_pass = False

            print()
            if all_pass:
                print('========== ALL TESTS PASSED ==========')
            else:
                print('========== SOME TESTS FAILED ==========')

        finally:
            # ---- 8. 清理测试数据 ----
            print('\n--- 清理测试数据 ---')
            # 按外键依赖顺序删除
            await db.execute(
                delete(DailyProductionRecord).where(
                    DailyProductionRecord.product_name.startswith(TEST_TAG)
                )
            )
            await db.execute(
                delete(StockOut).where(StockOut.customer == MOCK_CUSTOMER)
            )
            await db.execute(
                delete(StockIn).where(StockIn.customer == MOCK_CUSTOMER)
            )
            await db.execute(
                delete(InventoryLog).where(
                    InventoryLog.note.like('%入库ID：%')
                    if False else text('1=0')  # 日志无客户字段，跳过
                )
            )
            await db.execute(
                delete(Order).where(Order.customer == MOCK_CUSTOMER)
            )
            await db.execute(
                delete(Product).where(Product.name.startswith(TEST_TAG))
            )
            await db.commit()
            print('清理完成')

    await async_engine.dispose()


if __name__ == '__main__':
    asyncio.run(run_test())
