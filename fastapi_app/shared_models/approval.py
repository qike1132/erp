"""
审批流程模型 - 纯 SQLAlchemy 2.0 声明式

映射到与 Flask-SQLAlchemy ApprovalRequest / ApprovalLog 相同的表。
"""
from sqlalchemy import String, Integer, Text, DateTime, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from datetime import datetime

from fastapi_app.shared_models import Base


class ApprovalRequest(Base):
    """审批请求模型"""
    __tablename__ = 'approval_request'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(Integer, ForeignKey('order.id'), nullable=False, comment='关联订单ID')
    requester_id: Mapped[int] = mapped_column(Integer, ForeignKey('user.id'), nullable=False, comment='申请人ID')
    operation_type: Mapped[str] = mapped_column(String(20), nullable=False, comment='操作类型：edit/delete')
    operation_data: Mapped[str | None] = mapped_column(Text, comment='操作数据JSON')
    status: Mapped[str] = mapped_column(String(20), default='pending', index=True, comment='状态：pending/approved/rejected/cancelled')
    request_time: Mapped[datetime | None] = mapped_column(DateTime, default=datetime.now, index=True, comment='申请时间')
    approver_id: Mapped[int | None] = mapped_column(Integer, ForeignKey('user.id'), comment='审批人ID')
    approval_time: Mapped[datetime | None] = mapped_column(DateTime, comment='审批时间')
    rejection_reason: Mapped[str | None] = mapped_column(Text, comment='拒绝原因')
    lock_time: Mapped[datetime | None] = mapped_column(DateTime, comment='锁定时间')

    order: Mapped["Order"] = relationship('Order', backref='approval_requests')
    requester: Mapped["User"] = relationship('User', foreign_keys=[requester_id], backref='approval_requests_made')
    approver: Mapped["User | None"] = relationship('User', foreign_keys=[approver_id], backref='approval_requests_handled')

    __table_args__ = (
        Index('idx_approval_status_time', 'status', 'request_time'),
        Index('idx_approval_request_order', 'order_id'),
        Index('idx_approval_request_requester', 'requester_id'),
    )

    @property
    def operation_type_display(self) -> str:
        """操作类型的中文显示"""
        mapping = {'edit': '编辑', 'delete': '删除'}
        return mapping.get(self.operation_type, self.operation_type)

    @property
    def status_display(self) -> str:
        """状态的中文显示"""
        mapping = {'pending': '待审批', 'approved': '已同意', 'rejected': '已拒绝', 'cancelled': '已取消'}
        return mapping.get(self.status, self.status)

    def __repr__(self):
        return f'<ApprovalRequest {self.id} - Order {self.order_id}>'

    def to_dict(self):
        return {
            'id': self.id,
            'order_id': self.order_id,
            'order_no': self.order.order_no if self.order else None,
            'requester_id': self.requester_id,
            'requester_name': self.requester.username if self.requester else None,
            'operation_type': self.operation_type,
            'operation_type_display': self.operation_type_display,
            'operation_data': self.operation_data,
            'status': self.status,
            'status_display': self.status_display,
            'request_time': self.request_time.strftime('%Y-%m-%d %H:%M:%S') if self.request_time else None,
            'approver_id': self.approver_id,
            'approver_name': self.approver.username if self.approver else None,
            'approval_time': self.approval_time.strftime('%Y-%m-%d %H:%M:%S') if self.approval_time else None,
            'rejection_reason': self.rejection_reason,
            'lock_time': self.lock_time.strftime('%Y-%m-%d %H:%M:%S') if self.lock_time else None,
        }


class ApprovalLog(Base):
    """审批日志模型"""
    __tablename__ = 'approval_log'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    approval_request_id: Mapped[int] = mapped_column(Integer, ForeignKey('approval_request.id'), nullable=False, comment='审批请求ID')
    action: Mapped[str] = mapped_column(String(50), nullable=False, comment='操作动作')
    actor_id: Mapped[int | None] = mapped_column(Integer, ForeignKey('user.id'), comment='操作人ID')
    actor_name: Mapped[str | None] = mapped_column(String(50), comment='操作人名称')
    action_time: Mapped[datetime | None] = mapped_column(DateTime, default=datetime.now, index=True, comment='操作时间')
    details: Mapped[str | None] = mapped_column(Text, comment='操作详情JSON')

    approval_request: Mapped["ApprovalRequest"] = relationship('ApprovalRequest', backref='logs')
    actor: Mapped["User | None"] = relationship('User', backref='approval_logs')

    __table_args__ = (
        Index('idx_approval_log_request', 'approval_request_id'),
    )

    @property
    def action_display(self) -> str:
        """操作动作的中文显示"""
        mapping = {'create': '创建审批请求', 'approve': '同意审批', 'reject': '拒绝审批', 'cancel': '取消审批', 'execute': '执行操作'}
        return mapping.get(self.action, self.action)

    def __repr__(self):
        return f'<ApprovalLog {self.id} - {self.action}>'

    def to_dict(self):
        return {
            'id': self.id,
            'approval_request_id': self.approval_request_id,
            'action': self.action,
            'action_display': self.action_display,
            'actor_id': self.actor_id,
            'actor_name': self.actor_name or (self.actor.username if self.actor else None),
            'action_time': self.action_time.strftime('%Y-%m-%d %H:%M:%S') if self.action_time else None,
            'details': self.details,
        }
