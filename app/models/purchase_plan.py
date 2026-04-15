"""
采购计划模型

主从表结构：purchase_plans（主表）+ purchase_plan_details（明细表）
出货同步表：shipment_records
"""
from datetime import datetime
from app import db


class PurchasePlan(db.Model):
    """采购计划主表"""
    __tablename__ = 'purchase_plans'

    id = db.Column(db.Integer, primary_key=True)
    plan_no = db.Column(db.String(32), unique=True, nullable=False, comment='计划编号 PP-YYYYMMDD-NNNN')
    plan_month = db.Column(db.String(7), nullable=False, comment='计划月份 YYYY-MM')
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id'), nullable=False, comment='客户ID')
    customer_name = db.Column(db.String(100), nullable=False, comment='客户名称(冗余)')
    status = db.Column(db.String(20), nullable=False, default='pending', comment='状态: pending/confirmed/completed/cancelled')
    remark = db.Column(db.Text, nullable=True, comment='备注')
    upload_batch = db.Column(db.String(64), nullable=True, comment='上传批次ID')
    created_by = db.Column(db.String(50), nullable=True, comment='创建人')
    create_time = db.Column(db.DateTime, default=datetime.now, comment='创建时间')
    update_time = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now, comment='更新时间')

    details = db.relationship('PurchasePlanDetail', backref='plan', cascade='all, delete-orphan', lazy='dynamic')

    __table_args__ = (
        db.Index('idx_ppl_plan_month', 'plan_month'),
        db.Index('idx_ppl_customer_id', 'customer_id'),
        db.Index('idx_ppl_status', 'status'),
        db.Index('idx_ppl_upload_batch', 'upload_batch'),
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


class PurchasePlanDetail(db.Model):
    """采购计划明细表"""
    __tablename__ = 'purchase_plan_details'

    id = db.Column(db.Integer, primary_key=True)
    plan_id = db.Column(db.Integer, db.ForeignKey('purchase_plans.id', ondelete='CASCADE'), nullable=False, comment='关联主单ID')
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False, comment='产品ID')
    product_name = db.Column(db.String(100), nullable=False, comment='产品名称(冗余)')
    barcode = db.Column(db.String(50), nullable=False, comment='69码')
    plan_date = db.Column(db.Date, nullable=False, comment='计划日期')
    quantity = db.Column(db.Integer, nullable=False, comment='计划数量')
    shipped_qty = db.Column(db.Integer, default=0, comment='已出货数量(缓存)')
    remark = db.Column(db.Text, nullable=True, comment='备注')

    __table_args__ = (
        db.Index('idx_ppd_plan_date', 'plan_id', 'plan_date'),
        db.Index('idx_ppd_product_id', 'product_id'),
        db.Index('idx_ppd_plan_date_only', 'plan_date'),
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
        }


class ShipmentRecord(db.Model):
    """出货记录同步表 - 每日从 stock_out 同步"""
    __tablename__ = 'shipment_records'

    id = db.Column(db.Integer, primary_key=True)
    shipment_no = db.Column(db.String(64), unique=True, nullable=False, comment='原始出货单号')
    customer_id = db.Column(db.Integer, nullable=False, comment='客户ID')
    customer_name = db.Column(db.String(100), nullable=False, comment='客户名称')
    product_id = db.Column(db.Integer, nullable=False, comment='产品ID')
    product_name = db.Column(db.String(100), nullable=False, comment='产品名称')
    quantity = db.Column(db.Integer, nullable=False, comment='出货数量')
    shipment_date = db.Column(db.Date, nullable=False, comment='出货日期')
    source_type = db.Column(db.String(20), default='stockout', comment='来源类型')
    source_id = db.Column(db.Integer, nullable=True, comment='来源记录ID')
    synced_at = db.Column(db.DateTime, nullable=False, default=datetime.now, comment='同步时间')
    created_at = db.Column(db.DateTime, default=datetime.now, comment='创建时间')

    __table_args__ = (
        db.Index('idx_sr_customer_product_date', 'customer_id', 'product_id', 'shipment_date'),
        db.Index('idx_sr_shipment_date', 'shipment_date'),
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
