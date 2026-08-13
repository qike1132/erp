"""按客户分类打样信息模块 ORM 模型

包含打样项目主表与部位表。
编号格式遵循「{客户名称}{NNN}」按客户独立递增约定（通过 services/numbering.py 生成），
未关联客户时回退前缀为「未分类」。同一客户名下序号 001, 002, 003 单调递增；
跨客户各自独立计数。DB 列宽 String(32) 兼容中文名（≤6 字符）+ 3 位数字。

对应需求规格：.codeartsdoer/specs/customer_sampling/spec.md
对应技术设计：.codeartsdoer/specs/customer_sampling/design.md
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    desc,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from fastapi_app.shared_models import Base

if TYPE_CHECKING:
    from fastapi_app.shared_models.file_record import FileRecord
    from fastapi_app.shared_models.pattern_maker import PatternMaker
    from fastapi_app.shared_models.supplier import Supplier
    from fastapi_app.shared_models.user import User


# 操作类型常量
CUSTOMER_SAMPLING_ACTIONS = {
    'create_project': '创建项目',
    'update_project': '编辑项目',
    'delete_project': '删除项目',
    'create_part': '新增部位',
    'update_part': '编辑部位',
    'delete_part': '删除部位',
    'upload_image': '上传产品图片',
    'create_version': '创建新版本',
    'create_role': '新增角色',
    'update_role': '编辑角色',
    'delete_role': '删除角色',
}

# 变更类型常量
CUSTOMER_SAMPLING_CHANGE_TYPES = {
    'add': '新增',
    'modify': '修改',
    'delete': '删除',
}


class CustomerSamplingProject(Base):
    """按客户分类打样项目主表

    序列号格式：{客户名称}{NNN}，按客户独立递增，由 generate_customer_sampling_number 生成。
    未关联客户时前缀回退为「未分类」。同一客户名下 001, 002, 003 单调递增。
    """
    __tablename__ = 'customer_sampling_project'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sequence_no: Mapped[str] = mapped_column(
        String(32), nullable=False, unique=True, comment='序列号 {客户名称}{NNN}',
    )
    product_name: Mapped[str] = mapped_column(String(200), nullable=False, comment='产品名称')
    product_image_file_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey('file_records.id', ondelete='SET NULL'), comment='产品图片文件ID',
    )
    pattern_maker_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey('pattern_maker.id', ondelete='SET NULL'), comment='关联版师ID',
    )
    pattern_maker_name: Mapped[str | None] = mapped_column(String(200), comment='版师姓名(冗余)')
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
    # 乐观锁版本号
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment='乐观锁版本号')
    # 状态：in_progress/completed/cancelled
    status: Mapped[str] = mapped_column(String(20), nullable=False, default='in_progress', comment='状态')
    # 完成时间（标记为 completed 时写入，取消完成时清空）
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), comment='完成时间',
    )
    # 当前版本号
    current_version: Mapped[str] = mapped_column(String(8), nullable=False, default='T1', comment='当前版本 T1/T2/T3...')

    # 关联关系
    parts: Mapped[list["CustomerSamplingPart"]] = relationship(
        'CustomerSamplingPart',
        back_populates='project',
        cascade='all, delete-orphan',
        lazy='selectin',
        order_by='CustomerSamplingPart.sort_order',
    )
    pattern_maker: Mapped["PatternMaker | None"] = relationship("PatternMaker", lazy='selectin')
    product_image: Mapped["FileRecord | None"] = relationship("FileRecord", lazy='selectin')
    creator: Mapped["User | None"] = relationship("User", lazy='selectin')
    roles: Mapped[list["CustomerSamplingRole"]] = relationship(
        'CustomerSamplingRole',
        back_populates='project',
        cascade='all, delete-orphan',
        lazy='selectin',
        order_by='CustomerSamplingRole.sort_order',
    )
    fabric_versions: Mapped[list["CustomerSamplingFabricVersion"]] = relationship(
        'CustomerSamplingFabricVersion',
        back_populates='project',
        cascade='all, delete-orphan',
        lazy='selectin',
        order_by='CustomerSamplingFabricVersion.version_no',
    )
    change_logs: Mapped[list["CustomerSamplingChangeLog"]] = relationship(
        'CustomerSamplingChangeLog',
        back_populates='project',
        lazy='selectin',
        order_by='desc(CustomerSamplingChangeLog.created_at)',
    )

    __table_args__ = (
        Index('idx_csp_pattern_maker', 'pattern_maker_id'),
        Index('idx_csp_sequence_no', 'sequence_no'),
        # pg_trgm GIN 索引：使 ILIKE '%keyword%' 走索引（迁移脚本中创建）
        Index('idx_csp_product_name_trgm', 'product_name', postgresql_using='gin',
              postgresql_ops={'product_name': 'gin_trgm_ops'}),
        Index('idx_csp_updated_at_desc', desc('updated_at')),
        Index('idx_csp_created_at', 'created_at'),
        Index('idx_csp_completed_at', desc('completed_at')),
    )

    def __repr__(self):
        return f'<CustomerSamplingProject {self.sequence_no}>'

    def to_dict(self, include_parts: bool = False) -> dict:
        """序列化为字典

        Args:
            include_parts: 是否包含部位列表
        """
        data = {
            'id': self.id,
            'sequence_no': self.sequence_no,
            'product_name': self.product_name,
            'product_image_file_id': self.product_image_file_id,
            'pattern_maker_id': self.pattern_maker_id,
            'pattern_maker_name': self.pattern_maker_name or '',
            'remark': self.remark or '',
            'created_by': self.created_by,
            'created_by_name': self.creator.username if self.creator else None,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S') if self.created_at else '',
            'updated_at': self.updated_at.strftime('%Y-%m-%d %H:%M:%S') if self.updated_at else '',
            'version': self.version,
            'status': self.status,
            'completed_at': self.completed_at.strftime('%Y-%m-%d %H:%M:%S') if self.completed_at else None,
        }
        if include_parts:
            data['parts'] = [p.to_dict() for p in (self.parts or [])]
        return data


class CustomerSamplingRole(Base):
    """角色表（部位布料的角色维度）

    每个打样项目下可有 1..N 个角色，每个角色独立维护部位布料与版本快照。
    每个角色拥有独立的 current_version（最终版本），与其他角色完全隔离。
    迁移时为每个旧项目自动创建一个 is_default=True 的"默认角色"，承载所有旧数据。
    """
    __tablename__ = 'customer_sampling_role'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(
        Integer, ForeignKey('customer_sampling_project.id', ondelete='CASCADE'), nullable=False,
    )
    role_name: Mapped[str] = mapped_column(String(100), nullable=False, comment='角色名称')
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment='排序值')
    is_default: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default='false', comment='是否默认角色（不可删除）',
    )
    current_version: Mapped[str] = mapped_column(
        String(8), nullable=False, default='T1', server_default='T1', comment='该角色当前最终版本 T1/T2/T3...',
    )
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
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment='乐观锁版本号')

    project: Mapped["CustomerSamplingProject"] = relationship(
        "CustomerSamplingProject", back_populates="roles",
    )
    parts: Mapped[list["CustomerSamplingPart"]] = relationship(
        'CustomerSamplingPart',
        back_populates='role',
        cascade='all, delete-orphan',
        lazy='selectin',
        order_by='CustomerSamplingPart.sort_order',
    )
    fabric_versions: Mapped[list["CustomerSamplingFabricVersion"]] = relationship(
        'CustomerSamplingFabricVersion',
        back_populates='role',
        cascade='all, delete-orphan',
        lazy='selectin',
        order_by='CustomerSamplingFabricVersion.version_no',
    )

    __table_args__ = (
        # 项目内角色名唯一
        UniqueConstraint('project_id', 'role_name', name='uq_cs_role_project_name'),
        Index('idx_cs_role_project_sort', 'project_id', 'sort_order'),
    )

    def __repr__(self):
        return f'<CustomerSamplingRole {self.project_id}:{self.role_name}>'

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'project_id': self.project_id,
            'role_name': self.role_name,
            'sort_order': self.sort_order,
            'is_default': self.is_default,
            'current_version': self.current_version,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S') if self.created_at else '',
            'updated_at': self.updated_at.strftime('%Y-%m-%d %H:%M:%S') if self.updated_at else '',
            'version': self.version,
        }


class CustomerSamplingPart(Base):
    """部位表（当前工作布料数据）

    每个部位关联一条布料信息记录。
    同一打样项目下，同一 version_no 内部位名称唯一。
    通过"复制版本"操作可在同一 part_name 下创建多个版本（T1/T2/T3...）。
    """
    __tablename__ = 'customer_sampling_part'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(
        Integer, ForeignKey('customer_sampling_project.id', ondelete='CASCADE'), nullable=False,
    )
    role_id: Mapped[int] = mapped_column(
        Integer, ForeignKey('customer_sampling_role.id', ondelete='CASCADE'), nullable=False,
        comment='关联角色ID',
    )
    version_no: Mapped[str] = mapped_column(
        String(8), nullable=False, default='T1', server_default='T1', comment='版本号 T1/T2/T3...',
    )
    part_name: Mapped[str] = mapped_column(String(100), nullable=False, comment='部位名称')
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment='排序值')
    fabric_name: Mapped[str | None] = mapped_column(String(200), comment='布料名称')
    fabric_spec: Mapped[str | None] = mapped_column(String(200), comment='布料规格')
    fabric_color_no: Mapped[str | None] = mapped_column(String(50), comment='色号')
    supplier_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey('supplier.id', ondelete='SET NULL'), comment='供应商ID',
    )
    supplier_name: Mapped[str | None] = mapped_column(String(200), comment='供应商名称(冗余)')
    contact_person: Mapped[str | None] = mapped_column(String(100), comment='联系人')
    contact_phone: Mapped[str | None] = mapped_column(String(50), comment='联系电话')
    unit_price: Mapped[float | None] = mapped_column(Numeric(12, 2), comment='单价')
    delivery_days: Mapped[int | None] = mapped_column(Integer, comment='交期(天)')
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
    # 乐观锁
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment='乐观锁版本号')

    project: Mapped["CustomerSamplingProject"] = relationship(
        "CustomerSamplingProject", back_populates="parts",
    )
    role: Mapped["CustomerSamplingRole"] = relationship(
        "CustomerSamplingRole", back_populates="parts",
    )
    supplier: Mapped["Supplier | None"] = relationship("Supplier", lazy='selectin')

    __table_args__ = (
        # 同角色 + 同版本下部位名称唯一（T1/T2/T3 各自独立）
        Index('idx_csp_role_part_version', 'role_id', 'version_no', 'part_name', unique=True),
        Index('idx_csp_part_sort', 'project_id', 'sort_order'),
        # 单价非负、交期非负约束
        CheckConstraint('unit_price IS NULL OR unit_price >= 0', name='ck_csp_part_unit_price_nonneg'),
        CheckConstraint('delivery_days IS NULL OR delivery_days >= 0', name='ck_csp_part_delivery_days_nonneg'),
    )

    def __repr__(self):
        return f'<CustomerSamplingPart {self.part_name}>'

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'project_id': self.project_id,
            'role_id': self.role_id,
            'version_no': self.version_no,
            'part_name': self.part_name,
            'sort_order': self.sort_order,
            'fabric_name': self.fabric_name or '',
            'fabric_spec': self.fabric_spec or '',
            'fabric_color_no': self.fabric_color_no or '',
            'supplier_id': self.supplier_id,
            'supplier_name': self.supplier_name or '',
            'contact_person': self.contact_person or '',
            'contact_phone': self.contact_phone or '',
            'unit_price': float(self.unit_price) if self.unit_price is not None else None,
            'delivery_days': self.delivery_days,
            'remark': self.remark or '',
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S') if self.created_at else '',
            'updated_at': self.updated_at.strftime('%Y-%m-%d %H:%M:%S') if self.updated_at else '',
            'version': self.version,
        }

    def to_snapshot_dict(self) -> dict:
        """序列化为版本快照字典（用于 JSONB snapshot_data）

        返回所有参与 diff 比较的业务字段。
        """
        return {
            'id': self.id,
            'role_id': self.role_id,
            'version_no': self.version_no,
            'part_name': self.part_name,
            'sort_order': self.sort_order,
            'fabric_name': self.fabric_name or '',
            'fabric_spec': self.fabric_spec or '',
            'fabric_color_no': self.fabric_color_no or '',
            'supplier_id': self.supplier_id,
            'supplier_name': self.supplier_name or '',
            'contact_person': self.contact_person or '',
            'contact_phone': self.contact_phone or '',
            'unit_price': float(self.unit_price) if self.unit_price is not None else None,
            'delivery_days': self.delivery_days,
            'remark': self.remark or '',
            'version': self.version,
        }


class CustomerSamplingFabricVersion(Base):
    """布料版本快照表

    每次创建新版本时，快照当前所有部位布料信息。
    T1 为基线版本（创建项目时自动生成），snapshot_data 为完整快照，
    change_summary 为 null（基线版本无前一版本可比）。
    T2+ 版本：snapshot_data 为完整快照，change_summary 为相对前一版本的字段级 diff。
    """
    __tablename__ = 'customer_sampling_fabric_version'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(
        Integer, ForeignKey('customer_sampling_project.id', ondelete='CASCADE'), nullable=False,
    )
    role_id: Mapped[int] = mapped_column(
        Integer, ForeignKey('customer_sampling_role.id', ondelete='CASCADE'), nullable=False,
        comment='关联角色ID',
    )
    version_no: Mapped[str] = mapped_column(String(8), nullable=False, comment='版本号 T1/T2/T3...')
    snapshot_data: Mapped[list | None] = mapped_column(JSONB, nullable=False, comment='完整快照数据')
    change_summary: Mapped[list | None] = mapped_column(JSONB, comment='相对前一版本的字段级diff')
    reason: Mapped[str | None] = mapped_column(String(500), comment='变更原因')
    created_by: Mapped[int | None] = mapped_column(Integer, ForeignKey('user.id'), comment='创建人ID')
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        comment='创建时间',
    )

    project: Mapped["CustomerSamplingProject"] = relationship(
        "CustomerSamplingProject", back_populates="fabric_versions",
    )
    role: Mapped["CustomerSamplingRole"] = relationship(
        "CustomerSamplingRole", back_populates="fabric_versions",
    )
    creator: Mapped["User | None"] = relationship("User", lazy='selectin')

    __table_args__ = (
        Index('idx_csfv_project_version', 'project_id', 'version_no'),
        Index('idx_csfv_role_version', 'role_id', 'version_no'),
        Index('idx_csfv_created_at', 'created_at'),
        # 同一角色同一版本唯一
        Index('uq_csfv_role_version', 'role_id', 'version_no', unique=True),
    )

    def __repr__(self):
        return f'<CustomerSamplingFabricVersion {self.project_id}:{self.version_no}>'

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'project_id': self.project_id,
            'role_id': self.role_id,
            'version_no': self.version_no,
            'snapshot_data': self.snapshot_data or [],
            'change_summary': self.change_summary,
            'reason': self.reason or '',
            'created_by': self.created_by,
            'created_by_name': self.creator.username if self.creator else None,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S') if self.created_at else '',
        }


class CustomerSamplingChangeLog(Base):
    """打样变更日志表（审计追溯）

    记录所有打样项目的操作变更，包括创建/编辑/删除项目、部位操作、版本创建等。
    action 字段标识操作类型，change_type 标识具体变更类型（add/modify/delete）。
    项目删除时外键 SET NULL，保留日志可追溯。
    """
    __tablename__ = 'customer_sampling_change_log'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey('customer_sampling_project.id', ondelete='SET NULL'), comment='关联打样项目ID',
    )
    target_version: Mapped[str | None] = mapped_column(String(8), comment='目标版本号')
    action: Mapped[str] = mapped_column(String(32), nullable=False, comment='操作类型')
    change_type: Mapped[str | None] = mapped_column(String(16), comment='变更类型 add/modify/delete')
    part_name: Mapped[str | None] = mapped_column(String(100), comment='关联部位名称')
    field_diffs: Mapped[list | None] = mapped_column(JSONB, comment='字段级差异')
    operator_id: Mapped[int | None] = mapped_column(Integer, ForeignKey('user.id'), comment='操作人ID')
    operator_name: Mapped[str | None] = mapped_column(String(100), comment='操作人姓名(冗余)')
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        comment='操作时间',
    )

    project: Mapped["CustomerSamplingProject | None"] = relationship(
        "CustomerSamplingProject", back_populates="change_logs",
    )
    operator: Mapped["User | None"] = relationship("User", lazy='selectin')

    __table_args__ = (
        Index('idx_cscl_project_time', 'project_id', desc('created_at')),
        Index('idx_cscl_action', 'action'),
        Index('idx_cscl_created_at', desc('created_at')),
    )

    def __repr__(self):
        return f'<CustomerSamplingChangeLog {self.action}>'

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'project_id': self.project_id,
            'target_version': self.target_version or '',
            'action': self.action,
            'action_label': CUSTOMER_SAMPLING_ACTIONS.get(self.action, self.action),
            'change_type': self.change_type or '',
            'change_type_label': CUSTOMER_SAMPLING_CHANGE_TYPES.get(self.change_type or '', self.change_type or ''),
            'part_name': self.part_name or '',
            'field_diffs': self.field_diffs or [],
            'operator_id': self.operator_id,
            'operator_name': self.operator_name or (self.operator.username if self.operator else ''),
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S') if self.created_at else '',
        }
