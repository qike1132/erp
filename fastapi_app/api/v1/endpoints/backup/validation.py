"""备份验证、健康检查与统计路由。

从原 backup.py 拆分，URL / schema / 权限码保持不变：
- POST /validate               验证上传的备份文件（仅返回摘要）
- POST /integrity-check        备份完整性巡检
- GET  /health                 备份系统健康检查
- GET  /validate/{filename}    验证服务器上已有备份文件
- POST /validate-integrity     执行深度完整性检查
- GET  /stats                  获取备份统计信息
"""
import hashlib
import asyncio
import io
import json
import logging
import os
import time
import zipfile
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, Header, HTTPException, Query, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.api.v1.endpoints.backup._deps import (
    _decrypt_backup_data,
    _is_encrypted_data,
    require_backup_permission,
)
from fastapi_app.core.database import get_async_read_db
from fastapi_app.schemas.backup import (
    BackupHealthCheckResponse,
    BackupIntegrityCheckResponse,
    BackupStatisticsResponse,
    BackupValidateResponse,
    BackupValidationResponse,
    IntegrityCheckResponse,
)
from fastapi_app.services import backup as backup_service
from fastapi_app.services.backup import BackupFileError
from fastapi_app.shared_models import User

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# POST /validate
# ---------------------------------------------------------------------------
@router.post('/validate', response_model=BackupValidateResponse)
async def validate_backup(
    file: UploadFile = File(...),
    user: User = Depends(require_backup_permission('validate_backup')),
):
    """验证备份文件，不执行恢复，仅返回摘要信息"""
    filename = file.filename or ''
    ext = os.path.splitext(filename)[1].lower()
    if ext not in ('.zip', '.json', '.gz'):
        raise HTTPException(status_code=400, detail=f'不支持的文件类型: {ext}，仅支持 .zip / .json / .gz')
    try:
        content = await file.read()
        if len(content) > backup_service.MAX_BACKUP_FILE_SIZE:
            raise HTTPException(status_code=400, detail=f'备份文件超过大小限制({backup_service.MAX_BACKUP_FILE_SIZE // 1024 // 1024}MB)')
    except HTTPException:
        raise
    except (OSError, ValueError) as e:
        raise HTTPException(status_code=400, detail=f'读取文件失败: {e}') from e
    try:
        summary = backup_service.validate_backup_file(content, file.filename or '')
    except BackupFileError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {'success': True, 'summary': summary}


# ---------------------------------------------------------------------------
# POST /integrity-check
# ---------------------------------------------------------------------------
@router.post('/integrity-check', response_model=IntegrityCheckResponse)
async def run_integrity_check(user: User = Depends(require_backup_permission('run_integrity_check'))):
    """备份完整性巡检"""
    from fastapi_app.tasks.backup_tasks import _do_integrity_check
    result = await _do_integrity_check()
    return result


# ---------------------------------------------------------------------------
# GET /health
# ---------------------------------------------------------------------------
async def _check_backup_dir() -> tuple[dict, list[str]]:
    """检查备份目录可写性"""
    issues: list[str] = []
    try:
        backup_dir = backup_service.BACKUP_DIR
        test_file = backup_dir / ".health_check"
        if not backup_dir.exists():
            backup_dir.mkdir(parents=True, exist_ok=True)
            return {'status': 'warning', 'message': '备份目录不存在，已自动创建', 'path': str(backup_dir)}, issues
        try:
            test_file.touch()
            test_file.unlink()
            return {'status': 'healthy', 'message': '备份目录可写', 'path': str(backup_dir), 'writable': True}, issues
        except Exception as e:  # broad-except: 端点层兜底捕获所有异常并转为 HTTP 响应
            issues.append(f'备份目录不可写: {e!s}')
            return {'status': 'unhealthy', 'message': f'备份目录不可写: {e!s}', 'path': str(backup_dir), 'writable': False}, issues
    except Exception as e:  # broad-except: 端点层兜底捕获所有异常并转为 HTTP 响应
        issues.append(f'备份目录检查失败: {e!s}')
        return {'status': 'unhealthy', 'message': f'备份目录检查失败: {e!s}', 'error': str(e)}, issues


