"""
产品BOM表模型
支持详细的布料和配件信息
物料分类: fabric(面料类) / filling(填充类) / accessory(辅料类) / packaging(包装类)
"""
from datetime import datetime
from app import db


MATERIAL_CATEGORIES = {
    'fabric': {'name': '面料类'},
    'filling': {'name': '填充类'},
    'accessory': {'name': '辅料类'},
    'packaging': {'name': '包装类'}
}


class ProductFabric(db.Model):
    """产品布料明细模型 - 存储多种布料信息"""
    __tablename__ = 'product_fabric'
    
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False, comment='关联产品ID')
    material_code = db.Column(db.String(50), comment='物料编码')
    fabric_name = db.Column(db.String(100), nullable=False, comment='布料名称')
    specification = db.Column(db.String(100), comment='规格型号')
    quantity = db.Column(db.Numeric(10, 4), nullable=False, comment='布料码数/数量(单SKU标准用量)')
    supplier_id = db.Column(db.Integer, db.ForeignKey('supplier.id'), comment='默认供应商ID')
    supplier_name = db.Column(db.String(100), comment='供应商名称(冗余)')
    unit = db.Column(db.String(20), default='码', comment='单位')
    remark = db.Column(db.Text, comment='备注')
    create_time = db.Column(db.DateTime, default=datetime.now, comment='创建时间')
    update_time = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now, comment='更新时间')
    
    material_category = 'fabric'
    
    def to_dict(self):
        return {
            'id': self.id,
            'product_id': self.product_id,
            'material_code': self.material_code,
            'material_name': self.fabric_name,
            'fabric_name': self.fabric_name,
            'specification': self.specification,
            'quantity': float(self.quantity) if self.quantity else 0,
            'unit_usage': float(self.quantity) if self.quantity else 0,  # 添加unit_usage字段
            'supplier_id': self.supplier_id,
            'supplier_name': self.supplier_name,
            'unit': self.unit,
            'material_category': self.material_category,
            'category': self.material_category,  # 添加category字段
            'category_name': MATERIAL_CATEGORIES.get(self.material_category, {}).get('name', '面料类'),
            'remark': self.remark,
            'create_time': self.create_time.strftime('%Y-%m-%d %H:%M:%S') if self.create_time else None
        }


class ProductMaterial(db.Model):
    """产品物料用量模型 - 存储棉花/填充物用量"""
    __tablename__ = 'product_material'
    
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False, unique=True, comment='关联产品ID')
    material_code = db.Column(db.String(50), comment='物料编码')
    cotton_usage = db.Column(db.Numeric(10, 4), default=0, comment='棉花用量（克）- 单SKU标准用量')
    specification = db.Column(db.String(100), comment='规格型号')
    supplier_id = db.Column(db.Integer, db.ForeignKey('supplier.id'), comment='默认供应商ID')
    supplier_name = db.Column(db.String(100), comment='供应商名称(冗余)')
    unit = db.Column(db.String(20), default='克', comment='单位')
    remark = db.Column(db.Text, comment='备注')
    create_time = db.Column(db.DateTime, default=datetime.now, comment='创建时间')
    update_time = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now, comment='更新时间')
    
    material_category = 'filling'
    
    def to_dict(self):
        return {
            'id': self.id,
            'product_id': self.product_id,
            'product_name': self.product.name if self.product else None,
            'material_code': self.material_code,
            'material_name': '棉花/填充物',
            'cotton_usage': float(self.cotton_usage) if self.cotton_usage else 0,
            'quantity': float(self.cotton_usage) if self.cotton_usage else 0,
            'unit_usage': float(self.cotton_usage) if self.cotton_usage else 0,  # 添加unit_usage字段
            'specification': self.specification,
            'supplier_id': self.supplier_id,
            'supplier_name': self.supplier_name,
            'unit': self.unit,
            'material_category': self.material_category,
            'category': self.material_category,  # 添加category字段
            'category_name': MATERIAL_CATEGORIES.get(self.material_category, {}).get('name', '填充类'),
            'remark': self.remark,
            'create_time': self.create_time.strftime('%Y-%m-%d %H:%M:%S') if self.create_time else None,
            'update_time': self.update_time.strftime('%Y-%m-%d %H:%M:%S') if self.update_time else None
        }


