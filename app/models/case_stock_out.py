"""
皮套出库模型
"""
from datetime import datetime
from app import db


class CaseStockOut(db.Model):
    """皮套出库模型"""
    __tablename__ = 'case_stock_out'
    
    id = db.Column(db.Integer, primary_key=True)
    stockout_no = db.Column(db.String(20), unique=True, nullable=False, comment='出库编号')
    stockout_date = db.Column(db.DateTime, default=datetime.now, index=True, comment='出库时间')
    case_id = db.Column(db.Integer, db.ForeignKey('case.id'), nullable=False, index=True, comment='皮套ID')
    quantity = db.Column(db.Integer, nullable=False, comment='出库数量')
    customer = db.Column(db.String(100), nullable=True, index=True, comment='客户名称')
    note = db.Column(db.Text, comment='备注')
    
    case = db.relationship('Case', backref=db.backref('stockouts', lazy=True))
    
    __table_args__ = (
        db.Index('idx_case_stockout_case_date', 'case_id', 'stockout_date'),
        db.Index('idx_case_stockout_customer_date', 'customer', 'stockout_date'),
    )

    def __repr__(self):
        return f'<CaseStockOut {self.stockout_no}>'