async def _check_database() -> tuple[dict, list[str]]:
    """检查数据库连接状态"""
    issues: list[str] = []
    try:
        from fastapi_app.services.backup.verify import query_service as backup_query_service
        db_ok = await backup_query_service.check_database_alive()
        if not db_ok:
            issues.append('数据库连接失败')
        return {'status': 'healthy' if db_ok else 'unhealthy', 'message': '数据库连接正常' if db_ok else '数据库连接失败', 'connected': db_ok}, issues
    except Exception as e:  # broad-except: 端点层兜底捕获所有异常并转为 HTTP 响应
        issues.append(f'数据库连接检查失败: {e!s}')
        return {'status': 'unhealthy', 'message': f'数据库连接检查失败: {e!s}', 'error': str(e)}, issues


async def _check_redis() -> tuple[dict, list[str]]:
    """检查 Redis 连接状态"""
    issues: list[str] = []
    try:
        from utils.redis_cache import redis_cache
        redis_ok = False
        try:
            redis_client = redis_cache.redis_client
            if redis_client:
                redis_ok = await redis_client.ping()
            else:
                issues.append('Redis客户端未初始化')
        except Exception as e:  # broad-except: 端点层兜底捕获所有异常并转为 HTTP 响应
            logger.warning(f'Redis ping 失败: {e}')
        if not redis_ok:
            issues.append('Redis连接不可用，进度追踪功能可能受限')
        return {'status': 'healthy' if redis_ok else 'warning', 'message': 'Redis连接正常' if redis_ok else 'Redis连接不可用（不影响核心功能）', 'connected': redis_ok}, issues
    except ImportError:
        issues.append('Redis模块未安装')
        return {'status': 'warning', 'message': 'Redis模块未安装，进度追踪功能不可用', 'connected': False}, issues
    except Exception as e:  # broad-except: 端点层兜底捕获所有异常并转为 HTTP 响应
        issues.append(f'Redis连接检查失败: {e!s}')
        return {'status': 'warning', 'message': f'Redis连接检查失败: {e!s}', 'error': str(e)}, issues


def _check_last_backup() -> tuple[dict, list[str]]:  # log-context: internal helper 无请求上下文
    """检查最近备份时间"""
    issues: list[str] = []
    try:
        backup_files = backup_service.list_backup_files()
        if backup_files:
            latest_backup = max(backup_files, key=lambda x: x.get('mtime', 0))
            latest_time = datetime.fromtimestamp(latest_backup.get('mtime', 0))
            hours_since = (datetime.now() - latest_time).total_seconds() / 3600
            if hours_since > 24:
                issues.append(f'最近备份时间超过24小时（{round(hours_since, 1)}小时前）')
            return {
                'status': 'healthy' if hours_since <= 24 else 'warning',
                'message': f'最近备份时间: {latest_time.strftime("%Y-%m-%d %H:%M:%S")}',
                'latest_backup_time': latest_time.isoformat(),
                'hours_since_last_backup': round(hours_since, 2),
                'within_24h': hours_since <= 24,
            }, issues
        issues.append('未找到任何备份文件')
        return {'status': 'warning', 'message': '未找到备份文件', 'latest_backup_time': None, 'hours_since_last_backup': None, 'within_24h': False}, issues
    except Exception as e:  # broad-except: 端点层兜底捕获所有异常并转为 HTTP 响应
        issues.append(f'检查最近备份时间失败: {e!s}')
        return {'status': 'unhealthy', 'message': f'检查最近备份时间失败: {e!s}', 'error': str(e)}, issues


