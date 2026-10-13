"""商品列表首屏缓存测试（A9-narrow）

背景：
  `list_products` docstring 声称"分页+缓存+搜索"，但实现此前无缓存，
  且 `CacheNamespace.PRODUCT_LIST`（cache_keys.py）全项目从未使用。
  本测试锁定新增的"首页 + 无搜索"缓存契约与写路径失效，防止后续回归：

    · page=1 且无搜索 → 读缓存，未命中回源后写缓存；二次请求命中，不再查库
    · page>1 或带 search → 既不读也不写缓存（防缓存键基数爆炸）
    · create/update/delete → 失效 product:list:* （经服务层，覆盖所有写入口）
    · 缓存命中与未命中的响应结构完全一致（前端零改动）

参考实现：customer.py（客户列表缓存权威模板）。
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from fastapi_app.api.v1.endpoints import product as product_endpoint
from fastapi_app.core.cache_keys import (
    PRODUCT_LIST_CACHE_PATTERN,
    PRODUCT_LIST_CACHE_TTL,
    CacheNamespace,
    build_cache_key,
)
from fastapi_app.core.exceptions import db_transaction
from fastapi_app.services import product_service
from fastapi_app.services.product_search_service import product_search_service

# 首页无搜索时使用的缓存键（per_page=20 为端点默认值）
_EXPECTED_KEY = build_cache_key(CacheNamespace.PRODUCT_LIST, 20)


def _full_item(id_val: int, name: str) -> dict:
    """与 Product.to_dict() 字段一致的完整商品 dict（10 字段，含 customers）。

    ProductListResponse.items 是 list[ProductResponse]，缺必填字段（initial_stock /
    current_stock）会在端点构造响应时抛 ValidationError，故假数据必须补全。
    customers 由 product_service._load_customers_for_products 在服务层补上
    （Product.to_dict 本身不含该字段）。
    """
    return {
        'id': id_val, 'name': name, 'barcode': None, 'price': 0.0,
        'image': None, 'factory': None, 'initial_stock': 0, 'current_stock': 0,
        'create_time': None, 'customers': [],
    }


_ITEMS = [_full_item(1, 'A')]


@pytest.fixture
def fake_cache(monkeypatch):
    """用进程内 dict 替换端点层的 safe_get/safe_set，规避真实 Redis 依赖。

    返回 (store, set_calls)：store 为"物理键 -> 值"映射，set_calls 记录
    每次 safe_set 的 (key, timeout, context)，用于断言 TTL 与写次数。
    """
    store: dict = {}
    set_calls: list = []

    async def fake_get(key, fallback=None, context=""):
        return store.get(key)

    async def fake_set(key, value, timeout=300, context=""):
        store[key] = value
        set_calls.append((key, timeout, context))
        return True

    monkeypatch.setattr(product_endpoint, 'safe_get', fake_get)
    monkeypatch.setattr(product_endpoint, 'safe_set', fake_set)
    return store, set_calls


@pytest.fixture
def fallback_cache(monkeypatch):
    """把全局 redis_cache 固化为本环境真实运行路径（fallback 内存缓存）。

    用于不 mock 缓存层、驱动真实前缀匹配与模式删除的端到端用例。
    """
    from utils.redis_cache import redis_cache

    monkeypatch.setattr(redis_cache, 'redis_client', None)
    monkeypatch.setattr(redis_cache, 'key_prefix', 'erp:')
    redis_cache._fallback_cache.clear()
    redis_cache._fallback_timestamps.clear()
    yield redis_cache
    redis_cache._fallback_cache.clear()
    redis_cache._fallback_timestamps.clear()


class TestListProductsCache:
    """读路径：命中条件、写缓存时机与响应一致性"""

    async def test_second_page1_request_hits_cache(self, client, monkeypatch, fake_cache):
        """page=1 无搜索：二次请求应命中缓存，get_products_page 只被调用一次"""
        store, set_calls = fake_cache
        db_calls: list = []

        async def fake_page(db, page=1, per_page=20, search='', **_kwargs):
            db_calls.append((page, per_page, search))
            return {
                'items': list(_ITEMS),
                'total': 1, 'page': page, 'per_page': per_page,
            }

        monkeypatch.setattr(product_service, 'get_products_page', fake_page)

        r1 = await client.get('/api/v1/products/list')
        r2 = await client.get('/api/v1/products/list')

        assert r1.status_code == 200
        assert r2.status_code == 200
        assert len(db_calls) == 1, '第二次请求应命中缓存，不再查库'
        assert len(set_calls) == 1, '首次回源后应写入缓存一次'

        # 写入的键与 TTL 契约
        key, timeout, _ctx = set_calls[0]
        assert key == _EXPECTED_KEY
        assert timeout == PRODUCT_LIST_CACHE_TTL == 60
        assert key in store

    async def test_cached_response_matches_miss_response(self, client, monkeypatch, fake_cache):
        """缓存命中的响应结构必须与未命中完全一致（前端零改动）"""
        _, _ = fake_cache
        items = [_full_item(1, 'A'), _full_item(2, 'B')]

        async def fake_page(db, page=1, per_page=20, search='', **_kwargs):
            return {
                'items': list(items),
                'total': 2, 'page': page, 'per_page': per_page,
            }

        monkeypatch.setattr(product_service, 'get_products_page', fake_page)

        miss = await client.get('/api/v1/products/list')
        hit = await client.get('/api/v1/products/list')

        assert miss.json() == hit.json()
        body = hit.json()
        assert body['success'] is True
        assert body['total'] == 2
        # image_thumb 是出站派生字段（2026-10-13）。本夹具 image=None → 派生结果也是 None，
        # 但它会作为 null 出现在每个 item 里；与真实响应一致才算「命中/未命中结构相同」。
        assert body['items'] == [{**it, 'image_thumb': None} for it in items]

    async def test_page2_does_not_write_cache(self, client, monkeypatch, fake_cache):
        """page>1：不读也不写缓存"""
        store, set_calls = fake_cache
        db_calls: list = []

        async def fake_page(db, page=1, per_page=20, search='', **_kwargs):
            db_calls.append((page, per_page, search))
            return {'items': [], 'total': 0, 'page': page, 'per_page': per_page}

        monkeypatch.setattr(product_service, 'get_products_page', fake_page)

        r = await client.get('/api/v1/products/list?page=2')

        assert r.status_code == 200
        assert set_calls == [], 'page>1 不得写缓存'
        assert store == {}, 'page>1 不得产生任何缓存键'
        assert db_calls == [(2, 20, '')]

    async def test_search_does_not_write_cache(self, client, monkeypatch, fake_cache):
        """带 search：不读也不写缓存"""
        store, set_calls = fake_cache
        db_calls: list = []

        async def fake_page(db, page=1, per_page=20, search='', **_kwargs):
            db_calls.append((page, per_page, search))
            return {'items': [], 'total': 0, 'page': page, 'per_page': per_page}

        monkeypatch.setattr(product_service, 'get_products_page', fake_page)

        r = await client.get('/api/v1/products/list?search=abc')

        assert r.status_code == 200
        assert set_calls == [], '带搜索不得写缓存'
        assert store == {}, '带搜索不得产生任何缓存键'
        assert db_calls == [(1, 20, 'abc')]


class TestCacheHelpers:
    """私有 helper 的短路行为（早返回时不触碰缓存层）"""

    async def test_get_helper_skips_non_first_page(self, monkeypatch):
        touched: list = []

        async def fake_get(key, fallback=None, context=""):
            touched.append(key)
            return {'items': [], 'total': 0}

        monkeypatch.setattr(product_endpoint, 'safe_get', fake_get)
        assert await product_endpoint._get_cached_product_page(2, 20, '') is None
        assert touched == [], 'page!=1 时不得读缓存'

    async def test_get_helper_skips_search(self, monkeypatch):
        touched: list = []

        async def fake_get(key, fallback=None, context=""):
            touched.append(key)
            return {'items': [], 'total': 0}

        monkeypatch.setattr(product_endpoint, 'safe_get', fake_get)
        assert await product_endpoint._get_cached_product_page(1, 20, 'x') is None
        assert touched == [], '带搜索时不得读缓存'

    async def test_set_helper_skips_non_first_page(self, monkeypatch):
        touched: list = []

        async def fake_set(key, value, timeout=300, context=""):
            touched.append(key)
            return True

        monkeypatch.setattr(product_endpoint, 'safe_set', fake_set)
        await product_endpoint._set_cached_product_page(2, 20, '', [], 0)
        assert touched == [], 'page!=1 时不得写缓存'

    async def test_set_helper_skips_search(self, monkeypatch):
        touched: list = []

        async def fake_set(key, value, timeout=300, context=""):
            touched.append(key)
            return True

        monkeypatch.setattr(product_endpoint, 'safe_set', fake_set)
        await product_endpoint._set_cached_product_page(1, 20, 'x', [], 0)
        assert touched == [], '带搜索时不得写缓存'


class TestProductListCacheInvalidation:
    """写路径经 post-commit 回调失效 product:list:*（覆盖所有调用入口）"""

    @pytest.fixture(autouse=True)
    def _spy_invalidation(self, monkeypatch):
        """记录 safe_delete_pattern 调用，并短路 cache_mgr 域失效（避免真实 Redis）"""
        recorded: list = []
        search_invalidated: list = []

        async def fake_delete_pattern(pattern, context=""):
            recorded.append(pattern)
            return 0

        async def fake_search_invalidate():
            search_invalidated.append(True)

        monkeypatch.setattr(product_service, 'safe_delete_pattern', fake_delete_pattern)
        monkeypatch.setattr(product_service.cache_mgr, 'invalidate', AsyncMock())
        # 产品搜索缓存的失效走搜索服务自己的 invalidate_cache()（域级失效覆盖不到
        # product:search:*），故此处单独 spy，而不是复用 safe_delete_pattern
        monkeypatch.setattr(product_search_service, 'invalidate_cache', fake_search_invalidate)
        self.recorded = recorded
        self.search_invalidated = search_invalidated

    @staticmethod
    def _setup_create(mock_db):
        """准备 create_product 所需的 mock_db 行为"""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()
        mock_db.refresh = AsyncMock()

    async def test_create_product_registers_post_commit_callback(self, mock_db):
        """注册阶段不得立即失效；回调被登记进 db.info['post_commit_callbacks']"""
        self._setup_create(mock_db)

        await product_service.create_product(
            mock_db, name='缓存失效-新增', barcode=None, image=None, initial_stock=0,
        )

        callbacks = mock_db.info.get('post_commit_callbacks', [])
        assert len(callbacks) == 2, '应注册两个 post-commit 回调（商品列表 + 产品搜索）'
        assert self.recorded == [], '注册阶段不得立即失效缓存'
        assert self.search_invalidated == [], '注册阶段不得立即失效搜索缓存'

        for callback in callbacks:
            await callback()
        assert self.recorded == [PRODUCT_LIST_CACHE_PATTERN], '回调执行时必须失效 product:list:*'
        assert self.search_invalidated == [True], '回调执行时必须失效产品搜索缓存'

    async def test_invalidation_deferred_until_commit(self, mock_db):
        """关键回归：post-commit 回调在提交前不得执行、提交后必须执行。

        本用例 mock 掉了域级失效（product_service.cache_mgr.invalidate），以**隔离**回调
        行为；真实场景中域级失效（INVENTORY 域）可能在**提交前**触发，post-commit 回调的
        作用是保证提交后再清一次以消除竞态（见 TestPostCommitRaceE2E）。
        """
        self._setup_create(mock_db)

        async with db_transaction(mock_db):
            await product_service.create_product(
                mock_db, name='缓存失效-延迟', barcode=None, image=None, initial_stock=0,
            )
            assert self.recorded == [], '回调不得在提交前执行'

        assert self.recorded == [PRODUCT_LIST_CACHE_PATTERN], '提交后必须失效'

    async def test_create_product_invalidates_after_commit(self, mock_db):
        self._setup_create(mock_db)
        async with db_transaction(mock_db):
            await product_service.create_product(
                mock_db, name='缓存失效-提交', barcode=None, image=None, initial_stock=0,
            )
        assert self.recorded == [PRODUCT_LIST_CACHE_PATTERN]

    async def test_rollback_does_not_invalidate(self, mock_db):
        """事务回滚时回调不执行，缓存不得被清"""
        self._setup_create(mock_db)

        with pytest.raises(RuntimeError):
            async with db_transaction(mock_db):
                await product_service.create_product(
                    mock_db, name='缓存失效-回滚', barcode=None, image=None, initial_stock=0,
                )
                raise RuntimeError('boom')

        assert self.recorded == [], '回滚路径不得执行失效回调'

    async def test_update_product_invalidates_after_commit(self, mock_db):
        product = MagicMock()
        product.id = 1
        product.name = '旧名称'
        product.barcode = ''
        product.image = ''
        product.initial_stock = 0
        product.current_stock = 0
        product.to_dict.return_value = {'id': 1, 'name': '新名称'}

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.flush = AsyncMock()
        mock_db.refresh = AsyncMock()

        with patch(
            'fastapi_app.services.product_service.get_product_for_update',
            new_callable=AsyncMock, return_value=product,
        ):
            async with db_transaction(mock_db):
                await product_service.update_product(
                    mock_db, 1, name='新名称', barcode=None, image=None, initial_stock=None,
                )
        assert self.recorded == [PRODUCT_LIST_CACHE_PATTERN]

    async def test_delete_product_invalidates_after_commit(self, mock_db):
        product = MagicMock()
        product.name = '缓存失效-删除'
        mock_db.get = AsyncMock(return_value=product)
        count_result = MagicMock()
        count_result.one.return_value = (0, 0, 0)
        delete_result = MagicMock()
        mock_db.execute = AsyncMock(side_effect=[count_result, delete_result])
        mock_db.delete = AsyncMock()
        mock_db.flush = AsyncMock()

        async with db_transaction(mock_db):
            await product_service.delete_product(mock_db, 1)
        assert self.recorded == [PRODUCT_LIST_CACHE_PATTERN]


class TestStockPathInvalidatesProductList:
    """#2 修复：库存/订单写路径必须同时失效 product:list:*（否则首屏库存陈旧）"""

    async def test_invalidate_stock_and_order_issues_product_list_pattern(self, monkeypatch):
        """invalidate_stock_and_order 必须额外下发 'product:list:*' 失效模式"""
        from fastapi_app.core import cache_invalidation as ci

        issued: list = []

        async def fake_by_pattern(pattern):
            issued.append(pattern)
            return 0

        monkeypatch.setattr(ci.cache_mgr, '_invalidate_by_pattern', fake_by_pattern)
        await ci.cache_mgr.invalidate_stock_and_order()

        assert 'product:list:*' in issued, '库存/订单失效必须覆盖 product:list:*'
        # 既有模式不得回归
        for legacy in ('inventory:*', 'orders:*', 'stockins:*', 'stockouts:*'):
            assert legacy in issued

    async def test_stock_invalidation_physically_clears_product_list_key(self, monkeypatch):
        """端到端（fallback 真实路径）：invalidate_stock_and_order 后 product:list:* 键被物理删除"""
        from fastapi_app.core import cache_invalidation as ci
        from fastapi_app.core.redis_wrapper import safe_get, safe_set
        from utils.redis_cache import redis_cache

        monkeypatch.setattr(redis_cache, 'redis_client', None)
        monkeypatch.setattr(redis_cache, 'key_prefix', 'erp:')
        redis_cache._fallback_cache.clear()
        redis_cache._fallback_timestamps.clear()

        await safe_set(_EXPECTED_KEY, {'items': [{'id': 1, 'current_stock': 10}], 'total': 1}, timeout=60)
        assert await safe_get(_EXPECTED_KEY) is not None

        await ci.cache_mgr.invalidate_stock_and_order()

        assert await safe_get(_EXPECTED_KEY) is None, (
            '库存写路径必须清 product:list:*，否则首屏 current_stock 陈旧'
        )


