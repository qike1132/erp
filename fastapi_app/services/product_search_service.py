"""
产品搜索服务

基于 BaseSearchService 的产品搜索实现，统一异步/同步搜索逻辑。
支持基础搜索（返回产品信息）和 BOM 搜索（返回产品+BOM 信息）。
"""
import logging
from collections.abc import Callable
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session, joinedload

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

    def search_for_bom_copy_sync(self, db: Session, keyword: str) -> list[dict]:
        """BOM 复制专用搜索（同步版本，包含 BOM 信息）

        保持与原 purchase_bom_copy_service.search_products_for_bom_copy
        完全相同的返回格式，确保向后兼容。
        """
        if not keyword:
            return []

        from fastapi_app.services.product_service import product_has_bom
        from sqlalchemy.orm import selectinload

        query = self.build_search_query_sync(db, keyword)
        query = query.options(
            joinedload(Product.material),
            selectinload(Product.fabrics),
            selectinload(Product.accessories),
        ).limit(20)
        products = query.all()

        result = []
        for p in products:
            has_bom = product_has_bom(p)
            material_count = (
                len(p.fabrics) + len(p.accessories)
                + (1 if p.material and getattr(p.material, "cotton_usage", Decimal("0")) > 0 else 0)
            )
            result.append({
                "id": p.id,
                "name": p.name,
                "barcode": p.barcode,
                "price": float(p.price) if p.price else 0,
                "has_bom": has_bom,
                "material_count": material_count,
            })

        return result


product_search_service = ProductSearchService()
