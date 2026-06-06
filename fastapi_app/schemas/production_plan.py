"""
排产计划 Pydantic 数据模型

用于排产计划管理的请求/响应模型，包含库存对比和出货进度字段。
"""

from pydantic import BaseModel, Field

# ==================== 请求模型 ====================

class ProductionPlanCreate(BaseModel):
    """创建排产计划请求"""
    customer_name: str = Field(..., min_length=1, max_length=100, description="客户名称")
    product_name: str = Field(..., min_length=1, max_length=100, description="客户产品名称")
    barcode: str = Field(..., min_length=1, max_length=50, description="69码")
    quantity: int = Field(..., gt=0, le=999999, description="排产计划数量")
    plan_date: str = Field(..., description="计划日期 (YYYY-MM-DD)")
    remark: str | None = Field(None, max_length=500, description="备注")


class ProductionPlanUpdate(BaseModel):
    """更新排产计划请求"""
    customer_name: str | None = Field(None, min_length=1, max_length=100, description="客户名称")
    product_name: str | None = Field(None, min_length=1, max_length=100, description="客户产品名称")
    barcode: str | None = Field(None, min_length=1, max_length=50, description="69码")
    quantity: int | None = Field(None, gt=0, le=999999, description="排产计划数量")
    plan_date: str | None = Field(None, description="计划日期 (YYYY-MM-DD)")
    status: str | None = Field(None, description="状态: pending/confirmed/completed")
    remark: str | None = Field(None, max_length=500, description="备注")
    shipped_qty: int | None = Field(None, ge=0, description="已出货数量")


# ==================== 响应模型 ====================

class ProductionPlanItem(BaseModel):
    """排产计划条目（含库存对比+出货进度）"""
    id: int
    customer_name: str
    product_name: str
    barcode: str
    quantity: int
    inventory_qty: int = 0
    shipped_qty: int = 0
    remaining_qty: int = 0
    diff: int = 0
    stock_status: str = 'normal'
    shipment_status: str = 'pending'
    plan_date: str
    status: str
    remark: str | None = None
    upload_batch: str | None = None
    create_time: str | None = None
    update_time: str | None = None
    created_by: str | None = None


class CustomerSummaryItem(BaseModel):
    """客户汇总条目"""
    plan_qty: int = 0
    inventory_qty: int = 0
    shipped_qty: int = 0
    remaining_qty: int = 0
    warning_count: int = 0


class MonthlySummary(BaseModel):
    """当月汇总统计"""
    total_plan_qty: int = 0
    total_inventory_qty: int = 0
    total_shipped_qty: int = 0
    total_remaining_qty: int = 0
    total_diff: int = 0
    warning_count: int = 0
    customer_summary: dict = {}


class ProductionPlanListResponse(BaseModel):
    """排产计划列表响应"""
    success: bool = True
    plans: list[ProductionPlanItem] = []
    monthly_summary: MonthlySummary | None = None
    total: int = 0


class ProductionPlanActionResponse(BaseModel):
    """排产计划操作响应"""
    success: bool
    message: str


class BarcodeValidationResponse(BaseModel):
    """69码验证响应"""
    valid: bool
    product_name: str | None = None
    message: str | None = None


class TimelinePlanItem(BaseModel):
    id: int
    customer_name: str
    product_name: str
    barcode: str
    quantity: int
    inventory_qty: int = 0
    shipped_qty: int = 0
    remaining_qty: int = 0
    stock_status: str = 'normal'


class TimelineDayItem(BaseModel):
    date: str
    day: int
    plans: list[TimelinePlanItem] = []
    total_plan_qty: int = 0
    has_warning: bool = False


class TimelineResponse(BaseModel):
    year: int
    month: int
    days_in_month: int
    timeline: list[TimelineDayItem] = []
    customers: list[str] = []


class UploadExcelResponse(BaseModel):
    success: bool
    batch_id: str = ''
    total: int = 0
    success_count: int = 0
    error_count: int = 0
    errors: list[str] = []


class StagingPlanItem(BaseModel):
    id: int
    customer_name: str = ''
    product_name: str = ''
    barcode: str = ''
    quantity: int = 0
    plan_date: str = ''
    plan_month: str = ''
    remark: str = ''
    is_validated: bool = False
    validation_error: str = ''
    upload_batch_id: str = ''


class StagingListResponse(BaseModel):
    success: bool
    data: list[StagingPlanItem] = []
    total: int = 0


class StagingValidateResponse(BaseModel):
    success: bool
    total: int = 0
    valid_count: int = 0
    error_count: int = 0


class StagingConfirmResponse(BaseModel):
    success: bool
    created_count: int = 0
    skipped_count: int = 0
