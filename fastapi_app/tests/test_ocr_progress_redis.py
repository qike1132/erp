"""OCR 进度 Redis 化回归（2026-10-17 审计 AUD-03）

缺陷：进度存模块级 dict，4 worker 下轮询被分到非创建 worker 时永远查不到，
端点静默新建全 0 进度 → 前端 0% 卡死。现走 core.redis_wrapper（跨进程），
不可用时降级进程内字典。
"""
import pytest

from fastapi_app.services.ocr import _progress


@pytest.fixture(autouse=True)
def _clear_fallback():
    _progress._progress_store.clear()
    yield
    _progress._progress_store.clear()


@pytest.fixture
def no_redis(monkeypatch):
    async def _get(key, fallback=None, context=''):
        return fallback

    async def _set(key, value, timeout=300, context=''):
        return False

    monkeypatch.setattr(_progress, 'safe_get', _get)
    monkeypatch.setattr(_progress, 'safe_set', _set)


@pytest.fixture
def fake_redis(monkeypatch):
    store: dict[str, dict] = {}

    async def _get(key, fallback=None, context=''):
        # 模拟真实语义：miss 返回 None；fallback 只在读取异常时使用
        return store.get(key)

    async def _set(key, value, timeout=300, context=''):
        store[key] = value
        return True

    monkeypatch.setattr(_progress, 'safe_get', _get)
    monkeypatch.setattr(_progress, 'safe_set', _set)
    return store


@pytest.mark.asyncio
async def test_redis_store_is_shared_across_module_instances(fake_redis):
    """模拟另一个 worker：进程内 dict 为空，仍能从 Redis 读到进度"""
    task_id = await _progress.create_progress()
    await _progress._update_progress(task_id, status='processing', percent=40)

    _progress._progress_store.clear()  # 模拟另一个进程的内存
    data = await _progress.get_progress(task_id)

    assert data is not None
    assert data['percent'] == 40
    assert data['status'] == 'processing'
    assert fake_redis[_progress._key(task_id)]['percent'] == 40


@pytest.mark.asyncio
async def test_fallback_dict_when_redis_unavailable(no_redis):
    task_id = await _progress.create_progress()

    data = await _progress.get_progress(task_id)
    assert data is not None
    assert data['status'] == 'pending'


@pytest.mark.asyncio
async def test_unknown_task_is_initialized_on_update(no_redis):
    """上传端点可能先于 create-task 携带未知 task_id：更新时自动初始化"""
    await _progress._update_progress('unknown-task', status='processing', percent=5)

    data = await _progress.get_progress('unknown-task')
    assert data is not None
    assert data['percent'] == 5


@pytest.mark.asyncio
async def test_percent_is_monotonic(no_redis):
    task_id = await _progress.create_progress()
    await _progress._update_progress(task_id, percent=60)
    await _progress._update_progress(task_id, percent=30)

    data = await _progress.get_progress(task_id)
    assert data is not None
    assert data['percent'] == 60


@pytest.mark.asyncio
async def test_get_returns_none_when_missing(fake_redis):
    # Redis 正常但确实没有该 key → None（端点转 not_found 终态）
    assert await _progress.get_progress('nope') is None


@pytest.mark.asyncio
async def test_get_returns_pending_when_redis_unavailable(no_redis):
    # Redis 读取失败不等于任务不存在：返回 pending 占位，避免长批量被前端判死
    data = await _progress.get_progress('nope')
    assert data is not None
    assert data['status'] == 'pending'


@pytest.mark.asyncio
async def test_redis_miss_does_not_fall_back_to_store(fake_redis):
    """2026-10-18 OCR 评审：Redis 正常但 key 缺失 → None，不得回退进程内字典。

    旧实现最后一行是 `return _progress_store.get(task_id)`：Redis 侧 TTL 已过
    而进程内字典无过期机制时，会挖出一条**永不消失**的旧进度，端点永远不返回
    not_found，前端无限轮询。
    """
    import time as time_mod

    from fastapi_app.services.ocr._progress import _PROGRESS_TTL

    # 进程内字典里放一条已过期的旧进度（模拟上次 Redis 写入成功后残留）
    _progress._progress_store['stale-task'] = (
        {'status': 'done', 'percent': 100, 'message': '旧任务'},
        time_mod.monotonic() - 1,
    )
    assert await _progress.get_progress('stale-task') is None

    # 未过期的兜底条目也只在 Redis 读失败时兜底，Redis miss 仍返回 None
    _progress._progress_store['fresh-task'] = (
        {'status': 'processing', 'percent': 50, 'message': '新任务'},
        time_mod.monotonic() + _PROGRESS_TTL,
    )
    assert await _progress.get_progress('fresh-task') is None


@pytest.mark.asyncio
async def test_store_entry_expires_by_ttl():
    """进程内兜底字典自己也带 TTL（Redis 不可用时不能永久驻留）。"""
    import time as time_mod

    from fastapi_app.services.ocr._progress import _store_get, _store_put

    _store_put('t-exp', {'status': 'pending', 'percent': 0, 'message': ''})
    assert _store_get('t-exp') is not None

    # 手工把过期时间拨到过去，验证读取时按 TTL 判死
    data, _ = _progress._progress_store['t-exp']
    _progress._progress_store['t-exp'] = (data, time_mod.monotonic() - 1)
    assert _store_get('t-exp') is None
    # 过期条目被顺手清掉，不会在字典里无限堆积
    assert 't-exp' not in _progress._progress_store


@pytest.mark.asyncio
async def test_read_failure_falls_back_to_store_then_placeholder(monkeypatch):
    """Redis 读异常 → 先看进程内兜底，没有才返回非终态占位。"""
    import time as time_mod

    async def _boom(key, fallback=None, context=''):
        return fallback  # safe_get 读失败时的契约：返回 fallback

    monkeypatch.setattr(_progress, 'safe_get', _boom)

    # 进程内有未过期条目：读异常时优先用它（单 worker 下它是最新的）
    _progress._progress_store['t-fb'] = (
        {'status': 'processing', 'percent': 70, 'message': 'ocr'},
        time_mod.monotonic() + 3600,
    )
    data = await _progress.get_progress('t-fb')
    assert data is not None
    assert data['percent'] == 70

    # 进程内也没有：返回 pending 占位（非终态），让前端继续轮询
    data2 = await _progress.get_progress('never-seen')
    assert data2 is not None
    assert data2['status'] == 'pending'
    # 占位必须是副本：调用方 update() 不能污染共享哨兵
    data2['percent'] = 999
    assert _progress._UNAVAILABLE['percent'] == 0
