"""
备货模型 - 纯 SQLAlchemy 2.0 声明式

映射到 'stock_in' 表。
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, String, Text, cast, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from fastapi_app.shared_models import Base

if TYPE_CHECKING:
    from fastapi_app.shared_models.product import Product
    from fastapi_app.shared_models.stock_out import StockOut
    from fastapi_app.shared_models.user import User


class StockIn(Base):
    """备货模型"""
    __tablename__ = 'stock_in'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    stockin_no: Mapped[str] = mapped_column(String(20), unique=True, nullable=False, comment='备货编号')
    stockin_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), index=True, comment='备货时间')
    customer: Mapped[str] = mapped_column(String(100), nullable=False, comment='客户名称')
    product_id: Mapped[int] = mapped_column(Integer, ForeignKey('product.id', ondelete='RESTRICT'), nullable=False, comment='产品ID')
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, comment='备货数量')
    note: Mapped[str | None] = mapped_column(Text, comment='备注')
    batch_no: Mapped[str | None] = mapped_column(String(100), comment='批次号')
    batch_completed_at: Mapped[datetime | None] = mapped_column(DateTime, comment='批次完成时间')
    batch_completed_by_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey('user.id', ondelete='SET NULL'), comment='批次完成操作人ID'
    )
    # 湖北备货确认流程：confirmed_at IS NULL 视为「未确认备货」（与订单确认流程对齐）
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime, comment='备货确认时间（湖北备货确认流程）')
    confirmed_by_id: Mapped[int | None] = mapped_column(Integer, ForeignKey('user.id', ondelete='SET NULL'), comment='备货确认人ID')
    # 备货没有软删：删除入口是硬删（is_deleted 曾作为「永不写入的死状态位」存在，
    # 7 处 isnot(True) 过滤恒真；2026-10-17 审计 Z03-R5 已连同列一起移除）。
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC), comment='更新时间')

    product: Mapped[Product] = relationship('Product', backref='stockins')
    stockin_stockouts: Mapped[list[StockOut]] = relationship('StockOut', backref='stockin')
    confirmed_by: Mapped[User | None] = relationship('User', foreign_keys=[confirmed_by_id], backref='confirmed_stockins')
    batch_completed_by: Mapped[User | None] = relationship(
        'User', foreign_keys=[batch_completed_by_id], backref='batch_completed_stockins'
    )

    __table_args__ = (
    # 2026-11-01 编号查询族表达式索引（P3，体检报告 §4）：
    # 取号 read_daily_max / 巡检 numbering_audit_task / 对账 numbering_reconcile
    # 均按「日期段等值 + 序号段取 MAX」访问编号列。正则谓词与
    # NUMBERED_ENTITIES 白名单（numbering_reconcile.py）的格式约定强耦合——
    # 编号格式变更时必须同步重建本索引。
    Index(
        'idx_stockin_no_date_seq',
        func.split_part(stockin_no, '-', 2),
        cast(func.split_part(stockin_no, '-', 3), BigInteger),
        postgresql_where=text("stockin_no ~ '^[A-Z]+-[0-9]{8}-[0-9]+$'"),
    ),
        Index('idx_stockin_batch_no', 'batch_no'),
        Index('idx_stockin_product_date', 'product_id', 'stockin_date'),
        Index('idx_stockin_customer_date', 'customer', 'stockin_date'),
        Index('idx_stockin_customer_product_date', 'customer', 'product_id', 'stockin_date'),
        # 2026-10-31 索引对齐：删除 idx_perf_stockin_product_date 声明——
        # 它与 idx_stockin_product_date (product_id, stockin_date) 仅排序方向
        # 不同，B-tree 可反向扫描，同列组合两个方向索引是纯冗余（库内只有
        # ASC 版，此声明是永不落库的幽灵索引）。
    )

    def __repr__(self):
        return f'<StockIn {self.stockin_no}>'
