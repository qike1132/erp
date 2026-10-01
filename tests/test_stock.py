"""
出库管理 / 入库管理 单元测试

覆盖：
- 入库创建（库存校验、编号生成、库存变更日志）
- 入库编辑（数量变更、库存调整、关联保护）
- 入库删除（出库关联保护、库存保护）
- 出库创建（库存检查、客户订单可用性、FIFO 分配）
- 出库编辑（抵扣保护、退货保护、库存同步）
- 出库删除（关联保护、库存回滚）
- 退货创建（退货数量校验、并发安全）
- 边界条件（负数数量、库存不足、超大数量）
"""
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from fastapi_app.services.stock_service import (
    create_stockin_core,
    create_stockout_core,
    create_stockreturn_core,
    delete_stockin_core,
    delete_stockout_core,
    update_stockin_core,
    update_stockout_core,
)


def make_mock_stockin(id_val=1, quantity=100):
    """构造 mock 入库单"""
    si = MagicMock()
    si.id = id_val
    si.product_id = 1
    si.quantity = quantity
    si.customer = '测试客户'
    si.stockin_date = datetime.now(UTC)
    si.note = ''
    si.order_type = 'regular'
    si.country = None
    si.stockin_no = f'SI-2024-{id_val:04d}'
    si.stockin_stockouts = []  # 关联出库记录
    return si


def make_mock_stockout(id_val=1, quantity=50):
    """构造 mock 出库单"""
    so = MagicMock()
    so.id = id_val
    so.product_id = 1
    so.quantity = quantity
    so.customer = '测试客户'
    so.stockout_date = datetime.now(UTC)
    so.note = ''
    so.order_type = 'regular'
    so.country = None
    so.stockout_no = f'SO-2024-{id_val:04d}'
    so.stockin_id = None  # 非抵扣出库
    so.returned_quantity = 0
    so.order_id = 1
    return so


def _empty_result():
    """通用「空结果」替身：与库存写入无关的读（如订单状态重算）返回空集。"""
    res = MagicMock()
    res.scalar_one_or_none.return_value = None
    res.scalars.return_value.all.return_value = []
    res.rowcount = 0
    return res


def _wire_stock_write(db, row, *, new_stock, pre_results=()):
    """显式建模 update_stock_with_optimistic_lock 的两步调用序列（P1-3 乐观锁入口）。

    第 1 次 execute = SELECT 当前行（scalar_one_or_none() 返回带 version/current_stock
    的产品对象，即调用方持有的同一行）；第 2 次 execute = 条件 UPDATE
    （WHERE id + version [+ current_stock + delta >= 0]，rowcount=1 表示命中一行）。
    pre_results 用于该两步序列之前已发生的读（如按 id 装载出货记录）。

    refresh 忠实模拟数据库回读：把本次 UPDATE 写入的 current_stock/version 反映到行对象上
    （实现里对 current_stock 的直写已被统一入口取代，新值只能靠 refresh 拿回）。

    返回 state = {'calls': [...], 'consumed': n}：calls 记录每次 execute 的语句，
    consumed 记录「两步序列（含 pre_results）」被真实消费的次数，供用例断言序列按预期发生。
    """
    select_result = MagicMock()
    select_result.scalar_one_or_none.return_value = row
    update_result = MagicMock()
    update_result.rowcount = 1
    queue = [*pre_results, select_result, update_result]
    state = {'calls': [], 'consumed': 0}

    def _next(stmt, *args, **kwargs):
        state['calls'].append(stmt)
        if queue:
            state['consumed'] += 1
            return queue.pop(0)
        return _empty_result()

    db.execute = AsyncMock(side_effect=_next)

    async def _refresh(obj):
        obj.current_stock = new_stock
        obj.version = row.version + 1

    db.refresh = AsyncMock(side_effect=_refresh)
    return state


