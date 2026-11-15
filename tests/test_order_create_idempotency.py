"""``POST /orders/create`` 请求级幂等（P0）回归。

为什么不走 conftest 的 PG fixture：这些用例要验证的是「第二次请求不再建单」，
必须数真实的 order / inventory_log 行。这里用**自包含的真实 SQLite**（真实表、
真实 INSERT/SELECT）驱动端点函数本体，因此不依赖测试库连接：

- ``order`` / ``order_item`` / ``inventory_log`` / ``product`` / ``user`` 用 ORM
  真实表建库；
- ``order_create_attempt.response_body`` 在生产是 PG 的 JSONB，SQLite 方言没有该
  类型的编译实现（``can't render element of type JSONB``），故测试里建一个**同名
  同列**的影子表，只把 JSONB 换成 JSON；下方
  ``test_shadow_table_columns_match_model`` 防止影子表与模型漂移；
- 真正的下单实现（generate_order_number / 外发工序 / 缓存 / 领域事件）依赖 PG 与
  Redis，测试里替身到**语句级**：替身只 ``insert`` 一条 order 与一条 inventory_log，
  于是「没有第 2 张单 / 第 2 条流水」是可数的行数断言，而不是「某个 mock 没被调用」。
"""
from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    Integer,
    MetaData,
    String,
    Table,
    UniqueConstraint,
    func,
    select,
)
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from fastapi_app.core.exceptions import BusinessError
from fastapi_app.core.pg_locks import number_lock_key
from fastapi_app.schemas.order import OrderCreate
from fastapi_app.services import order_idempotency as oi
from fastapi_app.shared_models import Base, InventoryLog, Order, OrderCreateAttempt, Product

KEY = 'order-create:key-1'


def _attempt_shadow_table() -> Table:
    """SQLite 可建版的 ``order_create_attempt``（唯一差异：JSONB → JSON）。"""
    return Table(
        'order_create_attempt',
        MetaData(),
        Column('id', Integer, primary_key=True),
        Column('actor_id', Integer, nullable=False),
        Column('idempotency_key', String(64), nullable=False),
        Column('request_hash', String(64), nullable=False),
        Column('response_body', JSON, nullable=True),
        Column('created_at', DateTime(timezone=True), nullable=False, server_default=func.now()),
        Column('updated_at', DateTime(timezone=True), nullable=False, server_default=func.now()),
        UniqueConstraint('actor_id', 'idempotency_key', name='uq_order_create_attempt_actor_key'),
    )


@pytest.fixture
async def session_factory(tmp_path):
    """真实 SQLite 会话工厂（真实 ORM 表 + 幂等登记影子表）。"""
    engine = create_async_engine(f'sqlite+aiosqlite:///{tmp_path / "order_idempotency.db"}')
    needed = {'order', 'order_item', 'inventory_log', 'product', 'user'}
    tables = [t for t in Base.metadata.sorted_tables if t.name in needed]
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all, tables=tables)
        await conn.run_sync(_attempt_shadow_table().create)
    try:
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()


def _make_fake_create_order(calls: list[dict]):
    """语句级替身：模拟真实 create_order 的两条写语句（头单 + 需求流水）。"""

    async def _fake_create_order(db, *, product_id, quantity, customer, note, current_user):
        calls.append({
            'product_id': product_id, 'quantity': quantity,
            'customer': customer, 'note': note,
        })
        order = Order(
            order_no=f'ORD-IDEM-{len(calls)}',
            customer=customer,
            product_id=product_id,
            quantity=quantity,
            note=note,
            order_date=datetime.now(UTC),
        )
        db.add(order)
        await db.flush()
        db.add(InventoryLog(
            product_id=product_id,
            change_type='订单',
            change_quantity=quantity,
            related_id=order.order_no,
            note=f'订单：{order.order_no}',
        ))
        await db.flush()
        return {'id': order.id, 'order_no': order.order_no}

    return _fake_create_order


@pytest.fixture
async def product_id(session_factory):
    async with session_factory() as db:
        product = Product(name='幂等测试产品', barcode='IDEM-BAR-1', initial_stock=0, current_stock=0)
        db.add(product)
        await db.commit()
        return product.id


@pytest.fixture
def user():
    """端点里 user 只用到 id（锁/登记）与工厂隔离字段（本文件已替身掉）。"""
    return SimpleNamespace(id=7, factory=None, is_super=True)


