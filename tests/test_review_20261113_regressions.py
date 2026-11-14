"""2026-11-13 全量审查修复的回归钉子（B1 / H3 / M4 / M6 / H1）。

这几条的共同点是「不报错但结果错」，只靠人眼回归会漏：

- B1  JSON 备份里导出失败的表被当成空表恢复 —— 先 DELETE 再插 0 行，
      行数校验 0==0 通过，一次临时读失败就等于合法清空整表。
- H3  多 SKU 订单的出货汇总取 ``Order.quantity``（首 SKU 兼容值）而非本 SKU
      数量，B 料少报出货、可用量虚高。
- M4  非法日期筛选被 ``except ValueError: pass`` 吞掉，返回 200 + 整表数据，
      导出/对账的人以为筛选生效。
- M6  Redis 删除失败后 GET 仍命中旧值：缓存永不失效，比不缓存更危险。
- H1  恢复锁续期失败只打 warning，锁 TTL 到期后第二个还原能拿到同一把锁，
      两个任务交替 DROP/导入。

变异检查：把对应实现改回旧行为，本文件的用例必须变红。
"""
from __future__ import annotations

import asyncio
import fnmatch
from types import SimpleNamespace

import pytest

from fastapi_app.services.backup.exceptions import RestoreError
from fastapi_app.services.backup.json_backup import _validate_json_backup_payload
from fastapi_app.services.stock_inventory_service import _validated_day_range
from fastapi_app.shared.shipment_calc import build_shipment_summary
from server_manager.nssm_verify import nssm_param_problems


def _order(oid: int, qty: int) -> SimpleNamespace:
    return SimpleNamespace(id=oid, order_no=f'NO{oid}', quantity=qty)


# ---------------------------------------------------------------------------
# B1：导出失败的表绝不能被当成「空表」恢复
# ---------------------------------------------------------------------------

def test_b1_rejects_table_with_export_error():
    payload = {'tables': {'orders': {'error': 'read timeout', 'count': 0, 'rows': []}}}
    with pytest.raises(RestoreError, match='orders'):
        _validate_json_backup_payload(payload)


def test_b1_rejects_declared_failed_tables():
    payload = {
        'tables': {'orders': {'columns': ['id'], 'rows': [[1]]}},
        'failed_tables': ['order_items'],
    }
    with pytest.raises(RestoreError, match='failed_tables'):
        _validate_json_backup_payload(payload)


def test_b1_rejects_incomplete_coverage():
    payload = {
        'tables': {'orders': {'columns': ['id'], 'rows': [[1]]}},
        'failed_tables': [],
        'coverage': {'complete': False},
    }
    with pytest.raises(RestoreError, match='coverage'):
        _validate_json_backup_payload(payload)


def test_b1_rejects_empty_tables():
    with pytest.raises(RestoreError, match='不含任何表数据'):
        _validate_json_backup_payload({'tables': {}})


def test_b1_rejects_table_missing_rows_and_columns():
    with pytest.raises(RestoreError, match='orders'):
        _validate_json_backup_payload({'tables': {'orders': {'count': 3}}})


def test_b1_accepts_healthy_payload():
    payload = {
        'tables': {'orders': {'columns': ['id'], 'rows': [[1]]}},
        'failed_tables': [],
        'coverage': {'complete': True},
    }
    assert _validate_json_backup_payload(payload) is None


# ---------------------------------------------------------------------------
# H3：出货汇总必须用「本 SKU 数量」，不是订单首 SKU 的兼容值
# ---------------------------------------------------------------------------

def test_h3_summary_uses_this_sku_quantity():
    # 订单首 SKU 是 10 件，但当前产品（B 料）只有 7 件
    result = build_shipment_summary([_order(1, 10)], {1: 3}, {1: 7})
    assert result['order_quantity'] == 7
    assert result['available_quantity'] == 4
    assert result['orders'][0]['quantity'] == 7
    assert result['orders'][0]['available'] == 4


def test_h3_falls_back_to_order_quantity_when_no_map():
    # 未传映射（单 SKU 老调用方）时行为不变
    result = build_shipment_summary([_order(1, 10)], {1: 3})
    assert result['order_quantity'] == 10
    assert result['available_quantity'] == 7


def test_h3_multi_order_sums_per_sku_quantities():
    result = build_shipment_summary(
        [_order(1, 10), _order(2, 99)], {1: 1, 2: 2}, {1: 5, 2: 6},
    )
    assert result['order_quantity'] == 11
    assert result['shipped_quantity'] == 3
    assert result['available_quantity'] == 8


