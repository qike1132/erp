"""备份记录模型 - 纯 SQLAlchemy 2.0 声明式"""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import BigInteger, DateTime, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from fastapi_app.shared_models import Base


class BackupRecord(Base):
    """备份操作记录"""
    __tablename__ = 'backup_record'
    __table_args__ = (
        Index('idx_backup_record_type', 'type'),
        Index('idx_backup_record_status', 'status'),
        Index('idx_backup_record_created_at', 'created_at'),
        Index('idx_backup_record_trigger_type', 'trigger_type'),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    type: Mapped[str] = mapped_column(String(20), nullable=False, comment='备份类型: full/incremental/restore')
    trigger_type: Mapped[str] = mapped_column(String(20), nullable=False, default='manual', comment='触发方式: manual/auto')
    filename: Mapped[str | None] = mapped_column(String(255), comment='备份文件名')
    size: Mapped[int | None] = mapped_column(BigInteger, comment='文件大小(字节)')
    table_count: Mapped[int | None] = mapped_column(Integer, comment='表数量')
    total_rows: Mapped[int | None] = mapped_column(BigInteger, comment='总行数')
    operator: Mapped[str | None] = mapped_column(String(100), comment='操作者用户名')
    remark: Mapped[str | None] = mapped_column(Text, comment='备注')
    status: Mapped[str] = mapped_column(String(20), nullable=False, default='running', comment='状态: success/failed/running')
    error_message: Mapped[str | None] = mapped_column(Text, comment='错误信息')
    duration_seconds: Mapped[float | None] = mapped_column(comment='耗时(秒)')
    ip_address: Mapped[str | None] = mapped_column(String(45), comment='操作者IP地址')
    user_agent: Mapped[str | None] = mapped_column(Text, comment='浏览器UA')
    parent_record_id: Mapped[int | None] = mapped_column(Integer, comment='父备份记录ID(增量备份指向全量备份)')
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), comment='创建时间')
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC), comment='更新时间')

    def __repr__(self):
        return f'<BackupRecord {self.id} {self.type} {self.status}>'
