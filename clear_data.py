"""
清空业务数据脚本
注意：此操作不可逆，清空前请备份数据库
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app, db

def clear_all_business_data():
    """清空所有业务数据（保留用户和客户基础数据）"""
    app = create_app()

    with app.app_context():
        print("=" * 60)
        print("警告：即将清空所有业务数据！")
        print("=" * 60)
        print("\n将清空以下数据表：")
        print("  - 订单相关 (order, order_group)")
        print("  - 入库相关 (stock_in, case_stock_in)")
        print("  - 出库相关 (stock_out, case_stock_out)")
        print("  - 库存日志 (inventory_log, case_inventory_log)")
        print("  - 备货记录 (staging_order, staging_stock_in, staging_stock_out)")
        print("  - 审批记录 (approval_request, approval_log)")
        print("  - 物料计算 (product_material, product_fabric, product_accessory, product_packaging)")
        print("  - 采购订单 (purchase_order, purchase_order_item)")
        print("  - 物料清单 (material_registration, material_registration_item)")
        print("  - 生产计划 (production_plan, production_plan_log)")
        print("  - 采购计划 (purchase_plans, purchase_plan_details, staging_purchase_plan)")
        print("  - 订单分组 (order_group, order_group_material)")
        print("  - 产品 (product)")
        print("\n保留以下数据：")
        print("  - 客户 (customer)")
        print("  - 供应商 (supplier)")
        print("  - 用户 (user)")
        print("=" * 60)

        confirm = input("\n确认清空？输入 'YES' 继续: ")
        if confirm != 'YES':
            print("操作已取消")
            return

        try:
            print("\n开始清空数据...")

            # 禁用外键检查
            print("  - 禁用外键检查...")
            db.session.execute(db.text("SET FOREIGN_KEY_CHECKS = 0"))

            # 清空顺序很重要（外键依赖）
            print("  - 清空物料清单关联...")
            db.session.execute(db.text("DELETE FROM material_registration_item"))
            db.session.execute(db.text("DELETE FROM material_registration"))

            print("  - 清空审批记录...")
            db.session.execute(db.text("DELETE FROM approval_log"))
            db.session.execute(db.text("DELETE FROM approval_request"))

            print("  - 清空备货记录...")
            db.session.execute(db.text("DELETE FROM staging_stock_out"))
            db.session.execute(db.text("DELETE FROM staging_stock_in"))
            db.session.execute(db.text("DELETE FROM staging_order"))

            print("  - 清空皮套库存相关...")
            db.session.execute(db.text("DELETE FROM case_inventory_log"))
            db.session.execute(db.text("DELETE FROM case_stock_out"))
            db.session.execute(db.text("DELETE FROM case_stock_in"))

            print("  - 清空库存日志...")
            db.session.execute(db.text("DELETE FROM inventory_log"))

            print("  - 清空出入库记录...")
            db.session.execute(db.text("DELETE FROM stock_out"))
            db.session.execute(db.text("DELETE FROM stock_in"))

            print("  - 清空订单...")
            db.session.execute(db.text("DELETE FROM order_group_material"))
            db.session.execute(db.text("DELETE FROM order_group"))
            db.session.execute(db.text("DELETE FROM `order`"))

            print("  - 清空采购订单...")
            db.session.execute(db.text("DELETE FROM purchase_order_item"))
            db.session.execute(db.text("DELETE FROM purchase_order"))

            print("  - 清空物料关联...")
            db.session.execute(db.text("DELETE FROM product_packaging"))
            db.session.execute(db.text("DELETE FROM product_accessory"))
            db.session.execute(db.text("DELETE FROM product_material"))
            db.session.execute(db.text("DELETE FROM product_fabric"))

            print("  - 清空生产计划...")
            db.session.execute(db.text("DELETE FROM production_plan_log"))
            db.session.execute(db.text("DELETE FROM production_plan"))

            print("  - 清空采购计划...")
            db.session.execute(db.text("DELETE FROM staging_purchase_plan"))
            db.session.execute(db.text("DELETE FROM purchase_plan_details"))
            db.session.execute(db.text("DELETE FROM purchase_plans"))

            print("  - 清空产品...")
            db.session.execute(db.text("DELETE FROM product"))

            print("  - 清空皮套...")
            db.session.execute(db.text("DELETE FROM `case`"))

            # 重新启用外键检查
            print("  - 启用外键检查...")
            db.session.execute(db.text("SET FOREIGN_KEY_CHECKS = 1"))

            db.session.commit()
            print("\n✅ 数据清空完成！")

        except Exception as e:
            db.session.rollback()
            print(f"\n❌ 清空失败: {str(e)}")
            raise

if __name__ == '__main__':
    clear_all_business_data()
