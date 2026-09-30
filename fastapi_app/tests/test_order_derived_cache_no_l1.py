"""订单派生列表缓存：L1 必须关闭（跨 worker 失效）防腐检查

背景（2026-09-30）：
  生产为多 worker（UVICORN_WORKERS=4）且 CACHE_L1_BROADCAST_ENABLED=false。
  core.cache.invalidate_cache() 只清**当前 worker** 的 L1，广播关闭时其余 worker
  的 L1 无法失效；core.purchase_cache.invalidate_purchase_caches() 更是只清 L1
  （invalidate_local_cache）不删 L2。订单/备货写入后删掉的是 L2，于是带 L1 的
  订单派生列表会在 local_ttl 内继续返回写入前的旧数据。

  这正是「客户订单删除或改数量后，贝莱订单 / 外包订单 / 采购订单页面不实时更新」
  的根因之一：即使前端已重新取数，落到另一个 worker 上仍会拿到旧列表。

  orders:beile:list / orders:beile:unconfirmed_count 早已按同一理由设 local_ttl=0
  （见 beile.py 注释）。本测试把该不变量推广到其余订单派生列表，防止将来有人为了
  省一次 Redis GET 又把 L1 打开、让页面重新变成「延迟更新」。

维护方式：确需为这些 key 开启 L1 时，先启用 CACHE_L1_BROADCAST_ENABLED（或把失效
改为按版本号/时间戳校验，让 L1 无需广播即可自证失效），并同步更新本清单。
"""
import re
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# (相对路径, 函数名, 缓存 key_prefix)
ORDER_DERIVED_LIST_CACHES = [
    ('fastapi_app/services/order/queries.py', 'get_orders', 'orders:list'),
    ('fastapi_app/services/purchase_order_query.py', 'get_purchase_orders', 'orders'),
    ('fastapi_app/services/purchase_order_query.py', 'get_unprocessed_orders', 'orders:unprocessed'),
    ('fastapi_app/services/order/beile.py', 'get_beile_orders_with_stockins', 'orders:beile:list'),
    ('fastapi_app/services/order/beile.py', 'get_beile_unconfirmed_count', 'orders:beile:unconfirmed_count'),
]


def _decorator_block(source: str, func_name: str) -> str:
    """取出 ``async def <func_name>`` 之前最近的 ``@cache_result(...)`` 装饰器文本。"""
    match = re.search(rf'^async def {re.escape(func_name)}\(', source, re.MULTILINE)
    assert match, f'未找到函数定义: {func_name}'
    head = source[:match.start()]
    deco_start = head.rfind('@cache_result(')
    assert deco_start != -1, f'{func_name} 上未找到 @cache_result 装饰器'
    return head[deco_start:]


@pytest.mark.parametrize(('rel_path', 'func_name', 'prefix'), ORDER_DERIVED_LIST_CACHES)
def test_order_derived_list_cache_disables_l1(rel_path, func_name, prefix):
    source = (PROJECT_ROOT / rel_path).read_text(encoding='utf-8')
    block = _decorator_block(source, func_name)

    assert f"'{prefix}'" in block or f'"{prefix}"' in block, (
        f'{func_name} 的缓存 key_prefix 已变（期望 {prefix}），'
        f'请确认本测试的清单仍然对应该缓存'
    )

    m = re.search(r'local_ttl\s*=\s*(\d+)', block)
    assert m, f'{func_name} 的 @cache_result 未显式声明 local_ttl'
    assert m.group(1) == '0', (
        f'{func_name}（{prefix}）的 local_ttl={m.group(1)}，订单派生列表必须为 0：\n'
        f'生产多 worker 且 CACHE_L1_BROADCAST_ENABLED 关闭时，L1 无法跨 worker 失效，\n'
        f'订单写入后其余 worker 会在该 TTL 内继续返回旧列表，页面表现为「不实时更新」。'
    )
