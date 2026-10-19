"""库存/退货写端点的工厂隔离闸门（P0-2 回归，2026-10-18 审计）。

背景：stock.py / stock_return.py 的九个写端点（入库 create/edit/delete、
出库 create/edit/delete、退货 create/edit/delete）此前只认权限码、按自增
id 直取记录——厂绑定（User.factory 非空）的非超管用户可跨厂改删他厂
产品名下的库存记录（水平越权）。订单域已有同构闸门
（order.py::_assert_order_factory_scoped，2026-10-17 F-BE-API-01），
本文件锁定 stock 域同款语义：

- 厂绑定非超管触碰他厂记录：404（不暴露「存在但不属于你」，与 order 口径一致）；
- 超管、未绑定工厂（factory 为空）、本厂记录、产品 factory 为空的历史行：放行；
- 闸门在服务层写动作之前——被拒请求不得产生任何库存/流水变动。

用法：经 sr_api 式 fixture override 依赖（事务回滚隔离 + mock 用户），
直接向 app 发真实 HTTP 请求。
"""
import uuid

import pytest
import pytest_asyncio
from conftest import TEST_DATABASE_URL
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

STOCK_API = "/api/v1/stock"
RETURN_API = "/api/v1/stock-returns"


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
                        yield client, shared_session, user_mock, set_current_user
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
    user.username = "fs-tester"
    user.is_super = is_super
    user.factory = factory
    user.has_permission = MagicMock(return_value=True)
    return user


async def _make_hubei_stockout(db, *, with_stockin=False):
    """湖北厂产品 + 1 条独立出库（可再挂 1 条备货抵扣行）。返回 (product, stockout[, stockin])。"""
    from fastapi_app.shared_models import Product, StockIn, StockOut
    suffix = uuid.uuid4().hex[:8]
    product = Product(
        name=f"湖北-{suffix}", barcode=f"HB-{suffix}",
        factory="湖北", current_stock=100, initial_stock=100)
    db.add(product)
    await db.flush()
    stockout = StockOut(
        stockout_no=f"SO-FS-{suffix}", product_id=product.id,
        quantity=10, customer="湖北客户", stockout_date=None)
    db.add(stockout)
    if with_stockin:
        stockin = StockIn(
            stockin_no=f"SI-FS-{suffix}", product_id=product.id,
            quantity=50, customer="湖北客户", stockin_date=None)
        db.add(stockin)
        await db.flush()
        db.add(StockOut(
            stockout_no=f"SO-FD-{suffix}", product_id=product.id,
            quantity=10, customer="湖北客户", stockin_id=stockin.id,
            stockout_date=None))
        await db.flush()
        return product, stockout, stockin
    await db.flush()
    return product, stockout


async def _assert_no_stock_mutation(db, product):
    """闸门拒绝后不得产生任何库存/流水变动。"""
    from fastapi_app.shared_models import InventoryLog
    await db.refresh(product)
    assert product.current_stock == 100, f'被拒请求不得改库存，实际 {product.current_stock}'
    logs = (await db.execute(
        select(InventoryLog.id).where(InventoryLog.product_id == product.id))).scalars().all()
    assert logs == [], '被拒请求不得写流水'


@pytest.mark.integration
class TestStockInFactoryScope:
    """入库三端点：create / edit / delete。"""

    async def test_factory_user_cannot_create_for_other_factory(self, fs_api):
        client, db, _, set_user = fs_api
        set_user("东莞")
        product, _, _stockin = await _make_hubei_stockout(db, with_stockin=True)
        # 湖北厂产品建新备货 → 东莞绑定用户应 404
        resp = await client.post(f"{STOCK_API}/in/create", json={
            "product_id": product.id, "quantity": 5, "customer": "湖北客户",
            "stockin_date": "2026-10-18",
        })
        assert resp.status_code == 404, (
            f'厂绑定用户为他厂产品创建备货应 404，实际 {resp.status_code}：{resp.text}')
        await _assert_no_stock_mutation(db, product)

    async def test_factory_user_cannot_edit_other_factory(self, fs_api):
        client, db, _, set_user = fs_api
        set_user("东莞")
        product, _, stockin = await _make_hubei_stockout(db, with_stockin=True)
        resp = await client.put(f"{STOCK_API}/in/edit/{stockin.id}", json={"quantity": 99})
        assert resp.status_code == 404, (
            f'厂绑定用户改他厂备货应 404，实际 {resp.status_code}：{resp.text}')
        await db.refresh(stockin)
        assert stockin.quantity == 50, '被拒请求不得改备货数量'
        await _assert_no_stock_mutation(db, product)

    async def test_factory_user_cannot_delete_other_factory(self, fs_api):
        client, db, _, set_user = fs_api
        set_user("东莞")
        product, _, stockin = await _make_hubei_stockout(db, with_stockin=True)
        resp = await client.delete(f"{STOCK_API}/in/delete/{stockin.id}")
        assert resp.status_code == 404, (
            f'厂绑定用户删他厂备货应 404，实际 {resp.status_code}：{resp.text}')
        from fastapi_app.shared_models import StockIn
        assert (await db.execute(select(StockIn.id).where(StockIn.id == stockin.id))
                ).scalar() == stockin.id, '被拒请求不得删除备货'
        await _assert_no_stock_mutation(db, product)