# ---------------------------------------------------------------------------
# M4：非法日期必须报错，不能静默变成「未筛选」
# ---------------------------------------------------------------------------

def test_m4_rejects_invalid_start_date():
    with pytest.raises(ValueError, match='start_date'):
        _validated_day_range('2026-13-01', None)


def test_m4_rejects_invalid_end_date():
    with pytest.raises(ValueError, match='end_date'):
        _validated_day_range(None, 'not-a-date')


def test_m4_rejects_reversed_range():
    with pytest.raises(ValueError, match='不能晚于'):
        _validated_day_range('2026-11-10', '2026-11-01')


def test_m4_accepts_empty_filter():
    assert _validated_day_range(None, None) == (None, None)


def test_m4_accepts_normal_range():
    start, end = _validated_day_range('2026-11-01', '2026-11-10')
    assert start is not None and end is not None and start < end


# ---------------------------------------------------------------------------
# M6：删除失败必须让后续 GET 变成 miss（墓碑），否则缓存永不失效
# ---------------------------------------------------------------------------

class _FlakyRedis:
    """远端还在（GET 能读到旧值），但写命令可以按需失败。"""

    def __init__(self) -> None:
        self.store: dict[str, bytes] = {}
        self.writes_ok = True

    async def get(self, key):
        return self.store.get(key)

    async def setex(self, key, ttl, value):
        self.store[key] = bytes(value) if isinstance(value, (bytes, bytearray)) else str(value).encode()
        return True

    async def unlink(self, *keys):
        if not self.writes_ok:
            raise RuntimeError('redis write timeout')
        removed = 0
        for key in keys:
            if self.store.pop(key, None) is not None:
                removed += 1
        return removed

    async def delete(self, *keys):
        return await self.unlink(*keys)

    async def scan(self, cursor=0, match=None, count=100):
        """delete_pattern 走的是 scan(cursor, match, count)，不是 scan_iter。"""
        pattern = match or '*'
        keys = [
            key for key in list(self.store)
            if fnmatch.fnmatch(key.decode() if isinstance(key, bytes) else key, pattern)
        ]
        return 0, keys  # cursor=0 表示一次扫完


@pytest.mark.asyncio
async def test_m6_failed_delete_hides_stale_value():
    from utils.redis_cache import RedisCacheManager

    cache = RedisCacheManager()
    fake = _FlakyRedis()
    cache.redis_client = fake  # type: ignore[assignment]

    await cache.set('stale', {'v': 'old'}, timeout=60)
    assert await cache.get('stale') == {'v': 'old'}

    fake.writes_ok = False
    assert await cache.delete('stale') is False
    # 关键断言：删除失败后不能再把旧值返回，否则「改了数据但页面还是旧的」
    assert await cache.get('stale') is None

    fake.writes_ok = True
    assert await cache.delete('stale') is True
    assert not cache._invalidated_keys, '删除成功后墓碑必须清掉，否则该键永久失效'


@pytest.mark.asyncio
async def test_m6_failed_delete_pattern_hides_stale_values():
    from utils.redis_cache import RedisCacheManager

    cache = RedisCacheManager()
    fake = _FlakyRedis()
    cache.redis_client = fake  # type: ignore[assignment]

    await cache.set('list:a', {'v': 1}, timeout=60)
    await cache.set('list:b', {'v': 2}, timeout=60)

    fake.writes_ok = False
    await cache.delete_pattern('list:*')

    assert await cache.get('list:a') is None
    assert await cache.get('list:b') is None


# ---------------------------------------------------------------------------
# H1：恢复锁续期失败必须中止宿主任务（而不是只打日志继续写库）
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_h1_heartbeat_cancels_host_when_renew_fails(monkeypatch):
    from fastapi_app.services.backup import restore as restore_svc

    async def _renew_failed(task_id: str) -> bool:
        return False

    monkeypatch.setattr(restore_svc, 'renew_restore_lock', _renew_failed)

    lost: list[str] = []
    state = {'cancelled': False, 'body_finished': False}

    async def _worker() -> None:
        try:
            async with restore_svc.restore_lock_heartbeat(
                'task-x', interval=0.01, on_lost=lambda: lost.append('lost'),
            ):
                await asyncio.sleep(0.5)
            state['body_finished'] = True
        except asyncio.CancelledError:
            state['cancelled'] = True

    await asyncio.wait_for(asyncio.create_task(_worker()), timeout=3)

    assert state['cancelled'] is True, '锁丢失后宿主任务必须被取消，不能继续写库'
    assert state['body_finished'] is False
    assert lost == ['lost'], '锁丢失回调应恰好触发一次（供端点转 503 / 降级终态）'


