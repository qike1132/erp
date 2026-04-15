"""
产品模型
"""
from datetime import datetime
from app import db


class Product(db.Model):
    """产品模型"""
    __tablename__ = 'product'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True, index=True, comment='产品名称')
    barcode = db.Column(db.String(50), index=True, comment='69码/商品条码')
    price = db.Column(db.Numeric(10, 2), default=0, comment='产品价格')
    image = db.Column(db.String(200), comment='产品图片路径')
    initial_stock = db.Column(db.Integer, default=0, comment='初始库存')
    current_stock = db.Column(db.Integer, default=0, comment='当前库存')
    create_time = db.Column(db.DateTime, default=datetime.now, index=True, comment='创建时间')
    
    material = db.relationship('ProductMaterial', backref='product', uselist=False, cascade='all, delete-orphan')
    fabrics = db.relationship('ProductFabric', backref='product', cascade='all, delete-orphan')
    accessories = db.relationship('ProductAccessory', backref='product', cascade='all, delete-orphan')
    packagings = db.relationship('ProductPackaging', backref='product', cascade='all, delete-orphan')
    
    __table_args__ = (
        db.Index('idx_product_name_barcode', 'name', 'barcode'),
    )

    def __repr__(self):
        return f'<Product {self.name}>'
    
    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'barcode': self.barcode,
            'price': float(self.price) if self.price else 0,
            'image': self.image,
            'initial_stock': self.initial_stock,
            'current_stock': self.current_stock,
            'create_time': self.create_time.strftime('%Y-%m-%d %H:%M:%S') if self.create_time else None
        }
    
    def get_all_materials(self):
        """获取产品所有物料（包括填充物、面料、辅料、包装）"""
        materials = []
        
        if self.material and self.material.cotton_usage and self.material.cotton_usage > 0:
            materials.append(self.material.to_dict())
        
        for fabric in self.fabrics:
            materials.append(fabric.to_dict())
        
        for accessory in self.accessories:
            materials.append(accessory.to_dict())
        
        for packaging in self.packagings:
            materials.append(packaging.to_dict())
        
        return materials
    
    def has_bom(self):
        """检查产品是否有BOM数据"""
        has_material = self.material and self.material.cotton_usage and self.material.cotton_usage > 0
        has_fabric = len(self.fabrics) > 0
        has_accessory = len(self.accessories) > 0
        has_packaging = len(self.packagings) > 0
        return has_material or has_fabric or has_accessory or has_packaging
