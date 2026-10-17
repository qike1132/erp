"""备份 API 公共依赖：细粒度权限工厂、后台任务句柄与加密辅助。

从原 backup.py 拆分出的跨子模块共享逻辑：
- 权限工厂：_get_backup_permission / require_backup_permission
- 全局后台任务句柄：_background_tasks
- 加密辅助：_resolve_encryption / _get_encryption_password /
  _encrypt_backup_data / _decrypt_backup_data / _is_encrypted_data
"""
import asyncio
import json
import logging
import os

from fastapi import HTTPException

from fastapi_app.core.deps import require_any_permission
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
        'download_server_backup': 'backup_create',

        # M1 任务化触发
        'trigger_full_backup': 'backup_create',

        # M1 settings
        'get_backup_settings': 'backup_read',
        'update_backup_settings': 'backup_manage',
        'validate_backup_path': 'backup_read',

        # 恢复权限
        'import_backup': 'backup_restore',
        'restore_server_backup': 'backup_restore',
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
    细粒度权限检查依赖工厂。

    第八轮审计：生产 permission 表**只有 `backup_manage`**（无 backup_read/create/
    restore/delete），而 `has_permission` 只做 `xxx_manage → xxx_view` 继承、不映射到
    这些细粒度码 → 非超管对全部备份端点恒 403（导航却显示「数据备份」）。
    按本仓既有模式（require_any_permission 桥接导航码/接口码）放行 `backup_manage`：
    它语义上即「管理备份（所有权限）」，且是当前唯一可授予的码。
    """
    permission = _get_backup_permission(endpoint_name)
    return require_any_permission(permission, 'backup_manage')


logger = logging.getLogger(__name__)


def _ensure_backup_dir():  # log-context: internal helper 无请求上下文
    backup_service.ensure_backup_dir()


# ===========================================================================
# 加密辅助函数
# ===========================================================================

def _get_encryption_password(
    password: str | None = None,
    x_backup_password: str | None = None,
) -> str | None:
    """
    获取加密密码，优先级：
    1. 请求体字段（password，M4/H3：禁止使用 URL query 形式）
    2. 请求头 X-Backup-Password
    3. 环境变量 BACKUP_ENCRYPTION_PASSWORD

    均未配置时返回 None。禁止生成随机密码：随机密码无法可靠找回，
    会导致加密后的备份文件永久不可还原。
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

    return None


def _resolve_encryption(
    encrypt: bool,
    password: str | None = None,
    x_backup_password: str | None = None,
) -> tuple[bool, str | None]:
    """
    解析端点的加密意图，返回 (是否实际加密, 密码)。

    总开关优先：BACKUP_ENCRYPTION_ENABLED=false 时一律不加密，忽略调用方的 encrypt 意图
    （与 create_full_backup 口径统一）。

    请求加密但未配置任何密码时，明确降级为不加密并记录告警，
    绝不退化为随机密码加密（fail-safe：宁可明文可还原，不可密文打不开）。
    """
    from fastapi_app.services.backup.crypto import is_encryption_enabled

    if not is_encryption_enabled():
        if encrypt:
            logger.warning(
                'BACKUP_ENCRYPTION_ENABLED=false，已忽略 encrypt=True 请求，本次导出不加密'
            )
        return False, None
    if not encrypt:
        return False, None
    resolved = _get_encryption_password(password, x_backup_password)
    if not resolved:
        logger.warning(
            '请求加密备份但未配置密码（password 参数 / X-Backup-Password 头 / '
            'BACKUP_ENCRYPTION_PASSWORD 环境变量均未提供），本次备份将以未加密形式保存'
        )
        return False, None
    return True, resolved


def _encrypt_backup_data(zip_bytes: bytes, password: str) -> bytes:  # log-context: internal helper 无请求上下文
    """
    加密备份数据
    """
    try:
        # ITER-1 T3：新写密文统一走分块格式（chunked-v1）；本函数在其外再包一层
        # meta 前缀（历史上称格式 B），读侧 _decrypt_backup_data 会先剥前缀再解密。
        from fastapi_app.core.backup_encryption import encrypt_backup_auto
        encrypted_bytes, meta = encrypt_backup_auto(zip_bytes, password)
        # 添加元数据到加密数据开头（JSON格式）
        meta_json = json.dumps(meta, ensure_ascii=False).encode('utf-8')
        meta_len = len(meta_json).to_bytes(4, 'big')
        return meta_len + meta_json + encrypted_bytes
    except ImportError:
        # H2 修复：fail-closed——旧实现静默返回明文且文件名仍标 .enc，
        # 整库备份以明文落盘/外发却按加密件保管，属敏感数据泄露风险
        logger.error('加密模块不可用，拒绝导出（fail-closed）')
        raise HTTPException(status_code=503, detail='加密模块不可用，无法生成加密备份，请联系管理员') from None
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
        # H2 修复：fail-closed——解密模块不可用时无法确认数据形态，
        # 返回原始字节会把密文当明文喂给下游解析器产生误导性错误
        logger.error('加密模块不可用，拒绝解密（fail-closed）')
        raise HTTPException(status_code=503, detail='解密模块不可用，无法处理该备份，请联系管理员') from None
    except BackupFileError as e:
        raise HTTPException(status_code=400, detail=f'解密失败: {e!s}') from e
    except Exception as e:  # broad-except: 端点层兜底捕获所有异常并转为 HTTP 响应
        logger.exception('备份解密失败')
        raise HTTPException(status_code=500, detail='备份解密失败，请查看服务器日志') from e


def _is_encrypted_data(data: bytes) -> bool:
    """
    检查数据是否已加密

    2026-10-17 审计 P2-10：此前只认 meta 前缀（格式 B），而 chunked-v1 是
    新建备份的默认格式——探针对主力格式恒返回 False。
    """
    try:
        from fastapi_app.core.backup_encryption import detect_encryption_format

        if detect_encryption_format(data[:8]) == 'chunked-v1':
            return True
    except ImportError:
        pass
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
