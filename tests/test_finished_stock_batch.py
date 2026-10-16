"""成品库存（批次级）— 聚合口径与批次扣减测试（真库）

真值来源：daily_production_record(department='packaging') 入库
        + stock_out(批次) 出货扣减。与 /stock 的库存结余同源。
"""
from datetime import UTC, date, datetime

import pytest

from fastapi_app.services import finished_stock_service as fss
from fastapi_app.shared_models import DailyProductionRecord, Product, StockOut

SEQ = 0


def _uniq(prefix: str) -> str:
    global SEQ
    SEQ += 1
    return f'{prefix}-{SEQ}'


async def _mk_product(db, name=None, barcode=None) -> Product:
    p = Product(name=name or _uniq('FS-P'), barcode=barcode or _uniq('FS-B'),
                current_stock=0, initial_stock=0)
    db.add(p)
    await db.flush()
    return p


async def _mk_prod(db, *, product_id, qty, batch_no=None, customer_name=None,
                   dept='packaging', d=date(2026, 10, 15),
                   is_custom=False, country=None, product_name=None) -> DailyProductionRecord:
    r = DailyProductionRecord(
        department=dept, product_id=product_id, product_name=product_name or _uniq('成品'),
        barcode='', unit_price=0, quantity=qty, production_date=d,
        batch_no=batch_no, customer_name=customer_name,
        is_custom=is_custom, custom_country=country,
    )
    db.add(r)
    await db.flush()
    return r


async def _mk_stockout(db, *, product_id, qty, batch_no=None, returned=0,
                       stockin_id=None, customer='客户A') -> StockOut:
    so = StockOut(
        stockout_no=_uniq('SO'), product_id=product_id, quantity=qty,
        returned_quantity=returned, customer=customer, batch_no=batch_no,
        stockin_id=stockin_id, stockout_date=datetime.now(UTC),
    )
    db.add(so)
    await db.flush()
    return so


async def _rows(db, **kw):
    res = await fss.get_finished_stock_summary(db, **kw)
    return res['data']


async def test_summary_aggregates_by_batch(async_db_session):
    db = async_db_session
    p = await _mk_product(db)
    await _mk_prod(db, product_id=p.id, qty=100, batch_no='0464628801', customer_name='网易')
    await _mk_prod(db, product_id=p.id, qty=50, batch_no='0464629101', customer_name='网易')

    rows = [r for r in await _rows(db) if r['product_id'] == p.id]
    by_batch = {r['batch_no']: r for r in rows}
    assert by_batch['0464628801']['batch_in_qty'] == 100
    assert by_batch['0464628801']['batch_available'] == 100
    assert by_batch['0464629101']['batch_in_qty'] == 50
    assert by_batch['0464629101']['batch_available'] == 50


async def test_batch_available_deducted_by_stockout(async_db_session):
    db = async_db_session
    p = await _mk_product(db)
    await _mk_prod(db, product_id=p.id, qty=100, batch_no='B100')
    await _mk_stockout(db, product_id=p.id, qty=30, batch_no='B100')

    rows = [r for r in await _rows(db) if r['product_id'] == p.id]
    row = next(r for r in rows if r['batch_no'] == 'B100')
    assert row['batch_in_qty'] == 100
    assert row['batch_available'] == 70
    assert await fss.get_batch_available(db, p.id, 'B100') == 70


async def test_stockin_deduction_rows_excluded(async_db_session):
    """stockin_id 非空的备货抵扣行不占成品批次库存（不参与批次可用量扣减）。"""
    from fastapi_app.shared_models import StockIn
    db = async_db_session
    p = await _mk_product(db)
    await _mk_prod(db, product_id=p.id, qty=100, batch_no='B200')
    si = StockIn(stockin_no=_uniq('SI'), customer='客户A', product_id=p.id, quantity=500)
    db.add(si)
    await db.flush()
    # 抵扣行（stockin_id 非空）——应被批次可用量口径排除
    await _mk_stockout(db, product_id=p.id, qty=999, batch_no='B200', stockin_id=si.id)

    rows = [r for r in await _rows(db) if r['product_id'] == p.id]
    row = next(r for r in rows if r['batch_no'] == 'B200')
    assert row['batch_available'] == 100   # 抵扣行未扣减批次可用
    assert await fss.get_batch_available(db, p.id, 'B200') == 100


async def test_returned_quantity_refunds_batch(async_db_session):
    db = async_db_session
    p = await _mk_product(db)
    await _mk_prod(db, product_id=p.id, qty=100, batch_no='B300')
    await _mk_stockout(db, product_id=p.id, qty=30, returned=10, batch_no='B300')
    # 净出货 20 → 可用 80
    assert await fss.get_batch_available(db, p.id, 'B300') == 80


