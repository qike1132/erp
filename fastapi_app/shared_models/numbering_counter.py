"""
编号计数器模型 - 纯 SQLAlchemy 2.0 声明式

跨进程安全的业务序号分配：以 (prefix, number_date) 为粒度持久化当日已
分配的最大序号，通过 INSERT ... ON CONFLICT DO UPDATE ... RETURNING 原子
递增，消除多 worker 下"SELECT max 未提交即放锁"导致的重号窗口。
计数独立短事务提交，与业务事务解耦：业务回滚仅产生跳号，不回收序号。
"""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from fastapi_app.shared_models import Base


class NumberingCounter(Base):
    """编号计数器（prefix + 日期粒度的序号水位）"""
    __tablename__ = 'numbering_counter'

    prefix: Mapped[str] = mapped_column(String(20), primary_key=True, comment='编号前缀，如 PO/BH/SO/PP')
    number_date: Mapped[str] = mapped_column(String(8), primary_key=True, comment='日期，格式 YYYYMMDD')
    last_seq: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment='当日已分配的最大序号')
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        comment='更新时间',
    )

    def __repr__(self):
        return f'<NumberingCounter {self.prefix}:{self.number_date} seq={self.last_seq}>'
