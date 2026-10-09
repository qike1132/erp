"""商品列表首屏缓存 —— QA 独立验证（严过关）

与工程师的 test_product_list_cache.py 互补：工程师的用例 monkeypatch 掉了
`safe_get/safe_set/safe_delete_pattern`，因此**从未验证真实缓存层的前缀匹配**。
本文件刻意**不 monkeypatch 缓存层**，而是驱动真实的 utils.redis_cache.RedisCacheManager，
覆盖：

  ① 物理层端到端：写入键 'erp:product:list:20' 能被模式 'erp:product:list:*' 真实删除
     （fallback 路径 + Redis-scan 分支的 match 参数）
  ② 缓存条件边界：per_page 分桶（防串数据）、search/page 短路、search=None 行为
  ③ 写后一致性：create/update/delete 真实清空；失效相对事务提交点的时序（竞态窗口）
  ④ 响应结构一致性：缓存命中 vs 未命中的字段与值完全一致；Pydantic 重建无变形
  ⑤ fallback delete_pattern 的 startswith 前缀逻辑
  ⑥ 非 product.py 写入口（库存/订单/域失效）对 product:list:* 的覆盖情况；
     以及新缓存路径**缺少防击穿锁**的事实
  ⑦ B(INVENTORY) 修复后：一域多 pattern 引擎正确性（各域只清自身、不漏不重、不误伤）
  ⑧ 竞态兜底时序：提交前回写脏数据 → 提交 → post-commit 回调清除（消除竞态的属性）

运行环境说明（2026-09-14 实测）：本机 6379 端口有 Redis 服务但**需要密码**，
`redis_cache.init_app()` 连接失败 → `redis_client is None` → 走 fallback 内存缓存。
因此「真实 Redis SCAN 路径」用录制式假客户端验证（仅验证传给 SCAN 的 match 参数与
匹配语义），「真实 Redis 端到端」标记为 skip 并写明原因，不伪装为已验证。
"""
import asyncio
import fnmatch
from unittest.mock import AsyncMock, MagicMock

import pytest

from fastapi_app.api.v1.endpoints import product as product_endpoint
from fastapi_app.core.cache import CacheDomain
from fastapi_app.core.cache_invalidation import InvalidationStrategy, cache_mgr
from fastapi_app.core.cache_keys import (
    PRODUCT_LIST_CACHE_PATTERN,
    PRODUCT_LIST_CACHE_TTL,
    CacheNamespace,
    build_cache_key,
)
from fastapi_app.core.exceptions import db_transaction
from fastapi_app.core.redis_wrapper import safe_delete_pattern, safe_get, safe_set
from fastapi_app.schemas.product import ProductListResponse
from fastapi_app.services import product_service
from utils.redis_cache import RedisCacheManager, redis_cache

# 首页无搜索、端点默认 per_page=20 时使用的键
_KEY_P20 = build_cache_key(CacheNamespace.PRODUCT_LIST, 20)
_KEY_P50 = build_cache_key(CacheNamespace.PRODUCT_LIST, 50)

# 一份"完整"的商品 dict（与 Product.to_dict() 字段一致），用于结构一致性断言
_FULL_ITEM = {
    'id': 1,
    'name': 'A',
    'barcode': '6901234567890',
    'price': 12.5,
    'image': '/img/a.png',
    'factory': '东莞',
    'initial_stock': 3,
    'current_stock': 5,
    'create_time': '2026-01-01 00:00:00',
    'customers': [],
}

# 签发把 image 变成带 ?st=<到期秒>&s=<摘要> 的限时 URL（OPT-19）。st 取自 time.time()，
# 跨秒边界就变，会让「命中与未命中逐字节一致」变成偶发失败。冻结签名模块内的时钟，
# 使这些结构一致性断言可确定；签名本身的正确性由 test_signed_urls.py 覆盖。
_FROZEN_TS = 1_800_000_000


