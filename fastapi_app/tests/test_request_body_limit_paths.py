"""请求体大小上限的路径级豁免（H-2）。

背景：`core/middleware.py` 的 10MB 全局硬上限没有路径豁免，把"宣称支持 500MB"的
备份上传与"宣称 50MB"的 Excel 导入一并挡死 —— 上线后第一次整库还原/大导入即 413。

约定（本文件锁定）：只有**业务侧已经声明过上限**的路径可以突破 10MB，且中间件上限
必须 >= 业务侧上限，真正的校验仍由端点内的 `MAX_BACKUP_FILE_SIZE` /
`MAX_IMPORT_FILE_SIZE` 负责。

测试手法：中间件只读 `content-length` 头，故用"声明大 content-length + 空 body"
即可触发其判定，不必真的构造 512MB 负载。
"""
import re
from pathlib import Path

from fastapi_app.api.v1.endpoints.tasks import MAX_IMPORT_FILE_SIZE
from fastapi_app.core.middleware import (
    MAX_REQUEST_BODY_SIZE,
    max_body_size_for_path,
)
from fastapi_app.services import backup as backup_service

_ABOVE_DEFAULT = str(512 * 1024 * 1024)  # 远超 10MB，用于触发上限判定

# 各路径**业务侧声明的**可接受体积：这正是要能抵达端点的体积。
_DECLARED_BACKUP_SIZE = str(backup_service.MAX_BACKUP_FILE_SIZE)
_DECLARED_IMPORT_SIZE = str(MAX_IMPORT_FILE_SIZE)


async def _post_declaring(client, url: str, declared_bytes: str):
    """发送「声明大 content-length、实际空 body」的请求。"""
    return await client.post(
        url,
        content=b'',
        headers={'content-length': declared_bytes},
    )


# --------------------------------------------------------------------------
# 中间件上限解析
# --------------------------------------------------------------------------

def test_backup_path_limit_covers_declared_backup_max_size():
    """备份路径的中间件上限必须 >= 业务声明的备份文件上限（防止两处漂移）。"""
    assert max_body_size_for_path('/api/v1/backup/import') >= backup_service.MAX_BACKUP_FILE_SIZE


def test_import_path_limit_covers_declared_import_max_size():
    """导入路径的中间件上限必须 >= 业务声明的导入文件上限。"""
    assert max_body_size_for_path('/api/v1/tasks/import-orders') >= MAX_IMPORT_FILE_SIZE


def test_unlisted_path_keeps_default_limit():
    """未声明的路径维持默认 10MB（不加宽）。"""
    assert max_body_size_for_path('/api/v1/orders') == MAX_REQUEST_BODY_SIZE
    assert MAX_REQUEST_BODY_SIZE == 10 * 1024 * 1024


# --------------------------------------------------------------------------
# 线级行为
# --------------------------------------------------------------------------

async def test_backup_upload_at_declared_size_is_not_blocked_by_global_limit(client):
    """备份上传达到业务声明的 500MB 时不应被全局上限 413 拦下。"""
    resp = await _post_declaring(client, '/api/v1/backup/import', _DECLARED_BACKUP_SIZE)
    assert resp.status_code != 413, f'备份路径仍被全局上限拦截: {resp.text[:200]}'


async def test_excel_import_at_declared_size_is_not_blocked_by_global_limit(client):
    """Excel 导入达到业务声明的 50MB 时不应被全局上限 413 拦下。"""
    resp = await _post_declaring(client, '/api/v1/tasks/import-orders', _DECLARED_IMPORT_SIZE)
    assert resp.status_code != 413, f'导入路径仍被全局上限拦截: {resp.text[:200]}'


async def test_ordinary_write_path_is_still_capped(client):
    """普通写路径仍然在 10MB 处拦截（豁免不得扩大化）。"""
    resp = await _post_declaring(client, '/api/v1/orders', _ABOVE_DEFAULT)
    assert resp.status_code == 413


# --------------------------------------------------------------------------
# 部署侧 nginx 必须同步放宽（两层不同步 = 边缘仍 413，改了等于没改）
# --------------------------------------------------------------------------

_NGINX_CONF = Path(__file__).resolve().parents[2] / 'config' / 'nginx-windows.conf'
_SIZE_UNITS = {'': 1, 'k': 1024, 'm': 1024**2, 'g': 1024**3}


def _parse_size(raw: str) -> int:
    raw = raw.strip().lower()
    unit = raw[-1] if raw[-1] in _SIZE_UNITS else ''
    return int(raw[:-1] if unit else raw) * _SIZE_UNITS[unit]


def _location_body_limits(conf_text: str) -> dict[str, int]:
    """解析各 location 块内的 client_max_body_size（字节）。"""
    limits: dict[str, int] = {}
    for loc in re.finditer(r'location\s+([^\s{]+)\s*\{([^{}]*)\}', conf_text):
        prefix, block = loc.group(1), loc.group(2)
        m = re.search(r'client_max_body_size\s+([0-9]+[kmgKMG]?)\s*;', block)
        if m:
            limits[prefix] = _parse_size(m.group(1))
    return limits


def test_deployed_nginx_relaxes_exactly_the_two_upload_paths():
    """部署的 nginx 只应给备份/导入两个 location 放宽（不扩大到其它路径）。"""
    limits = _location_body_limits(_NGINX_CONF.read_text(encoding='utf-8'))
    assert set(limits) == {'/api/v1/backup/', '/api/v1/tasks/import-'}, (
        f'nginx location 级上限的覆盖范围与预期不符: {sorted(limits)}'
    )


def test_deployed_nginx_backup_limit_covers_declared_backup_max_size():
    limits = _location_body_limits(_NGINX_CONF.read_text(encoding='utf-8'))
    assert limits['/api/v1/backup/'] >= backup_service.MAX_BACKUP_FILE_SIZE


def test_deployed_nginx_import_limit_covers_declared_import_max_size():
    limits = _location_body_limits(_NGINX_CONF.read_text(encoding='utf-8'))
    assert limits['/api/v1/tasks/import-'] >= MAX_IMPORT_FILE_SIZE
