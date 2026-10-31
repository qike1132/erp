"""权限缓存跨 worker 失效回归（L1，2026-10-31 评审）。

背景：USER_PERMISSION_CHANGED 事件此前已定义但全链路无生产者/消费者——
invalidate_user_permission_cache 只清当前 worker，其余 worker 的 L1 权限缓存
要等 TTL（5s）自然过期，管理员撤销权限后数秒内其他 worker 仍按旧权限放行。

现链路：user.py::_schedule_permission_cache_invalidation 的 post-commit 回调
在本地失效之外 publish 事件（进程内派发覆盖发布 worker，Redis 广播覆盖其余
worker）；deps.register_permission_event_subscriber 订阅并在每个 worker 消费后
失效本进程 L1（含 _USER_ACTIVE_CACHE，禁用/删除用户同样受益）。

本文件锁两半：① 订阅者收到事件 → 失效对应 user 的本地缓存；
② user.py 的 post-commit 回调 → 发布正确类型与载荷的事件。
广播半边（跨进程监听器分发）由 test_domain_events_dedup 系列覆盖。
"""
import fastapi_app.core.deps as deps
import fastapi_app.core.domain_events as de
from fastapi_app.core.domain_events import DomainEvent, DomainEventType


class _FakeDB:
    """带 info dict 的最小 AsyncSession 替身（post_commit_callbacks 挂载点）。"""

    def __init__(self):
        self.info = {}


async def test_subscriber_invalidates_local_cache_on_event(monkeypatch):
    """① 订阅者收到 USER_PERMISSION_CHANGED 后必须失效该 user 的本地缓存。"""
    popped = []

    async def _fake_invalidate(user_id=None):
        popped.append(user_id)

    monkeypatch.setattr(deps, 'invalidate_user_permission_cache', _fake_invalidate)
    # 干净注册表：隔离其他用例可能注册的重复条目，保证计数确定性
    monkeypatch.setitem(de._subscribers, DomainEventType.USER_PERMISSION_CHANGED, [])
    deps.register_permission_event_subscriber()

    await de.publish(DomainEvent(
        event_type=DomainEventType.USER_PERMISSION_CHANGED,
        domain='user', payload={'user_id': 42},
    ))

    assert popped == [42], '事件未触发本地权限缓存失效'


async def test_subscriber_ignores_bad_payload(monkeypatch):
    """载荷缺 user_id / 非整数时不失效也不抛（防御：坏消息不得打挂监听协程）。"""
    popped = []

    async def _fake_invalidate(user_id=None):
        popped.append(user_id)

    monkeypatch.setattr(deps, 'invalidate_user_permission_cache', _fake_invalidate)
    monkeypatch.setitem(de._subscribers, DomainEventType.USER_PERMISSION_CHANGED, [])
    deps.register_permission_event_subscriber()

    await de.publish(DomainEvent(
        event_type=DomainEventType.USER_PERMISSION_CHANGED,
        domain='user', payload={'user_id': 'not-an-int'},
    ))
    await de.publish(DomainEvent(
        event_type=DomainEventType.USER_PERMISSION_CHANGED,
        domain='user', payload={},
    ))

    assert popped == [], '坏载荷不应触发失效'


async def test_permission_change_callback_publishes_event(monkeypatch):
    """② user.py 的 post-commit 回调在本地失效之外必须发布正确的事件。"""
    from fastapi_app.api.v1.endpoints import user as user_endpoint

    invalidated = []
    published = []

    async def _fake_invalidate(user_id=None):
        invalidated.append(user_id)

    async def _fake_publish(event):
        published.append(event)

    # 回调内 publish 是懒导入（from ... import publish），patch 源模块属性即可命中；
    # invalidate_user_permission_cache 则是 user.py 顶部导入的绑定名，须 patch 该模块
    monkeypatch.setattr(de, 'publish', _fake_publish)
    monkeypatch.setattr(
        'fastapi_app.api.v1.endpoints.user.invalidate_user_permission_cache',
        _fake_invalidate,
    )

    db = _FakeDB()
    user_endpoint._schedule_permission_cache_invalidation(db, 7)

    callbacks = db.info.get('post_commit_callbacks', [])
    assert len(callbacks) == 1, '回调未挂载到 post_commit_callbacks'
    await callbacks[0]()

    assert invalidated == [7], '本地失效未执行'
    assert len(published) == 1, '事件未发布'
    assert published[0].event_type == DomainEventType.USER_PERMISSION_CHANGED
    assert published[0].payload == {'user_id': 7}
