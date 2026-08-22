"""备份 API 公共依赖：细粒度权限工厂、后台任务句柄与加密辅助。

从原 backup.py 拆分出的跨子模块共享逻辑：
- 权限工厂：_get_backup_permission / require_backup_permission
- 全局后台任务句柄：_background_tasks
- 加密辅助：_get_encryption_password / _encrypt_backup_data /
  _decrypt_backup_data / _is_encrypted_data
"""
import asyncio
import json
import logging
import os
import secrets

from fastapi import HTTPException

from fastapi_app.core.deps import require_permission
from fastapi_app.services import backup as backup_service

_background_tasks: set[asyncio.Task] = set()


# ===========================================================================
# 细粒度权限控制
# ===========================================================================

def _get_backup_permission(endpoint_name: str) -> str:  # log-context: internal helper 无请求上下文
    """
    根据端点名称返回对应的细粒度权限
    权限映射：
    - backup_read: 查看备份列表和状态
    - backup_create: 创建备份
    - backup_restore: 恢复备份
    - backup_delete: 删除备份
    - backup_manage: 管理备份（所有权限）
    """
    permission_map = {
        # 读取权限
        'ping': 'backup_read',
        'list_backup_tables': 'backup_read',
        'list_server_backups': 'backup_read',
        'backup_status': 'backup_read',
        'get_backup_records': 'backup_read',
        'get_backup_schedule': 'backup_read',
        'get_backup_info': 'backup_read',

        # 创建权限
        'export_backup': 'backup_create',
        'export_backup_enhanced': 'backup_create',
        'save_backup_to_server': 'backup_create',
        'save_incremental_backup': 'backup_create',

        # 恢复权限
        'import_backup': 'backup_restore',
        'restore_server_backup': 'backup_restore',
        'restore_incremental_backup': 'backup_restore',
        'async_import_backup': 'backup_restore',
        'async_restore_server_backup': 'backup_restore',

        # 删除权限
        'delete_server_backup': 'backup_delete',

        # 验证权限
        'validate_backup': 'backup_read',
        'validate_server_backup': 'backup_read',
        'run_integrity_check': 'backup_read',

        # 进度查询
        'get_restore_progress': 'backup_read',

        # 统计
        'get_backup_statistics': 'backup_read',

        # 调度
        'trigger_backup_schedule': 'backup_create',

        # 分片导出
        'export_backup_chunk': 'backup_create',

        # 健康检查
        'health_check': 'backup_read',

        # 验证文件
        'validate_backup_file': 'backup_read',

        # 深度完整性检查
        'validate_backup_integrity': 'backup_read',
    }

    return permission_map.get(endpoint_name, 'backup_manage')


def require_backup_permission(endpoint_name: str):  # log-context: internal helper 无请求上下文
    """
    细粒度权限检查依赖工厂
    """
    permission = _get_backup_permission(endpoint_name)
    return require_permission(permission)


logger = logging.getLogger(__name__)


def _ensure_backup_dir():  # log-context: internal helper 无请求上下文
    backup_service.ensure_backup_dir()


# ===========================================================================
# 加密辅助函数
# ===========================================================================

def _get_encryption_password(
    password: str | None = None,
    x_backup_password: str | None = None,
) -> str:
    """
    获取加密密码，优先级：
    1. 请求参数中的 password
    2. 请求头 X-Backup-Password
    3. 环境变量 BACKUP_ENCRYPTION_PASSWORD
    4. 生成临时密码并记录到日志
    """
    # 1. 检查请求参数
    if password:
        return password

    # 2. 检查请求头
    if x_backup_password:
        return x_backup_password

    # 3. 检查环境变量
    env_password = os.environ.get('BACKUP_ENCRYPTION_PASSWORD')
    if env_password:
        return env_password

    # 4. 生成临时密码
    temp_password = secrets.token_urlsafe(32)
    logger.warning(
        f'未提供加密密码，使用临时密码：{temp_password[:8]}... '
        f'建议设置 BACKUP_ENCRYPTION_PASSWORD 环境变量或通过请求头/参数提供密码'
    )
    return temp_password


def _encrypt_backup_data(zip_bytes: bytes, password: str) -> bytes:  # log-context: internal helper 无请求上下文
    """
    加密备份数据
    """
    try:
        from fastapi_app.core.backup_encryption import encrypt_backup
        encrypted_bytes, meta = encrypt_backup(zip_bytes, password)
        # 添加元数据到加密数据开头（JSON格式）
        meta_json = json.dumps(meta, ensure_ascii=False).encode('utf-8')
        meta_len = len(meta_json).to_bytes(4, 'big')
        return meta_len + meta_json + encrypted_bytes
    except ImportError:
        logger.error('加密模块不可用，备份数据将不加密')
        return zip_bytes
    except (ValueError, RuntimeError, OSError) as e:
        logger.exception('备份加密失败')
        raise HTTPException(status_code=500, detail='备份加密失败，请查看服务器日志') from e


def _decrypt_backup_data(encrypted_bytes: bytes, password: str) -> bytes:  # log-context: internal helper 无请求上下文
    """
    解密备份数据
    """
    try:
        from fastapi_app.core.backup_encryption import BackupFileError, decrypt_backup

        # 解析元数据长度
        if len(encrypted_bytes) < 4:
            raise BackupFileError('加密数据格式无效')

        meta_len = int.from_bytes(encrypted_bytes[:4], 'big')
        if len(encrypted_bytes) < 4 + meta_len:
            raise BackupFileError('加密数据格式无效')

        # 跳过元数据，解密实际数据
        encrypted_data = encrypted_bytes[4 + meta_len:]
        return decrypt_backup(encrypted_data, password)
    except ImportError:
        logger.error('加密模块不可用，假设数据未加密')
        return encrypted_bytes
    except BackupFileError as e:
        raise HTTPException(status_code=400, detail=f'解密失败: {e!s}') from e
    except Exception as e:  # broad-except: 端点层兜底捕获所有异常并转为 HTTP 响应
        logger.exception('备份解密失败')
        raise HTTPException(status_code=500, detail='备份解密失败，请查看服务器日志') from e


def _is_encrypted_data(data: bytes) -> bool:
    """
    检查数据是否已加密
    """
    try:
        # 检查是否有元数据长度前缀
        if len(data) < 4:
            return False

        meta_len = int.from_bytes(data[:4], 'big')
        if len(data) < 4 + meta_len:
            return False

        # 尝试解析元数据
        meta_json = data[4:4 + meta_len]
        meta = json.loads(meta_json.decode('utf-8'))
        return meta.get('encrypted', False)
    except (ValueError, TypeError, OSError, KeyError, json.JSONDecodeError, UnicodeDecodeError, IndexError):
        return False