@pytest.fixture
def frozen_signing(monkeypatch):
    """冻结 signed_urls 内部时钟（只替换该模块的 time 名，不动全局 time 模块）。"""
    import types

    from fastapi_app.services import signed_urls

    monkeypatch.setattr(signed_urls, 'time', types.SimpleNamespace(time=lambda: _FROZEN_TS))
    return signed_urls


def _expected_item(signed_urls):
    """_FULL_ITEM 经出站签发后的期望形态（需在 frozen_signing 生效下调用）。"""
    return {**_FULL_ITEM, 'image': signed_urls.sign_upload_url(_FULL_ITEM['image'])}


@pytest.fixture
def real_fallback_cache(monkeypatch):
    """把全局 redis_cache 强制为本环境真实运行路径：fallback 内存缓存。

    - `redis_client = None`：本机 Redis 需密码，init_app 已降级，这里显式固化
    - `key_prefix = 'erp:'`：与 init_app() 默认值一致（权威前缀）
    - 前后清空内存态，保证用例独立
    """
    monkeypatch.setattr(redis_cache, 'redis_client', None)
    monkeypatch.setattr(redis_cache, 'key_prefix', 'erp:')
    redis_cache._fallback_cache.clear()
    redis_cache._fallback_timestamps.clear()
    yield redis_cache
    redis_cache._fallback_cache.clear()
    redis_cache._fallback_timestamps.clear()


def _redis_available() -> bool:
    try:
        return redis_cache.redis_client is not None
    except Exception:  # 环境探测
        return False


# ---------------------------------------------------------------------------
# ① 物理层：写入键 与 失效模式 必须真实匹配（本改动最容易静默失效的坑）
# ---------------------------------------------------------------------------
class TestPhysicalKeyPatternMatch:
    def test_physical_key_and_pattern_are_single_prefix(self):
        """固化物理键名与物理模式，防止双前缀回归（erp:erp:...）"""
        mgr = RedisCacheManager()
        assert _KEY_P20 == 'erp:product:list:20'
        assert PRODUCT_LIST_CACHE_PATTERN == 'erp:product:list:*'
        # _make_key 幂等：已带 erp: 前缀的键/模式原样返回
        assert mgr._make_key(_KEY_P20) == 'erp:product:list:20'
        assert mgr._make_key(PRODUCT_LIST_CACHE_PATTERN) == 'erp:product:list:*'
        assert not PRODUCT_LIST_CACHE_PATTERN.startswith('erp:erp:')

    async def test_end_to_end_write_then_pattern_delete_fallback(self, real_fallback_cache):
        """端到端（fallback 真实路径）：safe_set 写入 → safe_get 命中 →
        safe_delete_pattern(PATTERN) → safe_get 变 None，且物理键确实被删。"""
        await safe_set(_KEY_P20, {'items': [_FULL_ITEM], 'total': 1}, timeout=60)
        # 写入的物理键名（fallback 缓存以物理键为 dict key）
        assert 'erp:product:list:20' in redis_cache._fallback_cache
        assert await safe_get(_KEY_P20) is not None

        deleted = await safe_delete_pattern(PRODUCT_LIST_CACHE_PATTERN)
        assert deleted >= 1, '模式删除应至少命中写入的键'
        assert await safe_get(_KEY_P20) is None
        assert 'erp:product:list:20' not in redis_cache._fallback_cache

    async def test_pattern_deletes_only_product_list_namespace(self, real_fallback_cache):
        """模式只能命中 product:list:*，不得误删 product:detail:* / products:*"""
        await safe_set(_KEY_P20, {'items': [], 'total': 0}, timeout=60)
        await safe_set(_KEY_P50, {'items': [], 'total': 0}, timeout=60)
        await safe_set(build_cache_key(CacheNamespace.PRODUCT_DETAIL, 1), {'id': 1}, timeout=60)
        await safe_set('products:all:limit5000', [{'id': 1}], timeout=60)

        await safe_delete_pattern(PRODUCT_LIST_CACHE_PATTERN)

        assert await safe_get(_KEY_P20) is None
        assert await safe_get(_KEY_P50) is None
        assert await safe_get(build_cache_key(CacheNamespace.PRODUCT_DETAIL, 1)) is not None
        assert await safe_get('products:all:limit5000') is not None

    async def test_redis_branch_passes_single_prefix_match_to_scan(self):
        """Redis SCAN 分支：delete_pattern 传给 scan(match=...) 的物理模式必须是
        单前缀 'erp:product:list:*'（本机无真实 Redis，用录制式假客户端验证参数与语义）。"""
        mgr = RedisCacheManager()

        class _RecordingRedis:
            def __init__(self, keys):
                self.keys = list(keys)
                self.scan_matches = []
                self.unlinked = []

            async def scan(self, cursor=0, match=None, count=100):
                self.scan_matches.append(match)
                hit = [k for k in self.keys if fnmatch.fnmatch(k, match)]
                return 0, hit

            async def unlink(self, *keys):
                for k in keys:
                    if k in self.keys:
                        self.keys.remove(k)
                self.unlinked.extend(keys)
                return len(keys)

        fake = _RecordingRedis([
            'erp:product:list:20',
            'erp:product:list:50',
            'erp:product:detail:1',
            'erp:products:all',
        ])
        mgr.redis_client = fake

        deleted = await mgr.delete_pattern(PRODUCT_LIST_CACHE_PATTERN)

        assert fake.scan_matches == ['erp:product:list:*'], '传给 SCAN 的 match 必须是单前缀模式'
        assert deleted == 2
        assert 'erp:product:list:20' not in fake.keys
        assert 'erp:product:list:50' not in fake.keys
        assert 'erp:product:detail:1' in fake.keys
        assert 'erp:products:all' in fake.keys

    @pytest.mark.skipif(not _redis_available(), reason=(
        '本机 Redis 需密码，redis_cache 降级为内存缓存；未验证真实 Redis 的 SCAN+UNLINK 端到端'
    ))
    async def test_real_redis_end_to_end(self):
        """真实 Redis 端到端（Redis 可用时才执行）。"""
        key = build_cache_key(CacheNamespace.PRODUCT_LIST, 20)
        await safe_set(key, {'items': [], 'total': 0}, timeout=60)
        assert await safe_get(key) is not None
        await safe_delete_pattern(PRODUCT_LIST_CACHE_PATTERN)
        assert await safe_get(key) is None