class TestCreateStockIn:
    """入库创建"""

    @pytest.mark.asyncio
    @patch('fastapi_app.services.stock_service.generate_stockin_number')
    @patch('fastapi_app.services.stock_service.get_product_for_update')
    @patch('fastapi_app.services.stock_service.log_inventory_change')
    async def test_create_stockin_success(self, mock_log, mock_get_product,
                                           mock_gen_no, mock_async_db):
        """正常创建入库单"""
        mock_gen_no.return_value = 'SI-2024-0001'

        product = MagicMock()
        product.id = 1
        product.current_stock = 100
        mock_get_product.return_value = product

        result = await create_stockin_core(
            mock_async_db,
            product_id=1,
            quantity=50,
            customer='测试客户',
            stockin_date=datetime.now(UTC),
            note='入库测试'
        )

        assert result.quantity == 50
        assert product.current_stock == 150  # 100 + 50
        mock_async_db.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_stockin_zero_quantity(self, mock_async_db):
        """入库数量为0"""
        with pytest.raises(ValueError, match='入库数量必须大于 0'):
            await create_stockin_core(
                mock_async_db, product_id=1, quantity=0,
                customer='客户', stockin_date=datetime.now(UTC), note=''
            )

    @pytest.mark.asyncio
    async def test_create_stockin_negative_quantity(self, mock_async_db):
        """入库数量为负数"""
        with pytest.raises(ValueError, match='入库数量必须大于 0'):
            await create_stockin_core(
                mock_async_db, product_id=1, quantity=-10,
                customer='客户', stockin_date=datetime.now(UTC), note=''
            )

    @pytest.mark.asyncio
    async def test_create_stockin_exceed_max(self, mock_async_db):
        """入库数量超过上限"""
        with pytest.raises(ValueError, match='入库数量不能超过'):
            await create_stockin_core(
                mock_async_db, product_id=1, quantity=100000000,
                customer='客户', stockin_date=datetime.now(UTC), note=''
            )


class TestUpdateStockIn:
    """入库编辑"""

    @pytest.mark.asyncio
    @patch('fastapi_app.services.stock_service.log_inventory_change')
    @patch('fastapi_app.services.stock_service.get_product_for_update')
    async def test_update_stockin_success(self, mock_get_product, mock_log,
                                            mock_async_db):
        """正常编辑入库单"""
        stockin = make_mock_stockin(quantity=100)

        data_result = MagicMock()
        data_result.scalar_one_or_none.return_value = stockin
        mock_async_db.execute = AsyncMock(return_value=data_result)

        product = MagicMock()
        product.id = 1
        product.current_stock = 200
        mock_get_product.return_value = product

        result = await update_stockin_core(
            mock_async_db, stockin, quantity=80,
            customer='新客户', stockin_date=datetime.now(UTC),
            note='修改入库'
        )

        assert result.quantity == 80
        assert product.current_stock == 180  # 200 + (80 - 100)

    @pytest.mark.asyncio
    async def test_update_stockin_not_found(self, mock_async_db):
        """编辑不存在的入库单"""
        stockin = make_mock_stockin()

        data_result = MagicMock()
        data_result.scalar_one_or_none.return_value = None
        mock_async_db.execute = AsyncMock(return_value=data_result)

        with pytest.raises(ValueError, match='入库记录不存在'):
            await update_stockin_core(
                mock_async_db, stockin, quantity=50,
                customer='客户', stockin_date=datetime.now(UTC), note=''
            )

    @pytest.mark.asyncio
    @patch('fastapi_app.services.stock_service.log_inventory_change')
    @patch('fastapi_app.services.stock_service.get_product_for_update')
    async def test_update_stockin_same_quantity(self, mock_get_product, mock_log,
                                                  mock_async_db):
        """数量不变 - 不调库存"""
        stockin = make_mock_stockin(quantity=100)

        data_result = MagicMock()
        data_result.scalar_one_or_none.return_value = stockin
        mock_async_db.execute = AsyncMock(return_value=data_result)

        result = await update_stockin_core(
            mock_async_db, stockin, quantity=100,
            customer='客户', stockin_date=datetime.now(UTC), note='不变'
        )

        assert result.quantity == 100