class TestCachePatternContract:
    """锁定 pattern 为单前缀，防止被误改成双前缀导致静默失效"""

    def test_pattern_is_single_prefix(self):
        assert PRODUCT_LIST_CACHE_PATTERN == 'erp:product:list:*'
        assert not PRODUCT_LIST_CACHE_PATTERN.startswith('erp:erp:'), (
            '双前缀会匹配不到任何键且静默失效'
        )

    def test_pattern_aligns_with_generated_key(self):
        """pattern 与 build_cache_key 生成的键必须同层（_make_key 幂等）"""
        from utils.redis_cache import RedisCacheManager

        mgr = RedisCacheManager()
        assert mgr._make_key(build_cache_key(CacheNamespace.PRODUCT_LIST, 20)) == 'erp:product:list:20'
        assert mgr._make_key(PRODUCT_LIST_CACHE_PATTERN) == 'erp:product:list:*'


class TestDomainPatternMultiMap:
    """B(INVENTORY)：product:list:* 挂到 INVENTORY 域，从而覆盖 ORDER_AND_INVENTORY 写路径"""

    def test_inventory_domain_map_is_multi_pattern(self):
        from fastapi_app.core.cache import _DOMAIN_PATTERN_MAP, CacheDomain

        patterns = _DOMAIN_PATTERN_MAP[CacheDomain.INVENTORY]
        assert isinstance(patterns, tuple), '一域多 pattern：value 必须是 tuple'
        assert 'inventory:*' in patterns
        assert PRODUCT_LIST_CACHE_PATTERN in patterns
        # 其余域仍为单元素 tuple，结构升级不改变既有语义
        assert _DOMAIN_PATTERN_MAP[CacheDomain.ORDER] == ('orders:*',)
        assert _DOMAIN_PATTERN_MAP[CacheDomain.PRODUCT] == ('products:*',)

    async def test_inventory_domain_clears_product_list_and_inventory(self, fallback_cache):
        from fastapi_app.core.cache import CacheDomain, invalidate_related_caches
        from fastapi_app.core.redis_wrapper import safe_get, safe_set

        await safe_set(_EXPECTED_KEY, {'items': [], 'total': 0}, timeout=60)
        await safe_set('inventory:some', {'x': 1}, timeout=60)
        await safe_set('orders:some', {'x': 1}, timeout=60)
        await safe_set(build_cache_key(CacheNamespace.PRODUCT_DETAIL, 1), {'id': 1}, timeout=60)
        await safe_set('products:all:limit5000', [{'id': 1}], timeout=60)

        await invalidate_related_caches(CacheDomain.INVENTORY)

        assert await safe_get(_EXPECTED_KEY) is None, 'INVENTORY 域应清 product:list:*'
        assert await safe_get('inventory:some') is None
        # 不得误清其它命名空间
        assert await safe_get('orders:some') is not None
        assert await safe_get(build_cache_key(CacheNamespace.PRODUCT_DETAIL, 1)) is not None
        assert await safe_get('products:all:limit5000') is not None

    async def test_order_and_inventory_domain_clears_product_list(self, fallback_cache):
        """复现 order/deduction、order/commands 的失效路径（ORDER_AND_INVENTORY）"""
        from fastapi_app.core.cache import CacheDomain, invalidate_related_caches
        from fastapi_app.core.redis_wrapper import safe_get, safe_set

        await safe_set(_EXPECTED_KEY, {'items': [], 'total': 0}, timeout=60)
        await safe_set('orders:some', {'x': 1}, timeout=60)

        await invalidate_related_caches(CacheDomain.ORDER_AND_INVENTORY)

        assert await safe_get(_EXPECTED_KEY) is None, 'ORDER_AND_INVENTORY 应清 product:list:*'
        assert await safe_get('orders:some') is None

    async def test_product_domain_does_not_clear_product_list(self, fallback_cache):
        """PRODUCT 域映射仍为 products:*（复数），不得误清 product:list:*（单数）"""
        from fastapi_app.core.cache import CacheDomain, invalidate_related_caches
        from fastapi_app.core.redis_wrapper import safe_get, safe_set

        await safe_set(_EXPECTED_KEY, {'items': [], 'total': 0}, timeout=60)
        await safe_set('products:all:limit5000', [{'id': 1}], timeout=60)

        await invalidate_related_caches(CacheDomain.PRODUCT)

        assert await safe_get('products:all:limit5000') is None
        assert await safe_get(_EXPECTED_KEY) is not None, 'PRODUCT 域不应清 product:list:*'


