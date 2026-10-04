"""导入文件指纹闸门（第 1 层幂等）测试。

用**真实异步会话**（sqlite+aiosqlite）而非纯 mock —— 纯 mock 会掩盖
真实 SQLAlchemy 会话语义（例如 rollback 后对象变 transient 再 delete 会抛
InvalidRequestError 这类缺陷，2026-10-04 Opus 审核实锤 H-1 就是 mock 掩盖的）。

覆盖：命中重复 409 / 并发 flush 冲突 409 / 成功落登记 / 失败（未回滚）删除登记 /
失败（服务已回滚）不炸 / 综合导入全零不锁哈希 / 综合导入行数取和各分支。
"""
import hashlib
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from fastapi_app.api.v1.endpoints import import_guard
from fastapi_app.api.v1.endpoints.import_guard import run_guarded_import
from fastapi_app.shared_models import ImportFileRegistry

# SQLite 兼容建表：PG 用 BIGSERIAL / JSONB，SQLite 需 INTEGER PRIMARY KEY
# 自增、JSON。保持模型干净（不为测试在模型里塞 with_variant）。
_CREATE_SQL = """
CREATE TABLE import_file_registry (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    file_hash         TEXT NOT NULL,
    import_type       TEXT NOT NULL,
    original_filename TEXT NOT NULL,
    uploaded_by       BIGINT,
    row_total         INTEGER,
    result_summary    JSON,
    created_at        TIMESTAMP NOT NULL DEFAULT (datetime('now')),
    CONSTRAINT uq_import_file UNIQUE (file_hash, import_type)
)
"""


class _FakeUpload:
    def __init__(self, filename: str, content: bytes):
        self.filename = filename
        self._content = content

    async def read(self, size: int = -1) -> bytes:
        return self._content


_USER = SimpleNamespace(id=7)


@pytest_asyncio.fixture
async def session(tmp_path):
    engine = create_async_engine(f'sqlite+aiosqlite:///{tmp_path}/guard.db')
    async with engine.begin() as conn:
        await conn.execute(text(_CREATE_SQL))
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        yield s
    await engine.dispose()


async def _count(session: AsyncSession) -> int:
    return (await session.execute(select(func.count()).select_from(ImportFileRegistry))).scalar()


# ---------------------------------------------------------------------------
# 重复导入 → 409
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_rejects_when_prior_registration_exists(session):
    content = b'PK\x03\x04 same file'
    digest = hashlib.sha256(content).hexdigest()
    session.add(ImportFileRegistry(
        file_hash=digest, import_type=import_guard.TYPE_STOCKOUTS,
        original_filename='a.xlsx', uploaded_by=1, created_at=datetime.now(UTC),
    ))
    await session.commit()

    called = False

    async def runner(_f):
        nonlocal called
        called = True
        return SimpleNamespace(success=True)

    with pytest.raises(HTTPException) as ei:
        await run_guarded_import(
            session, _FakeUpload('a.xlsx', content), import_guard.TYPE_STOCKOUTS, _USER, runner
        )
    assert ei.value.status_code == 409
    assert '重复导入' in ei.value.detail
    assert not called, '命中重复时不得执行导入'


@pytest.mark.asyncio
async def test_rejects_on_concurrent_flush_violation():
    """并发双击：首次查询未命中，flush 撞唯一约束 → 409（而非 500）。

    真实并发需两个连接，此处用「flush 抛 IntegrityError」的替身专测 except 分支。
    """
    class _FlushRaises:
        rolled_back = False

        async def scalar(self, _s):
            return None

        def add(self, _o):
            pass

        async def flush(self):
            raise IntegrityError('stmt', {}, Exception('uq_import_file'))

        async def rollback(self):
            self.rolled_back = True

    db = _FlushRaises()

    async def runner(_f):
        return SimpleNamespace(success=True)

    with pytest.raises(HTTPException) as ei:
        await run_guarded_import(
            db, _FakeUpload('a.xlsx', b'x'), import_guard.TYPE_STOCKINS, _USER, runner
        )
    assert ei.value.status_code == 409
    assert db.rolled_back, '唯一约束冲突后必须回滚事务'


