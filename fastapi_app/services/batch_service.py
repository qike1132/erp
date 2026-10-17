"""
批量导入服务 Facade

职责已拆分（消除单一文件职责过载）：
- calculate_available_shipment_quantity → inventory_service
- Excel 导入相关函数（import_orders_from_data 等）→ batch_import_service
- process_order_deduction → order_deduction_service（E2 任务提取）

本模块保留 re-export 以保持向后兼容，现有代码无需修改导入路径。
"""
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

# Re-export 以保持向后兼容
from fastapi_app.services.batch_import_service import (
    cleanup_temp_file,
    import_orders_from_data,
    import_products_from_data,
    import_stockins_from_data,
    import_stockouts_from_data,
    parse_date_value,
    parse_excel_file_async,
    process_order_import,
    process_stockin_import,
    read_excel_sheets_async,
    validate_customer_name,
)
from fastapi_app.services.inventory_service import calculate_available_shipment_quantity
from fastapi_app.services.order_deduction_service import process_order_deduction
from fastapi_app.shared_models import Case, Product

__all__ = [
    'calculate_available_shipment_quantity',
    'cleanup_temp_file',
    'import_orders_from_data',
    'import_products_from_data',
    'import_stockins_from_data',
    'import_stockouts_from_data',
    'parse_date_value',
    'parse_excel_file_async',
    'process_order_deduction',
    'process_order_import',
    'process_stockin_import',
    'read_excel_sheets_async',
    'validate_customer_name',
]


# ==================== 查询函数（自 batch.py 端点下沉，纯查询搬移） ====================
# 注意：均接收端点传入的同一 AsyncSession，行锁语义与事务边界保持在端点请求事务内

async def find_case_locked(db: AsyncSession, identifier: str) -> tuple[Case | None, str | None]:
    """按产品名/条码或皮套名/条码查找皮套并加行锁。

    Returns:
        (case, None): 成功；
        (None, error_msg): 未找到或加锁失败。
    """
    result = await db.execute(select(Product).where((Product.name == identifier) | (Product.barcode == identifier)))
    product = result.scalars().first()
    case = None
    # P2-A2 类型收窄：Case 查询使用独立 result 变量，避免复用上方 Product 查询的 result 类型
    if product:
        case_result = await db.execute(select(Case).where(Case.product_id == product.id))
        case = case_result.scalar_one_or_none()
    if not case:
        case_result = await db.execute(select(Case).where((Case.name == identifier) | (Case.barcode == identifier)))
        case = case_result.scalars().first()
    if not case:
        return None, f'皮套 {identifier} 不存在'
    # 行锁确保并发安全。populate_existing 必须加：上面的无锁 SELECT 已把 Case 载入
    # session 身份映射，SQLAlchemy 默认不会用锁定读的结果刷新已有对象——锁拿到了、
    # 字段还是锁前旧值，后续负库存校验与 current_stock 直写都基于旧值
    # （与已修复的 F-BE-SVC-STOCK-02 同款缺陷）。
    case_result = await db.execute(
        select(Case).where(Case.id == case.id).with_for_update()
        .execution_options(populate_existing=True)
    )
    case = case_result.scalar_one_or_none()
    if not case:
        return None, f'皮套 {identifier} 加锁失败'
    return case, None


async def get_all_products(db: AsyncSession) -> list[Product]:
    """获取全部产品列表（用于构建导入产品映射）"""
    result = await db.execute(select(Product))
    return list(result.scalars().all())


async def get_product_by_identifier(db: AsyncSession, identifier: str) -> Product | None:
    """按产品名称或条码精确查找产品"""
    result = await db.execute(select(Product).where((Product.name == identifier) | (Product.barcode == identifier)))
    return result.scalars().first()


async def get_product_by_name_ci(db: AsyncSession, name: str) -> Product | None:
    """按产品名称查找产品（忽略大小写）"""
    result = await db.execute(select(Product).where(func.lower(Product.name) == func.lower(name)))
    return result.scalars().first()
