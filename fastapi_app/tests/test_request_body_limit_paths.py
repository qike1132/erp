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


def test_endpoint_level_declared_limits_within_effective_middleware_limit():
    """端点级文件上限（batch 七端点 / packaging 上传）必须小于中间件有效 body 上限。

    M2（2026-10-25 上线前检查）：multipart 请求体 = 文件 + 边界/字段头开销。
    body 上限与文件上限相等时，「恰好 10MB 的合法文件」会在抵达端点**之前**被
    413——端点常量成死配置、用户看不到友好报错。中间件预算 = 文件上限 +
    _MULTIPART_OVERHEAD_BYTES，本断言锁「严格大于」（余量存在）。
    """
    from fastapi_app.api.v1.endpoints.import_guard import (
        MAX_IMPORT_FILE_SIZE as GUARD_LIMIT,
    )
    from fastapi_app.api.v1.endpoints.production_summary import (
        MAX_PACKAGING_UPLOAD_SIZE,
    )

    assert max_body_size_for_path('/api/v1/batch/import-orders') > GUARD_LIMIT
    assert max_body_size_for_path(
        '/api/v1/production-summary/packaging/upload'
    ) > MAX_PACKAGING_UPLOAD_SIZE


def test_multipart_overhead_is_covered_for_at_limit_file():
    """恰好 10MB 文件 + multipart 开销的总 body 不得撞中间件上限（M2 核心）。"""
    from fastapi_app.api.v1.endpoints.import_guard import MAX_IMPORT_FILE_SIZE
    from fastapi_app.core.middleware import _MULTIPART_OVERHEAD_BYTES

    limit = max_body_size_for_path('/api/v1/batch/import-comprehensive')
    # 典型 multipart：单文件字段 + 边界两行 + 少量文本字段，开销远小于余量，
    # 但必须至少容得下「文件恰好上限 + 1 字节以上的边界开销」。
    assert limit >= MAX_IMPORT_FILE_SIZE + _MULTIPART_OVERHEAD_BYTES


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


