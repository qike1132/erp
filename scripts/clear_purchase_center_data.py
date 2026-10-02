"""
清空采购中心数据脚本

功能:
  - 清空采购订单相关数据
  - 清空产品管理数据(BOM)
  - 清空客户订单数据

警告: 此操作不可逆，请务必先备份数据库！

使用方法:
    python scripts/clear_purchase_center_data.py --type orders --dry-run  # 预览采购订单数据
    python scripts/clear_purchase_center_data.py --type orders --execute  # 执行清空采购订单
    python scripts/clear_purchase_center_data.py --type products --dry-run  # 预览产品管理数据
    python scripts/clear_purchase_center_data.py --type products --execute  # 执行清空产品管理
    python scripts/clear_purchase_center_data.py --type customer_orders --dry-run  # 预览客户订单数据
    python scripts/clear_purchase_center_data.py --type customer_orders --execute  # 执行清空客户订单
    python scripts/clear_purchase_center_data.py --type all --dry-run  # 预览所有数据
    python scripts/clear_purchase_center_data.py --type all --execute  # 执行清空所有数据
"""

import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from fastapi_app.core.config import settings


def get_db_connection():
    database_url = settings.DATABASE_URL
    engine = create_engine(database_url)
    return engine


def count_purchase_order_data(db: Session) -> dict:
    counts = {}
    counts['purchase_order'] = db.execute(text("SELECT COUNT(*) FROM purchase_order")).scalar()
    counts['purchase_order_item'] = db.execute(text("SELECT COUNT(*) FROM purchase_order_item")).scalar()
    counts['material_registration'] = db.execute(text("SELECT COUNT(*) FROM material_registration")).scalar()
    counts['material_registration_item'] = db.execute(text("SELECT COUNT(*) FROM material_registration_item")).scalar()
    counts['modification_log'] = db.execute(text("SELECT COUNT(*) FROM modification_log WHERE target_type LIKE 'purchase%'")).scalar()
    counts['saved_query'] = db.execute(text("SELECT COUNT(*) FROM saved_query WHERE query_type LIKE 'purchase%'")).scalar()
    counts['order_status_log'] = db.execute(text(
        "SELECT COUNT(*) FROM order_status_log WHERE target_type = 'purchase_order'"
    )).scalar()
    return counts


def count_product_data(db: Session) -> dict:
    counts = {}
    counts['product'] = db.execute(text("SELECT COUNT(*) FROM product")).scalar()
    counts['product_fabric'] = db.execute(text("SELECT COUNT(*) FROM product_fabric")).scalar()
    counts['product_material'] = db.execute(text("SELECT COUNT(*) FROM product_material")).scalar()
    counts['product_accessory'] = db.execute(text("SELECT COUNT(*) FROM product_accessory")).scalar()
    counts['product_packaging'] = db.execute(text("SELECT COUNT(*) FROM product_packaging")).scalar()
    return counts


def count_customer_order_data(db: Session) -> dict:
    counts = {}
    counts['order'] = db.execute(text("SELECT COUNT(*) FROM \"order\"")).scalar()
    counts['approval'] = db.execute(text("SELECT COUNT(*) FROM approval_request WHERE order_id IN (SELECT id FROM \"order\")")).scalar()
    counts['stock_out'] = db.execute(text("SELECT COUNT(*) FROM stock_out WHERE order_id IN (SELECT id FROM \"order\")")).scalar()
    counts['order_sync'] = db.execute(text("SELECT COUNT(*) FROM order_sync_record")).scalar()
    counts['order_status_log'] = db.execute(text(
        "SELECT COUNT(*) FROM order_status_log WHERE target_type = 'unprocessed_order'"
    )).scalar()
    return counts


