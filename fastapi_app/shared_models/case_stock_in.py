"""皮套入库模型"""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from fastapi_app.shared_models import Base


class CaseStockIn(Base):
    """皮套入库记录"""
    __tablename__ = 'case_stock_in'
    __table_args__ = (
        Index('idx_case_stockin_case_date', 'case_id', 'stockin_date'),
        Index('idx_case_stockin_customer_case', 'customer', 'case_id'),
        Index('idx_case_stockin_customer_date', 'customer', 'stockin_date'),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    stockin_no: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    stockin_date: Mapped[datetime | None] = mapped_column(DateTime, default=datetime.now, index=True)
    customer: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    case_id: Mapped[int] = mapped_column(Integer, ForeignKey('case.id'), nullable=False, index=True)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    note: Mapped[str | None] = mapped_column(Text)

    case: Mapped["Case"] = relationship('Case', backref='stockins')