@pytest.mark.asyncio
async def test_h1_heartbeat_ticks_while_lock_held(monkeypatch):
    from fastapi_app.services.backup import restore as restore_svc

    async def _renew_ok(task_id: str) -> bool:
        return True

    monkeypatch.setattr(restore_svc, 'renew_restore_lock', _renew_ok)

    ticks: list[int] = []

    async def _on_tick() -> None:
        ticks.append(1)

    async with restore_svc.restore_lock_heartbeat('task-y', interval=0.01, on_tick=_on_tick):
        await asyncio.sleep(0.06)

    assert len(ticks) >= 2, f'续期成功时应持续刷新进度，实际只有 {len(ticks)} 次'


# ---------------------------------------------------------------------------
# H2：会话失效失败必须降级终态，不能报「无警告完成」
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_h2_revocation_failure_downgrades_terminal_state(monkeypatch):
    import fastapi_app.core.backup_progress as bp
    from fastapi_app.api.v1.endpoints.backup import restore as restore_mod

    captured: dict[str, object] = {}

    async def _complete(task_id, result=None, *, status='completed'):
        captured['status'] = status
        captured['result'] = result

    async def _fail(task_id, message):
        captured['failed'] = message

    monkeypatch.setattr(bp, 'complete_progress', _complete)
    monkeypatch.setattr(bp, 'fail_progress', _fail)

    result = {
        'database': {'status': 'ok'},
        'verification': {'overall_pass': True},
        'session_revocation': {
            'ok': False, 'errors': ['旧会话未失效: 数据库引擎未初始化'], 'warnings': [],
        },
        'errors': [],
    }
    await restore_mod._report_restore_outcome('task-1', result)

    assert 'failed' not in captured, '库已恢复但会话未失效，不该报「恢复失败」'
    assert captured['status'] == 'completed_with_warnings'
    assert any('旧会话未失效' in e for e in result['warnings']), \
        '降级终态必须把原因写进 warnings，否则运维看不到'


# ---------------------------------------------------------------------------
# H11：安装后回读校验必须逐项比对（AppParameters / AppExit / 环境变量）
# ---------------------------------------------------------------------------

_GOOD_VALUES = {
    'Application': r'C:\Python\python.exe',
    'AppDirectory': r'D:\erp_system',
    'AppParameters': 'fastapi_app.core.prod_runner',
    'AppEnvironmentExtra': ['APP_ENV=production', r'PYTHONPATH=D:\erp_system'],
    'AppExit': ['Default', 'Restart'],
}

_EXPECTED = {
    'expected_app': r'C:\Python\python.exe',
    'expected_dir': r'D:\erp_system',
    'expected_token': 'fastapi_app.core.prod_runner',
    'expected_env': ['APP_ENV=production', r'PYTHONPATH=D:\erp_system'],
}


def test_h11_accepts_correct_config():
    assert nssm_param_problems(_GOOD_VALUES, **_EXPECTED) == []


def test_h11_flags_missing_application():
    problems = nssm_param_problems({}, **_EXPECTED)
    assert any('Application 缺失' in p for p in problems)


def test_h11_flags_wrong_interpreter_and_dir():
    values = dict(_GOOD_VALUES, Application=r'C:\other\python.exe', AppDirectory=r'C:\temp')
    problems = nssm_param_problems(values, **_EXPECTED)
    assert any(p.startswith('解释器=') for p in problems)
    assert any(p.startswith('工作目录=') for p in problems)


def test_h11_flags_missing_app_parameters_token():
    # 「装了但没装对」：服务指向对的解释器，却没加载预期模块
    values = dict(_GOOD_VALUES, AppParameters='-m something_else')
    problems = nssm_param_problems(values, **_EXPECTED)
    assert any(p.startswith('启动参数=') for p in problems)


def test_h11_flags_appexit_without_restart():
    values = dict(_GOOD_VALUES, AppExit=['Default'])
    problems = nssm_param_problems(values, **_EXPECTED)
    assert any('Restart' in p for p in problems), 'AppExit 缺 Restart = 崩溃后不自动拉起'


def test_h11_flags_missing_env_var():
    values = dict(_GOOD_VALUES, AppEnvironmentExtra=['APP_ENV=production'])
    problems = nssm_param_problems(values, **_EXPECTED)
    assert any('环境变量缺失' in p and 'PYTHONPATH' in p for p in problems)


