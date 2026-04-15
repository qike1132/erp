"""
备货模型 - 纯 SQLAlchemy 2.0 声明式

映射到与 Flask-SQLAlchemy StockIn 相同的 'stock_in' 表。
"""
from sqlalchemy import String, Integer, Text, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from datetime import datetime

from fastapi_app.shared_models import Base


class StockIn(Base):
    """备货模型"""
    __tablename__ = 'stock_in'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    stockin_no: Mapped[str] = mapped_column(String(20), unique=True, nullable=False, comment='备货编号')
    stockin_date: Mapped[datetime | None] = mapped_column(DateTime, default=datetime.now, index=True, comment='备货时间')
    customer: Mapped[str] = mapped_column(String(100), nullable=False, index=True, comment='客户名称')
    product_id: Mapped[int] = mapped_column(Integer, ForeignKey('product.id'), nullable=False, index=True, comment='产品ID')
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, comment='备货数量')
    note: Mapped[str | None] = mapped_column(Text, comment='备注')

    product: Mapped["Product"] = relationship('Product', backref='stockins')
    stockin_stockouts: Mapped[list["StockOut"]] = relationship('StockOut', backref='stockin')

    def __repr__(self):
        return f'<StockIn {self.stockin_no}>'
