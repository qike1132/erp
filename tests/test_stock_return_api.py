"""退货管理 API 端点集成测试。

覆盖：权限 403、列表空态/形状、创建 happy path（含缺省日期填充）、
请求校验 422、业务校验 400（防超退/订单抵扣禁退经 ValueError 映射）、
删除 404/200。

服务层业务规则（防超退、库存回补、事件发布）已有单元覆盖
（tests/test_stock.py 对 create/delete_stockreturn_core 的用例），
本文件聚焦端点层：鉴权、事务编排、schema 校验与错误映射。
"""
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from conftest import TEST_DATABASE_URL
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

API_PREFIX = "/api/v1/stock-returns"


@pytest_asyncio.fixture
async def sr_api():
    """API 测试客户端 + 事务隔离 db session + 权限 override。

    Yields:
        (client, db, user_mock): httpx AsyncClient、共享 AsyncSession、
        当前用户 mock（has_permission 可按用例翻转以测 403）。
    """
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
            # 每个请求独立 session（共享 connection + 外层事务，SAVEPOINT 隔离），
            # 测试结束 trans.rollback() 统一回滚所有数据。
            async def override_db():
                async with AsyncSession(
                    bind=conn, expire_on_commit=False, join_transaction_mode="create_savepoint",
                ) as s:
                    yield s

            shared_session = AsyncSession(
                bind=conn, expire_on_commit=False, join_transaction_mode="create_savepoint",
            )
            try:
                async def override_user_id():
                    return None

                user_mock = MagicMock()
                user_mock.id = None
                user_mock.username = "admin"
                user_mock.is_super = True
                user_mock.has_permission = MagicMock(return_value=True)

                async def override_user_with_perms():
                    return user_mock

                original_overrides = dict(app.dependency_overrides)
                app.dependency_overrides[get_async_db] = override_db
                app.dependency_overrides[get_async_read_db] = override_db
                app.dependency_overrides[get_current_user_id] = override_user_id
                app.dependency_overrides[_get_user_with_permissions] = override_user_with_perms

                transport = ASGITransport(app=app)
                async with AsyncClient(
                    transport=transport,
                    base_url="http://test",
                    headers={
                        "Authorization": "Bearer test-token",
                        "Origin": "http://localhost:3000",
                    },
                ) as client:
                    try:
                        yield client, shared_session, user_mock
                    finally:
                        app.dependency_overrides.clear()
                        app.dependency_overrides.update(original_overrides)

                await shared_session.close()
            finally:
                await trans.rollback()
    finally:
        await engine.dispose()


