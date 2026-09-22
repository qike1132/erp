"""
采购中心 Pydantic 请求模型
"""


from pydantic import BaseModel, Field

# BOM 保存 DTO 已收口到 canonical 位置 fastapi_app/schemas/purchase_center.py（见架构 §9.3）；
# 此处 re-export 以保持既有导入路径 `...endpoints.purchase_center.schemas` 可用。
from fastapi_app.schemas.purchase_center import (  # noqa: F401
    AccessoryItem,
    BomSaveRequest,
    FabricItem,
    FillingItem,
    PackagingItem,
    RoleItem,
)


class OrderIdsRequest(BaseModel):
    """订单ID列表请求"""
    ids: list[int] = Field(..., min_length=1, max_length=500, description="订单ID列表")

class OrderIdRequest(BaseModel):
    """单个订单ID请求

    `spare_rate`：下单完成时携带的损耗率（千分之几）；`None` 表示不覆盖该采购单已存值。
    """
    order_id: int = Field(..., description="订单ID")
    spare_rate: float | None = Field(None, description="损耗率(千分之几)，None=不覆盖已存值")

class OrderIdsAltRequest(BaseModel):
    """订单ID列表请求(备用字段名)"""
    order_ids: list[int] = Field(..., min_length=1, max_length=500, description="订单ID列表")

class CompositeIdsRequest(BaseModel):
    """复合ID列表请求，格式为 'order:5' 或 'stockin:3'"""
    composite_ids: list[str] = Field(..., min_length=1, max_length=500, description="复合ID列表")

class CustomerSyncRequest(BaseModel):
    """客户同步请求"""
    customer_ids: list[int] | None = Field(None, max_length=500, description="客户ID列表，为空则全量同步")
    force: bool = False

class CustomerBatchRequest(BaseModel):
    """客户批量查询请求"""
    ids: list[int] = Field(..., min_length=1, max_length=500, description="客户ID列表")

class BomCopyRequest(BaseModel):
    """复制BOM请求"""
    source_product_id: int = Field(..., description="源产品ID")
    overwrite: bool = False
    role_id: int | None = Field(None, description="目标角色ID；为空则按源产品结构复制（默认BOM+重建角色）")
    role_name: str | None = Field(None, max_length=50, description="目标角色名称；role_id 为空时按名称查找或新建角色")

class MaterialOrderItem(BaseModel):
    """物料计算单个订单项"""
    product_id: int = Field(..., gt=0, description="产品ID")
    quantity: float = Field(..., gt=0, le=1_000_000, description="订单数量，必须大于0且不超过100万")

class CalculateMaterialRequest(BaseModel):
    """物料计算请求"""
    orders: list[MaterialOrderItem] = Field(..., min_length=1, max_length=200, description="订单物料列表，上限200（与产品选择上限对齐）")

class PurchaseOrderMaterialItem(BaseModel):
    """采购订单物料明细。

    允许额外字段以兼容前端未声明的扩展字段。
    """
    model_config = {"extra": "allow"}
    material_name: str = ''
    material_code: str = ''
    specification: str = ''
    unit: str = ''
    unit_price: float = 0
    quantity: float = 0
    supplier_id: int | None = None
    supplier_name: str = ''
    customer_name: str = ''
    category: str = ''
    remark: str = ''


class PurchaseOrderCreateRequest(BaseModel):
    """创建采购订单请求"""
    materials: list[PurchaseOrderMaterialItem] = Field(..., min_length=1, description="物料列表")
    customer_id: int | None = None
    customer_name: str = ''
    customer_code: str = ''
    remark: str = ''
    unprocessed_order_id: int | None = None

class PurchaseOrderUpdateRequest(BaseModel):
    """更新采购订单请求"""
    status: str | None = None
    remark: str | None = None
    supplier_name: str | None = None
    customer_name: str | None = None
    modify_reason: str = ''

class BatchCompleteRequest(BaseModel):
    """批量完成订单请求

    `spare_rate`：批量确认时对所有涉及采购单统一覆盖的损耗率（千分之几）；`None` 表示不覆盖。
    """
    ids: list[int] = Field(..., min_length=1, max_length=500, description="订单ID列表")
    spare_rate: float | None = Field(None, description="损耗率(千分之几)，None=不覆盖已存值")

class OneClickGenerateRequest(BaseModel):
    """一键生成采购订单请求"""
    composite_ids: list[str] = Field(..., min_length=1, max_length=500, description="复合ID列表，格式为 'order:5' 或 'stockin:3'")

class ExportCompletedRequest(BaseModel):
    """导出已完成订单请求"""
    order_no: str | None = None
    customer_name: str | None = None
    product_name: str | None = None
    start_date: str | None = None
    end_date: str | None = None

class FactorySummaryEditItem(BaseModel):
    """工厂订单汇总编辑项。

    允许额外字段以兼容前端未声明的扩展字段。
    """
    model_config = {"extra": "allow"}
    item_ids: list[int] = []
    quantity: float | None = None


class FactorySummarySaveRequest(BaseModel):
    """保存工厂订单编辑请求。

    - `edits` 允许为空：损耗率输入框在非编辑态即可交互，用户可能「只改了损耗率、
      没有任何布料改动」，此时仅靠 `order_ids` + `spare_rate` 也要能落库。
    - `order_ids`：本次汇总涉及的采购单 ID 列表，用于在无编辑项时定位要写入备品的采购单。
    - `spare_rate`：对该次涉及的所有采购单覆盖写的损耗率（千分之几）；`None` 表示不覆盖。
    """
    edits: list[FactorySummaryEditItem] = Field(default_factory=list, description="编辑列表（可为空）")
    order_ids: list[int] = Field(default_factory=list, description="本次涉及的采购单ID列表")
    spare_rate: float | None = Field(None, description="损耗率(千分之几)，None=不覆盖已存值")

class SummaryPrintRequest(BaseModel):
    """汇总打印请求"""
    ids: list[int] = Field(..., min_length=1, max_length=500, description="订单ID列表")
    format: str = 'print'

class QueryCondition(BaseModel):
    """查询条件（动态结构，允许额外字段）。

    查询条件为前端动态构造的过滤参数，结构不固定，因此允许任意额外字段。
    """
    model_config = {"extra": "allow"}


class SaveQueryRequest(BaseModel):
    """保存查询请求"""
    name: str = Field(..., min_length=1, description="查询名称")
    query_type: str = 'purchase_order'
    conditions: QueryCondition = Field(..., description="查询条件")
