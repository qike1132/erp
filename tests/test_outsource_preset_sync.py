"""
湖北外发：未到货明细聚合、按产品同步订单工序、SKU 工序预设唯一冲突。

从 test_outsource.py 拆出（file_size_gate 阈值 1600 行）；断言逻辑一行未改。
"""
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from test_outsource import make_preset

from fastapi_app.services.outsource_service import (
    list_unshipped_processes,
)
from fastapi_app.shared_models import OrderOutsourceProcess


class TestListUnshippedProcesses:
    """未到货（未发完）工序明细聚合"""

    @pytest.mark.asyncio
    async def test_remaining_is_target_minus_shipped(self, mock_async_db):
        """未到数量 = 订单数量 - 已发数量"""
        row = SimpleNamespace(
            order_id=1, order_no='HB001', customer='客户A',
            order_date=datetime(2026, 1, 2, 2, 30, tzinfo=UTC),  # UTC 02:30
            product_name='测试产品', product_barcode='TEST001',
            process_type='电绣', target_qty=100, shipped_qty=30,
        )
        result = MagicMock()
        result.all.return_value = [row]
        mock_async_db.execute = AsyncMock(return_value=result)

        items = await list_unshipped_processes(mock_async_db)

        assert len(items) == 1
        assert items[0]['order_no'] == 'HB001'
        assert items[0]['target_qty'] == 100
        assert items[0]['shipped_qty'] == 30
        assert items[0]['remaining'] == 70
        # 下单时间按北京时间展示（与 beile-list 同口径）：UTC 02:30 → 北京 10:30
        assert items[0]['order_date'] == '2026-01-02 10:30'

    @pytest.mark.asyncio
    async def test_empty_result(self, mock_async_db):
        """无未发完工序时返回空列表"""
        result = MagicMock()
        result.all.return_value = []
        mock_async_db.execute = AsyncMock(return_value=result)

        items = await list_unshipped_processes(mock_async_db)

        assert items == []

    @pytest.mark.asyncio
    async def test_processes_source_is_presets_not_instances(self, tmp_path):
        """工序以 SKU 预设为准（回归）：实例多出的工序不导出、预设缺失的工序仍导出。

        修复前导出读 order_outsource_process（下单时的工序实例快照，与预设脱节）；
        修复后以 outsource_process_type（当前预设，is_active）为准，已发数量左连接实例。
        """
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        from fastapi_app.shared_models import (
            Order as OrderModel,
        )
        from fastapi_app.shared_models import (
            OrderItem as OrderItemModel,
        )
        from fastapi_app.shared_models import (
            OutsourceProcessType,
        )
        from fastapi_app.shared_models import (
            Product as ProductModel,
        )

        engine = create_async_engine(f'sqlite+aiosqlite:///{tmp_path / "unshipped.db"}')
        try:
            async with engine.begin() as conn:
                for table in (
                    ProductModel.__table__, OrderModel.__table__, OrderItemModel.__table__,
                    OutsourceProcessType.__table__, OrderOutsourceProcess.__table__,
                ):
                    await conn.run_sync(lambda c, t=table: t.create(c, checkfirst=True))

            session_factory = async_sessionmaker(engine, expire_on_commit=False)
            async with session_factory() as session:
                session.add(ProductModel(id=1, name='测试SKU', barcode='6978946330588', factory='湖北'))
                session.add(OrderModel(
                    id=1, order_no='PO-1', customer='客户A',
                    order_date=datetime(2026, 1, 2, 2, 30, tzinfo=UTC), product_id=1, quantity=100,
                ))
                session.add(OrderItemModel(id=1, order_id=1, product_id=1, quantity=100))
                # 预设只有「电绣」「转印」
                session.add(OutsourceProcessType(id=1, product_id=1, process_type='电绣', sort_order=1, is_active=True))
                session.add(OutsourceProcessType(id=2, product_id=1, process_type='转印', sort_order=2, is_active=True))
                # 订单实例与预设不一致：裁剪/电绣(已全发)/缝制
                session.add(OrderOutsourceProcess(
                    id=1, order_id=1, order_item_id=1, product_id=1, product_name='测试SKU',
                    process_type='裁剪', sort_order=0, status='pending',
                ))
                session.add(OrderOutsourceProcess(
                    id=2, order_id=1, order_item_id=1, product_id=1, product_name='测试SKU',
                    process_type='电绣', sort_order=0, status='received',
                    shipped_quantity=100, received_quantity=100,
                ))
                session.add(OrderOutsourceProcess(
                    id=3, order_id=1, order_item_id=1, product_id=1, product_name='测试SKU',
                    process_type='缝制', sort_order=0, status='pending',
                ))
                await session.commit()

            async with session_factory() as session:
                rows = await list_unshipped_processes(session)

            procs = [r['process_type'] for r in rows]
            # 预设「电绣」全发（100/100）→ 排除；预设「转印」无实例 → 保留且已发 0
            assert procs == ['转印']
            assert rows[0]['shipped_qty'] == 0
            assert rows[0]['remaining'] == 100
            # 实例特有工序（裁剪/缝制）不属于预设，不得出现在导出中
            assert '裁剪' not in procs
            assert '缝制' not in procs
        finally:
            await engine.dispose()


