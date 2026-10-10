"""批量导入的缓存失效集合（2026-10-09 实测导入后前端 20s 看不到新 SKU）。

为什么导入必须自己失效缓存
----------------------------
前端导入成功即 ``invalidateQueries(['products-list'])`` 立即 refetch，但
``/products/list`` 首页走 Redis 缓存（key ``erp:product:list:<per_page>``，TTL 60s，
见 ``core/cache_keys.py::PRODUCT_LIST_CACHE_TTL``）。批量导入此前全程无任何失效，
refetch 命中旧首页，新数据要等 TTL 自然过期（0~60s 随机）才可见 —— 单发
添加/编辑路径早有「域级 + post-commit」双保险，唯独导入漏了。

为什么不能只依赖 INVENTORY 域
----------------------------
导入还会改产品主数据（新增 SKU、改名、改条码），``products:*``（PRODUCT 域）
也该清。这里显式列出模式而非借用某个域：导入是跨域写（产品 + 库存 + 报表），
它的失效集合就是自己的单一事实来源。

为什么同时给每行注册 post-commit 回调
------------------------------------
缓存失效挂在**请求收尾提交之后**（``run_post_commit_callbacks``）执行，避免
「提交前失效、并发读回写脏数据」的竞态（与 ``product_service`` 同款）。回调由
``core/exceptions.run_post_commit_callbacks`` 执行；``get_async_db``（本仓库的
Unit-of-Work 依赖）已在 commit 成功后调用它 —— 这是本次一并补上的缺口。
"""
from __future__ import annotations

import logging

from fastapi_app.core.cache_keys import PRODUCT_LIST_CACHE_PATTERN
from fastapi_app.core.redis_wrapper import safe_delete_pattern

logger = logging.getLogger(__name__)

#: 批量导入会触碰的缓存键空间。ORDER/STOCKIN/STOCKOUT 域模式覆盖各单据的
#: 列表/统计缓存；product:list 是产品列表首屏（含 current_stock）；
#: product:search:* 是下单页 SKU 联想（base_search_service 的键形如
#: ``product:search:<md5>``，TTL 300s —— 导入改名/改归属不清它，下单页
#: 会继续按旧口径联想 5 分钟）。
BATCH_IMPORT_CACHE_PATTERNS: tuple[str, ...] = (
    'inventory:*',
    'orders:*',
    'stockins:*',
    'stockouts:*',
    'reports:*',
    'products:*',
    PRODUCT_LIST_CACHE_PATTERN,
    'product:search:*',
)


async def invalidate_batch_import_caches() -> None:
    """清掉批量导入触碰的全部缓存键空间。

    自带异常兜底：缓存侧故障不得让已经落库的导入变成失败的响应
    （与 ``product_service._invalidate_product_list_cache`` 同款容错）。
    """
    for pattern in BATCH_IMPORT_CACHE_PATTERNS:
        try:
            await safe_delete_pattern(pattern, context='批量导入缓存')
        except Exception:  # defensive: 逐模式兜底，一个失败不影响其余失效
            logger.warning('批量导入缓存失效失败: pattern=%s', pattern, exc_info=True)
