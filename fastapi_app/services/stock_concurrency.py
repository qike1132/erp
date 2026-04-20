"""
库存并发安全工具（向后兼容重导出）

实现已迁移至 fastapi_app.shared.stock_concurrency，此文件保留仅用于兼容现有导入路径。
新代码请使用：from fastapi_app.shared.stock_concurrency import ...
"""
from fastapi_app.shared.stock_concurrency import (  # noqa: F401
    StockConcurrentError,
    MAX_RETRY,
    get_product_for_update,
    get_product_for_update_sync,
    update_stock_with_optimistic_lock,
)
