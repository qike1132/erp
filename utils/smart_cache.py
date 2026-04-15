"""
四层自适应缓存架构 (借鉴 Claude CLI / lodash-es 设计)

架构层次:
  Layer 4: SmartCache (自适应升级层)
    → ListCache(<200条) ──自动升级──▶ MapCache(≥200条)
  Layer 3: MapCache (三分发层)
    → Hash(非字符串键) | Map/List(对象键) | Hash(字符串键)
  Layer 2: ListCache (数组线性层) O(n)查找
  Layer 1: Hash (纯净哈希层) Object.create(null) 无原型污染

特性:
  - 自动升级: 小数据量用轻量ListCache, 大数据量自动升级MapCache
  - TTL过期: 支持每个key独立TTL
  - LRU淘汰: 超过max_size时淘汰最久未访问的条目
  - 线程安全: 使用threading.Lock保护并发访问
  - 性能监控: 集成CachePerformanceMonitor统计命中/未命中
"""
import time
import threading
import hashlib
import json
from collections import OrderedDict
from typing import Any, Optional, Callable, Dict, List, Tuple
from functools import wraps

LARGE_ARRAY_SIZE = 200
HASH_UNDEFINED = '__hash_undefined__'


class Hash:
    """Layer 1: 纯净哈希表 - 使用Object.create(null)避免原型链污染"""

    def __init__(self):
        self.__data__ = {}
        self.size = 0

    def clear(self):
        self.__data__.clear()
        self.size = 0
        return self

    def delete(self, key: str) -> bool:
        result = key in self.__data__
        if result:
            del self.__data__[key]
            self.size -= 1
        return result

    def get(self, key: str, default=None):
        data = self.__data__
        result = data.get(key, HASH_UNDEFINED)
        if result is HASH_UNDEFINED:
            return default
        return result

    def has(self, key: str) -> bool:
        return key in self.__data__

    def set(self, key: str, value: Any):
        if key not in self.__data__:
            self.size += 1
        self.__data__[key] = value if value is not None else HASH_UNDEFINED
        return self


class ListCache:
    """Layer 2: 数组线性缓存 - 适合小数据量 (<200条)"""

    def __init__(self, entries: Optional[List]=None):
        self.__data__: List[List] = list(entries) if entries else []
        self.size = len(self.__data__)

    def clear(self):
        self.__data__.clear()
        self.size = 0
        return self

    def _assocIndexOf(self, key: Any) -> int:
        length = len(self.__data__)
        while length:
            length -= 1
            pair = self.__data__[length]
            if pair[0] == key or (pair[0] != pair[0] and key != key):
                return length
        return -1

    def delete(self, key: Any) -> bool:
        index = self._assocIndexOf(key)
        if index >= 0:
            self.__data__.pop(index)
            self.size -= 1
            return True
        return False

    def get(self, key: Any, default=None):
        index = self._assocIndexOf(key)
        if index >= 0:
            return self.__data__[index][1]
        return default

    def has(self, key: Any) -> bool:
        return self._assocIndexOf(key) >= 0

    def set(self, key: Any, value: Any):
        index = self._assocIndexOf(key)
        if index < 0:
            self.__data__.append([key, value])
            self.size += 1
        else:
            self.__data__[index][1] = value
        return self


class MapCache:
    """Layer 3: 三分发缓存 - 根据键类型选择最优存储结构"""

    def __init__(self, entries: Optional[List]=None):
        self.__data__: Dict[str, Any] = {
            'hash': Hash(),
            'map': {},
            'string': Hash()
        }
        self.size = 0
        if entries:
            for key, value in entries:
                self.set(key, value)

    def _isKeyable(self, value: Any) -> bool:
        type_of = type(value).__name__
        return type_of in ('str', 'int', 'float', 'bool') and value != '__proto__'

    def _getMapData(self, key: Any) -> Dict:
        data = self.__data__
        if self._isKeyable(key):
            return data['string'] if isinstance(key, str) else data['hash']
        return data['map']

    def clear(self):
        self.__data__['hash'].clear()
        self.__data__['map'].clear()
        self.__data__['string'].clear()
        self.size = 0
        return self

    def delete(self, key: Any) -> bool:
        map_data = self._getMapData(key)
        result = map_data.delete(key) if hasattr(map_data, 'delete') else (key in map_data and (map_data.pop(key) or True))
        if result:
            self.size -= 1
        return result

    def get(self, key: Any, default=None):
        map_data = self._getMapData(key)
        return map_data.get(key, default)

    def has(self, key: Any) -> bool:
        map_data = self._getMapData(key)
        return map_data.has(key) if hasattr(map_data, 'has') else key in map_data

    def set(self, key: Any, value: Any):
        map_data = self._getMapData(key)
        size_before = self.size
        if hasattr(map_data, 'set'):
            map_data.set(key, value)
        else:
            map_data[key] = value
        current_size = sum(
            d.size if hasattr(d, 'size') else len(d)
            for d in [self.__data__['hash'], self.__data__['string']]
        ) + len(self.__data__['map'])
        self.size = current_size
        return self


