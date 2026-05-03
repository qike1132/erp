"""
订单管理诊断脚本
"""
import os
import sys

# 设置UTF-8编码
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

os.environ['USE_NEW_ARCH'] = 'true'

from app import app, db
from app.models import Order, Product

print("=" * 60)
print("订单管理诊断")
print("=" * 60)

# 测试1: 检查数据库连接
print("\n[测试1] 数据库连接")
try:
    with app.app_context():
        from sqlalchemy import text
        result = db.session.execute(text('SELECT 1')).scalar()
        print(f"  数据库连接: 正常 (结果: {result})")
except Exception as e:
    print(f"  数据库连接: 失败 ({e})")

# 测试2: 检查订单数据
print("\n[测试2] 订单数据")
try:
    with app.app_context():
        orders = Order.query.all()
        print(f"  订单数量: {len(orders)}")
        for order in orders[:3]:
            print(f"    - 订单号: {order.order_no}, 客户: {order.customer}")
except Exception as e:
    print(f"  订单查询失败: {e}")

# 测试3: 检查产品数据
print("\n[测试3] 产品数据")
try:
    with app.app_context():
        products = Product.query.all()
        print(f"  产品数量: {len(products)}")
        for product in products[:3]:
            print(f"    - 产品: {product.name}, 条码: {product.barcode}")
except Exception as e:
    print(f"  产品查询失败: {e}")

# 测试4: 检查模板文件
print("\n[测试4] 模板文件")
import os

template_path = 'templates/order.html'
if os.path.exists(template_path):
    print("  模板文件: 存在")
    size = os.path.getsize(template_path)
    print(f"  文件大小: {size} 字节")
else:
    print("  模板文件: 不存在")

# 测试5: 测试路由访问
print("\n[测试5] 路由访问测试")
try:
    with app.test_client() as client:
        # 测试兼容性路由
        response1 = client.get('/orders')
        print(f"  /orders: {response1.status_code} (重定向)")

        # 测试实际路由
        response2 = client.get('/order/list')
        print(f"  /order/list: {response2.status_code}")

        if response2.status_code == 200:
            print(f"  响应大小: {len(response2.data)} 字节")
            print("  订单页面: 正常")
        else:
            print("  订单页面: 异常")
            print(f"  错误内容: {response2.data.decode('utf-8')[:200]}")
except Exception as e:
    print(f"  路由测试失败: {e}")

# 测试6: 检查蓝图注册
print("\n[测试6] 蓝图注册")
try:
    routes = []
    for rule in app.url_map.iter_rules():
        if 'order' in rule.endpoint:
            routes.append(f"{rule.rule} -> {rule.endpoint}")

    print(f"  订单相关路由: {len(routes)}个")
    for route in routes:
        print(f"    {route}")
except Exception as e:
    print(f"  蓝图检查失败: {e}")

print("\n" + "=" * 60)
print("诊断完成")
print("=" * 60)