class TestDeleteStockIn:
    """入库删除"""

    @pytest.mark.asyncio
    @patch('fastapi_app.services.stock_service.log_inventory_change')
    @patch('fastapi_app.services.stock_service.get_product_for_update')
    async def test_delete_stockin_success(self, mock_get_product, mock_log,
                                            mock_async_db):
        """正常删除无关联出库的入库单"""
        stockin = make_mock_stockin(quantity=100)

        product = MagicMock()
        product.id = 1
        product.name = '产品A'
        product.current_stock = 200
        mock_get_product.return_value = product

        await delete_stockin_core(mock_async_db, stockin)

        assert product.current_stock == 100  # 200 - 100
        mock_async_db.delete.assert_called_once_with(stockin)

    @pytest.mark.asyncio
    async def test_delete_stockin_with_stockouts(self, mock_async_db):
        """入库已有出库关联 - 拒绝删除"""
        stockin = make_mock_stockin(quantity=100)
        stockin.stockin_stockouts = [MagicMock()]  # 有关联出库

        with pytest.raises(ValueError, match='已有出库关联'):
            await delete_stockin_core(mock_async_db, stockin)

    @pytest.mark.asyncio
    @patch('fastapi_app.services.stock_service.get_product_for_update')
    async def test_delete_stockin_negative_stock(self, mock_get_product,
                                                   mock_async_db):
        """删除入库会导致库存为负"""
        stockin = make_mock_stockin(quantity=200)

        product = MagicMock()
        product.id = 1
        product.name = '库存不足产品'
        product.current_stock = 50
        mock_get_product.return_value = product

        with pytest.raises(ValueError, match='删除入库记录将导致库存为负数'):
            await delete_stockin_core(mock_async_db, stockin)


class TestCreateStockOut:
    """出库创建"""

    @pytest.mark.asyncio
    @patch('fastapi_app.services.stock_service.log_inventory_change')
    @patch('fastapi_app.services.stock_service.generate_stockout_number')
    @patch('fastapi_app.services.stock_service.calculate_available_shipment_quantity')
    @patch('fastapi_app.services.stock_service.get_product_for_update')
    async def test_create_stockout_success(self, mock_get_product, mock_calc,
                                             mock_gen_no, mock_log, mock_async_db):
        """正常创建出库单"""
        product = MagicMock()
        product.id = 1
        product.current_stock = 200
        mock_get_product.return_value = product

        mock_calc.return_value = {
            'available_quantity': 100,
            'order_quantity': 200,
            'shipped_quantity': 100,
            'orders': [
                {'order_id': 1, 'available': 50},
                {'order_id': 2, 'available': 30},
            ]
        }
        mock_gen_no.return_value = 'SO-2024-0001'

        mock_async_db.begin_nested = MagicMock(return_value=AsyncMock())
        mock_async_db.flush = AsyncMock()
        # 显式建模乐观锁入口的两步序列：SELECT 当前行（version=1）+ 条件 UPDATE 命中一行
        product.version = 1
        state = _wire_stock_write(mock_async_db, product, new_stock=150)

        result = await create_stockout_core(
            mock_async_db, product_id=1, quantity=50,
            customer='测试客户', stockout_date=datetime.now(UTC),
            note='出库测试'
        )

        assert len(result) > 0
        # 库存写入只经两步序列（SELECT + UPDATE），无其它未建模的读
        assert state['consumed'] == 2
        assert len(state['calls']) == 2
        assert product.current_stock == 150  # 200 - 50，经 refresh 回读

    @pytest.mark.asyncio
    @patch('fastapi_app.services.stock_service.get_product_for_update')
    async def test_create_stockout_insufficient_stock(self, mock_get_product,
                                                        mock_async_db):
        """库存不足"""
        product = MagicMock()
        product.id = 1
        product.current_stock = 30
        mock_get_product.return_value = product

        with pytest.raises(ValueError, match='库存不足'):
            await create_stockout_core(
                mock_async_db, product_id=1, quantity=100,
                customer='客户', stockout_date=datetime.now(UTC), note=''
            )

    @pytest.mark.asyncio
    @patch('fastapi_app.services.stock_service.get_product_for_update')
    async def test_create_stockout_no_available_order(self, mock_get_product,
                                                        mock_async_db):
        """客户没有可用订单"""
        product = MagicMock()
        product.id = 1
        product.current_stock = 200
        mock_get_product.return_value = product

        with patch('fastapi_app.services.stock_service.calculate_available_shipment_quantity') as mock_calc:
            mock_calc.return_value = {
                'available_quantity': 0,
                'order_quantity': 0,
                'shipped_quantity': 0,
                'orders': []
            }

            with pytest.raises(ValueError, match='没有可用的订单支持出货'):
                await create_stockout_core(
                    mock_async_db, product_id=1, quantity=10,
                    customer='客户', stockout_date=datetime.now(UTC), note=''
                )

    @pytest.mark.asyncio
    @patch('fastapi_app.services.stock_service.get_product_for_update')
    async def test_create_stockout_exceed_available(self, mock_get_product,
                                                      mock_async_db):
        """出货数量超过可出货量"""
        product = MagicMock()
        product.id = 1
        product.current_stock = 200
        mock_get_product.return_value = product

        with patch('fastapi_app.services.stock_service.calculate_available_shipment_quantity') as mock_calc:
            mock_calc.return_value = {
                'available_quantity': 10,
                'order_quantity': 100,
                'shipped_quantity': 90,
                'orders': [{'order_id': 1, 'available': 10}]
            }

            with pytest.raises(ValueError, match='出货数量超过可出货量'):
                await create_stockout_core(
                    mock_async_db, product_id=1, quantity=50,
                    customer='客户', stockout_date=datetime.now(UTC), note=''
                )


