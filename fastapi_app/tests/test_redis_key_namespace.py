"""Redis key 命名空间防腐检查

背景（P2，2026-09-14）：
  项目里存在两套并存的 Redis key 命名空间：

    路径 A（带 erp: 前缀）：utils.redis_cache.RedisCacheManager / core.redis_wrapper 的 safe_*
        redis_cache.get('orders:list:a')  ->  erp:orders:list:a

    路径 B（无前缀）：core.redis_wrapper.get_client() 取得的裸 client 直连
        裸 client.set('token_blacklist:x') ->  token_blacklist:x

  两套互不可见：裸 client 写进去的 key，走 wrapper 读不到，反之亦然。
  当前所有裸 client 调用点都是"读写同侧"，因此自洽、无功能性 bug；
  但一旦有人新增跨侧读写，就会出现"写入成功却读不到"的静默故障。

本测试的作用：**冻结当前裸 client 调用点清单**。
  今后若新增 `get_client()` 直连，必须显式更新本清单并在 PR 中说明原因，
  从而被迫思考"是否应该改走 wrapper"，而不是无意间引入第三套命名空间。

维护方式：确有正当理由新增裸 client 调用时，把它加入 _ALLOWED_BARE_CLIENT_CALLS
并写明理由。**不要为了让它变绿而盲目追加**——先确认 wrapper 无法满足需求
（如 pub/sub、原生 list 操作等 wrapper 未封装的能力）。
"""
import re
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCAN_DIRS = [PROJECT_ROOT / 'fastapi_app']

# ── 允许使用裸 client 的位置（key 为相对项目根的 POSIX 路径，value 为理由）──
# 冻结于 2026-09-14。新增条目必须附理由。
_ALLOWED_BARE_CLIENT_CALLS: dict[str, str] = {
    'fastapi_app/core/redis_wrapper.py':
        'wrapper 自身的实现层——get_client() 在此定义并被 safe_* 复用，属正常',
    'fastapi_app/core/auth/blacklist.py':
        'token 黑名单用 EXISTS/SET，读写均在本文件内自洽；改走 wrapper 会改变物理 key 位置',
    'fastapi_app/api/v1/endpoints/auth.py':
        '登录限流用 pipeline(incr+expire)，wrapper 未封装 pipeline；读写均在本文件内自洽',
    'fastapi_app/core/backup_progress.py':
        '仅做 PING 探活等连接级操作，不涉及业务 key',
    'fastapi_app/core/domain_events.py':
        'pub/sub 订阅，wrapper 未封装 pubsub；channel 名不是缓存 key',
    'fastapi_app/core/maintenance.py':
        'key 自带 erp: 前缀（erp:maintenance_mode），两套路径恰好解析一致',
    'fastapi_app/api/v1/endpoints/dead_letter.py':
        '读取 arq:dead_letter 死信队列，读写两侧均走 safe_* wrapper',
}

# 允许出现 "裸 client 变量名.set/get/..." 的标识符（用于精准定位直连用法）
_BARE_CLIENT_VARS = ('client', 'redis', '_redis', 'raw', 'r')

_CALL_PATTERN = re.compile(
    r'\b(' + '|'.join(re.escape(v) for v in _BARE_CLIENT_VARS) + r')'
    r'\.(set|get|exists|delete|incr|decr|expire|ttl|lpush|rpush|lrange|llen|lrem|'
    r'hset|hget|hgetall|scan|keys|unlink|eval|publish|pubsub|setex|setnx)\b'
)


def _iter_scanned_files():
    for base in SCAN_DIRS:
        for path in base.rglob('*.py'):
            if '__pycache__' in path.parts:
                continue
            if 'tests' in path.parts:
                continue
            yield path


def _rel(path: Path) -> str:
    return path.relative_to(PROJECT_ROOT).as_posix()


def _files_using_get_client() -> set[str]:
    """找出所有调用了 get_client() 的文件（排除其定义处之外的使用者）"""
    hits: set[str] = set()
    for path in _iter_scanned_files():
        text = path.read_text(encoding='utf-8', errors='ignore')
        if 'get_client()' not in text:
            continue
        rel = _rel(path)
        # redis_wrapper 是定义处，单独白名单覆盖
        if rel == 'fastapi_app/core/redis_wrapper.py':
            hits.add(rel)
            continue
        hits.add(rel)
    return hits


