"""
编号生成规则测试
"""
import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from fastapi_app.services.numbering import (
    generate_order_number,
    generate_purchase_order_number,
    generate_stockin_number,
)
from fastapi_app.services.numbering_sequence import business_date_str, read_daily_max


class TestNumberingFormat:
    """验证订单号/备货号格式符合规范"""

    @pytest.mark.asyncio
    async def test_generate_order_number_format(self):
        # 日期只读一次：mock 返回值与断言共用同一 today，跨午夜不再假红（Erratic Test）
        today = datetime.now().strftime('%y%m')
        with patch('fastapi_app.services.numbering.generate_number_async', new_callable=AsyncMock) as mock_generate:
            mock_generate.return_value = f"PO-{today}-001"
            number = await generate_order_number(MagicMock())

        assert number.startswith(f'PO-{today}-')
        assert len(number) == 11  # PO-YYMM-NNN
        assert number.split('-')[-1].isdigit()
        assert int(number.split('-')[-1]) == 1

    @pytest.mark.asyncio
    async def test_generate_stockin_number_format(self):
        today = datetime.now().strftime('%y%m')
        with patch('fastapi_app.services.numbering.generate_number_async', new_callable=AsyncMock) as mock_generate:
            mock_generate.return_value = f"BH-{today}-001"
            number = await generate_stockin_number(MagicMock())

        assert number.startswith(f'BH-{today}-')
        assert len(number) == 11  # BH-YYMM-NNN
        assert number.split('-')[-1].isdigit()
        assert int(number.split('-')[-1]) == 1

    @pytest.mark.asyncio
    async def test_generate_stockin_number_not_si(self):
        """备货编号不应再使用旧 SI 前缀"""
        with patch('fastapi_app.services.numbering.generate_number_async', new_callable=AsyncMock) as mock_generate:
            mock_generate.return_value = f"BH-{datetime.now().strftime('%y%m')}-001"
            number = await generate_stockin_number(MagicMock())

        assert not number.startswith('SI-')

    @pytest.mark.asyncio
    async def test_generate_purchase_order_number_format(self):
        """采购订单编号前缀为 PO（2026-10-10 由 CG 统一为 PO）。"""
        today = datetime.now().strftime('%y%m')
        with patch('fastapi_app.services.numbering.generate_number_async', new_callable=AsyncMock) as mock_generate:
            mock_generate.return_value = f"PO-{today}-001"
            number = await generate_purchase_order_number(MagicMock())

        # 断言真正传给取号内核的前缀，而非只断言 mock 的返回值
        assert mock_generate.call_args.args[0] == 'PO'
        assert number.startswith(f'PO-{today}-')
        assert len(number) == 11  # PO-YYMM-NNN
        assert number.split('-')[-1].isdigit()
        assert int(number.split('-')[-1]) == 1


class TestDeprecatedAliases:
    """旧名必须"吵"：``pytest.ini`` 只 ``ignore`` 了 UserWarning 与
    DeprecationWarning，FutureWarning 会落到 ``error`` 上，所以残留调用会直接
    抛异常而不是静默通过。这两条钉住"废弃别名不能变回静默别名"。
    """

    def test_business_date_str_is_loud(self):
        with pytest.raises(FutureWarning):
            business_date_str()

    def test_read_daily_max_is_loud(self):
        # 告警在函数体第一行就抛，不会真正触库；参数只求满足签名
        with pytest.raises(FutureWarning):
            asyncio.run(read_daily_max(MagicMock(), None, 'order_no', '2611'))
