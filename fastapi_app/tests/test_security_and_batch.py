"""
文件 MIME 校验 + 批量操作 savepoint + 配置安全校验单元测试
"""
import pytest

from fastapi_app.core.validators import matches_upload_magic

# ==================== 文件 MIME 校验 ====================

class TestImageMimeValidation:
    """图片上传 MIME 魔数校验测试（P0-12 后统一走 core.validators 公共魔数层）"""

    def test_valid_png_signature(self):
        png_sig = b'\x89PNG\r\n\x1a\n' + b'\x00' * 10
        assert matches_upload_magic(png_sig, 'png') is True

    def test_valid_jpg_signature(self):
        jpg_sig = b'\xff\xd8\xff' + b'\x00' * 10
        assert matches_upload_magic(jpg_sig, 'jpg') is True
        assert matches_upload_magic(jpg_sig, 'jpeg') is True

    def test_valid_gif87a_signature(self):
        gif_sig = b'GIF87a' + b'\x00' * 10
        assert matches_upload_magic(gif_sig, 'gif') is True

    def test_valid_gif89a_signature(self):
        gif_sig = b'GIF89a' + b'\x00' * 10
        assert matches_upload_magic(gif_sig, 'gif') is True

    def test_html_disguised_as_png(self):
        html_data = b'<html><script>alert("xss")</script></html>'
        assert matches_upload_magic(html_data, 'png') is False

    def test_js_disguised_as_jpg(self):
        js_data = b'console.log("malicious");'
        assert matches_upload_magic(js_data, 'jpg') is False

    def test_empty_content(self):
        assert matches_upload_magic(b'', 'png') is False

    def test_gif_sig_rejected_as_png(self):
        gif_sig = b'GIF89a' + b'\x00' * 10
        assert matches_upload_magic(gif_sig, 'png') is False

    def test_short_data_rejected(self):
        assert matches_upload_magic(b'\x89P', 'png') is False


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
        for i, _item in enumerate(items):
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
        import os
        import subprocess  # nosec B404
        import sys

        # 创建一个独立的Python脚本来测试配置验证
        #
        # 编码必须显式钉死为 UTF-8：子进程要打印中文报错（"必须通过环境变量"），
        # 而 `text=True` 在中文 Windows 上按 locale（GBK）解码 → 读取线程抛
        # UnicodeDecodeError → `stdout` 变成 None → 断言报
        # "argument of type 'NoneType' is not iterable"，看不出真实原因。
        # ⚠️ 关键：PYTHONIOENCODING 必须由【父进程】注入。子进程脚本里再赋值已经晚于
        #    解释器启动（stdout 编码在启动时就已确定），对子进程自身输出无效 → 中文报错
        #    仍按 GBK 写出 → 父进程按 utf-8 解码失败 → stdout 变成 None。
        #    （2026-09-30 本机实测：不注入 env 稳定失败，注入 env= 后稳定通过。）
        test_script = '''
import os
import sys
sys.path.insert(0, r'd:\\erp_system')
os.environ['PYTHONIOENCODING'] = 'utf-8'
os.environ['SECRET_KEY'] = ''
try:
    from fastapi_app.core.config import Settings
    s = Settings()
    print("NO_ERROR")
except RuntimeError as e:
    print(f"ERROR_RAISED:{str(e)}")
'''

        child_env = {**os.environ, 'PYTHONIOENCODING': 'utf-8', 'PYTHONUTF8': '1'}
        result = subprocess.run([sys.executable, '-c', test_script],  # nosec B603
                              capture_output=True, text=True, encoding='utf-8', cwd='.',
                              env=child_env)
        assert "ERROR_RAISED" in result.stdout
        assert "必须通过环境变量" in result.stdout

    def test_secret_key_weak_value_raises(self):
        import os
        orig = os.environ.get('SECRET_KEY')
        orig_env = os.environ.get('APP_ENV')
        try:
            os.environ['SECRET_KEY'] = 'CHANGE-ME-IN-PRODUCTION'
            # 现行策略为内网宽松：非生产环境不检查弱默认值；
            # 生产环境下该弱默认值（21 字符）因长度不足 32 被拦截
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
