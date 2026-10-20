"""ARQ 任务重放幂等与循环提交批量化（P1-7）测试。

守卫三件事：

1. ``CommitBatcher`` 每 ``batch_size`` 条提交一次（``commits == ceil(条数/batch_size)``），
   不再逐条 commit；
2. ARQ 任务被**重放**（``max_tries=3``，同一 ``job_id``）时不产生重复副作用：幂等标记只在
   提交成功之后登记，所以已提交的行被跳过，而崩溃前未提交的批次会被重做（不丢数据）；
3. ``core/arq_app.py`` 仍可 import 且任务函数能被 arq 装配（``create_worker``）。
"""
import os
import tempfile
import types
from unittest.mock import AsyncMock

import pytest
from arq.worker import create_worker

from fastapi_app.core import arq_app
from fastapi_app.core import database as database_module
from fastapi_app.services.backup import schedule_service
from fastapi_app.tasks import backup_tasks as bk
from fastapi_app.tasks import batch_tasks as bt


class _FakeSavepoint:
    """空 savepoint 上下文（Z06-R6：行循环每行套一个 savepoint）。"""

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeDb:
    """只记录 commit/rollback/close 的假会话。"""

    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0
        self.closed = False
        self.savepoints = 0

    def begin_nested(self):
        self.savepoints += 1
        return _FakeSavepoint()

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1

    async def close(self) -> None:
        self.closed = True


class _FakeRedis:
    """最小 Redis 集合客户端（smembers/sadd/expire）；``fail=True`` 用于验证 fail-open。"""

    def __init__(self, *, fail: bool = False) -> None:
        self._sets: dict[str, set[str]] = {}
        self.ttls: dict[str, int] = {}
        self.fail = fail

    async def smembers(self, key: str) -> set[str]:
        if self.fail:
            raise ConnectionError('redis down')
        return set(self._sets.get(key, set()))

    async def sadd(self, key: str, *members: str) -> None:
        if self.fail:
            raise ConnectionError('redis down')
        self._sets.setdefault(key, set()).update(members)

    async def expire(self, key: str, ttl: int) -> None:
        if self.fail:
            raise ConnectionError('redis down')
        self.ttls[key] = ttl


def _tmp_upload() -> str:
    """位于 ALLOWED_UPLOAD_DIRS 内的路径（不需要真实存在，解析层被替换）。"""
    return os.path.join(tempfile.gettempdir(), 'arq_idempotency_probe.xlsx')


def _idempotency(redis=None, *, job_id: str = 'job-1') -> arq_app.JobIdempotency:
    """构造 ``job_id`` 固定的幂等闸门（重放 = 用同一 job_id 再跑一次）。"""
    ctx: dict = {'job_id': job_id}
    if redis is not None:
        ctx['redis'] = redis
    return arq_app.job_idempotency(ctx, namespace=arq_app.IDEMPOTENCY_NAMESPACE_BATCH_IMPORT)


def _patch_import(monkeypatch, rows: list, db) -> AsyncMock:
    """替换解析与会话工厂，返回单行处理协程的 mock。"""
    monkeypatch.setattr(bt, '_parse_rows_async', AsyncMock(return_value=(True, rows, '')))
    monkeypatch.setattr(bt, '_open_import_session', AsyncMock(return_value=db))
    return AsyncMock(return_value=None)


