"""
排产计划 Pydantic 数据模型

用于排产计划管理的请求/响应模型，包含库存对比和出货进度字段。
"""
from pydantic import BaseModel, Field
from typing import Optional, List


# ==================== 请求模型 ====================

class ProductionPlanCreate(BaseModel):
    """创建排产计划请求"""
    customer_name: str = Field(..., min_length=1, max_length=100, description="客户名称")
    product_name: str = Field(..., min_length=1, max_length=100, description="客户产品名称")
    barcode: str = Field(..., min_length=1, max_length=50, description="69码")
    quantity: int = Field(..., gt=0, le=999999, description="排产计划数量")
    plan_date: str = Field(..., description="计划日期 (YYYY-MM-DD)")
    remark: Optional[str] = Field(None, max_length=500, description="备注")


class ProductionPlanUpdate(BaseModel):
    """更新排产计划请求"""
    customer_name: Optional[str] = Field(None, min_length=1, max_length=100, description="客户名称")
    product_name: Optional[str] = Field(None, min_length=1, max_length=100, description="客户产品名称")
    barcode: Optional[str] = Field(None, min_length=1, max_length=50, description="69码")
    quantity: Optional[int] = Field(None, gt=0, le=999999, description="排产计划数量")
    plan_date: Optional[str] = Field(None, description="计划日期 (YYYY-MM-DD)")
    status: Optional[str] = Field(None, description="状态: pending/confirmed/completed")
    remark: Optional[str] = Field(None, max_length=500, description="备注")
    shipped_qty: Optional[int] = Field(None, ge=0, description="已出货数量")


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
    remark: Optional[str] = None
    upload_batch: Optional[str] = None
    create_time: Optional[str] = None
    update_time: Optional[str] = None
    created_by: Optional[str] = None


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
    plans: List[ProductionPlanItem] = []
    monthly_summary: Optional[MonthlySummary] = None
    total: int = 0


class ProductionPlanActionResponse(BaseModel):
    """排产计划操作响应"""
    success: bool
    message: str


class BarcodeValidationResponse(BaseModel):
    """69码验证响应"""
    valid: bool
    product_name: Optional[str] = None
    message: Optional[str] = None
