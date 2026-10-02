"""
清空系统数据 - 完整脚本

功能:
  - 清空采购中心数据（供应商、物料计算器、来料登记）
  - 清空核心业务数据（产品清单、客户订单、出库管理、出货计划、生产报表）
  - 清空数据查询数据（订单查询、报表管理、皮套管理）
  - 清空系统管理数据（用户管理、客户管理、审批管理、版本管理）

警告: 此操作不可逆，请务必先备份数据库！

使用方法:
    python scripts/clear_all_data.py --dry-run          # 预览要清空的数据
    python scripts/clear_all_data.py --execute          # 执行清空操作（需要确认）
    python scripts/clear_all_data.py --execute --yes    # 执行清空操作（跳过确认）
    python scripts/clear_all_data.py --module purchase  # 仅清空采购中心数据
"""

import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
# 同目录的脚本模块（_prod_write_guard）—— 显式加进来，
# 这样无论以 `python scripts/x.py` 还是 importlib 加载都能导入
sys.path.insert(0, str(Path(__file__).parent))

from _prod_write_guard import affected_rows
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from fastapi_app.core.config import settings


def get_db_connection():
    database_url = settings.DATABASE_URL
    engine = create_engine(database_url)
    return engine


def count_all_data(db: Session) -> dict:
    """统计所有模块的数据量"""
    counts = {}

    # 采购中心
    counts['supplier'] = db.execute(text("SELECT COUNT(*) FROM supplier")).scalar()
    counts['purchase_order'] = db.execute(text("SELECT COUNT(*) FROM purchase_order")).scalar()
    counts['purchase_order_item'] = db.execute(text("SELECT COUNT(*) FROM purchase_order_item")).scalar()
    counts['material_registration'] = db.execute(text("SELECT COUNT(*) FROM material_registration")).scalar()
    counts['material_registration_item'] = db.execute(text("SELECT COUNT(*) FROM material_registration_item")).scalar()
    counts['purchase_plan'] = db.execute(text("SELECT COUNT(*) FROM purchase_plans")).scalar()
    counts['purchase_plan_detail'] = db.execute(text("SELECT COUNT(*) FROM purchase_plan_details")).scalar()
    counts['shipment_record'] = db.execute(text("SELECT COUNT(*) FROM shipment_records")).scalar()

    # 核心业务 - 产品
    counts['product'] = db.execute(text("SELECT COUNT(*) FROM product")).scalar()
    counts['product_fabric'] = db.execute(text("SELECT COUNT(*) FROM product_fabric")).scalar()
    counts['product_material'] = db.execute(text("SELECT COUNT(*) FROM product_material")).scalar()
    counts['product_accessory'] = db.execute(text("SELECT COUNT(*) FROM product_accessory")).scalar()
    # product_packaging 已由迁移 pg_standalone_054 删除（ORM 模型已移除），不再引用

    # 核心业务 - 订单和出库
    counts['order'] = db.execute(text("SELECT COUNT(*) FROM \"order\"")).scalar()
    counts['stock_out'] = db.execute(text("SELECT COUNT(*) FROM stock_out")).scalar()
    counts['stock_in'] = db.execute(text("SELECT COUNT(*) FROM stock_in")).scalar()
    counts['stock_return'] = db.execute(text("SELECT COUNT(*) FROM stock_return")).scalar()
    counts['inventory_log'] = db.execute(text("SELECT COUNT(*) FROM inventory_log")).scalar()

    # 核心业务 - 生产计划和报表
    counts['production_plan'] = db.execute(text("SELECT COUNT(*) FROM production_plan")).scalar()
    counts['production_plan_log'] = db.execute(text("SELECT COUNT(*) FROM production_plan_log")).scalar()
    counts['daily_production_record'] = db.execute(text("SELECT COUNT(*) FROM daily_production_record")).scalar()
    counts['craft_work'] = db.execute(text("SELECT COUNT(*) FROM craft_work")).scalar()
    counts['packaging_record'] = db.execute(text("SELECT COUNT(*) FROM packaging_record")).scalar()

    # 数据查询 - 皮套管理
    counts['case'] = db.execute(text('SELECT COUNT(*) FROM "case"')).scalar()
    counts['case_movement'] = db.execute(text("SELECT COUNT(*) FROM case_movement")).scalar()

    # 系统管理
    counts['customer'] = db.execute(text("SELECT COUNT(*) FROM customer")).scalar()
    counts['approval_request'] = db.execute(text("SELECT COUNT(*) FROM approval_request")).scalar()
    counts['approval_log'] = db.execute(text("SELECT COUNT(*) FROM approval_log")).scalar()
    counts['app_version'] = db.execute(text("SELECT COUNT(*) FROM app_version")).scalar()
    counts['user'] = db.execute(text("SELECT COUNT(*) FROM \"user\"")).scalar()
    counts['permission'] = db.execute(text("SELECT COUNT(*) FROM permission")).scalar()

    # 其他
    counts['modification_log'] = db.execute(text("SELECT COUNT(*) FROM modification_log")).scalar()
    counts['saved_query'] = db.execute(text("SELECT COUNT(*) FROM saved_query")).scalar()
    counts['order_status_log'] = db.execute(text("SELECT COUNT(*) FROM order_status_log")).scalar()
    counts['order_sync_record'] = db.execute(text("SELECT COUNT(*) FROM order_sync_record")).scalar()
    counts['sync_retry_queue'] = db.execute(text("SELECT COUNT(*) FROM sync_retry_queue")).scalar()
    counts['order_sync_config'] = db.execute(text("SELECT COUNT(*) FROM order_sync_config")).scalar()
    counts['customer_access_log'] = db.execute(text("SELECT COUNT(*) FROM customer_access_log")).scalar()
    counts['staging_order'] = db.execute(text("SELECT COUNT(*) FROM staging_order")).scalar()
    counts['staging_stock_in'] = db.execute(text("SELECT COUNT(*) FROM staging_stock_in")).scalar()
    counts['staging_stock_out'] = db.execute(text("SELECT COUNT(*) FROM staging_stock_out")).scalar()
    counts['staging_purchase_plan'] = db.execute(text("SELECT COUNT(*) FROM staging_purchase_plan")).scalar()

    return counts




