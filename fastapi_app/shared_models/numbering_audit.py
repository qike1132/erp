"""编号巡检结果（拉取式暴露：ARQ 周期计算，端点读取，spec §4.5）。

每次巡检为每个编号实体写一行（scope=前缀，如 PO/BH），格式违规另写一行
（scope=<表>.<列>）。counter_behind 只对反向偏差报警：数据号 > 水位；正向
跳号（删除/回滚）是文档化的正常语义，不报警。
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from fastapi_app.shared_models import Base


class NumberingAudit(Base):
    """编号不变量巡检记录（每轮每实体一行 + 每违规列一行）"""
    __tablename__ = 'numbering_audit'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scope: Mapped[str] = mapped_column(String(64), nullable=False, comment='PO/BH/... 或 <表>.<列>')
    counter_behind: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment='1=水位落后数据')
    detail: Mapped[str] = mapped_column(String(255), nullable=False, default='', comment='偏差描述')
    checked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, comment='巡检时间')

    def __repr__(self):
        return f'<NumberingAudit {self.scope} behind={self.counter_behind}>'