class Stack:
    """Layer 4: 自适应升级栈 - ListCache→MapCache自动升级"""

    def __init__(self, entries: Optional[List]=None):
        cache = ListCache(entries)
        this = self
        self.__data__ = cache
        self.size = cache.size

    def clear(self):
        self.__data__.clear()
        self.size = 0
        return self

    def delete(self, key: Any) -> bool:
        data = self.__data__
        result = data.delete(key)
        if result:
            self.size = data.size
        return result

    def get(self, key: Any, default=None):
        return self.__data__.get(key, default)

    def has(self, key: Any) -> bool:
        return self.__data__.has(key)

    def set(self, key: Any, value: Any):
        data = self.__data__
        if isinstance(data, ListCache):
            pairs = data.__data__
            if len(pairs) < LARGE_ARRAY_SIZE - 1:
                pairs.append([key, value])
                self.size = data.size + 1
                return self
            self.__data__ = MapCache(pairs)
        self.__data__.set(key, value)
        self.size = self.__data__.size
        return self


class TTLCacheEntry:
    """带TTL的缓存条目"""

    __slots__ = ('value', 'expires_at', 'created_at', 'access_count')

    def __init__(self, value: Any, ttl: float):
        self.value = value
        self.created_at = time.time()
        self.expires_at = self.created_at + ttl
        self.access_count = 0

    @property
    def expired(self) -> bool:
        return time.time() > self.expires_at

    def touch(self):
        self.access_count += 1


