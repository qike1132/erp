"""湖北外发模块 —— 待发货聚合与跨订单批量发货 单元测试。

自 ``tests/test_outsource.py`` 拆出（2026-10-13）：该文件 1632 行，超过
``pyproject.toml`` 的 ``max_file_size=1600``，CI 的文件规模门禁要求改动的超限
文件先拆分。**纯搬移**，断言与用例未改。
"""
from unittest.mock import AsyncMock, patch

import pytest

from fastapi_app.shared_models import OrderOutsourceProcess


class TestListShippableProcesses:
    """待发货工序聚合（批量发货面板数据源）"""

    @staticmethod
    async def _session(tmp_path):
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        from fastapi_app.shared_models import (
            Order as OrderModel,
        )
        from fastapi_app.shared_models import (
            OrderItem as OrderItemModel,
        )
        from fastapi_app.shared_models import (
            Product as ProductModel,
        )
        engine = create_async_engine(f'sqlite+aiosqlite:///{tmp_path / "shippable.db"}')
        async with engine.begin() as conn:
            for table in (
                ProductModel.__table__, OrderModel.__table__, OrderItemModel.__table__,
                OrderOutsourceProcess.__table__,
            ):
                await conn.run_sync(lambda c, t=table: t.create(c, checkfirst=True))
        return engine, async_sessionmaker(engine, expire_on_commit=False)

    @pytest.mark.asyncio
    async def test_only_unshipped_processes_listed(self, tmp_path):
        """待发货 = 已发 < 目标；已发满/已收齐的不出现。"""
        from fastapi_app.services.outsource_service import list_shippable_processes
        from fastapi_app.shared_models import (
            Order as OrderModel,
        )
        from fastapi_app.shared_models import (
            OrderItem as OrderItemModel,
        )
        from fastapi_app.shared_models import (
            Product as ProductModel,
        )

        engine, session_factory = await self._session(tmp_path)
        try:
            async with session_factory() as session:
                session.add(ProductModel(id=1, name='SKU1', factory='湖北'))
                session.add(OrderModel(id=1, order_no='PO-1', customer='C', product_id=1, quantity=100))
                session.add(OrderItemModel(id=10, order_id=1, product_id=1, quantity=100))
                session.add(OrderOutsourceProcess(id=1, order_id=1, order_item_id=10, product_id=1, product_name='SKU1', process_type='电绣', sort_order=1, status='pending'))
                session.add(OrderOutsourceProcess(id=2, order_id=1, order_item_id=10, product_id=1, product_name='SKU1', process_type='转印', sort_order=2, status='shipped', shipped_quantity=30))
                session.add(OrderOutsourceProcess(id=3, order_id=1, order_item_id=10, product_id=1, product_name='SKU1', process_type='缝制', sort_order=3, status='received', shipped_quantity=100, received_quantity=100))
                session.add(OrderOutsourceProcess(id=4, order_id=1, order_item_id=10, product_id=1, product_name='SKU1', process_type='配件', sort_order=4, status='shipped', shipped_quantity=100))
                await session.commit()

            async with session_factory() as session:
                rows = await list_shippable_processes(session)

            procs = [(r['process_type'], r['remaining']) for r in rows]
            assert procs == [('电绣', 100), ('转印', 70)]
        finally:
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_partially_shipped_then_received_still_listed(self, tmp_path):
        """回归：部分发货并已收货、但未发满的工序，仍须留在待发货列表（可继续发下一批）。

        收货只闭环「本批」而非关闭整单；此前以 received_quantity > 0 过滤，
        导致「王者荣耀」这类分批场景在首次收货后从批量发货面板消失，剩余数量再也发不出去。
        """
        from fastapi_app.services.outsource_service import list_shippable_processes
        from fastapi_app.shared_models import (
            Order as OrderModel,
        )
        from fastapi_app.shared_models import (
            OrderItem as OrderItemModel,
        )
        from fastapi_app.shared_models import (
            Product as ProductModel,
        )

        engine, session_factory = await self._session(tmp_path)
        try:
            async with session_factory() as session:
                session.add(ProductModel(id=1, name='王者荣耀', factory='湖北'))
                session.add(OrderModel(id=1, order_no='PO-1', customer='C', product_id=1, quantity=100))
                session.add(OrderItemModel(id=10, order_id=1, product_id=1, quantity=100))
                # 发 40 收 40，目标 100 → 剩余 60，仍应可发
                session.add(OrderOutsourceProcess(
                    id=1, order_id=1, order_item_id=10, product_id=1, product_name='王者荣耀',
                    process_type='电绣', sort_order=1, status='shipped',
                    shipped_quantity=40, received_quantity=40,
                ))
                await session.commit()

            async with session_factory() as session:
                rows = await list_shippable_processes(session)

            assert [(r['process_type'], r['target_qty'], r['shipped_qty'], r['remaining']) for r in rows] == [
                ('电绣', 100, 40, 60),
            ]
        finally:
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_fully_received_not_listed(self, tmp_path):
        """已收齐（收货累计 >= 目标）的工序不再出现在待发货列表。"""
        from fastapi_app.services.outsource_service import list_shippable_processes
        from fastapi_app.shared_models import (
            Order as OrderModel,
        )
        from fastapi_app.shared_models import (
            OrderItem as OrderItemModel,
        )
        from fastapi_app.shared_models import (
            Product as ProductModel,
        )

        engine, session_factory = await self._session(tmp_path)
        try:
            async with session_factory() as session:
                session.add(ProductModel(id=1, name='王者荣耀', factory='湖北'))
                session.add(OrderModel(id=1, order_no='PO-1', customer='C', product_id=1, quantity=100))
                session.add(OrderItemModel(id=10, order_id=1, product_id=1, quantity=100))
                session.add(OrderOutsourceProcess(
                    id=1, order_id=1, order_item_id=10, product_id=1, product_name='王者荣耀',
                    process_type='电绣', sort_order=1, status='received',
                    shipped_quantity=100, received_quantity=100,
                ))
                await session.commit()

            async with session_factory() as session:
                rows = await list_shippable_processes(session)

            assert rows == []
        finally:
            await engine.dispose()


class TestShipProcessesMulti:
    """跨订单批量发货：逐条复用 ship_order_process，失败包装错误"""

    @pytest.mark.asyncio
    async def test_ship_cross_orders(self, mock_async_db):
        from fastapi_app.services import outsource_service
        from fastapi_app.services.outsource import _order_processes as mod

        mock_ship = AsyncMock(side_effect=[
            {'id': 1, 'order_id': 100},
            {'id': 2, 'order_id': 200},
        ])
        with patch.object(mod, 'ship_order_process', new=mock_ship):
            items = await outsource_service.ship_processes_multi(
                mock_async_db, [(1, 10), (2, 20)], username='admin',
            )

        assert len(items) == 2
        assert items[0]['order_id'] == 100
        assert items[1]['order_id'] == 200
        assert mock_ship.await_count == 2

    @pytest.mark.asyncio
    async def test_ship_failure_wraps_error(self, mock_async_db):
        from fastapi_app.services import outsource_service
        from fastapi_app.services.outsource import _order_processes as mod

        with patch.object(mod, 'ship_order_process', new=AsyncMock(
            side_effect=ValueError('发货数量超过剩余数量（剩余 5）'),
        )):
            with pytest.raises(ValueError, match='外发工序 1：发货数量超过剩余数量'):
                await outsource_service.ship_processes_multi(
                    mock_async_db, [(1, 100)], username='admin',
                )
