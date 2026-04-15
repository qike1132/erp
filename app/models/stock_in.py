"""
备货模型
"""
from datetime import datetime
from app import db


class StockIn(db.Model):
    """备货模型"""
    __tablename__ = 'stock_in'
    
    id = db.Column(db.Integer, primary_key=True)
    stockin_no = db.Column(db.String(20), unique=True, nullable=False, comment='备货编号')
    stockin_date = db.Column(db.DateTime, default=datetime.now, index=True, comment='备货时间')
    customer = db.Column(db.String(100), nullable=False, index=True, comment='客户名称')
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False, index=True, comment='产品ID')
    quantity = db.Column(db.Integer, nullable=False, comment='备货数量')
    note = db.Column(db.Text, comment='备注')
    product = db.relationship('Product', backref=db.backref('stockins', lazy=True))
    
    # 复合索引 - 用于常见查询场景
    __table_args__ = (
        # 按客户和产品查询（用于订单抵扣逻辑，最关键的索引）
        db.Index('idx_stockin_customer_product', 'customer', 'product_id'),
        # 按产品和日期查询（用于按产品查看备货历史）
        db.Index('idx_stockin_product_date', 'product_id', 'stockin_date'),
        # 按客户和日期查询（用于按客户查看备货历史）
        db.Index('idx_stockin_customer_date', 'customer', 'stockin_date'),
        # 用于抵扣逻辑：按客户、产品、日期排序
        db.Index('idx_stockin_customer_product_date', 'customer', 'product_id', 'stockin_date'),
    )

    def __repr__(self):
        return f'<StockIn {self.stockin_no}>'
