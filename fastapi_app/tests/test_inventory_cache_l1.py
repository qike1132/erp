"""库存兼容入口的 L1 策略必须与分页版一致（审计 M-15）。"""
import re
from pathlib import Path

SOURCE = Path('fastapi_app/services/stock_inventory_service.py').read_text(encoding='utf-8')


def _decorator_block(func_name: str) -> str:
    match = re.search(rf'^async def {re.escape(func_name)}\(', SOURCE, re.MULTILINE)
    assert match, f'未找到函数定义: {func_name}'
    head = SOURCE[:match.start()]
    deco_start = head.rfind('@cache_result(')
    assert deco_start != -1, f'{func_name} 上未找到 @cache_result 装饰器'
    return head[deco_start:]


def test_get_inventory_disables_l1():
    block = _decorator_block('get_inventory')
    assert "key_prefix='inventory'" in block
    assert re.search(r'local_ttl\s*=\s*0', block), (
        'get_inventory 是 get_inventory_paginated 的兼容入口，必须同口径关闭 L1：'
        '多 worker + L1 广播关闭时，30s local_ttl 会让计划页读到旧结余'
    )


def test_get_inventory_paginated_disables_l1():
    block = _decorator_block('get_inventory_paginated')
    assert re.search(r'local_ttl\s*=\s*0', block)
