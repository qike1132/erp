"""简单的数据清空脚本（已弃用）。

⚠️ 2026-10-17 审计 P1-35：本脚本硬编码的表清单已与 ORM metadata 漂移（漏板房 7 张、
湖北外发 5 张、notification / numbering_counter 等），且没有写护栏与保留表校验。
上线清库请使用 ``scripts/purge_simulated_data.py``（pg_dump 备份 + 保留表指纹复核 +
真 dry-run + 写护栏）。确需运行本脚本须显式加 ``--allow-deprecated-clear``。
"""
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from sqlalchemy import create_engine, text

from fastapi_app.core.config import settings


def main():
    if '--allow-deprecated-clear' not in sys.argv:
        print("本脚本已弃用：表清单已与 ORM 漂移，且无写护栏/保留表校验。")
        print("请改用 scripts/purge_simulated_data.py（备份+复核+真 dry-run）。")
        print("确需运行请显式加 --allow-deprecated-clear。")
        sys.exit(2)

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
            print("   - 来料登记明细: 已清空")
            conn.execute(text("DELETE FROM material_registration"))
            print("   - 来料登记: 已清空")
            conn.execute(text("DELETE FROM purchase_order_item"))
            print("   - 采购订单明细: 已清空")
            conn.execute(text("DELETE FROM purchase_order"))
            print("   - 采购订单: 已清空")
            conn.execute(text("DELETE FROM purchase_plan_details"))
            print("   - 采购计划明细: 已清空")
            conn.execute(text("DELETE FROM shipment_records"))
            print("   - 出货记录: 已清空")
            conn.execute(text("DELETE FROM purchase_plans"))
            print("   - 采购计划: 已清空")
            conn.execute(text("DELETE FROM supplier"))
            print("   - 供应商: 已清空")

            # 2. 清空皮套管理（先清空，因为皮套引用了产品）
            print("\n2. 清空皮套管理...")
            conn.execute(text("DELETE FROM case_movement"))
            print("   - 皮套流水: 已清空")
            conn.execute(text('DELETE FROM "case"'))
            print("   - 皮套: 已清空")

            # 3. 清空核心业务
            print("\n3. 清空核心业务...")
            conn.execute(text("DELETE FROM packaging_record"))
            print("   - 包装记录: 已清空")
            conn.execute(text("DELETE FROM craft_work"))
            print("   - 工艺记录: 已清空")
            conn.execute(text("DELETE FROM daily_production_record"))
            print("   - 生产记录: 已清空")
            conn.execute(text("DELETE FROM production_plan_log"))
            print("   - 生产计划日志: 已清空")
            conn.execute(text("DELETE FROM production_plan"))
            print("   - 生产计划: 已清空")
            conn.execute(text("DELETE FROM stock_return"))
            print("   - 退货记录: 已清空")
            conn.execute(text("DELETE FROM stock_out"))
            print("   - 出库记录: 已清空")
            conn.execute(text("DELETE FROM stock_in"))
            print("   - 入库记录: 已清空")
            conn.execute(text("DELETE FROM inventory_log"))
            print("   - 库存日志: 已清空")
            conn.execute(text("DELETE FROM order_sync_record"))
            print("   - 订单同步记录: 已清空")
            conn.execute(text("DELETE FROM sync_retry_queue"))
            print("   - 同步重试队列: 已清空")
            conn.execute(text("DELETE FROM approval_log"))
            print("   - 审批日志: 已清空")
            conn.execute(text("DELETE FROM approval_request"))
            print("   - 审批请求: 已清空")
            conn.execute(text("DELETE FROM order_status_log"))
            print("   - 订单状态日志: 已清空")
            conn.execute(text('DELETE FROM "order"'))
            print("   - 客户订单: 已清空")
            # product_packaging 已由迁移 pg_standalone_054 删除（ORM 模型已移除），不再引用
            conn.execute(text("DELETE FROM product_accessory"))
            print("   - 产品辅料BOM: 已清空")
            conn.execute(text("DELETE FROM product_material"))
            print("   - 产品物料BOM: 已清空")
            conn.execute(text("DELETE FROM product_fabric"))
            print("   - 产品面料BOM: 已清空")
            conn.execute(text("DELETE FROM product"))
            print("   - 产品: 已清空")
            conn.execute(text("DELETE FROM modification_log"))
            print("   - 修改日志: 已清空")
            conn.execute(text("DELETE FROM saved_query"))
            print("   - 保存查询: 已清空")
            conn.execute(text("DELETE FROM order_sync_config"))
            print("   - 订单同步配置: 已清空")
            conn.execute(text("DELETE FROM customer_access_log"))
            print("   - 客户访问日志: 已清空")

            # 4. 清空系统管理
            print("\n4. 清空系统管理...")
            conn.execute(text("DELETE FROM app_version"))
            print("   - 版本管理: 已清空")
            conn.execute(text("DELETE FROM customer"))
            print("   - 客户: 已清空")
            # 保留 admin 用户的权限
            conn.execute(text("DELETE FROM user_permission WHERE user_id NOT IN (SELECT id FROM \"user\" WHERE username = 'admin')"))
            print("   - 用户权限: 已清空（保留admin）")
            conn.execute(text("DELETE FROM \"user\" WHERE username != 'admin'"))
            print("   - 用户: 已清空（保留admin）")

            # 5. 清空暂存数据
            print("\n5. 清空暂存数据...")
            conn.execute(text("DELETE FROM staging_stock_out"))
            print("   - 暂存出库: 已清空")
            conn.execute(text("DELETE FROM staging_stock_in"))
            print("   - 暂存入库: 已清空")
            conn.execute(text("DELETE FROM staging_order"))
            print("   - 暂存订单: 已清空")
            conn.execute(text("DELETE FROM staging_purchase_plan"))
            print("   - 暂存采购计划: 已清空")

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
    from _prod_write_guard import require_prod_write_consent
    require_prod_write_consent('清空全部业务数据（订单/出入库/库存/产品/客户/供应商/用户）')
    main()
