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
