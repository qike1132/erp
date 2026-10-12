"""
备份系统 Pydantic 数据模型
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class BackupRecordOut(BaseModel):
    """备份记录响应"""
    id: int | None = None
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
    source: str = Field(default='db', description="记录来源: db=数据库记录, fs=文件系统补录")
    encrypted: bool | None = None


class BackupRecordListOut(BaseModel):
    """备份记录列表响应"""
    success: bool = True
    records: list[BackupRecordOut] = []
    total: int = 0
    page: int = 1
    page_size: int = 20


class BackupScheduleTask(BaseModel):
    """定时任务信息"""
    id: int | None = None
    name: str = Field(description="任务名称")
    task: str = Field(description="ARQ 任务名")
    task_type: str | None = None
    cron_expr: str | None = None
    schedule: str = Field(description="调度表达式")
    enabled: bool = True
    last_run: datetime | None = None
    last_status: str | None = None


class BackupScheduleCreate(BaseModel):
    """定时任务新增"""
    name: str = Field(description="任务名称")
    task_type: str = Field(default='incremental', description="full/incremental/integrity_check/cleanup")
    cron_expr: str = Field(description="cron 表达式(如 0 2 * * *)")
    enabled: bool = True


class BackupScheduleUpdate(BaseModel):
    """定时任务更新"""
    name: str | None = None
    task_type: str | None = None
    cron_expr: str | None = None
    enabled: bool | None = None


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


class BackupRestorePlanRequest(BaseModel):
    """还原差异预览请求"""
    filename: str = Field(description="备份文件名（服务器默认路径下）")
    password: str | None = Field(
        default=None,
        description="加密备份的解密密码；缺省时加密包只回 encrypted=True 而不给出差异",
    )


class BackupRestorePlanItem(BaseModel):
    table: str
    backup_rows: int | None = None
    current_rows: int | None = None
    diff: int | None = None


class BackupRestorePlanOut(BaseModel):
    """还原差异预览响应"""
    success: bool = True
    filename: str = ""
    table_count: int = 0
    total_backup_rows: int = 0
    affected_count: int = 0
    affected_tables: list[dict] = []
    tables: list[BackupRestorePlanItem] = []
    encrypted: bool = False
    exported_at: str | None = None
    error: str | None = None


class BackupEncryptRequest(BaseModel):
    """加密备份请求"""
    password: str = Field(min_length=8, max_length=128, description="加密密码")


class BackupRestoreRequest(BaseModel):
    """恢复操作确认请求"""
    confirm: bool = Field(default=False, description="确认恢复操作")
    password: str | None = Field(default=None, description="加密备份的解密密码")


class BackupPingResponse(BaseModel):
    status: str = "ok"
    table_count: int = 0
    format_version: str = ""
    timestamp: str = ""


class BackupTableItem(BaseModel):
    name: str
    rows: int = 0


class BackupTablesResponse(BaseModel):
    success: bool = True
    tables: list[BackupTableItem] = []
    total: int = 0


class BackupImportResponse(BaseModel):
    success: bool = True
    format: str = ""
    filename: str | None = None
    results: dict[str, Any] = {}
    total_inserted: int = 0
    errors: list[str] = []
    pre_restore_backup: dict[str, Any] | None = None
    restored_at: str = ""


class BackupValidateResponse(BaseModel):
    success: bool = True
    summary: dict[str, Any] = {}


class BackupSaveResponse(BaseModel):
    success: bool = True
    format: str = "zip"
    filename: str = ""
    size: int = 0
    table_count: int = 0
    total_rows: int = 0
    exported_at: str | None = None
    exported_by: str | None = None
    includes: dict[str, Any] = {}
    remark: str = ""


class BackupListResponse(BaseModel):
    success: bool = True
    backups: list[dict[str, Any]] = []
    total: int = 0


class BackupDeleteResponse(BaseModel):
    success: bool = True
    deleted: str = ""


class IntegrityCheckResponse(BaseModel):
    checked_at: str = ""
    total: int = 0
    passed: int = 0
    failed: int = 0
    details: list[str] = []
    latest_backup: str | None = None
    latest_backup_size: int | None = None


class AsyncTaskResponse(BaseModel):
    success: bool = True
    task_id: str = ""
    message: str = ""


# ===========================================================================
# 新增端点相关的数据模型
# ===========================================================================

class BackupEncryptionRequest(BaseModel):
    """加密备份请求参数"""
    password: str | None = Field(default=None, description="加密密码，为空时从环境变量获取或生成临时密码")
    encrypt: bool = Field(default=False, description="是否启用加密（默认不加密；总开关 BACKUP_ENCRYPTION_ENABLED=false 时本字段被忽略）")


class BackupChunkInfo(BaseModel):
    """备份文件分片信息"""
    filename: str
    total_size: int
    chunk_size: int
    total_chunks: int
    encrypted: bool
    checksum: str | None = None
    bundle_id: str | None = None
    created_at: str


class BackupChunkResponse(BaseModel):
    """分片下载响应"""
    success: bool = True
    chunk_index: int
    chunk_data: bytes
    total_chunks: int
    chunk_size: int
    is_last: bool


class BackupHealthCheckResponse(BaseModel):
    """健康检查响应"""
    status: str = Field(description="overall status: healthy, degraded, unhealthy")
    timestamp: str
    checks: dict[str, dict[str, Any]] = {}
    issues: list[str] = []


class BackupValidationRequest(BaseModel):
    """备份验证请求参数"""
    password: str | None = Field(default=None, description="加密备份的解密密码")


class BackupValidationResponse(BaseModel):
    """备份验证响应"""
    success: bool = True
    filename: str
    valid: bool
    encrypted: bool
    size: int
    checksum: str | None = None
    format_version: str | None = None
    table_count: int | None = None
    total_rows: int | None = None
    created_at: str | None = None
    issues: list[str] = []


class BackupIntegrityCheckResponse(BaseModel):
    """深度完整性检查响应"""
    success: bool = True
    checked_at: str
    total_files: int
    valid_files: int
    invalid_files: int
    corrupted_files: list[str] = []
    missing_files: list[str] = []
    details: list[dict[str, Any]] = []
    cache_hit: bool = False
    cache_key: str | None = None


class BackupStatisticsResponse(BaseModel):
    """备份统计信息响应"""
    success: bool = True
    timestamp: str
    total_backups: int
    total_size_bytes: int
    last_backup_time: str | None
    backup_success_rate: float
    backup_distribution: dict[str, int] = {}
    storage_usage: dict[str, Any] = {}
    recent_backups: list[dict[str, Any]] = []


# ===========================================================================
# M1 备份任务化:手动触发 / settings / validate-path
# ===========================================================================

class BackupTaskTriggerOut(BaseModel):
    """手动触发备份任务响应(202 Accepted)"""
    success: bool = True
    task_id: str = Field(description="任务ID,用于轮询 /progress/{task_id}")
    message: str = Field(default="", description="提示信息")
    task_name: str = Field(default="", description="ARQ 任务名")


class BackupFullRequest(BaseModel):
    """全量备份触发请求"""
    remark: str = Field(default="", max_length=200, description="备份备注")
    encrypt: bool = Field(default=False, description="是否启用加密（默认不加密；总开关 BACKUP_ENCRYPTION_ENABLED=false 时被忽略）")
    password: str | None = Field(default=None, description="加密密码,为空时依次使用请求头/环境变量")
    tables: list[str] | None = Field(default=None, description="表级备份:仅备份指定表(与 exclude_tables 互斥)")
    exclude_tables: list[str] | None = Field(default=None, description="表级备份:排除指定表(与 tables 互斥)")


class BackupSettingsOut(BaseModel):
    """备份设置响应"""
    success: bool = True
    backup_dir: str = Field(default="", description="当前生效的备份路径")
    default_backup_dir: str = Field(default="", description="系统默认备份路径(恢复默认时使用)")
    retention_days: int = Field(default=30, description="保留天数")
    max_count: int = Field(default=50, description="最大备份数量")
    encryption_mode: str = Field(default="env", description="加密模式: off/password/key/env")
    updated_by: str | None = None
    updated_at: str | None = None
    initialized: bool = Field(default=False, description="表是否已初始化(未初始化时使用环境变量默认值)")


class BackupSettingsUpdate(BaseModel):
    """备份设置更新请求"""
    backup_dir: str | None = Field(default=None, max_length=500, description="自定义备份路径(须先通过 validate-path 校验)")
    retention_days: int | None = Field(default=None, ge=1, le=3650, description="保留天数")
    max_count: int | None = Field(default=None, ge=1, le=10000, description="最大备份数量")
    encryption_mode: Literal['off', 'password', 'key', 'env'] | None = Field(default=None, description="加密模式")


class BackupPathValidateRequest(BaseModel):
    """路径预校验请求"""
    path: str = Field(min_length=1, max_length=500, description="待校验的备份路径")


class BackupPathValidateResponse(BaseModel):
    """路径预校验响应"""
    valid: bool = Field(default=False, description="路径是否可用")
    error: str | None = Field(default=None, description="校验失败原因")
    message: str | None = Field(default=None, description="成功提示(如: 路径可写,空间充足)")
    path: str | None = Field(default=None, description="规范化后的路径")