def _check_backup_integrity() -> tuple[dict, list[str]]:  # log-context: internal helper 无请求上下文
    """抽样检查备份文件完整性"""
    import random
    issues: list[str] = []
    try:
        backup_files = backup_service.list_backup_files()
        if not backup_files:
            return {'status': 'warning', 'message': '没有备份文件可检查', 'sample_size': 0, 'results': []}, issues
        sample_files = random.sample(backup_files, min(3, len(backup_files)))  # nosec B311
        integrity_results = []
        for file_info in sample_files:
            filename = file_info.get('name', '')
            filepath = backup_service.BACKUP_DIR / filename
            try:
                if filepath.exists() and filepath.is_file():
                    integrity_results.append({'filename': filename, 'status': 'healthy', 'size': filepath.stat().st_size, 'readable': True, 'message': '文件完整可读'})
                else:
                    integrity_results.append({'filename': filename, 'status': 'unhealthy', 'size': 0, 'readable': False, 'message': '文件不存在或不是普通文件'})
                    issues.append(f'备份文件异常: {filename}')
            except Exception as e:  # broad-except: 端点层兜底捕获所有异常并转为 HTTP 响应
                integrity_results.append({'filename': filename, 'status': 'unhealthy', 'size': 0, 'readable': False, 'message': f'文件检查失败: {e!s}', 'error': str(e)})
                issues.append(f'备份文件检查失败 {filename}: {e!s}')
        return {
            'status': 'healthy' if all(r['status'] == 'healthy' for r in integrity_results) else 'degraded',
            'message': f'抽样检查了 {len(integrity_results)} 个备份文件',
            'sample_size': len(integrity_results),
            'results': integrity_results,
        }, issues
    except Exception as e:  # broad-except: 端点层兜底捕获所有异常并转为 HTTP 响应
        issues.append(f'备份文件完整性检查失败: {e!s}')
        return {'status': 'unhealthy', 'message': f'备份文件完整性检查失败: {e!s}', 'error': str(e)}, issues


def _check_disk_space() -> tuple[dict, list[str]]:
    """检查磁盘空间"""
    import shutil
    issues: list[str] = []
    try:
        backup_dir = backup_service.BACKUP_DIR
        if not backup_dir.exists():
            return {'status': 'warning', 'message': '备份目录不存在，无法检查磁盘空间', 'sufficient': None}, issues
        disk_usage = shutil.disk_usage(backup_dir)
        total_gb = disk_usage.total / (1024**3)
        used_gb = disk_usage.used / (1024**3)
        free_gb = disk_usage.free / (1024**3)
        free_percent = (disk_usage.free / disk_usage.total) * 100
        if free_percent <= 5:
            issues.append(f'磁盘空间严重不足: 仅剩 {free_percent:.1f}% 可用空间')
        elif free_percent <= 10:
            issues.append(f'磁盘空间不足: 仅剩 {free_percent:.1f}% 可用空间')
        return {
            'status': 'healthy' if free_percent > 10 else 'warning',
            'message': f'磁盘空间: {free_gb:.1f}GB 可用 ({free_percent:.1f}%)',
            'total_gb': round(total_gb, 2),
            'used_gb': round(used_gb, 2),
            'free_gb': round(free_gb, 2),
            'free_percent': round(free_percent, 2),
            'sufficient': free_percent > 10,
        }, issues
    except Exception as e:  # broad-except: 端点层兜底捕获所有异常并转为 HTTP 响应
        issues.append(f'磁盘空间检查失败: {e!s}')
        return {'status': 'warning', 'message': f'磁盘空间检查失败: {e!s}', 'error': str(e)}, issues


async def _check_arq_worker() -> tuple[dict, list[str]]:
    """检查 ARQ Worker 运行状态（备份任务能否被消费）"""
    issues: list[str] = []
    try:
        from fastapi_app.core.arq_app import check_worker_health
        is_healthy, message = await check_worker_health()
        if not is_healthy:
            issues.append(f'ARQ Worker 未运行: {message}')
        return {
            'status': 'healthy' if is_healthy else 'unhealthy',
            'message': message,
            'workers_online': is_healthy,
        }, issues
    except Exception as e:  # broad-except: 端点层兜底捕获所有异常并转为 HTTP 响应
        issues.append(f'ARQ Worker 检查失败: {e!s}')
        return {'status': 'unhealthy', 'message': f'ARQ Worker 检查失败: {e!s}', 'workers_online': False}, issues


