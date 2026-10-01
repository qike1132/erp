"""
手工部生产记录模型 - 纯 SQLAlchemy 2.0 声明式
"""
from datetime import UTC, date, datetime

from sqlalchemy import Date, DateTime, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from fastapi_app.shared_models import Base


class CraftWork(Base):
    """手工部生产记录"""
    __tablename__ = 'craft_work'
    __table_args__ = (
        Index('idx_craft_work_date', 'work_date'),
        Index('idx_craft_work_worker_date', 'worker_name', 'work_date'),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    worker_name: Mapped[str] = mapped_column(String(50), nullable=False, comment='工人姓名')
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, comment='生产数量')
    work_date: Mapped[date] = mapped_column(Date, nullable=False, comment='生产日期')
    remark: Mapped[str | None] = mapped_column(String(500), nullable=True, comment='备注')
    create_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), comment='创建时间')
    created_by: Mapped[str | None] = mapped_column(String(50), nullable=True, comment='创建人')
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC), comment='更新时间')

    def to_dict(self):
        return {
            'id': self.id,
            'worker_name': self.worker_name,
            'quantity': self.quantity,
            'work_date': self.work_date.isoformat() if self.work_date else '',
            'remark': self.remark or '',
            'create_time': self.create_time.strftime('%Y-%m-%d %H:%M:%S') if self.create_time else '',
            'created_by': self.created_by or '',
        }
