"""
暂存出货模型 - 用于存储批量导入的待审核出货
"""
from datetime import datetime
from app import db


class StagingStockOut(db.Model):
    """暂存出货模型"""
    __tablename__ = 'staging_stock_out'

    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.String(64), index=True, comment='会话ID，用于标识同一批导入')
    customer = db.Column(db.String(100), nullable=True, index=True, comment='客户名称')
    stockout_date = db.Column(db.DateTime, default=datetime.now, comment='出货时间')
    product_name = db.Column(db.String(200), nullable=False, comment='产品名称（冗余存储）')
    product_barcode = db.Column(db.String(50), comment='产品69码（冗余存储）')
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), comment='产品ID（确认后填充）')
    quantity = db.Column(db.Integer, nullable=False, comment='出货数量')
    note = db.Column(db.Text, comment='备注')
    order_type = db.Column(db.String(20), default='regular', comment='订单类型：regular=常规订单, custom=定制订单')
    country = db.Column(db.String(100), comment='国家名称（仅定制订单使用）')
    status = db.Column(db.String(20), default='pending', comment='状态：pending=待审核, approved=已确认, rejected=已拒绝')
    is_validated = db.Column(db.Boolean, default=False, comment='是否已验证产品存在')
    validation_error = db.Column(db.String(500), comment='验证错误信息')
    stock_check_passed = db.Column(db.Boolean, default=False, comment='库存检查是否通过')
    stock_check_message = db.Column(db.String(500), comment='库存检查信息')
    created_at = db.Column(db.DateTime, default=datetime.now, comment='创建时间')
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now, comment='更新时间')

    product = db.relationship('Product', backref=db.backref('staging_stockouts', lazy=True))

    __table_args__ = (
        db.Index('idx_staging_stockout_session', 'session_id'),
        db.Index('idx_staging_stockout_status', 'status'),
        db.Index('idx_staging_stockout_created', 'created_at'),
    )

    def __repr__(self):
        return f'<StagingStockOut {self.id} - {self.customer} - {self.product_name}>'

    def to_dict(self):
        """转换为字典"""
        return {
            'id': self.id,
            'customer': self.customer or '',
            'stockout_date': self.stockout_date.strftime('%Y-%m-%d') if self.stockout_date else '',
            'product_name': self.product_name,
            'product_barcode': self.product_barcode or '',
            'product_id': self.product_id,
            'quantity': self.quantity,
            'note': self.note or '',
            'order_type': self.order_type or 'regular',
            'country': self.country or '',
            'status': self.status,
            'is_validated': self.is_validated,
            'validation_error': self.validation_error or '',
            'stock_check_passed': self.stock_check_passed,
            'stock_check_message': self.stock_check_message or '',
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S') if self.created_at else ''
        }
