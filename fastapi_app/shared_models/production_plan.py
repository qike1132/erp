"""
排产计划模型 - 纯 SQLAlchemy 2.0 声明式

映射到与 Flask-SQLAlchemy ProductionPlan 相同的 'production_plan' 表。
"""
from datetime import datetime

from sqlalchemy import Boolean, Date, DateTime, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from fastapi_app.shared_models import Base


class ProductionPlan(Base):
    """排产计划模型"""
    __tablename__ = 'production_plan'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    customer_name: Mapped[str] = mapped_column(String(100), nullable=False, index=True, comment='客户名称')
    product_name: Mapped[str] = mapped_column(String(100), nullable=False, comment='客户产品名称')
    barcode: Mapped[str] = mapped_column(String(50), nullable=False, index=True, comment='69码')
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, comment='排产计划数量')
    plan_date: Mapped[datetime] = mapped_column(Date, nullable=False, comment='计划日期')
    status: Mapped[str] = mapped_column(String(20), default='pending', comment='状态: pending/confirmed/completed')
    shipped_qty: Mapped[int] = mapped_column(Integer, default=0, comment='已出货数量')
    remark: Mapped[str | None] = mapped_column(Text, nullable=True, comment='备注')
    upload_batch: Mapped[str | None] = mapped_column(String(64), nullable=True, comment='上传批次ID')
    create_time: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, comment='创建时间')
    update_time: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now, comment='更新时间')
    created_by: Mapped[str | None] = mapped_column(String(50), nullable=True, comment='创建人')

    __table_args__ = (
        Index('idx_pp_barcode', 'barcode'),
        Index('idx_pp_customer_name', 'customer_name'),
        Index('idx_pp_plan_date', 'plan_date'),
        Index('idx_pp_plan_month', 'plan_date', 'customer_name'),
    )

    def __repr__(self):
        return f'<ProductionPlan {self.id} - {self.customer_name} - {self.product_name}>'

    def to_dict(self):
        """转换为字典"""
        return {
            'id': self.id,
            'customer_name': self.customer_name,
            'product_name': self.product_name,
            'barcode': self.barcode,
            'quantity': self.quantity,
            'shipped_qty': self.shipped_qty,
            'remaining_qty': self.quantity - self.shipped_qty,
            'plan_date': self.plan_date.isoformat() if self.plan_date else '',
            'status': self.status,
            'remark': self.remark or '',
            'upload_batch': self.upload_batch or '',
            'create_time': self.create_time.strftime('%Y-%m-%d %H:%M:%S') if self.create_time else '',
            'update_time': self.update_time.strftime('%Y-%m-%d %H:%M:%S') if self.update_time else '',
            'created_by': self.created_by or '',
        }


class ProductionPlanLog(Base):
    """排产计划操作日志模型"""
    __tablename__ = 'production_plan_log'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plan_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True, comment='排产计划ID')
    action: Mapped[str] = mapped_column(String(20), nullable=False, comment='操作类型: create/update/delete')
    old_value: Mapped[str | None] = mapped_column(Text, nullable=True, comment='变更前数据(JSON)')
    new_value: Mapped[str | None] = mapped_column(Text, nullable=True, comment='变更后数据(JSON)')
    operator: Mapped[str] = mapped_column(String(50), nullable=False, comment='操作人')
    operate_time: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, comment='操作时间')
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now, comment='更新时间')

    def __repr__(self):
        return f'<ProductionPlanLog {self.id} - {self.action} - plan:{self.plan_id}>'


class StagingPurchasePlan(Base):
    """暂存采购计划模型 - 批量上传预览用"""
    __tablename__ = 'staging_purchase_plan'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True, comment='会话ID')
    customer_name: Mapped[str] = mapped_column(String(100), nullable=False, comment='客户名称')
    product_name: Mapped[str] = mapped_column(String(100), nullable=False, comment='产品名称')
    barcode: Mapped[str] = mapped_column(String(50), nullable=False, comment='69码')
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, comment='计划数量')
    plan_date: Mapped[datetime] = mapped_column(Date, nullable=False, comment='计划日期')
    plan_month: Mapped[str | None] = mapped_column(String(7), nullable=True, comment='计划月份 YYYY-MM')
    remark: Mapped[str | None] = mapped_column(Text, nullable=True, comment='备注')
    is_validated: Mapped[bool] = mapped_column(Boolean, default=False, comment='是否已验证')
    validation_error: Mapped[str | None] = mapped_column(String(500), nullable=True, comment='验证错误信息')
    upload_batch_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True, comment='上传批次ID')
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, comment='创建时间')
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now, comment='更新时间')

    __table_args__ = (
        Index('idx_spp_session', 'session_id'),
        Index('idx_spp_batch', 'upload_batch_id'),
    )

    def __repr__(self):
        return f'<StagingPurchasePlan {self.id} - {self.customer_name} - {self.product_name}>'

    def to_dict(self):
        """转换为字典"""
        return {
            'id': self.id,
            'customer_name': self.customer_name,
            'product_name': self.product_name,
            'barcode': self.barcode,
            'quantity': self.quantity,
            'plan_date': self.plan_date.isoformat() if self.plan_date else '',
            'plan_month': self.plan_month or '',
            'remark': self.remark or '',
            'is_validated': bool(self.is_validated),
            'validation_error': self.validation_error or '',
            'upload_batch_id': self.upload_batch_id or '',
        }
