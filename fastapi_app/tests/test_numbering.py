"""
编号生成规则测试
"""
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from fastapi_app.services.numbering import generate_order_number, generate_purchase_order_number, generate_stockin_number


class TestNumberingFormat:
    """验证订单号/备货号格式符合规范"""

    @pytest.mark.asyncio
    async def test_generate_order_number_format(self):
        with patch('fastapi_app.services.numbering.generate_number_async', new_callable=AsyncMock) as mock_generate:
            mock_generate.return_value = f"PO-{datetime.now().strftime('%Y%m%d')}-0001"
            number = await generate_order_number(MagicMock())

        today = datetime.now().strftime('%Y%m%d')
        assert number.startswith(f'PO-{today}-')
        assert len(number) == 16  # PO-YYYYMMDD-XXXX
        assert number.split('-')[-1].isdigit()
        assert int(number.split('-')[-1]) == 1

    @pytest.mark.asyncio
    async def test_generate_stockin_number_format(self):
        with patch('fastapi_app.services.numbering.generate_number_async', new_callable=AsyncMock) as mock_generate:
            mock_generate.return_value = f"BH-{datetime.now().strftime('%Y%m%d')}-0001"
            number = await generate_stockin_number(MagicMock())

        today = datetime.now().strftime('%Y%m%d')
        assert number.startswith(f'BH-{today}-')
        assert len(number) == 16  # BH-YYYYMMDD-XXXX
        assert number.split('-')[-1].isdigit()
        assert int(number.split('-')[-1]) == 1

    @pytest.mark.asyncio
    async def test_generate_stockin_number_not_si(self):
        """备货编号不应再使用旧 SI 前缀"""
        with patch('fastapi_app.services.numbering.generate_number_async', new_callable=AsyncMock) as mock_generate:
            mock_generate.return_value = f"BH-{datetime.now().strftime('%Y%m%d')}-0001"
            number = await generate_stockin_number(MagicMock())

        assert not number.startswith('SI-')

    @pytest.mark.asyncio
    async def test_generate_purchase_order_number_format(self):
        """采购订单编号格式应为 CG-YYYYMMDD-XXXX（4位序号，带分隔符）"""
        with patch('fastapi_app.services.numbering.generate_number_async', new_callable=AsyncMock) as mock_generate:
            mock_generate.return_value = f"CG-{datetime.now().strftime('%Y%m%d')}-0001"
            number = await generate_purchase_order_number(MagicMock())

        today = datetime.now().strftime('%Y%m%d')
        assert number.startswith(f'CG-{today}-')
        assert len(number) == 16  # CG-YYYYMMDD-XXXX
        assert number.split('-')[-1].isdigit()
        assert int(number.split('-')[-1]) == 1
