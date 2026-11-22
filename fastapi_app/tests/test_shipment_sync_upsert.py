"""H-6：出货同步 INSERT 必须在同号竞态下原子 upsert。"""
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

pytestmark = pytest.mark.integration

_IDEM_NO = 'UPSERT-IDEM-001'
_RACE_NO = 'UPSERT-RACE-001'
_RACE_CREATED_AT = datetime(2020, 1, 2, 3, 4, 5, tzinfo=UTC)


def _cleanup(engine, shipment_no: str) -> None:
    customer_name = f'{shipment_no} 客户'
    barcode = f'{shipment_no}-P1'
    with sessionmaker(bind=engine)() as session:
        session.execute(
            text('DELETE FROM shipment_records WHERE shipment_no = :no'),
            {'no': shipment_no},
        )
        session.execute(
            text('DELETE FROM stock_out WHERE stockout_no = :no'),
            {'no': shipment_no},
        )
        session.execute(
            text('DELETE FROM customer WHERE name = :name'),
            {'name': customer_name},
        )
        session.execute(
            text('DELETE FROM product WHERE barcode = :barcode'),
            {'barcode': barcode},
        )
        session.commit()


@pytest.fixture(scope='module')
def pg_engine():
    from fastapi_app.tests._test_db_guard import resolve_test_db_url

    url = resolve_test_db_url().replace('+asyncpg', '+psycopg')
    engine = create_engine(url, poolclass=NullPool)
    with engine.connect() as conn:
        conn.execute(text('SELECT 1'))
    try:
        yield engine
        for shipment_no in (_IDEM_NO, _RACE_NO):
            _cleanup(engine, shipment_no)
    finally:
        engine.dispose()


def _seed_stockout(engine, shipment_no: str, quantity: int, returned: int) -> dict:
    from fastapi_app.core.business_time import business_today

    _cleanup(engine, shipment_no)
    target = business_today()
    customer_name = f'{shipment_no} 客户'
    product_name = f'{shipment_no} 产品'
    barcode = f'{shipment_no}-P1'
    stockout_date = datetime(
        target.year, target.month, target.day, 12, 0,
        tzinfo=ZoneInfo('Asia/Shanghai'),
    )
    with sessionmaker(bind=engine)() as session:
        customer_id = session.execute(
            text('INSERT INTO customer (name, status) VALUES (:name, TRUE) RETURNING id'),
            {'name': customer_name},
        ).scalar_one()
        product_id = session.execute(
            text(
                'INSERT INTO product (name, barcode, current_stock, initial_stock) '
                'VALUES (:name, :barcode, 0, 0) RETURNING id'
            ),
            {'name': product_name, 'barcode': barcode},
        ).scalar_one()
        stockout_id = session.execute(
            text('''
                INSERT INTO stock_out (
                    stockout_no, product_id, quantity, returned_quantity,
                    customer, stockout_date
                ) VALUES (
                    :no, :product_id, :quantity, :returned, :customer, :stockout_date
                ) RETURNING id
            '''),
            {
                'no': shipment_no,
                'product_id': product_id,
                'quantity': quantity,
                'returned': returned,
                'customer': customer_name,
                'stockout_date': stockout_date,
            },
        ).scalar_one()
        session.commit()
    return {
        'target': target,
        'customer_map': {customer_name: customer_id},
        'customer_id': customer_id,
        'product_id': product_id,
        'stockout_id': stockout_id,
    }


def _fetch_shipment(session, shipment_no: str):
    return session.execute(
        text('''
            SELECT customer_id, customer_name, product_id, product_name, quantity,
                   shipment_date, source_type, source_id, created_at, synced_at
            FROM shipment_records WHERE shipment_no = :no
        '''),
        {'no': shipment_no},
    ).mappings().one()


class _RaceSession:
    """在旧 ORM add 或新 SQL INSERT 前，先由独立事务写入同号记录。"""

    def __init__(self, session, engine, competitor: dict):
        self._session = session
        self._engine = engine
        self._competitor = competitor
        self._inserted = False

    def _insert_competitor(self) -> None:
        if self._inserted:
            return
        self._inserted = True
        with sessionmaker(bind=self._engine)() as competitor:
            competitor.execute(
                text('''
                    INSERT INTO shipment_records (
                        shipment_no, customer_id, customer_name,
                        product_id, product_name, quantity, shipment_date,
                        source_type, source_id, created_at, synced_at
                    ) VALUES (
                        :shipment_no, :customer_id, :customer_name,
                        :product_id, :product_name, :quantity, :shipment_date,
                        :source_type, :source_id, :created_at, :synced_at
                    )
                '''),
                self._competitor,
            )
            competitor.commit()

    def execute(self, statement, params=None, **kwargs):
        normalized = ' '.join(str(statement).split()).lower()
        if normalized.startswith('insert into shipment_records'):
            self._insert_competitor()
        return self._session.execute(statement, params, **kwargs)

    def add(self, instance) -> None:
        self._insert_competitor()
        self._session.add(instance)

    def __getattr__(self, name):
        return getattr(self._session, name)


def test_repeated_sync_is_idempotent_and_uses_net_quantity(pg_engine):
    from fastapi_app.tasks.plan_tasks import _sync_one_date

    seed = _seed_stockout(pg_engine, _IDEM_NO, quantity=12, returned=3)
    with sessionmaker(bind=pg_engine)() as session:
        first = _sync_one_date(session, seed['target'], seed['customer_map'])
        session.commit()
        created = _fetch_shipment(session, _IDEM_NO)

        second = _sync_one_date(session, seed['target'], seed['customer_map'])
        session.commit()
        repeated = _fetch_shipment(session, _IDEM_NO)
        count = session.execute(
            text('SELECT COUNT(*) FROM shipment_records WHERE shipment_no = :no'),
            {'no': _IDEM_NO},
        ).scalar_one()

    assert (first, second) == (1, 1)
    assert count == 1
    assert created['quantity'] == 9
    assert repeated['quantity'] == 9
    assert created['source_type'] == 'stockout'
    assert created['source_id'] == seed['stockout_id']
    assert created['created_at'] is not None
    assert created['synced_at'] is not None
    assert repeated['created_at'] == created['created_at']
    assert repeated['source_id'] == created['source_id']


def test_select_miss_then_existing_row_uses_atomic_upsert(pg_engine):
    from fastapi_app.tasks.plan_tasks import _sync_one_date

    seed = _seed_stockout(pg_engine, _RACE_NO, quantity=10, returned=2)
    competitor = {
        'shipment_no': _RACE_NO,
        'customer_id': seed['customer_id'],
        'customer_name': '竞态先写客户',
        'product_id': seed['product_id'],
        'product_name': '竞态先写产品',
        'quantity': 999,
        'shipment_date': seed['target'],
        'source_type': 'catchup',
        'source_id': 987654,
        'created_at': _RACE_CREATED_AT,
        'synced_at': _RACE_CREATED_AT,
    }
    with sessionmaker(bind=pg_engine)() as session:
        race_session = _RaceSession(session, pg_engine, competitor)
        synced = _sync_one_date(race_session, seed['target'], seed['customer_map'])
        race_session.commit()
        saved = _fetch_shipment(session, _RACE_NO)

    assert synced == 1
    assert saved['quantity'] == 8
    assert saved['source_type'] == 'catchup'
    assert saved['source_id'] == 987654
    assert saved['created_at'] == _RACE_CREATED_AT
    assert saved['synced_at'] > _RACE_CREATED_AT
