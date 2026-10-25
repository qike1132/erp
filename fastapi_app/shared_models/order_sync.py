"""
订单同步与状态流转模型 - 纯 SQLAlchemy 2.0 声明式

映射到 'order_sync_record', 'sync_retry_queue', 'order_sync_config' 表。
"""
from datetime import UTC, datetime, timedelta
from typing import TypedDict

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from fastapi_app.core.business_time import fmt_business
from fastapi_app.shared_models import Base


class OrderSyncRecord(Base):
    """订单同步记录"""
    __tablename__ = 'order_sync_record'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_order_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True, comment='来源订单ID')
    order_no: Mapped[str] = mapped_column(String(20), nullable=False, comment='订单编号')
    sync_type: Mapped[str] = mapped_column(String(20), default='create', comment='同步类型')
    sync_status: Mapped[str] = mapped_column(String(20), default='pending', index=True, comment='同步状态')
    sync_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), index=True, comment='同步时间')
    retry_count: Mapped[int] = mapped_column(Integer, default=0, comment='重试次数')
    max_retries: Mapped[int] = mapped_column(Integer, default=3, comment='最大重试次数')
    next_retry_time: Mapped[datetime | None] = mapped_column(DateTime, comment='下次重试时间')
    error_message: Mapped[str | None] = mapped_column(Text, comment='错误信息')
    sync_data: Mapped[str | None] = mapped_column(Text, comment='同步数据JSON')
    operator_id: Mapped[int | None] = mapped_column(Integer, comment='操作人ID')
    operator_name: Mapped[str | None] = mapped_column(String(100), comment='操作人姓名')
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC), comment='更新时间')

    __table_args__ = (
        Index('idx_sync_status_time', 'sync_status', 'sync_time'),
        Index('idx_sync_order', 'source_order_id'),
    )

    def __repr__(self):
        return f'<OrderSyncRecord {self.id}>'

    def to_dict(self):
        return {
            'id': self.id,
            'source_order_id': self.source_order_id,
            'order_no': self.order_no,
            'sync_type': self.sync_type,
            'sync_status': self.sync_status,
            'sync_time': fmt_business(self.sync_time, '%Y-%m-%d %H:%M:%S') if self.sync_time else None,
            'retry_count': self.retry_count,
            'max_retries': self.max_retries,
            'next_retry_time': self.next_retry_time.strftime('%Y-%m-%d %H:%M:%S') if self.next_retry_time else None,
            'error_message': self.error_message,
            'operator_name': self.operator_name,
        }

    def mark_success(self):
        """标记同步成功"""
        self.sync_status = 'success'
        # B5-F4（2026-10-24 审计）：sync_time 是 timestamptz 列，裸 datetime.now()
        # 写 naive 本地时间会错位 8 小时（058 迁移修过的同型反模式）。
        self.sync_time = datetime.now(UTC)

    def mark_failed(self, error_msg: str):
        """标记同步失败"""
        self.sync_status = 'failed' if self.retry_count >= self.max_retries else 'retrying'
        self.error_message = error_msg
        self.retry_count += 1
        if self.retry_count < self.max_retries:
            delay_seconds = min(60, 5 * (2 ** (self.retry_count - 1)))
            self.next_retry_time = datetime.now() + timedelta(seconds=delay_seconds)
            self.sync_status = 'retrying'

    def can_retry(self) -> bool:
        """检查是否可以重试"""
        if self.sync_status not in ['pending', 'retrying']:
            return False
        if self.retry_count >= self.max_retries:
            return False
        return not (self.next_retry_time and datetime.now() < self.next_retry_time)