# ---------------------------------------------------------------------------
# ⑤ fallback delete_pattern 的 startswith 前缀逻辑（utils/redis_cache.py:206-212）
# ---------------------------------------------------------------------------
class TestFallbackDeletePatternPrefix:
    async def test_prefix_is_full_pattern_without_star(self):
        """full_pattern.replace('*','') == 'erp:product:list:' 必须是写入键的前缀"""
        mgr = RedisCacheManager()
        mgr.redis_client = None
        mgr._fallback_cache = {
            'erp:product:list:20': 1,
            'erp:product:list:50': 2,
            'erp:product:detail:1': 3,
            'erp:products:all': 4,
        }
        mgr._fallback_timestamps = dict.fromkeys(mgr._fallback_cache, 0.0)

        deleted = await mgr.delete_pattern(PRODUCT_LIST_CACHE_PATTERN)

        assert deleted == 2
        assert 'erp:product:list:20' not in mgr._fallback_cache
        assert 'erp:product:list:50' not in mgr._fallback_cache
        assert 'erp:product:detail:1' in mgr._fallback_cache
        assert 'erp:products:all' in mgr._fallback_cache


# ---------------------------------------------------------------------------
# ② 缓存条件边界（用真实 fallback 缓存驱动端点 helper，不 monkeypatch 缓存层）
# ---------------------------------------------------------------------------
class TestCacheConditionBoundaries:
    async def test_first_page_no_search_writes_and_hits(self, real_fallback_cache, frozen_signing):
        await product_endpoint._set_cached_product_page(1, 20, '', [_FULL_ITEM], 1)
        hit = await product_endpoint._get_cached_product_page(1, 20, '')
        assert hit is not None
        assert hit.total == 1
        # 缓存存裸 dict；命中时重建 ProductListResponse，image 经出站签发
        assert [i.model_dump() for i in hit.items] == [_expected_item(frozen_signing)]

    async def test_per_page_buckets_are_isolated(self, real_fallback_cache):
        """per_page 不同必须落到不同键，绝不能串数据（最易出的 bug）"""
        await product_endpoint._set_cached_product_page(1, 20, '', [_FULL_ITEM], 1)
        await product_endpoint._set_cached_product_page(1, 50, '', [_FULL_ITEM, {**_FULL_ITEM, 'id': 2}], 2)

        r20 = await product_endpoint._get_cached_product_page(1, 20, '')
        r50 = await product_endpoint._get_cached_product_page(1, 50, '')
        assert r20.total == 1 and len(r20.items) == 1
        assert r50.total == 2 and len(r50.items) == 2
        assert 'erp:product:list:20' in redis_cache._fallback_cache
        assert 'erp:product:list:50' in redis_cache._fallback_cache

    async def test_page2_writes_nothing(self, real_fallback_cache):
        await product_endpoint._set_cached_product_page(2, 20, '', [_FULL_ITEM], 1)
        assert redis_cache._fallback_cache == {}, 'page!=1 不得写缓存'
        assert await product_endpoint._get_cached_product_page(2, 20, '') is None

    async def test_search_writes_nothing(self, real_fallback_cache):
        await product_endpoint._set_cached_product_page(1, 20, 'abc', [_FULL_ITEM], 1)
        assert redis_cache._fallback_cache == {}, '带搜索不得写缓存'
        assert await product_endpoint._get_cached_product_page(1, 20, 'abc') is None

    async def test_search_none_behaves_like_empty(self, real_fallback_cache):
        """search=None 为假值，与 '' 同路（会走缓存）。端点签名为 str、HTTP 不会传 None，
        故非缺陷；此处固化行为，避免将来误判。"""
        await product_endpoint._set_cached_product_page(1, 20, None, [_FULL_ITEM], 1)
        assert await product_endpoint._get_cached_product_page(1, 20, None) is not None

    def test_ttl_constant(self):
        assert PRODUCT_LIST_CACHE_TTL == 60

    async def test_endpoint_writes_with_ttl_60(self, monkeypatch):
        """端点写缓存时 TTL 必须等于 PRODUCT_LIST_CACHE_TTL"""
        calls = []

        async def fake_set(key, value, timeout=300, context=''):
            calls.append((key, timeout))
            return True

        monkeypatch.setattr(product_endpoint, 'safe_set', fake_set)
        await product_endpoint._set_cached_product_page(1, 20, '', [], 0)
        assert calls == [('erp:product:list:20', 60)]


