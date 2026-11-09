"""皮套出入库流水模型 - 纯 SQLAlchemy 2.0 声明式

统一台账：一条记录即一次出入库，``direction`` 区分方向。取代旧的
``case_stock_in`` / ``case_stock_out`` / ``case_inventory_log`` 三表。
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, String, Text, cast, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from fastapi_app.shared.numbering_format import NUMBERING_FORMAT_REGEX
from fastapi_app.shared_models import Base

if TYPE_CHECKING:
    from fastapi_app.shared_models.case import Case

DIRECTION_IN = 'in'
DIRECTION_OUT = 'out'
DIRECTIONS = (DIRECTION_IN, DIRECTION_OUT)


class CaseMovement(Base):
    """皮套出入库流水（单一真值来源）"""
    __tablename__ = 'case_movement'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[int] = mapped_column(
        Integer, ForeignKey('case.id', ondelete='CASCADE'), nullable=False
    )
    direction: Mapped[str] = mapped_column(String(3), nullable=False, comment='方向：in=入库 / out=出库')
    movement_no: Mapped[str] = mapped_column(String(30), unique=True, nullable=False, comment='单号（CSI-/CSO-）')
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    customer: Mapped[str | None] = mapped_column(String(100))
    movement_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), index=True
    )
    note: Mapped[str | None] = mapped_column(Text)
    create_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC), comment='更新时间'
    )

    case: Mapped[Case] = relationship('Case', back_populates='movements')

    __table_args__ = (
        # 2026-11-01 编号查询族表达式索引（P3，体检报告 §4）：
        # 取号 read_period_max / 巡检 numbering_audit_task / 对账 numbering_reconcile
        # 均按「日期段等值 + 序号段取 MAX」访问编号列。正则谓词与
        # NUMBERED_ENTITIES 白名单（numbering_reconcile.py）的格式约定强耦合——
        # 编号格式变更时必须同步重建本索引。
        Index(
            'idx_case_movement_no_date_seq',
            func.split_part(movement_no, '-', 2),
            cast(func.split_part(movement_no, '-', 3), BigInteger),
            postgresql_where=text(f"movement_no ~ '{NUMBERING_FORMAT_REGEX}'"),
        ),
        Index('idx_case_movement_case_date', 'case_id', 'movement_date'),
        Index('idx_case_movement_dir_date', 'direction', 'movement_date'),
        Index('idx_case_movement_customer_date', 'customer', 'movement_date'),
    )