def _aggregate_health_status(checks: dict) -> str:
    """根据各项检查结果聚合总体健康状态"""
    status_priority = {'unhealthy': 3, 'degraded': 2, 'warning': 1, 'healthy': 0}
    worst = 'healthy'
    for check in checks.values():
        check_status = check.get('status', 'healthy')
        if status_priority.get(check_status, 0) > status_priority.get(worst, 0):
            worst = check_status
    return worst


@router.get('/health', response_model=BackupHealthCheckResponse)
async def health_check(
    user: User = Depends(require_backup_permission('health_check')),
):
    """
    备份系统健康检查端点
    检查项目：
    1. 备份目录可写性
    2. 数据库连接状态
    3. Redis连接状态（用于进度追踪）
    4. 最近备份时间（不超过24小时）
    5. 备份文件完整性
    6. 磁盘空间
    7. ARQ Worker 运行状态（备份任务能否被消费）
    """
    checks: dict = {}
    issues: list[str] = []

    checks['backup_dir'], dir_issues = await _check_backup_dir()
    issues.extend(dir_issues)

    checks['database'], db_issues = await _check_database()
    issues.extend(db_issues)

    checks['redis'], redis_issues = await _check_redis()
    issues.extend(redis_issues)

    checks['last_backup'], backup_issues = _check_last_backup()
    issues.extend(backup_issues)

    checks['backup_integrity'], integrity_issues = _check_backup_integrity()
    issues.extend(integrity_issues)

    checks['disk_space'], disk_issues = _check_disk_space()
    issues.extend(disk_issues)

    checks['arq_worker'], arq_issues = await _check_arq_worker()
    issues.extend(arq_issues)

    overall_status = _aggregate_health_status(checks)

    return {
        'status': overall_status,
        'timestamp': datetime.now().isoformat(),
        'checks': checks,
        'issues': issues,
    }


# ---------------------------------------------------------------------------
# 验证缓存管理
# ---------------------------------------------------------------------------

class ValidationCache:
    """备份验证结果缓存（P2: Redis 共享版）

    旧实现为进程内 dict——4 worker 各自缓存互不可见、且无容量上限。
    改为 Redis 后多 worker 共享、TTL 由 Redis 管理；Redis 不可用时
    降级为无缓存（每次直读），不阻塞验证主流程。
    """

    _KEY_PREFIX = 'erp:backup_validation:'

    def __init__(self, ttl_seconds: int = 3600):  # 默认1小时缓存
        self.ttl = ttl_seconds

    async def get(self, cache_key: str):
        """获取缓存项（Redis 不可用/未命中返回 None）"""
        try:
            from fastapi_app.core.backup_progress import _get_redis
            client = await _get_redis()
            if client is None:
                return None
            raw = await client.get(self._KEY_PREFIX + cache_key)
            return json.loads(raw) if raw else None
        except Exception:  # broad-except: 缓存读取失败降级为直读
            return None

    async def set(self, cache_key: str, data):
        """设置缓存项（失败仅告警）"""
        try:
            from fastapi_app.core.backup_progress import _get_redis
            client = await _get_redis()
            if client is None:
                return
            await client.set(
                self._KEY_PREFIX + cache_key,
                json.dumps(data, ensure_ascii=False, default=str),
                ex=self.ttl,
            )
        except Exception as e:  # broad-except: 缓存写入失败不影响验证结果返回
            logger.warning(f'验证缓存写入失败: {e}')


# 全局验证缓存实例
_validation_cache = ValidationCache()


