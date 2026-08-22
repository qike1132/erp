"""备份系统设置模型 - 纯 SQLAlchemy 2.0 声明式

单行配置表(主键固定为 1),存储备份存储路径与保留策略。
优先级:backup_settings 表 > 环境变量(向后兼容,未初始化时回退 env)。
"""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from fastapi_app.shared_models import Base


class BackupSettings(Base):
    """备份系统设置(单行)"""
    __tablename__ = 'backup_settings'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1, comment='单行主键,固定为 1')
    backup_dir: Mapped[str] = mapped_column(String(500), nullable=False, comment='备份存储路径')
    retention_days: Mapped[int] = mapped_column(Integer, nullable=False, default=30, comment='保留天数')
    max_count: Mapped[int] = mapped_column(Integer, nullable=False, default=50, comment='最大备份数量')
    encryption_mode: Mapped[str] = mapped_column(String(20), nullable=False, default='env', comment='加密模式: off/password/key/env')
    updated_by: Mapped[str | None] = mapped_column(String(100), comment='最后更新者用户名')
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC), comment='更新时间')

    def __repr__(self):
        return f'<BackupSettings id={self.id} dir={self.backup_dir}>'
