"""
出货模型
"""
from datetime import datetime
from app import db


class StockOut(db.Model):
    """出货模型"""
    __tablename__ = 'stock_out'
    
    id = db.Column(db.Integer, primary_key=True)
    stockout_no = db.Column(db.String(20), unique=True, nullable=False, comment='出货编号')
    stockout_date = db.Column(db.DateTime, default=datetime.now, comment='出货时间')
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False, comment='产品ID')
    quantity = db.Column(db.Integer, nullable=False, comment='出货数量')
    customer = db.Column(db.String(100), nullable=True, comment='客户名称')
    order_id = db.Column(db.Integer, db.ForeignKey('order.id', ondelete='CASCADE'), nullable=True, comment='关联订单ID')
    stockin_id = db.Column(db.Integer, db.ForeignKey('stock_in.id', ondelete='SET NULL'), comment='关联备货ID')
    note = db.Column(db.Text, comment='备注')
    product = db.relationship('Product', backref=db.backref('stockouts', lazy=True))
    order = db.relationship('Order', backref=db.backref('order_stockouts', lazy=True, passive_deletes=True))
    stockin = db.relationship('StockIn', backref=db.backref('stockin_stockouts', lazy=True))
    
    __table_args__ = (
        db.Index('idx_stockout_stockin', 'stockin_id'),
        db.Index('idx_stockout_order', 'order_id'),
        db.Index('idx_stockout_product_date', 'product_id', 'stockout_date'),
        db.Index('idx_stockout_customer_date', 'customer', 'stockout_date'),
        db.Index('idx_stockout_product_customer_type', 'product_id', 'customer', 'stockin_id'),
        db.Index('idx_stockout_order_type', 'order_id', 'stockin_id'),
    )

    def __repr__(self):
        return f'<StockOut {self.stockout_no}>'
