"""
产品BOM表模型 - 纯 SQLAlchemy 2.0 声明式

支持详细的布料和配件信息。
物料分类: fabric(面料类) / filling(填充类) / accessory(辅料类) / packaging(包装类)
"""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from fastapi_app.shared_models import Base

if TYPE_CHECKING:
    from fastapi_app.shared_models.product import Product

MATERIAL_CATEGORIES = {
    'fabric': {'name': '面料类'},
    'filling': {'name': '填充类'},
    'accessory': {'name': '辅料类'},
    'packaging': {'name': '包装类'}
}


class ProductFabric(Base):
    """产品布料明细模型"""
    __tablename__ = 'product_fabric'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(Integer, ForeignKey('product.id'), nullable=False, comment='关联产品ID')
    material_code: Mapped[str | None] = mapped_column(String(50), comment='物料编码')
    fabric_name: Mapped[str] = mapped_column(String(100), nullable=False, comment='布料名称')
    specification: Mapped[str | None] = mapped_column(String(100), comment='规格型号')
    quantity: Mapped[float] = mapped_column(Numeric(10, 4), nullable=False, comment='布料码数/数量(单SKU标准用量)')
    supplier_id: Mapped[int | None] = mapped_column(Integer, ForeignKey('supplier.id'), comment='默认供应商ID')
    supplier_name: Mapped[str | None] = mapped_column(String(100), comment='供应商名称(冗余)')
    unit: Mapped[str | None] = mapped_column(String(20), default='码', comment='单位')
    remark: Mapped[str | None] = mapped_column(Text, comment='备注')
    create_time: Mapped[datetime | None] = mapped_column(DateTime, default=datetime.now, comment='创建时间')
    update_time: Mapped[datetime | None] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now, comment='更新时间')

    material_category = 'fabric'

    product: Mapped["Product"] = relationship("Product", back_populates="fabrics")

    __table_args__ = (
        Index('idx_product_fabric_product', 'product_id'),
        Index('idx_product_fabric_supplier', 'supplier_id'),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'product_id': self.product_id,
            'material_code': self.material_code,
            'material_name': self.fabric_name,
            'fabric_name': self.fabric_name,
            'specification': self.specification,
            'quantity': float(self.quantity) if self.quantity else 0,
            'unit_usage': float(self.quantity) if self.quantity else 0,
            'supplier_id': self.supplier_id,
            'supplier_name': self.supplier_name,
            'unit': self.unit,
            'material_category': self.material_category,
            'category': self.material_category,
            'category_name': MATERIAL_CATEGORIES.get(self.material_category, {}).get('name', '面料类'),
            'remark': self.remark,
            'create_time': self.create_time.strftime('%Y-%m-%d %H:%M:%S') if self.create_time else None
        }


class ProductMaterial(Base):
    """产品填充材料模型 - 每个产品只有一条"""
    __tablename__ = 'product_material'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(Integer, ForeignKey('product.id'), nullable=False, unique=True, comment='关联产品ID')
    material_code: Mapped[str | None] = mapped_column(String(50), comment='物料编码')
    cotton_usage: Mapped[float | None] = mapped_column(Numeric(10, 4), default=0, comment='棉花用量（克）- 单SKU标准用量')
    specification: Mapped[str | None] = mapped_column(String(100), comment='规格型号')
    supplier_id: Mapped[int | None] = mapped_column(Integer, ForeignKey('supplier.id'), comment='默认供应商ID')
    supplier_name: Mapped[str | None] = mapped_column(String(100), comment='供应商名称(冗余)')
    unit: Mapped[str | None] = mapped_column(String(20), default='克', comment='单位')
    remark: Mapped[str | None] = mapped_column(Text, comment='备注')
    create_time: Mapped[datetime | None] = mapped_column(DateTime, default=datetime.now, comment='创建时间')
    update_time: Mapped[datetime | None] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now, comment='更新时间')

    material_category = 'filling'

    product: Mapped["Product"] = relationship("Product", back_populates="material")

    __table_args__ = (
        Index('idx_product_material_product', 'product_id'),
        Index('idx_product_material_supplier', 'supplier_id'),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'product_id': self.product_id,
            'product_name': self.product.name if self.product else None,
            'material_code': self.material_code,
            'material_name': '棉花/填充物',
            'cotton_usage': float(self.cotton_usage) if self.cotton_usage else 0,
            'quantity': float(self.cotton_usage) if self.cotton_usage else 0,
            'unit_usage': float(self.cotton_usage) if self.cotton_usage else 0,
            'specification': self.specification,
            'supplier_id': self.supplier_id,
            'supplier_name': self.supplier_name,
            'unit': self.unit,
            'material_category': self.material_category,
            'category': self.material_category,
            'category_name': MATERIAL_CATEGORIES.get(self.material_category, {}).get('name', '填充类'),
            'remark': self.remark,
            'create_time': self.create_time.strftime('%Y-%m-%d %H:%M:%S') if self.create_time else None,
            'update_time': self.update_time.strftime('%Y-%m-%d %H:%M:%S') if self.update_time else None
        }


