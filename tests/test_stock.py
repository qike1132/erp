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


@pytest.fixture(autouse=True)
def _default_inventory_balance():
    """库存结余闸门（2026-10-07）默认充足，使既有出库用例聚焦各自语义。"""
    with patch(
        'fastapi_app.services.stock_service.get_inventory_balance',
        new_callable=AsyncMock, return_value=10**9,
    ):
        yield


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


def _assert_optimistic_lock_write(state):
    """断言乐观锁写入口的**序性质**（2026-10-15 去过度指定）。

    此前用例断言 ``consumed == N`` / ``len(calls) == N`` 的精确计数——任何在
    写路径上新增一次合法读（如状态重算）都会假红，属 Fragile Test
    （xUnit Test Patterns: Overspecified Software）。真正要守住的行为是：
    库存只经「SELECT 产品行 → 条件 UPDATE」这一序写入，且 UPDATE 恰好一次
    （乐观锁单轮写不重复）。最终库存/版本号由各用例的 result 断言覆盖。
    """
    texts = [str(call) for call in state['calls']]
    reads = [i for i, t in enumerate(texts)
             if t.lstrip().upper().startswith('SELECT') and 'FROM product' in t]
    writes = [i for i, t in enumerate(texts)
              if t.lstrip().upper().startswith('UPDATE') and 'UPDATE product' in t]
    assert len(writes) == 1, f'库存 UPDATE 应恰好一次: {texts}'
    assert reads, f'缺少产品行读取（SELECT ... FROM product）: {texts}'
    assert reads[0] < writes[0], f'必须先读行再写（乐观锁序）: {texts}'


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
        # 库存写入经乐观锁序（SELECT 行 → 条件 UPDATE），不做精确计数断言
        _assert_optimistic_lock_write(state)
        assert product.current_stock == 150  # 200 - 50，经 refresh 回读

    @pytest.mark.asyncio
    @patch('fastapi_app.services.stock_service.log_inventory_change')
    @patch('fastapi_app.services.stock_service.generate_stockout_number')
    @patch('fastapi_app.services.stock_service.calculate_available_shipment_quantity')
    @patch('fastapi_app.services.stock_service.get_product_for_update')
    async def test_create_stockout_current_stock_guard_deferred_to_write_entry(
            self, mock_get_product, mock_calc, mock_gen_no, mock_log, mock_async_db):
        """current_stock 低于出货量不再由前置断言拒绝（2026-10-07 与批量路径统一），
        改由写入口 update_stock_with_optimistic_lock 的负库存守卫拒绝。"""
        product = MagicMock()
        product.id = 1
        product.name = '产品A'
        product.current_stock = 30
        mock_get_product.return_value = product
        mock_calc.return_value = {
            'available_quantity': 200, 'order_quantity': 200, 'shipped_quantity': 0,
            'orders': [{'order_id': 1, 'available': 200}],
        }
        mock_gen_no.return_value = 'SO-1'
        mock_async_db.begin_nested = MagicMock(return_value=AsyncMock())

        with patch('fastapi_app.services.stock_out_service.update_stock_with_optimistic_lock',
                   new_callable=AsyncMock,
                   side_effect=ValueError('库存不足！当前库存: 30，需要: 100')):
            with pytest.raises(ValueError, match='库存不足'):
                await create_stockout_core(
                    mock_async_db, product_id=1, quantity=100,
                    customer='客户', stockout_date=datetime.now(UTC), note=''
                )

    @pytest.mark.asyncio
    @patch('fastapi_app.services.stock_service.get_product_for_update')
    async def test_create_stockout_inventory_balance_insufficient(self, mock_get_product,
                                                                    mock_async_db):
        """库存结余不足（2026-10-07 闸门）：拒绝，文案含客户/产品/可用/本次"""
        product = MagicMock()
        product.id = 1
        product.name = '产品A'
        product.current_stock = 200
        mock_get_product.return_value = product

        with patch('fastapi_app.services.stock_service.get_inventory_balance',
                   new_callable=AsyncMock, return_value=8):
            with pytest.raises(ValueError) as ei:
                await create_stockout_core(
                    mock_async_db, product_id=1, quantity=10,
                    customer='客户A', stockout_date=datetime.now(UTC), note=''
                )
        assert str(ei.value) == '客户「客户A」产品「产品A」库存不足：可用 8，本次 10'

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
    @patch('fastapi_app.services.stock_service.get_product_for_update')
    async def test_update_stockout_deduction_over_stockin_protected(self, mock_get_product, mock_async_db):
        """抵扣出库已允许直接编辑，但新抵扣量不得超过所属备货可用量（2026-10-07 放开）"""
        product = MagicMock()
        product.id = 1
        product.current_stock = 200
        mock_get_product.return_value = product

        stockout = make_mock_stockout()
        stockout.stockin_id = 5  # 抵扣出库
        # db.get(StockIn, 5) → 备货总量 5；已被其它抵扣行占用 0
        mock_async_db.get.return_value = MagicMock(quantity=5)
        occupied = MagicMock()
        occupied.scalar.return_value = 0
        mock_async_db.execute.return_value = occupied

        with pytest.raises(ValueError, match='抵扣数量超过'):
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
        _assert_optimistic_lock_write(state)
        assert product.current_stock == 220  # 200 + (50 - 30)

    @pytest.mark.asyncio
    @patch('fastapi_app.services.stock_service.log_inventory_change')
    @patch('fastapi_app.services.stock_service.calculate_available_shipment_quantity')
    @patch('fastapi_app.services.stock_service.get_product_for_update')
    async def test_update_stockout_reduce_beyond_current_stock(self, mock_get_product,
                                                                mock_calc, mock_log,
                                                                mock_async_db):
        """调小出库量、且回补幅度大于当前库存时应当放行（回归 H-1）。

        库存为 0、出库单 100 改为 50：这是回补 50 件库存的合法操作。
        缺陷版本把 delta 传成 (new - returned) - old_net（= -50），
        与真实库存变化 -(new - old)（= +50）符号相反，于是误抛「库存不足！」。
        该场景此前无测试覆盖（test_update_stockout_success 用 200/50/30 大库存恰好绕过）。
        """
        product = MagicMock()
        product.id = 1
        product.current_stock = 0
        mock_get_product.return_value = product

        mock_calc.return_value = {
            'available_quantity': 100,
            'order_quantity': 200,
            'shipped_quantity': 100,
            'orders': []
        }

        stockout = make_mock_stockout(quantity=100)

        product.version = 1
        state = _wire_stock_write(mock_async_db, product, new_stock=50)

        result = await update_stockout_core(
            mock_async_db, stockout, new_quantity=50,
            customer='客户', stockout_date=datetime.now(UTC), note=''
        )

        assert result.quantity == 50
        _assert_optimistic_lock_write(state)
        assert product.current_stock == 50  # 0 + (100 - 50)

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

        # P1 守卫前置查询：关联退货计数返回 0（scalar() 为 0 → falsy 放行）
        linked_result = MagicMock()
        linked_result.scalar.return_value = 0
        # 显式建模乐观锁入口的两步序列：SELECT 当前行 + 条件 UPDATE 命中一行
        state = _wire_stock_write(
            mock_async_db, product, new_stock=150, pre_results=(linked_result,)
        )

        await delete_stockout_core(mock_async_db, stockout)

        assert product.current_stock == 150  # 100 + 50
        mock_async_db.delete.assert_called_once_with(stockout)
        # 写入经乐观锁序（退货计数读 → SELECT 行 → UPDATE），不做精确计数断言
        _assert_optimistic_lock_write(state)
        assert product.version == 2  # 乐观锁 version 递增经 refresh 回读

    @pytest.mark.asyncio
    @patch('fastapi_app.services.stock_service.log_inventory_change')
    @patch('fastapi_app.services.stock_out_service.update_stock_with_optimistic_lock')
    @patch('fastapi_app.services.stock_service.get_product_for_update')
    async def test_delete_stockout_deduction_now_allowed(self, mock_get_product, mock_update, mock_log, mock_async_db):
        """抵扣出库已允许直接删除（2026-10-07 放开；所属备货可用量随之释放）"""
        product = MagicMock()
        product.current_stock = 200
        mock_get_product.return_value = product
        mock_update.return_value = product

        stockout = make_mock_stockout()
        stockout.stockin_id = 5
        stockout.returned_quantity = 0
        # 无关联退货：count 查询返回 0
        linked = MagicMock()
        linked.scalar.return_value = 0
        mock_async_db.execute.return_value = linked

        await delete_stockout_core(mock_async_db, stockout)

        mock_async_db.delete.assert_awaited()

    @pytest.mark.asyncio
    async def test_delete_stockout_with_returns(self, mock_async_db):
        """有退货关联的出库不能删除"""
        stockout = make_mock_stockout(quantity=50)
        stockout.returned_quantity = 10

        with pytest.raises(ValueError, match='已有退货关联'):
            await delete_stockout_core(mock_async_db, stockout)


