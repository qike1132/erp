"""
客户接入日志模型
用于监控客户在各模块的使用情况
"""
from datetime import datetime
from app import db


class CustomerAccessLog(db.Model):
    """客户接入日志模型"""
    __tablename__ = 'customer_access_log'
    
    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id'), nullable=True, comment='客户ID')
    customer_name = db.Column(db.String(100), nullable=False, comment='客户名称')
    module = db.Column(db.String(50), nullable=False, comment='模块名称')
    action = db.Column(db.String(50), nullable=False, comment='操作类型')
    related_id = db.Column(db.Integer, nullable=True, comment='关联记录ID')
    related_no = db.Column(db.String(50), nullable=True, comment='关联单号')
    quantity = db.Column(db.Integer, default=0, comment='数量')
    status = db.Column(db.String(20), default='success', comment='状态：success/failed')
    error_message = db.Column(db.Text, nullable=True, comment='错误信息')
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True, comment='操作用户ID')
    access_time = db.Column(db.DateTime, default=datetime.now, comment='接入时间')
    ip_address = db.Column(db.String(50), nullable=True, comment='IP地址')
    
    customer = db.relationship('Customer', backref=db.backref('access_logs', lazy='dynamic'))
    user = db.relationship('User', backref=db.backref('customer_access_logs', lazy='dynamic'))
    
    __table_args__ = (
        db.Index('idx_customer_access_name_time', 'customer_name', 'access_time'),
        db.Index('idx_customer_access_module_time', 'module', 'access_time'),
    )
    
    def __repr__(self):
        return f'<CustomerAccessLog {self.customer_name} - {self.module} - {self.action}>'
    
    def to_dict(self):
        """转换为字典"""
        return {
            'id': self.id,
            'customer_id': self.customer_id,
            'customer_name': self.customer_name,
            'module': self.module,
            'action': self.action,
            'related_id': self.related_id,
            'related_no': self.related_no,
            'quantity': self.quantity,
            'status': self.status,
            'error_message': self.error_message,
            'user_id': self.user_id,
            'access_time': self.access_time.isoformat() if self.access_time else None,
            'ip_address': self.ip_address
        }
    
    @staticmethod
    def log_access(customer_name, module, action, related_id=None, related_no=None, 
                   quantity=0, status='success', error_message=None, user_id=None, ip_address=None):
        """记录客户接入日志"""
        from app.models import Customer
        
        customer = Customer.query.filter_by(name=customer_name).first()
        customer_id = customer.id if customer else None
        
        log = CustomerAccessLog(
            customer_id=customer_id,
            customer_name=customer_name,
            module=module,
            action=action,
            related_id=related_id,
            related_no=related_no,
            quantity=quantity,
            status=status,
            error_message=error_message,
            user_id=user_id,
            ip_address=ip_address
        )
        db.session.add(log)
        db.session.commit()
        return log
    
    @staticmethod
    def get_customer_stats(customer_name, days=30):
        """获取客户统计信息"""
        from datetime import timedelta
        start_date = datetime.now() - timedelta(days=days)
        
        logs = CustomerAccessLog.query.filter(
            CustomerAccessLog.customer_name == customer_name,
            CustomerAccessLog.access_time >= start_date
        ).all()
        
        stats = {
            'total_access': len(logs),
            'success_count': sum(1 for l in logs if l.status == 'success'),
            'failed_count': sum(1 for l in logs if l.status == 'failed'),
            'total_quantity': sum(l.quantity for l in logs if l.status == 'success'),
            'modules': {},
            'recent_logs': [l.to_dict() for l in logs[:10]]
        }
        
        for log in logs:
            if log.module not in stats['modules']:
                stats['modules'][log.module] = {'count': 0, 'quantity': 0}
            stats['modules'][log.module]['count'] += 1
            stats['modules'][log.module]['quantity'] += log.quantity
        
        return stats
    
    @staticmethod
    def get_module_stats(module, days=30):
        """获取模块统计信息"""
        from datetime import timedelta
        start_date = datetime.now() - timedelta(days=days)
        
        logs = CustomerAccessLog.query.filter(
            CustomerAccessLog.module == module,
            CustomerAccessLog.access_time >= start_date
        ).all()
        
        stats = {
            'total_access': len(logs),
            'success_count': sum(1 for l in logs if l.status == 'success'),
            'failed_count': sum(1 for l in logs if l.status == 'failed'),
            'total_quantity': sum(l.quantity for l in logs if l.status == 'success'),
            'customers': {}
        }
        
        for log in logs:
            if log.customer_name not in stats['customers']:
                stats['customers'][log.customer_name] = {'count': 0, 'quantity': 0}
            stats['customers'][log.customer_name]['count'] += 1
            stats['customers'][log.customer_name]['quantity'] += log.quantity
        
        return stats