async def test_null_batch_and_customer_buckets(async_db_session):
    db = async_db_session
    p = await _mk_product(db)
    await _mk_prod(db, product_id=p.id, qty=60, batch_no=None, customer_name=None)
    rows = [r for r in await _rows(db) if r['product_id'] == p.id]
    row = rows[0]
    assert row['batch_no'] == ''          # 未分批次
    assert row['customer_name'] == ''     # 未指定客户
    assert row['batch_available'] == 60


async def test_unbatched_stockout_deducts_unbatched_bucket(async_db_session):
    """无批次出货必须落进 ''（未分批次）桶扣减——否则该桶只减入库不减出货、可用量虚高。"""
    db = async_db_session
    p = await _mk_product(db)
    await _mk_prod(db, product_id=p.id, qty=100, batch_no=None)
    await _mk_stockout(db, product_id=p.id, qty=40, batch_no=None)
    rows = [r for r in await _rows(db) if r['product_id'] == p.id]
    assert len(rows) == 1
    assert rows[0]['batch_no'] == ''
    assert rows[0]['batch_available'] == 60


async def test_product_id_null_excluded(async_db_session):
    """product_id 为 NULL 的生产记录不进成品库存（与 _apply_production_stock 一致）。"""
    db = async_db_session
    before = await _rows(db)
    await _mk_prod(db, product_id=None, qty=777, batch_no='B-NULL')
    after = await _rows(db)
    # 行数不变（product_id 为空的被 WHERE 过滤）
    assert len(after) == len(before)


async def test_non_packaging_department_excluded(async_db_session):
    db = async_db_session
    p = await _mk_product(db)
    await _mk_prod(db, product_id=p.id, qty=88, batch_no='B-FILL', dept='filling')
    rows = [r for r in await _rows(db) if r['product_id'] == p.id]
    assert rows == []


async def test_is_custom_aggregated(async_db_session):
    db = async_db_session
    p = await _mk_product(db)
    await _mk_prod(db, product_id=p.id, qty=10, batch_no='BC', is_custom=True, country='美国')
    rows = [r for r in await _rows(db) if r['product_id'] == p.id]
    assert rows[0]['is_custom'] is True
    assert rows[0]['custom_country'] == '美国'


async def test_batches_by_product_sorted(async_db_session):
    db = async_db_session
    p = await _mk_product(db)
    await _mk_prod(db, product_id=p.id, qty=1, batch_no='0464629101')
    await _mk_prod(db, product_id=p.id, qty=1, batch_no='0464628801')
    batches = await fss.get_batches_by_product(db, p.id)
    assert [b['batch_no'] for b in batches] == ['0464628801', '0464629101']


async def test_batches_by_product_excludes_empty_batch(async_db_session):
    """未分批次（batch_no 空）不可选，不进批次下拉。"""
    db = async_db_session
    p = await _mk_product(db)
    await _mk_prod(db, product_id=p.id, qty=5, batch_no=None)
    await _mk_prod(db, product_id=p.id, qty=5, batch_no='B1')
    batches = await fss.get_batches_by_product(db, p.id)
    assert [b['batch_no'] for b in batches] == ['B1']


async def test_same_batch_two_customers_no_double_deduct(async_db_session):
    """同一 (产品,批次) 有两个客户的入库行时，出货只扣一次（不按客户拆行）。"""
    db = async_db_session
    p = await _mk_product(db)
    await _mk_prod(db, product_id=p.id, qty=100, batch_no='B9', customer_name='甲')
    await _mk_prod(db, product_id=p.id, qty=60, batch_no='B9', customer_name='乙')
    await _mk_stockout(db, product_id=p.id, qty=40, batch_no='B9', customer='甲')
    rows = [r for r in await _rows(db) if r['product_id'] == p.id]
    assert len(rows) == 1                      # 同一批次并成一行
    assert rows[0]['batch_in_qty'] == 160
    assert rows[0]['batch_available'] == 120   # 只扣一次 40
    assert rows[0]['customer_name'] == ''      # 跨客户 → 未指定


async def test_total_available_is_global_not_page(async_db_session):
    """total_available 是过滤后全量合计，不是当前页求和（翻页/筛选时数字不应跳动）。"""
    db = async_db_session
    p = await _mk_product(db)
    name = _uniq('TOT')
    await _mk_prod(db, product_id=p.id, qty=100, batch_no='TA1', product_name=name)
    await _mk_prod(db, product_id=p.id, qty=50, batch_no='TA2', product_name=name)
    res = await fss.get_finished_stock_summary(db, product_search=name, per_page=1)
    assert res['total'] == 2
    assert len(res['data']) == 1          # 本页只 1 行
    assert res['total_available'] == 150  # 但合计是全量


# ==================== 定制校验（纯逻辑） ====================

def test_validate_custom_requires_country():
    from fastapi_app.services.daily_production_service import _validate_custom
    with pytest.raises(ValueError):
        _validate_custom(True, '')
    with pytest.raises(ValueError):
        _validate_custom(True, '   ')
    _validate_custom(True, '美国')   # 通过
    _validate_custom(False, None)    # 通过
