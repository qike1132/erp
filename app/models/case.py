"""
皮套模型
"""
from datetime import datetime
from app import db


class Case(db.Model):
    """皮套模型"""
    __tablename__ = 'case'
    
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=True, index=True, comment='关联的产品ID')
    name = db.Column(db.String(100), nullable=False, index=True, comment='皮套名称(独立或冗余)')
    barcode = db.Column(db.String(50), index=True, comment='69码/皮套条码(独立或冗余)')
    image = db.Column(db.String(200), comment='皮套图片路径')
    initial_stock = db.Column(db.Integer, default=0, comment='初始库存')
    current_stock = db.Column(db.Integer, default=0, comment='当前库存')
    version = db.Column(db.Integer, default=0, nullable=False, server_default='0', comment='乐观锁版本号')
    create_time = db.Column(db.DateTime, default=datetime.now, index=True, comment='创建时间')
    
    product = db.relationship('Product', backref=db.backref('cases', lazy=True))
    
    __table_args__ = (
        db.Index('idx_case_product', 'product_id'),
        db.Index('idx_case_barcode', 'barcode'),
    )

    @property
    def sync_name(self):
        """实时同步产品名称"""
        if self.product_id and self.product:
            return self.product.name
        return self.name

    @property
    def sync_barcode(self):
        """实时同步产品条码"""
        if self.product_id and self.product:
            return self.product.barcode
        return self.barcode

    def __repr__(self):
        return f'<Case {self.sync_name}>'
