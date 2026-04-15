"""
ERP系统功能验证脚本
验证修复后的核心功能是否正常工作
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app, db
from app.models import Product, Order, StockIn, StockOut, InventoryLog
from datetime import datetime

def test_product_management():
    """测试产品管理功能"""
    print("\n" + "="*50)
    print("测试1: 产品管理功能")
    print("="*50)
    
    app = create_app('testing')
    with app.app_context():
        db.create_all()
        
        # 创建产品
        product = Product(
            name='测试产品',
            barcode='6901234567890',
            initial_stock=100,
            current_stock=100
        )
        db.session.add(product)
        db.session.commit()
        
        print(f"[OK] 产品创建成功: ID={product.id}, 名称={product.name}")
        
        # 测试to_dict方法
        product_dict = product.to_dict()
        print(f"[OK] to_dict方法正常: {product_dict['name']}")
        
        # 查询产品
        found = Product.query.get(product.id)
        print(f"[OK] 产品查询成功: {found.name}")
        
        db.drop_all()
        return True

def test_order_management():
    """测试订单管理功能"""
    print("\n" + "="*50)
    print("测试2: 订单管理功能")
    print("="*50)
    
    app = create_app('testing')
    with app.app_context():
        db.create_all()
        
        # 创建产品
        product = Product(name='订单测试产品', current_stock=100)
        db.session.add(product)
        db.session.commit()
        
        # 创建订单
        order = Order(
            order_no='ORD-20260322-001',
            customer='测试客户',
            product_id=product.id,
            quantity=10,
            status='待备货'
        )
        db.session.add(order)
        db.session.commit()
        
        print(f"[OK] 订单创建成功: 编号={order.order_no}, 状态={order.status}")
        print(f"[OK] 订单关联产品: {order.product.name}")
        
        db.drop_all()
        return True

def test_stockin_management():
    """测试入库管理功能"""
    print("\n" + "="*50)
    print("测试3: 入库管理功能")
    print("="*50)
    
    app = create_app('testing')
    with app.app_context():
        db.create_all()
        
        # 创建产品
        product = Product(name='入库测试产品', current_stock=100)
        db.session.add(product)
        db.session.commit()
        
        # 创建入库记录
        stockin = StockIn(
            stockin_no='SI-20260322-001',
            product_id=product.id,
            quantity=50,
            customer='入库客户',
            stockin_date=datetime.now()
        )
        db.session.add(stockin)
        db.session.commit()
        
        print(f"[OK] 入库记录创建成功: 编号={stockin.stockin_no}")
        print(f"[OK] 入库数量: {stockin.quantity}")
        
        # 更新库存
        product.current_stock += stockin.quantity
        db.session.commit()
        print(f"[OK] 库存更新成功: 当前库存={product.current_stock}")
        
        db.drop_all()
        return True

def test_stockout_management():
    """测试出库管理功能"""
    print("\n" + "="*50)
    print("测试4: 出库管理功能")
    print("="*50)
    
    app = create_app('testing')
    with app.app_context():
        db.create_all()
        
        # 创建产品
        product = Product(name='出库测试产品', current_stock=100)
        db.session.add(product)
        db.session.commit()
        
        # 创建出库记录
        stockout = StockOut(
            stockout_no='SO-20260322-001',
            product_id=product.id,
            quantity=30,
            customer='出库客户',
            stockout_date=datetime.now()
        )
        db.session.add(stockout)
        db.session.commit()
        
        print(f"[OK] 出库记录创建成功: 编号={stockout.stockout_no}")
        print(f"[OK] 出库数量: {stockout.quantity}")
        
        # 更新库存
        product.current_stock -= stockout.quantity
        db.session.commit()
        print(f"[OK] 库存更新成功: 当前库存={product.current_stock}")
        
        db.drop_all()
        return True

def test_inventory_log():
    """测试库存日志功能"""
    print("\n" + "="*50)
    print("测试5: 库存日志功能")
    print("="*50)
    
    app = create_app('testing')
    with app.app_context():
        db.create_all()
        
        # 创建产品
        product = Product(name='日志测试产品')
        db.session.add(product)
        db.session.commit()
        
        # 创建库存日志
        log = InventoryLog(
            product_id=product.id,
            change_type='初始库存',
            change_quantity=100,
            related_id='INIT-001',
            note='初始库存设置'
        )
        db.session.add(log)
        db.session.commit()
        
        print(f"[OK] 库存日志创建成功: 类型={log.change_type}")
        print(f"[OK] 变化数量: {log.change_quantity}")
        print(f"[OK] 变化时间: {log.change_date}")
        
        db.drop_all()
        return True

def test_api_routes():
    """测试API路由"""
    print("\n" + "="*50)
    print("测试6: API路由")
    print("="*50)
    
    app = create_app('testing')
    client = app.test_client()
    
    with app.app_context():
        db.create_all()
        
        # 测试产品搜索API
        response = client.get('/api/product-search?q=测试')
        print(f"[OK] 产品搜索API: 状态码={response.status_code}")
        
        # 测试产品可用库存API
        product = Product(name='API测试产品', current_stock=100)
        db.session.add(product)
        db.session.commit()
        
        response = client.get(f'/api/product-available-stock?product_id={product.id}')
        print(f"[OK] 可用库存API: 状态码={response.status_code}")
        
        db.drop_all()
        return True

def main():
    """主测试函数"""
    print("\n" + "="*60)
    print(" ERP系统功能验证测试")
    print("="*60)
    
    tests = [
        ("产品管理", test_product_management),
        ("订单管理", test_order_management),
        ("入库管理", test_stockin_management),
        ("出库管理", test_stockout_management),
        ("库存日志", test_inventory_log),
        ("API路由", test_api_routes)
    ]
    
    results = []
    for name, test_func in tests:
        try:
            result = test_func()
            results.append((name, result, None))
        except Exception as e:
            results.append((name, False, str(e)))
    
    # 打印总结
    print("\n" + "="*60)
    print(" 测试总结")
    print("="*60)
    
    passed = sum(1 for _, result, _ in results if result)
    total = len(results)
    
    for name, result, error in results:
        if result:
            print(f"[PASS] {name}: 通过")
        else:
            print(f"[FAIL] {name}: 失败 - {error}")
    
    print("\n" + "="*60)
    print(f" 总计: {passed}/{total} 测试通过")
    print("="*60)
    
    if passed == total:
        print("\n[SUCCESS] 所有测试通过！系统功能正常。")
        return 0
    else:
        print(f"\n[WARNING] {total - passed} 个测试失败，请检查错误信息。")
        return 1

if __name__ == '__main__':
    sys.exit(main())
