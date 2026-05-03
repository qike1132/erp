"""
验证新架构的数据库连接和路由
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
from app.models import Order, Product, StockIn, StockOut


def verify_database():
    """验证数据库连接"""
    print("=" * 50)
    print("验证数据库连接")
    print("=" * 50)

    try:
        with app.app_context():
            # 测试数据库连接
            from sqlalchemy import text
            result = db.session.execute(text('SELECT 1')).scalar()
            print(f"✓ 数据库连接成功: {result}")

            # 检查表是否存在
            inspector = db.inspect(db.engine)
            tables = inspector.get_table_names()
            print(f"✓ 数据库表数量: {len(tables)}")
            print(f"✓ 表列表: {tables}")

            # 测试模型查询
            product_count = Product.query.count()
            order_count = Order.query.count()
            stockin_count = StockIn.query.count()
            stockout_count = StockOut.query.count()

            print(f"✓ 产品数量: {product_count}")
            print(f"✓ 订单数量: {order_count}")
            print(f"✓ 入库记录数量: {stockin_count}")
            print(f"✓ 出库记录数量: {stockout_count}")

        return True
    except Exception as e:
        print(f"✗ 数据库验证失败: {e}")
        return False

def verify_routes():
    """验证路由注册"""
    print("\n" + "=" * 50)
    print("验证路由注册")
    print("=" * 50)

    routes = {}
    for rule in app.url_map.iter_rules():
        if rule.endpoint != 'static':
            routes[rule.rule] = rule.endpoint

    print(f"✓ 总路由数量: {len(routes)}")
    print("\n路由列表:")
    for path, endpoint in sorted(routes.items()):
        print(f"  {path:40s} -> {endpoint}")

    # 检查关键路由
    critical_routes = ['/', '/login', '/logout', '/product', '/order', '/stockin', '/stockout']
    print("\n关键路由检查:")
    for route in critical_routes:
        if route in routes:
            print(f"  ✓ {route} 已注册")
        else:
            print(f"  ✗ {route} 未注册")

    return len(routes) > 0

def verify_models():
    """验证模型定义"""
    print("\n" + "=" * 50)
    print("验证模型定义")
    print("=" * 50)

    models = [Product, Order, StockIn, StockOut]
    for model in models:
        print(f"✓ {model.__name__} 模型已定义")
        print(f"  - 表名: {model.__tablename__}")
        print(f"  - 字段数: {len(model.__table__.columns)}")

    return True

if __name__ == '__main__':
    print("\n" + "=" * 50)
    print("新架构验证测试")
    print("=" * 50)

    # 验证数据库
    db_ok = verify_database()

    # 验证路由
    routes_ok = verify_routes()

    # 验证模型
    models_ok = verify_models()

    # 总结
    print("\n" + "=" * 50)
    print("验证结果总结")
    print("=" * 50)
    print(f"数据库连接: {'✓ 通过' if db_ok else '✗ 失败'}")
    print(f"路由注册: {'✓ 通过' if routes_ok else '✗ 失败'}")
    print(f"模型定义: {'✓ 通过' if models_ok else '✗ 失败'}")
    print("=" * 50)

    if db_ok and routes_ok and models_ok:
        print("✓ 新架构验证通过！")
    else:
        print("✗ 新架构验证失败！")
