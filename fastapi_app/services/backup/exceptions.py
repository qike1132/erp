"""备份/恢复自定义异常层级。"""
from __future__ import annotations


class BackupError(Exception):
    """备份操作基础异常"""


class BackupLockError(BackupError):
    """获取备份/恢复锁失败（REV-06: 不降级继续）"""


class BackupFileError(BackupError):
    """备份文件操作失败"""


class DatabaseSnapshotError(BackupError):
    """数据库快照操作失败"""


class BinaryLogError(BackupError):
    """二进制日志操作失败"""


class RestoreError(BackupError):
    """恢复操作失败"""