class SyncRetryQueue(Base):
    """同步失败重试队列"""
    __tablename__ = 'sync_retry_queue'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_order_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True, comment='来源订单ID')
    order_no: Mapped[str] = mapped_column(String(20), nullable=False, comment='订单编号')
    sync_type: Mapped[str] = mapped_column(String(20), default='create', comment='同步类型')
    sync_data: Mapped[str] = mapped_column(Text, nullable=False, comment='同步数据JSON')
    retry_count: Mapped[int] = mapped_column(Integer, default=0, comment='已重试次数')
    max_retries: Mapped[int] = mapped_column(Integer, default=5, comment='最大重试次数')
    status: Mapped[str] = mapped_column(String(20), default='pending', index=True, comment='状态')
    next_retry_time: Mapped[datetime | None] = mapped_column(DateTime, index=True, comment='下次重试时间')
    last_retry_time: Mapped[datetime | None] = mapped_column(DateTime, comment='上次重试时间')
    last_error: Mapped[str | None] = mapped_column(Text, comment='最后错误信息')
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), comment='创建时间')
    priority: Mapped[int] = mapped_column(Integer, default=0, comment='优先级')
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC), comment='更新时间')

    __table_args__ = (
        Index('idx_retry_status_time', 'status', 'next_retry_time'),
        Index('idx_retry_priority', 'priority', 'next_retry_time'),
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
            'created_at': fmt_business(self.created_at, '%Y-%m-%d %H:%M:%S') if self.created_at else None,
            'priority': self.priority,
        }

    def calculate_next_retry_time(self) -> datetime:
        """计算下次重试时间（指数退避）"""
        base_delay = 10
        max_delay = 3600
        delay = min(max_delay, base_delay * (2 ** self.retry_count))
        return datetime.now() + timedelta(seconds=delay)

    def increment_retry(self, error_msg: str):
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
        self.status = 'processing'

    def mark_success(self):
        self.status = 'success'
        self.last_retry_time = datetime.now()

    def mark_abandoned(self, reason: str):
        self.status = 'abandoned'
        self.last_error = reason


class OrderSyncConfig(Base):
    """订单同步配置"""
    __tablename__ = 'order_sync_config'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    config_key: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, comment='配置键')
    config_value: Mapped[str | None] = mapped_column(Text, comment='配置值')
    description: Mapped[str | None] = mapped_column(String(255), comment='配置描述')
    updated_by_id: Mapped[int | None] = mapped_column(Integer, ForeignKey('user.id'), comment='更新人ID')
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC), comment='更新时间')

    __table_args__ = (
        Index('idx_order_sync_config_updated_by', 'updated_by_id'),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'config_key': self.config_key,
            'config_value': self.config_value or '',
            'description': self.description or '',
            'updated_at': fmt_business(self.updated_at, '%Y-%m-%d %H:%M:%S') if self.updated_at else None,
            'updated_by_id': self.updated_by_id,
        }


# ==================== 状态流转定义 ====================

class StatusAction(TypedDict, total=False):
    """状态流转中可选动作的定义（'actions' 表项）。"""
    to: str
    label: str
    require_remark: bool


class StatusFlowEntry(TypedDict, total=False):
    """单个订单状态的定义（ORDER_STATUS_FLOW 的表项）。"""
    next: list[str]
    label: str
    color: str
    actions: dict[str, StatusAction]


ORDER_STATUS_FLOW: dict[str, StatusFlowEntry] = {
    'unprocessed': {
        'next': ['processing'],
        'label': '未处理',
        'color': '#6b7280',
        'actions': {
            'start_process': {'to': 'processing', 'label': '开始处理', 'require_remark': False}
        }
    },
    'processing': {
        'next': ['processed', 'ignored'],
        'label': '处理中',
        'color': '#3b82f6',
        'actions': {
            'complete': {'to': 'processed', 'label': '完成处理', 'require_remark': False},
            'ignore': {'to': 'ignored', 'label': '忽略订单', 'require_remark': True},
        }
    },
    'processed': {
        'next': ['processing'],
        'label': '已完成',
        'color': '#10b981',
        'actions': {
            'reopen': {'to': 'processing', 'label': '重新处理', 'require_remark': True}
        }
    },
    'ignored': {
        'next': ['processing'],
        'label': '已忽略',
        'color': '#ef4444',
        'actions': {
            'reopen': {'to': 'processing', 'label': '重新处理', 'require_remark': True}
        }
    }
}


def validate_status_transition(from_status: str, to_status: str) -> tuple[bool, str | None]:
    """验证状态转换是否合法"""
    if from_status not in ORDER_STATUS_FLOW:
        return False, f"无效的源状态: {from_status}"
    allowed_next = ORDER_STATUS_FLOW[from_status].get('next', [])
    if to_status not in allowed_next:
        return False, f"不允许从 {ORDER_STATUS_FLOW[from_status]['label']} 转换到 {ORDER_STATUS_FLOW.get(to_status, {}).get('label', to_status)}"
    return True, None


def get_action_for_transition(from_status: str, to_status: str) -> tuple[str, StatusAction] | None:
    """获取状态转换对应的操作"""
    if from_status not in ORDER_STATUS_FLOW:
        return None
    actions = ORDER_STATUS_FLOW[from_status].get('actions', {})
    for action_name, action_info in actions.items():
        if action_info['to'] == to_status:
            return action_name, action_info
    return None