class ProductAccessory(Base):
    """产品配件明细模型"""
    __tablename__ = 'product_accessory'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(Integer, ForeignKey('product.id'), nullable=False, comment='关联产品ID')
    material_code: Mapped[str | None] = mapped_column(String(50), comment='物料编码')
    accessory_name: Mapped[str] = mapped_column(String(100), nullable=False, comment='配件名称')
    specification: Mapped[str | None] = mapped_column(String(100), comment='规格型号')
    quantity: Mapped[float] = mapped_column(Numeric(10, 4), nullable=False, default=1, comment='数量(单SKU标准用量)')
    supplier_id: Mapped[int | None] = mapped_column(Integer, ForeignKey('supplier.id'), comment='默认供应商ID')
    supplier_name: Mapped[str | None] = mapped_column(String(100), comment='供应商名称(冗余)')
    unit: Mapped[str | None] = mapped_column(String(20), default='个', comment='单位')
    material_category: Mapped[str | None] = mapped_column(String(20), default='accessory', comment='物料分类: accessory/packaging')
    remark: Mapped[str | None] = mapped_column(Text, comment='备注')
    create_time: Mapped[datetime | None] = mapped_column(DateTime, default=datetime.now, comment='创建时间')
    update_time: Mapped[datetime | None] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now, comment='更新时间')

    product: Mapped["Product"] = relationship("Product", back_populates="accessories")

    __table_args__ = (
        Index('idx_product_accessory_product', 'product_id'),
        Index('idx_product_accessory_supplier', 'supplier_id'),
    )

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
            'unit_usage': float(self.quantity) if self.quantity else 0,
            'supplier_id': self.supplier_id,
            'supplier_name': self.supplier_name,
            'unit': self.unit,
            'material_category': category,
            'category': category,
            'category_name': MATERIAL_CATEGORIES.get(category, {}).get('name', '辅料类'),
            'remark': self.remark,
            'create_time': self.create_time.strftime('%Y-%m-%d %H:%M:%S') if self.create_time else None
        }


class ProductPackaging(Base):
    """产品包装材料明细模型"""
    __tablename__ = 'product_packaging'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(Integer, ForeignKey('product.id'), nullable=False, comment='关联产品ID')
    material_code: Mapped[str | None] = mapped_column(String(50), comment='物料编码')
    packaging_name: Mapped[str] = mapped_column(String(100), nullable=False, comment='包装材料名称')
    specification: Mapped[str | None] = mapped_column(String(100), comment='规格型号')
    quantity: Mapped[float] = mapped_column(Numeric(10, 4), nullable=False, default=1, comment='数量(单SKU标准用量)')
    supplier_id: Mapped[int | None] = mapped_column(Integer, ForeignKey('supplier.id'), comment='默认供应商ID')
    supplier_name: Mapped[str | None] = mapped_column(String(100), comment='供应商名称(冗余)')
    unit: Mapped[str | None] = mapped_column(String(20), default='个', comment='单位')
    remark: Mapped[str | None] = mapped_column(Text, comment='备注')
    create_time: Mapped[datetime | None] = mapped_column(DateTime, default=datetime.now, comment='创建时间')
    update_time: Mapped[datetime | None] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now, comment='更新时间')

    material_category = 'packaging'

    product: Mapped["Product"] = relationship("Product", back_populates="packagings")

    __table_args__ = (
        Index('idx_product_packaging_product', 'product_id'),
        Index('idx_product_packaging_supplier', 'supplier_id'),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'product_id': self.product_id,
            'material_code': self.material_code,
            'material_name': self.packaging_name,
            'packaging_name': self.packaging_name,
            'specification': self.specification,
            'quantity': float(self.quantity) if self.quantity else 0,
            'unit_usage': float(self.quantity) if self.quantity else 0,
            'supplier_id': self.supplier_id,
            'supplier_name': self.supplier_name,
            'unit': self.unit,
            'material_category': self.material_category,
            'category': self.material_category,
            'category_name': MATERIAL_CATEGORIES.get(self.material_category, {}).get('name', '包装类'),
            'remark': self.remark,
            'create_time': self.create_time.strftime('%Y-%m-%d %H:%M:%S') if self.create_time else None
        }
