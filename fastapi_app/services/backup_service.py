"""兼容层 - 从 backup 包重新导出所有公共 API。

实际实现已拆分到 fastapi_app/services/backup/ 包。
此文件仅作为兼容层，确保以下导入路径仍然可用：
    from fastapi_app.services.backup_service import create_full_backup
    from fastapi_app.services.backup_service import BACKUP_DIR, ensure_backup_dir, quote_table
"""
from fastapi_app.services.backup import *  # noqa: F403
from fastapi_app.services.backup import __all__ as _backup_all

# 重新导出 __all__，确保 from backup_service import * 可用
__all__ = _backup_all