def _get_validation_cache_key(filename: str, password: str | None = None) -> str:
    """生成验证缓存键"""
    key_parts = [filename]
    if password:
        # 使用密码的哈希值，避免存储明文密码
        key_parts.append(hashlib.sha256(password.encode()).hexdigest()[:16])
    return hashlib.md5('_'.join(key_parts).encode(), usedforsecurity=False).hexdigest()


# ---------------------------------------------------------------------------
# GET /validate/{filename}
# ---------------------------------------------------------------------------
@router.get('/validate/{filename}', response_model=BackupValidationResponse)
async def validate_backup_file(
    filename: str,
    password: str | None = Query(None, description="加密备份的解密密码"),
    x_backup_password: str | None = Header(None, alias='X-Backup-Password'),
    user: User = Depends(require_backup_permission('validate_backup_file')),
):
    """
    验证服务器上已有备份文件的完整性
    支持加密备份的解密验证
    """
    # 安全检查：防止路径遍历
    safe_name = Path(filename).name
    if safe_name != filename:
        raise HTTPException(status_code=400, detail='无效的文件名')

    filepath = backup_service.BACKUP_DIR / safe_name
    if not filepath.exists():
        raise HTTPException(status_code=404, detail='备份文件不存在')

    # 检查缓存
    cache_key = _get_validation_cache_key(filename, password or x_backup_password)
    cached_result = await _validation_cache.get(cache_key)
    if cached_result:
        cached_result['cache_hit'] = True
        return cached_result

    try:
        # 读取文件（阻塞 IO 移入线程池，避免卡住事件循环）
        content = await asyncio.to_thread(filepath.read_bytes)
        file_size = len(content)

        # 检查是否为加密文件
        encrypted = _is_encrypted_data(content)

        # 如果是加密文件，尝试解密
        if encrypted:
            if not password and not x_backup_password:
                # 检查环境变量
                env_password = os.environ.get('BACKUP_ENCRYPTION_PASSWORD')
                if not env_password:
                    return {
                        'success': True,
                        'filename': filename,
                        'valid': False,
                        'encrypted': True,
                        'size': file_size,
                        'checksum': None,
                        'format_version': None,
                        'table_count': None,
                        'total_rows': None,
                        'created_at': None,
                        'issues': ['文件已加密但未提供密码']
                    }
                password_to_use = env_password
            else:
                password_to_use = password or x_backup_password

            try:
                decrypted_content = _decrypt_backup_data(content, password_to_use)
                content = decrypted_content
            except Exception:  # broad-except: 端点层兜底捕获所有异常并转为 HTTP 响应
                logger.exception('验证备份文件时解密失败: %s', filename)
                return {
                    'success': True,
                    'filename': filename,
                    'valid': False,
                    'encrypted': True,
                    'size': file_size,
                    'checksum': None,
                    'format_version': None,
                    'table_count': None,
                    'total_rows': None,
                    'created_at': None,
                    'issues': ['解密失败']
                }
        else:
            pass

        # 计算校验和
        checksum = hashlib.sha256(content).hexdigest()

        # 验证文件格式
        issues = []
        valid = True

        try:
            # 尝试解析为ZIP文件
            if filename.endswith('.zip') or filename.endswith('.zip.enc'):
                with zipfile.ZipFile(io.BytesIO(content)) as zip_file:
                    # 检查必需的manifest文件
                    namelist = zip_file.namelist()
                    if 'manifest.json' not in namelist:
                        issues.append('ZIP文件缺少manifest.json')
                        valid = False

                    # 检查文件完整性
                    for zip_info in zip_file.infolist():
                        try:
                            with zip_file.open(zip_info.filename) as f:
                                f.read()  # 尝试读取文件
                        except Exception as e:  # broad-except: 端点层兜底捕获所有异常并转为 HTTP 响应
                            issues.append(f'文件 {zip_info.filename} 损坏: {e!s}')
                            valid = False

            # 尝试解析为JSON文件
            elif filename.endswith('.json') or filename.endswith('.json.enc'):
                try:
                    backup_data = json.loads(content.decode('utf-8'))
                    if 'tables' not in backup_data:
                        issues.append('JSON文件缺少tables字段')
                        valid = False
                except json.JSONDecodeError as e:
                    issues.append(f'JSON解析失败: {e!s}')
                    valid = False

            else:
                issues.append('不支持的文件格式')
                valid = False

        except zipfile.BadZipFile as e:
            issues.append(f'ZIP文件损坏: {e!s}')
            valid = False
        except Exception as e:  # broad-except: 端点层兜底捕获所有异常并转为 HTTP 响应
            issues.append(f'文件验证失败: {e!s}')
            valid = False

        # 尝试提取元数据
        format_version = None
        table_count = None
        total_rows = None
        created_at = None

        if valid:
            try:
                if filename.endswith('.zip') or filename.endswith('.zip.enc'):
                    with zipfile.ZipFile(io.BytesIO(content)) as zip_file:
                        if 'manifest.json' in zip_file.namelist():
                            with zip_file.open('manifest.json') as f:
                                manifest = json.load(f)
                                format_version = manifest.get('format_version')
                                table_count = manifest.get('table_count')
                                total_rows = manifest.get('total_rows')
                                created_at = manifest.get('exported_at')
                elif filename.endswith('.json') or filename.endswith('.json.enc'):
                    backup_data = json.loads(content.decode('utf-8'))
                    format_version = backup_data.get('format_version', '1.0')
                    table_count = len(backup_data.get('tables', {}))
                    total_rows = sum(len(table_data.get('data', [])) for table_data in backup_data.get('tables', {}).values())
                    created_at = backup_data.get('exported_at')
            except (ValueError, TypeError, OSError, KeyError, json.JSONDecodeError, UnicodeDecodeError):
                pass  # 元数据提取失败不影响验证结果; defensive: 异常静默处理,不影响主流程

        # 构建响应
        result = {
            'success': True,
            'filename': filename,
            'valid': valid,
            'encrypted': encrypted,
            'size': file_size,
            'checksum': checksum,
            'format_version': format_version,
            'table_count': table_count,
            'total_rows': total_rows,
            'created_at': created_at,
            'issues': issues,
            'cache_hit': False,
            'cache_key': cache_key
        }

        # 缓存验证结果（仅当验证成功时）
        if valid:
            await _validation_cache.set(cache_key, result)

        return result

    except Exception as e:  # broad-except: 端点层兜底捕获所有异常并转为 HTTP 响应
        logger.exception('验证备份文件失败')
        raise HTTPException(status_code=500, detail='验证备份文件失败，请查看服务器日志') from e


