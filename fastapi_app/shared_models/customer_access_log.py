"""
客户接入日志模型 - 纯 SQLAlchemy 2.0 声明式

映射到与 Flask-SQLAlchemy CustomerAccessLog 相同的 'customer_access_log' 表。
"""
from sqlalchemy import String, Integer, Text, DateTime, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from datetime import datetime

from fastapi_app.shared_models import Base


class CustomerAccessLog(Base):
    """客户接入日志"""
    __tablename__ = 'customer_access_log'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    customer_id: Mapped[int | None] = mapped_column(Integer, ForeignKey('customer.id'), comment='客户ID')
    customer_name: Mapped[str] = mapped_column(String(100), nullable=False, comment='客户名称')
    module: Mapped[str] = mapped_column(String(50), nullable=False, comment='模块名称')
    action: Mapped[str] = mapped_column(String(50), nullable=False, comment='操作类型')
    related_id: Mapped[int | None] = mapped_column(Integer, comment='关联记录ID')
    related_no: Mapped[str | None] = mapped_column(String(50), comment='关联单号')
    quantity: Mapped[int] = mapped_column(Integer, default=0, comment='数量')
    status: Mapped[str] = mapped_column(String(20), default='success', comment='状态')
    error_message: Mapped[str | None] = mapped_column(Text, comment='错误信息')
    user_id: Mapped[int | None] = mapped_column(Integer, ForeignKey('user.id'), comment='操作用户ID')
    access_time: Mapped[datetime | None] = mapped_column(DateTime, default=datetime.now, comment='接入时间')
    ip_address: Mapped[str | None] = mapped_column(String(50), comment='IP地址')

    customer = relationship('Customer', backref='access_logs')
    user = relationship('User', backref='customer_access_logs')

    __table_args__ = (
        Index('idx_customer_access_name_time', 'customer_name', 'access_time'),
        Index('idx_customer_access_module_time', 'module', 'access_time'),
    )

    def to_dict(self):
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
            'ip_address': self.ip_address,
        }

    @staticmethod
    def log_access(db_session, customer_name, module, action, related_id=None,
                   related_no=None, quantity=0, status='success', error_message=None,
                   user_id=None, ip_address=None):
        """记录客户接入日志"""
        from fastapi_app.shared_models import Customer
        from sqlalchemy import select

        result = db_session.execute(
            select(Customer).where(Customer.name == customer_name)
        )
        customer = result.scalar_one_or_none()
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
        db_session.add(log)
        db_session.commit()
        return log

    @staticmethod
    def get_customer_stats(db_session, customer_name, days=30):
        """获取客户统计信息"""
        from datetime import timedelta
        from sqlalchemy import select

        start_date = datetime.now() - timedelta(days=days)
        result = db_session.execute(
            select(CustomerAccessLog).where(
                CustomerAccessLog.customer_name == customer_name,
                CustomerAccessLog.access_time >= start_date
            )
        )
        logs = list(result.scalars().all())

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
    def get_module_stats(db_session, module, days=30):
        """获取模块统计信息"""
        from datetime import timedelta
        from sqlalchemy import select

        start_date = datetime.now() - timedelta(days=days)
        result = db_session.execute(
            select(CustomerAccessLog).where(
                CustomerAccessLog.module == module,
                CustomerAccessLog.access_time >= start_date
            )
        )
        logs = list(result.scalars().all())

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
