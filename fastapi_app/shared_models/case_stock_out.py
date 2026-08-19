"""皮套出库模型"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from fastapi_app.shared_models import Base

if TYPE_CHECKING:
    from fastapi_app.shared_models.case import Case


class CaseStockOut(Base):
    """皮套出库记录"""
    __tablename__ = 'case_stock_out'
    __table_args__ = (
        Index('idx_case_stockout_case_date', 'case_id', 'stockout_date'),
        Index('idx_case_stockout_customer_date', 'customer', 'stockout_date'),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    stockout_no: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    stockout_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), index=True)
    case_id: Mapped[int] = mapped_column(Integer, ForeignKey('case.id'), nullable=False, index=True)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    customer: Mapped[str | None] = mapped_column(String(100), index=True)
    note: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC), comment='更新时间')

    case: Mapped[Case] = relationship('Case', backref='stockouts')
