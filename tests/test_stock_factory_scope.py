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
    from fastapi_app.core.deps import (
        _get_user_with_permissions,
        get_current_user_id,
        get_current_user_id_write_strict,
    )
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
                        # 模拟生产 get_async_db 收尾 commit（2026-10-19 OCR
                        # 第四轮 H2 测试）：aux 删除端点 db_transaction(commit=
                        # False) 的写要靠请求依赖收尾的 commit 才持久化；不加
                        # 这行，端点写停留在 savepoint 里随 session.close()
                        # 回滚，正路径用例断言「行已删」永远看不到效果。此处
                        # commit 的是 savepoint（RELEASE），外层事务仍由 fixture
                        # 统一回滚，用例间隔离不变；路由抛异常时收尾异常路径
                        # 不走 commit（与生产一致，写被回滚）。
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
                app.dependency_overrides[get_current_user_id_write_strict] = override_user_id
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
    # ── 2026-10-19 OCR 第三轮 M1：factory 为**空串**的产品同样放行 ──
    # product_service.create_product 落库写 factory=factory or ''——未分配工厂
    # 是空串而非 NULL；旧判 `row_factory is not None` 把空串产品对厂绑定用户
    # 404，而产品列表页不按厂过滤仍显示这些行，读放行写拦截口径矛盾。

    async def test_legacy_product_with_empty_string_factory_allowed(self, fs_api):
        """产品 factory 为空串（create_product 写 factory or ''）的历史行不拦。"""
        client, db, _, set_user = fs_api
        set_user("东莞")
        from fastapi_app.shared_models import Product
        suffix = uuid.uuid4().hex[:8]
        product = Product(
            name=f"空厂-{suffix}", barcode=f"EF-{suffix}",
            factory="", current_stock=100, initial_stock=100)
        db.add(product)
        await db.flush()
        resp = await client.post(f"{STOCK_API}/in/create", json={
            "product_id": product.id, "quantity": 5, "customer": "客户",
            "stockin_date": "2026-10-19",
        })
        assert resp.status_code != 404, 'factory 为空串的历史产品不得被厂闸门拦截'


@pytest.mark.integration
class TestAuxBatchFactoryScope:
    """OCR 第三轮 H1：批量提交端点的逐项工厂闸门。

    /aux/batch-submit-stockins|stockouts 此前只认权限码，编排内部
    （batch_create_stockins / batch_create_stockouts）无任何工厂校验——
    厂绑定用户可混入他厂 product_id 批量建备货/出货（单条路径 P0-2 修了，
    批量路径漏网）。闸门须逐项执行：他厂项标 success=False 留在原下标
    （HTTP 恒 200，不破坏整批语义，前端按 results 下标对位判定部分失败）。
    """

    async def test_factory_user_batch_stockin_item_rejected(self, fs_api):
        client, db, _, set_user = fs_api
        set_user("东莞")
        product, _stockout = await _make_hubei_stockout(db)
        resp = await client.post("/api/v1/aux/batch-submit-stockins", json={
            "stockins": [
                {"product_id": product.id, "quantity": 5, "customer": "湖北客户"},
            ],
        })
        assert resp.status_code == 200, (
            f'批量端点不得因单项被拒而整批 4xx/5xx，实际 {resp.status_code}：{resp.text}')
        body = resp.json()
        assert len(body["results"]) == 1, 'results 须与请求项数对齐（前端按下标对位）'
        assert body["results"][0]["success"] is False, (
            f'他厂产品的备货项应被拒，实际 {body["results"][0]}')
        assert "工厂" in (body["results"][0].get("error") or ''), (
            f'拒绝文案须明确指出工厂范围，实际 {body["results"][0]}')
        await _assert_no_stock_mutation(db, product)

    async def test_factory_user_batch_stockout_item_rejected(self, fs_api):
        client, db, _, set_user = fs_api
        set_user("东莞")
        product, _stockout = await _make_hubei_stockout(db)
        resp = await client.post("/api/v1/aux/batch-submit-stockouts", json={
            "stockouts": [
                {"product_id": product.id, "quantity": 5, "customer": "湖北客户"},
            ],
        })
        assert resp.status_code == 200, (
            f'批量端点不得因单项被拒而整批 4xx/5xx，实际 {resp.status_code}：{resp.text}')
        body = resp.json()
        assert len(body["results"]) == 1, 'results 须与请求项数对齐（前端按下标对位）'
        assert body["results"][0]["success"] is False, (
            f'他厂产品的出货项应被拒，实际 {body["results"][0]}')
        assert "工厂" in (body["results"][0].get("error") or ''), (
            f'拒绝文案须明确指出工厂范围，实际 {body["results"][0]}')
        await _assert_no_stock_mutation(db, product)

    async def test_factory_user_batch_mixed_items_keep_order_and_partial_success(self, fs_api):
        """混合批次：他厂项拒（原下标）、本厂项正常编排成功，顺序不得错位。"""
        from fastapi_app.shared_models import Product
        client, db, _, set_user = fs_api
        set_user("湖北")
        product_hb, _stockout = await _make_hubei_stockout(db)
        suffix = uuid.uuid4().hex[:8]
        product_dg = Product(
            name=f"东莞-{suffix}", barcode=f"DG-{suffix}",
            factory="东莞", current_stock=100, initial_stock=100)
        db.add(product_dg)
        await db.flush()
        resp = await client.post("/api/v1/aux/batch-submit-stockins", json={
            "stockins": [
                {"product_id": product_dg.id, "quantity": 5, "customer": "东莞客户"},
                {"product_id": product_hb.id, "quantity": 5, "customer": "湖北客户"},
            ],
        })
        assert resp.status_code == 200, f'实际 {resp.status_code}：{resp.text}'
        body = resp.json()
        assert len(body["results"]) == 2, 'results 须与请求项数对齐（前端按下标对位）'
        assert body["results"][0]["success"] is False, (
            f'第 0 项（他厂）应被拒，实际 {body["results"][0]}')
        assert "工厂" in (body["results"][0].get("error") or '')
        assert body["results"][1]["success"] is True, (
            f'第 1 项（本厂）应正常创建，实际 {body["results"][1]}')
        assert body["results"][1].get("stockin_no"), '成功项须带 stockin_no'
        # 他厂产品不得因本厂项成功而被连带处理
        await db.refresh(product_dg)
        assert product_dg.current_stock == 100, '被拒项不得改他厂产品库存'

