"""手工出入库请求级幂等（审计 M-03 回归）。

拦哪种错：手工 /in/create、/out/create 原先无幂等令牌，网络超时重发或双击
会落两套记录并双扣/双加库存。本测试在真实测试库上锁定：
同一 request_id 的第二次提交必须被拒，且只留下一条记录 + 一条流水。
"""
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from fastapi_app.core.exceptions import ConflictError, db_transaction
from fastapi_app.services import stock_in_service, stock_out_service
from fastapi_app.shared_models import (
    DailyProductionRecord,
    InventoryLog,
    Order,
    Product,
    StockIn,
    StockOut,
)

pytestmark = pytest.mark.integration

CUSTOMER = '幂等测试客户'


@pytest_asyncio.fixture
async def db(test_engine):
    factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False, autoflush=False,
    )
    async with factory() as session:
        async with session.begin() as transaction:
            yield session
            await transaction.rollback()


@pytest_asyncio.fixture
async def product(db):
    p = Product(name='幂等测试产品', barcode='IDEM-001', current_stock=0, initial_stock=0)
    db.add(p)
    await db.flush()
    return p


async def test_stockin_same_request_id_writes_once(db, product, monkeypatch):
    monkeypatch.setattr(
        'fastapi_app.services.stock_service.generate_stockin_number',
        AsyncMock(return_value='BH-IDEM-001'),
    )
    await stock_in_service.create_stockin_core(
        db, product.id, 5, CUSTOMER, datetime.now(UTC), '', request_id='req-in-1',
    )
    with pytest.raises(ConflictError, match='重复提交'):
        await stock_in_service.create_stockin_core(
            db, product.id, 5, CUSTOMER, datetime.now(UTC), '', request_id='req-in-1',
        )

    stockins = (await db.execute(
        select(func.count()).select_from(StockIn).where(StockIn.product_id == product.id)
    )).scalar_one()
    logs = (await db.execute(
        select(func.count()).select_from(InventoryLog).where(
            InventoryLog.idem_key == 'req-in-1',
        )
    )).scalar_one()
    assert stockins == 1
    assert logs == 1


async def test_stockout_same_request_id_writes_once(db, product, monkeypatch):
    monkeypatch.setattr(
        'fastapi_app.services.stock_service.generate_stockout_number',
        AsyncMock(return_value='SO-IDEM-001'),
    )
    product.current_stock = 100
    db.add(DailyProductionRecord(
        department='packaging', product_id=product.id,
        product_name=product.name, barcode='IDEM-001',
        quantity=100, production_date=datetime.now(UTC).date(),
    ))
    db.add(Order(
        order_no='IDEM-ORD-1', customer=CUSTOMER, product_id=product.id,
        quantity=50, order_date=datetime.now(UTC), status='待备货',
    ))
    await db.flush()

    await stock_out_service.create_stockout_core(
        db, product.id, 10, CUSTOMER, datetime.now(UTC), '', request_id='req-out-1',
    )
    with pytest.raises(ConflictError, match='重复提交'):
        await stock_out_service.create_stockout_core(
            db, product.id, 10, CUSTOMER, datetime.now(UTC), '', request_id='req-out-1',
        )

    stockouts = (await db.execute(
        select(func.count()).select_from(StockOut).where(StockOut.product_id == product.id)
    )).scalar_one()
    logs = (await db.execute(
        select(func.count()).select_from(InventoryLog).where(
            InventoryLog.idem_key == 'req-out-1',
        )
    )).scalar_one()
    assert stockouts == 1
    assert logs == 1


def test_batch_item_models_preserve_request_id():
    """H-2：Pydantic 模型必须保留 request_id，否则 API 边界会静默丢弃令牌。"""
    from fastapi_app.api.v1.endpoints.auxiliary import BatchStockInItem, BatchStockOutItem

    common = {'product_id': 1, 'customer': CUSTOMER, 'quantity': 1}
    assert BatchStockInItem(**common, request_id='in-token').model_dump()['request_id'] == 'in-token'
    assert BatchStockOutItem(**common, request_id='out-token').model_dump()['request_id'] == 'out-token'


