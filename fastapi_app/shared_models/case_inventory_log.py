"""皮套库存日志模型"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, desc
from sqlalchemy.orm import Mapped, mapped_column, relationship

from fastapi_app.shared_models import Base

if TYPE_CHECKING:
    from fastapi_app.shared_models.case import Case


class CaseInventoryLog(Base):
    """皮套库存变化日志"""
    __tablename__ = 'case_inventory_log'
    __table_args__ = (
        Index('idx_case_inventory_log_case_date', 'case_id', desc('change_date')),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[int] = mapped_column(Integer, ForeignKey('case.id', ondelete='CASCADE'), nullable=False, index=True)
    change_type: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    change_quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    change_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), index=True)
    related_id: Mapped[str | None] = mapped_column(String(50))
    note: Mapped[str | None] = mapped_column(Text)
    customer: Mapped[str | None] = mapped_column(String(100), index=True)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC), comment='更新时间')

    case: Mapped[Case] = relationship('Case', backref='inventory_logs')

    def __repr__(self):
        return f'<CaseInventoryLog {self.case_id} - {self.change_type}>'
