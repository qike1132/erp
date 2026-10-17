"""OCR 进度 Redis 化回归（2026-10-17 审计 AUD-03）

缺陷：进度存模块级 dict，4 worker 下轮询被分到非创建 worker 时永远查不到，
端点静默新建全 0 进度 → 前端 0% 卡死。现改为 Redis（跨进程）+ 进程内降级。
"""
import json

import pytest

from fastapi_app.services.ocr import _progress


@pytest.fixture(autouse=True)
def _clear_fallback():
    _progress._progress_store.clear()
    yield
    _progress._progress_store.clear()


async def _no_client():
    return None


class _FakeRedis:
    def __init__(self):
        self.store: dict[str, str] = {}

    async def set(self, key, value, ex=None):
        self.store[key] = value
        return True

    async def get(self, key):
        return self.store.get(key)


@pytest.mark.asyncio
async def test_redis_store_is_shared_across_module_instances(monkeypatch):
    """模拟另一个 worker：进程内 dict 为空，仍能从 Redis 读到进度"""
    fake = _FakeRedis()

    async def _client():
        return fake

    monkeypatch.setattr(_progress, '_get_client', _client)
    task_id = await _progress.create_progress()
    await _progress._update_progress(task_id, status='processing', percent=40)

    _progress._progress_store.clear()  # 模拟另一个进程的内存
    data = await _progress.get_progress(task_id)

    assert data is not None
    assert data['percent'] == 40
    assert data['status'] == 'processing'
    assert json.loads(fake.store[_progress._key(task_id)])['percent'] == 40


@pytest.mark.asyncio
async def test_fallback_dict_when_redis_unavailable(monkeypatch):
    monkeypatch.setattr(_progress, '_get_client', _no_client)
    task_id = await _progress.create_progress()

    data = await _progress.get_progress(task_id)
    assert data is not None
    assert data['status'] == 'pending'


@pytest.mark.asyncio
async def test_unknown_task_is_initialized_on_update(monkeypatch):
    """上传端点可能先于 create-task 携带未知 task_id：更新时自动初始化"""
    monkeypatch.setattr(_progress, '_get_client', _no_client)

    await _progress._update_progress('unknown-task', status='processing', percent=5)

    data = await _progress.get_progress('unknown-task')
    assert data is not None
    assert data['percent'] == 5


@pytest.mark.asyncio
async def test_percent_is_monotonic(monkeypatch):
    monkeypatch.setattr(_progress, '_get_client', _no_client)
    task_id = await _progress.create_progress()
    await _progress._update_progress(task_id, percent=60)
    await _progress._update_progress(task_id, percent=30)

    data = await _progress.get_progress(task_id)
    assert data is not None
    assert data['percent'] == 60


@pytest.mark.asyncio
async def test_get_returns_none_when_missing(monkeypatch):
    monkeypatch.setattr(_progress, '_get_client', _no_client)
    assert await _progress.get_progress('nope') is None