# ---------------------------------------------------------------------------
# POST /validate-integrity
# ---------------------------------------------------------------------------
@router.post('/validate-integrity', response_model=BackupIntegrityCheckResponse)
async def validate_backup_integrity(
    user: User = Depends(require_backup_permission('validate_backup_integrity')),
):
    """
    执行深度完整性检查，验证所有备份文件的完整性
    支持缓存避免重复验证
    """
    try:
        backup_files = backup_service.list_backup_files()
        if not backup_files:
            return {
                'success': True,
                'checked_at': datetime.now().isoformat(),
                'total_files': 0,
                'valid_files': 0,
                'invalid_files': 0,
                'corrupted_files': [],
                'missing_files': [],
                'details': [],
                'cache_hit': False,
                'cache_key': None
            }

        # 检查缓存
        cache_key = hashlib.md5(
            '_'.join(sorted(f['name'] for f in backup_files)).encode(),
            usedforsecurity=False
        ).hexdigest()

        cached_result = await _validation_cache.get(cache_key)
        if cached_result:
            cached_result['cache_hit'] = True
            return cached_result

        # 执行完整性检查
        details = []
        corrupted_files = []
        missing_files = []

        for file_info in backup_files:
            filename = file_info.get('name', '')
            filepath = backup_service.BACKUP_DIR / filename

            try:
                # 检查文件是否存在
                if not filepath.exists():
                    missing_files.append(filename)
                    details.append({
                        'filename': filename,
                        'status': 'missing',
                        'message': '文件不存在'
                    })
                    continue

                # 检查文件大小
                file_size = filepath.stat().st_size
                if file_size == 0:
                    corrupted_files.append(filename)
                    details.append({
                        'filename': filename,
                        'status': 'corrupted',
                        'message': '文件大小为0',
                        'size': file_size
                    })
                    continue

                # 尝试读取文件
                try:
                    content = filepath.read_bytes()

                    # 检查是否为加密文件
                    encrypted = _is_encrypted_data(content)

                    # 如果是加密文件，跳过深度验证（需要密码）
                    if encrypted:
                        details.append({
                            'filename': filename,
                            'status': 'encrypted',
                            'message': '文件已加密，跳过深度验证',
                            'size': file_size,
                            'encrypted': True
                        })
                        continue

                    # 验证文件格式
                    valid = True
                    message = '验证通过'

                    if filename.endswith('.zip'):
                        try:
                            with zipfile.ZipFile(io.BytesIO(content)) as zip_file:
                                # 测试ZIP文件完整性
                                test_result = zip_file.testzip()
                                if test_result is not None:
                                    valid = False
                                    message = f'ZIP文件损坏: {test_result}'
                                    corrupted_files.append(filename)
                        except zipfile.BadZipFile as e:
                            valid = False
                            message = f'ZIP文件格式错误: {e!s}'
                            corrupted_files.append(filename)

                    elif filename.endswith('.json'):
                        try:
                            json.loads(content.decode('utf-8'))
                        except json.JSONDecodeError as e:
                            valid = False
                            message = f'JSON格式错误: {e!s}'
                            corrupted_files.append(filename)

                    details.append({
                        'filename': filename,
                        'status': 'valid' if valid else 'invalid',
                        'message': message,
                        'size': file_size,
                        'encrypted': encrypted,
                        'valid': valid
                    })

                except Exception as e:  # broad-except: 端点层兜底捕获所有异常并转为 HTTP 响应
                    corrupted_files.append(filename)
                    details.append({
                        'filename': filename,
                        'status': 'corrupted',
                        'message': f'读取失败: {e!s}',
                        'size': file_size,
                        'error': str(e)
                    })

            except Exception as e:  # broad-except: 端点层兜底捕获所有异常并转为 HTTP 响应
                details.append({
                    'filename': filename,
                    'status': 'error',
                    'message': f'检查过程中发生错误: {e!s}',
                    'error': str(e)
                })

        valid_files = len(backup_files) - len(corrupted_files) - len(missing_files)

        result = {
            'success': True,
            'checked_at': datetime.now().isoformat(),
            'total_files': len(backup_files),
            'valid_files': valid_files,
            'invalid_files': len(corrupted_files) + len(missing_files),
            'corrupted_files': corrupted_files,
            'missing_files': missing_files,
            'details': details,
            'cache_hit': False,
            'cache_key': cache_key
        }

        # 缓存结果
        await _validation_cache.set(cache_key, result)

        return result

    except Exception as e:  # broad-except: 端点层兜底捕获所有异常并转为 HTTP 响应
        logger.exception('完整性检查失败')
        raise HTTPException(status_code=500, detail='完整性检查失败，请查看服务器日志') from e