class TestSyncOrdersForProduct:
    """预设变更后自动同步订单实例：新增补齐、仅删未发货、已发货保留"""

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
            OutsourceProcessType,
        )
        from fastapi_app.shared_models import (
            Product as ProductModel,
        )
        engine = create_async_engine(f'sqlite+aiosqlite:///{tmp_path / "sync.db"}')
        async with engine.begin() as conn:
            for table in (
                ProductModel.__table__, OrderModel.__table__, OrderItemModel.__table__,
                OutsourceProcessType.__table__, OrderOutsourceProcess.__table__,
            ):
                await conn.run_sync(lambda c, t=table: t.create(c, checkfirst=True))
        return engine, async_sessionmaker(engine, expire_on_commit=False)

    @staticmethod
    def _seed(session):
        """预设=电绣/转印；实例=电绣(已发100) + 裁剪(未发，不在预设)。"""
        from fastapi_app.shared_models import (
            Order as OrderModel,
        )
        from fastapi_app.shared_models import (
            OrderItem as OrderItemModel,
        )
        from fastapi_app.shared_models import (
            OutsourceProcessType,
        )
        from fastapi_app.shared_models import (
            Product as ProductModel,
        )
        session.add(ProductModel(id=1, name='SKU1', factory='湖北'))
        session.add(OrderModel(id=1, order_no='PO-1', customer='C', product_id=1, quantity=100))
        session.add(OrderItemModel(id=10, order_id=1, product_id=1, quantity=100))
        session.add(OutsourceProcessType(id=1, product_id=1, process_type='电绣', sort_order=1, is_active=True))
        session.add(OutsourceProcessType(id=2, product_id=1, process_type='转印', sort_order=2, is_active=True))
        session.add(OrderOutsourceProcess(
            id=1, order_id=1, order_item_id=10, product_id=1, product_name='SKU1',
            process_type='电绣', sort_order=1, status='shipped', shipped_quantity=100,
        ))
        session.add(OrderOutsourceProcess(
            id=2, order_id=1, order_item_id=10, product_id=1, product_name='SKU1',
            process_type='裁剪', sort_order=0, status='pending',
        ))

    @pytest.mark.asyncio
    async def test_add_missing_and_remove_unshipped(self, tmp_path):
        """同步：补预设缺失工序、删未发货的非预设工序、保留已发货的非预设工序"""
        from sqlalchemy import select

        from fastapi_app.services.outsource_service import sync_orders_for_product
        from fastapi_app.shared_models import OutsourceProcessType

        engine, session_factory = await self._session(tmp_path)
        try:
            async with session_factory() as session:
                self._seed(session)
                await session.commit()

            async with session_factory() as session:
                stats = await sync_orders_for_product(session, 1)
                await session.commit()
                # 新增「转印」；移除未发货的「裁剪」；「电绣」在预设中不动
                assert stats == {'created': 1, 'removed': 1, 'kept': 0}
                procs = (await session.execute(
                    select(OrderOutsourceProcess.process_type)
                )).scalars().all()
                assert sorted(procs) == ['电绣', '转印']

            # 删除预设「电绣」后同步：该实例已发货 → 必须保留，不丢发货流水
            async with session_factory() as session:
                pt = (await session.execute(
                    select(OutsourceProcessType).where(OutsourceProcessType.process_type == '电绣')
                )).scalar_one()
                await session.delete(pt)
                await session.commit()

            async with session_factory() as session:
                stats2 = await sync_orders_for_product(session, 1)
                await session.commit()
                assert stats2 == {'created': 0, 'removed': 0, 'kept': 1}
                procs2 = (await session.execute(
                    select(OrderOutsourceProcess.process_type)
                )).scalars().all()
                assert sorted(procs2) == ['电绣', '转印']
        finally:
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_remove_unshipped_when_preset_deleted(self, tmp_path):
        """预设删除某工序且实例未发货 → 同步删除该实例。"""
        from sqlalchemy import select

        from fastapi_app.services.outsource_service import sync_orders_for_product
        from fastapi_app.shared_models import OutsourceProcessType

        engine, session_factory = await self._session(tmp_path)
        try:
            async with session_factory() as session:
                self._seed(session)
                await session.commit()

            # 先同步（补齐「转印」实例），再删除预设「转印」
            async with session_factory() as session:
                await sync_orders_for_product(session, 1)
                await session.commit()
            async with session_factory() as session:
                pt = (await session.execute(
                    select(OutsourceProcessType).where(OutsourceProcessType.process_type == '转印')
                )).scalar_one()
                await session.delete(pt)
                await session.commit()

            async with session_factory() as session:
                stats = await sync_orders_for_product(session, 1)
                await session.commit()
                assert stats['removed'] == 1
                procs = (await session.execute(
                    select(OrderOutsourceProcess.process_type)
                )).scalars().all()
                assert '转印' not in procs
        finally:
            await engine.dispose()


