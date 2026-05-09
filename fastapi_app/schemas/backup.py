"""
备份系统 Pydantic 数据模型
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class BackupRecordOut(BaseModel):
    """备份记录响应"""
    id: int
    type: str = Field(description="备份类型: full/incremental/restore")
    trigger_type: str = Field(description="触发方式: manual/auto")
    filename: str | None = None
    size: int | None = None
    table_count: int | None = None
    total_rows: int | None = None
    operator: str | None = None
    remark: str | None = None
    status: str = Field(description="状态: success/failed/running")
    error_message: str | None = None
    duration_seconds: float | None = None
    ip_address: str | None = None
    user_agent: str | None = None
    parent_record_id: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class BackupRecordListOut(BaseModel):
    """备份记录列表响应"""
    success: bool = True
    records: list[BackupRecordOut] = []
    total: int = 0
    page: int = 1
    page_size: int = 20


class BackupScheduleTask(BaseModel):
    """定时任务信息"""
    name: str = Field(description="任务名称")
    task: str = Field(description="Celery 任务名")
    schedule: str = Field(description="调度表达式")
    enabled: bool = True
    last_run: datetime | None = None
    last_status: str | None = None


class BackupScheduleOut(BaseModel):
    """定时任务配置响应"""
    success: bool = True
    tasks: list[BackupScheduleTask] = []


class BackupProgressOut(BaseModel):
    """进度查询响应"""
    success: bool = True
    task_id: str
    status: str = Field(description="pending/running/completed/failed")
    progress: float = 0.0
    phase: str = ""
    phase_label: str = ""
    started_at: str | None = None
    completed_at: str | None = None
    result: dict[str, Any] | None = None
    error: str | None = None


class BackupStatusOut(BaseModel):
    """备份系统状态响应"""
    success: bool = True
    backup_dir: str = ""
    total_backups: int = 0
    total_size_bytes: int = 0
    last_full_backup: dict[str, Any] | None = None
    disk_usage_percent: float | None = None
    checksum_tables: list[str] = []
    timestamp: str = ""


class BackupTriggerOut(BaseModel):
    """手动触发任务响应"""
    success: bool = True
    task_name: str = ""
    message: str = ""


class BackupEncryptRequest(BaseModel):
    """加密备份请求"""
    password: str = Field(min_length=1, description="加密密码")


class BackupRestoreRequest(BaseModel):
    """恢复操作确认请求"""
    confirm: bool = Field(default=False, description="确认恢复操作")
    password: str | None = Field(default=None, description="加密备份的解密密码")
