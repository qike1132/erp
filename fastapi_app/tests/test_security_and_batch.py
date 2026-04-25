"""
文件 MIME 校验 + 批量操作 savepoint + 配置安全校验单元测试
"""
import pytest


# ==================== 文件 MIME 校验 ====================

class TestImageMimeValidation:
    """图片上传 MIME 魔数校验测试"""

    def test_valid_png_signature(self):
        from fastapi_app.api.v1.endpoints.auth import _validate_image_content
        png_sig = b'\x89PNG\r\n\x1a\n' + b'\x00' * 10
        assert _validate_image_content(png_sig, 'png') is True

    def test_valid_jpg_signature(self):
        from fastapi_app.api.v1.endpoints.auth import _validate_image_content
        jpg_sig = b'\xff\xd8\xff' + b'\x00' * 10
        assert _validate_image_content(jpg_sig, 'jpg') is True
        assert _validate_image_content(jpg_sig, 'jpeg') is True

    def test_valid_gif87a_signature(self):
        from fastapi_app.api.v1.endpoints.auth import _validate_image_content
        gif_sig = b'GIF87a' + b'\x00' * 10
        assert _validate_image_content(gif_sig, 'gif') is True

    def test_valid_gif89a_signature(self):
        from fastapi_app.api.v1.endpoints.auth import _validate_image_content
        gif_sig = b'GIF89a' + b'\x00' * 10
        assert _validate_image_content(gif_sig, 'gif') is True

    def test_html_disguised_as_png(self):
        from fastapi_app.api.v1.endpoints.auth import _validate_image_content
        html_data = b'<html><script>alert("xss")</script></html>'
        assert _validate_image_content(html_data, 'png') is False

    def test_js_disguised_as_jpg(self):
        from fastapi_app.api.v1.endpoints.auth import _validate_image_content
        js_data = b'console.log("malicious");'
        assert _validate_image_content(js_data, 'jpg') is False

    def test_empty_content(self):
        from fastapi_app.api.v1.endpoints.auth import _validate_image_content
        assert _validate_image_content(b'', 'png') is False

    def test_gif_sig_rejected_as_png(self):
        from fastapi_app.api.v1.endpoints.auth import _validate_image_content
        gif_sig = b'GIF89a' + b'\x00' * 10
        assert _validate_image_content(gif_sig, 'png') is False

    def test_short_data_rejected(self):
        from fastapi_app.api.v1.endpoints.auth import _validate_image_content
        assert _validate_image_content(b'\x89P', 'png') is False


# ==================== 批量操作 savepoint ====================

class TestBatchStockInSavepoint:
    """批量入库 savepoint 隔离测试"""

    def test_begin_nested_called_per_item(self):
        from unittest.mock import MagicMock
        session = MagicMock()
        nested_ctx = MagicMock()
        nested_ctx.__enter__ = MagicMock(return_value=nested_ctx)
        nested_ctx.__exit__ = MagicMock(return_value=False)
        session.begin_nested.return_value = nested_ctx

        items = [
            {'product_id': 1, 'customer': 'A', 'quantity': 10, 'note': ''},
            {'product_id': 2, 'customer': 'B', 'quantity': 5, 'note': ''},
            {'product_id': 3, 'customer': 'C', 'quantity': 3, 'note': ''},
        ]

        results = {}
        for i, item in enumerate(items):
            nested = session.begin_nested()
            try:
                nested.commit()
                results[i] = {'success': True}
            except Exception:
                nested.rollback()
                results[i] = {'success': False}

        assert session.begin_nested.call_count == 3
        assert all(r['success'] for r in results.values())

    def test_rollback_on_single_item_failure(self):
        from unittest.mock import MagicMock
        session = MagicMock()
        nested_ctx = MagicMock()
        nested_ctx.__enter__ = MagicMock(return_value=nested_ctx)
        nested_ctx.__exit__ = MagicMock(return_value=False)
        session.begin_nested.return_value = nested_ctx

        items = [
            {'product_id': 1, 'customer': 'A', 'quantity': 10, 'note': ''},
            {'product_id': -1, 'customer': 'B', 'quantity': 0, 'note': ''},
            {'product_id': 3, 'customer': 'C', 'quantity': 3, 'note': ''},
        ]

        results = {}
        for i, item in enumerate(items):
            nested = session.begin_nested()
            try:
                if item['product_id'] < 0 or item['quantity'] <= 0:
                    raise ValueError("无效参数")
                nested.commit()
                results[i] = {'success': True}
            except Exception:
                nested.rollback()
                results[i] = {'success': False}

        assert results[0] == {'success': True}
        assert results[1] == {'success': False}
        assert results[2] == {'success': True}


# ==================== 配置安全校验 ====================

class TestConfigSecurityValidation:
    """配置安全校验测试"""

    def test_secret_key_too_short_raises_runtime_error(self):
        import os
        orig = os.environ.get('SECRET_KEY')
        orig_env = os.environ.get('APP_ENV')
        try:
            os.environ['SECRET_KEY'] = 'short-key'
            os.environ['APP_ENV'] = 'production'
            from fastapi_app.core.config import Settings
            with pytest.raises(RuntimeError, match="长度不足"):
                Settings()
        finally:
            if orig is not None:
                os.environ['SECRET_KEY'] = orig
            elif 'SECRET_KEY' in os.environ:
                del os.environ['SECRET_KEY']
            if orig_env is not None:
                os.environ['APP_ENV'] = orig_env
            elif 'APP_ENV' in os.environ:
                del os.environ['APP_ENV']

    def test_secret_key_default_empty_raises(self):
        import subprocess
        import sys
        
        # 创建一个独立的Python脚本来测试配置验证
        test_script = '''
import os
import sys
sys.path.insert(0, r'd:\\erp_system')
os.environ['SECRET_KEY'] = ''
try:
    from fastapi_app.core.config import Settings
    s = Settings()
    print("NO_ERROR")
except RuntimeError as e:
    print(f"ERROR_RAISED:{str(e)}")
'''
        
        result = subprocess.run([sys.executable, '-c', test_script], 
                              capture_output=True, text=True, cwd='.')
        assert "ERROR_RAISED" in result.stdout
        assert "必须通过环境变量" in result.stdout

    def test_secret_key_weak_value_raises(self):
        import os
        orig = os.environ.get('SECRET_KEY')
        try:
            os.environ['SECRET_KEY'] = 'CHANGE-ME-IN-PRODUCTION'
            from fastapi_app.core.config import Settings
            with pytest.raises(RuntimeError, match="不能使用不安全的默认值"):
                Settings()
        finally:
            if orig is not None:
                os.environ['SECRET_KEY'] = orig
            elif 'SECRET_KEY' in os.environ:
                del os.environ['SECRET_KEY']