@pytest.mark.integration
class TestAuxDeleteFactoryScope:
    """OCR 第四轮 H2：aux 单行删除端点的工厂闸门。

    /aux/stockout/{id} 与 /aux/stockin/{id} 此前只认权限码、直调
    stock_service.delete_stockout/delete_stockin——stock.py 的
    /stock/out|in/delete/{id} 与本文件批量端点均已过闸门，这两个单行
    端点漏网，厂绑定用户可按 id 跨厂删他厂出库/入库行（水平越权）。
    """

    async def test_factory_user_cannot_delete_other_factory_stockout(self, fs_api):
        client, db, _, set_user = fs_api
        set_user("东莞")
        product, stockout = await _make_hubei_stockout(db)
        resp = await client.delete(f"/api/v1/aux/stockout/{stockout.id}")
        assert resp.status_code == 404, (
            f'厂绑定用户删他厂出库应 404（闸门口径，不暴露存在性），'
            f'实际 {resp.status_code}：{resp.text}')
        from fastapi_app.shared_models import StockOut
        assert (await db.execute(select(StockOut.id).where(StockOut.id == stockout.id))
                ).scalar() == stockout.id, '被拒请求不得删除出库记录'
        await _assert_no_stock_mutation(db, product)

    async def test_factory_user_cannot_delete_other_factory_stockin(self, fs_api):
        from fastapi_app.shared_models import Product, StockIn
        client, db, _, set_user = fs_api
        set_user("东莞")
        # 造无抵扣行的备货：挂抵扣行时旧版（无闸门）会被 svc 业务校验以 400
        # 拒绝，虽也红但证明力弱；无抵扣行时旧版会把删请求真放行到底，
        # 「行仍在」断言才直接证明越权删除确实发生。
        suffix = uuid.uuid4().hex[:8]
        product = Product(
            name=f"湖北-{suffix}", barcode=f"HB3-{suffix}",
            factory="湖北", current_stock=100, initial_stock=100)
        db.add(product)
        await db.flush()
        stockin = StockIn(
            stockin_no=f"SI-AUX-{suffix}", product_id=product.id,
            quantity=20, customer="湖北客户", stockin_date=None)
        db.add(stockin)
        await db.flush()
        resp = await client.delete(f"/api/v1/aux/stockin/{stockin.id}")
        assert resp.status_code == 404, (
            f'厂绑定用户删他厂备货应 404（闸门口径），'
            f'实际 {resp.status_code}：{resp.text}')
        assert (await db.execute(select(StockIn.id).where(StockIn.id == stockin.id))
                ).scalar() == stockin.id, '被拒请求不得删除备货记录'
        await _assert_no_stock_mutation(db, product)

    async def test_same_factory_user_delete_stockout_ok(self, fs_api):
        """本厂正路径：闸门放行，删除真实生效（200）。"""
        client, db, _, set_user = fs_api
        set_user("湖北")
        _product, stockout = await _make_hubei_stockout(db)
        resp = await client.delete(f"/api/v1/aux/stockout/{stockout.id}")
        assert resp.status_code == 200, (
            f'本厂用户删本厂出库应 200，实际 {resp.status_code}：{resp.text}')
        from fastapi_app.shared_models import StockOut
        assert (await db.execute(select(StockOut.id).where(StockOut.id == stockout.id))
                ).scalar() is None, '删除成功后出库行应不存在'

    async def test_same_factory_user_delete_stockin_ok(self, fs_api):
        """本厂正路径：无抵扣行的备货删除真实生效（200）。"""
        from fastapi_app.shared_models import Product, StockIn
        client, db, _, set_user = fs_api
        set_user("湖北")
        # 造无抵扣行的备货（挂抵扣行会被 svc 的业务校验拒绝，不是闸门问题）
        suffix = uuid.uuid4().hex[:8]
        product = Product(
            name=f"湖北-{suffix}", barcode=f"HB2-{suffix}",
            factory="湖北", current_stock=100, initial_stock=100)
        db.add(product)
        await db.flush()
        stockin = StockIn(
            stockin_no=f"SI-AUX-{suffix}", product_id=product.id,
            quantity=20, customer="湖北客户", stockin_date=None)
        db.add(stockin)
        await db.flush()
        resp = await client.delete(f"/api/v1/aux/stockin/{stockin.id}")
        assert resp.status_code == 200, (
            f'本厂用户删本厂备货应 200，实际 {resp.status_code}：{resp.text}')
        assert (await db.execute(select(StockIn.id).where(StockIn.id == stockin.id))
                ).scalar() is None, '删除成功后备货行应不存在'
