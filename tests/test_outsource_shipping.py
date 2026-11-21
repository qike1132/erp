"""湖北外发模块 —— 待发货聚合与跨订单批量发货 单元测试。

自 ``tests/test_outsource.py`` 拆出（2026-10-13）：该文件 1632 行，超过
``pyproject.toml`` 的 ``max_file_size=1600``，CI 的文件规模门禁要求改动的超限
文件先拆分。**纯搬移**，断言与用例未改。
"""

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


class TestListUnshippedProcesses:
    """未到货清单（导出/打印）聚合"""

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
            OutsourceProcessType as PresetModel,
        )
        from fastapi_app.shared_models import (
            Product as ProductModel,
        )
        engine = create_async_engine(f'sqlite+aiosqlite:///{tmp_path / "unshipped.db"}')
        async with engine.begin() as conn:
            for table in (
                ProductModel.__table__, OrderModel.__table__, OrderItemModel.__table__,
                OrderOutsourceProcess.__table__, PresetModel.__table__,
            ):
                await conn.run_sync(lambda c, t=table: t.create(c, checkfirst=True))
        return engine, async_sessionmaker(engine, expire_on_commit=False)

    @pytest.mark.asyncio
    async def test_legacy_order_without_order_item_listed(self, tmp_path):
        """回归（hubei-M-3 / P1-6）：无 OrderItem 的旧单工序必须出现在未到货清单。

        旧单（单 SKU、无明细行）的工序实例 order_item_id 为空；待发货面板
        （list_shippable_processes）与发货校验（_process_target_quantity）都按
        coalesce(OrderItem.quantity, Order.quantity) 回退整单数量——旧单可见可发，
        但未到货清单以 OrderItem 为驱动表 → 旧单整单漏出，打印给贝乐的
        「未到货清单」少列这些欠货（对账差异）。
        """
        from fastapi_app.services.outsource_service import list_unshipped_processes
        from fastapi_app.shared_models import (
            Order as OrderModel,
        )
        from fastapi_app.shared_models import (
            Product as ProductModel,
        )

        engine, session_factory = await self._session(tmp_path)
        try:
            async with session_factory() as session:
                session.add(ProductModel(id=1, name='老SKU', factory='湖北'))
                # 旧单：无 OrderItem 行，quantity 在订单上
                session.add(OrderModel(id=1, order_no='PO-OLD-1', customer='贝乐客户',
                                       product_id=1, quantity=50))
                # 工序实例 order_item_id 为空，已发 20
                session.add(OrderOutsourceProcess(
                    id=1, order_id=1, order_item_id=None, product_id=1, product_name='老SKU',
                    process_type='电绣', sort_order=0, status='shipped', shipped_quantity=20,
                ))
                await session.commit()

            async with session_factory() as session:
                rows = await list_unshipped_processes(session)

            assert [(r['order_no'], r['process_type'], r['target_qty'], r['shipped_qty'], r['remaining'])
                    for r in rows] == [
                ('PO-OLD-1', '电绣', 50, 20, 30),
            ]
        finally:
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_new_order_preset_rows_still_listed(self, tmp_path):
        """守卫：新单（有 OrderItem）的预设口径行为不变——SKU 明细驱动 + 启用预设展开。"""
        from fastapi_app.services.outsource_service import list_unshipped_processes
        from fastapi_app.shared_models import (
            Order as OrderModel,
        )
        from fastapi_app.shared_models import (
            OrderItem as OrderItemModel,
        )
        from fastapi_app.shared_models import (
            OutsourceProcessType as PresetModel,
        )
        from fastapi_app.shared_models import (
            Product as ProductModel,
        )

        engine, session_factory = await self._session(tmp_path)
        try:
            async with session_factory() as session:
                session.add(ProductModel(id=1, name='新SKU', factory='湖北'))
                session.add(OrderModel(id=1, order_no='PO-1', customer='贝乐客户',
                                       product_id=1, quantity=100))
                session.add(OrderItemModel(id=10, order_id=1, product_id=1, quantity=100))
                session.add(PresetModel(id=1, product_id=1, process_type='电绣',
                                        sort_order=0, is_active=True))
                await session.commit()

            async with session_factory() as session:
                rows = await list_unshipped_processes(session)

            assert [(r['process_type'], r['target_qty'], r['shipped_qty'], r['remaining'])
                    for r in rows] == [
                ('电绣', 100, 0, 100),
            ]
        finally:
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_dirty_null_item_instance_on_new_order_not_listed(self, tmp_path):
        """订单已有 SKU 明细而实例 order_item_id 为空（脏数据）：_process_target_quantity
        对其 fail-closed 拒发，未到货清单同样不把它当旧单欠货列出。"""
        from fastapi_app.services.outsource_service import list_unshipped_processes
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
                session.add(ProductModel(id=1, name='新SKU', factory='湖北'))
                session.add(OrderModel(id=1, order_no='PO-1', customer='贝乐客户',
                                       product_id=1, quantity=100))
                session.add(OrderItemModel(id=10, order_id=1, product_id=1, quantity=100))
                session.add(OrderOutsourceProcess(
                    id=1, order_id=1, order_item_id=None, product_id=1, product_name='新SKU',
                    process_type='电绣', sort_order=0, status='pending',
                ))
                await session.commit()

            async with session_factory() as session:
                rows = await list_unshipped_processes(session)

            assert rows == []
        finally:
            await engine.dispose()
