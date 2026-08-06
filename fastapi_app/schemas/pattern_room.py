"""板房模块 Pydantic Schemas"""
from __future__ import annotations

from pydantic import BaseModel, Field


# ==================== BOM 节点 ====================

class BomItemVersionSchema(BaseModel):
    """物料版本快照"""
    id: int | None = None
    bom_item_id: int | None = None
    version: str = Field(..., description='版本号 T1/T2/T3...')
    supplier_id: int | None = None
    supplier_name: str = ''
    material_spec: str = ''
    unit_price: float | None = None
    contact_person: str = ''
    contact_phone: str = ''
    delivery_days: int | None = None
    remark: str = ''
    snapshot_at: str = ''


class BomItemSchema(BaseModel):
    """BOM 节点"""
    id: int | None = None
    bom_id: int | None = None
    parent_id: int | None = None
    sort_order: int = 0
    material_name: str = Field(..., min_length=1, max_length=200, description='物料名称')
    category: str = Field(..., description='类别: fabric/filling/accessory/packaging')
    quantity: float = Field(..., gt=0, description='用量')
    unit: str = '个'
    spec: str = ''
    current_supplier_id: int | None = None
    current_supplier_name: str = ''
    current_version: str = 'T1'
    remark: str = ''
    children: list['BomItemSchema'] = Field(default_factory=list)
    versions: list[BomItemVersionSchema] = Field(default_factory=list)


# 前向引用解析
BomItemSchema.model_rebuild()


# ==================== BOM 主表 ====================

class BomCreateRequest(BaseModel):
    """创建 BOM 请求"""
    product_name: str = Field(..., min_length=1, max_length=200, description='产品名称')
    customer_id: int | None = None
    customer_name: str = ''
    remark: str = ''
    items: list[BomItemSchema] = Field(default_factory=list, description='初始节点')


class BomUpdateRequest(BaseModel):
    """更新 BOM 元信息"""
    product_name: str | None = Field(None, min_length=1, max_length=200)
    customer_id: int | None = None
    customer_name: str | None = None
    remark: str | None = None
    status: str | None = Field(None, description='状态: draft/sampling/confirmed/archived')


class BomItemsSaveRequest(BaseModel):
    """批量保存 BOM 节点（整树提交，后端 diff + apply）"""
    items: list[BomItemSchema] = Field(..., description='整棵 BOM 树')


class BomListResponse(BaseModel):
    """BOM 列表响应"""
    success: bool = True
    items: list[dict] = Field(default_factory=list)
    total: int = 0
    pages: int = 1
    current_page: int = 1


class BomDetailResponse(BaseModel):
    """BOM 详情响应"""
    success: bool = True
    bom: dict | None = None


# ==================== 版本管理 ====================

class VersionCreateRequest(BaseModel):
    """创建新版本请求（自动快照当前数据）"""
    reason: str = Field(..., min_length=10, max_length=500, description='变更原因（≥10字符）')
    items: list[BomItemSchema] | None = Field(None, description='新版本的节点数据（可选，不传则快照当前）')


class VersionCompareResponse(BaseModel):
    """版本对比响应"""
    success: bool = True
    from_version: str
    to_version: str
    bom: dict | None = None
    differences: list[dict] = Field(default_factory=list, description='差异列表')


class VersionListResponse(BaseModel):
    """版本列表响应"""
    success: bool = True
    versions: list[str] = Field(default_factory=list)


# ==================== 变更日志 ====================

class ChangeLogListResponse(BaseModel):
    """变更日志列表响应"""
    success: bool = True
    items: list[dict] = Field(default_factory=list)
    total: int = 0


class ChangeLogDetailResponse(BaseModel):
    """变更日志详情响应"""
    success: bool = True
    log: dict | None = None


# ==================== 通用 ====================

class BomActionResponse(BaseModel):
    """操作响应"""
    success: bool = True
    id: int | None = None
    bom_no: str | None = None
    message: str = ''