async def test_batch_stockin_endpoint_forwards_request_id(monkeypatch):
    from types import SimpleNamespace

    from fastapi_app.api.v1.endpoints import auxiliary as ep
    from fastapi_app.api.v1.endpoints.auxiliary import BatchStockInItem, BatchStockInRequest

    captured: list[dict] = []

    async def fake_gate(db, user, items, **_kwargs):
        return [item.model_dump() for item in items], [0], [None]

    async def fake_orchestrate(db, allowed, operator_id=None):
        captured.extend(allowed)
        return {'results': [{'success': True}]}

    monkeypatch.setattr(ep, '_factory_gate_batch_items', fake_gate)
    monkeypatch.setattr(
        'fastapi_app.services.auxiliary_service.orchestrate_batch_stockins',
        fake_orchestrate,
    )

    data = BatchStockInRequest(stockins=[
        BatchStockInItem(product_id=1, customer=CUSTOMER, quantity=1, request_id='in-token'),
    ])
    await ep.batch_submit_stockins(
        data, user=SimpleNamespace(id=1), db=object(),
    )

    assert captured[0]['request_id'] == 'in-token'


async def test_batch_stockout_endpoint_forwards_request_id(monkeypatch):
    from types import SimpleNamespace

    from fastapi_app.api.v1.endpoints import auxiliary as ep
    from fastapi_app.api.v1.endpoints.auxiliary import BatchStockOutItem, BatchStockOutRequest

    captured: list[dict] = []

    async def fake_gate(db, user, items, **_kwargs):
        return [item.model_dump() for item in items], [0], [None]

    async def fake_orchestrate(db, allowed, operator_id=None):
        captured.extend(allowed)
        return {'results': [{'success': True}]}

    monkeypatch.setattr(ep, '_factory_gate_batch_items', fake_gate)
    monkeypatch.setattr(
        'fastapi_app.services.auxiliary_service.orchestrate_batch_stockouts',
        fake_orchestrate,
    )

    data = BatchStockOutRequest(stockouts=[
        BatchStockOutItem(product_id=1, customer=CUSTOMER, quantity=1, request_id='out-token'),
    ])
    await ep.batch_submit_stockouts(
        data, user=SimpleNamespace(id=1), db=object(),
    )

    assert captured[0]['request_id'] == 'out-token'


async def test_batch_stockin_same_request_id_writes_once(db, product, monkeypatch):
    """前端实际走的 /aux/batch-submit-stockins 也必须幂等。"""
    monkeypatch.setattr(
        'fastapi_app.services.stock_service.generate_stockin_number',
        AsyncMock(return_value='BH-BATCH-001'),
    )
    monkeypatch.setattr(
        'fastapi_app.services.purchase._auto_generate.schedule_auto_generate_purchase_orders',
        MagicMock(),
    )
    row = {
        'product_id': product.id, 'customer': CUSTOMER, 'quantity': 5,
        'stockin_date': '', 'note': '', 'id': 'row-1',
        'request_id': 'batch-in-1',
    }

    first = await stock_in_service.batch_create_stockins(db, [row])
    second = await stock_in_service.batch_create_stockins(db, [row])

    assert first['success'] is True
    assert second['results'][0]['success'] is False
    assert '重复' in second['results'][0]['error']
    stockins = (await db.execute(
        select(func.count()).select_from(StockIn).where(StockIn.product_id == product.id)
    )).scalar_one()
    logs = (await db.execute(
        select(func.count()).select_from(InventoryLog).where(
            InventoryLog.idem_key == 'batch-in-1',
        )
    )).scalar_one()
    assert stockins == 1
    assert logs == 1


async def test_batch_stockout_same_request_id_writes_once(db, product, monkeypatch):
    """前端实际走的 /aux/batch-submit-stockouts 也必须幂等。"""
    monkeypatch.setattr(
        'fastapi_app.services.stock_service.generate_stockout_number',
        AsyncMock(return_value='SO-BATCH-001'),
    )
    product.current_stock = 100
    db.add(DailyProductionRecord(
        department='packaging', product_id=product.id,
        product_name=product.name, barcode='IDEM-001',
        quantity=100, production_date=datetime.now(UTC).date(),
    ))
    db.add(Order(
        order_no='IDEM-BATCH-ORD-1', customer=CUSTOMER, product_id=product.id,
        quantity=50, order_date=datetime.now(UTC), status='待备货',
    ))
    await db.flush()
    row = {
        'product_id': product.id, 'customer': CUSTOMER, 'quantity': 10,
        'stockout_date': '', 'note': '', 'batch_no': '', 'id': 'row-1',
        'request_id': 'batch-out-1',
    }

    first = await stock_out_service.batch_create_stockouts(db, [row])
    second = await stock_out_service.batch_create_stockouts(db, [row])

    assert first['success'] is True
    assert second['results'][0]['success'] is False
    assert '重复' in second['results'][0]['error']
    stockouts = (await db.execute(
        select(func.count()).select_from(StockOut).where(StockOut.product_id == product.id)
    )).scalar_one()
    logs = (await db.execute(
        select(func.count()).select_from(InventoryLog).where(
            InventoryLog.idem_key == 'batch-out-1',
        )
    )).scalar_one()
    assert stockouts == 1
    assert logs == 1


