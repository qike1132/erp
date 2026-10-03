"""
清空ERP系统业务数据脚本
保留系统配置表，清空所有业务数据表
"""
import asyncio
import sys
from pathlib import Path

# 让 `python scripts/archive/clear_business_data.py` 能直接跑：
#   · scripts/  —— 同级的 _prod_write_guard
#   · 项目根     —— fastapi_app
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from sqlalchemy import text

from fastapi_app.core.database import _AsyncSessionLocal, _init_async_engine

# 需要清空的业务表（按依赖关系排序，使用 TRUNCATE CASCADE）
BUSINESS_TABLES = [
    # 订单相关
    'order',
    'staging_order',
    'order_status_log',
    'order_sync_record',
    'sync_retry_queue',
    'order_batch_audit_log',

    # 采购订单
    'purchase_order_item',
    'purchase_order',

    # 采购计划
    'purchase_plan_details',
    'shipment_records',
    'purchase_plans',
    'staging_purchase_plan',

    # 来料登记
    'material_registration_item',
    'material_registration',

    # 库存相关
    'stock_out',
    'staging_stock_out',
    'stock_in',
    'staging_stock_in',
    'stock_return',
    'inventory_log',

    # 生产相关
    'daily_production_record',
    'production_plan_log',
    'production_plan',
    'craft_work',
    'packaging_record',

    # 皮套管理（case_stock_in/out/case_inventory_log 三表已由迁移
    # pg_standalone_062 删除，统一为 case_movement —— 原样 TRUNCATE 会报表不存在）
    'case_movement',
    'case',

    # 客户相关
    'customer_access_log',
    'customer',

    # 产品相关
    'product',
    'product_fabric',
    'product_material',
    'product_accessory',

    # 供应商
    'supplier',

    # 采购中心
    'modification_log',
    'saved_query',

    # 审批记录
    'approval_log',
    'approval_request',
]

# 保留的系统表（不清空）
SYSTEM_TABLES = [
    'user',
    'permission',
    # country 表已由迁移 pg_standalone_055 删除
    # device_token 表已由迁移 pg_standalone_054 删除
    'backup_record',
    'audit_log',
    'order_sync_config',
]


async def clear_business_data():
    """清空业务数据表。

    ⚠️ 这是**归档脚本**（功能已由带 dry-run/护栏的 `clear_all_data.py` 等取代）。
    2026-10-03 第三轮审计发现：本脚本此前因 `BUSINESS_TABLES` 里含**已被迁移删除**的
    `case_stock_out` 而必抛异常 → 整体回滚 → **等于空跑**；把表名修正为有效值后，
    它变成**真的会 TRUNCATE CASCADE 清掉约 30 张业务表并 commit**，却**没有任何护栏**
    —— 等于把一个"跑不动"的脚本修成了"一跑就清库"。故补上与其它清库脚本同口径的
    生产写护栏（`ERP_ALLOW_PROD_WRITE=1` 或 `--allow-prod-write`）。
    """
    from _prod_write_guard import require_prod_write_consent
    require_prod_write_consent(
        f'TRUNCATE CASCADE 清空 {len(BUSINESS_TABLES)} 张业务表（归档脚本，无 dry-run）',
        hint='不可逆；建议改用 scripts/clear_all_data.py --dry-run 先预览',
    )
    _init_async_engine()

    print("=" * 60)
    print("开始清空业务数据...")
    print("=" * 60)

    async with _AsyncSessionLocal() as session:
        try:
            # 使用 TRUNCATE CASCADE 清空所有业务表
            for table in BUSINESS_TABLES:
                print(f"正在清空表: {table}...")
                await session.execute(text(f'TRUNCATE TABLE "{table}" CASCADE'))

            await session.commit()
            print("\n" + "=" * 60)
            print("✓ 所有业务数据已清空完成!")
            print("=" * 60)

            # 显示保留的系统表
            print("\n保留的系统表:")
            for table in SYSTEM_TABLES:
                result = await session.execute(text(f'SELECT COUNT(*) FROM "{table}"'))
                count = result.scalar()
                print(f"  - {table}: {count} 条记录")

        except Exception as e:
            await session.rollback()
            print(f"\n✗ 清空数据时出错: {e}")
            sys.exit(1)


if __name__ == "__main__":
    asyncio.run(clear_business_data())
