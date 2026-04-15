"""
采购计划 Pydantic Schema（重构版）

主从表结构：PurchasePlan（主表）+ PurchasePlanDetail（明细表）
"""
from pydantic import BaseModel, Field
from typing import Optional


# ==================== 请求模型 ====================

class PlanDetailInput(BaseModel):
    """明细输入"""
    product_id: int = Field(..., description="产品ID")
    product_name: str = Field(..., description="产品名称")
    barcode: str = Field(..., description="69码")
    quantity: int = Field(..., gt=0, le=999999, description="计划数量")
    plan_date: str = Field(..., description="计划日期 YYYY-MM-DD")
    remark: str = Field('', description="备注")


class PurchasePlanCreate(BaseModel):
    """创建采购计划"""
    customer_id: int = Field(..., description="客户ID")
    customer_name: str = Field(..., description="客户名称")
    plan_month: str = Field(..., description="计划月份 YYYY-MM")
    details: list[PlanDetailInput] = Field(..., min_length=1, description="计划明细列表")
    remark: str = Field('', description="备注")


class PurchasePlanUpdate(BaseModel):
    """更新采购计划主单"""
    status: Optional[str] = Field(None, description="状态: pending/confirmed/completed/cancelled")
    remark: Optional[str] = Field(None, description="备注")


class PurchasePlanDetailUpdate(BaseModel):
    """更新明细"""
    quantity: Optional[int] = Field(None, gt=0, le=999999, description="计划数量")
    plan_date: Optional[str] = Field(None, description="计划日期 YYYY-MM-DD")
    remark: Optional[str] = Field(None, description="备注")


class AddDetailsRequest(BaseModel):
    """追加明细请求"""
    details: list[PlanDetailInput] = Field(..., min_length=1, description="新增明细列表")


class ConfirmStagingRequest(BaseModel):
    """确认暂存请求"""
    batch_id: str = Field('', description="批次ID")
    selected_ids: Optional[list[int]] = Field(None, description="仅确认选中的ID列表")


class SyncShipmentRequest(BaseModel):
    """出货同步请求"""
    year: int = Field(..., description="年份")
    month: int = Field(..., ge=1, le=12, description="月份")


# ==================== 响应模型 ====================

class PurchasePlanItem(BaseModel):
    """采购计划主单列表项"""
    id: int
    plan_no: str
    plan_month: str
    customer_id: int
    customer_name: str
    status: str
    remark: str = ''
    upload_batch: str = ''
    created_by: str = ''
    create_time: str = ''
    update_time: str = ''
    detail_count: int = 0
    total_quantity: int = 0
    total_shipped: int = 0
    total_remaining: int = 0


class PurchasePlanDetailItem(BaseModel):
    """明细列表项（含库存对比+出货进度）"""
    id: int
    plan_id: int
    product_id: int
    product_name: str
    barcode: str
    plan_date: str
    quantity: int
    shipped_qty: int = 0
    remaining_qty: int = 0
    remark: str = ''
    inventory_qty: int = 0
    stock_status: str = 'sufficient'
    shipment_status: str = 'pending'


class PurchasePlanDetailResponse(BaseModel):
    """主单+明细响应"""
    plan: dict
    details: list[PurchasePlanDetailItem]


class CustomerSummaryItem(BaseModel):
    """客户汇总项"""
    customer_id: int
    customer_name: str
    plan_qty: int = 0
    inventory_qty: int = 0
    shipped_qty: int = 0
    remaining_qty: int = 0
    warning_count: int = 0


class CustomerSummaryResponse(BaseModel):
    """客户汇总响应"""
    customers: list[CustomerSummaryItem] = []
    total_plan_qty: int = 0
    total_inventory_qty: int = 0
    total_shipped_qty: int = 0
    total_remaining_qty: int = 0
    warning_count: int = 0


class InventoryCompareItem(BaseModel):
    """库存对比项"""
    detail_id: int
    product_id: int
    product_name: str
    barcode: str
    customer_name: str
    plan_qty: int
    inventory_qty: int = 0
    diff: int = 0
    stock_status: str = 'sufficient'


class InventoryCompareResponse(BaseModel):
    """库存对比响应"""
    details: list[InventoryCompareItem] = []


class ShipmentProgressItem(BaseModel):
    """出货进度项"""
    detail_id: int
    product_name: str
    barcode: str
    plan_qty: int
    shipped_qty: int = 0
    remaining_qty: int = 0
    percent: float = 0.0
    shipment_status: str = 'pending'


class ShipmentProgressResponse(BaseModel):
    """出货进度响应"""
    details: list[ShipmentProgressItem] = []


class PurchasePlanActionResponse(BaseModel):
    """操作响应"""
    success: bool
    message: str = ''


class BarcodeValidationResponse(BaseModel):
    """69码验证响应"""
    valid: bool
    product_name: Optional[str] = None
    product_id: Optional[int] = None
    message: str = ''


class PlanListResponse(BaseModel):
    """计划列表响应"""
    plans: list[PurchasePlanItem] = []
    total: int = 0


class MonthlyCalendarResponse(BaseModel):
    """月度日历响应"""
    year: int
    month: int
    days_in_month: int
    plans_by_date: dict = {}
    customers: list = []