async def test_stockin_unique_conflict_maps_to_conflict_error(db, product, monkeypatch):
    """L-1 并发窗口：预检已通过，写入流水时撞 uq_inventory_log_idem。

    顺序重复由预检拦截；本用例模拟两事务都通过了预检，后提交者必须在
    flush 阶段把数据库唯一冲突转成 ConflictError(409)，而不是裸 IntegrityError(500)。
    """
    db.add(InventoryLog(
        product_id=product.id, change_type='导入', change_quantity=0,
        idem_key='race-in-1',
    ))
    await db.flush()
    # 预检已通过（模拟另一事务尚未提交时的窗口）
    monkeypatch.setattr(
        stock_in_service, 'assert_request_not_processed', AsyncMock(), raising=False,
    )
    monkeypatch.setattr(
        'fastapi_app.services.stock_service.generate_stockin_number',
        AsyncMock(return_value='BH-RACE-001'),
    )

    with pytest.raises(ConflictError, match='重复提交'):
        await stock_in_service.create_stockin_core(
            db, product.id, 5, CUSTOMER, datetime.now(UTC), '',
            request_id='race-in-1',
        )


async def test_stockout_unique_conflict_maps_to_conflict_error(db, product, monkeypatch):
    """L-1 出库侧：预检通过后撞唯一索引，必须转 ConflictError(409)。"""
    product.current_stock = 100
    db.add(DailyProductionRecord(
        department='packaging', product_id=product.id,
        product_name=product.name, barcode='IDEM-001',
        quantity=100, production_date=datetime.now(UTC).date(),
    ))
    db.add(Order(
        order_no='IDEM-RACE-ORD-1', customer=CUSTOMER, product_id=product.id,
        quantity=50, order_date=datetime.now(UTC), status='待备货',
    ))
    await db.flush()
    db.add(InventoryLog(
        product_id=product.id, change_type='导入', change_quantity=0,
        idem_key='race-out-1',
    ))
    await db.flush()
    monkeypatch.setattr(
        stock_out_service, 'assert_request_not_processed', AsyncMock(), raising=False,
    )
    monkeypatch.setattr(
        'fastapi_app.services.stock_service.generate_stockout_number',
        AsyncMock(return_value='SO-RACE-001'),
    )

    with pytest.raises(ConflictError, match='重复提交'):
        await stock_out_service.create_stockout_core(
            db, product.id, 10, CUSTOMER, datetime.now(UTC), '',
            request_id='race-out-1',
        )


async def test_batch_stockout_unique_conflict_raises_conflict_error(db, product, monkeypatch):
    """批量出库无逐行 SAVEPOINT：竞态冲突必须以 409 整批回滚，而不是 500。"""
    product.current_stock = 100
    db.add(DailyProductionRecord(
        department='packaging', product_id=product.id,
        product_name=product.name, barcode='IDEM-001',
        quantity=100, production_date=datetime.now(UTC).date(),
    ))
    db.add(Order(
        order_no='IDEM-BATCH-RACE-1', customer=CUSTOMER, product_id=product.id,
        quantity=50, order_date=datetime.now(UTC), status='待备货',
    ))
    await db.flush()
    db.add(InventoryLog(
        product_id=product.id, change_type='导入', change_quantity=0,
        idem_key='race-batch-out-1',
    ))
    await db.flush()
    monkeypatch.setattr(
        stock_out_service, 'assert_request_not_processed', AsyncMock(), raising=False,
    )
    monkeypatch.setattr(
        'fastapi_app.services.stock_service.generate_stockout_number',
        AsyncMock(return_value='SO-BATCH-RACE-001'),
    )
    row = {
        'product_id': product.id, 'customer': CUSTOMER, 'quantity': 10,
        'stockout_date': '', 'note': '', 'batch_no': '', 'id': 'row-1',
        'request_id': 'race-batch-out-1',
    }

    with pytest.raises(ConflictError, match='重复提交'):
        await stock_out_service.batch_create_stockouts(db, [row])


async def test_conflict_error_maps_to_http_409(test_engine):
    """端点事务层必须把 ConflictError 映射成 HTTP 409。"""
    factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False, autoflush=False,
    )
    async with factory() as session:
        with pytest.raises(HTTPException) as exc_info:
            async with db_transaction(session):
                raise ConflictError('请勿重复提交：该请求已登记过入库')

    assert exc_info.value.status_code == 409