async def test_multipart_file_at_exact_limit_reaches_endpoint(client):
    """M2 线级回归：恰好 10MB 文件的真实 multipart 请求不得被 413 挡在端点之外。

    multipart body = 10MB 文件 + 边界/字段头开销 > 旧全局 10MB —— 修复前本用例
    必红（413 来自中间件而非端点）。端点之后的业务响应（401/422/500…）不在本
    断言范围，只锁「体积预算放行到端点」。
    """
    from fastapi_app.api.v1.endpoints.import_guard import MAX_IMPORT_FILE_SIZE

    content = b'0' * MAX_IMPORT_FILE_SIZE
    resp = await client.post(
        '/api/v1/batch/import-orders',
        files={'file': ('at-limit.xlsx', content,
                        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')},
    )
    assert resp.status_code != 413, (
        f'恰好上限的合法文件被 413（multipart 开销未给余量）: {resp.status_code} {resp.text[:120]}'
    )


async def test_chunked_body_on_batch_path_still_capped(client):
    """M2 流式口径（评审 finding 9）：batch 放宽路径的 chunked 累计边界 = 12MiB。"""
    resp = await client.post(
        '/api/v1/batch/import-orders',
        content=_chunked_body(13),
        headers={'content-type': 'application/octet-stream'},
    )
    assert resp.status_code == 413, f'batch 放宽路径的 13MB 流未被拦下: {resp.status_code}'


async def test_multipart_body_over_relaxed_budget_is_413(client):
    """M2 边界：body 超过放宽预算（文件 12MB > 10MB 文件上限 + 余量）仍要 413。"""
    oversize = b'0' * (10 * 1024 * 1024 + 3 * 1024 * 1024)
    resp = await client.post(
        '/api/v1/batch/import-orders',
        files={'file': ('too-big.xlsx', oversize, 'application/octet-stream')},
    )
    assert resp.status_code == 413, f'超预算 body 未被拦下: {resp.status_code}'


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
    """解析各 location 块内的 client_max_body_size（字节）。

    key 保留 ``= `` 修饰符前缀：精确匹配 location 与前缀 location 语义不同，
    M2 评审把 production-summary 的放宽收窄为精确匹配后，两者必须在断言里
    可区分，否则「整前缀放宽」会伪装成「精确放宽」通过 parity。
    """
    limits: dict[str, int] = {}
    for loc in re.finditer(r'location\s+(=\s+)?([^\s{]+)\s*\{([^{}]*)\}', conf_text):
        modifier, prefix = loc.group(1) or '', loc.group(2)
        block = loc.group(3)
        m = re.search(r'client_max_body_size\s+([0-9]+[kmgKMG]?)\s*;', block)
        if m:
            limits[modifier.replace(' ', '') + prefix] = _parse_size(m.group(1))
    return limits


def test_deployed_nginx_relaxes_exactly_the_declared_upload_paths():
    """部署的 nginx 只应给四组上传 location 放宽（备份 / ARQ 导入 / batch / packaging）。"""
    limits = _location_body_limits(_NGINX_CONF.read_text(encoding='utf-8'))
    assert set(limits) == {
        '/api/v1/backup/', '/api/v1/tasks/import-',
        '/api/v1/batch/', '=/api/v1/production-summary/packaging/upload',
    }, (
        f'nginx location 级上限的覆盖范围与预期不符: {sorted(limits)}'
    )


def test_deployed_nginx_backup_limit_covers_declared_backup_max_size():
    limits = _location_body_limits(_NGINX_CONF.read_text(encoding='utf-8'))
    assert limits['/api/v1/backup/'] >= backup_service.MAX_BACKUP_FILE_SIZE


def test_deployed_nginx_import_limit_covers_declared_import_max_size():
    limits = _location_body_limits(_NGINX_CONF.read_text(encoding='utf-8'))
    assert limits['/api/v1/tasks/import-'] >= MAX_IMPORT_FILE_SIZE


def test_deployed_nginx_excel_limits_leave_multipart_headroom():
    """M2：nginx 对 batch/packaging 的 body 上限必须大于端点文件上限（余量给足）。"""
    from fastapi_app.api.v1.endpoints.import_guard import MAX_IMPORT_FILE_SIZE
    from fastapi_app.api.v1.endpoints.production_summary import MAX_PACKAGING_UPLOAD_SIZE

    limits = _location_body_limits(_NGINX_CONF.read_text(encoding='utf-8'))
    assert limits['/api/v1/batch/'] > MAX_IMPORT_FILE_SIZE, (
        'nginx 与文件上限相等 = 恰好 10MB 的合法文件被边缘 413（M2）'
    )
    assert limits['=/api/v1/production-summary/packaging/upload'] > MAX_PACKAGING_UPLOAD_SIZE

# --------------------------------------------------------------------------
# 无 Content-Length（chunked / 流式）请求体上限（P0-12）
# --------------------------------------------------------------------------
# 此前中间件在无 Content-Length 时**不计数**：请求体直接透传给端点，10MB 全局上限
# 形同虚设（改协议的客户端即可绕过）。修复为「累积计数器 + 超限立即 413」，且
# 必须边读边判（不能先攒完再判，否则内存已被打满）。
async def _chunked_body(megabytes: int, chunk_kib: int = 256):
    chunk = b'\x00' * (chunk_kib * 1024)
    for _ in range(megabytes * 1024 // chunk_kib):
        yield chunk


async def test_chunked_body_over_default_limit_is_413(client):
    """12MB 分块流（无 Content-Length）必须在 10MB 处提前 413。"""
    resp = await client.post(
        '/api/v1/orders',
        content=_chunked_body(12),
        headers={'content-type': 'application/octet-stream'},
    )
    assert resp.status_code == 413, f'流式超限请求未被拦下: {resp.status_code} {resp.text[:200]}'


async def test_chunked_body_within_limit_is_not_413(client):
    """1MB 流式请求不受影响（累积计数不得误伤正常请求）。"""
    resp = await client.post(
        '/api/v1/orders',
        content=_chunked_body(1),
        headers={'content-type': 'application/octet-stream'},
    )
    assert resp.status_code != 413, f'正常体积的流式请求被误判超限: {resp.text[:200]}'


async def test_chunked_body_path_limit_still_applies(client):
    """放宽路径（备份导入 512MB）下 12MB 流不应 413 —— 计数用的是路径级上限。"""
    resp = await client.post(
        '/api/v1/backup/import',
        content=_chunked_body(12),
        headers={'content-type': 'application/octet-stream'},
    )
    assert resp.status_code != 413, f'路径级放宽对流式请求失效: {resp.text[:200]}'

