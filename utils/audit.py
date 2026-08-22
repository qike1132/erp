"""
审计日志系统
记录用户操作和数据变更 (FastAPI 兼容版本)
"""
import contextvars
import json
from datetime import datetime
from functools import wraps
from typing import Any

from sqlalchemy import Column, DateTime, Integer, String, Text

from fastapi_app.core.database import SyncSession
from fastapi_app.shared_models.base import Base

# 使用 contextvars 存储请求上下文
current_user_id = contextvars.ContextVar('current_user_id', default=None)
current_username = contextvars.ContextVar('current_username', default='anonymous')
current_ip = contextvars.ContextVar('current_ip', default=None)
current_user_agent = contextvars.ContextVar('current_user_agent', default=None)


class AuditLog(Base):
    """审计日志模型"""
    __tablename__ = 'audit_log'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, nullable=True)
    username = Column(String(50))
    action = Column(String(50), nullable=False)
    model = Column(String(50))
    model_id = Column(Integer)
    old_value = Column(Text)
    new_value = Column(Text)
    ip_address = Column(String(50))
    user_agent = Column(String(200))
    description = Column(Text)
    create_time = Column(DateTime, default=datetime.now, index=True)

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'user_id': self.user_id,
            'username': self.username,
            'action': self.action,
            'model': self.model,
            'model_id': self.model_id,
            'old_value': self.old_value,
            'new_value': self.new_value,
            'ip_address': self.ip_address,
            'description': self.description,
            'create_time': self.create_time.strftime('%Y-%m-%d %H:%M:%S') if self.create_time else None
        }


class AuditService:
    """审计服务"""

    @staticmethod
    def log(action: str, model: str | None = None, model_id: int | None = None,
           old_value: Any = None, new_value: Any = None,
           description: str | None = None) -> AuditLog:
        """
        记录审计日志

        Args:
            action: 操作类型
            model: 模型名称
            model_id: 记录ID
            old_value: 旧值
            new_value: 新值
            description: 描述
        """
        user_id = current_user_id.get()
        username = current_username.get() or 'anonymous'
        ip_address = current_ip.get()
        user_agent = current_user_agent.get()

        old_value_json = json.dumps(old_value, ensure_ascii=False) if old_value else None
        new_value_json = json.dumps(new_value, ensure_ascii=False) if new_value else None

        audit_log = AuditLog(
            user_id=user_id,
            username=username,
            action=action,
            model=model,
            model_id=model_id,
            old_value=old_value_json,
            new_value=new_value_json,
            ip_address=ip_address,
            user_agent=user_agent,
            description=description
        )

        with SyncSession() as session:
            session.add(audit_log)

        return audit_log

    @staticmethod
    def get_logs(user_id: int | None = None, model: str | None = None,
                action: str | None = None, limit: int = 100) -> list:
        """查询审计日志"""
        with SyncSession() as session:
            query = session.query(AuditLog)

            if user_id:
                query = query.filter(AuditLog.user_id == user_id)
            if model:
                query = query.filter(AuditLog.model == model)
            if action:
                query = query.filter(AuditLog.action == action)

            return query.order_by(AuditLog.create_time.desc()).limit(limit).all()

    @staticmethod
    def get_model_history(model: str, model_id: int) -> list:
        """获取模型的变更历史"""
        with SyncSession() as session:
            return session.query(AuditLog).filter(
                AuditLog.model == model,
                AuditLog.model_id == model_id
            ).order_by(AuditLog.create_time.desc()).all()


def audit_action(action: str, model: str | None = None):
    """审计装饰器"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            result = f(*args, **kwargs)

            try:
                description = f'{action} {model}' if model else action
                AuditService.log(
                    action=action,
                    model=model,
                    model_id=kwargs.get('id') or kwargs.get('product_id') or kwargs.get('order_id'),
                    description=description
                )
            except Exception as e:
                print(f'审计日志记录失败: {e}')

            return result

        return decorated_function
    return decorator


class AuditAction:
    """操作类型常量"""
    CREATE = 'create'
    UPDATE = 'update'
    DELETE = 'delete'
    LOGIN = 'login'
    LOGOUT = 'logout'
    VIEW = 'view'
    EXPORT = 'export'
    IMPORT = 'import'
