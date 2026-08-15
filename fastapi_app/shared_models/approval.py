"""
审批流程模型 - 纯 SQLAlchemy 2.0 声明式
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, ClassVar

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, backref, mapped_column, relationship

from fastapi_app.shared_models import Base

if TYPE_CHECKING:
    from fastapi_app.shared_models.order import Order
    from fastapi_app.shared_models.user import User

_DATETIME_FMT = '%Y-%m-%d %H:%M:%S'


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)  # naive UTC: DB列类型为 TIMESTAMP WITHOUT TIME ZONE


def _fmt_dt(value: datetime | None) -> str | None:
    return value.strftime(_DATETIME_FMT) if value else None


class ApprovalRequest(Base):
    __tablename__ = 'approval_request'

    OPERATION_EDIT = 'edit'
    OPERATION_DELETE = 'delete'
    STATUS_PENDING = 'pending'
    STATUS_APPROVED = 'approved'
    STATUS_REJECTED = 'rejected'
    STATUS_CANCELLED = 'cancelled'

    _OPERATION_DISPLAY: ClassVar[dict[str, str]] = {
        OPERATION_EDIT: '编辑',
        OPERATION_DELETE: '删除',
    }
    _STATUS_DISPLAY: ClassVar[dict[str, str]] = {
        STATUS_PENDING: '待审批',
        STATUS_APPROVED: '已同意',
        STATUS_REJECTED: '已拒绝',
        STATUS_CANCELLED: '已取消',
    }

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(Integer, ForeignKey('order.id', ondelete='CASCADE'), nullable=False, comment='关联订单ID')
    requester_id: Mapped[int] = mapped_column(Integer, ForeignKey('user.id'), nullable=False, comment='申请人ID')
    operation_type: Mapped[str] = mapped_column(String(20), nullable=False, comment='操作类型：edit/delete')
    operation_data: Mapped[str | None] = mapped_column(Text, comment='操作数据JSON')
    status: Mapped[str] = mapped_column(String(20), default=STATUS_PENDING, index=True, comment='状态：pending/approved/rejected/cancelled')
    request_time: Mapped[datetime | None] = mapped_column(DateTime, default=_utcnow, index=True, comment='申请时间')
    approver_id: Mapped[int | None] = mapped_column(Integer, ForeignKey('user.id'), comment='审批人ID')
    approval_time: Mapped[datetime | None] = mapped_column(DateTime, comment='审批时间')
    rejection_reason: Mapped[str | None] = mapped_column(Text, comment='拒绝原因')
    lock_time: Mapped[datetime | None] = mapped_column(DateTime, comment='锁定时间')
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now, comment='更新时间')

    order: Mapped["Order"] = relationship('Order', backref=backref('approval_requests', passive_deletes=True))
    requester: Mapped["User"] = relationship('User', foreign_keys=[requester_id], backref='approval_requests_made')
    approver: Mapped["User | None"] = relationship('User', foreign_keys=[approver_id], backref='approval_requests_handled')

    __table_args__ = (
        Index('idx_approval_status_time', 'status', 'request_time'),
        Index('idx_approval_request_order', 'order_id'),
        Index('idx_approval_request_requester', 'requester_id'),
        Index('idx_approval_approver', 'approver_id'),
    )

    @property
    def operation_type_display(self) -> str:
        return self._OPERATION_DISPLAY.get(self.operation_type, self.operation_type)

    @property
    def status_display(self) -> str:
        return self._STATUS_DISPLAY.get(self.status, self.status)

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
            'request_time': _fmt_dt(self.request_time),
            'approver_id': self.approver_id,
            'approver_name': self.approver.username if self.approver else None,
            'approval_time': _fmt_dt(self.approval_time),
            'rejection_reason': self.rejection_reason,
            'lock_time': _fmt_dt(self.lock_time),
        }


class ApprovalLog(Base):
    __tablename__ = 'approval_log'

    ACTION_CREATE = 'create'
    ACTION_APPROVE = 'approve'
    ACTION_REJECT = 'reject'
    ACTION_CANCEL = 'cancel'
    ACTION_EXECUTE = 'execute'

    _ACTION_DISPLAY: ClassVar[dict[str, str]] = {
        ACTION_CREATE: '创建审批请求',
        ACTION_APPROVE: '同意审批',
        ACTION_REJECT: '拒绝审批',
        ACTION_CANCEL: '取消审批',
        ACTION_EXECUTE: '执行操作',
    }

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    approval_request_id: Mapped[int] = mapped_column(Integer, ForeignKey('approval_request.id'), nullable=False, comment='审批请求ID')
    action: Mapped[str] = mapped_column(String(50), nullable=False, comment='操作动作')
    actor_id: Mapped[int | None] = mapped_column(Integer, ForeignKey('user.id'), comment='操作人ID')
    actor_name: Mapped[str | None] = mapped_column(String(50), comment='操作人名称')
    action_time: Mapped[datetime | None] = mapped_column(DateTime, default=_utcnow, index=True, comment='操作时间')
    details: Mapped[str | None] = mapped_column(Text, comment='操作详情JSON')
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now, comment='更新时间')

    approval_request: Mapped["ApprovalRequest"] = relationship('ApprovalRequest', backref='logs')
    actor: Mapped["User | None"] = relationship('User', backref='approval_logs')

    __table_args__ = (
        Index('idx_approval_log_request', 'approval_request_id'),
        Index('idx_approval_log_actor', 'actor_id'),
    )

    @property
    def action_display(self) -> str:
        return self._ACTION_DISPLAY.get(self.action, self.action)

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
            'action_time': _fmt_dt(self.action_time),
            'details': self.details,
        }
