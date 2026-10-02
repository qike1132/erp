"""皮套出入库流水模型 - 纯 SQLAlchemy 2.0 声明式

统一台账：一条记录即一次出入库，``direction`` 区分方向。取代旧的
``case_stock_in`` / ``case_stock_out`` / ``case_inventory_log`` 三表。
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from fastapi_app.shared_models import Base

if TYPE_CHECKING:
    from fastapi_app.shared_models.case import Case

DIRECTION_IN = 'in'
DIRECTION_OUT = 'out'
DIRECTIONS = (DIRECTION_IN, DIRECTION_OUT)


class CaseMovement(Base):
    """皮套出入库流水（单一真值来源）"""
    __tablename__ = 'case_movement'
    __table_args__ = (
        Index('idx_case_movement_case_date', 'case_id', 'movement_date'),
        Index('idx_case_movement_dir_date', 'direction', 'movement_date'),
        Index('idx_case_movement_customer_date', 'customer', 'movement_date'),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[int] = mapped_column(
        Integer, ForeignKey('case.id', ondelete='CASCADE'), nullable=False, index=True
    )
    direction: Mapped[str] = mapped_column(String(3), nullable=False, index=True, comment='方向：in=入库 / out=出库')
    movement_no: Mapped[str] = mapped_column(String(30), unique=True, nullable=False, comment='单号（CSI-/CSO-）')
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    customer: Mapped[str | None] = mapped_column(String(100), index=True)
    movement_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), index=True
    )
    note: Mapped[str | None] = mapped_column(Text)
    create_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC), comment='更新时间'
    )

    case: Mapped[Case] = relationship('Case', back_populates='movements')