@pytest.fixture
def endpoint(monkeypatch):
    """装好替身与锁记录的端点模块。

    返回 (module, state)。``state['calls']`` 是真实下单替身被调用的次数；
    ``state['events']`` 记录锁/查重放的先后顺序。
    """
    from fastapi_app.api.v1.endpoints import order as order_endpoint

    state: dict = {'calls': [], 'events': [], 'lock_keys': []}
    monkeypatch.setattr(
        order_endpoint.order_service, 'create_order', _make_fake_create_order(state['calls']),
    )

    async def _noop_factory_scope(*args, **kwargs):
        return None

    async def _noop_invalidate():
        return None

    async def _record_lock(_db, lock_key):
        state['events'].append('lock')
        state['lock_keys'].append(lock_key)
        return None

    monkeypatch.setattr(order_endpoint, 'assert_product_factory_scoped', _noop_factory_scope)
    monkeypatch.setattr(order_endpoint.cache_mgr, 'invalidate_dashboard', _noop_invalidate)
    # SQLite 没有 pg_advisory_xact_lock（抛 OperationalError 而非被吞的 ProgrammingError），
    # 这里替身只记录锁键；锁键推导由 test_key_lock_uses_actor_scoped_advisory_key 断言。
    monkeypatch.setattr(oi, 'acquire_advisory_lock_async', _record_lock)

    original_load_replay = oi.load_replay

    async def _spy_load_replay(*args, **kwargs):
        state['events'].append('replay')
        return await original_load_replay(*args, **kwargs)

    monkeypatch.setattr(oi, 'load_replay', _spy_load_replay)
    return order_endpoint, state


async def _count(db, model) -> int:
    return int((await db.execute(select(func.count()).select_from(model))).scalar_one())


async def test_shadow_table_columns_match_model() -> None:
    """影子表列集合必须与 ORM 模型一致（防止测试库与生产结构漂移）。"""
    shadow = _attempt_shadow_table()
    model_columns = {col.name for col in OrderCreateAttempt.__table__.columns}
    assert {col.name for col in shadow.columns} == model_columns
    constraint_names = {
        constraint.name for constraint in shadow.constraints if isinstance(constraint, UniqueConstraint)
    }
    assert constraint_names == {'uq_order_create_attempt_actor_key'}


async def test_same_key_same_payload_creates_one_order_then_replays(
    session_factory, endpoint, product_id, user,
) -> None:
    """同 actor + 同键 + 同内容连续两次：只一张单、一条流水，第二次重放。"""
    order_endpoint, state = endpoint

    async with session_factory() as db:
        first = await order_endpoint.create_order(
            data=OrderCreate(product_id=product_id, quantity=7, customer='幂等客户', note=None),
            idempotency_key=KEY, db=db, user=user,
        )
        assert first.success is True
        assert first.message == '订单添加成功！'
        assert len(state['calls']) == 1
        assert await _count(db, Order) == 1
        assert await _count(db, InventoryLog) == 1
        assert await _count(db, OrderCreateAttempt) == 1

        second = await order_endpoint.create_order(
            data=OrderCreate(product_id=product_id, quantity=7, customer='幂等客户', note=None),
            idempotency_key=KEY, db=db, user=user,
        )

        # 第二次：success 仍为真，但文案是重放提示；且**没有**再下单
        assert second.success is True
        assert second.message == oi.REPLAY_MESSAGE
        assert len(state['calls']) == 1
        assert await _count(db, Order) == 1
        assert await _count(db, InventoryLog) == 1
        assert await _count(db, OrderCreateAttempt) == 1

    # 两次请求都先取锁、再查重放（顺序即并发正确性的前提）
    assert state['events'] == ['lock', 'replay', 'lock', 'replay']


async def test_same_key_different_payload_returns_409(
    session_factory, endpoint, product_id, user,
) -> None:
    """同键不同内容 → 409（不能把首次结果张冠李戴地返回）。"""
    from fastapi import HTTPException

    order_endpoint, state = endpoint

    async with session_factory() as db:
        await order_endpoint.create_order(
            data=OrderCreate(product_id=product_id, quantity=7, customer='幂等客户', note=None),
            idempotency_key=KEY, db=db, user=user,
        )
        with pytest.raises(HTTPException) as exc_info:
            await order_endpoint.create_order(
                data=OrderCreate(product_id=product_id, quantity=8, customer='幂等客户', note=None),
                idempotency_key=KEY, db=db, user=user,
            )
        # db_transaction 的 AppError 分支：ConflictError(409) 必须原样映射成 409 而非 400
        assert exc_info.value.status_code == 409
        assert '幂等键' in str(exc_info.value.detail)
        # 内容冲突不得建单，也不得覆盖首次结果
        assert len(state['calls']) == 1
        assert await _count(db, Order) == 1
        attempt = (await db.execute(select(OrderCreateAttempt))).scalar_one()
        assert attempt.request_hash == oi.request_hash(product_id, 7, '幂等客户', None)