# ---------------------------------------------------------------------------
# 成功 → 落登记 + 可重放文件
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_persists_registration_on_success(session):
    seen: dict = {}

    async def runner(f):
        seen['content'] = await f.read()
        seen['filename'] = f.filename
        return SimpleNamespace(success=True, imported=5, skipped=1)

    content = b'PK\x03\x04 excel'
    result = await run_guarded_import(
        session, _FakeUpload('orders.xlsx', content), import_guard.TYPE_ORDERS, _USER, runner
    )
    await session.commit()

    assert result.imported == 5
    assert seen['content'] == content and seen['filename'] == 'orders.xlsx'
    assert await _count(session) == 1
    reg = (await session.execute(select(ImportFileRegistry))).scalar_one()
    assert reg.row_total == 5 and reg.result_summary == {'skipped': 1}
    assert reg.import_type == import_guard.TYPE_ORDERS


# ---------------------------------------------------------------------------
# 失败 → 登记不留存（两条真实路径）
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_removes_registration_when_import_fails_without_rollback(session):
    """早退校验失败（服务未回滚）→ 登记仍在会话中 → 显式删除。"""
    async def runner(_f):
        return SimpleNamespace(success=False, imported=0, skipped=0)

    await run_guarded_import(
        session, _FakeUpload('bad.txt', b'nope'), import_guard.TYPE_STOCKOUTS, _USER, runner
    )
    await session.commit()
    assert await _count(session) == 0, '失败导入不得留登记（否则无法重试）'


@pytest.mark.asyncio
async def test_failure_after_service_rollback_does_not_raise(session):
    """服务错误分支 `await db.rollback()` 后对象变 transient —— 守卫不得再 delete。

    回归守卫：修复前此处抛 InvalidRequestError → 500（2026-10-04 H-1）。
    """
    async def runner(_f):
        await session.rollback()  # 模拟服务层 except 分支的行为
        return SimpleNamespace(success=False, imported=0, skipped=0)

    # 不得抛异常
    await run_guarded_import(
        session, _FakeUpload('x.xlsx', b'z'), import_guard.TYPE_ORDERS, _USER, runner
    )
    assert await _count(session) == 0


@pytest.mark.asyncio
async def test_zero_import_is_treated_as_failure(session):
    """success=True 但零行（如空 Sheet）→ 视为失败，不锁文件哈希。"""
    async def runner(_f):
        return SimpleNamespace(success=True, imported=0, skipped=0)

    await run_guarded_import(
        session, _FakeUpload('empty.xlsx', b'e'), import_guard.TYPE_STOCKOUTS, _USER, runner
    )
    await session.commit()
    assert await _count(session) == 0


# ---------------------------------------------------------------------------
# 综合导入：dict 结果（H-2）+ 全零不锁哈希（M-1）
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_comprehensive_partial_success_sums_row_total(session):
    """imported 是 dict —— row_total 必须取和，塞 dict 会致 commit 失败、整批丢失。"""

    async def runner(_f):
        return SimpleNamespace(
            success=True, imported={'products': 2, 'orders': 3, 'stockins': 0, 'stockouts': 0}
        )

    await run_guarded_import(
        session, _FakeUpload('all.xlsx', b'c'), import_guard.TYPE_COMPREHENSIVE, _USER, runner
    )
    await session.commit()
    reg = (await session.execute(select(ImportFileRegistry))).scalar_one()
    assert reg.row_total == 5, 'row_total 必须为 int（各 Sheet 求和），不得是 dict'
    assert isinstance(reg.row_total, int)


@pytest.mark.asyncio
async def test_comprehensive_all_zero_does_not_lock_hash(session):
    """综合导入 success 恒 True，但全部 Sheet 零导入 → 不得锁死文件哈希。"""
    async def runner(_f):
        return SimpleNamespace(
            success=True, imported={'products': 0, 'orders': 0, 'stockins': 0, 'stockouts': 0}
        )

    await run_guarded_import(
        session, _FakeUpload('fail.xlsx', b'f'), import_guard.TYPE_COMPREHENSIVE, _USER, runner
    )
    await session.commit()
    assert await _count(session) == 0, '全零综合导入不得留登记'
