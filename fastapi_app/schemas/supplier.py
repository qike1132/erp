"""供应商管理相关 Schema"""
from pydantic import BaseModel, Field


class SupplierCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, description="供应商名称")
    contact_person: str | None = Field(default=None, max_length=50, description="联系人")
    phone: str | None = Field(default=None, max_length=20, description="电话")
    address: str | None = Field(default=None, max_length=200, description="地址")
    remark: str | None = Field(default=None, description="备注")


class SupplierUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100, description="供应商名称")
    contact_person: str | None = Field(default=None, max_length=50, description="联系人")
    phone: str | None = Field(default=None, max_length=20, description="电话")
    address: str | None = Field(default=None, max_length=200, description="地址")
    remark: str | None = Field(default=None, description="备注")
    # status 字段已移除：状态切换由独立的 /toggle-status 端点处理


class SupplierResponse(BaseModel):
    id: int
    name: str
    contact_person: str | None = None
    phone: str | None = None
    address: str | None = None
    remark: str | None = None
    status: bool = True
    created_at: str | None = None

    class Config:
        from_attributes = True


class SupplierListResponse(BaseModel):
    success: bool = True
    suppliers: list[SupplierResponse]
    total: int = 0


class SupplierActionResponse(BaseModel):
    success: bool = True
    message: str


class SupplierToggleResponse(BaseModel):
    success: bool = True
    status: bool
    message: str