class TestProcessTypeUniqueConflict:
    """工序预设唯一约束冲突 → 409（审计 #6）

    (product_id, process_type) 上有唯一约束 uq_outsource_pt_product_process。
    服务层「先查后插」是 TOCTOU：并发插入时约束在 flush 处抛 IntegrityError。
    端点若不把它映射成 409，用户看到的是 500（服务器故障），而实际只是
    「有人同时加了同名工序」，刷新即可。
    """

    @staticmethod
    def _conflicting_db(mock_async_db):
        """构造 flush 时抛唯一约束冲突的会话"""
        mock_async_db.flush = AsyncMock(side_effect=IntegrityError(
            'INSERT INTO outsource_process_type',
            params=None,
            orig=Exception('uq_outsource_pt_product_process'),
        ))
        return mock_async_db

    @staticmethod
    def _product():
        product = MagicMock()
        product.id = 1
        product.name = '测试产品'
        return product

    @pytest.mark.asyncio
    async def test_batch_create_maps_conflict_to_409(self, mock_async_db, mock_user):
        """批量创建：并发插入撞唯一约束 → 409，不是 500"""
        from fastapi_app.api.v1.endpoints import outsource as outsource_ep

        db = self._conflicting_db(mock_async_db)
        db.get = AsyncMock(return_value=self._product())
        existing = MagicMock()
        existing.all.return_value = []
        db.execute = AsyncMock(return_value=existing)

        data = outsource_ep.ProcessTypeBatchCreate(product_id=1, process_types=['电绣'])
        with pytest.raises(HTTPException) as exc:
            await outsource_ep.batch_create_process_types(data, db, mock_user)

        assert exc.value.status_code == 409, f'应返回 409，实际 {exc.value.status_code}'
        assert '已存在同名工序' in str(exc.value.detail)

    @pytest.mark.asyncio
    async def test_create_maps_conflict_to_409(self, mock_async_db, mock_user):
        """单条创建：并发插入撞唯一约束 → 409"""
        from fastapi_app.api.v1.endpoints import outsource as outsource_ep

        db = self._conflicting_db(mock_async_db)
        db.get = AsyncMock(return_value=self._product())
        dup = MagicMock()
        dup.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=dup)

        data = outsource_ep.ProcessTypeCreate(product_id=1, process_type='电绣')
        with pytest.raises(HTTPException) as exc:
            await outsource_ep.create_process_type(data, db, mock_user)

        assert exc.value.status_code == 409, f'应返回 409，实际 {exc.value.status_code}'

    @pytest.mark.asyncio
    async def test_update_maps_conflict_to_409(self, mock_async_db, mock_user):
        """改名：撞上其他行同名约束 → 409"""
        from fastapi_app.api.v1.endpoints import outsource as outsource_ep

        db = self._conflicting_db(mock_async_db)
        db.get = AsyncMock(return_value=make_preset(product_id=1, process_type='电绣'))
        dup = MagicMock()
        dup.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=dup)

        data = outsource_ep.ProcessTypeUpdate(process_type='转印')
        with pytest.raises(HTTPException) as exc:
            await outsource_ep.update_process_type(1, data, db, mock_user)

        assert exc.value.status_code == 409, f'应返回 409，实际 {exc.value.status_code}'


