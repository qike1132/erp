"""板房模块 ORM 模型

包含打样 BOM 主表、BOM 节点表、节点版本快照表、变更日志表。
编号格式遵循项目统一约定：BF-YYYYMMDD-XXXX（通过 services/numbering.py 生成）。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    desc,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from fastapi_app.shared_models import Base

if TYPE_CHECKING:
    from fastapi_app.shared_models.user import User


# 物料类别常量（与 product_material 模块一致）
PATTERN_ROOM_CATEGORIES = {
    'fabric': {'name': '面料类'},
    'filling': {'name': '填充类'},
    'accessory': {'name': '辅料类'},
    'packaging': {'name': '包装类'},
}

# BOM 状态流转：draft → sampling → confirmed → archived
PATTERN_ROOM_BOM_STATUSES = {
    'draft': '草稿',
    'sampling': '打样中',
    'confirmed': '已确认',
    'archived': '已归档',
}

# 变更类型
PATTERN_ROOM_CHANGE_TYPES = {
    'create': '创建 BOM',
    'version_upgrade': '版本升级',
    'supplier_change': '供应商变更',
    'status_change': '状态变更',
    'item_edit': '节点编辑',
}


class PatternRoomBom(Base):
    """板房打样 BOM 主表"""
    __tablename__ = 'pattern_room_bom'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bom_no: Mapped[str] = mapped_column(String(32), nullable=False, unique=True, comment='打样编号 BF-YYYYMMDD-XXXX')
    product_name: Mapped[str] = mapped_column(String(200), nullable=False, comment='产品名称')
    customer_id: Mapped[int | None] = mapped_column(Integer, ForeignKey('customer.id'), comment='客户ID')
    customer_name: Mapped[str | None] = mapped_column(String(200), comment='客户名称(冗余)')
    current_version: Mapped[str] = mapped_column(String(8), nullable=False, default='T1', comment='当前版本 T1/T2/T3...')
    status: Mapped[str] = mapped_column(String(16), nullable=False, default='draft', comment='状态: draft/sampling/confirmed/archived')
    remark: Mapped[str | None] = mapped_column(Text, comment='备注')
    created_by: Mapped[int | None] = mapped_column(Integer, ForeignKey('user.id'), comment='创建人ID')
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        comment='创建时间',
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
        comment='更新时间',
    )
    # 乐观锁
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment='乐观锁版本号')

    items: Mapped[list["PatternRoomBomItem"]] = relationship(
        'PatternRoomBomItem',
        back_populates='bom',
        cascade='all, delete-orphan',
        lazy='selectin',
    )
    change_logs: Mapped[list["PatternRoomChangeLog"]] = relationship(
        'PatternRoomChangeLog',
        back_populates='bom',
        cascade='all, delete-orphan',
        lazy='selectin',
        order_by='desc(PatternRoomChangeLog.created_at)',
    )
    creator: Mapped["User | None"] = relationship("User", lazy='selectin')

    __table_args__ = (
        Index('idx_prb_customer', 'customer_id'),
        Index('idx_prb_status_version', 'status', 'current_version'),
        Index('idx_prb_created_at', desc('created_at')),
        Index('idx_prb_product_name', 'product_name'),
    )

    def __repr__(self):
        return f'<PatternRoomBom {self.bom_no}>'

    def to_dict(self, include_items: bool = True, include_logs: bool = False) -> dict:
        data = {
            'id': self.id,
            'bom_no': self.bom_no,
            'product_name': self.product_name,
            'customer_id': self.customer_id,
            'customer_name': self.customer_name or '',
            'current_version': self.current_version,
            'status': self.status,
            'status_label': PATTERN_ROOM_BOM_STATUSES.get(self.status, self.status),
            'remark': self.remark or '',
            'created_by': self.created_by,
            'created_by_name': self.creator.username if self.creator else None,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S') if self.created_at else '',
            'updated_at': self.updated_at.strftime('%Y-%m-%d %H:%M:%S') if self.updated_at else '',
            'version': self.version,
        }
        if include_items:
            data['items'] = [item.to_dict() for item in (self.items or [])]
        if include_logs:
            data['change_logs'] = [log.to_dict() for log in (self.change_logs or [])]
        return data


class PatternRoomBomItem(Base):
    """BOM 节点表（支持多级树）"""
    __tablename__ = 'pattern_room_bom_item'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bom_id: Mapped[int] = mapped_column(Integer, ForeignKey('pattern_room_bom.id', ondelete='CASCADE'), nullable=False)
    parent_id: Mapped[int | None] = mapped_column(Integer, ForeignKey('pattern_room_bom_item.id', ondelete='CASCADE'), comment='父节点ID')
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment='排序')
    material_name: Mapped[str] = mapped_column(String(200), nullable=False, comment='物料名称')
    category: Mapped[str] = mapped_column(String(16), nullable=False, comment='类别: fabric/filling/accessory/packaging')
    quantity: Mapped[float] = mapped_column(Numeric(12, 3), nullable=False, default=1, comment='用量')
    unit: Mapped[str] = mapped_column(String(16), nullable=False, default='个', comment='单位')
    spec: Mapped[str | None] = mapped_column(String(200), comment='规格')
    current_supplier_id: Mapped[int | None] = mapped_column(Integer, ForeignKey('supplier.id'), comment='当前供应商ID')
    current_supplier_name: Mapped[str | None] = mapped_column(String(200), comment='当前供应商名称(冗余)')
    current_version: Mapped[str] = mapped_column(String(8), nullable=False, default='T1', comment='当前版本')
    remark: Mapped[str | None] = mapped_column(Text, comment='备注')
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    bom: Mapped["PatternRoomBom"] = relationship("PatternRoomBom", back_populates="items")
    # 自引用关系：与 permission.py 一致使用 remote_side 指定方向
    parent: Mapped["PatternRoomBomItem | None"] = relationship(
        "PatternRoomBomItem",
        back_populates="children",
        remote_side="PatternRoomBomItem.id",
    )
    children: Mapped[list["PatternRoomBomItem"]] = relationship(
        "PatternRoomBomItem",
        back_populates="parent",
        foreign_keys="PatternRoomBomItem.parent_id",
        cascade='all, delete-orphan',
        lazy='selectin',
        order_by='PatternRoomBomItem.sort_order',
    )
    versions: Mapped[list["PatternRoomBomItemVersion"]] = relationship(
        'PatternRoomBomItemVersion',
        back_populates='item',
        cascade='all, delete-orphan',
        lazy='selectin',
        order_by='desc(PatternRoomBomItemVersion.version)',
    )

    __table_args__ = (
        Index('idx_prbi_bom_parent', 'bom_id', 'parent_id', 'sort_order'),
        Index('idx_prbi_category', 'category'),
        Index('idx_prbi_supplier', 'current_supplier_id'),
    )

    def to_dict(
        self,
        include_versions: bool = True,
        children: list[dict] | None = None,
    ) -> dict:
        """序列化节点。

        Args:
            include_versions: 是否包含版本快照。
            children: 已构建的子节点列表。传入时直接使用，避免在 async
                上下文中递归访问 ``self.children`` 触发 lazy load
                （SQLAlchemy 自引用关系的 selectin 默认只加载 1 层，
                深层访问会抛 MissingGreenlet）。不传则尝试 lazy load
                （仅在同步上下文或单层树时安全）。
        """
        data = {
            'id': self.id,
            'bom_id': self.bom_id,
            'parent_id': self.parent_id,
            'sort_order': self.sort_order,
            'material_name': self.material_name,
            'category': self.category,
            'category_label': PATTERN_ROOM_CATEGORIES.get(self.category, {}).get('name', self.category),
            'quantity': float(self.quantity or 0),
            'unit': self.unit or '个',
            'spec': self.spec or '',
            'current_supplier_id': self.current_supplier_id,
            'current_supplier_name': self.current_supplier_name or '',
            'current_version': self.current_version,
            'remark': self.remark or '',
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S') if self.created_at else '',
            'updated_at': self.updated_at.strftime('%Y-%m-%d %H:%M:%S') if self.updated_at else '',
        }
        if include_versions:
            data['versions'] = [v.to_dict() for v in (self.versions or [])]
        # 调用方已构建好子树时直接使用，否则回退到 ORM lazy load
        # （async 上下文下递归访问 self.children 会触发 MissingGreenlet）
        if children is not None:
            data['children'] = children
        else:
            data['children'] = [c.to_dict(include_versions=include_versions) for c in (self.children or [])]
        return data


class PatternRoomBomItemVersion(Base):
    """物料版本快照表（每次版本切换时记录）"""
    __tablename__ = 'pattern_room_bom_item_version'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bom_item_id: Mapped[int] = mapped_column(Integer, ForeignKey('pattern_room_bom_item.id', ondelete='CASCADE'), nullable=False)
    version: Mapped[str] = mapped_column(String(8), nullable=False, comment='版本号 T1/T2/T3...')
    supplier_id: Mapped[int | None] = mapped_column(Integer, ForeignKey('supplier.id'))
    supplier_name: Mapped[str | None] = mapped_column(String(200), comment='供应商名称')
    material_spec: Mapped[str | None] = mapped_column(String(200), comment='物料规格')
    unit_price: Mapped[float | None] = mapped_column(Numeric(12, 2), comment='单价')
    contact_person: Mapped[str | None] = mapped_column(String(100), comment='联系人')
    contact_phone: Mapped[str | None] = mapped_column(String(50), comment='联系电话')
    delivery_days: Mapped[int | None] = mapped_column(Integer, comment='交期(天)')
    remark: Mapped[str | None] = mapped_column(Text, comment='备注')
    snapshot_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        comment='快照时间',
    )

    item: Mapped["PatternRoomBomItem"] = relationship("PatternRoomBomItem", back_populates="versions")

    __table_args__ = (
        Index('idx_prbiv_bom_item_version', 'bom_item_id', 'version'),
        Index('idx_prbiv_version', 'version'),
        # 同一节点同一版本唯一
        Index('uq_prbiv_item_version', 'bom_item_id', 'version', unique=True),
    )

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'bom_item_id': self.bom_item_id,
            'version': self.version,
            'supplier_id': self.supplier_id,
            'supplier_name': self.supplier_name or '',
            'material_spec': self.material_spec or '',
            'unit_price': float(self.unit_price) if self.unit_price is not None else None,
            'contact_person': self.contact_person or '',
            'contact_phone': self.contact_phone or '',
            'delivery_days': self.delivery_days,
            'remark': self.remark or '',
            'snapshot_at': self.snapshot_at.strftime('%Y-%m-%d %H:%M:%S') if self.snapshot_at else '',
        }


class PatternRoomChangeLog(Base):
    """板房变更日志表"""
    __tablename__ = 'pattern_room_change_log'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bom_id: Mapped[int] = mapped_column(Integer, ForeignKey('pattern_room_bom.id', ondelete='CASCADE'), nullable=False)
    bom_item_id: Mapped[int | None] = mapped_column(Integer, ForeignKey('pattern_room_bom_item.id', ondelete='SET NULL'), comment='关联节点ID')
    change_type: Mapped[str] = mapped_column(String(16), nullable=False, comment='变更类型')
    from_version: Mapped[str | None] = mapped_column(String(8), comment='原版本')
    to_version: Mapped[str | None] = mapped_column(String(8), comment='新版本')
    change_reason: Mapped[str] = mapped_column(Text, nullable=False, comment='变更原因')
    change_details: Mapped[dict] = mapped_column(JSONB, nullable=False, default=list, comment='字段级 diff')
    operator_id: Mapped[int | None] = mapped_column(Integer, ForeignKey('user.id'), comment='操作人ID')
    operator_name: Mapped[str | None] = mapped_column(String(100), comment='操作人姓名(冗余)')
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    bom: Mapped["PatternRoomBom"] = relationship("PatternRoomBom", back_populates="change_logs")
    operator: Mapped["User | None"] = relationship("User", lazy='selectin')

    __table_args__ = (
        Index('idx_prcl_bom_time', 'bom_id', desc('created_at')),
        Index('idx_prcl_type', 'change_type'),
        Index('idx_prcl_created_at', desc('created_at')),
    )

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'bom_id': self.bom_id,
            'bom_item_id': self.bom_item_id,
            'change_type': self.change_type,
            'change_type_label': PATTERN_ROOM_CHANGE_TYPES.get(self.change_type, self.change_type),
            'from_version': self.from_version or '',
            'to_version': self.to_version or '',
            'change_reason': self.change_reason or '',
            'change_details': self.change_details or [],
            'operator_id': self.operator_id,
            'operator_name': self.operator_name or (self.operator.username if self.operator else ''),
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S') if self.created_at else '',
        }
