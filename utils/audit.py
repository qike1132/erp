"""
审计日志系统
记录用户操作和数据变更
"""
from datetime import datetime
from typing import Dict, Any, Optional
from functools import wraps
from flask import request, session
from app import db


# 审计日志模型
class AuditLog(db.Model):
    """审计日志模型"""
    __tablename__ = 'audit_log'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=True)
    username = db.Column(db.String(50))
    action = db.Column(db.String(50), nullable=False)  # create, update, delete, login, logout
    model = db.Column(db.String(50))  # 操作的模型
    model_id = db.Column(db.Integer)  # 操作的记录ID
    old_value = db.Column(db.Text)  # 旧值(JSON)
    new_value = db.Column(db.Text)  # 新值(JSON)
    ip_address = db.Column(db.String(50))
    user_agent = db.Column(db.String(200))
    description = db.Column(db.Text)
    create_time = db.Column(db.DateTime, default=datetime.now, index=True)
    
    def to_dict(self) -> Dict:
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
            'create_time': self.create_time.strftime('%Y-%m-%d %H:%M:%S')
        }


class AuditService:
    """审计服务"""
    
    @staticmethod
    def log(action: str, model: str = None, model_id: int = None,
           old_value: Any = None, new_value: Any = None,
           description: str = None) -> AuditLog:
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
        import json
        
        # 获取当前用户信息
        user_id = session.get('user_id')
        username = session.get('username', 'anonymous')
        
        # 获取请求信息
        ip_address = request.remote_addr if request else None
        user_agent = request.user_agent.string[:200] if request and request.user_agent else None
        
        # 转换值为JSON
        old_value_json = json.dumps(old_value, ensure_ascii=False) if old_value else None
        new_value_json = json.dumps(new_value, ensure_ascii=False) if new_value else None
        
        # 创建审计日志
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
        
        db.session.add(audit_log)
        db.session.commit()
        
        return audit_log
    
    @staticmethod
    def get_logs(user_id: int = None, model: str = None,
                action: str = None, limit: int = 100) -> list:
        """
        查询审计日志
        
        Args:
            user_id: 用户ID
            model: 模型名称
            action: 操作类型
            limit: 限制数量
        """
        query = AuditLog.query
        
        if user_id:
            query = query.filter(AuditLog.user_id == user_id)
        if model:
            query = query.filter(AuditLog.model == model)
        if action:
            query = query.filter(AuditLog.action == action)
        
        return query.order_by(AuditLog.create_time.desc()).limit(limit).all()
    
    @staticmethod
    def get_model_history(model: str, model_id: int) -> list:
        """
        获取模型的变更历史
        
        Args:
            model: 模型名称
            model_id: 记录ID
        """
        return AuditLog.query.filter(
            AuditLog.model == model,
            AuditLog.model_id == model_id
        ).order_by(AuditLog.create_time.desc()).all()


# 审计装饰器
def audit_action(action: str, model: str = None):
    """
    审计装饰器
    自动记录操作日志
    
    Args:
        action: 操作类型
        model: 模型名称
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            # 执行原函数
            result = f(*args, **kwargs)
            
            # 记录审计日志
            try:
                description = f'{action} {model}' if model else action
                AuditService.log(
                    action=action,
                    model=model,
                    model_id=kwargs.get('id') or kwargs.get('product_id') or kwargs.get('order_id'),
                    description=description
                )
            except Exception as e:
                # 审计日志失败不影响主流程
                print(f'审计日志记录失败: {e}')
            
            return result
        
        return decorated_function
    return decorator


# 操作类型常量
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


if __name__ == '__main__':
    print("审计日志系统模块")
    print("\n使用示例:")
    print("""
# 1. 手动记录审计日志
from utils.audit import AuditService, AuditAction

AuditService.log(
    action=AuditAction.UPDATE,
    model='Product',
    model_id=1,
    old_value={'name': '旧名称'},
    new_value={'name': '新名称'},
    description='更新产品名称'
)

# 2. 使用装饰器
from utils.audit import audit_action

@app.route('/product/update/<int:id>', methods=['POST'])
@audit_action(action='update', model='Product')
def update_product(id):
    # 更新产品
    pass

# 3. 查询审计日志
logs = AuditService.get_logs(user_id=1, limit=50)

# 4. 查询模型变更历史
history = AuditService.get_model_history('Product', 1)
    """)