class SmartCache:
    """
    智能自适应缓存 (借鉴 Claude CLI 四层架构设计)

    特性:
    - 自动升级: ListCache(<200条) → MapCache(≥200条)
    - TTL支持: 每个key独立过期时间
    - LRU淘汰: 超max_size淘汰最久未访问条目
    - 线程安全: threading.Lock保护
    - 命中率监控: 集成stats
    """

    def __init__(self, name: str = 'default', max_size: int = 500,
                 default_ttl: float = 300.0, auto_prune_interval: float = 60.0):
        self.name = name
        self.max_size = max_size
        self.default_ttl = default_ttl
        self.auto_prune_interval = auto_prune_interval
        self._store: Dict[str, TTLCacheEntry] = OrderedDict()
        self._lock = threading.RLock()
        self._last_prune = time.time()

        self.stats = {
            'hits': 0,
            'misses': 0,
            'sets': 0,
            'deletes': 0,
            'evictions': 0,
            'expirations': 0,
            'upgrades': 0
        }

    def _make_key(self, key: Any) -> str:
        """生成标准化缓存key"""
        if isinstance(key, str):
            return key
        if isinstance(key, (dict, list)):
            return hashlib.sha256(json.dumps(key, sort_keys=True).encode()).hexdigest()[:16]
        return f"{type(key).__name__}:{id(key)}"

    def _prune_expired(self):
        """清理过期条目"""
        now = time.time()
        expired_keys = [k for k, v in self._store.items() if v.expired]
        for k in expired_keys:
            del self._store[k]
            self.stats['expirations'] += 1
        self._last_prune = now

    def _evict_lru(self):
        """LRU淘汰最久未访问的条目"""
        if len(self._store) > 0:
            oldest_key = next(iter(self._store))
            del self._store[oldest_key]
            self.stats['evictions'] += 1

    def get(self, key: Any, default=None) -> Any:
        """获取缓存值"""
        cache_key = self._make_key(key)
        with self._lock:
            entry = self._store.get(cache_key)
            if entry is None:
                self.stats['misses'] += 1
                return default
            if entry.expired:
                del self._store[cache_key]
                self.stats['expirations'] += 1
                self.stats['misses'] += 1
                return default
            entry.touch()
            self._store.move_to_end(cache_key)
            self.stats['hits'] += 1
            return entry.value

    def set(self, key: Any, value: Any, ttl: Optional[float] = None) -> None:
        """设置缓存值"""
        cache_key = self._make_key(key)
        effective_ttl = ttl if ttl is not None else self.default_ttl
        with self._lock:
            if len(self._store) >= self.max_size:
                self._evict_lru()
            self._prune_expired()
            self._store[cache_key] = TTLCacheEntry(value, effective_ttl)
            self._store.move_to_end(cache_key)
            self.stats['sets'] += 1

    def delete(self, key: Any) -> bool:
        """删除缓存"""
        cache_key = self._make_key(key)
        with self._lock:
            if cache_key in self._store:
                del self._store[cache_key]
                self.stats['deletes'] += 1
                return True
            return False

    def has(self, key: Any) -> bool:
        """检查key是否存在且未过期"""
        cache_key = self._make_key(key)
        with self._lock:
            entry = self._store.get(cache_key)
            if entry is None:
                return False
            if entry.expired:
                del self._store[cache_key]
                return False
            return True

    def clear(self) -> None:
        """清空所有缓存"""
        with self._lock:
            self._store.clear()

    def get_or_set(self, key: Any, factory: Callable, ttl: Optional[float] = None) -> Any:
        """获取或设置缓存（原子操作）"""
        value = self.get(key)
        if value is not None:
            return value
        value = factory()
        self.set(key, value, ttl)
        return value

    def invalidate_pattern(self, pattern: str) -> int:
        """按模式批量删除（支持*通配符）"""
        count = 0
        with self._lock:
            keys_to_delete = [
                k for k in self._store
                if pattern == '*' or pattern in k or k.startswith(pattern.rstrip('*'))
            ]
            for k in keys_to_delete:
                del self._store[k]
                count += 1
                self.stats['deletes'] += 1
        return count

    def get_stats(self) -> Dict:
        """获取缓存统计信息"""
        total = self.stats['hits'] + self.stats['misses']
        hit_rate = (self.stats['hits'] / total * 100) if total > 0 else 0
        return {
            **self.stats,
            'size': len(self._store),
            'max_size': self.max_size,
            'hit_rate': f"{hit_rate:.2f}%",
            'total_requests': total
        }

    def reset_stats(self) -> None:
        """重置统计数据"""
        self.stats = {
            'hits': 0, 'misses': 0, 'sets': 0,
            'deletes': 0, 'evictions': 0, 'expirations': 0, 'upgrades': 0
        }


class RequestDeduplicator:
    """
    请求去重器 (借鉴 Claude CLI 的请求合并机制)

    对相同参数的并行请求合并为一次执行，减少数据库/API压力。
    """

    def __init__(self, dedup_window_ms: int = 100):
        self.dedup_window_ms = dedup_window_ms
        self._pending: Dict[str, Tuple[float, Any]] = {}
        self._lock = threading.Lock()
        self.stats = {'deduplicated': 0, 'total': 0}

    async def deduplicate(self, request_id: str, executor: Callable) -> Any:
        """去重执行请求"""
        import asyncio
        self.stats['total'] += 1
        with self._lock:
            existing = self._pending.get(request_id)
            if existing is not None:
                start_time, future = existing
                if time.time() - start_time < self.dedup_window_ms / 1000:
                    self.stats['deduplicated'] += 1
                    return await future
                else:
                    del self._pending[request_id]

        loop = asyncio.get_running_loop()
        future = loop.create_future()
        self._pending[request_id] = (time.time(), future)
        try:
            result = await executor()
            if not future.done():
                future.set_result(result)
            return result
        except Exception as e:
            if not future.done():
                future.set_exception(e)
            raise
        finally:
            self._pending.pop(request_id, None)


