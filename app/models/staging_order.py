"""
暂存订单模型 - 用于存储批量导入的待审核订单
"""
from datetime import datetime
from app import db


class StagingOrder(db.Model):
    """暂存订单模型"""
    __tablename__ = 'staging_order'

    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.String(64), index=True, comment='会话ID，用于标识同一批导入')
    customer = db.Column(db.String(100), nullable=False, index=True, comment='客户名称')
    order_date = db.Column(db.DateTime, default=datetime.now, comment='下单时间')
    product_name = db.Column(db.String(200), nullable=False, comment='产品名称（冗余存储）')
    product_barcode = db.Column(db.String(50), comment='产品69码（冗余存储）')
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), comment='产品ID（确认后填充）')
    quantity = db.Column(db.Integer, nullable=False, comment='订单数量')
    deduct_stock = db.Column(db.Boolean, default=False, comment='是否抵扣备货')
    deduct_quantity = db.Column(db.Integer, default=0, comment='抵扣备货数量')
    note = db.Column(db.Text, comment='备注')
    status = db.Column(db.String(20), default='pending', comment='状态：pending=待审核, approved=已确认, rejected=已拒绝')
    is_validated = db.Column(db.Boolean, default=False, comment='是否已验证产品存在')
    validation_error = db.Column(db.String(500), comment='验证错误信息')
    created_at = db.Column(db.DateTime, default=datetime.now, comment='创建时间')
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now, comment='更新时间')
    import_batch_id = db.Column(db.String(64), index=True, comment='导入批次ID，用于标识批量导入的订单，刷新后自动清空')

    product = db.relationship('Product', backref=db.backref('staging_orders', lazy=True))

    __table_args__ = (
        db.Index('idx_staging_session', 'session_id'),
        db.Index('idx_staging_status', 'status'),
        db.Index('idx_staging_created', 'created_at'),
    )

    def __repr__(self):
        return f'<StagingOrder {self.id} - {self.customer} - {self.product_name}>'

    def to_dict(self):
        """转换为字典"""
        return {
            'id': self.id,
            'customer': self.customer,
            'order_date': self.order_date.strftime('%Y-%m-%d %H:%M') if self.order_date else '',
            'product_name': self.product_name,
            'product_barcode': self.product_barcode or '',
            'product_id': self.product_id,
            'quantity': self.quantity,
            'deduct_stock': self.deduct_stock,
            'deduct_quantity': self.deduct_quantity,
            'note': self.note or '',
            'status': self.status,
            'is_validated': self.is_validated,
            'validation_error': self.validation_error or '',
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S') if self.created_at else '',
            'import_batch_id': self.import_batch_id or ''
        }