def clear_purchase_center(db: Session, dry_run: bool = True) -> dict:
    """清空采购中心数据"""
    results = {}

    if dry_run:
        print("\n[DRY RUN] 预览要清空的采购中心数据:")
    else:
        print("\n[EXECUTE] 开始清空采购中心数据...")

    # 按照依赖关系从子表到父表删除
    results['material_registration_item'] = affected_rows(db, "DELETE FROM material_registration_item", dry_run=dry_run)
    results['material_registration'] = affected_rows(db, "DELETE FROM material_registration", dry_run=dry_run)
    results['purchase_order_item'] = affected_rows(db, "DELETE FROM purchase_order_item", dry_run=dry_run)
    results['purchase_order'] = affected_rows(db, "DELETE FROM purchase_order", dry_run=dry_run)
    results['purchase_plan_detail'] = affected_rows(db, "DELETE FROM purchase_plan_details", dry_run=dry_run)
    results['shipment_record'] = affected_rows(db, "DELETE FROM shipment_records", dry_run=dry_run)
    results['purchase_plan'] = affected_rows(db, "DELETE FROM purchase_plans", dry_run=dry_run)
    results['supplier'] = affected_rows(db, "DELETE FROM supplier", dry_run=dry_run)

    # 相关的日志和查询
    results['modification_log'] = affected_rows(db, "DELETE FROM modification_log WHERE target_type LIKE 'purchase%'", dry_run=dry_run)
    results['saved_query'] = affected_rows(db, "DELETE FROM saved_query WHERE query_type LIKE 'purchase%'", dry_run=dry_run)
    results['order_status_log'] = affected_rows(db, "DELETE FROM order_status_log WHERE target_type = 'purchase_order'", dry_run=dry_run)

    if not dry_run:
        db.commit()
        print("已清空采购中心数据:")
        print(f"  - 供应商: {results['supplier']} 条")
        print(f"  - 采购订单: {results['purchase_order']} 条")
        print(f"  - 采购订单明细: {results['purchase_order_item']} 条")
        print(f"  - 来料登记: {results['material_registration']} 条")
        print(f"  - 来料登记明细: {results['material_registration_item']} 条")
        print(f"  - 采购计划: {results['purchase_plan']} 条")
        print(f"  - 采购计划明细: {results['purchase_plan_detail']} 条")
        print(f"  - 出货记录: {results['shipment_record']} 条")
    else:
        print("将清空采购中心数据:")
        print(f"  - 供应商: {results['supplier']} 条")
        print(f"  - 采购订单: {results['purchase_order']} 条")
        print(f"  - 采购订单明细: {results['purchase_order_item']} 条")
        print(f"  - 来料登记: {results['material_registration']} 条")
        print(f"  - 来料登记明细: {results['material_registration_item']} 条")
        print(f"  - 采购计划: {results['purchase_plan']} 条")
        print(f"  - 采购计划明细: {results['purchase_plan_detail']} 条")
        print(f"  - 出货记录: {results['shipment_record']} 条")

    return results


