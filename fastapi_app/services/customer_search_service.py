"""
客户搜索服务

基于 BaseSearchService 的客户搜索实现，统一搜索逻辑。
默认按 status=True 过滤，搜索字段包括 name、contact、phone。
"""
import logging
from typing import Any, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.services.base_search_service import BaseSearchService
from fastapi_app.shared_models import Customer

logger = logging.getLogger(__name__)


class CustomerSearchService(BaseSearchService[Customer]):

    def __init__(self):
        super().__init__(cache_prefix="customer", cache_ttl=300)

    def get_model_class(self) -> type:
        return Customer

    def get_search_fields(self) -> list[str]:
        return ["name", "contact", "phone"]

    def get_result_serializer(self) -> Callable[[Any], dict]:
        def serialize(customer: Customer) -> dict:
            return {
                "id": customer.id,
                "name": customer.name,
                "contact": customer.contact or "",
                "phone": customer.phone or "",
                "status": customer.status,
            }
        return serialize

    async def search_active_customers(
        self,
        db: AsyncSession,
        keyword: str,
        limit: int = 20,
    ) -> list[dict]:
        """搜索启用状态的客户（最常用场景的快捷方法）"""
        return await self.search_async_with_cache(
            db, keyword, limit=limit, status_filter=True
        )


customer_search_service = CustomerSearchService()