def clear_purchase_order_data(db: Session, dry_run: bool = True) -> dict:
    results = {}

    if dry_run:
        print("\n[DRY RUN] 预览要清空的采购订单数据:")
    else:
        print("\n[EXECUTE] 开始清空采购订单数据...")

    results['material_registration_item'] = db.execute(text(
        "DELETE FROM material_registration_item WHERE registration_id IN (SELECT id FROM material_registration)"
    ))
    deleted_reg_items = results['material_registration_item'].rowcount

    results['material_registration'] = db.execute(text("DELETE FROM material_registration"))
    deleted_reg = results['material_registration'].rowcount

    results['purchase_order_item'] = db.execute(text(
        "DELETE FROM purchase_order_item WHERE order_id IN (SELECT id FROM purchase_order)"
    ))
    deleted_items = results['purchase_order_item'].rowcount

    results['purchase_order'] = db.execute(text("DELETE FROM purchase_order"))
    deleted_orders = results['purchase_order'].rowcount

    results['modification_log'] = db.execute(text(
        "DELETE FROM modification_log WHERE target_type LIKE 'purchase%'"
    ))
    deleted_mods = results['modification_log'].rowcount

    results['saved_query'] = db.execute(text(
        "DELETE FROM saved_query WHERE query_type LIKE 'purchase%'"
    ))
    deleted_queries = results['saved_query'].rowcount

    results['order_status_log'] = db.execute(text(
        "DELETE FROM order_status_log WHERE target_type = 'purchase_order'"
    ))
    deleted_status = results['order_status_log'].rowcount

    if not dry_run:
        db.commit()
        print("已清空数据:")
        print(f"  - 采购订单: {deleted_orders} 条")
        print(f"  - 订单明细: {deleted_items} 条")
        print(f"  - 来料登记: {deleted_reg} 条")
        print(f"  - 来料登记明细: {deleted_reg_items} 条")
        print(f"  - 修改日志: {deleted_mods} 条")
        print(f"  - 保存查询: {deleted_queries} 条")
        print(f"  - 状态日志: {deleted_status} 条")
    else:
        print("将清空数据:")
        print(f"  - 采购订单: {deleted_orders} 条")
        print(f"  - 订单明细: {deleted_items} 条")
        print(f"  - 来料登记: {deleted_reg} 条")
        print(f"  - 来料登记明细: {deleted_reg_items} 条")
        print(f"  - 修改日志: {deleted_mods} 条")
        print(f"  - 保存查询: {deleted_queries} 条")
        print(f"  - 状态日志: {deleted_status} 条")

    return {
        'orders': deleted_orders,
        'items': deleted_items,
        'registrations': deleted_reg,
        'registration_items': deleted_reg_items,
        'modification_logs': deleted_mods,
        'saved_queries': deleted_queries,
        'status_logs': deleted_status
    }


def clear_product_data(db: Session, dry_run: bool = True) -> dict:
    results = {}

    if dry_run:
        print("\n[DRY RUN] 预览要清空的产品管理数据:")
    else:
        print("\n[EXECUTE] 开始清空产品管理数据...")

    results['product_packaging'] = db.execute(text("DELETE FROM product_packaging"))
    deleted_packaging = results['product_packaging'].rowcount

    results['product_accessory'] = db.execute(text("DELETE FROM product_accessory"))
    deleted_accessory = results['product_accessory'].rowcount

    results['product_material'] = db.execute(text("DELETE FROM product_material"))
    deleted_material = results['product_material'].rowcount

    results['product_fabric'] = db.execute(text("DELETE FROM product_fabric"))
    deleted_fabric = results['product_fabric'].rowcount

    deleted_product = 0
    print("\n  注意: 由于产品被订单表引用，BOM数据已清空，产品主数据保留")

    if not dry_run:
        db.commit()
        print("已清空数据:")
        print(f"  - 面料BOM: {deleted_fabric} 条")
        print(f"  - 填充物BOM: {deleted_material} 条")
        print(f"  - 辅料BOM: {deleted_accessory} 条")
        print(f"  - 包装BOM: {deleted_packaging} 条")
        print(f"  - 产品: {deleted_product} 条（保留，因被订单引用）")
    else:
        print("将清空数据:")
        print(f"  - 面料BOM: {deleted_fabric} 条")
        print(f"  - 填充物BOM: {deleted_material} 条")
        print(f"  - 辅料BOM: {deleted_accessory} 条")
        print(f"  - 包装BOM: {deleted_packaging} 条")
        print(f"  - 产品: {deleted_product} 条（将保留，因被订单引用）")

    return {
        'products': deleted_product,
        'fabrics': deleted_fabric,
        'materials': deleted_material,
        'accessories': deleted_accessory,
        'packagings': deleted_packaging
    }


def clear_customer_order_data(db: Session, dry_run: bool = True) -> dict:
    results = {}

    if dry_run:
        print("\n[DRY RUN] 预览要清空的客户订单数据:")
    else:
        print("\n[EXECUTE] 开始清空客户订单数据...")

    results['approval'] = db.execute(text(
        "DELETE FROM approval_request WHERE order_id IN (SELECT id FROM \"order\")"
    ))
    deleted_approval = results['approval'].rowcount

    results['stock_out'] = db.execute(text(
        "DELETE FROM stock_out WHERE order_id IN (SELECT id FROM \"order\")"
    ))
    deleted_stock_out = results['stock_out'].rowcount

    results['order_sync'] = db.execute(text("DELETE FROM order_sync_record"))
    deleted_sync = results['order_sync'].rowcount

    results['order_status_log'] = db.execute(text(
        "DELETE FROM order_status_log WHERE target_type = 'unprocessed_order'"
    ))
    deleted_status = results['order_status_log'].rowcount

    results['order'] = db.execute(text("DELETE FROM \"order\""))
    deleted_orders = results['order'].rowcount

    if not dry_run:
        db.commit()
        print("已清空数据:")
        print(f"  - 客户订单: {deleted_orders} 条")
        print(f"  - 审批记录: {deleted_approval} 条")
        print(f"  - 出库记录: {deleted_stock_out} 条")
        print(f"  - 订单同步记录: {deleted_sync} 条")
        print(f"  - 状态日志: {deleted_status} 条")
    else:
        print("将清空数据:")
        print(f"  - 客户订单: {deleted_orders} 条")
        print(f"  - 审批记录: {deleted_approval} 条")
        print(f"  - 出库记录: {deleted_stock_out} 条")
        print(f"  - 订单同步记录: {deleted_sync} 条")
        print(f"  - 状态日志: {deleted_status} 条")

    return {
        'orders': deleted_orders,
        'approvals': deleted_approval,
        'stock_outs': deleted_stock_out,
        'sync_records': deleted_sync,
        'status_logs': deleted_status
    }