class TestPostCommitRaceE2E:
    """端到端：域级失效可能提交前触发，但 post-commit 回调保证清除并发回填的脏数据"""

    async def test_post_commit_callback_clears_repopulated_cache(self, mock_db, fallback_cache):
        """模拟竞态：提交前并发读把旧数据回写缓存 → 提交后回调必须清掉（不 mock 缓存层）"""
        from fastapi_app.core.redis_wrapper import safe_get, safe_set

        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=result)
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()
        mock_db.refresh = AsyncMock()

        await safe_set(_EXPECTED_KEY, {'items': [{'id': 1}], 'total': 1}, timeout=60)

        async with db_transaction(mock_db):
            await product_service.create_product(
                mock_db, name='竞态回填', barcode=None, image=None, initial_stock=0,
            )
            # 提交前：域级失效（INVENTORY 域）已清一次；此处模拟并发读把旧数据回写（脏数据）
            await safe_set(_EXPECTED_KEY, {'items': [{'id': 1}], 'total': 1}, timeout=60)
            assert await safe_get(_EXPECTED_KEY) is not None, '模拟的并发回填应存在'

        assert await safe_get(_EXPECTED_KEY) is None, (
            'post-commit 回调必须清掉并发回填的脏数据（消除竞态窗口）'
        )
