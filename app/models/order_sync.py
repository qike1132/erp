"""
订单同步与状态流转模型
包含同步记录、状态流转日志、重试队列
"""
from datetime import datetime, timedelta
from app import db
import json


class OrderSyncRecord(db.Model):
    """订单同步记录"""
    __tablename__ = 'order_sync_record'

    id = db.Column(db.Integer, primary_key=True)
    source_order_id = db.Column(db.Integer, nullable=False, index=True, comment='来源订单ID')
    order_no = db.Column(db.String(20), nullable=False, comment='订单编号')
    sync_type = db.Column(db.String(20), default='create', comment='同步类型: create/update/delete')
    sync_status = db.Column(db.String(20), default='pending', index=True, comment='同步状态: pending/success/failed/retrying')
    sync_time = db.Column(db.DateTime, default=datetime.now, index=True, comment='同步时间')
    retry_count = db.Column(db.Integer, default=0, comment='重试次数')
    max_retries = db.Column(db.Integer, default=3, comment='最大重试次数')
    next_retry_time = db.Column(db.DateTime, comment='下次重试时间')
    error_message = db.Column(db.Text, comment='错误信息')
    sync_data = db.Column(db.Text, comment='同步数据JSON快照')
    operator_id = db.Column(db.Integer, nullable=True, comment='操作人ID')
    operator_name = db.Column(db.String(100), comment='操作人姓名')

    __table_args__ = (
        db.Index('idx_sync_status_time', 'sync_status', 'sync_time'),
        db.Index('idx_sync_order', 'source_order_id'),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'source_order_id': self.source_order_id,
            'order_no': self.order_no,
            'sync_type': self.sync_type,
            'sync_status': self.sync_status,
            'sync_time': self.sync_time.strftime('%Y-%m-%d %H:%M:%S') if self.sync_time else None,
            'retry_count': self.retry_count,
            'max_retries': self.max_retries,
            'next_retry_time': self.next_retry_time.strftime('%Y-%m-%d %H:%M:%S') if self.next_retry_time else None,
            'error_message': self.error_message,
            'operator_name': self.operator_name,
        }

    def mark_success(self):
        """标记同步成功"""
        self.sync_status = 'success'
        self.sync_time = datetime.now()

    def mark_failed(self, error_msg):
        """标记同步失败"""
        self.sync_status = 'failed' if self.retry_count >= self.max_retries else 'retrying'
        self.error_message = error_msg
        self.retry_count += 1
        if self.retry_count < self.max_retries:
            delay_seconds = min(60, 5 * (2 ** (self.retry_count - 1)))
            self.next_retry_time = datetime.now() + timedelta(seconds=delay_seconds)
            self.sync_status = 'retrying'

    def can_retry(self):
        """检查是否可以重试"""
        if self.sync_status not in ['pending', 'retrying']:
            return False
        if self.retry_count >= self.max_retries:
            return False
        if self.next_retry_time and datetime.now() < self.next_retry_time:
            return False
        return True


class OrderStatusLog(db.Model):
    """订单状态流转日志"""
    __tablename__ = 'order_status_log'

    id = db.Column(db.Integer, primary_key=True)
    target_type = db.Column(db.String(50), nullable=False, index=True, comment='目标类型: unprocessed_order/purchase_order')
    target_id = db.Column(db.Integer, nullable=False, index=True, comment='目标ID')
    order_no = db.Column(db.String(20), comment='订单编号')
    from_status = db.Column(db.String(50), comment='变更前状态')
    to_status = db.Column(db.String(50), nullable=False, comment='变更后状态')
    action = db.Column(db.String(50), nullable=False, comment='操作类型: start_process/complete/ignore/reopen')
    action_label = db.Column(db.String(100), comment='操作标签(中文)')
    operator_id = db.Column(db.Integer, db.ForeignKey('user.id'), comment='操作人ID')
    operator_name = db.Column(db.String(100), comment='操作人姓名')
    action_time = db.Column(db.DateTime, default=datetime.now, index=True, comment='操作时间')
    action_result = db.Column(db.String(20), default='success', comment='操作结果: success/failed')
    remark = db.Column(db.Text, comment='备注说明')
    related_data = db.Column(db.Text, comment='关联数据JSON')

    __table_args__ = (
        db.Index('idx_status_target', 'target_type', 'target_id'),
        db.Index('idx_status_time', 'action_time'),
        db.Index('idx_status_order', 'order_no'),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'target_type': self.target_type,
            'target_id': self.target_id,
            'order_no': self.order_no,
            'from_status': self.from_status,
            'to_status': self.to_status,
            'action': self.action,
            'action_label': self.action_label,
            'operator_id': self.operator_id,
            'operator_name': self.operator_name,
            'action_time': self.action_time.strftime('%Y-%m-%d %H:%M:%S') if self.action_time else None,
            'action_result': self.action_result,
            'remark': self.remark,
            'related_data': json.loads(self.related_data) if self.related_data else None,
        }