@pytest.mark.integration
class TestStockOutFactoryScope:
    """出库三端点：create / edit / delete。"""

    async def test_factory_user_cannot_create_for_other_factory(self, fs_api):
        client, db, _, set_user = fs_api
        set_user("东莞")
        product, _stockout = await _make_hubei_stockout(db)
        resp = await client.post(f"{STOCK_API}/out/create", json={
            "product_id": product.id, "quantity": 5, "customer": "湖北客户",
            "stockout_date": "2026-10-18",
        })
        assert resp.status_code == 404, (
            f'厂绑定用户为他厂产品创建出货应 404，实际 {resp.status_code}：{resp.text}')
        await _assert_no_stock_mutation(db, product)

    async def test_factory_user_cannot_edit_other_factory(self, fs_api):
        client, db, _, set_user = fs_api
        set_user("东莞")
        product, stockout = await _make_hubei_stockout(db)
        resp = await client.put(f"{STOCK_API}/out/edit/{stockout.id}", json={"quantity": 99})
        assert resp.status_code == 404, (
            f'厂绑定用户改他厂出货应 404，实际 {resp.status_code}：{resp.text}')
        await db.refresh(stockout)
        assert stockout.quantity == 10, '被拒请求不得改出货数量'
        await _assert_no_stock_mutation(db, product)

    async def test_factory_user_cannot_delete_other_factory(self, fs_api):
        client, db, _, set_user = fs_api
        set_user("东莞")
        product, stockout = await _make_hubei_stockout(db)
        resp = await client.delete(f"{STOCK_API}/out/delete/{stockout.id}")
        assert resp.status_code == 404, (
            f'厂绑定用户删他厂出货应 404，实际 {resp.status_code}：{resp.text}')
        from fastapi_app.shared_models import StockOut
        assert (await db.execute(select(StockOut.id).where(StockOut.id == stockout.id))
                ).scalar() == stockout.id, '被拒请求不得删除出货'
        await _assert_no_stock_mutation(db, product)