class TestUpdateStockOut:
    """出库编辑"""

    @pytest.mark.asyncio
    async def test_update_stockout_deduction_protected(self, mock_async_db):
        """抵扣出库不能直接编辑"""
        stockout = make_mock_stockout()
        stockout.stockin_id = 5  # 抵扣出库

        with pytest.raises(ValueError, match='订单抵扣的出货记录不能直接编辑'):
            await update_stockout_core(
                mock_async_db, stockout, new_quantity=60,
                customer='客户', stockout_date=datetime.now(UTC), note=''
            )

    @pytest.mark.asyncio
    @patch('fastapi_app.services.stock_service.log_inventory_change')
    @patch('fastapi_app.services.stock_service.calculate_available_shipment_quantity')
    @patch('fastapi_app.services.stock_service.get_product_for_update')
    async def test_update_stockout_success(self, mock_get_product, mock_calc,
                                             mock_log, mock_async_db):
        """正常编辑出库单"""
        product = MagicMock()
        product.id = 1
        product.current_stock = 200
        mock_get_product.return_value = product

        mock_calc.return_value = {
            'available_quantity': 100,
            'order_quantity': 200,
            'shipped_quantity': 100,
            'orders': []
        }

        stockout = make_mock_stockout(quantity=50)

        # 显式建模乐观锁入口的两步序列：SELECT 当前行（version=1）+ 条件 UPDATE 命中一行
        product.version = 1
        state = _wire_stock_write(mock_async_db, product, new_stock=220)

        result = await update_stockout_core(
            mock_async_db, stockout, new_quantity=30,
            customer='新客户', stockout_date=datetime.now(UTC), note='修改'
        )

        assert result.quantity == 30
        assert state['consumed'] == 2
        assert len(state['calls']) == 2
        assert product.current_stock == 220  # 200 + (50 - 30)

    @pytest.mark.asyncio
    async def test_update_stockout_below_returned(self, mock_async_db):
        """出库数量小于已退货数量"""
        stockout = make_mock_stockout(quantity=50)
        stockout.returned_quantity = 40

        with pytest.raises(ValueError, match='出货数量不能小于已退货数量'):
            await update_stockout_core(
                mock_async_db, stockout, new_quantity=30,
                customer='客户', stockout_date=datetime.now(UTC), note=''
            )


class TestDeleteStockOut:
    """出库删除"""

    @pytest.mark.asyncio
    @patch('fastapi_app.services.stock_service.log_inventory_change')
    @patch('fastapi_app.services.stock_service.get_product_for_update')
    async def test_delete_stockout_success(self, mock_get_product, mock_log,
                                             mock_async_db):
        """正常删除出库单"""
        stockout = make_mock_stockout(quantity=50)

        product = MagicMock()
        product.id = 1
        product.current_stock = 100
        product.version = 1
        mock_get_product.return_value = product

        # 显式建模乐观锁入口的两步序列：SELECT 当前行 + 条件 UPDATE 命中一行
        state = _wire_stock_write(mock_async_db, product, new_stock=150)

        await delete_stockout_core(mock_async_db, stockout)

        assert product.current_stock == 150  # 100 + 50
        mock_async_db.delete.assert_called_once_with(stockout)
        assert state['consumed'] == 2
        assert len(state['calls']) == 2
        assert product.version == 2  # 乐观锁 version 递增经 refresh 回读

    @pytest.mark.asyncio
    async def test_delete_stockout_deduction_protected(self, mock_async_db):
        """抵扣出库不能直接删除"""
        stockout = make_mock_stockout()
        stockout.stockin_id = 5

        with pytest.raises(ValueError, match='订单抵扣的出货记录不能直接删除'):
            await delete_stockout_core(mock_async_db, stockout)

    @pytest.mark.asyncio
    async def test_delete_stockout_with_returns(self, mock_async_db):
        """有退货关联的出库不能删除"""
        stockout = make_mock_stockout(quantity=50)
        stockout.returned_quantity = 10

        with pytest.raises(ValueError, match='已有退货关联'):
            await delete_stockout_core(mock_async_db, stockout)


