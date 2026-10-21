"""批量导入的缓存失效 —— 防止导入后前端看到最长 60s 的旧列表（2026-10-09 实测 20s 延迟）。

根因（systematic-debugging Phase 1 实证）：
- 前端导入成功即 ``invalidateQueries(['products-list'])`` 立即 refetch；
- ``/products/list`` 首页走 Redis 缓存（key ``erp:product:list:<per_page>``，TTL 60s，
  ``core/cache_keys.py::PRODUCT_LIST_CACHE_TTL``）；
- 批量导入（单 Sheet 与综合两条路径）此前全程无任何失效 → refetch 命中旧首页，
  新 SKU 要等 TTL 自然过期才可见（用户观测 20s ≈ 缓存的剩余寿命，0~60s 随机）。

守卫式测试（读源码断言接线存在，删一行这里就红）+ 回调机制行为测试。
"""
from __future__ import annotations

import asyncio
import pathlib
from unittest.mock import AsyncMock

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
SERVICES = REPO_ROOT / 'fastapi_app' / 'services'


class TestInvalidationWiring:
    """结构守卫：导入源码必须接线缓存失效。"""

    def test_sheet_import_path_has_no_second_wiring(self):
        """单 Sheet 路径的失效接线只在 core 一份（Z04-R3② 合并行循环骨架）。

        合并前 ``batch_import_service._run_sheet_rows`` 自带一份
        ``schedule_post_commit_invalidation`` 调用，与 core 骨架各持一份 —— 正是
        「改一处漏一处」的温床。现在行循环与钩子都只在 core，服务层再出现直连
        接线就说明第二份实现长回来了。
        行为侧的证据在 ``tests/test_sheet_import_shares_core_skeleton.py``
        （真实会话断言登记了哪些 post-commit 回调）。
        """
        text = (SERVICES / 'batch_import_service.py').read_text(encoding='utf-8')
        assert 'schedule_post_commit_invalidation' not in text, (
            'batch_import_service.py 又出现了自己的缓存失效接线：两条导入路径应共用 core 骨架'
        )

    def test_batch_import_core_invalidates_cache(self):
        text = (SERVICES / 'batch_import_core.py').read_text(encoding='utf-8')
        assert 'invalidate_batch_import_caches' in text, (
            'batch_import_core.py 缺少批量导入的缓存失效调用'
        )

    def test_invalidation_helper_covers_product_list_pattern(self):
        from fastapi_app.core.cache_keys import PRODUCT_LIST_CACHE_PATTERN
        from fastapi_app.services.batch_import_cache import BATCH_IMPORT_CACHE_PATTERNS

        assert PRODUCT_LIST_CACHE_PATTERN in BATCH_IMPORT_CACHE_PATTERNS

    def test_products_create_endpoint_invalidates_inventory_domain(self):
        """对照组守卫：单发添加产品的域级失效不能在重构中被顺手删掉"""
        text = (REPO_ROOT / 'fastapi_app' / 'api' / 'v1' / 'endpoints' / 'product.py').read_text(encoding='utf-8')
        assert 'CacheDomain.INVENTORY' in text


class TestPostCommitCallbackOnUowPath:
    """get_async_db（Unit-of-Work）提交后必须执行注册的回调。

    batch 端点不走 db_transaction；run_post_commit_callbacks 的 docstring 明说
    「不经 db_transaction 的入口必须在提交后显式调用，否则回调被静默丢弃」——
    而 get_async_db 恰好是这类入口里最大的一个，此前从不执行回调。
    """

    def test_get_async_db_source_calls_run_post_commit_callbacks(self):
        text = (REPO_ROOT / 'fastapi_app' / 'core' / 'database.py').read_text(encoding='utf-8')
        assert 'run_post_commit_callbacks' in text, (
            'get_async_db 提交后未执行 post_commit_callbacks —— 回调会被静默丢弃'
        )


def test_run_post_commit_callbacks_executes_and_clears():
    """回调执行后从 session.info 移除；回调抛异常不影响后续回调。"""
    from fastapi_app.core.exceptions import run_post_commit_callbacks

    db = AsyncMock()
    db.info = {}
    called: list[str] = []

    async def ok():
        called.append('ok')

    async def boom():
        raise RuntimeError('回调失败')

    async def after():
        called.append('after')

    db.info['post_commit_callbacks'] = [ok, boom, after]
    asyncio.run(run_post_commit_callbacks(db))
    assert called == ['ok', 'after'], '失败回调不应阻断后续回调'
    assert 'post_commit_callbacks' not in db.info, '执行后应清空回调列表'


def test_schedule_helper_degrades_to_immediate_for_infoless_session():
    """会话没有 dict 型 info（测试桩/轻量包装）时，回调退化为立即执行而非静默丢弃。"""
    from fastapi_app.core.cache_invalidation import schedule_post_commit_invalidation

    class _FakeSession:  # 与 test_stock_negative_policy 的桩同形：无 info 属性
        pass

    called: list[str] = []

    async def cb():
        called.append('x')

    async def main():
        schedule_post_commit_invalidation(_FakeSession(), cb)
        # create_task 调度，让出一轮事件循环让它跑完
        await asyncio.sleep(0)

    asyncio.run(main())
    assert called == ['x'], '无 info 的会话应立即执行回调（否则注册即丢失）'


def test_import_helper_registers_callback_via_schedule_helper():
    """导入侧注册回调必须走 core 的 schedule_post_commit_invalidation（单一事实来源）。"""
    from fastapi_app.core import cache_invalidation

    db = AsyncMock()
    db.info = {}
    called: list[str] = []

    async def cb():
        called.append('x')

    cache_invalidation.schedule_post_commit_invalidation(db, cb)
    assert db.info['post_commit_callbacks'] == [cb]
