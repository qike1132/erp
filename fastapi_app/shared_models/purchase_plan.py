"""
采购计划模型 - 纯 SQLAlchemy 2.0 声明式

主从表结构：purchase_plans（主表）+ purchase_plan_details（明细表）
出货同步表：shipment_records
"""
from datetime import datetime, timezone

from sqlalchemy import Date, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from fastapi_app.shared_models import Base


class PurchasePlan(Base):
    """采购计划主表"""
    __tablename__ = 'purchase_plans'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plan_no: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, comment='计划编号 PP-YYYYMMDD-NNNN')
    plan_month: Mapped[str] = mapped_column(String(7), nullable=False, comment='计划月份 YYYY-MM')
    customer_id: Mapped[int] = mapped_column(Integer, ForeignKey('customer.id'), nullable=False, comment='客户ID')
    customer_name: Mapped[str] = mapped_column(String(100), nullable=False, comment='客户名称(冗余)')
    status: Mapped[str] = mapped_column(String(20), nullable=False, default='pending', comment='状态: pending/confirmed/completed/cancelled')
    remark: Mapped[str | None] = mapped_column(Text, nullable=True, comment='备注')
    upload_batch: Mapped[str | None] = mapped_column(String(64), nullable=True, comment='上传批次ID')
    created_by: Mapped[str | None] = mapped_column(String(50), nullable=True, comment='创建人')
    create_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), comment='创建时间')
    update_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), comment='更新时间')

    # 关系
    details: Mapped[list["PurchasePlanDetail"]] = relationship(
        'PurchasePlanDetail', back_populates='plan', cascade='all, delete-orphan',
    )

    __table_args__ = (
        Index('idx_ppl_plan_month', 'plan_month'),
        Index('idx_ppl_customer_id', 'customer_id'),
        Index('idx_ppl_status', 'status'),
        Index('idx_ppl_upload_batch', 'upload_batch'),
        Index('idx_ppl_month_customer', 'plan_month', 'customer_id'),
        Index('idx_ppl_customer_name', 'customer_name'),
    )

    def __repr__(self):
        return f'<PurchasePlan {self.plan_no}>'

    def to_dict(self):
        return {
            'id': self.id,
            'plan_no': self.plan_no,
            'plan_month': self.plan_month,
            'customer_id': self.customer_id,
            'customer_name': self.customer_name,
            'status': self.status,
            'remark': self.remark or '',
            'upload_batch': self.upload_batch or '',
            'created_by': self.created_by or '',
            'create_time': self.create_time.strftime('%Y-%m-%d %H:%M:%S') if self.create_time else '',
            'update_time': self.update_time.strftime('%Y-%m-%d %H:%M:%S') if self.update_time else '',
        }


class PurchasePlanDetail(Base):
    """采购计划明细表"""
    __tablename__ = 'purchase_plan_details'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plan_id: Mapped[int] = mapped_column(Integer, ForeignKey('purchase_plans.id', ondelete='CASCADE'), nullable=False, comment='关联主单ID')
    product_id: Mapped[int] = mapped_column(Integer, ForeignKey('product.id'), nullable=False, comment='产品ID')
    product_name: Mapped[str] = mapped_column(String(100), nullable=False, comment='产品名称(冗余)')
    barcode: Mapped[str] = mapped_column(String(50), nullable=False, comment='69码')
    plan_date: Mapped[datetime] = mapped_column(Date, nullable=False, comment='计划日期')
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, comment='计划数量')
    shipped_qty: Mapped[int] = mapped_column(Integer, default=0, comment='已出货数量(缓存)')
    remark: Mapped[str | None] = mapped_column(Text, nullable=True, comment='备注')
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment='更新时间')

    plan: Mapped["PurchasePlan"] = relationship('PurchasePlan', back_populates='details')

    __table_args__ = (
        Index('idx_ppd_plan_date', 'plan_id', 'plan_date'),
        Index('idx_ppd_product_id', 'product_id'),
        Index('idx_ppd_plan_date_only', 'plan_date'),
        Index('idx_ppd_barcode', 'barcode'),
        Index('idx_ppd_product_name', 'product_name'),
    )

    def __repr__(self):
        return f'<PurchasePlanDetail {self.id} - plan:{self.plan_id} - {self.product_name}>'

    def to_dict(self):
        return {
            'id': self.id,
            'plan_id': self.plan_id,
            'product_id': self.product_id,
            'product_name': self.product_name,
            'barcode': self.barcode,
            'plan_date': self.plan_date.isoformat() if self.plan_date else '',
            'quantity': self.quantity,
            'shipped_qty': self.shipped_qty,
            'remaining_qty': self.quantity - self.shipped_qty,
            'remark': self.remark or '',
            'updated_at': self.updated_at.strftime('%Y-%m-%d %H:%M:%S') if self.updated_at else None,
        }


class ShipmentRecord(Base):
    """出货记录同步表 - 每日从 stock_out 同步"""
    __tablename__ = 'shipment_records'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    shipment_no: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, comment='原始出货单号')
    customer_id: Mapped[int] = mapped_column(Integer, nullable=False, comment='客户ID')
    customer_name: Mapped[str] = mapped_column(String(100), nullable=False, comment='客户名称')
    product_id: Mapped[int] = mapped_column(Integer, nullable=False, comment='产品ID')
    product_name: Mapped[str] = mapped_column(String(100), nullable=False, comment='产品名称')
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, comment='出货数量')
    shipment_date: Mapped[datetime] = mapped_column(Date, nullable=False, comment='出货日期')
    source_type: Mapped[str] = mapped_column(String(20), default='stockout', comment='来源类型')
    source_id: Mapped[int | None] = mapped_column(Integer, nullable=True, comment='来源记录ID')
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), comment='同步时间')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), comment='创建时间')
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), comment='更新时间')

    __table_args__ = (
        Index('idx_sr_customer_product_date', 'customer_id', 'product_id', 'shipment_date'),
        Index('idx_sr_shipment_date', 'shipment_date'),
        Index('idx_sr_customer_name', 'customer_name'),
    )

    def __repr__(self):
        return f'<ShipmentRecord {self.shipment_no}>'

    def to_dict(self):
        return {
            'id': self.id,
            'shipment_no': self.shipment_no,
            'customer_id': self.customer_id,
            'customer_name': self.customer_name,
            'product_id': self.product_id,
            'product_name': self.product_name,
            'quantity': self.quantity,
            'shipment_date': self.shipment_date.isoformat() if self.shipment_date else '',
            'source_type': self.source_type,
            'source_id': self.source_id,
            'synced_at': self.synced_at.strftime('%Y-%m-%d %H:%M:%S') if self.synced_at else '',
        }