class TestCreateStockReturn:
    """退货创建（按出货明细：可退量 = 出货量 - 已退量）"""

    @pytest.mark.asyncio
    @patch('fastapi_app.services.stock_service.generate_stockreturn_number')
    @patch('fastapi_app.services.stock_service.log_inventory_change')
    @patch('fastapi_app.services.stock_service.get_product_for_update')
    async def test_create_stockreturn_success(self, mock_get_product, mock_log,
                                                mock_gen_no, mock_async_db):
        """正常创建：数量落在所选出货明细的已退量上"""
        mock_gen_no.return_value = 'SR-2024-0001'
        product = MagicMock()
        product.id = 1
        product.current_stock = 100
        product.version = 1
        product.name = '测试产品'
        mock_get_product.return_value = product

        stockout = make_mock_stockout(quantity=50)
        stockout.returned_quantity = 0
        stockout.customer = '测试客户'
        stockout.order_id = 1

        pid_result = MagicMock(); pid_result.one_or_none.return_value = (1,)
        data_result = MagicMock(); data_result.scalar_one_or_none.return_value = stockout
        state = _wire_stock_write(
            mock_async_db, product, new_stock=130, pre_results=(pid_result, data_result)
        )

        result = await create_stockreturn_core(
            mock_async_db, stockout_id=1, quantity=30,
            return_date=datetime.now(UTC), reason='质量问题', note='退货备注',
        )

        assert result is not None
        mock_async_db.add.assert_called_once()
        _assert_optimistic_lock_write(state)
        assert stockout.returned_quantity == 30
        assert product.current_stock == 130

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
        pid_result = MagicMock(); pid_result.one_or_none.return_value = None
        mock_async_db.execute = AsyncMock(return_value=pid_result)

        with pytest.raises(ValueError, match='出货记录不存在'):
            await create_stockreturn_core(
                mock_async_db, stockout_id=999, quantity=10,
                return_date=datetime.now(UTC)
            )



    @pytest.mark.asyncio
    @patch('fastapi_app.services.stock_service.generate_stockreturn_number')
    @patch('fastapi_app.services.stock_service.log_inventory_change')
    @patch('fastapi_app.services.stock_service.get_product_for_update')
    async def test_create_stockreturn_request_id_dedup(self, mock_get_product, mock_log,
                                                        mock_gen_no, mock_async_db):
        """P1-③ 幂等：同 request_id 已登记过（流水命中）→ 拒绝"""
        product = MagicMock()
        product.id = 1
        product.current_stock = 100
        product.version = 1
        mock_get_product.return_value = product

        stockout = make_mock_stockout(quantity=50)
        stockout.returned_quantity = 0
        stockout.order_id = None

        pid_result = MagicMock(); pid_result.one_or_none.return_value = (1,)
        data_result = MagicMock(); data_result.scalar_one_or_none.return_value = stockout
        dup_result = MagicMock(); dup_result.first.return_value = (99,)
        mock_async_db.execute = AsyncMock(side_effect=[pid_result, data_result, dup_result])

        with pytest.raises(ValueError, match='请勿重复提交'):
            await create_stockreturn_core(
                mock_async_db, stockout_id=1, quantity=10,
                return_date=datetime.now(UTC), request_id='req-dedup-0001'
            )
