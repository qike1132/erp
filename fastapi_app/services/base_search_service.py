"""
通用搜索服务基类

统一产品搜索、客户搜索等模糊查询逻辑，消除重复代码。
支持可配置搜索字段、统一 ilike 大小写不敏感匹配、
可选 Redis 缓存。
"""
import hashlib
import json
import logging
from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any, Generic, TypeVar

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

from fastapi_app.core.redis_wrapper import safe_delete_pattern, safe_get, safe_set
from fastapi_app.core.sanitizer import escape_like

logger = logging.getLogger(__name__)

T = TypeVar("T")


class BaseSearchService(Generic[T], ABC):
    """通用搜索服务基类

    子类需实现:
        - get_model_class(): 返回 ORM 模型类
        - get_search_fields(): 返回可搜索的字段名列表
        - get_result_formatter(): 返回结果格式化函数

    使用示例:
        class ProductSearchService(BaseSearchService[Product]):
            def get_model_class(self) -> type: return Product
            def get_search_fields(self) -> list[str]: return ['name', 'barcode']
            def get_result_formatter(self) -> Callable: ...
    """

    def __init__(self, cache_prefix: str = "", cache_ttl: int = 300, use_trgm: bool = False):
        self.cache_prefix = cache_prefix
        self.cache_ttl = cache_ttl
        self.use_trgm = use_trgm

    @abstractmethod
    def get_model_class(self) -> type:
        """返回 ORM 模型类"""

    @abstractmethod
    def get_search_fields(self) -> list[str]:
        """返回可搜索的字段名列表"""

    @abstractmethod
    def get_result_formatter(self) -> Callable[[Any], dict]:
        """返回结果格式化函数，将 ORM 对象转为 dict"""

    def _build_keyword_conditions(self, keyword: str, use_trgm: bool = False):
        """构建关键词 OR 条件列表

        默认使用 ILIKE 子串匹配，确保中英文关键词都能命中。
        当 use_trgm=True 时额外叠加 pg_trgm % 相似度匹配（OR 组合），
        既保证子串命中，又增加模糊匹配能力。
        """
        model = self.get_model_class()
        search_fields = self.get_search_fields()
        conditions = []
        escaped = escape_like(keyword)
        for field_name in search_fields:
            col = getattr(model, field_name, None)
            if col is not None:
                # ILIKE 子串匹配：保证中文/短关键词必定命中
                conditions.append(col.ilike(f"%{escaped}%"))
                if use_trgm:
                    # pg_trgm % 运算符：额外叠加相似度模糊匹配
                    conditions.append(col.op('%')(keyword))
        return conditions

    def build_search_query_async(
        self,
        db: AsyncSession,
        keyword: str,
        status_filter: Any | None = None,
    ):
        """构建搜索查询（异步版本）"""
        model = self.get_model_class()
        query: Select = select(model)

        conditions = []
        if status_filter is not None:
            conditions.append(model.status == status_filter)  # type: ignore[attr-defined] # 同上

        if keyword:
            keyword_conds = self._build_keyword_conditions(keyword, self.use_trgm)
            if keyword_conds:
                conditions.append(or_(*keyword_conds))

        if conditions:
            query = query.where(*conditions)

        return query

    async def search_async(
        self,
        db: AsyncSession,
        keyword: str,
        limit: int = 20,
        status_filter: Any | None = None,
    ) -> list[dict]:
        """异步搜索，返回格式化后的 dict 列表"""
        query = self.build_search_query_async(db, keyword, status_filter)
        query = query.limit(limit)
        result = await db.execute(query)
        results = result.scalars().all()
        formatter = self.get_result_formatter()
        return [formatter(item) for item in results]

    def _get_cache_key(self, keyword: str, limit: int, status_filter: Any | None = None) -> str:
        """生成缓存键"""
        params = f"{keyword}:{limit}:{status_filter}"
        hash_val = hashlib.md5(params.encode(), usedforsecurity=False).hexdigest()[:12]
        return f"{self.cache_prefix}:search:{hash_val}"

    async def search_async_with_cache(
        self,
        db: AsyncSession,
        keyword: str,
        limit: int = 20,
        status_filter: Any | None = None,
    ) -> list[dict]:
        """带 Redis 缓存的异步搜索

        如果 cache_prefix 为空则跳过缓存，直接查询数据库。
        """
        if not self.cache_prefix:
            return await self.search_async(db, keyword, limit, status_filter)

        cache_key = self._get_cache_key(keyword, limit, status_filter)

        cached = await safe_get(cache_key, context='搜索缓存')
        if cached is not None:
            if isinstance(cached, str):
                return json.loads(cached)
            return cached

        results = await self.search_async(db, keyword, limit, status_filter)

        await safe_set(
            cache_key,
            json.dumps(results, ensure_ascii=False, default=str),
            timeout=self.cache_ttl,
            context='搜索缓存',
        )

        return results

    async def invalidate_cache(self):
        """清除搜索缓存（数据变更时调用）"""
        if not self.cache_prefix:
            return
        pattern = f"{self.cache_prefix}:search:*"
        await safe_delete_pattern(pattern, context='搜索缓存')