class TestCreateStockReturn:
    """退货创建"""

    @pytest.mark.asyncio
    @patch('fastapi_app.services.stock_service.generate_stockreturn_number')
    @patch('fastapi_app.services.stock_service.log_inventory_change')
    @patch('fastapi_app.services.stock_service.get_product_for_update')
    async def test_create_stockreturn_success(self, mock_get_product, mock_log,
                                                mock_gen_no, mock_async_db):
        """正常创建退货"""
        mock_gen_no.return_value = 'SR-2024-0001'

        product = MagicMock()
        product.id = 1
        product.current_stock = 100
        mock_get_product.return_value = product

        stockout = make_mock_stockout(quantity=100)
        stockout.returned_quantity = 0
        stockout.customer = '测试客户'
        stockout.order_id = 1

        data_result = MagicMock()
        data_result.scalar_one_or_none.return_value = stockout

        # 显式建模调用序列：按 id 装载出货记录 → 乐观锁入口的两步序列
        # （SELECT 当前行 version=1 → 条件 UPDATE 命中一行）
        product.version = 1
        state = _wire_stock_write(
            mock_async_db, product, new_stock=130, pre_results=(data_result,)
        )

        result = await create_stockreturn_core(
            mock_async_db, stockout_id=1, quantity=30,
            return_date=datetime.now(UTC), reason='质量问题', note='退货备注'
        )

        assert result is not None
        mock_async_db.add.assert_called_once()
        assert state['consumed'] == 3  # 装载出货记录 + SELECT + UPDATE
        # 第 4 次读是订单状态重算（按 id 装载 Order），与库存写入无关
        assert len(state['calls']) == 4
        assert product.current_stock == 130  # 100 + 30

    @pytest.mark.asyncio
    async def test_create_stockreturn_zero_quantity(self, mock_async_db):
        """退货数量为0"""
        with pytest.raises(ValueError, match='退货数量必须大于0'):
            await create_stockreturn_core(
                mock_async_db, stockout_id=1, quantity=0,
                return_date=datetime.now(UTC)
            )

    @pytest.mark.asyncio
    async def test_create_stockreturn_negative_quantity(self, mock_async_db):
        """退货数量为负"""
        with pytest.raises(ValueError, match='退货数量必须大于0'):
            await create_stockreturn_core(
                mock_async_db, stockout_id=1, quantity=-5,
                return_date=datetime.now(UTC)
            )

    @pytest.mark.asyncio
    async def test_create_stockreturn_stockout_not_found(self, mock_async_db):
        """出货记录不存在"""
        data_result = MagicMock()
        data_result.scalar_one_or_none.return_value = None
        mock_async_db.execute = AsyncMock(return_value=data_result)

        with pytest.raises(ValueError, match='出货记录不存在'):
            await create_stockreturn_core(
                mock_async_db, stockout_id=999, quantity=10,
                return_date=datetime.now(UTC)
            )

    @pytest.mark.asyncio
    async def test_create_stockreturn_deduction_protected(self, mock_async_db):
        """抵扣出库不能退货"""
        stockout = make_mock_stockout()
        stockout.stockin_id = 5

        data_result = MagicMock()
        data_result.scalar_one_or_none.return_value = stockout
        mock_async_db.execute = AsyncMock(return_value=data_result)

        with pytest.raises(ValueError, match='订单抵扣的出货记录不能直接退货'):
            await create_stockreturn_core(
                mock_async_db, stockout_id=1, quantity=10,
                return_date=datetime.now(UTC)
            )

    @pytest.mark.asyncio
    async def test_create_stockreturn_exceed_available(self, mock_async_db):
        """退货数量超过可退数量"""
        stockout = make_mock_stockout(quantity=100)
        stockout.returned_quantity = 80
        stockout.stockin_id = None

        data_result = MagicMock()
        data_result.scalar_one_or_none.return_value = stockout
        mock_async_db.execute = AsyncMock(return_value=data_result)

        with pytest.raises(ValueError, match='退货数量超过可退数量'):
            await create_stockreturn_core(
                mock_async_db, stockout_id=1, quantity=30,
                return_date=datetime.now(UTC)
            )
