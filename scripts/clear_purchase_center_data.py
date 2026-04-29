"""
清空采购中心数据脚本

功能: 清空所有采购订单、订单明细、来料登记、修改日志、保存查询、状态日志等数据

警告: 此操作不可逆，请务必先备份数据库！

使用方法:
    python scripts/clear_purchase_center_data.py --dry-run  # 预览要删除的数据
    python scripts/clear_purchase_center_data.py --execute  # 执行清空操作
"""

import os
import sys
from datetime import datetime
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


def count_records(db: Session) -> dict:
    counts = {}

    counts['purchase_order'] = db.execute(text("SELECT COUNT(*) FROM purchase_order")).scalar()
    counts['purchase_order_item'] = db.execute(text("SELECT COUNT(*) FROM purchase_order_item")).scalar()
    counts['material_registration'] = db.execute(text("SELECT COUNT(*) FROM material_registration")).scalar()
    counts['material_registration_item'] = db.execute(text("SELECT COUNT(*) FROM material_registration_item")).scalar()
    counts['modification_log'] = db.execute(text("SELECT COUNT(*) FROM modification_log")).scalar()
    counts['saved_query'] = db.execute(text("SELECT COUNT(*) FROM saved_query")).scalar()
    counts['order_status_log'] = db.execute(text(
        "SELECT COUNT(*) FROM order_status_log WHERE target_type = 'purchase_order'"
    )).scalar()

    return counts


def clear_purchase_center_data(db: Session, dry_run: bool = True) -> dict:
    results = {}

    if dry_run:
        print("\n[DRY RUN] 预览要清空的数据:")
    else:
        print("\n[EXECUTE] 开始清空数据...")

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
        print(f"已清空数据:")
        print(f"  - 采购订单: {deleted_orders} 条")
        print(f"  - 订单明细: {deleted_items} 条")
        print(f"  - 来料登记: {deleted_reg} 条")
        print(f"  - 来料登记明细: {deleted_reg_items} 条")
        print(f"  - 修改日志: {deleted_mods} 条")
        print(f"  - 保存查询: {deleted_queries} 条")
        print(f"  - 状态日志: {deleted_status} 条")
    else:
        print(f"将清空数据:")
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


def main():
    import argparse
    parser = argparse.ArgumentParser(description='清空采购中心数据')
    parser.add_argument('--dry-run', action='store_true', help='预览要删除的数据，不实际删除')
    parser.add_argument('--execute', action='store_true', help='执行清空操作')
    args = parser.parse_args()

    if not args.dry_run and not args.execute:
        print("请指定 --dry-run 或 --execute")
        print("使用 --dry-run 预览要删除的数据")
        print("使用 --execute 执行清空操作")
        sys.exit(1)

    print("=" * 60)
    print("采购中心数据清空工具")
    print("=" * 60)

    engine = get_db_connection()

    with Session(engine) as db:
        print("\n当前数据统计:")
        counts = count_records(db)
        print(f"  - 采购订单: {counts['purchase_order']} 条")
        print(f"  - 订单明细: {counts['purchase_order_item']} 条")
        print(f"  - 来料登记: {counts['material_registration']} 条")
        print(f"  - 来料登记明细: {counts['material_registration_item']} 条")
        print(f"  - 修改日志: {counts['modification_log']} 条")
        print(f"  - 保存查询: {counts['saved_query']} 条")
        print(f"  - 状态日志: {counts['order_status_log']} 条")

        if args.dry_run:
            clear_purchase_center_data(db, dry_run=True)
        elif args.execute:
            print("\n警告: 即将清空所有采购中心数据！")
            print("此操作不可逆！")
            confirm = input("确认继续? (yes/no): ")
            if confirm.lower() not in ['yes', 'y']:
                print("已取消操作")
                sys.exit(0)
            clear_purchase_center_data(db, dry_run=False)

    print("\n" + "=" * 60)
    print("操作完成")
    print("=" * 60)


if __name__ == '__main__':
    main()