async def test_without_key_behaviour_unchanged(session_factory, endpoint, product_id, user) -> None:
    """不带幂等键：每次都是新单（旧行为逐字保留），且不写任何登记行。"""
    order_endpoint, state = endpoint

    async with session_factory() as db:
        for _ in range(2):
            response = await order_endpoint.create_order(
                data=OrderCreate(product_id=product_id, quantity=3, customer='无键客户', note=''),
                idempotency_key=None, db=db, user=user,
            )
            assert response.success is True
            assert response.message == '订单添加成功！'
        assert len(state['calls']) == 2
        assert await _count(db, Order) == 2
        assert await _count(db, InventoryLog) == 2
        assert await _count(db, OrderCreateAttempt) == 0
    # 无键时既不取锁也不查重放（零额外开销）
    assert state['events'] == []


async def test_same_key_other_actor_is_independent(
    session_factory, endpoint, product_id, user,
) -> None:
    """唯一约束按 actor 划分：别人用同一把键不会被我「重放」成我的单。"""
    order_endpoint, state = endpoint
    other_user = SimpleNamespace(id=8, factory=None, is_super=True)

    async with session_factory() as db:
        await order_endpoint.create_order(
            data=OrderCreate(product_id=product_id, quantity=7, customer='幂等客户', note=None),
            idempotency_key=KEY, db=db, user=user,
        )
        other = await order_endpoint.create_order(
            data=OrderCreate(product_id=product_id, quantity=7, customer='幂等客户', note=None),
            idempotency_key=KEY, db=db, user=other_user,
        )
        assert other.message == '订单添加成功！'
        assert len(state['calls']) == 2
        assert await _count(db, Order) == 2
        assert await _count(db, OrderCreateAttempt) == 2


@pytest.mark.parametrize('bad_key', ['short', 'a' * 65, 'bad key with space', 'bad/key', ''])
async def test_invalid_key_rejected_with_4xx_before_any_write(
    session_factory, endpoint, product_id, user, bad_key,
) -> None:
    """非法键（长度/字符集）→ 4xx，且不建单、不登记、不取锁。"""
    order_endpoint, state = endpoint

    async with session_factory() as db:
        with pytest.raises(BusinessError) as exc_info:
            await order_endpoint.create_order(
                data=OrderCreate(product_id=product_id, quantity=7, customer='幂等客户', note=None),
                idempotency_key=bad_key, db=db, user=user,
            )
        assert exc_info.value.status_code == 400
        assert await _count(db, Order) == 0
        assert await _count(db, OrderCreateAttempt) == 0
    assert state['calls'] == []
    assert state['events'] == []


async def test_valid_key_accepts_documented_charset() -> None:
    """允许的字符集 [A-Za-z0-9._:-] 与 8..64 长度边界。"""
    assert oi.validate_key(None) is None
    assert oi.validate_key('abcd1234') == 'abcd1234'
    assert oi.validate_key('a' * 64) == 'a' * 64
    assert oi.validate_key('A.b_c-d:e123') == 'A.b_c-d:e123'
    with pytest.raises(BusinessError):
        oi.validate_key('a' * 7)
    with pytest.raises(BusinessError):
        oi.validate_key('a' * 65)


async def test_key_lock_uses_actor_scoped_advisory_key(monkeypatch) -> None:
    """锁键必须是 ``ORDER_CREATE_KEY`` + ``{actor_id}:{key}``（同键不同人互不阻塞）。"""
    recorded: list[int] = []

    async def _record(_db, lock_key):
        recorded.append(lock_key)

    monkeypatch.setattr(oi, 'acquire_advisory_lock_async', _record)
    await oi.acquire_key_lock(db=None, actor_id=42, key='abc12345')
    assert recorded == [number_lock_key('ORDER_CREATE_KEY', '42:abc12345')]


def test_request_hash_is_order_insensitive_and_normalized() -> None:
    """指纹只看取值：note 的 None/''、两端空白、调用方参数顺序都不该改变指纹。"""
    base = oi.request_hash(5, 10, '客户A', None)
    assert base == oi.request_hash(5, 10, ' 客户A ', '')
    assert base == oi.request_hash(product_id=5, quantity=10, customer='客户A', note=None)
    assert base != oi.request_hash(5, 11, '客户A', None)
    assert base != oi.request_hash(6, 10, '客户A', None)
    assert base != oi.request_hash(5, 10, '客户A', '备注')


async def test_unsuccessful_first_attempt_allows_retry(session_factory) -> None:
    """首次登记里 success 不为真（历史/半成品行）时放行重做，而不是返回假成功。"""
    async with session_factory() as db:
        db.add(OrderCreateAttempt(
            actor_id=7, idempotency_key=KEY,
            request_hash=oi.request_hash(5, 10, '客户A', None),
            response_body={'success': False, 'message': '下单失败'},
        ))
        await db.commit()
        assert await oi.load_replay(db, 7, KEY, oi.request_hash(5, 10, '客户A', None)) is None
