"""
权限模型（含导航字段）
"""
from app import db


class Permission(db.Model):
    """权限模型 - 同时作为导航配置"""
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False, comment='权限名称')
    code = db.Column(db.String(50), unique=True, nullable=False, comment='权限标识')
    parent_id = db.Column(db.Integer, db.ForeignKey('permission.id'), comment='父权限ID')
    
    icon = db.Column(db.String(50), comment='导航图标')
    url = db.Column(db.String(200), comment='导航链接')
    section = db.Column(db.String(50), comment='所属板块')
    section_name = db.Column(db.String(50), comment='板块显示名')
    sort_order = db.Column(db.Integer, default=0, comment='排序')
    is_nav = db.Column(db.Boolean, default=True, comment='是否显示在导航栏')
    
    parent = db.relationship('Permission', remote_side=[id], backref=db.backref('children', lazy=True))

    def __repr__(self):
        return f'<Permission {self.name}>'
    
    def to_dict(self):
        """转换为字典"""
        return {
            'id': self.id,
            'name': self.name,
            'code': self.code,
            'parent_id': self.parent_id,
            'icon': self.icon,
            'url': self.url,
            'section': self.section,
            'section_name': self.section_name,
            'sort_order': self.sort_order,
            'is_nav': self.is_nav
        }
