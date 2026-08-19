"""
外发模块模型 - 纯 SQLAlchemy 2.0 声明式

承载湖北外发业务：
- outsource_process_type: 按 SKU 预设的固定外发工序类型（电绣/转印/配件等）
- order_outsource_process: 订单级外发工序实例（计划/实际完成时间、状态流转）

"返单自动带出工序"：创建订单（含湖北工厂 SKU）时，根据 SKU 预设
自动生成 order_outsource_process 记录，使返单无需重复配置。
"""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from fastapi_app.shared_models import Base

if TYPE_CHECKING:
    from fastapi_app.shared_models.order import Order
    from fastapi_app.shared_models.order_item import OrderItem
    from fastapi_app.shared_models.product import Product

# 外发工序状态
OUTSOURCE_PROCESS_STATUSES = ('pending', 'in_progress', 'completed')

# 状态显示文案
OUTSOURCE_PROCESS_STATUS_LABELS = {
    'pending': '待开始',
    'in_progress': '进行中',
    'completed': '已完成',
}


class OutsourceProcessType(Base):
    """SKU 外发工序预设：为某个产品（SKU）固定配置的外发工序类型清单。"""

    __tablename__ = 'outsource_process_type'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(
        Integer, ForeignKey('product.id'), nullable=False, index=True, comment='产品(SKU)ID'
    )
    process_type: Mapped[str] = mapped_column(String(50), nullable=False, comment='工序类型：电绣/转印/配件等')
    sort_order: Mapped[int] = mapped_column(Integer, default=0, comment='工序顺序，数值越小越靠前')
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, comment='是否启用')
    remark: Mapped[str | None] = mapped_column(String(200), nullable=True, comment='备注')
    created_by: Mapped[str | None] = mapped_column(String(50), nullable=True, comment='创建人')
    create_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), comment='创建时间'
    )
    update_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), comment='更新时间'
    )

    product: Mapped[Product] = relationship('Product')

    __table_args__ = (
        UniqueConstraint('product_id', 'process_type', name='uq_outsource_pt_product_process'),
        Index('ix_outsource_pt_product_sort', 'product_id', 'sort_order'),
    )

    def __repr__(self):
        return f'<OutsourceProcessType product_id={self.product_id} type={self.process_type}>'


class OrderOutsourceProcess(Base):
    """订单外发工序实例：订单下某个 SKU 需经历的一道外发工序。"""

    __tablename__ = 'order_outsource_process'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(
        Integer, ForeignKey('order.id', ondelete='CASCADE'), nullable=False, index=True, comment='主订单ID'
    )
    order_item_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey('order_item.id', ondelete='CASCADE'), nullable=True, index=True,
        comment='订单明细ID（SKU 粒度）；单 SKU 订单可为空'
    )
    product_id: Mapped[int] = mapped_column(
        Integer, ForeignKey('product.id'), nullable=False, index=True, comment='产品(SKU)ID'
    )
    product_name: Mapped[str | None] = mapped_column(String(200), nullable=True, comment='冗余产品名称，便于展示')
    process_type: Mapped[str] = mapped_column(String(50), nullable=False, comment='工序类型：电绣/转印/配件等')
    sort_order: Mapped[int] = mapped_column(Integer, default=0, comment='工序顺序，数值越小越靠前')
    status: Mapped[str] = mapped_column(
        String(20), default='pending', nullable=False, index=True, comment='状态：pending/in_progress/completed'
    )
    planned_start_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment='计划开始时间'
    )
    planned_end_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment='计划完成时间'
    )
    actual_start_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment='实际开始时间'
    )
    actual_end_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment='实际完成时间'
    )
    remark: Mapped[str | None] = mapped_column(Text, nullable=True, comment='备注')
    created_by: Mapped[str | None] = mapped_column(String(50), nullable=True, comment='创建人')
    create_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), comment='创建时间'
    )
    update_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), comment='更新时间'
    )

    order: Mapped[Order] = relationship('Order')
    order_item: Mapped[OrderItem | None] = relationship('OrderItem')
    product: Mapped[Product] = relationship('Product')

    __table_args__ = (
        Index('ix_oosp_order_sort', 'order_id', 'sort_order'),
        Index('ix_oosp_status_date', 'status', 'create_time'),
        Index('ix_oosp_order_item', 'order_item_id'),
    )

    def __repr__(self):
        return f'<OrderOutsourceProcess order_id={self.order_id} type={self.process_type} status={self.status}>'
