"""
清空 ERP 系统数据脚本
保留用户和权限数据，清空所有业务数据
"""

from app import app, db
from models import (
    BOMFile,
    Case,
    CaseInventoryLog,
    CaseStockIn,
    CaseStockOut,
    InventoryLog,
    Order,
    Product,
    StockIn,
    StockOut,
)


def clear_all_data():
    """清空所有业务数据，保留用户和权限"""
    with app.app_context():
        try:
            print("开始清空数据...")

            # 1. 清空订单相关数据
            print("清空订单数据...")
            StockOut.query.delete()
            Order.query.delete()
            print("✓ 订单数据已清空")

            # 2. 清空产品入库相关数据
            print("清空产品入库数据...")
            InventoryLog.query.delete()
            StockIn.query.delete()
            print("✓ 产品入库数据已清空")

            # 3. 清空产品相关数据
            print("清空产品数据...")
            BOMFile.query.delete()
            Product.query.delete()
            print("✓ 产品数据已清空")

            # 4. 清空皮套出货相关数据
            print("清空皮套出货数据...")
            CaseStockOut.query.delete()
            print("✓ 皮套出货数据已清空")

            # 5. 清空皮套入库相关数据
            print("清空皮套入库数据...")
            CaseInventoryLog.query.delete()
            CaseStockIn.query.delete()
            print("✓ 皮套入库数据已清空")

            # 6. 清空皮套数据
            print("清空皮套数据...")
            Case.query.delete()
            print("✓ 皮套数据已清空")

            # 提交事务
            db.session.commit()

            print("\n" + "="*50)
            print("✓ 所有业务数据已成功清空！")
            print("="*50)
            print("\n保留的数据：")
            print("- 用户账号")
            print("- 权限配置")
            print("\n已清空的数据：")
            print("- 产品及BOM文件")
            print("- 订单及出货记录")
            print("- 产品入库及库存日志")
            print("- 皮套及出入库记录")
            print("- 皮套库存日志")

        except Exception as e:
            db.session.rollback()
            print(f"\n✗ 清空数据失败: {e}")
            raise

if __name__ == '__main__':
    confirm = input("⚠️  警告：此操作将清空所有业务数据！\n是否继续？(yes/no): ")
    if confirm.lower() == 'yes':
        clear_all_data()
    else:
        print("操作已取消")
