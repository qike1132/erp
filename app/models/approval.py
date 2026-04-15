"""
审批流程模型
"""
from datetime import datetime
from app import db


class ApprovalRequest(db.Model):
    """审批请求模型"""
    __tablename__ = 'approval_request'
    
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('order.id'), nullable=False, comment='关联订单ID')
    requester_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, comment='申请人ID')
    operation_type = db.Column(db.String(20), nullable=False, comment='操作类型：edit/delete')
    operation_data = db.Column(db.Text, comment='操作数据JSON（编辑时保存修改内容）')
    status = db.Column(db.String(20), default='pending', index=True, comment='状态：pending/approved/rejected/cancelled')
    request_time = db.Column(db.DateTime, default=datetime.now, index=True, comment='申请时间')
    approver_id = db.Column(db.Integer, db.ForeignKey('user.id'), comment='审批人ID')
    approval_time = db.Column(db.DateTime, comment='审批时间')
    rejection_reason = db.Column(db.Text, comment='拒绝原因')
    lock_time = db.Column(db.DateTime, comment='锁定时间')
    
    order = db.relationship('Order', backref=db.backref('approval_requests', lazy=True))
    requester = db.relationship('User', foreign_keys=[requester_id], backref=db.backref('approval_requests_made', lazy=True))
    approver = db.relationship('User', foreign_keys=[approver_id], backref=db.backref('approval_requests_handled', lazy=True))
    
    __table_args__ = (
        db.Index('idx_approval_status_time', 'status', 'request_time'),
        db.Index('idx_approval_request_order', 'order_id'),
        db.Index('idx_approval_request_requester', 'requester_id'),
    )

    def __repr__(self):
        return f'<ApprovalRequest {self.id} - Order {self.order_id}>'
    
    @property
    def status_display(self):
        """状态显示文本"""
        status_map = {
            'pending': '待审批',
            'approved': '已同意',
            'rejected': '已拒绝',
            'cancelled': '已取消'
        }
        return status_map.get(self.status, self.status)
    
    @property
    def operation_type_display(self):
        """操作类型显示文本"""
        operation_map = {
            'edit': '编辑',
            'delete': '删除'
        }
        return operation_map.get(self.operation_type, self.operation_type)
    
    def to_dict(self):
        """转换为字典"""
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
            'lock_time': self.lock_time.strftime('%Y-%m-%d %H:%M:%S') if self.lock_time else None
        }


class ApprovalLog(db.Model):
    """审批日志模型"""
    __tablename__ = 'approval_log'
    
    id = db.Column(db.Integer, primary_key=True)
    approval_request_id = db.Column(db.Integer, db.ForeignKey('approval_request.id'), nullable=False, comment='审批请求ID')
    action = db.Column(db.String(50), nullable=False, comment='操作动作：create/approve/reject/cancel/execute')
    actor_id = db.Column(db.Integer, db.ForeignKey('user.id'), comment='操作人ID')
    actor_name = db.Column(db.String(50), comment='操作人名称')
    action_time = db.Column(db.DateTime, default=datetime.now, index=True, comment='操作时间')
    details = db.Column(db.Text, comment='操作详情JSON')
    
    approval_request = db.relationship('ApprovalRequest', backref=db.backref('logs', lazy=True, order_by='ApprovalLog.action_time.desc()'))
    actor = db.relationship('User', backref=db.backref('approval_logs', lazy=True))
    
    __table_args__ = (
        db.Index('idx_approval_log_request', 'approval_request_id'),
    )
    
    def __repr__(self):
        return f'<ApprovalLog {self.id} - {self.action}>'
    
    @property
    def action_display(self):
        """操作动作显示文本"""
        action_map = {
            'create': '创建审批请求',
            'approve': '同意审批',
            'reject': '拒绝审批',
            'cancel': '取消审批',
            'execute': '执行操作'
        }
        return action_map.get(self.action, self.action)
    
    def to_dict(self):
        """转换为字典"""
        return {
            'id': self.id,
            'approval_request_id': self.approval_request_id,
            'action': self.action,
            'action_display': self.action_display,
            'actor_id': self.actor_id,
            'actor_name': self.actor_name or (self.actor.username if self.actor else None),
            'action_time': self.action_time.strftime('%Y-%m-%d %H:%M:%S') if self.action_time else None,
            'details': self.details
        }