# ---------------------------------------------------------------------------
# CommitBatcher：批提交语义
# ---------------------------------------------------------------------------
async def test_commit_batcher_commits_once_per_batch():
    db = _FakeDb()
    batcher = arq_app.CommitBatcher(db)
    assert arq_app.DEFAULT_COMMIT_BATCH_SIZE == 200
    for _ in range(250):
        await batcher.tick()
    await batcher.flush()
    batches = -(-250 // arq_app.DEFAULT_COMMIT_BATCH_SIZE)
    assert db.commits == batcher.commits == 2
    assert db.commits <= batches + 1


async def test_commit_batcher_flush_skips_empty_batch():
    db = _FakeDb()
    batcher = arq_app.CommitBatcher(db, batch_size=5)
    assert await batcher.flush() is False
    assert db.commits == 0
    for _ in range(3):
        assert await batcher.tick() is False
    assert await batcher.flush() is True
    assert db.commits == 1


def test_commit_batcher_rejects_invalid_batch_size():
    with pytest.raises(ValueError):
        arq_app.CommitBatcher(_FakeDb(), batch_size=0)


# ---------------------------------------------------------------------------
# 批量导入：重放幂等（acceptance ①）+ 批提交计数（acceptance ②）
# ---------------------------------------------------------------------------
async def test_batch_import_replay_does_not_duplicate_committed_rows(monkeypatch):
    rows = [{'产品名称': f'P{i}', '客户名称': 'C', '数量': 1} for i in range(5)]
    db = _FakeDb()
    build = _patch_import(monkeypatch, rows, db)
    redis = _FakeRedis()
    idempotency = _idempotency(redis)

    first = await bt._run_batch_import_async(_tmp_upload(), 'job-1', '订单', build, idempotency=idempotency)
    assert first['imported_count'] == 5
    assert first['skipped_idempotent'] == 0
    assert build.await_count == 5

    # ARQ 重放：同一 job_id、同一文件再跑一次 —— 不得重复建单/重复加减库存
    replay = await bt._run_batch_import_async(_tmp_upload(), 'job-1', '订单', build, idempotency=idempotency)
    assert replay['imported_count'] == 0
    assert replay['skipped_idempotent'] == 5
    assert build.await_count == 5  # 副作用没有第二次
    assert idempotency.key == 'arq:idem:batch-import:job-1'
    assert redis.ttls[idempotency.key] == arq_app.IDEMPOTENCY_TTL_SECONDS


async def test_batch_import_replay_redoes_only_uncommitted_rows(monkeypatch):
    rows = [{'产品名称': f'P{i}'} for i in range(5)]
    db = _FakeDb()
    calls = {'n': 0, 'crash': True}

    async def build(_db, _row, _i):
        calls['n'] += 1
        if calls['crash'] and calls['n'] == 3:
            raise RuntimeError('worker 崩溃（模拟）')  # 不在窄 except 内 → 直接冒泡
        return None

    monkeypatch.setattr(bt, '_parse_rows_async', AsyncMock(return_value=(True, rows, '')))
    monkeypatch.setattr(bt, '_open_import_session', AsyncMock(return_value=db))
    idempotency = _idempotency(_FakeRedis())

    with pytest.raises(RuntimeError):
        await bt._run_batch_import_async(_tmp_upload(), 'job-1', '订单', build,
                                         batch_size=2, idempotency=idempotency)
    assert db.commits == 1  # 第 1 批（行 2、3）已提交 → 已登记幂等标记

    calls['n'] = 0
    calls['crash'] = False  # 重放这次不再崩
    second = await bt._run_batch_import_async(_tmp_upload(), 'job-1', '订单', build,
                                              batch_size=2, idempotency=idempotency)
    assert second['skipped_idempotent'] == 2  # 已提交的两行跳过
    assert second['imported_count'] == 3      # 崩溃时未提交的 3 行被重做（不丢行）
    assert calls['n'] == 3


async def test_batch_import_commit_count_is_batch_count(monkeypatch):
    rows = [{'产品名称': f'P{i}'} for i in range(110)]
    db = _FakeDb()
    build = _patch_import(monkeypatch, rows, db)
    result = await bt._run_batch_import_async(_tmp_upload(), 'job-1', '订单', build,
                                              idempotency=_idempotency(_FakeRedis()))
    batches = -(-110 // bt.BATCH_COMMIT_SIZE)
    assert result['imported_count'] == 110
    assert result['errors'] == []
    assert db.commits == batches
    assert db.commits <= batches + 1  # 每 N 条一批，而不是逐条 commit


def test_row_business_key_binds_row_number_and_content():
    row = {'产品名称': 'P1', '客户名称': 'C', '数量': 2}
    assert bt._row_business_key(row, 2) == bt._row_business_key(dict(row), 2)
    assert bt._row_business_key(row, 2) != bt._row_business_key(row, 3)
    assert bt._row_business_key(row, 2) != bt._row_business_key({'产品名称': 'P2'}, 2)


# ---------------------------------------------------------------------------
# 幂等存储：Redis 主线 / 进程内兜底 / fail-open
# ---------------------------------------------------------------------------
async def test_job_idempotency_falls_back_to_in_memory_without_redis():
    store = arq_app.in_memory_idempotency_store()
    store.clear()
    idempotency = arq_app.job_idempotency({'job_id': 'job-x'}, namespace='ns')
    assert idempotency.key == 'arq:idem:ns:job-x'
    assert await idempotency.load() == set()
    await idempotency.mark(['a', 'b'])
    assert await idempotency.load() == {'a', 'b'}
    assert arq_app.job_idempotency(None, namespace='ns').job_id == 'anonymous'
    store.clear()


async def test_redis_idempotency_store_roundtrip_with_ttl():
    redis = _FakeRedis()
    idempotency = arq_app.job_idempotency({'job_id': 'j', 'redis': redis}, namespace='ns')
    await idempotency.mark(['a'])
    assert await idempotency.load() == {'a'}
    assert redis.ttls[idempotency.key] == arq_app.IDEMPOTENCY_TTL_SECONDS


async def test_redis_idempotency_store_fails_open():
    redis = _FakeRedis(fail=True)
    idempotency = arq_app.job_idempotency({'job_id': 'j', 'redis': redis}, namespace='ns')
    assert await idempotency.load() == set()  # 读失败 → 本批不去重，但绝不抛
    await idempotency.mark(['a'])             # 写失败 → 只记 WARNING


# ---------------------------------------------------------------------------
# 调度轮询：批提交 + 重放去重（acceptance ①②③）
# ---------------------------------------------------------------------------
class _FakePool:
    """记录入队的假 ARQ 池（返回非 None 视为入队成功）。"""

    def __init__(self) -> None:
        self.enqueued: list[tuple] = []

    async def enqueue_job(self, func_name: str, _job_id: str | None = None):
        self.enqueued.append((func_name, _job_id))
        return object()


class _FakeDbContext:
    """``async with get_async_db_context() as db`` 的假上下文。"""

    def __init__(self, db) -> None:
        self._db = db

    async def __aenter__(self):
        return self._db

    async def __aexit__(self, *exc) -> bool:
        return False


def _schedule(schedule_id: int):
    return types.SimpleNamespace(id=schedule_id, name=f's{schedule_id}', task_type='full',
                                 last_run_at=None, last_status=None)


async def test_scheduler_poller_batches_commits_and_skips_replayed_schedules(monkeypatch):
    schedules = [_schedule(7), _schedule(8), _schedule(9)]
    db = _FakeDb()
    pool = _FakePool()
    monkeypatch.setattr(database_module, 'get_async_db_context', lambda: _FakeDbContext(db))
    monkeypatch.setattr(schedule_service, 'due_schedules', AsyncMock(return_value=schedules))
    monkeypatch.setattr(arq_app, 'get_arq_pool', AsyncMock(return_value=pool))
    ctx = {'job_id': 'poller-sched:1', 'redis': _FakeRedis()}

    await bk.scheduler_poller(ctx)
    assert [name for name, _ in pool.enqueued] == ['auto_daily_backup_task'] * 3
    assert all(job_id and job_id.startswith('sched:') for _, job_id in pool.enqueued)
    batches = -(-3 // arq_app.DEFAULT_COMMIT_BATCH_SIZE)
    assert db.commits == 1 <= batches + 1  # 3 条一次收尾提交，而不是逐条 3 次
    assert [s.last_status for s in schedules] == ['running'] * 3

    # ARQ 重放同一 job：已入队且状态已提交的调度不得重复入队/重复回写
    await bk.scheduler_poller(ctx)
    assert len(pool.enqueued) == 3
    assert db.commits == 1


def test_arq_worker_still_loads_tasks():
    worker = create_worker(arq_app.WorkerSettings)
    for name in ('batch_import_orders_task', 'batch_import_stockins_task', 'scheduler_poller'):
        assert name in worker.functions