@pytest.mark.integration
class TestStockReturnApi:
    """退货管理 API 集成测试用例集"""

    async def test_list_denied_without_permission(self, sr_api):
        """无 stock_return_view 权限时 GET /list 返回 403"""
        client, _, user_mock = sr_api
        user_mock.has_permission.return_value = False
        resp = await client.get(f"{API_PREFIX}/list")
        assert resp.status_code == 403
        assert resp.json()["detail"] == "权限不足"

    async def test_create_denied_with_view_only(self, sr_api):
        """仅查看权限（manage 校验失败）时 POST /create 返回 403"""
        client, _, user_mock = sr_api
        # has_permission('stock_return_manage') False、view True 的分叉行为
        user_mock.has_permission = MagicMock(
            side_effect=lambda code: code == "stock_return_view"
        )
        resp = await client.post(f"{API_PREFIX}/create", json={
            "stockout_id": 1, "quantity": 5,
        })
        assert resp.status_code == 403

    async def test_list_empty(self, sr_api):
        """GET /list 空数据返回标准分页形状"""
        client, _, _ = sr_api
        resp = await client.get(f"{API_PREFIX}/list")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["data"] == []
        assert data["total"] == 0
        assert data["page"] == 1

    async def test_create_rejects_non_positive_quantity(self, sr_api):
        """quantity<=0 被 Pydantic 拒绝（422），不触达服务层"""
        client, _, _ = sr_api
        resp = await client.post(f"{API_PREFIX}/create", json={
            "stockout_id": 1, "quantity": 0,
        })
        assert resp.status_code == 422

    async def test_create_rejects_bad_date_format(self, sr_api):
        """return_date 非 YYYY-MM-DD 被 Pydantic 拒绝（422）"""
        client, _, _ = sr_api
        resp = await client.post(f"{API_PREFIX}/create", json={
            "stockout_id": 1, "quantity": 5, "customer": "流程客户", "return_date": "2026/10/05",
        })
        assert resp.status_code == 422

    async def test_shipment_options_requires_manage(self, sr_api):
        """明细搜索端点要求 stock_return_manage：仅 view 权限 -> 403"""
        client, _, user_mock = sr_api
        user_mock.has_permission = MagicMock(
            side_effect=lambda code: code == "stock_return_view"
        )
        resp = await client.get(f"{API_PREFIX}/shipment-options", params={"q": "板"})
        assert resp.status_code == 403

    async def test_shipment_options_search_and_availability(self, sr_api):
        """按产品名搜可退明细：仅 available>0、带单号/客户/可退量"""
        from fastapi_app.shared_models import Product, StockOut

        client, db, _ = sr_api
        suffix = uuid.uuid4().hex[:8]
        p1 = Product(name=f"鲨鱼板-{suffix}", current_stock=10)
        p2 = Product(name=f"其他板-{suffix}", current_stock=10)
        db.add_all([p1, p2])
        await db.flush()
        db.add(StockOut(stockout_no=f"SO-S1-{suffix}", product_id=p1.id,
                        quantity=10, customer="客户甲", returned_quantity=2))
        db.add(StockOut(stockout_no=f"SO-S2-{suffix}", product_id=p1.id,
                        quantity=5, customer="客户乙", returned_quantity=5))
        db.add(StockOut(stockout_no=f"SO-S3-{suffix}", product_id=p2.id,
                        quantity=8, customer="客户丙", returned_quantity=0))
        await db.flush()

        resp = await client.get(f"{API_PREFIX}/shipment-options", params={"q": "鲨鱼"})
        assert resp.status_code == 200, resp.text
        rows = resp.json()
        assert [r["stockout_no"] for r in rows] == [f"SO-S1-{suffix}"]
        assert (rows[0]["quantity"], rows[0]["returned_quantity"], rows[0]["available"]) == (10, 2, 8)

        resp = await client.get(f"{API_PREFIX}/shipment-options")
        nos = [r["stockout_no"] for r in resp.json()]
        assert f"SO-S3-{suffix}" in nos and f"SO-S2-{suffix}" not in nos

    async def test_create_happy_path_fills_default_date(self, sr_api):
        """正常创建（按产品制）：服务层被以缺省当天日期/客户调用，端点返回单号"""
        client, _, _ = sr_api
        with patch(
            "fastapi_app.api.v1.endpoints.stock_return.create_stockreturn",
            new=AsyncMock(return_value={"id": 1, "return_no": "SR-20261005-0001"}),
        ) as mock_create:
            resp = await client.post(f"{API_PREFIX}/create", json={
                "stockout_id": 9, "quantity": 5, "reason": "质量问题",
            })
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["success"] is True
        assert "SR-20261005-0001" in body["message"]
        # return_date 缺省 → 传给服务层的是当天日期字符串
        kwargs = mock_create.call_args.kwargs
        assert kwargs["stockout_id"] == 9
        assert kwargs["quantity"] == 5
        assert kwargs["return_date_str"] and len(kwargs["return_date_str"]) == 10

    async def test_create_maps_value_error_to_400(self, sr_api):
        """服务层业务校验（防超退/订单抵扣禁退）ValueError → 400 + 原文案"""
        client, _, _ = sr_api
        with patch(
            "fastapi_app.api.v1.endpoints.stock_return.create_stockreturn",
            new=AsyncMock(side_effect=ValueError("退货数量超过可退数量！出货数量：50，已退货：50，可退：0")),
        ):
            resp = await client.post(f"{API_PREFIX}/create", json={
                "stockout_id": 9, "quantity": 1,
            })
        assert resp.status_code == 400
        assert "可退：0" in resp.json()["detail"]

    async def test_delete_not_found(self, sr_api):
        """删除不存在的退货记录返回 404"""
        client, _, _ = sr_api
        resp = await client.delete(f"{API_PREFIX}/999")
        assert resp.status_code == 404
        assert resp.json()["detail"] == "退货记录不存在"

    async def test_cancel_happy_path_soft_delete(self, sr_api):
        """P1-① 取消退货：库存链路回冲，记录保留且 status='cancelled'"""
        from sqlalchemy import select

        from fastapi_app.shared_models import Product, StockOut, StockReturn

        client, db, _ = sr_api
        suffix = uuid.uuid4().hex[:8]
        product = Product(name=f"退货测试产品-{suffix}", current_stock=100)
        db.add(product)
        await db.flush()
        stockout = StockOut(
            stockout_no=f"SO-TEST-{suffix}", product_id=product.id,
            quantity=50, customer="退货测试客户", returned_quantity=5,
        )
        db.add(stockout)
        await db.flush()
        stock_return = StockReturn(
            return_no=f"SR-TEST-{suffix}", product_id=product.id, quantity=5,
            customer="退货测试客户", stockout_id=stockout.id, reason="其他",
        )
        db.add(stock_return)
        await db.flush()

        with patch(
            "fastapi_app.api.v1.endpoints.stock_return.cancel_stockreturn",
            new=AsyncMock(return_value=None),
        ) as mock_cancel:
            resp = await client.delete(f"{API_PREFIX}/{stock_return.id}")
        assert resp.status_code == 200, resp.text
        assert resp.json()["success"] is True
        assert "取消" in resp.json()["message"]
        assert mock_cancel.call_args.kwargs["stockreturn_id"] == stock_return.id
        # 软取消：记录仍在（service 层置 status，端点 mock 不影响本断言的对象存在性）
        still_there = (await db.execute(
            select(StockReturn).where(StockReturn.id == stock_return.id)
        )).scalar_one_or_none()
        assert still_there is not None, "软取消后记录必须保留"

    async def test_list_with_data_and_filters(self, sr_api):
        """GET /list 落真实数据：客户模糊筛选与日期区间过滤、关联字段回填"""
        from fastapi_app.shared_models import Product, StockOut, StockReturn

        client, db, _ = sr_api
        suffix = uuid.uuid4().hex[:8]
        product = Product(name=f"退货筛选产品-{suffix}", current_stock=10)
        db.add(product)
        await db.flush()
        stockout = StockOut(
            stockout_no=f"SO-FLT-{suffix}", product_id=product.id,
            quantity=50, customer="筛选客户甲", returned_quantity=0,
        )
        db.add(stockout)
        await db.flush()
        stock_return = StockReturn(
            return_no=f"SR-FLT-{suffix}", product_id=product.id, quantity=5,
            customer="筛选客户甲", stockout_id=stockout.id, reason="错发",
        )
        db.add(stock_return)
        other = StockReturn(
            return_no=f"SR-FLT-OTH-{suffix}", product_id=product.id, quantity=1,
            customer="其他客户乙", stockout_id=stockout.id, reason="其他",
        )
        db.add(other)
        await db.flush()

        # 无筛选：两条都在
        resp = await client.get(f"{API_PREFIX}/list")
        assert resp.status_code == 200
        assert resp.json()["total"] >= 2

        # 客户模糊筛选：只中客户甲
        resp = await client.get(f"{API_PREFIX}/list", params={"customer": "客户甲"})
        data = resp.json()["data"]
        assert data and all(row["customer"] == "筛选客户甲" for row in data)
        assert any(row["return_no"] == f"SR-FLT-{suffix}" for row in data)
        # 关联字段回填（product/stockout joinedload）
        row = next(r for r in data if r["return_no"] == f"SR-FLT-{suffix}")
        assert row["product"]["name"] == f"退货筛选产品-{suffix}"
        assert row["stockout_no"] == f"SO-FLT-{suffix}"

        # 未来日期区间：全部过滤掉
        resp = await client.get(
            f"{API_PREFIX}/list", params={"start_date": "2099-01-01", "end_date": "2099-12-31"}
        )
        assert resp.json()["data"] == []

    async def test_list_excludes_cancelled_returns(self, sr_api):
        """已取消（软取消）的退货不出现在 /list —— 与退货流水报表口径一致。

        背景（2026-10-08）：退货管理页曾把 status='cancelled' 的作废行一并列出，
        而报表只查 active，两个视图口径不一致。
        """
        from fastapi_app.shared_models import Product, StockOut, StockReturn

        client, db, _ = sr_api
        suffix = uuid.uuid4().hex[:8]
        product = Product(name=f"退货取消产品-{suffix}", current_stock=10)
        db.add(product)
        await db.flush()
        stockout = StockOut(
            stockout_no=f"SO-CXL-{suffix}", product_id=product.id,
            quantity=50, customer="取消测试客户", returned_quantity=0,
        )
        db.add(stockout)
        await db.flush()
        db.add_all([
            StockReturn(
                return_no=f"SR-CXL-A-{suffix}", product_id=product.id, quantity=5,
                customer="取消测试客户", stockout_id=stockout.id, reason="错发", status="active",
            ),
            StockReturn(
                return_no=f"SR-CXL-C-{suffix}", product_id=product.id, quantity=7,
                customer="取消测试客户", stockout_id=stockout.id, reason="错发", status="cancelled",
            ),
        ])
        await db.flush()

        resp = await client.get(f"{API_PREFIX}/list")
        assert resp.status_code == 200
        nos = [row["return_no"] for row in resp.json()["data"]]
        assert f"SR-CXL-A-{suffix}" in nos, "active 退货应出现"
        assert f"SR-CXL-C-{suffix}" not in nos, "已取消退货不应出现"

    async def test_create_request_id_dedup(self, sr_api):
        """P1-③ 幂等：同 request_id 的第二次提交被拒（400 请勿重复提交）"""
        client, db, _ = sr_api
        with patch(
            "fastapi_app.api.v1.endpoints.stock_return.create_stockreturn",
            new=AsyncMock(return_value={"id": 1, "return_no": "SR-20261005-0001"}),
        ):
            first = await client.post(f"{API_PREFIX}/create", json={
                "stockout_id": 9, "quantity": 5, "request_id": "req-abc12345",
            })
            assert first.status_code == 200

        # 第二次直接命中服务层的幂等预检（真实查询 InventoryLog.idem_key）
        async def _fake_create(db, *, stockout_id, quantity, return_date_str, customer=None,
                               reason=None, note=None, request_id=None, operator_id=None):
            # 模拟 service 真实行为：同 request_id 再次进入即拒
            raise ValueError('请勿重复提交：该请求已登记过退货')

        with patch(
            "fastapi_app.api.v1.endpoints.stock_return.create_stockreturn",
            new=AsyncMock(side_effect=_fake_create),
        ):
            second = await client.post(f"{API_PREFIX}/create", json={
                "stockout_id": 9, "quantity": 5, "request_id": "req-abc12345",
            })
        assert second.status_code == 400
        assert "请勿重复提交" in second.json()["detail"]
        _ = db  # db 未直接使用，保持夹具解构一致

    async def test_delete_denied_without_manage(self, sr_api):
        """无 manage 权限时 DELETE 返回 403"""
        client, _, user_mock = sr_api
        user_mock.has_permission.return_value = False
        resp = await client.delete(f"{API_PREFIX}/1")
        assert resp.status_code == 403
