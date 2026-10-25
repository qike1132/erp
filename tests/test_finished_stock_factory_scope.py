"""成品库存（finished-stock）读写链的工厂隔离回归（2026-10-25 上线前检查 H1）。

背景：summary / batches / export / remark 四端点此前只认权限码——厂绑定
（User.factory 非空）的非超管用户可读、导出、写他厂产品的批次库存（水平越权）。
修复：工厂一律由服务端当前用户派生（finished_stock._factory_scope，与
stock.py 同口径），summary/export/batches 的入/出聚合与客户快捷栏全链收窄；
batches/remark 接收调用方 product_id 的，先过 assert_product_factory_scoped
（不匹配一律 404，不暴露存在性）。

用法：与 test_stock_factory_scope.py 同款 fixture——事务回滚隔离 + mock 用户
（factory 可翻转），直接向 app 发真实 HTTP 请求。
"""
import uuid

import pytest
import pytest_asyncio
from conftest import TEST_DATABASE_URL
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

API = "/api/v1/finished-stock"


@pytest_asyncio.fixture
async def fs_api():
    """工厂隔离测试客户端：事务回滚隔离 + 当前用户 mock（factory 可翻转）。"""
    from fastapi_app.core import database as _db_mod
    from fastapi_app.core.database import get_async_db, get_async_read_db
    from fastapi_app.core.deps import _get_user_with_permissions, get_current_user_id
    from fastapi_app.main import app
    from fastapi_app.shared_models import Base
    await _db_mod.ensure_engine_for_current_loop()

    engine = create_async_engine(TEST_DATABASE_URL, echo=False, pool_pre_ping=True)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        async with engine.connect() as conn:
            trans = await conn.begin()
            try:

                async def override_db():
                    async with AsyncSession(
                        bind=conn, expire_on_commit=False,
                        join_transaction_mode="create_savepoint",
                    ) as s:
                        yield s
                        await s.commit()

                shared_session = AsyncSession(
                    bind=conn, expire_on_commit=False,
                    join_transaction_mode="create_savepoint",
                )

                user_mock = _make_user_mock(factory="东莞", is_super=False)

                async def override_user_id():
                    return None

                async def override_user_with_perms():
                    return user_mock

                original_overrides = dict(app.dependency_overrides)
                app.dependency_overrides[get_async_db] = override_db
                app.dependency_overrides[get_async_read_db] = override_db
                app.dependency_overrides[get_current_user_id] = override_user_id
                app.dependency_overrides[_get_user_with_permissions] = override_user_with_perms

                def set_current_user(factory, is_super=False):
                    user_mock.factory = factory
                    user_mock.is_super = is_super

                transport = ASGITransport(app=app)
                async with AsyncClient(
                    transport=transport, base_url="http://test",
                    cookies={"fastapi_csrf_token": "test-csrf-token"},
                    headers={
                        "Authorization": "Bearer test-token",
                        "Origin": "http://localhost:3000",
                        "X-CSRF-Token": "test-csrf-token",
                    },
                ) as client:
                    try:
                        yield client, shared_session, set_current_user
                    finally:
                        app.dependency_overrides.clear()
                        app.dependency_overrides.update(original_overrides)

                await shared_session.close()
            finally:
                await trans.rollback()
    finally:
        await engine.dispose()


def _make_user_mock(factory=None, is_super=True):
    from unittest.mock import MagicMock
    user = MagicMock()
    user.id = None
    user.username = "fs-factory-tester"
    user.is_super = is_super
    user.factory = factory
    user.has_permission = MagicMock(return_value=True)
    return user


async def _seed_two_factories(db: AsyncSession, tag: str):
    """东莞/湖北两厂产品 + 各自的包装部入库行与出货行。返回 (dg, hb, rows)。"""
    from datetime import date

    from fastapi_app.shared_models import DailyProductionRecord, Product, StockOut

    dg = Product(name=f"东莞-{tag}", barcode=f"DG-{tag}", factory="东莞")
    hb = Product(name=f"湖北-{tag}", barcode=f"HB-{tag}", factory="湖北")
    db.add_all([dg, hb])
    await db.flush()
    for prod, cust in ((dg, "东莞客户"), (hb, "湖北客户")):
        db.add(DailyProductionRecord(
            department="packaging", product_id=prod.id, product_name=prod.name,
            barcode=prod.barcode, unit_price=0, quantity=100,
            production_date=date(2026, 10, 20), batch_no=f"B-{tag}",
            customer_name=cust,
        ))
        db.add(StockOut(
            stockout_no=f"SO-FS-{prod.id}", product_id=prod.id, quantity=10,
            customer=cust, stockout_date=None))
    await db.flush()
    return dg, hb


async def _cleanup(db: AsyncSession, dg, hb, tag: str):
    from fastapi_app.shared_models import DailyProductionRecord, FinishedStockRemark, StockOut
    await db.execute(delete(StockOut).where(StockOut.product_id.in_([dg.id, hb.id])))
    await db.execute(delete(DailyProductionRecord).where(
        DailyProductionRecord.product_id.in_([dg.id, hb.id])))
    await db.execute(delete(FinishedStockRemark).where(
        FinishedStockRemark.product_id.in_([dg.id, hb.id])))
    await db.flush()