def clear_core_business(db: Session, dry_run: bool = True) -> dict:
    """清空核心业务数据"""
    results = {}

    if dry_run:
        print("\n[DRY RUN] 预览要清空的核心业务数据:")
    else:
        print("\n[EXECUTE] 开始清空核心业务数据...")

    # 生产相关
    results['packaging_record'] = affected_rows(db, "DELETE FROM packaging_record", dry_run=dry_run)
    results['craft_work'] = affected_rows(db, "DELETE FROM craft_work", dry_run=dry_run)
    results['daily_production_record'] = affected_rows(db, "DELETE FROM daily_production_record", dry_run=dry_run)
    results['production_plan_log'] = affected_rows(db, "DELETE FROM production_plan_log", dry_run=dry_run)
    results['production_plan'] = affected_rows(db, "DELETE FROM production_plan", dry_run=dry_run)

    # 库存相关
    results['stock_return'] = affected_rows(db, "DELETE FROM stock_return", dry_run=dry_run)
    results['stock_out'] = affected_rows(db, "DELETE FROM stock_out", dry_run=dry_run)
    results['stock_in'] = affected_rows(db, "DELETE FROM stock_in", dry_run=dry_run)
    results['inventory_log'] = affected_rows(db, "DELETE FROM inventory_log", dry_run=dry_run)

    # 订单相关
    results['order_sync_record'] = affected_rows(db, "DELETE FROM order_sync_record", dry_run=dry_run)
    results['sync_retry_queue'] = affected_rows(db, "DELETE FROM sync_retry_queue", dry_run=dry_run)
    results['approval_log'] = affected_rows(db, "DELETE FROM approval_log", dry_run=dry_run)
    results['approval_request'] = affected_rows(db, "DELETE FROM approval_request", dry_run=dry_run)
    results['order_status_log'] = affected_rows(db, "DELETE FROM order_status_log WHERE target_type = 'unprocessed_order'", dry_run=dry_run)
    results['order'] = affected_rows(db, "DELETE FROM \"order\"", dry_run=dry_run)

    # 产品BOM（product_packaging 已删，见迁移 054）
    results['product_accessory'] = affected_rows(db, "DELETE FROM product_accessory", dry_run=dry_run)
    results['product_material'] = affected_rows(db, "DELETE FROM product_material", dry_run=dry_run)
    results['product_fabric'] = affected_rows(db, "DELETE FROM product_fabric", dry_run=dry_run)
    results['product'] = affected_rows(db, "DELETE FROM product", dry_run=dry_run)

    # 其他
    results['modification_log'] = affected_rows(db, "DELETE FROM modification_log WHERE target_type NOT LIKE 'purchase%'", dry_run=dry_run)
    results['saved_query'] = affected_rows(db, "DELETE FROM saved_query WHERE query_type NOT LIKE 'purchase%'", dry_run=dry_run)
    results['order_sync_config'] = affected_rows(db, "DELETE FROM order_sync_config", dry_run=dry_run)
    results['customer_access_log'] = affected_rows(db, "DELETE FROM customer_access_log", dry_run=dry_run)

    if not dry_run:
        db.commit()
        print("已清空核心业务数据:")
        print(f"  - 产品: {results['product']} 条")
        print(f"  - 产品BOM（面料/填充物/辅料）: {results['product_fabric'] + results['product_material'] + results['product_accessory']} 条")
        print(f"  - 客户订单: {results['order']} 条")
        print(f"  - 出库记录: {results['stock_out']} 条")
        print(f"  - 入库记录: {results['stock_in']} 条")
        print(f"  - 生产计划: {results['production_plan']} 条")
        print(f"  - 生产记录: {results['daily_production_record']} 条")
    else:
        print("将清空核心业务数据:")
        print(f"  - 产品: {results['product']} 条")
        print(f"  - 产品BOM（面料/填充物/辅料）: {results['product_fabric'] + results['product_material'] + results['product_accessory']} 条")
        print(f"  - 客户订单: {results['order']} 条")
        print(f"  - 出库记录: {results['stock_out']} 条")
        print(f"  - 入库记录: {results['stock_in']} 条")
        print(f"  - 生产计划: {results['production_plan']} 条")
        print(f"  - 生产记录: {results['daily_production_record']} 条")

    return results


