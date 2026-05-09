"""简单的数据清空脚本"""
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from sqlalchemy import create_engine, text

from fastapi_app.core.config import settings


def main():
    print("=" * 80)
    print("开始清空数据...")
    print("=" * 80)
    
    engine = create_engine(settings.DATABASE_URL)
    
    with engine.connect() as conn:
        # 开始事务
        trans = conn.begin()
        
        try:
            # 1. 清空采购中心
            print("\n1. 清空采购中心...")
            conn.execute(text("DELETE FROM material_registration_item"))
            print(f"   - 来料登记明细: 已清空")
            conn.execute(text("DELETE FROM material_registration"))
            print(f"   - 来料登记: 已清空")
            conn.execute(text("DELETE FROM purchase_order_item"))
            print(f"   - 采购订单明细: 已清空")
            conn.execute(text("DELETE FROM purchase_order"))
            print(f"   - 采购订单: 已清空")
            conn.execute(text("DELETE FROM purchase_plan_details"))
            print(f"   - 采购计划明细: 已清空")
            conn.execute(text("DELETE FROM shipment_records"))
            print(f"   - 出货记录: 已清空")
            conn.execute(text("DELETE FROM purchase_plans"))
            print(f"   - 采购计划: 已清空")
            conn.execute(text("DELETE FROM supplier"))
            print(f"   - 供应商: 已清空")
            
            # 2. 清空皮套管理（先清空，因为皮套引用了产品）
            print("\n2. 清空皮套管理...")
            conn.execute(text("DELETE FROM case_inventory_log"))
            print(f"   - 皮套库存日志: 已清空")
            conn.execute(text("DELETE FROM case_stock_out"))
            print(f"   - 皮套出库: 已清空")
            conn.execute(text("DELETE FROM case_stock_in"))
            print(f"   - 皮套入库: 已清空")
            conn.execute(text('DELETE FROM "case"'))
            print(f"   - 皮套: 已清空")
            
            # 3. 清空核心业务
            print("\n3. 清空核心业务...")
            conn.execute(text("DELETE FROM packaging_record"))
            print(f"   - 包装记录: 已清空")
            conn.execute(text("DELETE FROM craft_work"))
            print(f"   - 工艺记录: 已清空")
            conn.execute(text("DELETE FROM daily_production_record"))
            print(f"   - 生产记录: 已清空")
            conn.execute(text("DELETE FROM production_plan_log"))
            print(f"   - 生产计划日志: 已清空")
            conn.execute(text("DELETE FROM production_plan"))
            print(f"   - 生产计划: 已清空")
            conn.execute(text("DELETE FROM stock_return"))
            print(f"   - 退货记录: 已清空")
            conn.execute(text("DELETE FROM stock_out"))
            print(f"   - 出库记录: 已清空")
            conn.execute(text("DELETE FROM stock_in"))
            print(f"   - 入库记录: 已清空")
            conn.execute(text("DELETE FROM inventory_log"))
            print(f"   - 库存日志: 已清空")
            conn.execute(text("DELETE FROM order_sync_record"))
            print(f"   - 订单同步记录: 已清空")
            conn.execute(text("DELETE FROM sync_retry_queue"))
            print(f"   - 同步重试队列: 已清空")
            conn.execute(text("DELETE FROM approval_log"))
            print(f"   - 审批日志: 已清空")
            conn.execute(text("DELETE FROM approval_request"))
            print(f"   - 审批请求: 已清空")
            conn.execute(text("DELETE FROM order_status_log"))
            print(f"   - 订单状态日志: 已清空")
            conn.execute(text('DELETE FROM "order"'))
            print(f"   - 客户订单: 已清空")
            conn.execute(text("DELETE FROM product_packaging"))
            print(f"   - 产品包装BOM: 已清空")
            conn.execute(text("DELETE FROM product_accessory"))
            print(f"   - 产品辅料BOM: 已清空")
            conn.execute(text("DELETE FROM product_material"))
            print(f"   - 产品物料BOM: 已清空")
            conn.execute(text("DELETE FROM product_fabric"))
            print(f"   - 产品面料BOM: 已清空")
            conn.execute(text("DELETE FROM product"))
            print(f"   - 产品: 已清空")
            conn.execute(text("DELETE FROM modification_log"))
            print(f"   - 修改日志: 已清空")
            conn.execute(text("DELETE FROM saved_query"))
            print(f"   - 保存查询: 已清空")
            conn.execute(text("DELETE FROM order_sync_config"))
            print(f"   - 订单同步配置: 已清空")
            conn.execute(text("DELETE FROM customer_access_log"))
            print(f"   - 客户访问日志: 已清空")
            
            # 4. 清空系统管理
            print("\n4. 清空系统管理...")
            conn.execute(text("DELETE FROM app_version"))
            print(f"   - 版本管理: 已清空")
            conn.execute(text("DELETE FROM customer"))
            print(f"   - 客户: 已清空")
            # 保留 admin 用户的权限
            conn.execute(text("DELETE FROM user_permission WHERE user_id NOT IN (SELECT id FROM \"user\" WHERE username = 'admin')"))
            print(f"   - 用户权限: 已清空（保留admin）")
            conn.execute(text("DELETE FROM \"user\" WHERE username != 'admin'"))
            print(f"   - 用户: 已清空（保留admin）")
            
            # 5. 清空暂存数据
            print("\n5. 清空暂存数据...")
            conn.execute(text("DELETE FROM staging_stock_out"))
            print(f"   - 暂存出库: 已清空")
            conn.execute(text("DELETE FROM staging_stock_in"))
            print(f"   - 暂存入库: 已清空")
            conn.execute(text("DELETE FROM staging_order"))
            print(f"   - 暂存订单: 已清空")
            conn.execute(text("DELETE FROM staging_purchase_plan"))
            print(f"   - 暂存采购计划: 已清空")
            
            # 提交事务
            trans.commit()
            print("\n" + "=" * 80)
            print("✓ 所有数据已成功清空！")
            print("=" * 80)
            
        except Exception as e:
            trans.rollback()
            print(f"\n✗ 错误: {e}")
            print("已回滚所有更改")
            sys.exit(1)


if __name__ == '__main__':
    main()
