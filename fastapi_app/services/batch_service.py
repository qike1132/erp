"""
批量导入服务 Facade

职责已拆分（消除单一文件职责过载）：
- calculate_available_shipment_quantity → inventory_service
- Excel 导入相关函数（import_orders_from_data 等）→ batch_import_service
- process_order_deduction → order_deduction_service（E2 任务提取）

本模块保留 re-export 以保持向后兼容，现有代码无需修改导入路径。
"""
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
from fastapi_app.services.order_deduction_service import process_order_deduction  # noqa: F401

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
