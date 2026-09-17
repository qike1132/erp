"""
产品BOM表模型 - 纯 SQLAlchemy 2.0 声明式

支持详细的布料和配件信息。
物料分类: fabric(面料类) / filling(填充类) / accessory(辅料类)
角色(role): 一个 SKU 可关联多个角色，每个角色拥有独立的物料清单；
物料表 role_id 为 NULL 时表示产品级默认 BOM（无角色产品）。
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from fastapi_app.shared_models import Base

if TYPE_CHECKING:
    from fastapi_app.shared_models.product import Product

MATERIAL_CATEGORIES = {
    'fabric': {'name': '面料类'},
    'filling': {'name': '填充类'},
    'accessory': {'name': '辅料类'},
    'packaging': {'name': '包装类'},
}


class Role(Base):
    """全局角色字典 - 跨产品复用的角色主数据（表 role）。

    角色从「产品私有」升级为「全局字典」：一个角色记录可被多个产品通过
    ``ProductRole.global_role_id`` 关联复用。

    唯一性说明：**不在 ORM 层声明唯一约束**，改由迁移
    ``pg_standalone_045_global_role`` 建立函数唯一索引
    ``uq_role_name_lower ON role (lower(name))`` 实现「trim 后存储 + 大小写不敏感唯一」，
    免引入 ``citext`` 扩展。应用层（``role_service``）另有 ``lower(trim(name))`` 预校验。
    """
    __tablename__ = 'role'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, comment='全局角色名（trim 后存储，保留用户输入大小写）')
    create_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), comment='创建时间')
    update_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC), comment='更新时间')

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'create_time': self.create_time.strftime('%Y-%m-%d %H:%M:%S') if self.create_time else None,
            'update_time': self.update_time.strftime('%Y-%m-%d %H:%M:%S') if self.update_time else None,
        }


class ProductRole(Base):
    """产品 × 全局角色 关联表（每个 SKU 可关联多个角色，如公仔的不同角色）。

    迁移后本表降级为「产品 × 全局角色」关联表，其 ``id`` **保持不变**——
    三张物料表（``product_material`` / ``product_fabric`` / ``product_accessory``）
    的 ``role_id`` 外键仍指向本表 ``id``，因此物料表零迁移。

    - ``global_role_id``：指向全局角色字典 ``role.id``（ON DELETE RESTRICT，回填后 NOT NULL）；
    - ``role_name``：**回滚兼容镜像列**，改名时与全局角色名同步，保证回滚后旧代码显示正确名。
    """
    __tablename__ = 'product_role'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(Integer, ForeignKey('product.id', ondelete='CASCADE'), nullable=False, comment='关联产品ID')
    global_role_id: Mapped[int | None] = mapped_column(Integer, ForeignKey('role.id', ondelete='RESTRICT'), comment='全局角色ID(role.id)')
    role_name: Mapped[str] = mapped_column(String(100), nullable=False, comment='角色名称（回滚兼容镜像列，改名时同步）')
    create_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), comment='创建时间')
    update_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC), comment='更新时间')

    product: Mapped[Product] = relationship("Product", back_populates="roles")
    # 全 ORM 关系均为 lazy='raise'：读取前必须显式 selectinload，否则抛 InvalidRequestError。
    global_role: Mapped[Role | None] = relationship("Role", lazy='raise')

    __table_args__ = (
        Index('idx_product_role_product', 'product_id'),
        UniqueConstraint('product_id', 'global_role_id', name='uq_product_role_product_global'),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'product_id': self.product_id,
            'global_role_id': self.global_role_id,
            'role_name': self.role_name,
            'name': self.role_name,
            'create_time': self.create_time.strftime('%Y-%m-%d %H:%M:%S') if self.create_time else None,
        }


class ProductFabric(Base):
    """产品布料明细模型"""
    __tablename__ = 'product_fabric'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(Integer, ForeignKey('product.id'), nullable=False, comment='关联产品ID')
    role_id: Mapped[int | None] = mapped_column(Integer, ForeignKey('product_role.id', ondelete='CASCADE'), comment='角色ID(NULL=产品级默认BOM)')
    material_code: Mapped[str | None] = mapped_column(String(50), comment='物料编码')
    fabric_name: Mapped[str] = mapped_column(String(100), nullable=False, comment='布料名称')
    specification: Mapped[str | None] = mapped_column(String(100), comment='规格型号')
    quantity: Mapped[float] = mapped_column(Numeric(10, 4), nullable=False, comment='布料码数/数量(单SKU标准用量)')
    supplier_id: Mapped[int | None] = mapped_column(Integer, ForeignKey('supplier.id'), comment='默认供应商ID')
    supplier_name: Mapped[str | None] = mapped_column(String(100), comment='供应商名称(冗余)')
    unit: Mapped[str | None] = mapped_column(String(20), default='码', comment='单位')
    remark: Mapped[str | None] = mapped_column(Text, comment='备注')
    create_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), comment='创建时间')
    update_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC), comment='更新时间')

    material_category = 'fabric'

    product: Mapped[Product] = relationship("Product", back_populates="fabrics")

    __table_args__ = (
        Index('idx_product_fabric_product', 'product_id'),
        Index('idx_product_fabric_supplier', 'supplier_id'),
        Index('idx_product_fabric_role_id', 'role_id'),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'product_id': self.product_id,
            'role_id': self.role_id,
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
    product_id: Mapped[int] = mapped_column(Integer, ForeignKey('product.id'), nullable=False, comment='关联产品ID')
    role_id: Mapped[int | None] = mapped_column(Integer, ForeignKey('product_role.id', ondelete='CASCADE'), comment='角色ID(NULL=产品级默认BOM)')
    material_code: Mapped[str | None] = mapped_column(String(50), comment='物料编码')
    cotton_usage: Mapped[float | None] = mapped_column(Numeric(10, 4), default=0, comment='棉花用量（克）- 单SKU标准用量')
    specification: Mapped[str | None] = mapped_column(String(100), comment='规格型号')
    supplier_id: Mapped[int | None] = mapped_column(Integer, ForeignKey('supplier.id'), comment='默认供应商ID')
    supplier_name: Mapped[str | None] = mapped_column(String(100), comment='供应商名称(冗余)')
    unit: Mapped[str | None] = mapped_column(String(20), default='克', comment='单位')
    remark: Mapped[str | None] = mapped_column(Text, comment='备注')
    create_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), comment='创建时间')
    update_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC), comment='更新时间')

    material_category = 'filling'

    product: Mapped[Product] = relationship("Product", back_populates="material")

    __table_args__ = (
        Index('idx_product_material_product', 'product_id'),
        Index('idx_product_material_supplier', 'supplier_id'),
        Index('idx_product_material_role_id', 'role_id'),
        UniqueConstraint('product_id', 'role_id', name='uq_product_material_product_role'),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'product_id': self.product_id,
            'role_id': self.role_id,
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
    role_id: Mapped[int | None] = mapped_column(Integer, ForeignKey('product_role.id', ondelete='CASCADE'), comment='角色ID(NULL=产品级默认BOM)')
    material_code: Mapped[str | None] = mapped_column(String(50), comment='物料编码')
    accessory_name: Mapped[str] = mapped_column(String(100), nullable=False, comment='配件名称')
    specification: Mapped[str | None] = mapped_column(String(100), comment='规格型号')
    quantity: Mapped[float] = mapped_column(Numeric(10, 4), nullable=False, default=1, comment='数量(单SKU标准用量)')
    supplier_id: Mapped[int | None] = mapped_column(Integer, ForeignKey('supplier.id'), comment='默认供应商ID')
    supplier_name: Mapped[str | None] = mapped_column(String(100), comment='供应商名称(冗余)')
    unit: Mapped[str | None] = mapped_column(String(20), default='个', comment='单位')
    material_category: Mapped[str | None] = mapped_column(String(20), default='accessory', comment='物料分类: accessory/packaging')
    remark: Mapped[str | None] = mapped_column(Text, comment='备注')
    create_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), comment='创建时间')
    update_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC), comment='更新时间')

    product: Mapped[Product] = relationship("Product", back_populates="accessories")

    __table_args__ = (
        Index('idx_product_accessory_product', 'product_id'),
        Index('idx_product_accessory_supplier', 'supplier_id'),
        Index('idx_product_accessory_role_id', 'role_id'),
    )

    def to_dict(self):
        category = self.material_category or 'accessory'
        return {
            'id': self.id,
            'product_id': self.product_id,
            'role_id': self.role_id,
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