def main():
    import argparse
    parser = argparse.ArgumentParser(description='清空采购中心数据')
    parser.add_argument('--type', choices=['orders', 'products', 'customer_orders', 'all'], default='all',
                        help='要清空的数据类型: orders(采购订单), products(产品管理), customer_orders(客户订单), all(全部)')
    parser.add_argument('--dry-run', action='store_true', help='预览要删除的数据，不实际删除')
    parser.add_argument('--execute', action='store_true', help='执行清空操作')
    args = parser.parse_args()

    if not args.dry_run and not args.execute:
        print("请指定 --dry-run 或 --execute")
        print("使用 --dry-run 预览要删除的数据")
        print("使用 --execute 执行清空操作")
        sys.exit(1)

    # 统一生产写护栏：只拦真正执行的路径（--dry-run 不写库，不拦）
    if args.execute:
        from _prod_write_guard import require_prod_write_consent
        require_prod_write_consent(
            f'清空采购中心数据（--execute，type={args.type}）',
            hint='不可逆；建议先 --dry-run 预览并确认已备份',
        )

    print("=" * 60)
    print("采购中心数据清空工具")
    print("=" * 60)

    engine = get_db_connection()

    with Session(engine) as db:
        if args.type in ['orders', 'all']:
            print("\n========== 采购订单数据统计 ==========")
            counts = count_purchase_order_data(db)
            print(f"  - 采购订单: {counts['purchase_order']} 条")
            print(f"  - 订单明细: {counts['purchase_order_item']} 条")
            print(f"  - 来料登记: {counts['material_registration']} 条")
            print(f"  - 来料登记明细: {counts['material_registration_item']} 条")
            print(f"  - 修改日志: {counts['modification_log']} 条")
            print(f"  - 保存查询: {counts['saved_query']} 条")
            print(f"  - 状态日志: {counts['order_status_log']} 条")

        if args.type in ['products', 'all']:
            print("\n========== 产品管理数据统计 ==========")
            counts = count_product_data(db)
            print(f"  - 产品: {counts['product']} 条")
            print(f"  - 面料BOM: {counts['product_fabric']} 条")
            print(f"  - 填充物BOM: {counts['product_material']} 条")
            print(f"  - 辅料BOM: {counts['product_accessory']} 条")
            print(f"  - 包装BOM: {counts['product_packaging']} 条")

        if args.type in ['customer_orders', 'all']:
            print("\n========== 客户订单数据统计 ==========")
            counts = count_customer_order_data(db)
            print(f"  - 客户订单: {counts['order']} 条")
            print(f"  - 审批记录: {counts['approval']} 条")
            print(f"  - 出库记录: {counts['stock_out']} 条")
            print(f"  - 订单同步记录: {counts['order_sync']} 条")
            print(f"  - 状态日志: {counts['order_status_log']} 条")

        if args.dry_run:
            if args.type in ['orders', 'all']:
                clear_purchase_order_data(db, dry_run=True)
            if args.type in ['products', 'all']:
                clear_product_data(db, dry_run=True)
            if args.type in ['customer_orders', 'all']:
                clear_customer_order_data(db, dry_run=True)
        elif args.execute:
            print("\n警告: 即将清空采购中心数据！")
            print("此操作不可逆！")
            confirm = input("确认继续? (yes/no): ")
            if confirm.lower() not in ['yes', 'y']:
                print("已取消操作")
                sys.exit(0)
            if args.type in ['orders', 'all']:
                clear_purchase_order_data(db, dry_run=False)
            if args.type in ['products', 'all']:
                clear_product_data(db, dry_run=False)
            if args.type in ['customer_orders', 'all']:
                clear_customer_order_data(db, dry_run=False)

    print("\n" + "=" * 60)
    print("操作完成")
    print("=" * 60)


if __name__ == '__main__':
    main()