# ---------------------------------------------------------------------------
# ④ 响应结构一致性（缓存命中 vs 未命中；Pydantic 重建）
# ---------------------------------------------------------------------------
class TestResponseStructureConsistency:
    async def test_cached_and_miss_responses_are_identical(self, client, real_fallback_cache,
                                                            monkeypatch, frozen_signing):
        """真实缓存层下：二次请求命中缓存，响应 JSON 与首次（回源）逐字节一致"""
        db_calls = []

        async def fake_page(db, page=1, per_page=20, search='', **_kwargs):
            db_calls.append((page, per_page, search))
            return {'items': [_FULL_ITEM], 'total': 1, 'page': page, 'per_page': per_page}

        monkeypatch.setattr(product_service, 'get_products_page', fake_page)

        miss = await client.get('/api/v1/products/list')
        hit = await client.get('/api/v1/products/list')

        assert miss.status_code == 200 and hit.status_code == 200
        assert miss.json() == hit.json(), '命中与未命中的响应必须完全一致'
        assert len(db_calls) == 1, '第二次应命中缓存不再回源'
        body = hit.json()
        assert body['success'] is True
        assert body['total'] == 1 and isinstance(body['total'], int)
        # 除 image 经出站签发外，其余字段与值都不得变形
        expected = _expected_item(frozen_signing)
        assert body['items'] == [expected]
        assert {k: v for k, v in body['items'][0].items() if k != 'image'} == \
            {k: v for k, v in _FULL_ITEM.items() if k != 'image'}
        # 缓存键确实以单前缀写入
        assert any(k.startswith('erp:product:list:') for k in redis_cache._fallback_cache)

    def test_product_list_response_rebuilds_from_cached_dicts(self, frozen_signing):
        """从缓存 dict 重建 ProductListResponse：字段零变形，total 保持 int，image 经签发"""
        cached = {'items': [_FULL_ITEM], 'total': 1}
        resp = ProductListResponse(items=cached['items'], total=cached['total'])
        dumped = resp.model_dump()
        assert len(dumped['items']) == 1
        rebuilt = dumped['items'][0]
        assert {k: v for k, v in rebuilt.items() if k != 'image'} == \
            {k: v for k, v in _FULL_ITEM.items() if k != 'image'}
        assert rebuilt['image'] == frozen_signing.sign_upload_url(_FULL_ITEM['image'])
        assert dumped['total'] == 1 and isinstance(dumped['total'], int)
        assert dumped['success'] is True
        # 缓存里那份原始 dict 不得被改动（签发只发生在序列化期）
        assert cached['items'][0]['image'] == '/img/a.png'


