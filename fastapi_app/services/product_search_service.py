"""
产品搜索服务

基于 BaseSearchService 的产品搜索实现（异步搜索路径）。
支持基础搜索与结果格式化；BOM 复制专用同步搜索已随 P1-11 同步死路径清理移除。
"""
import logging
from collections.abc import Callable
from typing import Any

from fastapi_app.services.base_search_service import BaseSearchService
from fastapi_app.services.product_visibility import visible_to_customer
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

    async def search_visible_to_customer_async_with_cache(        self,
        db,
        keyword: str,
        customer_id: int | None = None,
        limit: int = 50,
    ) -> list[dict]:
        """按客户可见性搜索。

        customer_id=None 表示不过滤，行为与 search_async_with_cache 完全一致
        （未选客户时保持现状）。

        刻意不覆写基类的 search_async_with_cache：那需要把 customer_id 塞进它的
        签名，而子类多一个形参会让 mypy 判为 LSP 违规（基类的 extra_conditions /
        cache_scope 在子类里缺失）。独立方法名既守住类型契约，也让「按客户搜索」
        这个意图在调用点自明。
        """
        if customer_id is None:
            return await self.search_async_with_cache(db, keyword, limit=limit)
        return await self.search_async_with_cache(
            db, keyword, limit=limit,
            extra_conditions=[visible_to_customer(customer_id)],
            cache_scope=f"cust{customer_id}",
        )


product_search_service = ProductSearchService()
