"""H-1：还原流程必须**真正开启**维护模式（还原期间拒绝非备份域写请求）。

背景：`core/maintenance.py` 的 `enter_maintenance` / `exit_maintenance` 此前
**在生产代码里零调用方**（docstring 自认的「已知缺口，需产品决策」），于是
"还原期间禁止业务写入"只是文案，还原期间订单照写。

接线点选在还原锁的 **获取 / 释放 / 续期** 三处 —— 同步路径与异步任务路径共用
`services/backup/restore.py` 里这三个函数，故单点接线即可全覆盖：

* 取锁成功  → 开维护模式（fail-open：开不上只告警，能否还原已由锁 fail-closed 决定）
* **由持锁者**释放 → 关维护模式（非持锁者不得关，否则会替并发中的还原开门）
* 锁续期成功 → 维护模式同步续期（否则还原超过 30 分钟 gate 会中途失效）
"""
from __future__ import annotations

import pytest

from fastapi_app.services.backup import restore as restore_svc


class _FakeRedis:
    """最小假 Redis：只覆盖锁与维护模式用到的命令。"""

    def __init__(self, *, acquire_ok: bool = True, release_result: int = 1, renew_result: int = 1) -> None:
        self.calls: list[tuple] = []
        self._acquire_ok = acquire_ok
        self._release_result = release_result
        self._renew_result = renew_result

    async def set(self, key, value, nx=False, ex=None):
        self.calls.append(('set', key, value, nx, ex))
        return True if self._acquire_ok else None

    async def eval(self, script, numkeys, *args):
        self.calls.append(('eval', numkeys, *args))
        return self._release_result if 'DEL' in script else self._renew_result

    async def delete(self, key):
        self.calls.append(('delete', key))
        return 1


@pytest.fixture()
def fake_redis(monkeypatch):
    def _install(fake: _FakeRedis) -> _FakeRedis:
        async def _get_redis():
            return fake

        import fastapi_app.core.backup_progress as bp

        monkeypatch.setattr(bp, '_get_redis', _get_redis)
        return fake

    return _install


@pytest.fixture()
def maintenance(monkeypatch):
    """记录维护模式的开关/续期调用（接线是本用例的被测对象）。"""
    calls = {'enter': 0, 'exit': 0, 'renew': 0}

    import fastapi_app.core.maintenance as m

    async def enter():
        calls['enter'] += 1
        return True

    async def exit_():
        calls['exit'] += 1

    async def renew():
        calls['renew'] += 1
        return True

    monkeypatch.setattr(m, 'enter_maintenance', enter)
    monkeypatch.setattr(m, 'exit_maintenance', exit_)
    monkeypatch.setattr(m, 'renew_maintenance', renew)
    return calls


# ---------------------------------------------------------------------------
# 取锁 → 开维护模式
# ---------------------------------------------------------------------------

async def test_acquire_turns_maintenance_on(fake_redis, maintenance):
    fake_redis(_FakeRedis(acquire_ok=True))

    assert await restore_svc.acquire_restore_lock('t1') is True
    assert maintenance['enter'] == 1, '取到还原锁后必须开启维护模式'


async def test_failed_acquire_leaves_maintenance_untouched(fake_redis, maintenance):
    fake_redis(_FakeRedis(acquire_ok=False))

    assert await restore_svc.acquire_restore_lock('t1') is False
    assert maintenance['enter'] == 0, '没取到锁就不能开维护模式（会误伤正常写入）'


# ---------------------------------------------------------------------------
# 释放 → 只有持锁者能关
# ---------------------------------------------------------------------------

async def test_release_by_owner_turns_maintenance_off(fake_redis, maintenance):
    fake_redis(_FakeRedis(release_result=1))  # Lua 比对成功 = 确实是我删掉的

    await restore_svc.release_restore_lock('t1')

    assert maintenance['exit'] == 1


async def test_release_by_non_owner_keeps_maintenance_on(fake_redis, maintenance):
    """锁已易主（Lua 返回 0）：这是**别人的**还原在跑，不得替他关闸门。"""
    fake_redis(_FakeRedis(release_result=0))

    await restore_svc.release_restore_lock('t1')

    assert maintenance['exit'] == 0


async def test_legacy_unconditional_release_also_clears_maintenance(fake_redis, maintenance):
    fake_redis(_FakeRedis())

    await restore_svc.release_restore_lock()

    assert maintenance['exit'] == 1


# ---------------------------------------------------------------------------
# 续期 → 维护模式与锁同周期
# ---------------------------------------------------------------------------

async def test_renew_refreshes_maintenance(fake_redis, maintenance):
    fake_redis(_FakeRedis(renew_result=1))

    assert await restore_svc.renew_restore_lock('t1') is True
    assert maintenance['renew'] == 1, '长还原续锁时必须同步续维护模式 TTL'


async def test_failed_renew_does_not_refresh_maintenance(fake_redis, maintenance):
    fake_redis(_FakeRedis(renew_result=0))

    assert await restore_svc.renew_restore_lock('t1') is False
    assert maintenance['renew'] == 0
