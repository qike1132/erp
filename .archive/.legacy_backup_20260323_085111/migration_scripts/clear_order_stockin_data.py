"""
清空订单管理和备货管理的数据
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import app, db
from sqlalchemy import text

def clear_order_and_stockin_data():
    """清空订单和备货数据"""
    print("=" * 60)
    print("清空订单管理和备货管理数据")
    print("=" * 60)
    
    with app.app_context():
        try:
            # 1. 查询当前数据量
            print("\n[1] 查询当前数据量...")
            
            # 订单数量
            order_count = db.session.execute(text("SELECT COUNT(*) FROM `order`")).scalar()
            print(f"  - 订单数量: {order_count}")
            
            # 备货数量
            stockin_count = db.session.execute(text("SELECT COUNT(*) FROM stock_in")).scalar()
            print(f"  - 备货数量: {stockin_count}")
            
            # 出货数量
            stockout_count = db.session.execute(text("SELECT COUNT(*) FROM stock_out")).scalar()
            print(f"  - 出货数量: {stockout_count}")
            
            # 库存日志数量
            log_count = db.session.execute(text("SELECT COUNT(*) FROM inventory_log")).scalar()
            print(f"  - 库存日志数量: {log_count}")
            
            if order_count == 0 and stockin_count == 0 and stockout_count == 0:
                print("\n[INFO] 数据库已经是空的，无需清空")
                return
            
            # 2. 确认清空操作
            print("\n[2] 准备清空数据...")
            confirm = input("确认要清空所有订单、备货、出货和库存日志数据吗？(输入 'yes' 确认): ")
            
            if confirm.lower() != 'yes':
                print("[CANCELLED] 操作已取消")
                return
            
            # 3. 开始清空数据
            print("\n[3] 开始清空数据...")
            
            # 禁用外键检查（MySQL）
            db.session.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
            
            # 清空出货记录
            print("  - 清空出货记录...")
            db.session.execute(text("DELETE FROM stock_out"))
            db.session.commit()
            print("    [OK] 出货记录已清空")
            
            # 清空备货记录
            print("  - 清空备货记录...")
            db.session.execute(text("DELETE FROM stock_in"))
            db.session.commit()
            print("    [OK] 备货记录已清空")
            
            # 清空订单记录
            print("  - 清空订单记录...")
            db.session.execute(text("DELETE FROM `order`"))
            db.session.commit()
            print("    [OK] 订单记录已清空")
            
            # 清空库存日志
            print("  - 清空库存日志...")
            db.session.execute(text("DELETE FROM inventory_log"))
            db.session.commit()
            print("    [OK] 库存日志已清空")
            
            # 启用外键检查
            db.session.execute(text("SET FOREIGN_KEY_CHECKS = 1"))
            db.session.commit()
            
            # 4. 验证清空结果
            print("\n[4] 验证清空结果...")
            
            order_count = db.session.execute(text("SELECT COUNT(*) FROM `order`")).scalar()
            stockin_count = db.session.execute(text("SELECT COUNT(*) FROM stock_in")).scalar()
            stockout_count = db.session.execute(text("SELECT COUNT(*) FROM stock_out")).scalar()
            log_count = db.session.execute(text("SELECT COUNT(*) FROM inventory_log")).scalar()
            
            print(f"  - 订单数量: {order_count}")
            print(f"  - 备货数量: {stockin_count}")
            print(f"  - 出货数量: {stockout_count}")
            print(f"  - 库存日志数量: {log_count}")
            
            if order_count == 0 and stockin_count == 0 and stockout_count == 0 and log_count == 0:
                print("\n[SUCCESS] 数据清空成功！")
            else:
                print("\n[WARNING] 部分数据可能未清空，请检查")
            
            # 5. 重置产品库存
            print("\n[5] 重置产品库存...")
            db.session.execute(text("UPDATE product SET current_stock = initial_stock"))
            db.session.commit()
            print("    [OK] 产品库存已重置为初始库存")
            
        except Exception as e:
            print(f"\n[ERROR] 清空数据时出错: {e}")
            import traceback
            print(traceback.format_exc())
            db.session.rollback()
    
    print("\n" + "=" * 60)
    print("操作完成")
    print("=" * 60)

if __name__ == '__main__':
    clear_order_and_stockin_data()
