"""包装部生产记录模型"""
from datetime import datetime
from app import db


class PackagingRecord(db.Model):
    """包装部生产记录"""
    __tablename__ = 'packaging_record'

    id = db.Column(db.Integer, primary_key=True)
    customer = db.Column(db.String(100), nullable=False, comment='客户')
    product_name = db.Column(db.String(100), nullable=False, comment='产品名称')
    barcode = db.Column(db.String(50), nullable=False, comment='69码')
    quantity = db.Column(db.Integer, nullable=False, comment='数量')
    pack_date = db.Column(db.Date, nullable=False, comment='包装日期')
    remark = db.Column(db.Text, nullable=True, comment='备注')
    upload_batch = db.Column(db.String(64), nullable=True, comment='上传批次ID')
    create_time = db.Column(db.DateTime, default=datetime.now, comment='创建时间')
    created_by = db.Column(db.String(50), nullable=True, comment='创建人')

    __table_args__ = (
        db.Index('idx_packaging_date', 'pack_date'),
        db.Index('idx_packaging_customer_date', 'customer', 'pack_date'),
        db.Index('idx_packaging_barcode', 'barcode'),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'customer': self.customer,
            'product_name': self.product_name,
            'barcode': self.barcode,
            'quantity': self.quantity,
            'pack_date': self.pack_date.isoformat() if self.pack_date else '',
            'remark': self.remark or '',
            'upload_batch': self.upload_batch or '',
            'create_time': self.create_time.strftime('%Y-%m-%d %H:%M:%S') if self.create_time else '',
            'created_by': self.created_by or '',
        }
