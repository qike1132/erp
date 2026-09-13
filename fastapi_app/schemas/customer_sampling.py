"""按客户分类打样信息模块 Pydantic Schemas

对应 design.md 2.2.2 的 15 个接口请求/响应模型。
字段约束与 design.md 2.3.3 表定义一致。
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# ==================== 类型别名 ====================

ChangeType = Literal['add', 'modify', 'delete']

# 版本号格式（T1/T2/.../T999）
_VERSION_NO_PATTERN = r'^T\d{1,3}$'

# 单价上限（DB 列 Numeric(12, 2)，超出会触发数据库异常返回 500）
_UNIT_PRICE_MAX = 9999999999.99


# ==================== 通用响应 ====================

class ActionResponse(BaseModel):
    """操作响应（创建/更新/删除）

    version 字段：带乐观锁的更新操作（部位/角色/项目）返回更新后的新版本号，
    供前端局部回写，避免第二次编辑携带旧 version 触发 409。
    """
    success: bool = True
    message: str = '操作成功'
    id: int | None = None
    sequence_no: str | None = None
    version_id: int | None = None
    version_no: str | None = None
    version: int | None = None
    file_id: int | None = None
    url: str | None = None
    thumbnail_url: str | None = None


# ==================== 部位布料 ====================

class PartDetail(BaseModel):
    """部位布料详情"""
    model_config = ConfigDict(from_attributes=True)

    id: int | None = None
    project_id: int | None = None
    role_id: int | None = None
    version_no: str | None = None
    part_name: str = Field(..., min_length=1, max_length=100, description='部位名称')
    sort_order: int = Field(0, ge=0, description='排序值')
    fabric_name: str = ''
    fabric_spec: str = ''
    fabric_color_no: str = ''
    supplier_id: int | None = None
    supplier_name: str = ''
    contact_person: str = ''
    contact_phone: str = ''
    unit_price: float | None = Field(None, ge=0, description='单价')
    delivery_days: int | None = Field(None, ge=0, description='交期(天)')
    remark: str = ''
    created_at: str = ''
    updated_at: str = ''
    version: int = 0


class PartListResponse(BaseModel):
    """部位列表响应"""
    success: bool = True
    items: list[PartDetail] = Field(default_factory=list)


class PartsByVersionResponse(BaseModel):
    """部位跨版本汇总响应（部位+版本二维表数据源）"""
    success: bool = True
    items: list[PartDetail] = Field(default_factory=list)
    versions: list[str] = Field(default_factory=list)
    final_version: str = 'T1'


# ==================== 角色 ====================

class RoleBrief(BaseModel):
    """角色简要信息（列表展示）"""
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    role_name: str
    sort_order: int = 0
    is_default: bool = False
    current_version: str = 'T1'
    created_at: str = ''
    updated_at: str = ''
    version: int = 0


class RoleListResponse(BaseModel):
    """角色列表响应"""
    success: bool = True
    items: list[RoleBrief] = Field(default_factory=list)


class RoleCreateRequest(BaseModel):
    """新增角色请求"""
    role_name: str = Field(..., min_length=1, max_length=100, description='角色名称')


class RoleUpdateRequest(BaseModel):
    """编辑角色请求（role_name 可改，is_default 不可改）"""
    role_name: str | None = Field(None, min_length=1, max_length=100, description='角色名称')
    current_version: str | None = Field(
        None, max_length=8, pattern=_VERSION_NO_PATTERN,
        description='当前最终版本 T1/T2/T3...',
    )
    version: int = Field(..., description='乐观锁版本号')


# ==================== 版本 ====================

class VersionBrief(BaseModel):
    """版本简要信息"""
    model_config = ConfigDict(from_attributes=True)

    id: int
    version_no: str
    created_at: str = ''
    reason: str = ''


class VersionListResponse(BaseModel):
    """版本列表响应"""
    success: bool = True
    items: list[VersionBrief] = Field(default_factory=list)


class FieldDiff(BaseModel):
    """字段级差异"""
    field: str
    old: Any = None
    new: Any = None


class ChangeRecord(BaseModel):
    """变更记录（版本 diff 元素）"""
    change_type: ChangeType
    part_name: str
    new_value: PartDetail | None = None
    old_value: PartDetail | None = None
    field_diffs: list[FieldDiff] | None = None


class VersionDetailResponse(BaseModel):
    """版本详情响应

    - T1（is_baseline=True）：返回 full_snapshot，change_summary=null
    - T2+ 正常：返回 change_summary（预计算 diff），full_snapshot=null
    - 降级（degraded=True，前一版本缺失）：返回 full_snapshot + degraded=true
    """
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    version_no: str
    created_at: str = ''
    is_baseline: bool = False
    degraded: bool = False
    full_snapshot: list[PartDetail] | None = None
    change_summary: list[ChangeRecord] | None = None


# ==================== 变更日志 ====================

class ChangeLogEntry(BaseModel):
    """变更日志条目"""
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    target_version: str = ''
    action: str
    action_label: str = ''
    change_type: str = ''
    change_type_label: str = ''
    part_name: str = ''
    field_diffs: list[Any] = Field(default_factory=list)
    operator_id: int | None = None
    operator_name: str = ''
    created_at: str = ''


class ChangeLogListResponse(BaseModel):
    """变更日志列表响应"""
    success: bool = True
    items: list[ChangeLogEntry] = Field(default_factory=list)
    total: int = 0
    pages: int = 1
    current_page: int = 1


# ==================== 打样项目 ====================

class ProjectSummary(BaseModel):
    """打样项目摘要（列表展示）"""
    model_config = ConfigDict(from_attributes=True)

    id: int
    sequence_no: str
    product_name: str
    product_image_url: str | None = None
    product_image_thumbnail_url: str | None = None
    product_image_blur_url: str | None = None
    current_version: str = 'T1'
    status: str = 'in_progress'
    completed_at: str | None = None
    parts_count: int = 0
    updated_at: str = ''


class PatternMakerGroup(BaseModel):
    """版师分组"""
    pattern_maker_id: int | None = None
    pattern_maker_name: str
    project_count: int = 0
    latest_update_time: str = ''
    projects: list[ProjectSummary] = Field(default_factory=list)


class GroupedListResponse(BaseModel):
    """按版师分组聚合查询响应"""
    success: bool = True
    groups: list[PatternMakerGroup] = Field(default_factory=list)
    total_projects: int = 0
    total: int = 0
    pages: int = 1
    current_page: int = 1


class ProjectListResponse(BaseModel):
    """打样项目列表响应（分页）"""
    success: bool = True
    items: list[ProjectSummary] = Field(default_factory=list)
    total: int = 0
    pages: int = 1
    current_page: int = 1


class ProjectDetailResponse(BaseModel):
    """打样项目详情响应"""
    model_config = ConfigDict(from_attributes=True)

    id: int
    sequence_no: str
    product_name: str
    product_image_url: str | None = None
    product_image_thumbnail_url: str | None = None
    product_image_blur_url: str | None = None
    product_image_file_id: int | None = None
    pattern_maker_id: int | None = None
    pattern_maker_name: str = ''
    current_version: str = 'T1'
    status: str = 'in_progress'
    remark: str = ''
    created_by_name: str | None = None
    created_at: str = ''
    updated_at: str = ''
    version: int = 0
    parts: list[PartDetail] = Field(default_factory=list)
    versions: list[VersionBrief] = Field(default_factory=list)
    roles: list[RoleBrief] = Field(default_factory=list)


# ==================== 请求 Schema ====================

class ProjectStatusUpdateRequest(BaseModel):
    """项目状态更新请求（in_progress/completed/cancelled）"""
    status: Literal['in_progress', 'completed', 'cancelled'] = Field(
        ..., description='项目状态',
    )

class ProjectCreateRequest(BaseModel):
    """新增打样项目请求"""
    product_name: str = Field(..., min_length=1, max_length=200, description='产品名称')
    pattern_maker_id: int | None = None
    remark: str | None = Field(None, max_length=2000, description='备注')
    initial_roles: list[str] | None = Field(
        None, max_length=10, description='初始角色名称列表（不传时自动创建"默认"）',
    )


class ProjectUpdateRequest(BaseModel):
    """编辑打样项目请求

    序列号与历史版本快照不可修改。
    version 为乐观锁版本号，必填。
    clear_image=True 时清除产品图片（None 语义为"不修改"，无法表达清空）。
    """
    product_name: str | None = Field(None, min_length=1, max_length=200)
    pattern_maker_id: int | None = None
    remark: str | None = Field(None, max_length=2000)
    product_image_file_id: int | None = None
    clear_image: bool = Field(False, description='清除产品图片（默认 False）')
    current_version: str | None = Field(
        None, max_length=8, pattern=_VERSION_NO_PATTERN,
        description='当前版本/最终版本 T1/T2/T3...',
    )
    version: int = Field(..., description='乐观锁版本号')


class PartCreateRequest(BaseModel):
    """新增部位请求"""
    part_name: str = Field(..., min_length=1, max_length=100, description='部位名称')
    sort_order: int = Field(0, ge=0, description='排序值')
    fabric_name: str | None = Field(None, max_length=200, description='布料名称')
    fabric_spec: str | None = Field(None, max_length=200, description='布料规格')
    fabric_color_no: str | None = Field(None, max_length=50, description='色号')
    supplier_id: int | None = None
    contact_person: str | None = Field(None, max_length=100, description='联系人')
    contact_phone: str | None = Field(None, max_length=50, description='联系电话')
    unit_price: float | None = Field(None, ge=0, le=_UNIT_PRICE_MAX, description='单价')
    delivery_days: int | None = Field(None, ge=0, description='交期(天)')
    remark: str | None = Field(None, max_length=2000, description='备注')


class PartUpdateRequest(BaseModel):
    """编辑部位请求

    所有字段可选，version 为乐观锁版本号，必填。
    """
    part_name: str | None = Field(None, min_length=1, max_length=100)
    sort_order: int | None = Field(None, ge=0)
    fabric_name: str | None = Field(None, max_length=200)
    fabric_spec: str | None = Field(None, max_length=200)
    fabric_color_no: str | None = Field(None, max_length=50)
    supplier_id: int | None = None
    supplier_name: str | None = Field(None, max_length=200, description='供应商名称(文本)')
    contact_person: str | None = Field(None, max_length=100)
    contact_phone: str | None = Field(None, max_length=50)
    unit_price: float | None = Field(None, ge=0, le=_UNIT_PRICE_MAX)
    delivery_days: int | None = Field(None, ge=0)
    remark: str | None = Field(None, max_length=2000)
    version: int = Field(..., description='乐观锁版本号')


class VersionCreateRequest(BaseModel):
    """创建新版本请求"""
    reason: str | None = Field(None, max_length=500, description='变更原因(可选)')


class BatchPartItem(BaseModel):
    """批量新增部位单项"""
    part_name: str = Field(..., min_length=1, max_length=100, description='部位名称')
    supplier_id: int | None = None
    supplier_name: str | None = Field(None, max_length=100, description='供应商名称（手动输入）')
    fabric_name: str | None = Field(None, max_length=200, description='布料名称')
    fabric_color_no: str | None = Field(None, max_length=50, description='色号')
    version_no: str = Field('T1', max_length=8, pattern=_VERSION_NO_PATTERN, description='版本号')


class BatchPartCreateRequest(BaseModel):
    """批量新增部位请求"""
    items: list[BatchPartItem] = Field(..., min_length=1, max_length=50, description='部位列表')
