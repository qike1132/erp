"""
用户模型
"""
from datetime import datetime
from app import db


user_permission = db.Table('user_permission',
    db.Column('user_id', db.Integer, db.ForeignKey('user.id'), primary_key=True),
    db.Column('permission_id', db.Integer, db.ForeignKey('permission.id'), primary_key=True)
)


class User(db.Model):
    """用户模型"""
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False, comment='用户名')
    phone = db.Column(db.String(20), nullable=True, comment='手机号')
    password = db.Column(db.String(200), nullable=False, comment='密码')
    is_super = db.Column(db.Boolean, default=False, comment='是否超级用户')
    status = db.Column(db.Boolean, default=True, comment='是否启用')
    create_time = db.Column(db.DateTime, default=datetime.now, comment='创建时间')
    update_time = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now, comment='更新时间')
    permissions = db.relationship('Permission', secondary='user_permission', backref=db.backref('users', lazy=True))

    def __repr__(self):
        return f'<User {self.username}>'

    def has_permission(self, permission_code):
        """检查用户是否有指定权限（支持父权限包含子权限，敏感权限仅超级用户可用）"""
        SENSITIVE_PERMISSIONS = ['user_manage']
        SENSITIVE_PREFIXES = ['user_']

        if permission_code in SENSITIVE_PERMISSIONS:
            return self.is_super

        for prefix in SENSITIVE_PREFIXES:
            if permission_code.startswith(prefix):
                return self.is_super

        if self.is_super:
            return True

        for p in self.permissions:
            if p.code == permission_code:
                return True
            if p.children:
                for child in p.children:
                    if child.code == permission_code:
                        return True
            if p.parent_id is None:
                if permission_code.startswith(p.code.split('_')[0] + '_'):
                    return True

        return False

    def get_all_permissions(self):
        """获取用户所有权限（包括父权限关联的子权限）"""
        all_perms = set()
        for p in self.permissions:
            all_perms.add(p)
            for child in p.children:
                all_perms.add(child)
        return list(all_perms)

    @property
    def masked_phone(self):
        """获取脱敏后的手机号"""
        if not self.phone or len(self.phone) < 7:
            return self.phone
        return f"{self.phone[:3]}****{self.phone[-4:]}"

    def to_dict(self, include_sensitive=False):
        """转换为字典"""
        data = {
            'id': self.id,
            'username': self.username,
            'phone': self.phone if include_sensitive else self.masked_phone,
            'is_super': self.is_super,
            'status': self.status,
            'create_time': self.create_time.isoformat() if self.create_time else None,
            'update_time': self.update_time.isoformat() if self.update_time else None
        }
        return data