def clear_case_management(db: Session, dry_run: bool = True) -> dict:
    """清空皮套管理数据"""
    results = {}

    if dry_run:
        print("\n[DRY RUN] 预览要清空的皮套管理数据:")
    else:
        print("\n[EXECUTE] 开始清空皮套管理数据...")

    results['case_movement'] = affected_rows(db, "DELETE FROM case_movement", dry_run=dry_run)
    results['case'] = affected_rows(db, 'DELETE FROM "case"', dry_run=dry_run)

    if not dry_run:
        db.commit()
        print("已清空皮套管理数据:")
        print(f"  - 皮套: {results['case']} 条")
        print(f"  - 皮套流水: {results['case_movement']} 条")
    else:
        print("将清空皮套管理数据:")
        print(f"  - 皮套: {results['case']} 条")
        print(f"  - 皮套流水: {results['case_movement']} 条")

    return results


def clear_system_management(db: Session, dry_run: bool = True, keep_admin: bool = True) -> dict:
    """清空系统管理数据"""
    results = {}

    if dry_run:
        print("\n[DRY RUN] 预览要清空的系统管理数据:")
    else:
        print("\n[EXECUTE] 开始清空系统管理数据...")

    results['app_version'] = affected_rows(db, "DELETE FROM app_version", dry_run=dry_run)
    results['customer'] = affected_rows(db, "DELETE FROM customer", dry_run=dry_run)

    # 用户相关 - 保留admin用户（必须先删 user_permission 再删 user，否则外键约束报错）
    if keep_admin:
        results['user_permission'] = affected_rows(db, "DELETE FROM user_permission WHERE user_id NOT IN (SELECT id FROM \"user\" WHERE username = 'admin')", dry_run=dry_run)
        results['user'] = affected_rows(db, "DELETE FROM \"user\" WHERE username != 'admin'", dry_run=dry_run)
    else:
        results['user_permission'] = affected_rows(db, "DELETE FROM user_permission", dry_run=dry_run)
        results['user'] = affected_rows(db, "DELETE FROM \"user\"", dry_run=dry_run)

    if not dry_run:
        db.commit()
        print("已清空系统管理数据:")
        print(f"  - 客户: {results['customer']} 条")
        print(f"  - 用户: {results['user']} 条（保留admin）")
        print(f"  - 版本管理: {results['app_version']} 条")
    else:
        print("将清空系统管理数据:")
        print(f"  - 客户: {results['customer']} 条")
        print(f"  - 用户: {results['user']} 条（保留admin）")
        print(f"  - 版本管理: {results['app_version']} 条")

    return results


def clear_staging_data(db: Session, dry_run: bool = True) -> dict:
    """清空暂存数据"""
    results = {}

    if dry_run:
        print("\n[DRY RUN] 预览要清空的暂存数据:")
    else:
        print("\n[EXECUTE] 开始清空暂存数据...")

    results['staging_stock_out'] = affected_rows(db, "DELETE FROM staging_stock_out", dry_run=dry_run)
    results['staging_stock_in'] = affected_rows(db, "DELETE FROM staging_stock_in", dry_run=dry_run)
    results['staging_order'] = affected_rows(db, "DELETE FROM staging_order", dry_run=dry_run)
    results['staging_purchase_plan'] = affected_rows(db, "DELETE FROM staging_purchase_plan", dry_run=dry_run)

    if not dry_run:
        db.commit()
        print("已清空暂存数据:")
        print(f"  - 暂存订单: {results['staging_order']} 条")
        print(f"  - 暂存入库: {results['staging_stock_in']} 条")
        print(f"  - 暂存出库: {results['staging_stock_out']} 条")
        print(f"  - 暂存采购计划: {results['staging_purchase_plan']} 条")
    else:
        print("将清空暂存数据:")
        print(f"  - 暂存订单: {results['staging_order']} 条")
        print(f"  - 暂存入库: {results['staging_stock_in']} 条")
        print(f"  - 暂存出库: {results['staging_stock_out']} 条")
        print(f"  - 暂存采购计划: {results['staging_purchase_plan']} 条")

    return results


