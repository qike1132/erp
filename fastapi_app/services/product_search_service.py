"""
产品搜索服务

基于 BaseSearchService 的产品搜索实现（异步搜索路径）。
支持基础搜索与结果格式化；BOM 复制专用同步搜索已随 P1-11 同步死路径清理移除。
"""
import logging
from collections.abc import Callable
from typing import Any

from fastapi_app.services.base_search_service import BaseSearchService
from fastapi_app.shared_models import Product

logger = logging.getLogger(__name__)


class ProductSearchService(BaseSearchService[Product]):

    def __init__(self):
        super().__init__(cache_prefix="product", cache_ttl=300)

    def get_model_class(self) -> type:
        return Product

    def get_search_fields(self) -> list[str]:
        return ["name", "barcode"]

    def get_result_formatter(self) -> Callable[[Any], dict]:
        def serialize(product: Product) -> dict:
            return {
                "id": product.id,
                "name": product.name,
                "barcode": product.barcode or "",
                "price": float(product.price) if product.price else 0,
                "current_stock": product.current_stock,
            }
        return serialize


product_search_service = ProductSearchService()
