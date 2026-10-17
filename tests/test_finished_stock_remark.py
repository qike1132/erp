"""成品库存页备注 UPSERT 测试（真库）

键 (客户,产品,批次) 一行一条；空批次 = batch_no 空串；内容清空即删行。
"""
import sqlalchemy as sa

from fastapi_app.services import finished_stock_service as fss
from fastapi_app.shared_models import DailyProductionRecord, FinishedStockRemark, Product

_SEQ = 0


def _uniq(prefix: str) -> str:
    global _SEQ
    _SEQ += 1
    return f'{prefix}-{_SEQ}'


async def _mk_product(db) -> Product:
    p = Product(name=_uniq('RM-P'), barcode=_uniq('RM-B'), current_stock=0, initial_stock=0)
    db.add(p)
    await db.flush()
    return p


async def _mk_prod(db, *, product_id: int, qty: int, batch_no: str, product_name: str) -> None:
    """一条包装部生产记录（让 summary 里出现该产品行）。"""
    from datetime import date
    db.add(DailyProductionRecord(
        department='packaging', product_id=product_id, product_name=product_name,
        barcode='', unit_price=0, quantity=qty, production_date=date(2026, 10, 15),
        batch_no=batch_no, customer_name='C',
    ))
    await db.flush()


async def _rows(db, product_id: int) -> list:
    return list((await db.execute(sa.select(FinishedStockRemark).where(
        FinishedStockRemark.product_id == product_id
    ))).scalars().all())


async def _count(db, product_id: int) -> int:
    return (await db.execute(sa.select(sa.func.count()).select_from(FinishedStockRemark).where(
        FinishedStockRemark.product_id == product_id
    ))).scalar() or 0


async def test_upsert_then_read_back_via_summary(async_db_session):
    db = async_db_session
    p = await _mk_product(db)
    name = _uniq('REMARK')
    await _mk_prod(db, product_id=p.id, qty=100, batch_no='RM1', product_name=name)

    res = await fss.get_finished_stock_summary(db, product_search=name)
    row = res['data'][0]
    assert row['remark'] == ''

    await fss.upsert_remark(db, customer_name=row['customer_name'], product_id=p.id, batch_no='RM1', remark='整批没问题')
    await db.flush()
    res2 = await fss.get_finished_stock_summary(db, product_search=name)
    assert res2['data'][0]['remark'] == '整批没问题'


async def test_upsert_updates_same_row_not_duplicate(async_db_session):
    """同一键重复写只更新一行（唯一约束兜底），不产生第二行。"""
    db = async_db_session
    p = await _mk_product(db)
    await fss.upsert_remark(db, customer_name='C', product_id=p.id, batch_no='', remark='一稿')
    await fss.upsert_remark(db, customer_name='C', product_id=p.id, batch_no='', remark='二稿')
    await db.flush()
    rows = await _rows(db, p.id)
    assert len(rows) == 1
    assert rows[0].remark == '二稿'


async def test_empty_batch_key_distinct_from_real_batch(async_db_session):
    """未分批次(空串)与真实批次是两个不同的备注键，互不覆盖。"""
    db = async_db_session
    p = await _mk_product(db)
    await fss.upsert_remark(db, customer_name='C', product_id=p.id, batch_no='', remark='无批次备注')
    await fss.upsert_remark(db, customer_name='C', product_id=p.id, batch_no='B1', remark='有批次备注')
    await db.flush()
    rows = await _rows(db, p.id)
    by_batch = {r.batch_no: r.remark for r in rows}
    assert by_batch == {'': '无批次备注', 'B1': '有批次备注'}


async def test_remark_survives_customer_display_collapse(async_db_session):
    """回归：批次先单客户 A 写备注，后新增客户 B 使展示值塌成 ''，备注不得失联。

    备注键只含 (产品,批次)——客户是派生展示值，会随批次客户构成抖动。
    """
    db = async_db_session
    p = await _mk_product(db)
    name = _uniq('RM-COLLAPSE')
    await _mk_prod(db, product_id=p.id, qty=100, batch_no='RMX', product_name=name)

    res = await fss.get_finished_stock_summary(db, product_search=name)
    row = res['data'][0]
    assert row['customer_name'] == 'C'

    await fss.upsert_remark(db, customer_name=row['customer_name'], product_id=p.id, batch_no='RMX', remark='单客户期备注')
    await db.flush()

    # 同一批次新增另一个客户的入库行 → display_cust 塌成 ''
    await _mk_prod(db, product_id=p.id, qty=50, batch_no='RMX', product_name=name)
    # _mk_prod 写死 customer_name='C'，此处手工补一条 D 客户行
    from datetime import date
    db.add(DailyProductionRecord(
        department='packaging', product_id=p.id, product_name=name,
        barcode='', unit_price=0, quantity=50, production_date=date(2026, 10, 15),
        batch_no='RMX', customer_name='D',
    ))
    await db.flush()

    res2 = await fss.get_finished_stock_summary(db, product_search=name)
    assert res2['data'][0]['customer_name'] == ''
    assert res2['data'][0]['remark'] == '单客户期备注'

    # 塌缩后再写一次备注，仍只更新同一行，不产生孤儿
    await fss.upsert_remark(db, customer_name='', product_id=p.id, batch_no='RMX', remark='塌缩后备注')
    await db.flush()
    rows = await _rows(db, p.id)
    assert len(rows) == 1
    assert rows[0].remark == '塌缩后备注'


async def test_clear_remark_deletes_row(async_db_session):
    """内容清空即删除该行（不留空行）。"""
    db = async_db_session
    p = await _mk_product(db)
    await fss.upsert_remark(db, customer_name='C', product_id=p.id, batch_no='', remark='先写点')
    await fss.upsert_remark(db, customer_name='C', product_id=p.id, batch_no='', remark='')
    await db.flush()
    assert await _count(db, p.id) == 0