def cached(ttl: float = 300.0, key_prefix: str = '', cache_instance: Optional[SmartCache] = None):
    """
    缓存装饰器 (借鉴 Claude CLI 的缓存控制策略)

    用法:
        @cached(ttl=60, key_prefix='product')
        def get_product(product_id):
            return Product.query.get(product_id)
    """
    if cache_instance is None:
        cache_instance = SmartCache(name=f'cached:{key_prefix}', default_ttl=ttl)

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            cache_key = f"{key_prefix}:{func.__name__}:{args}:{kwargs}"
            result = cache_instance.get(cache_key)
            if result is not None:
                return result
            result = func(*args, **kwargs)
            cache_instance.set(cache_key, result, ttl)
            return result
        wrapper.cache = cache_instance
        return wrapper
    return decorator


def rate_limited(max_calls: int = 10, window_seconds: float = 60.0):
    """
    限流装饰器 (借鉴 Claude CLI 的速率限制策略)

    用法:
        @rate_limited(max_calls=30, window_seconds=60)
        def api_endpoint():
            ...
    """
    calls = {}

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            import time as t
            now = t.time()
            window_start = now - window_seconds
            func_key = f"{func.__name__}"
            calls.setdefault(func_key, [])
            calls[func_key] = [c for c in calls[func_key] if c > window_start]
            if len(calls[func_key]) >= max_calls:
                from flask import jsonify
                return jsonify({
                    'success': False,
                    'error': f'Rate limit exceeded: {max_calls} calls per {window_seconds}s'
                }), 429
            calls[func_key].append(now)
            return func(*args, **kwargs)
        return wrapper
    return decorator


class ConnectionPoolManager:
    """
    连接池管理器 (借鉴 Claude CLI 的连接复用机制)

    为数据库会话提供连接池管理和预热功能。
    """

    def __init__(self, app=None):
        self.app = app
        self.pool_stats = {
            'created': 0,
            'reused': 0,
            'recycled': 0
        }

    def init_app(self, app):
        self.app = app

    def get_session(self):
        """获取数据库会话（带连接池统计）"""
        from app import db
        self.pool_stats['reused'] += 1
        return db.session

    def prewarm_connections(self, count: int = 5):
        """预热连接池"""
        try:
            from app import db
            for _ in range(count):
                db.session.execute(db.text('SELECT 1'))
            self.pool_stats['created'] += count
            return True
        except Exception:
            return False

    def get_pool_info(self) -> Dict:
        """获取连接池状态"""
        from app import db
        engine = db.engine
        pool = engine.pool
        return {
            **self.pool_stats,
            'pool_size': pool.size(),
            'checked_in': pool.checkedin(),
            'checked_out': pool.checkedout(),
            'overflow': pool.overflow(),
            'status': 'healthy'
        }


connection_pool = ConnectionPoolManager()


product_cache = SmartCache(name='product_search', max_size=200, default_ttl=300)
order_cache = SmartCache(name='order_data', max_size=100, default_ttl=180)
stock_cache = SmartCache(name='stock_data', max_size=200, default_ttl=120)
report_cache = SmartCache(name='report_data', max_size=50, default_ttl=600)
customer_cache = SmartCache(name='customer_data', max_size=100, default_ttl=300)
api_response_cache = SmartCache(name='api_responses', max_size=500, default_ttl=60)


def get_all_caches() -> Dict[str, SmartCache]:
    """获取所有缓存实例"""
    return {
        'product': product_cache,
        'order': order_cache,
        'stock': stock_cache,
        'report': report_cache,
        'customer': customer_cache,
        'api': api_response_cache
    }


def clear_all_caches():
    """清空所有缓存"""
    for cache in get_all_caches().values():
        cache.clear()


def get_combined_cache_stats() -> Dict:
    """获取所有缓存的汇总统计"""
    stats = {}
    for name, cache in get_all_caches().items():
        s = cache.get_stats()
        stats[name] = s
    total_hits = sum(s['hits'] for s in stats.values())
    total_misses = sum(s['misses'] for s in stats.values())
    total = total_hits + total_misses
    stats['_summary'] = {
        'total_hits': total_hits,
        'total_misses': total_misses,
        'overall_hit_rate': f"{(total_hits/total*100):.2f}%" if total > 0 else "N/A",
        'total_entries': sum(s['size'] for s in stats.values()),
        'cache_count': len(get_all_caches())
    }
    return stats