@pytest.mark.integration
class TestStockReturnFactoryScope:
    """退货三端点：create / edit / delete。"""

    async def test_factory_user_cannot_create_for_other_factory(self, fs_api):
        client, db, _, set_user = fs_api
        set_user("东莞")
        product, stockout = await _make_hubei_stockout(db)
        resp = await client.post(f"{RETURN_API}/create", json={
            "stockout_id": stockout.id, "quantity": 5, "request_id": uuid.uuid4().hex,
        })
        assert resp.status_code == 404, (
            f'厂绑定用户为他厂出货登记退货应 404，实际 {resp.status_code}：{resp.text}')
        await _assert_no_stock_mutation(db, product)

    async def test_factory_user_cannot_edit_other_factory(self, fs_api):
        client, db, _, set_user = fs_api
        set_user("东莞")
        product, stockout = await _make_hubei_stockout(db)
        # 造一条湖北厂退货行，供东莞用户尝试篡改
        from fastapi_app.shared_models import StockReturn
        stock_return = StockReturn(
            return_no=f"SR-FS-{uuid.uuid4().hex[:8]}", product_id=product.id,
            stockout_id=stockout.id, quantity=3, customer="湖北客户",
            return_date=None, status="active")
        db.add(stock_return)
        await db.flush()
        resp = await client.put(f"{RETURN_API}/{stock_return.id}", json={"quantity": 99})
        assert resp.status_code == 404, (
            f'厂绑定用户改他厂退货应 404，实际 {resp.status_code}：{resp.text}')
        await db.refresh(stockout)
        assert stockout.returned_quantity == 0, '被拒请求不得改出货已退量'
        await _assert_no_stock_mutation(db, product)

    async def test_factory_user_cannot_delete_other_factory(self, fs_api):
        client, db, _, set_user = fs_api
        set_user("东莞")
        product, stockout = await _make_hubei_stockout(db)
        from fastapi_app.shared_models import StockReturn
        stock_return = StockReturn(
            return_no=f"SR-FS-{uuid.uuid4().hex[:8]}", product_id=product.id,
            stockout_id=stockout.id, quantity=3, customer="湖北客户",
            return_date=None, status="active")
        db.add(stock_return)
        await db.flush()
        resp = await client.delete(f"{RETURN_API}/{stock_return.id}")
        assert resp.status_code == 404, (
            f'厂绑定用户删他厂退货应 404，实际 {resp.status_code}：{resp.text}')
        assert (await db.execute(select(StockReturn.id).where(StockReturn.id == stock_return.id))
                ).scalar() == stock_return.id, '被拒请求不得删除退货'
        await _assert_no_stock_mutation(db, product)

    # ── 2026-10-19 OCR 第二轮 M1：按产品退货的历史行（stockout_id NULL）不得绕过厂闸门 ──
    # StockReturn.stockout_id 可空（迁移 071：按产品退货不关联出货），
    # 旧闸门 `if stockout_id is None: return` 对这些行直接放行——厂绑定用户
    # 可跨厂回冲库存/删记录。StockReturn.product_id NOT NULL，闸门须按它判厂。

    async def test_factory_user_cannot_edit_product_return_without_stockout(self, fs_api):
        client, db, _, set_user = fs_api
        set_user("东莞")
        product, _stockout = await _make_hubei_stockout(db)
        from fastapi_app.shared_models import StockReturn
        stock_return = StockReturn(
            return_no=f"SR-FS-{uuid.uuid4().hex[:8]}", product_id=product.id,
            stockout_id=None, quantity=3, customer="湖北客户",
            return_date=None, status="active")
        db.add(stock_return)
        await db.flush()
        resp = await client.put(f"{RETURN_API}/{stock_return.id}", json={"quantity": 99})
        assert resp.status_code == 404, (
            f'厂绑定用户改他厂按产品退货（无 stockout）应 404，'
            f'实际 {resp.status_code}：{resp.text}')
        await _assert_no_stock_mutation(db, product)

    async def test_factory_user_cannot_delete_product_return_without_stockout(self, fs_api):
        client, db, _, set_user = fs_api
        set_user("东莞")
        product, _stockout = await _make_hubei_stockout(db)
        from fastapi_app.shared_models import StockReturn
        stock_return = StockReturn(
            return_no=f"SR-FS-{uuid.uuid4().hex[:8]}", product_id=product.id,
            stockout_id=None, quantity=3, customer="湖北客户",
            return_date=None, status="active")
        db.add(stock_return)
        await db.flush()
        resp = await client.delete(f"{RETURN_API}/{stock_return.id}")
        assert resp.status_code == 404, (
            f'厂绑定用户删他厂按产品退货（无 stockout）应 404，'
            f'实际 {resp.status_code}：{resp.text}')
        assert (await db.execute(select(StockReturn.id).where(StockReturn.id == stock_return.id))
                ).scalar() == stock_return.id, '被拒请求不得删除按产品退货'
        await _assert_no_stock_mutation(db, product)


@pytest.mark.integration
class TestFactoryScopeAllows:
    """放行面：超管 / 未绑定厂 / 本厂记录 / factory 为空的历史产品。"""

    async def test_same_factory_user_allowed(self, fs_api):
        """厂匹配（湖北→湖北）不拦：编辑应到达业务层（非 404）。"""
        client, db, _, set_user = fs_api
        set_user("湖北")
        _product, stockout = await _make_hubei_stockout(db)
        resp = await client.put(f"{STOCK_API}/out/edit/{stockout.id}", json={"note": "本厂改"})
        assert resp.status_code != 404, '本厂记录不得被厂闸门拦截'

    async def test_unbound_user_allowed(self, fs_api):
        """factory 为空的非超管按全库口径放行（与 order 闸门同语义）。"""
        client, db, _, set_user = fs_api
        set_user(None)
        _product, stockout = await _make_hubei_stockout(db)
        resp = await client.put(f"{STOCK_API}/out/edit/{stockout.id}", json={"note": "未绑定改"})
        assert resp.status_code != 404, '未绑定厂用户不得被厂闸门拦截'

    async def test_super_user_allowed(self, fs_api):
        """超管豁免厂闸门。"""
        client, db, _, set_user = fs_api
        set_user("东莞", is_super=True)
        _product, stockout = await _make_hubei_stockout(db)
        resp = await client.put(f"{STOCK_API}/out/edit/{stockout.id}", json={"note": "超管改"})
        assert resp.status_code != 404, '超管不得被厂闸门拦截'

    async def test_legacy_product_without_factory_allowed(self, fs_api):
        """产品 factory 为空的历史行不拦（与 order 闸门 Product.factory.isnot(None) 同口径）。"""
        client, db, _, set_user = fs_api
        set_user("东莞")
        from fastapi_app.shared_models import Product
        suffix = uuid.uuid4().hex[:8]
        product = Product(
            name=f"无厂-{suffix}", barcode=f"NF-{suffix}",
            factory=None, current_stock=100, initial_stock=100)
        db.add(product)
        await db.flush()
        resp = await client.post(f"{STOCK_API}/in/create", json={
            "product_id": product.id, "quantity": 5, "customer": "客户",
            "stockin_date": "2026-10-18",
        })
        assert resp.status_code != 404, 'factory 为空的历史产品不得被厂闸门拦截'
