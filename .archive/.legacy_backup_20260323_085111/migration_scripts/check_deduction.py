#!/usr/bin/env python
"""
备货抵扣功能检查脚本
用于验证后端逻辑和数据库操作
"""

import os
import sys
from datetime import datetime

# 添加当前目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import InventoryLog, Order, Product, StockIn, StockOut, app, db


def check_database():
    """检查数据库状态"""
    print("=" * 60)
    print("数据库状态检查")
    print("=" * 60)

    with app.app_context():
        print("\n1. 产品列表:")
        products = Product.query.all()
        if products:
            for p in products:
                print(f"  - ID: {p.id}, 名称: {p.name}, 当前库存: {p.current_stock}")
        else:
            print("  (无产品)")

        print("\n2. 备货记录列表:")
        stockins = StockIn.query.all()
        if stockins:
            for s in stockins:
                used = sum(so.quantity for so in s.stockouts) if s.stockouts else 0
                print(f"  - ID: {s.id}, 编号: {s.stockin_no}, 产品: {s.product.name if s.product else 'N/A'}, "
                      f"总数量: {s.quantity}, 已用: {used}")
        else:
            print("  (无备货记录)")

        print("\n3. 订单列表:")
        orders = Order.query.all()
        if orders:
            for o in orders:
                print(f"  - ID: {o.id}, 编号: {o.order_no}, 客户: {o.customer}, "
                      f"产品: {o.product.name if o.product else 'N/A'}, 数量: {o.quantity}, 状态: {o.status}")
        else:
            print("  (无订单)")

        print("\n4. 出货记录列表:")
        stockouts = StockOut.query.all()
        if stockouts:
            for so in stockouts:
                print(f"  - ID: {so.id}, 编号: {so.stockout_no}, 数量: {so.quantity}, "
                      f"订单: {so.order.order_no if so.order else 'N/A'}, "
                      f"备货: {so.stockin.stockin_no if so.stockin else 'N/A'}")
        else:
            print("  (无出货记录)")

    print("\n" + "=" * 60)


def test_available_stockins_api():
    """测试获取可用备货API"""
    print("\n测试获取可用备货API")
    print("-" * 60)

    with app.test_client() as client:
        # 设置会话（模拟登录）
        with client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['is_super'] = True

        # 获取产品ID
        with app.app_context():
            product = Product.query.first()
            if product:
                product_id = product.id
                print(f"\n使用产品ID: {product_id}, 名称: {product.name}")

                # 调用API
                response = client.get(f'/api/available-stockins?product_id={product_id}&order_quantity=10')
                print(f"\nAPI响应状态码: {response.status_code}")
                print(f"API响应内容: {response.get_json()}")
            else:
                print("\n警告: 数据库中没有产品")


def test_order_creation():
    """测试订单创建和抵扣逻辑"""
    print("\n测试订单创建和抵扣逻辑")
    print("-" * 60)

    with app.app_context():
        # 检查是否有测试数据
        product = Product.query.first()
        if not product:
            print("\n创建测试产品...")
            product = Product(
                name='测试产品',
                barcode='6901234567890',
                initial_stock=0,
                current_stock=0
            )
            db.session.add(product)
            db.session.flush()
            print(f"  产品创建成功，ID: {product.id}")

        # 检查是否有备货记录
        stockin = StockIn.query.filter_by(product_id=product.id).first()
        if not stockin:
            print("\n创建测试备货记录...")
            from app import generate_stockin_number
            stockin = StockIn(
                stockin_no=generate_stockin_number(),
                stockin_date=datetime.now(),
                product_id=product.id,
                quantity=50,
                note='测试备货'
            )
            db.session.add(stockin)
            db.session.flush()
            print(f"  备货记录创建成功，编号: {stockin.stockin_no}, 数量: 50")

            # 增加库存
            product.current_stock += 50
            log = InventoryLog(
                product_id=product.id,
                change_type='备货',
                change_quantity=50,
                related_id=stockin.stockin_no,
                note=f'备货：{stockin.stockin_no}'
            )
            db.session.add(log)

        db.session.commit()
        print("\n测试数据准备完成！")
        print("\n请访问 http://127.0.0.1:5003/orders 进行手动测试")


if __name__ == '__main__':
    print("备货抵扣功能检查脚本")
    print("=" * 60)

    # 检查数据库
    check_database()

    # 测试API
    test_available_stockins_api()

    # 准备测试数据
    test_order_creation()

    print("\n检查完成！")
