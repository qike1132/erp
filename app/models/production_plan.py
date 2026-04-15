"""
排产计划模型
"""
from datetime import datetime
from app import db


class ProductionPlan(db.Model):
    """排产计划模型"""
    __tablename__ = 'production_plan'

    id = db.Column(db.Integer, primary_key=True)
    customer_name = db.Column(db.String(100), nullable=False, index=True, comment='客户名称')
    product_name = db.Column(db.String(100), nullable=False, comment='客户产品名称')
    barcode = db.Column(db.String(50), nullable=False, index=True, comment='69码')
    quantity = db.Column(db.Integer, nullable=False, comment='排产计划数量')
    plan_date = db.Column(db.Date, nullable=False, comment='计划日期')
    status = db.Column(db.String(20), default='pending', comment='状态: pending/confirmed/completed')
    shipped_qty = db.Column(db.Integer, default=0, comment='已出货数量')
    remark = db.Column(db.Text, nullable=True, comment='备注')
    upload_batch = db.Column(db.String(64), nullable=True, comment='上传批次ID')
    create_time = db.Column(db.DateTime, default=datetime.now, comment='创建时间')
    update_time = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now, comment='更新时间')
    created_by = db.Column(db.String(50), nullable=True, comment='创建人')

    __table_args__ = (
        db.Index('idx_pp_barcode', 'barcode'),
        db.Index('idx_pp_customer_name', 'customer_name'),
        db.Index('idx_pp_plan_date', 'plan_date'),
        db.Index('idx_pp_plan_month', 'plan_date', 'customer_name'),
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


class ProductionPlanLog(db.Model):
    """排产计划操作日志模型"""
    __tablename__ = 'production_plan_log'

    id = db.Column(db.Integer, primary_key=True)
    plan_id = db.Column(db.Integer, nullable=False, index=True, comment='排产计划ID')
    action = db.Column(db.String(20), nullable=False, comment='操作类型: create/update/delete')
    old_value = db.Column(db.Text, nullable=True, comment='变更前数据(JSON)')
    new_value = db.Column(db.Text, nullable=True, comment='变更后数据(JSON)')
    operator = db.Column(db.String(50), nullable=False, comment='操作人')
    operate_time = db.Column(db.DateTime, default=datetime.now, comment='操作时间')

    def __repr__(self):
        return f'<ProductionPlanLog {self.id} - {self.action} - plan:{self.plan_id}>'


class StagingPurchasePlan(db.Model):
    """暂存采购计划模型 - 批量上传预览用"""
    __tablename__ = 'staging_purchase_plan'

    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.String(64), nullable=False, index=True, comment='会话ID')
    customer_name = db.Column(db.String(100), nullable=False, comment='客户名称')
    product_name = db.Column(db.String(100), nullable=False, comment='产品名称')
    barcode = db.Column(db.String(50), nullable=False, comment='69码')
    quantity = db.Column(db.Integer, nullable=False, comment='计划数量')
    plan_date = db.Column(db.Date, nullable=False, comment='计划日期')
    plan_month = db.Column(db.String(7), nullable=True, comment='计划月份 YYYY-MM')
    remark = db.Column(db.Text, nullable=True, comment='备注')
    is_validated = db.Column(db.Boolean, default=False, comment='是否已验证')
    validation_error = db.Column(db.String(500), nullable=True, comment='验证错误信息')
    upload_batch_id = db.Column(db.String(64), nullable=True, index=True, comment='上传批次ID')
    created_at = db.Column(db.DateTime, default=datetime.now, comment='创建时间')

    __table_args__ = (
        db.Index('idx_spp_session', 'session_id'),
        db.Index('idx_spp_batch', 'upload_batch_id'),
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
            'is_validated': self.is_validated,
            'validation_error': self.validation_error or '',
            'upload_batch_id': self.upload_batch_id or '',
        }
