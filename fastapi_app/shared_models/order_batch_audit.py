"""订单批次审计日志模型"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from fastapi_app.shared_models import Base


class OrderBatchAuditLog(Base):
    __tablename__ = 'order_batch_audit_log'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_no: Mapped[str] = mapped_column(String(100), nullable=False, index=True, comment='批次号')
    action: Mapped[str] = mapped_column(String(50), nullable=False, index=True, comment='操作类型')
    order_ids: Mapped[str] = mapped_column(Text, nullable=False, comment='关联订单ID列表(JSON)')
    operator_id: Mapped[int] = mapped_column(Integer, ForeignKey('user.id'), nullable=False, comment='操作人ID')
    operator_name: Mapped[str] = mapped_column(String(100), nullable=False, comment='操作人姓名')
    old_value: Mapped[str | None] = mapped_column(String(100), comment='变更前值')
    new_value: Mapped[str | None] = mapped_column(String(100), comment='变更后值')
    detail: Mapped[str | None] = mapped_column(Text, comment='详细信息')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False, index=True, comment='创建时间')

    __table_args__ = (
        Index('idx_batch_audit_batch_action', 'batch_no', 'action'),
        Index('idx_batch_audit_time', 'created_at'),
        Index('idx_order_batch_audit_operator', 'operator_id'),
    )