@pytest.mark.integration
class TestFinishedStockFactoryScope:
    async def test_summary_scoped_for_factory_user(self, fs_api):
        """厂绑定用户的 summary 只见本厂产品行与客户；未绑定/超管见全量。"""
        client, db, set_user = fs_api
        tag = uuid.uuid4().hex[:8]
        dg, hb = await _seed_two_factories(db, tag)
        try:
            resp = await client.get(f"{API}/summary", params={"product": tag})
            assert resp.status_code == 200, resp.text
            body = resp.json()
            names = {row["product_name"] for row in body["data"]}
            assert names == {f"东莞-{tag}"}, f"厂用户只见本厂行，实际 {names}"
            assert "湖北客户" not in body["all_customers"], "客户快捷栏不得泄漏他厂客户"
            assert "东莞客户" in body["all_customers"]

            set_user(None)  # 未绑定厂 → 全量
            resp_all = await client.get(f"{API}/summary", params={"product": tag})
            names_all = {row["product_name"] for row in resp_all.json()["data"]}
            assert names_all == {f"东莞-{tag}", f"湖北-{tag}"}
        finally:
            await _cleanup(db, dg, hb, tag)

    async def test_batches_for_other_factory_product_is_404(self, fs_api):
        """batches 接收调用方 product_id：他厂产品 404，不暴露存在性。"""
        client, db, _set_user = fs_api
        tag = uuid.uuid4().hex[:8]
        dg, hb = await _seed_two_factories(db, tag)
        try:
            resp = await client.get(f"{API}/batches", params={"product_id": hb.id})
            assert resp.status_code == 404, f"他厂产品批次必须 404，实际 {resp.status_code}"

            resp_ok = await client.get(f"{API}/batches", params={"product_id": dg.id})
            assert resp_ok.status_code == 200, resp_ok.text
            assert [r["batch_no"] for r in resp_ok.json()["data"]] == [f"B-{tag}"]
        finally:
            await _cleanup(db, dg, hb, tag)

    async def test_export_scoped_for_factory_user(self, fs_api):
        """导出与列表同范围：厂用户导出的 Excel 不含他厂行。"""
        client, db, _set_user = fs_api
        tag = uuid.uuid4().hex[:8]
        dg, hb = await _seed_two_factories(db, tag)
        try:
            resp = await client.get(f"{API}/export", params={"product": tag})
            assert resp.status_code == 200, resp.text
            import io

            import openpyxl
            wb = openpyxl.load_workbook(io.BytesIO(resp.content), read_only=True)
            rows = list(wb.active.iter_rows(values_only=True))
            wb.close()
            cell_text = " ".join(str(c) for r in rows for c in r if c is not None)
            assert f"东莞-{tag}" in cell_text
            assert f"湖北-{tag}" not in cell_text, "导出不得包含他厂产品行"
        finally:
            await _cleanup(db, dg, hb, tag)

    async def test_remark_for_other_factory_product_is_404_without_side_effect(self, fs_api):
        """备注写他厂产品：404 且不产生任何 remark 行（写副作用为零）。"""
        from fastapi_app.shared_models import FinishedStockRemark
        client, db, _set_user = fs_api
        tag = uuid.uuid4().hex[:8]
        dg, hb = await _seed_two_factories(db, tag)
        try:
            resp = await client.put(
                f"{API}/remark",
                json={"customer_name": "湖北客户", "product_id": hb.id,
                      "batch_no": f"B-{tag}", "remark": "越权写入"},
            )
            assert resp.status_code == 404, f"他厂备注写必须 404，实际 {resp.status_code}"
            rows = (await db.execute(select(FinishedStockRemark).where(
                FinishedStockRemark.product_id == hb.id))).scalars().all()
            assert rows == [], "被拒请求不得留下任何 remark 行"

            # 本厂产品正常写
            resp_ok = await client.put(
                f"{API}/remark",
                json={"customer_name": "东莞客户", "product_id": dg.id,
                      "batch_no": f"B-{tag}", "remark": "本厂备注"},
            )
            assert resp_ok.status_code == 200, resp_ok.text
        finally:
            await _cleanup(db, dg, hb, tag)

    async def test_super_user_sees_all_factories(self, fs_api):
        """超管不受工厂收窄（与 stock 域读侧口径一致）。"""
        client, db, _set_user = fs_api
        tag = uuid.uuid4().hex[:8]
        dg, hb = await _seed_two_factories(db, tag)
        try:
            _set_user("东莞", is_super=True)  # 厂绑定但超管 → 全量
            resp = await client.get(f"{API}/summary", params={"product": tag})
            names = {row["product_name"] for row in resp.json()["data"]}
            assert names == {f"东莞-{tag}", f"湖北-{tag}"}
        finally:
            await _cleanup(db, dg, hb, tag)

    async def test_outbound_aggregation_also_scoped(self, fs_api):
        """出货侧聚合同步收窄：他厂出货量不得影响本厂批次可用量的计算口径。

        东莞入 100 出 10 → 可用 90；湖北入 100 出 10 → 可用 90。
        厂用户只看到本厂的 90，且两厂各自独立（互不串扣）。
        """
        client, db, _set_user = fs_api
        tag = uuid.uuid4().hex[:8]
        dg, hb = await _seed_two_factories(db, tag)
        try:
            resp = await client.get(f"{API}/summary", params={"product": tag})
            rows = resp.json()["data"]
            assert len(rows) == 1
            assert rows[0]["batch_in_qty"] == 100
            assert rows[0]["batch_available"] == 90
        finally:
            await _cleanup(db, dg, hb, tag)