# ---------------------------------------------------------------------------
# ③ 写后一致性：真实清空 + 时序（竞态窗口）
# ---------------------------------------------------------------------------
class TestWriteInvalidationEndToEnd:
    async def test_create_product_clears_real_cache(self, real_fallback_cache, mock_db):
        await safe_set(_KEY_P20, {'items': [{'id': 999}], 'total': 1}, timeout=60)
        assert await safe_get(_KEY_P20) is not None

        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=result)

        async with db_transaction(mock_db):
            await product_service.create_product(
                mock_db, name='QA-新增', barcode=None, image=None, initial_stock=0,
            )
        # 失效现为 post-commit 回调：退出 db_transaction（已 commit）后才生效
        assert await safe_get(_KEY_P20) is None, 'create 提交后 product:list:* 必须被清'

    async def test_create_cache_cleared_after_commit_and_callback_executes(
        self, real_fallback_cache, mock_db, monkeypatch,
    ):
        """B(INVENTORY) 后：product 写路径**提交前**经 INVENTORY 域清一次（广覆盖），
        post-commit 回调再于**提交后**清一次（竞态兜底）。

        关键：消除竞态的属性是「**提交后必定已清**」，而非「提交前必然未清」。
        提交前也清（INVENTORY 域广覆盖）不削弱竞态防护——回调在提交后执行，能清掉
        并发读在提交前回写的脏数据。故本用例验证：提交后已清 + 回调确实注册且**晚于** commit 执行。
        """
        await safe_set(_KEY_P20, {'items': [], 'total': 0}, timeout=60)

        events: list = []
        real_sdp = product_service.safe_delete_pattern

        async def spy_sdp(pattern, context=''):
            events.append(('callback', pattern))
            return await real_sdp(pattern, context=context)

        monkeypatch.setattr(product_service, 'safe_delete_pattern', spy_sdp)
        mock_db.commit = AsyncMock(side_effect=lambda *a, **k: events.append(('commit', None)))

        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=result)

        async with db_transaction(mock_db):
            await product_service.create_product(
                mock_db, name='QA-兜底', barcode=None, image=None, initial_stock=0,
            )

        assert await safe_get(_KEY_P20) is None, '提交后 product:list:* 必定已清'
        kinds = [e[0] for e in events]
        assert kinds == ['commit', 'callback'], (
            f'post-commit 回调必须在 commit 之后执行：{events}'
        )
        assert events[-1][1] == PRODUCT_LIST_CACHE_PATTERN

    async def test_update_product_clears_real_cache(self, real_fallback_cache, mock_db, monkeypatch):
        await safe_set(_KEY_P20, {'items': [{'id': 999}], 'total': 1}, timeout=60)

        product = MagicMock()
        product.id = 1
        product.name = '旧名'
        product.to_dict.return_value = {'id': 1, 'name': '旧名'}
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=result)

        monkeypatch.setattr(
            product_service, 'get_product_for_update',
            AsyncMock(return_value=product),
        )
        async with db_transaction(mock_db):
            await product_service.update_product(
                mock_db, 1, name=None, barcode=None, image=None, initial_stock=None,
            )
        assert await safe_get(_KEY_P20) is None, 'update 提交后 product:list:* 必须被清'

    async def test_delete_product_clears_real_cache(self, real_fallback_cache, mock_db):
        await safe_set(_KEY_P20, {'items': [{'id': 999}], 'total': 1}, timeout=60)

        product = MagicMock()
        product.name = 'QA-删除'
        mock_db.get = AsyncMock(return_value=product)
        count_result = MagicMock()
        count_result.one.return_value = (0, 0, 0)
        mock_db.execute = AsyncMock(side_effect=[count_result, MagicMock()])

        async with db_transaction(mock_db):
            await product_service.delete_product(mock_db, 1)
        assert await safe_get(_KEY_P20) is None, 'delete 提交后 product:list:* 必须被清'

    async def test_invalidation_ordering_relative_to_commit(self, real_fallback_cache, mock_db, monkeypatch):
        """时序验证（#1 修复后）：失效作为 post-commit 回调，**晚于** commit 执行。

        端点形如 `async with db_transaction(db): await product_service.create_product(...)`；
        服务层经 _schedule_post_commit 注册回调，db_transaction 在 commit 成功后执行，
        故原竞态窗口（提交前失效 → 他请求回写旧数据 → 提交后脏数据留存 TTL）已消除。
        """
        order = []
        await safe_set(_KEY_P20, {'items': [], 'total': 0}, timeout=60)

        mock_db.flush = AsyncMock(side_effect=lambda *a, **k: order.append('flush'))
        mock_db.refresh = AsyncMock(side_effect=lambda *a, **k: order.append('refresh'))
        mock_db.commit = AsyncMock(side_effect=lambda *a, **k: order.append('commit'))
        mock_db.rollback = AsyncMock(side_effect=lambda *a, **k: order.append('rollback'))

        real_delete = product_service.safe_delete_pattern

        async def spy_delete(pattern, context=''):
            order.append('invalidate')
            return await real_delete(pattern, context=context)

        monkeypatch.setattr(product_service, 'safe_delete_pattern', spy_delete)

        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=result)

        async with db_transaction(mock_db):
            await product_service.create_product(
                mock_db, name='QA-时序', barcode=None, image=None, initial_stock=0,
            )

        # 修复后：flush/refresh → commit → invalidate（post-commit 回调）
        assert 'invalidate' in order and 'commit' in order, order
        assert order.index('refresh') < order.index('commit'), order
        assert order.index('commit') < order.index('invalidate'), (
            f'失效必须在提交之后（竞态窗口应已消除）：{order}'
        )
        assert order[-1] == 'invalidate', order


