"""
外发模块模型 - 纯 SQLAlchemy 2.0 声明式

承载湖北外发业务：
- outsource_process_type: 按 SKU 预设的固定外发工序类型（电绣/转印/配件等）
- order_outsource_process: 订单级外发工序实例（计划/实际完成时间、状态流转）
- outsource_shipment: 发货单（一键发货生成，贝乐侧为「待收货订单」）
- outsource_shipment_item: 发货单明细（每道被发货工序一行）

"返单自动带出工序"：创建订单（含湖北工厂 SKU）时，根据 SKU 预设
自动生成 order_outsource_process 记录，使返单无需重复配置。

"一键发货工作流"：发货按钮 → 生成 outsource_shipment（发货单）→ 贝乐用户端
看到「待收货」新订单 → 贝乐确认收货 → shipment 状态流转为「已完成」闭环。
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
        String(20), default='pending', nullable=False, index=True, comment='状态：pending/shipped/received'
    )
    shipped_quantity: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment='发货数量（发货时录入，每道工序独立）'
    )
    received_quantity: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment='收货数量（确认收货时默认等于发货数量）'
    )
    planned_start_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment='计划开始时间'
    )
    planned_end_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment='计划完成时间'
    )
    actual_start_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment='实际发货时间'
    )
    actual_end_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment='实际收货时间'
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
        # 第十四轮：外发工序生成是 check-then-act（SELECT 已有集合 → INSERT），双击/并发
        # 会重复插入同一 (订单,明细,产品,工序) 的工序行，各自可发满目标量 → 超发。
        # 加唯一索引兜底；NULLS NOT DISTINCT 使 order_item_id 为空（单 SKU 旧订单）的行
        # 也参与去重（PG 默认把 NULL 视为互不相同）。
        Index(
            'uq_oosp_order_item_product_process',
            'order_id', 'order_item_id', 'product_id', 'process_type',
            unique=True, postgresql_nulls_not_distinct=True,
        ),
    )

    def __repr__(self):
        return f'<OrderOutsourceProcess order_id={self.order_id} type={self.process_type} status={self.status}>'


class OrderOutsourceProcessFlow(Base):
    """外发工序发货/收货流水：每次发/收一条记录，用于台账审计（时间+工序+数量+操作人）。"""

    __tablename__ = 'order_outsource_process_flow'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    process_id: Mapped[int] = mapped_column(
        Integer, ForeignKey('order_outsource_process.id', ondelete='CASCADE'), nullable=False, index=True,
        comment='工序ID'
    )
    action: Mapped[str] = mapped_column(String(10), nullable=False, comment='动作：ship=发货 / receive=收货')
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, comment='本次数量')
    operator: Mapped[str | None] = mapped_column(String(50), nullable=True, comment='操作人')
    create_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True, comment='操作时间'
    )

    process: Mapped[OrderOutsourceProcess] = relationship('OrderOutsourceProcess')

    __table_args__ = (
        Index('ix_oospf_process_time', 'process_id', 'create_time'),
    )

    def __repr__(self):
        return f'<OrderOutsourceProcessFlow process_id={self.process_id} action={self.action} qty={self.quantity}>'


# 发货单状态的唯一权威定义：业务代码引用这些常量，禁止新增字面量。
# shipped  = 已发货（工厂视角）= 贝乐用户端「待收货」
# received = 已收货（贝乐确认收货后）= 「已完成」闭环
SHIPMENT_STATUS_SHIPPED = 'shipped'
SHIPMENT_STATUS_RECEIVED = 'received'

VALID_SHIPMENT_STATUSES = frozenset({SHIPMENT_STATUS_SHIPPED, SHIPMENT_STATUS_RECEIVED})


class OutsourceShipment(Base):
    """发货单：一键发货生成的单据，同时也是推送给贝乐用户端的「待收货订单」。

    状态机（shipped → received）：
    - shipped：一键发货后生成，贝乐用户端显示为「待收货」；
    - received：贝乐确认收货后置为「已完成」，闭环。
    """

    __tablename__ = 'outsource_shipment'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    shipment_no: Mapped[str] = mapped_column(String(24), unique=True, nullable=False, index=True, comment='发货单号 FH-YYYYMMDD-XXXX')
    order_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey('order.id', ondelete='SET NULL'), nullable=True, index=True,
        comment='来源订单ID（一键发货按订单发起；订单删除后置空保留发货单审计）',
    )
    customer: Mapped[str | None] = mapped_column(String(100), nullable=True, comment='冗余客户名称')
    status: Mapped[str] = mapped_column(
        String(20), default=SHIPMENT_STATUS_SHIPPED, nullable=False, index=True,
        comment='状态：shipped=已发货(待收货)/received=已收货(已完成)',
    )
    shipped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, comment='发货时间')
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, comment='收货时间')
    shipped_by: Mapped[str | None] = mapped_column(String(50), nullable=True, comment='发货人')
    received_by: Mapped[str | None] = mapped_column(String(50), nullable=True, comment='收货人')
    remark: Mapped[str | None] = mapped_column(Text, nullable=True, comment='备注')
    create_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), comment='创建时间'
    )
    update_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), comment='更新时间'
    )

    items: Mapped[list[OutsourceShipmentItem]] = relationship(
        'OutsourceShipmentItem',
        cascade='all, delete-orphan',
        back_populates='shipment',
        order_by='OutsourceShipmentItem.id',
    )

    __table_args__ = (
        Index('ix_outsource_shipment_status_create', 'status', 'create_time'),
    )

    def __repr__(self):
        return f'<OutsourceShipment {self.shipment_no} status={self.status}>'


class OutsourceShipmentItem(Base):
    """发货单明细：发货单下每一道被发货的工序一行（SKU + 工序 + 数量）。"""

    __tablename__ = 'outsource_shipment_item'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    shipment_id: Mapped[int] = mapped_column(
        Integer, ForeignKey('outsource_shipment.id', ondelete='CASCADE'), nullable=False, index=True,
        comment='发货单ID',
    )
    process_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey('order_outsource_process.id', ondelete='SET NULL'), nullable=True, index=True,
        comment='对应外发工序实例ID（工序删除后置空保留明细审计）',
    )
    product_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey('product.id', ondelete='SET NULL'), nullable=True, comment='产品(SKU)ID'
    )
    product_name: Mapped[str | None] = mapped_column(String(200), nullable=True, comment='冗余产品名称')
    process_type: Mapped[str] = mapped_column(String(50), nullable=False, comment='工序类型：电绣/转印/配件等')
    shipped_quantity: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment='发货数量')
    received_quantity: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment='收货数量')
    create_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), comment='创建时间'
    )

    shipment: Mapped[OutsourceShipment] = relationship('OutsourceShipment', back_populates='items')

    __table_args__ = (
        Index('ix_outsource_shipment_item_process', 'process_id'),
    )

    def __repr__(self):
        return f'<OutsourceShipmentItem shipment_id={self.shipment_id} type={self.process_type} shipped={self.shipped_quantity}>'
