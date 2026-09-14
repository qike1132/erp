"""P0-02 回归测试：`_recalc_plans_common` 三处 return 必须元数一致

背景
----
`affected_plan_months` 是后加到 `_recalc_plans_common` 的返回项，但当时只改了
**正常返回路径**与调用方，漏改两处早退路径 → 调用方按 3 元组解包时抛 `ValueError`。

实证（非推演）
--------------
`logs/server_manager_20260910.log:345` 记录过该异常：

    STOCK_OUT_CREATED 处理失败: customer=SIMTEST-CUST-20260910
    product=SIMTEST-PROD-20260910103426
    error=not enough values to unpack (expected 3, got 2)
    File ".../purchase_plan_shipment.py", line 285, in recalc_plans_after_stockout_create

且异常被 `purchase_plan_service.py:174` 的 `except Exception` 吞成 ERROR 日志，
因此实际后果是「**出货成功但采购计划 shipped_qty 未重算**」的静默数据不一致（用户无感）。

覆盖范围
--------
| 用例 | 命中的 return |
|---|---|
| test_empty_names_returns_three_tuple | 早退 A（空客户名/产品名） |
| test_no_matching_plans_returns_three_tuple | 早退 B（无匹配计划） |
| test_no_related_details_returns_three_tuple | 早退 B（有计划无关联明细） |
| test_stockout_create_without_plan_rows_does_not_raise | L285 主路径（无守卫） |
| test_stockout_event_handler_no_silent_failure | 对齐 9/10 实证场景 |
"""
import logging
from unittest.mock import AsyncMock, patch

import pytest

from fastapi_app.services.purchase_plan_shipment import (
    _recalc_plans_common,
    recalc_plans_after_stockout_create,
)

_FETCH = 'fastapi_app.services.purchase_plan_shipment._fetch_affected_plans_and_details'


class TestRecalcPlansCommonArity:
    """三处 return 元数一致性（本工单核心断言）"""

    @pytest.mark.asyncio
    async def test_empty_names_returns_three_tuple(self, mock_db):
        """早退 A：客户名/产品名为空 → 必须仍返回 3 元组"""
        result = await _recalc_plans_common(
            mock_db, '', 'P1', action_type='recalc_stockout'
        )
        assert len(result) == 3, '早退路径必须返回 3 元组'
        status_changes, affected_count, months = result
        assert status_changes == {}
        assert affected_count == 0
        assert months == set()

    @pytest.mark.asyncio
    async def test_no_matching_plans_returns_three_tuple(self, mock_db):
        """早退 B：客户+产品无匹配采购计划 → 必须仍返回 3 元组（最易命中的分支）"""
        with patch(_FETCH, new=AsyncMock(return_value=([], [], []))):
            result = await _recalc_plans_common(
                mock_db, '不存在的客户', '不存在的产品', action_type='recalc_stockout'
            )
        assert len(result) == 3
        status_changes, affected_count, months = result
        assert status_changes == {}
        assert affected_count == 0
        assert months == set()

    @pytest.mark.asyncio
    async def test_no_related_details_returns_three_tuple(self, mock_db):
        """早退 B 的另一半：有计划但无关联明细 → 元数为 3，且计数须保留真实计划数"""
        with patch(_FETCH, new=AsyncMock(return_value=([object(), object()], [], []))):
            status_changes, affected_count, months = await _recalc_plans_common(
                mock_db, 'C', 'P', action_type='recalc_stockout'
            )
        assert status_changes == {}
        assert affected_count == 2, '早退时应返回受影响计划数，而非退化为 0'
        assert months == set()


class TestStockoutRecalcRegression:
    """L285 主路径回归：出货创建后重算不得抛异常"""

    @pytest.mark.asyncio
    async def test_stockout_create_without_plan_rows_does_not_raise(self, mock_db):
        """无采购计划行时调用 recalc_plans_after_stockout_create 不得抛 ValueError

        修复前：此处会抛 `ValueError: not enough values to unpack (expected 3, got 2)`
        """
        with patch(_FETCH, new=AsyncMock(return_value=([], [], []))):
            await recalc_plans_after_stockout_create(
                mock_db, '无计划客户', '无计划产品'
            )

    @pytest.mark.asyncio
    async def test_stockout_event_handler_no_silent_failure(self, mock_db, caplog):
        """对齐 2026-09-10 实证场景：不得再出现 'not enough values to unpack'

        该场景下异常会被上层 `except Exception` 吞成 ERROR 日志 → 用户无感、
        但采购计划 shipped_qty 静默失准。这里直接断言日志中不再出现该错误串。
        """
        with patch(_FETCH, new=AsyncMock(return_value=([], [], []))), \
                caplog.at_level(logging.ERROR):
            await recalc_plans_after_stockout_create(
                mock_db, 'SIMTEST-CUST-20260910', 'SIMTEST-PROD-20260910103426'
            )
        assert 'not enough values to unpack' not in caplog.text
        assert not caplog.records, f'不应产生任何 ERROR 日志，实际: {caplog.text}'
