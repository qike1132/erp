"""按客户分类打样信息模块 Pydantic Schemas

对应 design.md 2.2.2 的 15 个接口请求/响应模型。
字段约束与 design.md 2.3.3 表定义一致。
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


# ==================== 类型别名 ====================

ChangeType = Literal['add', 'modify', 'delete']


# ==================== 通用响应 ====================

class ActionResponse(BaseModel):
    """操作响应（创建/更新/删除）"""
    success: bool = True
    message: str = '操作成功'
    id: int | None = None
    sequence_no: str | None = None
    version_id: int | None = None
    version_no: str | None = None
    file_id: int | None = None
    url: str | None = None


# ==================== 部位布料 ====================

class PartDetail(BaseModel):
    """部位布料详情"""
    model_config = ConfigDict(from_attributes=True)

    id: int | None = None
    project_id: int | None = None
    part_name: str = Field(..., min_length=1, max_length=100, description='部位名称')
    sort_order: int = Field(0, ge=0, description='排序值')
    fabric_name: str = ''
    fabric_spec: str = ''
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
    current_version: str = 'T1'
    updated_at: str = ''


class CustomerGroup(BaseModel):
    """客户分组"""
    customer_id: int | None = None
    customer_name: str
    project_count: int = 0
    latest_update_time: str = ''
    projects: list[ProjectSummary] = Field(default_factory=list)


class GroupedListResponse(BaseModel):
    """按客户分组聚合查询响应"""
    success: bool = True
    groups: list[CustomerGroup] = Field(default_factory=list)
    total_projects: int = 0


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
    product_image_file_id: int | None = None
    customer_id: int | None = None
    customer_name: str = ''
    current_version: str = 'T1'
    remark: str = ''
    created_by_name: str | None = None
    created_at: str = ''
    updated_at: str = ''
    version: int = 0
    parts: list[PartDetail] = Field(default_factory=list)
    versions: list[VersionBrief] = Field(default_factory=list)


# ==================== 请求 Schema ====================

class ProjectCreateRequest(BaseModel):
    """新增打样项目请求"""
    product_name: str = Field(..., min_length=1, max_length=200, description='产品名称')
    customer_id: int | None = None
    remark: str | None = Field(None, max_length=2000, description='备注')


class ProjectUpdateRequest(BaseModel):
    """编辑打样项目请求

    序列号与历史版本快照不可修改。
    version 为乐观锁版本号，必填。
    """
    product_name: str | None = Field(None, min_length=1, max_length=200)
    customer_id: int | None = None
    remark: str | None = Field(None, max_length=2000)
    product_image_file_id: int | None = None
    version: int = Field(..., description='乐观锁版本号')


class PartCreateRequest(BaseModel):
    """新增部位请求"""
    part_name: str = Field(..., min_length=1, max_length=100, description='部位名称')
    sort_order: int = Field(0, ge=0, description='排序值')
    fabric_name: str | None = Field(None, max_length=200, description='布料名称')
    fabric_spec: str | None = Field(None, max_length=200, description='布料规格')
    supplier_id: int | None = None
    contact_person: str | None = Field(None, max_length=100, description='联系人')
    contact_phone: str | None = Field(None, max_length=50, description='联系电话')
    unit_price: float | None = Field(None, ge=0, description='单价')
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
    supplier_id: int | None = None
    contact_person: str | None = Field(None, max_length=100)
    contact_phone: str | None = Field(None, max_length=50)
    unit_price: float | None = Field(None, ge=0)
    delivery_days: int | None = Field(None, ge=0)
    remark: str | None = Field(None, max_length=2000)
    version: int = Field(..., description='乐观锁版本号')


class VersionCreateRequest(BaseModel):
    """创建新版本请求"""
    reason: str | None = Field(None, max_length=500, description='变更原因(可选)')