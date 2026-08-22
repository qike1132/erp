"""定时备份任务配置模型 - 纯 SQLAlchemy 2.0 声明式

替代 ARQ cron_schedules 中的硬编码定时备份配置,支持用户在界面配置
定时增量备份(周期/时间/启停),由 scheduler_poller 读取本表调度执行。
"""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from fastapi_app.shared_models import Base


class BackupSchedule(Base):
    """定时备份任务配置"""
    __tablename__ = 'backup_schedule'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, comment='任务名称')
    task_type: Mapped[str] = mapped_column(String(20), nullable=False, default='incremental', comment='任务类型: full/incremental')
    cron_expr: Mapped[str] = mapped_column(String(100), nullable=False, comment='cron 表达式(如 0 2 * * * 或 0 6,10,14,18,22 * * *)')
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, comment='是否启用')
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), comment='上次执行时间')
    last_status: Mapped[str | None] = mapped_column(String(20), comment='上次执行结果: success/failed/running')
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), comment='创建时间')
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC), comment='更新时间')

    def __repr__(self):
        return f'<BackupSchedule {self.id} {self.name} {self.task_type} enabled={self.enabled}>'
