"""
检查备货数据
"""
from app import app, db
from app.models import StockIn, StockOut, Product
import sys

# 设置UTF-8编码输出
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

with app.app_context():
    print("=" * 60)
    print("备货数据检查")
    print("=" * 60)

    # 查询所有备货
    stockins = StockIn.query.all()
    print(f"\n总备货记录数: {len(stockins)}")

    for stockin in stockins:
        print(f"\n备货ID: {stockin.id}")
        print(f"  备货编号: {stockin.stockin_no}")
        print(f"  产品ID: {stockin.product_id}")
        print(f"  产品名称: {stockin.product.name if stockin.product else 'N/A'}")
        print(f"  客户: {stockin.customer}")
        print(f"  备货数量: {stockin.quantity}")
        print(f"  备货日期: {stockin.stockin_date}")
        print(f"  备注: {stockin.note}")

        # 查询相关的出库记录
        stockouts = stockin.stockouts
        print(f"  关联出库记录数: {len(stockouts)}")

        total_deducted = 0
        for stockout in stockouts:
            print(f"    - 出库ID: {stockout.id}, 数量: {stockout.quantity}, 订单ID: {stockout.order_id}")
            total_deducted += stockout.quantity

        available = stockin.quantity - total_deducted
        print(f"  已抵扣数量: {total_deducted}")
        print(f"  可用数量: {available}")

    # 检查产品库存
    print("\n" + "=" * 60)
    print("产品库存检查")
    print("=" * 60)

    products = Product.query.all()
    print(f"\n总产品数: {len(products)}")

    for product in products:
        print(f"\n产品ID: {product.id}")
        print(f"  产品名称: {product.name}")
        print(f"  69码: {product.barcode}")
        print(f"  当前库存: {product.current_stock}")
