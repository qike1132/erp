"""
统一缓存失效管理器

整合系统中分散的缓存失效机制，提供一致的失效接口：
- 域枚举失效：CacheDomain → pattern 映射
- 模式匹配失效：通配符 pattern 匹配缓存键
- 键列表失效：直接删除指定 Redis 键
- 采购中心失效：跨进程 Pub/Sub 广播

所有方法在 Redis 不可用时静默降级，不影响核心业务流程。
"""
import logging
from collections.abc import Awaitable, Callable
from enum import Enum
from typing import Any

from fastapi_app.core.cache import CacheDomain, invalidate_cache, invalidate_related_caches

logger = logging.getLogger(__name__)


class InvalidationStrategy(Enum):
    """缓存失效策略枚举"""
    DOMAIN = "domain"       # 基于 CacheDomain 域枚举
    PATTERN = "pattern"     # 基于通配符模式匹配
    KEYS = "keys"           # 基于键列表直接删除
    PURCHASE = "purchase"   # 采购中心专用（含跨进程广播）


class CacheInvalidationManager:
    """统一的缓存失效管理器"""

    async def invalidate(
        self,
        strategy: InvalidationStrategy,
        target: Any = None,
    ) -> int:
        """统一的缓存失效接口

        Args:
            strategy: 失效策略
            target: 失效目标
                - DOMAIN: CacheDomain 枚举（支持按位或组合）
                - PATTERN: 通配符模式字符串，如 'orders:*'
                - KEYS: 要删除的 Redis 键列表
                - PURCHASE: 忽略 target

        Returns:
            失效的缓存条目数
        """
        if strategy == InvalidationStrategy.DOMAIN:
            return await self._invalidate_by_domain(target)
        elif strategy == InvalidationStrategy.PATTERN:
            return await self._invalidate_by_pattern(target)
        elif strategy == InvalidationStrategy.KEYS:
            return await self._invalidate_by_keys(target or [])
        elif strategy == InvalidationStrategy.PURCHASE:
            return await self._invalidate_purchase_caches()
        else:
            logger.warning("不支持的失效策略: %s", strategy)
            return 0

    # ---- 便捷方法 ----

    async def invalidate_dashboard(self) -> int:
        """失效 Dashboard 相关缓存"""
        count = 0
        for pattern in ('dashboard:*', 'dashboard:stats', 'dashboard:activities'):
            count += await self._invalidate_by_pattern(pattern)
        logger.info("Dashboard 缓存已失效")
        return count

    async def invalidate_stock_and_order(self) -> int:
        """失效库存+订单相关缓存（stock_service 常用组合）"""
        count = 0
        count += await self._invalidate_by_pattern('inventory:*')
        count += await self._invalidate_by_pattern('orders:*')
        count += await self._invalidate_by_pattern('stockins:*')
        count += await self._invalidate_by_pattern('stockouts:*')
        # 报表流水由订单/备货/出货聚合而来：入库/出库/退货写入后必须一并失效，
        # 否则报表页在 TTL 内持续展示写入前的旧数据。
        count += await self._invalidate_by_pattern('reports:*')
        # 商品列表首屏缓存亦含 current_stock（Product.to_dict），库存/订单变更后必须一并失效，
        # 否则首屏库存显示最多陈旧一个 TTL。
        # 模式不带 'erp:' 前缀：本方法经 _invalidate_by_pattern → cache.invalidate_cache →
        # redis.delete_pattern → redis_cache._make_key，后者对无前缀模式补 'erp:'、
        # 对已带前缀的幂等原样返回，故 'product:list:*' 与 'erp:product:list:*' 物理等价，
        # 这里沿用相邻行的无前缀风格。
        # ⚠️ 本行与 cache.py:_DOMAIN_PATTERN_MAP 中 INVENTORY 域的 product:list:* 挂载
        # **不是重复**：本函数直连 _invalidate_by_pattern，不经过 _DOMAIN_PATTERN_MAP。
        # 两者覆盖不同入口，请勿删除其一。
        count += await self._invalidate_by_pattern('product:list:*')
        count += await self.invalidate_dashboard()
        return count

    async def invalidate_purchase(self) -> int:
        """失效采购中心缓存（含跨进程广播）"""
        return await self._invalidate_purchase_caches()

    # ---- 内部实现 ----

    async def _invalidate_by_domain(self, domains: CacheDomain) -> int:
        """基于域枚举失效"""
        return await invalidate_related_caches(domains)

    async def _invalidate_by_pattern(self, pattern: str) -> int:
        """基于模式匹配失效"""
        return await invalidate_cache(pattern)

    async def _invalidate_by_keys(self, keys: list[str]) -> int:
        """基于键列表直接删除 Redis 缓存"""
        if not keys:
            return 0
        from fastapi_app.core.redis_wrapper import safe_delete
        count = 0
        for key in keys:
            if await safe_delete(key, context='统一缓存失效'):
                count += 1
        return count

    async def _invalidate_purchase_caches(self) -> int:
        """失效采购中心缓存（含跨进程广播）"""
        try:
            from fastapi_app.core.purchase_cache import invalidate_purchase_caches
            return await invalidate_purchase_caches()
        except (RuntimeError, OSError, ValueError):
            logger.warning("采购中心缓存失效失败", exc_info=True)
            return 0


# 全局单例
cache_mgr = CacheInvalidationManager()


def schedule_post_commit_invalidation(session: Any, callback: Callable[[], Awaitable[Any]]) -> None:
    """注册「事务提交成功后」执行的缓存失效回调。

    解决「提交前失效」的竞态：并发请求可能在本次提交前读到旧数据并回写缓存，
    提交后不再失效，脏数据将留存至 TTL 到期。

    回调由 db_transaction 在成功 commit 后执行，事务回滚则不执行；因此调用处仍需
    保留原有的提交前失效作为广覆盖 —— 不经 db_transaction 提交的调用方（ARQ 任务、
    直连会话的脚本）不会执行本回调，只挂回调会导致这些入口彻底失去失效。
    """
    session.info.setdefault('post_commit_callbacks', []).append(callback)
