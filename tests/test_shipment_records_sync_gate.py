"""H-1（2026-10-25 上线前审计）：出货同步 INSERT 必须显式提供 created_at。

生产实证：``shipment_records.created_at`` 只有 Python 侧 default（无
server_default），``plan_tasks._sync_one_date`` 的原生 INSERT 列清单缺
created_at → 首次有行可同步（2026-10-23 起）每行必炸 NotNullViolation，
采购计划模块出货数据断流 3 天（logs/erp-arq.log 每天 41 次失败，窗口内
仅有的"成功"全是 synced_count=0——INSERT 从未真正成功过）。

不直接调 ``sync_shipment_records_task``：模块级 ``_SyncSession`` 在导入期
绑定引擎对象，conftest 的 ``app_on_test_db`` 重定向设置后它仍指向导入时
URL（见 tests/conftest.py）。改用测试库 sync 会话直接调 ``_sync_one_date``
（与 tests/test_plan_import_idempotency_real.py 同款注入法）。
"""
import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
import pytest_asyncio
from conftest import TEST_DATABASE_URL
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import sessionmaker

pytestmark = pytest.mark.integration

_SHIP_NO = 'SYNCGATE-SO-001'
_CUST_NAME = 'SYNCGATE 客户'
_PROD_BARCODE = 'SYNCGATE-P1'


@pytest_asyncio.fixture
async def sync_gate_cleanup(async_db_session):
    """用例结束后清掉本文件造的行（共享测试库只在会话开始时整库重置）。"""
    yield
    from fastapi_app.shared_models import Customer, Product, StockOut
    from fastapi_app.shared_models.purchase_plan import ShipmentRecord

    # 顺序按 FK 依赖：流水 → 出库 → 客户 → 产品
    await async_db_session.execute(
        delete(ShipmentRecord).where(ShipmentRecord.shipment_no == _SHIP_NO))
    await async_db_session.execute(
        delete(StockOut).where(StockOut.stockout_no == _SHIP_NO))
    await async_db_session.execute(
        delete(Customer).where(Customer.name == _CUST_NAME))
    await async_db_session.execute(
        delete(Product).where(Product.barcode == _PROD_BARCODE))
    await async_db_session.commit()


class TestSyncOneDateInsertsCreatedAt:
    async def test_insert_and_idempotent_update(
        self, async_db_session, sync_gate_cleanup,
    ):
        """首次同步 INSERT 必须落行且 created_at 非空；二次同步走 UPDATE 不炸。

        种子走 async 会话（有事件循环）：fifo_allocation._fifo_after_commit 是
        全局 after_commit 监听器，在无线程循环的 sync 会话里 commit StockOut
        会撞 "no running event loop"（2026-10-25 提权全量实测）。生产里
        _sync_one_date 也只在 to_thread 里 commit shipment_records（监听器
        早退，UPDATE 路径每天成功）——同步侧只做与生产同构的事。
        """
        from fastapi_app.core.business_time import business_today
        from fastapi_app.shared_models import Customer, Product, StockOut
        from fastapi_app.shared_models.purchase_plan import ShipmentRecord
        from fastapi_app.tasks.plan_tasks import _sync_one_date

        target = business_today()
        product = Product(
            name='SYNCGATE 产品', barcode=_PROD_BARCODE,
            current_stock=0, initial_stock=0,
        )
        customer = Customer(name=_CUST_NAME)
        async_db_session.add_all([product, customer])
        await async_db_session.flush()
        # 出库时刻取业务日正午（Asia/Shanghai）：_sync_one_date 用
        # ``DATE(stockout_date) = :target_date``（DB 时区日期）过滤，种子若用
        # now(UTC)，在 UTC 16:00–24:00（北京 0:00–8:00）窗口内 DB 的 UTC 日期
        # 会落后业务日一天 → 同步 0 行（2026-10-25 CI 三跑实锤，北京 00:06）。
        # 业务日正午在 UTC 与 +08 两种 DB 时区下 DATE() 都落在 target 当天。
        stockout_dt = datetime(
            target.year, target.month, target.day, 12, 0,
            tzinfo=ZoneInfo('Asia/Shanghai'),
        )
        async_db_session.add(StockOut(
            stockout_no=_SHIP_NO, product_id=product.id,
            quantity=5, customer=_CUST_NAME,
            stockout_date=stockout_dt,
        ))
        await async_db_session.commit()
        cust_map = {_CUST_NAME: customer.id}

        sync_url = TEST_DATABASE_URL.replace('+asyncpg', '+psycopg')

        def _run():
            engine = create_engine(sync_url)
            session = sessionmaker(bind=engine)()
            try:
                first = _sync_one_date(session, target, cust_map)
                session.commit()
                second = _sync_one_date(session, target, cust_map)
                session.commit()
                created = session.execute(
                    select(ShipmentRecord.created_at)
                    .where(ShipmentRecord.shipment_no == _SHIP_NO)
                ).scalar_one_or_none()
                qty = session.execute(
                    select(ShipmentRecord.quantity)
                    .where(ShipmentRecord.shipment_no == _SHIP_NO)
                ).scalar_one_or_none()
                return first, second, created, qty
            finally:
                session.close()
                engine.dispose()

        # 修复前：首次 _sync_one_date 内的 INSERT 即抛 NotNullViolation（红）。
        first, second, created, qty = await asyncio.to_thread(_run)
        assert (first, second) == (1, 1), '首次 INSERT 写一条、二次走幂等 UPDATE 一条'
        assert created is not None, 'created_at 必须非空（无 server_default，绕过 ORM 默认值即断流）'
        assert qty == 5, 'quantity 应为 出库数-退货数（5-0）'
