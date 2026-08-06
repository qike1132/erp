"""
统一缓存键生成工具

提供全系统统一的缓存键命名规范，避免不同模块使用不一致的缓存键格式。
所有缓存键均以 `erp:` 为前缀，便于运维时识别和清理。
"""
from __future__ import annotations

import hashlib
from typing import Any

# 全局缓存键前缀，便于识别和批量清理
CACHE_KEY_PREFIX = 'erp'


def build_cache_key(*parts: Any, separator: str = ':') -> str:
    """
    构建标准格式的缓存键

    示例：
        build_cache_key('customer', 'list', 'all', 50)
        -> 'erp:customer:list:all:50'

    Args:
        *parts: 缓存键的各部分，按顺序拼接
        separator: 分隔符，默认 ':'

    Returns:
        标准格式的缓存键字符串
    """
    normalized_parts: list[str] = []
    for part in parts:
        if part is None:
            normalized_parts.append('null')
        elif isinstance(part, bool):
            normalized_parts.append('1' if part else '0')
        else:
            normalized_parts.append(str(part).strip())

    return separator.join([CACHE_KEY_PREFIX, *normalized_parts])


def build_cache_key_hash(*parts: Any, length: int = 16) -> str:
    """
    构建基于哈希的缓存键（适用于参数特别长或需要定长键的场景）

    示例：
        build_cache_key_hash('search', 'very long keyword...')
        -> 'erp:search:hash:a1b2c3d4e5f6g7h8'

    Args:
        *parts: 缓存键的各部分
        length: 哈希截取长度，默认16

    Returns:
        包含哈希的标准格式缓存键
    """
    raw = ':'.join(str(p) for p in parts)
    digest = hashlib.sha256(raw.encode('utf-8')).hexdigest()[:length]
    return f'{CACHE_KEY_PREFIX}:hash:{digest}'


# 常用缓存键命名空间常量
class CacheNamespace:
    """缓存键命名空间常量，避免散落的魔法字符串"""
    CUSTOMER_LIST = 'customer:list'
    CUSTOMER_ACTIVE_NAMES = 'customer:active_names'
    CUSTOMER_DETAIL = 'customer:detail'

    SUPPLIER_LIST = 'supplier:list'
    SUPPLIER_ACTIVE_NAMES = 'supplier:active_names'
    SUPPLIER_DETAIL = 'supplier:detail'

    PRODUCT_LIST = 'product:list'
    PRODUCT_DETAIL = 'product:detail'
    PRODUCT_SEARCH = 'product:search'

    ORDER_LIST = 'order:list'
    ORDER_DETAIL = 'order:detail'

    BACKUP_VALIDATION = 'backup:validation'
    BACKUP_METADATA = 'backup:metadata'
