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

from sqlalchemy import DateTime, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint, text
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

    唯一性说明：**大小写不敏感唯一由 ORM 与迁移共同表达**——两者都建立同名函数唯一索引
    ``uq_role_name_lower ON role (lower(name))``，实现「trim 后存储 + 大小写不敏感唯一」。
    在 ORM 层声明该索引（``text('lower(name)')``）会让 ``Base.metadata.create_all`` 建出的
    测试库与生产 DDL 一致，避免「迁移表达了、ORM 没表达 ⇒ 测试静默失守」。仍然**不使用**
    ``citext`` 扩展。应用层（``role_service``）另有 ``lower(trim(name))`` 预校验，
    数据库索引作为并发写入的最终兜底。
    """
    __tablename__ = 'role'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, comment='全局角色名（trim 后存储，保留用户输入大小写）')
    create_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), comment='创建时间')
    update_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC), comment='更新时间')

    # 函数唯一索引：与迁移 045 的 DDL 逐字同名同义（uq_role_name_lower）。
    # 必须用 text('lower(name)')（列表达式）——类体内 name 是 MappedColumn，
    # 用 func.lower(name) 会渲染成绑定参数，得不到真正的 (lower(name)) 函数索引。
    __table_args__ = (
        Index('uq_role_name_lower', text('lower(name)'), unique=True),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'create_time': self.create_time.strftime('%Y-%m-%d %H:%M:%S') if self.create_time else None,
            'update_time': self.update_time.strftime('%Y-%m-%d %H:%M:%S') if self.update_time else None,
        }


class ProductRole(Base):
    """产品 × 角色（**产品私有**）关联表（每个 SKU 可关联多个角色，如公仔的不同角色）。

    本表 ``id`` 是三张物料表（``product_material`` / ``product_fabric`` /
    ``product_accessory``）``role_id`` 外键的指向目标，因此**角色私有化改造不动物料表**。

    角色为**产品私有**：同一产品内 ``role_name`` 唯一（``lower(role_name)``，写入前
    trim），不同产品可有同名角色且互不影响（改名/删除只作用于本行）。

    - ``role_name``：角色名（写入前 trim；本产品的权威名）；
    - ``global_role_id``：**过渡残留列**（迁移 088 起可空、089 删除）。私有化后不再写入。
    """

    __tablename__ = 'product_role'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(Integer, ForeignKey('product.id', ondelete='CASCADE'), nullable=False, comment='关联产品ID')
    # 过渡残留列：088 改为可空、不再写入；089 删除。见迁移 pg_standalone_088/089。
    global_role_id: Mapped[int | None] = mapped_column(Integer, ForeignKey('role.id', ondelete='RESTRICT'), nullable=True, comment='[过渡] 全局角色ID，088 起可空、089 删除')
    role_name: Mapped[str] = mapped_column(String(100), nullable=False, comment='角色名称（产品私有；写入前 trim）')
    create_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), comment='创建时间')
    update_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC), comment='更新时间')

    product: Mapped[Product] = relationship("Product", back_populates="roles")
    # 全 ORM 关系均为 lazy='raise'：读取前必须显式 selectinload，否则抛 InvalidRequestError。
    global_role: Mapped[Role | None] = relationship("Role", lazy='raise')

    __table_args__ = (
        Index('idx_product_role_product', 'product_id'),
        # 产品内角色名唯一（大小写不敏感）。用 text('lower(role_name)') 列表达式
        # ——类体内 role_name 是 MappedColumn，用 func.lower 会渲染成绑定参数。
        # 用可移植的 lower()（而非 btrim）：迁移 088 已把存量名 btrim 归一，
        # 应用层写入前也 trim，故索引只需 lower；这样 SQLite 测试库也能建索引。
        Index('uq_product_role_product_name_lower', 'product_id', text('lower(role_name)'), unique=True),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'product_id': self.product_id,
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
        # AUD-09（104 迁移）：默认作用域硬 1:1 的 DB 兜底——必须与迁移声明一致，
        # 否则 alembic check 把迁移建的索引当漂移要求 remove。
        Index('uq_product_fabric_default_scope', 'product_id', unique=True,
              postgresql_where=text('role_id IS NULL')),
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
        # AUD-09（104 迁移）：同 ProductFabric——与迁移声明逐字一致防 check 漂移
        Index('uq_product_material_default_scope', 'product_id', unique=True,
              postgresql_where=text('role_id IS NULL')),
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
        # AUD-09（104 迁移）：同 ProductFabric
        Index('uq_product_accessory_default_scope', 'product_id', unique=True,
              postgresql_where=text('role_id IS NULL')),
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
