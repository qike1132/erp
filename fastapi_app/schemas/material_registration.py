"""来料登记相关 Schema"""
from pydantic import BaseModel, Field


class MaterialRegistrationItemCreate(BaseModel):
    order_item_id: int | None = None
    material_code: str | None = Field(default=None, max_length=50)
    material_name: str = Field(..., max_length=100)
    specification: str | None = Field(default=None, max_length=100)
    unit: str | None = Field(default=None, max_length=20)
    ordered_quantity: float = Field(..., ge=0)
    received_quantity: float = Field(0, ge=0)
    material_category: str | None = Field(default=None, max_length=20)
    remark: str | None = None


class MaterialRegistrationCreate(BaseModel):
    purchase_order_id: int = Field(..., description="采购订单ID")
    remark: str | None = None
    items: list[MaterialRegistrationItemCreate] = Field(default_factory=list)


class MaterialRegistrationUpdate(BaseModel):
    status: str | None = None
    remark: str | None = None
    items: list[dict] | None = None  # partial update for items


class ReceiveMaterialRequest(BaseModel):
    received_quantity: float = Field(..., ge=0, description="收货数量")
    remark: str | None = None


class RegistrationListResponse(BaseModel):
    success: bool = True
    registrations: list[dict]
    total: int
    pages: int
    current_page: int
    stats: dict = {}


class RegistrationDetailResponse(BaseModel):
    success: bool = True
    registration: dict


class StatsOverviewResponse(BaseModel):
    success: bool = True
    overview: dict = {}


class TrendResponse(BaseModel):
    success: bool = True
    trend: list[dict] = []


class ActionResponse(BaseModel):
    success: bool = True
    message: str
