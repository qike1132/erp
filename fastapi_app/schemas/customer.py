"""客户管理相关 Schema"""
from pydantic import BaseModel, Field


class CustomerCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, description="客户名称")
    contact: str | None = Field(default=None, max_length=50, description="联系人")
    phone: str | None = Field(default=None, max_length=20, description="电话")
    address: str | None = Field(default=None, max_length=200, description="地址")
    note: str | None = Field(default=None, description="备注")


class CustomerUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100, description="客户名称")
    contact: str | None = Field(default=None, max_length=50, description="联系人")
    phone: str | None = Field(default=None, max_length=20, description="电话")
    address: str | None = Field(default=None, max_length=200, description="地址")
    note: str | None = Field(default=None, description="备注")
    status: bool | None = Field(default=None, description="状态")


class CustomerResponse(BaseModel):
    id: int
    customer_code: str | None = None
    name: str
    contact: str | None = None
    phone: str | None = None
    address: str | None = None
    note: str | None = None
    status: bool = True
    create_time: str | None = None

    class Config:
        from_attributes = True


class CustomerListResponse(BaseModel):
    success: bool = True
    customers: list[CustomerResponse]
    total: int = 0


class CustomerActionResponse(BaseModel):
    success: bool = True
    message: str


class CustomerToggleResponse(BaseModel):
    success: bool = True
    status: bool
    message: str