class SyncRetryQueue(db.Model):
    """同步失败重试队列"""
    __tablename__ = 'sync_retry_queue'

    id = db.Column(db.Integer, primary_key=True)
    source_order_id = db.Column(db.Integer, nullable=False, index=True, comment='来源订单ID')
    order_no = db.Column(db.String(20), nullable=False, comment='订单编号')
    sync_type = db.Column(db.String(20), default='create', comment='同步类型')
    sync_data = db.Column(db.Text, nullable=False, comment='同步数据JSON')
    retry_count = db.Column(db.Integer, default=0, comment='已重试次数')
    max_retries = db.Column(db.Integer, default=5, comment='最大重试次数')
    status = db.Column(db.String(20), default='pending', index=True, comment='状态: pending/processing/success/failed/abandoned')
    next_retry_time = db.Column(db.DateTime, index=True, comment='下次重试时间')
    last_retry_time = db.Column(db.DateTime, comment='上次重试时间')
    last_error = db.Column(db.Text, comment='最后错误信息')
    created_at = db.Column(db.DateTime, default=datetime.now, comment='创建时间')
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now, comment='更新时间')
    priority = db.Column(db.Integer, default=0, comment='优先级(数字越大优先级越高)')

    __table_args__ = (
        db.Index('idx_retry_status_time', 'status', 'next_retry_time'),
        db.Index('idx_retry_priority', 'priority', 'next_retry_time'),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'source_order_id': self.source_order_id,
            'order_no': self.order_no,
            'sync_type': self.sync_type,
            'retry_count': self.retry_count,
            'max_retries': self.max_retries,
            'status': self.status,
            'next_retry_time': self.next_retry_time.strftime('%Y-%m-%d %H:%M:%S') if self.next_retry_time else None,
            'last_retry_time': self.last_retry_time.strftime('%Y-%m-%d %H:%M:%S') if self.last_retry_time else None,
            'last_error': self.last_error,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S') if self.created_at else None,
            'priority': self.priority,
        }

    def calculate_next_retry_time(self):
        """计算下次重试时间（指数退避）"""
        base_delay = 10
        max_delay = 3600
        delay = min(max_delay, base_delay * (2 ** self.retry_count))
        return datetime.now() + timedelta(seconds=delay)

    def increment_retry(self, error_msg):
        """增加重试次数"""
        self.retry_count += 1
        self.last_retry_time = datetime.now()
        self.last_error = error_msg
        if self.retry_count >= self.max_retries:
            self.status = 'failed'
        else:
            self.next_retry_time = self.calculate_next_retry_time()
            self.status = 'pending'

    def mark_processing(self):
        """标记为处理中"""
        self.status = 'processing'

    def mark_success(self):
        """标记为成功"""
        self.status = 'success'
        self.last_retry_time = datetime.now()

    def mark_abandoned(self, reason):
        """标记为放弃"""
        self.status = 'abandoned'
        self.last_error = reason


class OrderSyncConfig(db.Model):
    """订单同步配置"""
    __tablename__ = 'order_sync_config'

    id = db.Column(db.Integer, primary_key=True)
    config_key = db.Column(db.String(100), unique=True, nullable=False, comment='配置键')
    config_value = db.Column(db.Text, comment='配置值')
    description = db.Column(db.String(255), comment='配置描述')
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now, comment='更新时间')
    updated_by_id = db.Column(db.Integer, db.ForeignKey('user.id'), comment='更新人ID')

    @classmethod
    def get_value(cls, key, default=None):
        """获取配置值"""
        config = cls.query.filter_by(config_key=key).first()
        return config.config_value if config else default

    @classmethod
    def set_value(cls, key, value, user_id=None, description=None):
        """设置配置值"""
        config = cls.query.filter_by(config_key=key).first()
        if config:
            config.config_value = value
            config.updated_by_id = user_id
            if description:
                config.description = description
        else:
            config = cls(
                config_key=key,
                config_value=value,
                description=description,
                updated_by_id=user_id
            )
            db.session.add(config)
        db.session.commit()
        return config


ORDER_STATUS_FLOW = {
    'unprocessed': {
        'next': ['processing'],
        'label': '未处理',
        'color': '#6b7280',
        'actions': {
            'start_process': {
                'to': 'processing',
                'label': '开始处理',
                'require_remark': False
            }
        }
    },
    'processing': {
        'next': ['processed', 'ignored'],
        'label': '处理中',
        'color': '#3b82f6',
        'actions': {
            'complete': {
                'to': 'processed',
                'label': '完成处理',
                'require_remark': False
            },
            'ignore': {
                'to': 'ignored',
                'label': '忽略订单',
                'require_remark': True
            }
        }
    },
    'processed': {
        'next': ['processing'],
        'label': '已完成',
        'color': '#10b981',
        'actions': {
            'reopen': {
                'to': 'processing',
                'label': '重新处理',
                'require_remark': True
            }
        }
    },
    'ignored': {
        'next': ['processing'],
        'label': '已忽略',
        'color': '#ef4444',
        'actions': {
            'reopen': {
                'to': 'processing',
                'label': '重新处理',
                'require_remark': True
            }
        }
    }
}


def validate_status_transition(from_status, to_status):
    """验证状态转换是否合法"""
    if from_status not in ORDER_STATUS_FLOW:
        return False, f"无效的源状态: {from_status}"
    
    allowed_next = ORDER_STATUS_FLOW[from_status].get('next', [])
    if to_status not in allowed_next:
        return False, f"不允许从 {ORDER_STATUS_FLOW[from_status]['label']} 转换到 {ORDER_STATUS_FLOW.get(to_status, {}).get('label', to_status)}"
    
    return True, None


def get_action_for_transition(from_status, to_status):
    """获取状态转换对应的操作"""
    if from_status not in ORDER_STATUS_FLOW:
        return None
    
    actions = ORDER_STATUS_FLOW[from_status].get('actions', {})
    for action_name, action_info in actions.items():
        if action_info['to'] == to_status:
            return action_name, action_info
    
    return None