# ---------------------------------------------------------------------------
# ⑥ 非 product.py 写入口的失效覆盖 & 防击穿
# ---------------------------------------------------------------------------
class TestCoverageGapsAndStampede:
    async def test_domain_product_pattern_does_not_cover_product_list_key(self, real_fallback_cache):
        """CacheDomain.PRODUCT 映射 'products:*'（复数），与 'product:list:*'（单数）不同层，
        故既有域失效不会顺带清掉新缓存（这正是需要独立 _invalidate_product_list_cache 的原因）。"""
        await safe_set(_KEY_P20, {'items': [], 'total': 0}, timeout=60)
        await cache_mgr.invalidate(InvalidationStrategy.DOMAIN, CacheDomain.PRODUCT)
        assert await safe_get(_KEY_P20) is not None

    async def test_stock_write_path_clears_product_list(self, real_fallback_cache):
        """#2 修复后：invalidate_stock_and_order() 额外下发 'product:list:*'，
        故 stock_in/out/return_service 写路径会清空首屏列表缓存（首屏库存不再陈旧）。"""
        await safe_set(_KEY_P20, {'items': [{'id': 1, 'current_stock': 10}], 'total': 1}, timeout=60)
        await cache_mgr.invalidate_stock_and_order()
        assert await safe_get(_KEY_P20) is None, '库存写路径必须清 product:list:*'

    async def test_order_deduction_domain_route_clears_product_list(self, real_fallback_cache):
        """B(INVENTORY) 修复后：order/deduction.py:248 的
        cache_mgr.invalidate(DOMAIN, ORDER_AND_INVENTORY) 经 INVENTORY 域一并清 product:list:*。
        订单抵扣改 current_stock（deduction.py:131/183）后首屏库存不再陈旧。"""
        await safe_set(_KEY_P20, {'items': [{'id': 1, 'current_stock': 10}], 'total': 1}, timeout=60)
        await cache_mgr.invalidate(InvalidationStrategy.DOMAIN, CacheDomain.ORDER_AND_INVENTORY)
        assert await safe_get(_KEY_P20) is None, 'ORDER_AND_INVENTORY 必须清 product:list:*'

    async def test_new_cache_path_has_no_stampede_protection(self, real_fallback_cache, monkeypatch):
        """新端点缓存使用裸 safe_get/safe_set，**未接** cache_result 的 Lua 防击穿锁：
        冷缓存下 N 个并发首页请求会各查一次 DB（N 次），非 1 次。"""
        db_calls = []

        async def fake_page(db, page=1, per_page=20, search='', **_kwargs):
            db_calls.append(1)
            await asyncio.sleep(0.01)  # 模拟 DB 往返，放大并发窗口
            return {'items': [_FULL_ITEM], 'total': 1, 'page': page, 'per_page': per_page}

        monkeypatch.setattr(product_service, 'get_products_page', fake_page)

        async def one_request():
            cached = await product_endpoint._get_cached_product_page(1, 20, '')
            if cached is not None:
                return
            res = await product_service.get_products_page(None, 1, 20, '')
            await product_endpoint._set_cached_product_page(1, 20, '', res['items'], res['total'])

        await asyncio.gather(*[one_request() for _ in range(20)])

        assert len(db_calls) == 20, (
            f'冷缓存 20 并发实测回源 {len(db_calls)} 次：新路径无防击穿锁（非 1 次）'
        )


