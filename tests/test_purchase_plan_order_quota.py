"""出货计划准入校验（订单余量）单元测试

背景：2026-09 用户裁决 —— 排产日历上的计划只要对应订单还有数量（订单余量 > 0）
就允许添加，不再因库存不足拦截。本文件固化新口径：

    - collect_without_order / format_without_order_error：纯判定与文案（无 DB）
    - get_order_remaining_map：订单量 - 独立出货量，并按 (客户, 产品) 聚合并钳到 0
    - check_order_remaining：把上面两步串起来，返回「无订单余量」的明细行
    - 三个写入路径（create_plan / add_details / confirm_staging）已不再调用
      库存校验 —— 用源码守卫钉住，防止回退

mock 的 db.execute 按语句内容分派（订单聚合 vs 出货聚合），不依赖查询顺序：
一旦实现调整了查询先后，测试不会以「mock 错位」的假失败告终。
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from fastapi_app.services import purchase_plan_order_quota as quota


def _make_rows(pairs):
    """把 [(customer, product_name, qty), ...] 转成属性可访问的行对象"""
    rows = []
    for customer, product_name, qty in pairs:
        row = MagicMock()
        row.customer = customer
        row.product_name = product_name
        row.order_qty = qty
        row.shipped_qty = qty
        rows.append(row)
    return rows


def _make_db(order_rows, shipped_rows):
    """按语句内容分派 execute 的 mock db

    出货查询会取 row.shipped_qty，订单查询取 row.order_qty —— 行对象两个属性
    都带上，避免测试因属性缺失而报 AttributeError 掩盖真实断言。
    """
    async def _execute(stmt, *args, **kwargs):
        sql = str(stmt)
        res = MagicMock()
        res.all.return_value = order_rows if '"order"' in sql else shipped_rows
        return res

    db = MagicMock()
    db.execute = AsyncMock(side_effect=_execute)
    return db


# ============================================================
# collect_without_order —— 纯判定
# ============================================================

class TestCollectWithoutOrder:
    """「无订单余量」明细收集"""

    def test_returns_empty_when_all_have_remaining(self):
        remaining = {('客户A', '产品1'): 10, ('客户B', '产品2'): 5}
        items = [{'customer_name': '客户A', 'product_name': '产品1'}]
        assert quota.collect_without_order(remaining, items) == []

    def test_flags_items_with_zero_remaining(self):
        remaining = {('客户A', '产品1'): 10}
        items = [
            {'customer_name': '客户A', 'product_name': '产品1'},
            {'customer_name': '客户A', 'product_name': '产品2'},
        ]
        assert quota.collect_without_order(remaining, items) == [
            {'customer_name': '客户A', 'product_name': '产品2'},
        ]

    def test_unknown_pair_counts_as_no_remaining(self):
        """查不到订单 = 没有订单余量 = 不可添加"""
        items = [{'customer_name': '客户X', 'product_name': '产品Y'}]
        assert quota.collect_without_order({}, items) == items

    def test_deduplicates_and_keeps_input_order(self):
        items = [
            {'customer_name': '客户B', 'product_name': '产品2'},
            {'customer_name': '客户B', 'product_name': '产品2'},
            {'customer_name': '客户A', 'product_name': '产品1'},
        ]
        assert quota.collect_without_order({}, items) == [
            {'customer_name': '客户B', 'product_name': '产品2'},
            {'customer_name': '客户A', 'product_name': '产品1'},
        ]

    def test_skips_blank_customer_or_product(self):
        """空客户名/空产品名交由 _validate_products_exist 处理，此处不报"""
        items = [
            {'customer_name': '', 'product_name': '产品1'},
            {'customer_name': '客户A', 'product_name': ''},
        ]
        assert quota.collect_without_order({}, items) == []


class TestFormatWithoutOrderError:
    """错误文案"""

    def test_joins_pairs(self):
        missing = [
            {'customer_name': '客户A', 'product_name': '产品1'},
            {'customer_name': '客户B', 'product_name': '产品2'},
        ]
        assert quota.format_without_order_error(missing) == '客户A / 产品1、客户B / 产品2'

    def test_empty_list_gives_empty_string(self):
        assert quota.format_without_order_error([]) == ''


# ============================================================
# get_order_remaining_map —— 订单量 - 独立出货量
# ============================================================

class TestGetOrderRemainingMap:
    """(客户, 产品) 维度的订单余量"""

    @pytest.mark.asyncio
    async def test_subtracts_shipped_from_order(self):
        db = _make_db(
            order_rows=_make_rows([('客户A', '产品1', 100)]),
            shipped_rows=_make_rows([('客户A', '产品1', 30)]),
        )
        result = await quota.get_order_remaining_map(db, [('客户A', '产品1')])
        assert result == {('客户A', '产品1'): 70}

    @pytest.mark.asyncio
    async def test_clamps_negative_to_absent(self):
        """已发超（负余量）与「查不到订单」对调用方是同一结论，不入映射"""
        db = _make_db(
            order_rows=_make_rows([('客户A', '产品1', 20)]),
            shipped_rows=_make_rows([('客户A', '产品1', 50)]),
        )
        assert await quota.get_order_remaining_map(db, [('客户A', '产品1')]) == {}

    @pytest.mark.asyncio
    async def test_exact_fill_is_absent(self):
        """刚好发完 → 余量 0 → 不可添加"""
        db = _make_db(
            order_rows=_make_rows([('客户A', '产品1', 40)]),
            shipped_rows=_make_rows([('客户A', '产品1', 40)]),
        )
        assert await quota.get_order_remaining_map(db, [('客户A', '产品1')]) == {}

    @pytest.mark.asyncio
    async def test_no_shipped_rows_keeps_full_order_qty(self):
        db = _make_db(order_rows=_make_rows([('客户A', '产品1', 12)]), shipped_rows=[])
        assert await quota.get_order_remaining_map(db, [('客户A', '产品1')]) == {
            ('客户A', '产品1'): 12,
        }

    @pytest.mark.asyncio
    async def test_empty_pairs_skips_queries(self):
        db = MagicMock()
        db.execute = AsyncMock()
        assert await quota.get_order_remaining_map(db, []) == {}
        db.execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_drops_keys_outside_requested_pairs(self):
        """查询用 IN 过滤，返回行仍按入参收敛 —— 防止超集污染判定"""
        db = _make_db(
            order_rows=_make_rows([('客户A', '产品1', 10), ('客户Z', '产品9', 99)]),
            shipped_rows=[],
        )
        result = await quota.get_order_remaining_map(db, [('客户A', '产品1')])
        assert result == {('客户A', '产品1'): 10}

    @pytest.mark.asyncio
    async def test_product_filter_is_pushed_into_where(self):
        """产品名与客户名同时下推到 WHERE，不把全表拉回内存过滤"""
        seen = {}

        async def _execute(stmt, *args, **kwargs):
            seen['sql'] = str(stmt)
            res = MagicMock()
            res.all.return_value = []
            return res

        db = MagicMock()
        db.execute = AsyncMock(side_effect=_execute)
        await quota.get_order_remaining_map(db, [('客户A', '产品1')])
        assert '"order".customer IN' in seen['sql']
        assert 'product.name IN' in seen['sql']

    @pytest.mark.asyncio
    async def test_shipped_query_excludes_stockin_deduction(self):
        """备货抵扣出货（stockin_id 非空）扣的是备货，不计入订单余量扣减"""
        shipped_sql = []

        async def _execute(stmt, *args, **kwargs):
            sql = str(stmt)
            res = MagicMock()
            res.all.return_value = _make_rows([('客户A', '产品1', 100)]) if '"order"' in sql else []
            if 'stock_out' in sql:
                shipped_sql.append(sql)
            return res

        db = MagicMock()
        db.execute = AsyncMock(side_effect=_execute)
        await quota.get_order_remaining_map(db, [('客户A', '产品1')])
        assert len(shipped_sql) == 1
        assert 'stock_out.stockin_id IS NULL' in shipped_sql[0]


# ============================================================
# check_order_remaining —— 串起来的准入判定
# ============================================================

class TestCheckOrderRemaining:
    """明细准入校验"""

    @pytest.mark.asyncio
    async def test_all_pass(self):
        db = _make_db(order_rows=_make_rows([('客户A', '产品1', 10)]), shipped_rows=[])
        assert await quota.check_order_remaining(db, [{'customer_name': '客户A', 'product_name': '产品1'}]) == []

    @pytest.mark.asyncio
    async def test_reports_missing(self):
        db = _make_db(order_rows=[], shipped_rows=[])
        items = [{'customer_name': '客户A', 'product_name': '产品1'}]
        assert await quota.check_order_remaining(db, items) == items


class TestValidateOrderRemaining:
    """crud_ops 的准入校验辅助 —— 错误文案须指明客户与产品"""

    @pytest.mark.asyncio
    async def test_passes_when_order_remaining_exists(self):
        from fastapi_app.services.purchase_plan_crud_ops import _validate_order_remaining
        db = _make_db(order_rows=_make_rows([('客户A', '产品1', 10)]), shipped_rows=[])
        await _validate_order_remaining(db, '客户A', [{'product_name': '产品1'}], '无法创建出货计划')

    @pytest.mark.asyncio
    async def test_raises_with_customer_and_product_in_message(self):
        from fastapi_app.services.purchase_plan_crud_ops import _validate_order_remaining
        db = _make_db(order_rows=[], shipped_rows=[])
        with pytest.raises(ValueError) as ei:
            await _validate_order_remaining(db, '客户A', [{'product_name': '产品1'}], '无法创建出货计划')
        msg = str(ei.value)
        assert '客户A' in msg
        assert '产品1' in msg
        assert '没有订单余量' in msg
        assert '无法创建出货计划' in msg

    @pytest.mark.asyncio
    async def test_lists_every_offending_pair(self):
        from fastapi_app.services.purchase_plan_crud_ops import _validate_order_remaining
        db = _make_db(order_rows=_make_rows([('客户A', '产品1', 5)]), shipped_rows=[])
        with pytest.raises(ValueError) as ei:
            await _validate_order_remaining(
                db, '客户A',
                [{'product_name': '产品1'}, {'product_name': '产品2'}],
                '无法追加明细',
            )
        msg = str(ei.value)
        assert '产品1' not in msg.split('：')[-1]
        assert '产品2' in msg


# ============================================================
# 源码守卫：写入路径必须用订单余量、不得回退库存校验
# ============================================================

class TestAdmissionWiringGuards:
    """钉住准入条件：只认订单余量，不再查库存"""

    def _read(self, name):
        from pathlib import Path
        # tests/ 与 fastapi_app/tests/ 都在仓库根下一层，逐级上溯找 services 目录
        here = Path(__file__).resolve()
        for parent in here.parents:
            candidate = parent / 'fastapi_app' / 'services' / name
            if candidate.is_file():
                return candidate.read_text(encoding='utf-8')
        raise FileNotFoundError(f'fastapi_app/services/{name} not found from {here}')

    def test_crud_ops_validates_order_remaining(self):
        src = self._read('purchase_plan_crud_ops.py')
        # create_plan / update_detail / add_details 三个写入路径
        assert src.count('_validate_order_remaining(db,') == 3
        assert '_validate_order_remaining(db, customer_name, details' in src
        assert '_validate_order_remaining(db, plan.customer_name, details' in src
        assert '_validate_order_remaining(db, plan_month_row[1]' in src

    def test_crud_ops_has_no_inventory_admission(self):
        src = self._read('purchase_plan_crud_ops.py')
        assert '_check_inventory_realtime' not in src
        assert '库存不足' not in src

    def test_staging_validates_order_remaining(self):
        src = self._read('purchase_plan_staging.py')
        # validate_staging 与 confirm_staging 两条路径
        assert src.count('check_order_remaining(db,') == 2
        assert 'format_without_order_error' in src

    def test_staging_has_no_inventory_admission(self):
        src = self._read('purchase_plan_staging.py')
        assert '_check_inventory_realtime' not in src
        assert '库存不足' not in src

    def test_inventory_module_no_longer_exposes_check_chain(self):
        """库存校验链已删除，模块只留库存映射缓存"""
        src = self._read('purchase_plan_inventory.py')
        for dead in ('_fetch_barcode_stock', '_fetch_name_stock', '_aggregate_barcode_demand',
                     '_aggregate_name_demand', '_collect_insufficient', '_check_inventory_realtime'):
            assert f'def {dead}' not in src
