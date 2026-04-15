"""皮套库存日志模型"""
from sqlalchemy import String, Integer, ForeignKey, DateTime, Text, Index, desc
from sqlalchemy.orm import Mapped, mapped_column, relationship
from datetime import datetime

from fastapi_app.shared_models import Base


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
    change_date: Mapped[datetime | None] = mapped_column(DateTime, default=datetime.now, index=True)
    related_id: Mapped[str | None] = mapped_column(String(50))
    note: Mapped[str | None] = mapped_column(Text)
    customer: Mapped[str | None] = mapped_column(String(100), index=True)

    case: Mapped["Case"] = relationship('Case', backref='inventory_logs')

    def __repr__(self):
        return f'<CaseInventoryLog {self.case_id} - {self.change_type}>'