def display_data_summary(counts: dict):
    """显示数据统计摘要"""
    print("\n" + "="*80)
    print("数据统计摘要")
    print("="*80)

    print("\n【采购中心】")
    print(f"  供应商: {counts['supplier']} 条")
    print(f"  采购订单: {counts['purchase_order']} 条")
    print(f"  来料登记: {counts['material_registration']} 条")
    print(f"  采购计划: {counts['purchase_plan']} 条")

    print("\n【核心业务】")
    print(f"  产品: {counts['product']} 条")
    print(f"  客户订单: {counts['order']} 条")
    print(f"  出库记录: {counts['stock_out']} 条")
    print(f"  生产计划: {counts['production_plan']} 条")
    print(f"  生产记录: {counts['daily_production_record']} 条")

    print("\n【数据查询】")
    print(f"  皮套: {counts['case']} 条")

    print("\n【系统管理】")
    print(f"  客户: {counts['customer']} 条")
    print(f"  用户: {counts['user']} 条")
    print(f"  版本管理: {counts['app_version']} 条")

    print("\n【其他】")
    print(f"  修改日志: {counts['modification_log']} 条")
    print(f"  保存查询: {counts['saved_query']} 条")
    print(f"  订单状态日志: {counts['order_status_log']} 条")
    print("="*80)


def main():
    import argparse
    parser = argparse.ArgumentParser(description='清空系统数据')
    parser.add_argument('--dry-run', action='store_true', help='预览要清空的数据')
    parser.add_argument('--execute', action='store_true', help='执行清空操作')
    parser.add_argument('--yes', action='store_true', help='跳过确认提示')
    parser.add_argument('--module', choices=['purchase', 'core', 'case', 'system', 'staging', 'all'],
                        default='all', help='指定要清空的模块')
    parser.add_argument('--keep-admin', action='store_true', default=True, help='保留admin用户（默认保留）')
    parser.add_argument('--no-keep-admin', action='store_false', dest='keep_admin', help='清空所有用户（包括admin）')
    parser.add_argument('--allow-prod-write', action='store_true',
                        help='显式授权写生产库（与 ERP_ALLOW_PROD_WRITE=1 等价）')

    args = parser.parse_args()

    if not args.dry_run and not args.execute:
        print("请指定 --dry-run 或 --execute")
        print("使用 --dry-run 预览要清空的数据")
        print("使用 --execute 执行清空操作")
        sys.exit(1)

    # 统一生产写护栏：只拦真正执行的路径（--dry-run 不写库，不拦）
    if args.execute:
        from _prod_write_guard import require_prod_write_consent
        require_prod_write_consent(
            f'清空系统数据（--execute，模块={args.module}）',
            hint='不可逆；建议先 --dry-run 预览并确认已备份',
        )

    print("="*80)
    print("系统数据清空工具")
    print("="*80)
    print("\n警告: 此操作不可逆！")
    print("强烈建议先使用 --dry-run 预览，确认无误后再执行 --execute")

    engine = get_db_connection()

    with Session(engine) as db:
        # 先统计数据
        print("\n正在统计数据...")
        counts = count_all_data(db)
        display_data_summary(counts)

        if args.dry_run:
            # 预览模式
            if args.module in ['purchase', 'all']:
                clear_purchase_center(db, dry_run=True)
            if args.module in ['case', 'all']:
                clear_case_management(db, dry_run=True)
            if args.module in ['core', 'all']:
                clear_core_business(db, dry_run=True)
            if args.module in ['system', 'all']:
                clear_system_management(db, dry_run=True, keep_admin=args.keep_admin)
            if args.module in ['staging', 'all']:
                clear_staging_data(db, dry_run=True)
        elif args.execute:
            # 执行模式
            if not args.yes:
                confirm = input("\n确认要清空数据吗？此操作不可逆！(yes/no): ")
                if confirm.lower() not in ['yes', 'y']:
                    print("已取消操作")
                    sys.exit(0)

            if args.module in ['purchase', 'all']:
                clear_purchase_center(db, dry_run=False)
            if args.module in ['case', 'all']:
                clear_case_management(db, dry_run=False)
            if args.module in ['core', 'all']:
                clear_core_business(db, dry_run=False)
            if args.module in ['system', 'all']:
                clear_system_management(db, dry_run=False, keep_admin=args.keep_admin)
            if args.module in ['staging', 'all']:
                clear_staging_data(db, dry_run=False)

            print("\n" + "="*80)
            print("操作完成！")
            print("="*80)


if __name__ == '__main__':
    main()
