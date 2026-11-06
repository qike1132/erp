"""客户快捷切换栏（/stock chips）的缓存失效回归。

背景（2026-11-06 生产报障）：08:38:12 批量备货 3 个 23cm 企鹅公仔（客户 MINISO国际）
之后，/stock 表格已经出现该客户的备货行，但顶部「客户快捷切换」里没有 MINISO国际，
点不到筛选。同一份响应的表格行是新的、chips 是旧的。

根因：chips 成员来自 ``stock_inventory_service._get_all_customers``（缓存
key_prefix='customers:all'，Redis 120s / L1 60s）。批量入库走
``auxiliary_service.orchestrate_batch_stockins``，它只失效
ORDER_AND_INVENTORY | STOCKIN | REPORT —— ``customers:*`` 一次都没清
（生产日志 2026-11-06 08:38:12 的失效清单可证：orders:*/inventory:*/stockins:*/reports:*
有，customers:* 无）。表格的 ``inventory:*`` 被清了所以是新数据，chips 留到 TTL 到期。

本组用例锁死两条不变量：
  1) INVENTORY 域必须连带清 ``customers:*`` —— chips 与库存行来自同一批源表
     （order / stock_in / daily_production_record），凡改库存行就必须重算 chips；
  2) ``_get_all_customers`` 不得启用 L1 进程内缓存 —— 生产 8 worker 且
     CACHE_L1_BROADCAST_ENABLED=false，其他 worker 的 L1 无法被失效，同
     ``test_order_derived_cache_no_l1.py`` 的口径。
"""
import re
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from fastapi_app.core.cache import CacheDomain, invalidate_related_caches
from fastapi_app.core.redis_wrapper import safe_get, safe_set
from utils.redis_cache import redis_cache

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def fallback_cache(monkeypatch):
    """强制走真实 fallback 内存缓存（本机 Redis 需密码，init_app 已降级）。"""
    monkeypatch.setattr(redis_cache, 'redis_client', None)
    monkeypatch.setattr(redis_cache, 'key_prefix', 'erp:')
    redis_cache._fallback_cache.clear()
    redis_cache._fallback_timestamps.clear()
    yield redis_cache
    redis_cache._fallback_cache.clear()
    redis_cache._fallback_timestamps.clear()


async def test_inventory_domain_clears_customer_chip_cache(fallback_cache):
    """INVENTORY 失效必须物理删除 customers:*（否则 chips 与表格不一致）。"""
    await safe_set('erp:customers:all:pidsall-f:', ['MINISO国际'], timeout=60)
    await safe_set('erp:inventory:paginated:x', {'rows': []}, timeout=60)

    await invalidate_related_caches(CacheDomain.INVENTORY)

    assert await safe_get('erp:inventory:paginated:x') is None
    assert await safe_get('erp:customers:all:pidsall-f:') is None, (
        '库存行变了但客户 chips 缓存还在：新客户会在 TTL 内「表格看得见、chips 筛不了」'
    )


async def test_order_and_inventory_domain_clears_customer_chip_cache(fallback_cache):
    """批量入库实际下发的 ORDER_AND_INVENTORY 组合同样要清 chips。"""
    await safe_set('erp:customers:all:pidsall-f:', ['MINISO国际'], timeout=60)

    await invalidate_related_caches(CacheDomain.ORDER_AND_INVENTORY | CacheDomain.STOCKIN | CacheDomain.REPORT)

    assert await safe_get('erp:customers:all:pidsall-f:') is None


async def test_batch_stockin_path_issues_customer_pattern(monkeypatch):
    """走真实编排函数：批量入库 → 失效清单里必须有 customers:*。"""
    from fastapi_app.services import auxiliary_service, stock_service

    async def fake_batch_create(db, data, operator_id=None):
        return {'results': [{'success': True} for _ in data]}

    class _FakeTx:
        async def __aenter__(self):
            return None

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(stock_service, 'batch_create_stockins', fake_batch_create)
    monkeypatch.setattr(auxiliary_service, 'db_transaction', lambda db: _FakeTx())

    issued: list[str] = []

    async def fake_invalidate_cache(pattern):
        issued.append(pattern)
        return 0

    monkeypatch.setattr('fastapi_app.core.cache.invalidate_cache', fake_invalidate_cache)

    await auxiliary_service.orchestrate_batch_stockins(
        AsyncMock(), [{'product_id': 21158, 'customer': 'MINISO国际'}], operator_id=1,
    )

    assert 'customers:*' in issued, (
        f'批量备货后未失效客户 chips 缓存，实际下发: {issued}'
    )
    # 既有失效不得回归
    for legacy in ('orders:*', 'inventory:*', 'stockins:*', 'reports:*'):
        assert legacy in issued


def test_get_all_customers_disables_l1():
    """chips 缓存不得开 L1：多 worker + 广播关闭时 L1 无法跨进程失效。"""
    source = (PROJECT_ROOT / 'fastapi_app/services/stock_inventory_service.py').read_text(encoding='utf-8')
    match = re.search(r'^async def _get_all_customers\(', source, re.MULTILINE)
    assert match, '未找到 _get_all_customers 定义'
    head = source[:match.start()]
    deco_start = head.rfind('@cache_result(')
    assert deco_start != -1, '_get_all_customers 上未找到 @cache_result 装饰器'
    block = head[deco_start:]

    assert "key_prefix=\"customers:all\"" in block or "key_prefix='customers:all'" in block
    ttl = re.search(r'local_ttl\s*=\s*(\d+)', block)
    assert ttl, '_get_all_customers 的 @cache_result 未显式声明 local_ttl'
    assert ttl.group(1) == '0', (
        '生产 8 worker 且 CACHE_L1_BROADCAST_ENABLED=false：开 L1 后其他 worker 会'
        '在 local_ttl 内继续返回旧的客户 chips'
    )
