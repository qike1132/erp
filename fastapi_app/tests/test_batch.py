"""批量导入接口测试"""
from io import BytesIO
from unittest.mock import patch

import pytest


class TestBatchEndpoints:
    @pytest.mark.asyncio
    async def test_download_template_not_found(self, client):
        """测试下载模板 - 模板文件不存在"""
        with patch('os.path.exists', return_value=False):
            response = await client.get("/api/v1/batch/download-template")
            assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_import_orders_invalid_file_format(self, client, mock_db):
        """测试批量导入订单 - 非 xlsx 文件格式"""
        files = {
            'file': ('test.csv', BytesIO(b'customer,product,qty'), 'text/csv')
        }
        response = await client.post("/api/v1/batch/import-orders", files=files)
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is False
        assert 'Excel' in data['message']

    @pytest.mark.asyncio
    async def test_import_stockins_invalid_file_format(self, client, mock_db):
        """测试批量导入备货 - 非 xlsx 文件格式"""
        files = {
            'file': ('data.txt', BytesIO(b'some text data'), 'text/plain')
        }
        response = await client.post("/api/v1/batch/import-stockins", files=files)
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is False
        assert 'Excel' in data['message']

    @pytest.mark.asyncio
    async def test_import_stockouts_invalid_file_format(self, client, mock_db):
        """测试批量导入出库 - 非 xlsx 文件格式"""
        files = {
            'file': ('export.xls', BytesIO(b'old format'), 'application/vnd.ms-excel')
        }
        response = await client.post("/api/v1/batch/import-stockouts", files=files)
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is False
        assert 'Excel' in data['message']

    @pytest.mark.asyncio
    async def test_batch_import_products_invalid_file_format(self, client, mock_db):
        """测试批量导入产品 - 非 xlsx 文件格式"""
        files = {
            'file': ('products.csv', BytesIO(b'name,barcode'), 'text/csv')
        }
        response = await client.post("/api/v1/batch/batch-import", files=files)
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is False
        assert 'Excel' in data['message']

    @pytest.mark.asyncio
    async def test_import_comprehensive_invalid_file_format(self, client, mock_db):
        """测试综合批量导入 - 非 xlsx 文件格式"""
        files = {
            'file': ('comprehensive.pdf', BytesIO(b'pdf content'), 'application/pdf')
        }
        response = await client.post("/api/v1/batch/import-comprehensive", files=files)
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is False
        assert 'Excel' in data['message']

    @pytest.mark.asyncio
    async def test_import_case_stockouts_invalid_file_format(self, client, mock_db):
        """测试批量导入皮套出库 - 非 xlsx 文件格式"""
        files = {
            'file': ('cases.csv', BytesIO(b'name,qty'), 'text/csv')
        }
        response = await client.post("/api/v1/batch/import-case-stockouts", files=files)
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is False
        assert 'Excel' in data['message']

    @pytest.mark.asyncio
    async def test_import_case_stockins_invalid_file_format(self, client, mock_db):
        """测试批量导入皮套入库 - 非 xlsx 文件格式"""
        files = {
            'file': ('cases.txt', BytesIO(b'name,qty'), 'text/plain')
        }
        response = await client.post("/api/v1/batch/import-case-stockins", files=files)
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is False
        assert 'Excel' in data['message']