# ---------------------------------------------------------------------------
# ⑦ B(INVENTORY) 修复：一域多 pattern 引擎正确性 + 不误伤
# ---------------------------------------------------------------------------
class TestDomainMultiPatternEngine:
    """_DOMAIN_PATTERN_MAP 值元组化后：各域只清各自 pattern，不漏清、不重复清、不误伤。"""

    @pytest.fixture
    def record_patterns(self, real_fallback_cache, monkeypatch):
        """记录 invalidate_related_caches 实际下发的**物理** pattern（不真删）。"""
        issued: list = []

        async def fake_delete_pattern(pattern):
            issued.append(redis_cache._make_key(pattern))  # 还原物理键空间
            return 0

        monkeypatch.setattr(redis_cache, 'delete_pattern', fake_delete_pattern)
        return issued

    async def test_order_domain_issues_only_orders(self, record_patterns):
        await cache_mgr.invalidate(InvalidationStrategy.DOMAIN, CacheDomain.ORDER)
        assert record_patterns == ['erp:orders:*']

    async def test_inventory_domain_issues_inventory_and_product_list(self, record_patterns):
        await cache_mgr.invalidate(InvalidationStrategy.DOMAIN, CacheDomain.INVENTORY)
        assert record_patterns == ['erp:inventory:*', 'erp:product:list:*']

    async def test_order_and_inventory_issues_three_no_dup(self, record_patterns):
        await cache_mgr.invalidate(InvalidationStrategy.DOMAIN, CacheDomain.ORDER_AND_INVENTORY)
        assert record_patterns == ['erp:orders:*', 'erp:inventory:*', 'erp:product:list:*']
        assert len(record_patterns) == len(set(record_patterns)), '不得重复下发同一 pattern'

    async def test_other_domain_unaffected_by_tuple_change(self, record_patterns):
        """CUSTOMER 等域仍只清自身 pattern（元组化未漏清/串清）"""
        await cache_mgr.invalidate(InvalidationStrategy.DOMAIN, CacheDomain.CUSTOMER)
        assert record_patterns == ['erp:customers:*']

    async def test_inventory_domain_clears_product_list_not_others(self, real_fallback_cache):
        """真实删除：INVENTORY 只清 inventory:* 与 product:list:*，不误伤其他命名空间"""
        for k in ('erp:product:list:20', 'erp:inventory:z', 'erp:product:detail:1',
                  'erp:products:all', 'erp:orders:x', 'erp:customers:y'):
            await safe_set(k, {'k': k}, timeout=60)

        await cache_mgr.invalidate(InvalidationStrategy.DOMAIN, CacheDomain.INVENTORY)

        assert await safe_get('erp:product:list:20') is None
        assert await safe_get('erp:inventory:z') is None
        assert await safe_get('erp:product:detail:1') is not None
        assert await safe_get('erp:products:all') is not None
        assert await safe_get('erp:orders:x') is not None
        assert await safe_get('erp:customers:y') is not None

    async def test_order_and_inventory_clears_orders_inventory_product_list(self, real_fallback_cache):
        for k in ('erp:product:list:20', 'erp:orders:x', 'erp:inventory:z',
                  'erp:products:all', 'erp:product:detail:1', 'erp:customers:y'):
            await safe_set(k, {'k': k}, timeout=60)

        await cache_mgr.invalidate(InvalidationStrategy.DOMAIN, CacheDomain.ORDER_AND_INVENTORY)

        assert await safe_get('erp:product:list:20') is None
        assert await safe_get('erp:orders:x') is None
        assert await safe_get('erp:inventory:z') is None
        assert await safe_get('erp:products:all') is not None
        assert await safe_get('erp:product:detail:1') is not None
        assert await safe_get('erp:customers:y') is not None


