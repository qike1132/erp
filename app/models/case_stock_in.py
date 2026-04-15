"""
皮套入库模型
"""
from datetime import datetime
from app import db


class CaseStockIn(db.Model):
    """皮套入库模型"""
    __tablename__ = 'case_stock_in'
    
    id = db.Column(db.Integer, primary_key=True)
    stockin_no = db.Column(db.String(20), unique=True, nullable=False, comment='入库编号')
    stockin_date = db.Column(db.DateTime, default=datetime.now, index=True, comment='入库时间')
    customer = db.Column(db.String(100), nullable=False, index=True, comment='客户名称')
    case_id = db.Column(db.Integer, db.ForeignKey('case.id'), nullable=False, index=True, comment='皮套ID')
    quantity = db.Column(db.Integer, nullable=False, comment='入库数量')
    note = db.Column(db.Text, comment='备注')
    
    case = db.relationship('Case', backref=db.backref('stockins', lazy=True))
    
    __table_args__ = (
        db.Index('idx_case_stockin_customer_case', 'customer', 'case_id'),
        db.Index('idx_case_stockin_case_date', 'case_id', 'stockin_date'),
        db.Index('idx_case_stockin_customer_date', 'customer', 'stockin_date'),
    )

    def __repr__(self):
        return f'<CaseStockIn {self.stockin_no}>'
