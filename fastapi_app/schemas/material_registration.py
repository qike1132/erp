"""来料登记相关 Schema"""
from typing import Any

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
    received_quantity: float = Field(..., gt=0, description="收货数量")
    remark: str | None = None


class RegistrationListResponse(BaseModel):
    success: bool = True
    registrations: list[dict]
    total: int
    pages: int
    current_page: int


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


class AvailablePurchaseOrdersResponse(BaseModel):
    success: bool = True
    orders: list[dict[str, Any]] = []


class PurchaseOrderItemsResponse(BaseModel):
    success: bool = True
    items: list[dict[str, Any]] = []


class ExportRegistrationsResponse(BaseModel):
    success: bool = True
    html: str = ""


class ExportRequest(BaseModel):
    """导出来料登记的筛选参数（POST body）"""
    order_no: str = ''
    supplier: str = ''
    customer_name: str = ''
    material_category: str = ''
    start_date: str = ''
    end_date: str = ''


class RegistrationHistoryResponse(BaseModel):
    success: bool = True
    registrations: list[dict[str, Any]] = []
    total: int = 0
    pages: int = 0
    current_page: int = 1


class SuggestionsResponse(BaseModel):
    success: bool = True
    suggestions: list[str] = []


class StatsDistributionResponse(BaseModel):
    success: bool = True
    distribution: list[dict[str, Any]] = []
