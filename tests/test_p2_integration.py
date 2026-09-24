"""P2级修复的集成验证测试"""

from fastapi_app.api.v1.endpoints import backup, customer, supplier
from fastapi_app.core.cache_keys import CacheNamespace, build_cache_key
from fastapi_app.core.exceptions import (
    ConflictError,
    InternalError,
    NotFoundError,
    PermissionDeniedError,
    current_iso_timestamp,
    http_error,
    make_error_response,
    new_request_id,
)
from fastapi_app.core.sanitizer import safe_exception_message
from fastapi_app.main import app
from fastapi_app.services import backup as backup_service


def test_all_modules_imported():
    """验证所有P0/P1/P2修复涉及的模块可以正常导入"""
    assert customer is not None
    assert supplier is not None
    assert backup is not None
    assert app is not None
    assert len(app.routes) > 0


def test_error_response_structure():
    """P2-1: 验证统一错误响应结构"""
    err = make_error_response(code='TEST', message='test message', status_code=400)
    assert err['success'] is False
    assert err['error']['code'] == 'TEST'
    assert 'request_id' in err['error']
    assert 'timestamp' in err['error']


def test_http_error_returns_http_exception():
    """P2-1: http_error返回带有结构化detail的HTTPException"""
    exc = http_error(status_code=409, code='CONFLICT', message='conflict')
    assert exc.status_code == 409
    assert isinstance(exc.detail, dict)
    assert exc.detail['error']['code'] == 'CONFLICT'


def test_app_error_classes():
    """P2-1: 业务异常类的code和status_code正确"""
    err = NotFoundError('test')
    assert err.code == 'NOT_FOUND'
    assert err.status_code == 404

    err = ConflictError('test')
    assert err.code == 'CONFLICT'
    assert err.status_code == 409

    err = PermissionDeniedError('test')
    assert err.code == 'PERMISSION_DENIED'
    assert err.status_code == 403

    err = InternalError('test')
    assert err.code == 'INTERNAL_ERROR'
    assert err.status_code == 500


def test_request_id_format():
    """P2-1: request_id是16字符"""
    rid = new_request_id()
    assert len(rid) == 16


def test_timestamp_format():
    """P2-1: timestamp以Z结尾表示UTC"""
    ts = current_iso_timestamp()
    assert ts.endswith('Z')


def test_backup_chunk_size_imported():
    """P2-2: 分片大小配置存在于 backup 服务包并可被 endpoints 导入"""
    from fastapi_app.api.v1.endpoints.backup.export import _get_chunk_size
    from fastapi_app.services.backup import BACKUP_CHUNK_SIZE
    assert BACKUP_CHUNK_SIZE > 0
    assert _get_chunk_size() > 0


def test_cache_key_utility():
    """P1-1: 缓存键生成工具"""
    key = build_cache_key(CacheNamespace.CUSTOMER_LIST, 'all', 50)
    assert key == 'erp:customer:list:all:50'

    key = build_cache_key('order', 'detail', None, True)
    assert key == 'erp:order:detail:null:1'


def test_log_sanitization():
    """P1-2: 敏感信息脱敏"""
    try:
        raise ValueError('Connection failed with token=abc123')
    except ValueError as e:
        msg = safe_exception_message(e)
        assert 'abc123' not in msg


def test_backup_timeout_configured():
    """P1-4: 备份超时配置存在"""
    assert hasattr(backup_service, 'BACKUP_OPERATION_TIMEOUT')
    assert backup_service.BACKUP_OPERATION_TIMEOUT > 0


def test_backup_in_process_lock():
    """P1-4: 进程级备份锁存在（现位于 services/backup/_constants.py）"""
    import asyncio

    from fastapi_app.services.backup._constants import _backup_in_progress
    assert isinstance(_backup_in_progress, asyncio.Lock)