class ProductAccessory(db.Model):
    """产品配件模型 - 存储配件明细"""
    __tablename__ = 'product_accessory'
    
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False, comment='关联产品ID')
    material_code = db.Column(db.String(50), comment='物料编码')
    accessory_name = db.Column(db.String(100), nullable=False, comment='配件名称')
    specification = db.Column(db.String(100), comment='规格型号')
    quantity = db.Column(db.Numeric(10, 4), nullable=False, default=1, comment='数量(单SKU标准用量)')
    supplier_id = db.Column(db.Integer, db.ForeignKey('supplier.id'), comment='默认供应商ID')
    supplier_name = db.Column(db.String(100), comment='供应商名称(冗余)')
    unit = db.Column(db.String(20), default='个', comment='单位')
    material_category = db.Column(db.String(20), default='accessory', comment='物料分类: accessory/packaging')
    remark = db.Column(db.Text, comment='备注')
    create_time = db.Column(db.DateTime, default=datetime.now, comment='创建时间')
    update_time = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now, comment='更新时间')
    
    def to_dict(self):
        category = self.material_category or 'accessory'
        return {
            'id': self.id,
            'product_id': self.product_id,
            'material_code': self.material_code,
            'material_name': self.accessory_name,
            'accessory_name': self.accessory_name,
            'specification': self.specification,
            'quantity': float(self.quantity) if self.quantity else 0,
            'unit_usage': float(self.quantity) if self.quantity else 0,  # 添加unit_usage字段
            'supplier_id': self.supplier_id,
            'supplier_name': self.supplier_name,
            'unit': self.unit,
            'material_category': category,
            'category': category,  # 添加category字段
            'category_name': MATERIAL_CATEGORIES.get(category, {}).get('name', '辅料类'),
            'remark': self.remark,
            'create_time': self.create_time.strftime('%Y-%m-%d %H:%M:%S') if self.create_time else None
        }


class ProductPackaging(db.Model):
    """产品包装材料模型"""
    __tablename__ = 'product_packaging'
    
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False, comment='关联产品ID')
    material_code = db.Column(db.String(50), comment='物料编码')
    packaging_name = db.Column(db.String(100), nullable=False, comment='包装材料名称')
    specification = db.Column(db.String(100), comment='规格型号')
    quantity = db.Column(db.Numeric(10, 4), nullable=False, default=1, comment='数量(单SKU标准用量)')
    supplier_id = db.Column(db.Integer, db.ForeignKey('supplier.id'), comment='默认供应商ID')
    supplier_name = db.Column(db.String(100), comment='供应商名称(冗余)')
    unit = db.Column(db.String(20), default='个', comment='单位')
    remark = db.Column(db.Text, comment='备注')
    create_time = db.Column(db.DateTime, default=datetime.now, comment='创建时间')
    update_time = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now, comment='更新时间')
    
    material_category = 'packaging'
    
    def to_dict(self):
        return {
            'id': self.id,
            'product_id': self.product_id,
            'material_code': self.material_code,
            'material_name': self.packaging_name,
            'packaging_name': self.packaging_name,
            'specification': self.specification,
            'quantity': float(self.quantity) if self.quantity else 0,
            'unit_usage': float(self.quantity) if self.quantity else 0,  # 添加unit_usage字段
            'supplier_id': self.supplier_id,
            'supplier_name': self.supplier_name,
            'unit': self.unit,
            'material_category': self.material_category,
            'category': self.material_category,  # 添加category字段
            'category_name': MATERIAL_CATEGORIES.get(self.material_category, {}).get('name', '包装类'),
            'remark': self.remark,
            'create_time': self.create_time.strftime('%Y-%m-%d %H:%M:%S') if self.create_time else None
        }
