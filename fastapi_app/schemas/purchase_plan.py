"""
采购计划 Pydantic Schema（重构版）

主从表结构：PurchasePlan（主表）+ PurchasePlanDetail（明细表）
"""

from pydantic import BaseModel, Field

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
    status: str | None = Field(None, description="状态: pending/confirmed/completed/cancelled")
    remark: str | None = Field(None, description="备注")


class PurchasePlanDetailUpdate(BaseModel):
    """更新明细"""
    quantity: int | None = Field(None, gt=0, le=999999, description="计划数量")
    plan_date: str | None = Field(None, description="计划日期 YYYY-MM-DD")
    remark: str | None = Field(None, description="备注")


class AddDetailsRequest(BaseModel):
    """追加明细请求"""
    details: list[PlanDetailInput] = Field(..., min_length=1, description="新增明细列表")


class ConfirmStagingRequest(BaseModel):
    """确认暂存请求"""
    batch_id: str = Field('', description="批次ID")
    selected_ids: list[int] | None = Field(None, description="仅确认选中的ID列表")


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
    updated_at: str | None = None


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
    # FIFO 出货量统计降级标记（服务异常时为 True，前端可提示数据可能不完整）
    fifo_degraded: bool = False


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
    # FIFO 出货量统计降级标记（服务异常时为 True，前端可提示数据可能不完整）
    fifo_degraded: bool = False


class PurchasePlanActionResponse(BaseModel):
    """操作响应"""
    success: bool
    message: str = ''


class BarcodeValidationResponse(BaseModel):
    """69码验证响应"""
    valid: bool
    product_name: str | None = None
    product_id: int | None = None
    message: str = ''


class PlanListResponse(BaseModel):
    """计划列表响应"""
    plans: list[PurchasePlanItem] = []
    total: int = 0
    # FIFO 出货量统计降级标记（服务异常时为 True，前端可提示数据可能不完整）
    fifo_degraded: bool = False


class MonthlyCalendarResponse(BaseModel):
    """月度日历响应"""
    year: int
    month: int
    days_in_month: int
    plans_by_date: dict[str, list] = {}
    customers: list[dict] = []
    # FIFO 分配降级标记（服务异常时为 True，前端可提示数据可能不完整）。
    # 本响应自 2026-09-29 起改为生产量分配（见设计稿 §7），不再是出货口径。
    fifo_degraded: bool = False


class MonthlyAggregatedResponse(BaseModel):
    """月度聚合响应（6.9：后端完成聚合，不传输全量明细）"""
    year: int
    month: int
    days_in_month: int
    rows: list[dict] = []
    sku_summary: list[dict] = []
    sku_date_index: dict[str, list] = {}
    customers: list[dict] = []
    customer_totals: dict = {}
    fifo_degraded: bool = False


class DayDetailsResponse(BaseModel):
    """指定日期明细响应（6.9：按需加载当日明细；produced_pct 为按每日生产记录计算的生产达标率）"""
    date: str
    weekday: str = ''
    plans: list[dict] = []
    by_customer: dict[str, list] = {}
    produced_pct: float = 0.0
    fifo_degraded: bool = False


class CreatePlanResponse(BaseModel):
    success: bool
    data: dict = {}


class ShipmentRecordItem(BaseModel):
    stockout_id: int
    shipment_no: str = ''
    customer_name: str = ''
    product_name: str = ''
    quantity: int = 0
    shipment_date: str = ''
    source_type: str = 'stockout'
    note: str = ''


class ShipmentRecordsResponse(BaseModel):
    records: list[ShipmentRecordItem] = []


class ShipmentSyncResponse(BaseModel):
    success: bool
    synced_count: int = 0


class PurchasePlanUploadExcelResponse(BaseModel):
    success: bool
    batch_id: str = ''
    total: int = 0
    success_count: int = 0
    error_count: int = 0
    errors: list[str] = []
    is_async: bool = False
    detected_month: str | None = None


class PurchasePlanStagingItem(BaseModel):
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


class PurchasePlanStagingListResponse(BaseModel):
    success: bool
    data: list[PurchasePlanStagingItem] = []
    total: int = 0


class StagingErrorItem(BaseModel):
    """暂存校验失败明细，供前端展示与导出错误清单"""
    seq: int = Field(0, description='导入批次内的行序号（1 起），非 Excel 物理行号')
    customer_name: str = ''
    product_name: str = ''
    barcode: str = ''
    quantity: int = 0
    plan_date: str = ''
    message: str = Field('', description='失败原因，上传阶段的错误自带「第N行」物理行号')


class PurchasePlanStagingValidateResponse(BaseModel):
    success: bool
    total: int = 0
    valid_count: int = 0
    error_count: int = 0
    errors: list[StagingErrorItem] = []


class PurchasePlanStagingConfirmResponse(BaseModel):
    success: bool
    created_plans: list[dict] = []
    created_count: int = 0
    skipped_count: int = 0
