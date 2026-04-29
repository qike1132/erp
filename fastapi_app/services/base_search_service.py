"""
通用搜索服务基类

统一产品搜索、客户搜索等模糊查询逻辑，消除重复代码。
支持同步/异步双模式、可配置搜索字段、统一 ilike 大小写不敏感匹配、
可选 Redis 缓存。
"""
import hashlib
import json
import logging
from abc import ABC, abstractmethod
from typing import Any, Callable, Generic, List, Optional, TypeVar

from sqlalchemy import or_, select, func, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from fastapi_app.services import escape_like

logger = logging.getLogger(__name__)

T = TypeVar("T")


class BaseSearchService(Generic[T], ABC):
    """通用搜索服务基类

    子类需实现:
        - get_model_class(): 返回 ORM 模型类
        - get_search_fields(): 返回可搜索的字段名列表
        - get_result_serializer(): 返回结果序列化函数

    使用示例:
        class ProductSearchService(BaseSearchService[Product]):
            def get_model_class(self) -> type: return Product
            def get_search_fields(self) -> list[str]: return ['name', 'barcode']
            def get_result_serializer(self) -> Callable: ...
    """

    def __init__(self, cache_prefix: str = "", cache_ttl: int = 300, use_trgm: bool = True):
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
    def get_result_serializer(self) -> Callable[[Any], dict]:
        """返回结果序列化函数，将 ORM 对象转为 dict"""

    def _build_keyword_conditions(self, keyword: str, use_trgm: bool = True):
        """构建关键词 OR 条件列表

        当 use_trgm=True 且 pg_trgm 扩展可用时，使用 % 运算符
        进行三字组匹配，性能远优于 ILIKE '%keyword%'。
        % 运算符同时支持模糊匹配（如"泰迪能"匹配"泰迪熊"）。
        当 use_trgm=False 时回退到传统 ILIKE 模式。
        """
        model = self.get_model_class()
        search_fields = self.get_search_fields()
        conditions = []
        escaped = escape_like(keyword)
        for field_name in search_fields:
            col = getattr(model, field_name, None)
            if col is not None:
                if use_trgm:
                    # pg_trgm 的 % 运算符：基于相似度匹配，自动使用 GIN 索引
                    # 比 ILIKE 快 10-50 倍，且支持模糊匹配
                    conditions.append(
                        col.op('%')(keyword)
                    )
                else:
                    conditions.append(col.ilike(f"%{escaped}%"))
        return conditions

    def build_search_query_sync(
        self,
        db: Session,
        keyword: str,
        status_filter: Optional[Any] = None,
    ):
        """构建搜索查询（同步版本）"""
        model = self.get_model_class()
        query = db.query(model)

        if status_filter is not None:
            query = query.filter(model.status == status_filter)

        if keyword:
            keyword_conds = self._build_keyword_conditions(keyword, self.use_trgm)
            if keyword_conds:
                query = query.filter(or_(*keyword_conds))

        return query

    def build_search_query_async(
        self,
        db: AsyncSession,
        keyword: str,
        status_filter: Optional[Any] = None,
    ):
        """构建搜索查询（异步版本）"""
        model = self.get_model_class()
        query = select(model)

        conditions = []
        if status_filter is not None:
            conditions.append(model.status == status_filter)

        if keyword:
            keyword_conds = self._build_keyword_conditions(keyword, self.use_trgm)
            conditions.extend(keyword_conds)

        if conditions:
            query = query.where(*conditions)

        return query

    def search_sync(
        self,
        db: Session,
        keyword: str,
        limit: int = 20,
        status_filter: Optional[Any] = None,
    ) -> list[dict]:
        """同步搜索，返回序列化后的 dict 列表"""
        query = self.build_search_query_sync(db, keyword, status_filter)
        query = query.limit(limit)
        results = query.all()
        serializer = self.get_result_serializer()
        return [serializer(item) for item in results]

    async def search_async(
        self,
        db: AsyncSession,
        keyword: str,
        limit: int = 20,
        status_filter: Optional[Any] = None,
    ) -> list[dict]:
        """异步搜索，返回序列化后的 dict 列表"""
        query = self.build_search_query_async(db, keyword, status_filter)
        query = query.limit(limit)
        result = await db.execute(query)
        results = result.scalars().all()
        serializer = self.get_result_serializer()
        return [serializer(item) for item in results]

    def _get_cache_key(self, keyword: str, limit: int, status_filter: Optional[Any] = None) -> str:
        """生成缓存键"""
        params = f"{keyword}:{limit}:{status_filter}"
        hash_val = hashlib.md5(params.encode(), usedforsecurity=False).hexdigest()[:12]
        return f"{self.cache_prefix}:search:{hash_val}"

    async def search_async_with_cache(
        self,
        db: AsyncSession,
        keyword: str,
        limit: int = 20,
        status_filter: Optional[Any] = None,
    ) -> list[dict]:
        """带 Redis 缓存的异步搜索

        如果 cache_prefix 为空则跳过缓存，直接查询数据库。
        """
        if not self.cache_prefix:
            return await self.search_async(db, keyword, limit, status_filter)

        cache_key = self._get_cache_key(keyword, limit, status_filter)

        try:
            from utils.redis_cache import redis_cache

            cached = await redis_cache.get(cache_key)
            if cached is not None:
                if isinstance(cached, str):
                    return json.loads(cached)
                return cached
        except (OSError, ConnectionError, ValueError):
            logger.warning("搜索缓存读取失败", exc_info=True)

        results = await self.search_async(db, keyword, limit, status_filter)

        try:
            from utils.redis_cache import redis_cache

            await redis_cache.set(
                cache_key,
                json.dumps(results, ensure_ascii=False, default=str),
                timeout=self.cache_ttl,
            )
        except (OSError, ValueError):
            logger.warning("搜索缓存写入失败", exc_info=True)

        return results

    async def invalidate_cache(self):
        """清除搜索缓存（数据变更时调用）"""
        if not self.cache_prefix:
            return
        try:
            from utils.redis_cache import redis_cache

            pattern = f"{self.cache_prefix}:search:*"
            await redis_cache.delete_pattern(pattern)
        except (OSError, ConnectionError, ValueError):
            logger.warning("搜索缓存清除失败", exc_info=True)