# ---------------------------------------------------------------------------
# ⑧ 竞态兜底时序证据：提交前回写脏数据 → 提交 → post-commit 回调清除
# ---------------------------------------------------------------------------
class TestRaceFallback:
    async def test_post_commit_callback_clears_dirty_writeback(self, real_fallback_cache, mock_db):
        """构造竞态：并发读在提交前把旧数据回写缓存（脏）→ 提交 → post-commit 回调清除。

        时序：create_product 内 INVENTORY 域先清一次（提交前）→ 提交瞬间发生脏回写
        → db_transaction 提交后执行回调再清一次 → 最终缓存为空（竞态兜底成立）。
        """
        await safe_set(_KEY_P20, {'items': [{'id': 1, 'name': 'old'}], 'total': 1}, timeout=60)

        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=result)

        real_commit = mock_db.commit

        async def commit_with_dirty_writeback(*a, **k):
            # 模拟并发读：提交完成前把「旧数据」回写缓存
            await safe_set(_KEY_P20, {'items': [{'id': 1, 'name': 'STALE'}], 'total': 1}, timeout=60)
            return await real_commit(*a, **k)

        mock_db.commit = AsyncMock(side_effect=commit_with_dirty_writeback)

        async with db_transaction(mock_db):
            await product_service.create_product(
                mock_db, name='QA-竞态', barcode=None, image=None, initial_stock=0,
            )
            # 提交前：INVENTORY 域已清（广覆盖）
            assert await safe_get(_KEY_P20) is None, '提交前经 INVENTORY 域应已清'

        # 提交时回写的脏数据，必须被 post-commit 回调清除
        assert await safe_get(_KEY_P20) is None, 'post-commit 回调必须清掉提交前回写的脏数据'
