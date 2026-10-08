"""OCR 可选依赖缺失的守卫测试（2026-10-08 生产事故的回归钉）

事故：新部署的 venv 漏装 `requirements/ocr.txt`（约 500MB 的可选栈）。OCR 图片路径的
第一行就是 `import numpy as np`（惰性导入），于是端点抛裸
`ModuleNotFoundError: No module named 'numpy'` → 用户只看到「服务器内部错误」，
真因只躺在日志里，排查成本很高。

本文件锁死三件事：
  1. 缺依赖抛的是**带修复命令**的 OcrDependencyError，且**一次报全**缺失项；
  2. 它仍是 RuntimeError 子类 —— `_import.py` 既有的「表格识别失败回退文本模式」不被破坏；
  3. 端点把它转成可读的 503，而不是 500「服务器内部错误」。
"""
from io import BytesIO
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from fastapi_app.services.ocr._extractors import (
    OcrDependencyError,
    _require_modules,
    extract_text_from_image,
)

ORDER_URL = '/api/v1/ocr-import/order/preview'
PREVIEW_URL = '/api/v1/ocr-import/preview'

MISSING_MSG = 'OCR 依赖未安装：numpy；请执行 pip install -r requirements/ocr.txt（约 500MB，可选装）'


def png_bytes() -> bytes:
    """真 PNG：端点有文件头（魔数）校验，伪造字节会先被 400 拦掉，测不到守卫"""
    from PIL import Image

    buf = BytesIO()
    Image.new('RGB', (8, 8), 'white').save(buf, 'PNG')
    return buf.getvalue()


def upload(name: str = 'order.png', field: str = 'file') -> list:
    return [(field, (name, BytesIO(png_bytes()), 'image/png'))]


class TestRequireModules:
    def test_installed_module_passes(self):
        # numpy 现在装在 venv 里；已装的依赖不应抛错
        _require_modules('numpy')

    def test_missing_module_reports_actionable_hint(self):
        with pytest.raises(OcrDependencyError) as ei:
            _require_modules('__definitely_not_a_module__')
        msg = str(ei.value)
        assert '__definitely_not_a_module__' in msg
        assert 'requirements/ocr.txt' in msg
        assert 'pip install' in msg

    def test_reports_all_missing_at_once(self):
        """一次报全：逐个报会让人修一个再撞下一个"""
        with pytest.raises(OcrDependencyError) as ei:
            _require_modules('__missing_a__', 'numpy', '__missing_b__')
        msg = str(ei.value)
        assert '__missing_a__' in msg and '__missing_b__' in msg
        # numpy 已安装，不该出现在缺失清单里
        assert 'numpy' not in msg

    def test_error_is_runtime_error_subclass(self):
        """必须是 RuntimeError 子类：_import.py 靠 `except RuntimeError` 回退文本模式"""
        assert issubclass(OcrDependencyError, RuntimeError)

    def test_image_path_raises_guard_when_dep_missing(self):
        with patch('fastapi_app.services.ocr._extractors._missing_modules',
                   return_value=['numpy']):
            with pytest.raises(OcrDependencyError) as ei:
                extract_text_from_image(b'\x89PNG-fake')
        assert 'numpy' in str(ei.value)


class TestEndpointsSurfaceIt:
    """端点必须把它变成可读的 503，而不是 500「服务器内部错误」"""

    @pytest.mark.asyncio
    async def test_order_preview_returns_503_with_hint(self, client, mock_db):
        with patch('fastapi_app.services.ocr_service.preview_order_items',
                   new=AsyncMock(side_effect=OcrDependencyError(MISSING_MSG))):
            response = await client.post(ORDER_URL, files=upload())
        assert response.status_code == 503
        assert 'requirements/ocr.txt' in response.json()['detail']

    @pytest.mark.asyncio
    async def test_stockout_preview_returns_503_with_hint(self, client):
        with patch('fastapi_app.services.ocr_service.extract_table_structure',
                   side_effect=OcrDependencyError(MISSING_MSG)):
            response = await client.post(PREVIEW_URL, files=upload())
        assert response.status_code == 503
        assert 'requirements/ocr.txt' in response.json()['detail']

    @pytest.mark.asyncio
    async def test_upload_reports_per_file_instead_of_500(self, client, mock_db):
        """批量上传路径：缺依赖时逐文件如实报出，不让整批 500"""
        import fastapi_app.services.ocr_service as svc

        with patch.object(svc, 'import_staging_stockouts_from_file',
                          new=AsyncMock(side_effect=OcrDependencyError(MISSING_MSG))), \
             patch.object(svc, 'create_progress', return_value='t-1'), \
             patch.object(svc, '_update_progress', MagicMock()), \
             patch.object(svc, '_progress_store', {'t-1': {}}):
            response = await client.post(
                '/api/v1/ocr-import/upload?session_id=s1&task_id=t-1', files=upload(field='files'))
        assert response.status_code == 200
        body = response.json()
        assert any('requirements/ocr.txt' in e for e in body['errors'])