class TestBareClientCallSitesFrozen:
    """冻结裸 client 调用点，防止无意间引入第三套 key 命名空间"""

    def test_no_unexpected_get_client_usage(self):
        """任何使用 get_client() 的文件都必须在白名单内"""
        actual = _files_using_get_client()
        allowed = set(_ALLOWED_BARE_CLIENT_CALLS)
        unexpected = actual - allowed

        assert not unexpected, (
            '发现未登记的 get_client() 直连用法：\n'
            + '\n'.join(f'  - {p}' for p in sorted(unexpected))
            + '\n\n裸 client 绕过 RedisCacheManager._make_key()，其 key 不带 erp: 前缀，\n'
            '与走 wrapper 的缓存互不可见。若确有必要（如 pub/sub、pipeline），\n'
            '请在 fastapi_app/tests/test_redis_key_namespace.py 的\n'
            '_ALLOWED_BARE_CLIENT_CALLS 中登记并写明理由；否则请改用\n'
            'core/redis_wrapper 的 safe_get/safe_set/safe_delete 等封装。'
        )

    def test_allowlist_has_no_stale_entries(self):
        """白名单不应残留已不再使用 get_client() 的文件（防止清单腐烂）"""
        actual = _files_using_get_client()
        stale = set(_ALLOWED_BARE_CLIENT_CALLS) - actual

        assert not stale, (
            '白名单中存在已不再调用 get_client() 的条目，请清理：\n'
            + '\n'.join(f'  - {p}' for p in sorted(stale))
        )

    def test_allowlist_entries_have_reasons(self):
        """每条白名单都必须写明理由"""
        empty = [p for p, reason in _ALLOWED_BARE_CLIENT_CALLS.items() if not reason.strip()]
        assert not empty, f'以下白名单条目缺少理由：{empty}'


class TestNamespaceContract:
    """锁定 _make_key 的前缀契约（两套路径的解析差异是**已知事实**，不是 bug）"""

    def test_make_key_adds_prefix(self):
        from utils.redis_cache import RedisCacheManager

        mgr = RedisCacheManager()
        assert mgr._make_key('orders:list:a') == 'erp:orders:list:a'

    def test_make_key_is_idempotent_for_prefixed_key(self):
        """已带前缀的 key 不会二次加前缀（防双前缀）"""
        from utils.redis_cache import RedisCacheManager

        mgr = RedisCacheManager()
        assert mgr._make_key('erp:orders:list:a') == 'erp:orders:list:a'

    def test_bare_and_wrapper_paths_diverge_for_unprefixed_key(self):
        """固化『两套路径对无前缀 key 解析不同』这一事实，防止有人误以为它们等价

        这是 P2 的核心风险点：token_blacklist:x 在裸路径下是
        'token_blacklist:x'，在 wrapper 路径下是 'erp:token_blacklist:x'。
        """
        from utils.redis_cache import RedisCacheManager

        mgr = RedisCacheManager()
        logical_key = 'token_blacklist:abc123'
        bare_physical = logical_key                      # 裸 client 不加前缀
        wrapper_physical = mgr._make_key(logical_key)     # wrapper 加前缀

        assert bare_physical != wrapper_physical, (
            '若两者相等，说明前缀策略已变更——请同步更新 P2 的结论与文档'
        )
        assert wrapper_physical == 'erp:token_blacklist:abc123'

    def test_hostname_does_not_affect_prefix(self, monkeypatch):
        """HOSTNAME 不再影响 key_prefix（P2 清理的死代码回归防护）"""
        import importlib

        import utils.redis_cache as rc_mod

        monkeypatch.setenv('HOSTNAME', 'SOME_RANDOM_HOST_XYZ')
        importlib.reload(rc_mod)
        try:
            mgr = rc_mod.RedisCacheManager()
            assert 'SOME_RANDOM_HOST_XYZ' not in mgr.key_prefix, (
                'key_prefix 不得包含 HOSTNAME——否则改主机名会导致全量缓存失效'
            )
            assert mgr.key_prefix == 'erp:'
        finally:
            # 还原模块，避免污染其他测试
            monkeypatch.delenv('HOSTNAME', raising=False)
            importlib.reload(rc_mod)


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