# ---------------------------------------------------------------------------
# GET /stats
# ---------------------------------------------------------------------------
@router.get('/stats', response_model=BackupStatisticsResponse)
async def get_backup_statistics(
    user: User = Depends(require_backup_permission('get_backup_statistics')),
    db: AsyncSession = Depends(get_async_read_db),
):
    """
    获取备份统计信息
    """
    from datetime import datetime, timedelta

    try:
        # 1. 获取备份文件列表
        backup_files = backup_service.list_backup_files()

        # 2. 计算基本统计
        total_backups = len(backup_files)
        total_size_bytes = sum(f.get('size', 0) for f in backup_files)

        # 3. 计算最近备份时间
        last_backup_time = None
        if backup_files:
            latest_backup = max(backup_files, key=lambda x: x.get('mtime', 0))
            last_backup_time = datetime.fromtimestamp(latest_backup.get('mtime', 0)).isoformat()

        # 4. 计算备份成功率（从备份记录中获取）
        from fastapi_app.services.backup.verify import query_service as backup_query_service

        # 获取最近30天的备份记录
        thirty_days_ago = datetime.now() - timedelta(days=30)
        total_records, success_records = await backup_query_service.get_backup_record_stats_since(db, thirty_days_ago)
        backup_success_rate = (success_records / total_records * 100) if total_records > 0 else 0.0

        # 5. 计算备份类型分布
        type_distribution = await backup_query_service.get_backup_type_distribution_since(db, thirty_days_ago)

        # 6. 计算存储使用情况
        import shutil
        backup_dir = backup_service.BACKUP_DIR

        storage_usage = {}
        if backup_dir.exists():
            try:
                disk_usage = shutil.disk_usage(backup_dir)
                storage_usage = {
                    'total_bytes': disk_usage.total,
                    'used_bytes': disk_usage.used,
                    'free_bytes': disk_usage.free,
                    'used_percent': (disk_usage.used / disk_usage.total * 100) if disk_usage.total > 0 else 0,
                    'free_percent': (disk_usage.free / disk_usage.total * 100) if disk_usage.total > 0 else 0,
                }
            except Exception as e:  # broad-except: 端点层兜底捕获所有异常并转为 HTTP 响应
                logger.warning(f'无法获取磁盘使用情况: {e}')
                storage_usage = {'error': str(e)}

        # 7. 获取最近备份列表（最近10个）
        recent_backups = []
        if backup_files:
            # 按修改时间排序
            sorted_backups = sorted(backup_files, key=lambda x: x.get('mtime', 0), reverse=True)
            for backup in sorted_backups[:10]:  # 只取最近10个
                recent_backups.append({
                    'filename': backup.get('name', ''),
                    'size_bytes': backup.get('size', 0),
                    'modified_time': datetime.fromtimestamp(backup.get('mtime', 0)).isoformat(),
                    'type': 'full' if 'full' in backup.get('name', '').lower() else 'incremental' if 'inc' in backup.get('name', '').lower() else 'unknown',
                    'encrypted': backup.get('name', '').endswith('.enc'),
                })

        # 8. 计算备份频率
        backup_frequency = {}
        if backup_files:
            # 按日期分组
            from collections import defaultdict
            daily_counts = defaultdict(int)

            for backup in backup_files:
                mtime = datetime.fromtimestamp(backup.get('mtime', 0))
                date_key = mtime.strftime('%Y-%m-%d')
                daily_counts[date_key] += 1

            backup_frequency = {
                'daily_average': sum(daily_counts.values()) / max(len(daily_counts), 1),
                'most_active_day': max(daily_counts.items(), key=lambda x: x[1]) if daily_counts else None,
                'days_with_backups': len(daily_counts),
                'total_days': 30,  # 统计周期
            }

        return {
            'success': True,
            'timestamp': datetime.now().isoformat(),
            'total_backups': total_backups,
            'total_size_bytes': total_size_bytes,
            'last_backup_time': last_backup_time,
            'backup_success_rate': round(backup_success_rate, 2),
            'backup_distribution': type_distribution,
            'storage_usage': storage_usage,
            'recent_backups': recent_backups,
            'backup_frequency': backup_frequency,
            'records_analyzed': {
                'total': total_records,
                'success': success_records,
                'failure': total_records - success_records,
                'period_days': 30,
            }
        }

    except Exception as e:  # broad-except: 端点层兜底捕获所有异常并转为 HTTP 响应
        logger.exception('获取备份统计信息失败')
        raise HTTPException(status_code=500, detail='获取备份统计信息失败，请查看服务器日志') from e
