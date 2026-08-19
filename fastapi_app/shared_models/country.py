"""
国家模型 - 管理定制订单使用的国家列表
"""
from __future__ import annotations

from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from fastapi_app.shared_models import Base


class Country(Base):
    __tablename__ = 'country'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, comment='国家名称')

    def __repr__(self):
        return f'<Country {self.name}>'
