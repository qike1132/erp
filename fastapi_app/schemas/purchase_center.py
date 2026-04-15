"""
采购中心 Pydantic 请求/响应模型
"""

from datetime import datetime
from decimal import Decimal
from typing import Any, Optional

from pydantic import BaseModel, Field


# ============================================================
# 产品/BOM 相关
# ============================================================

class ProductBomInfo(BaseModel):
    filling_count: int = 0
    fabric_count: int = 0
    accessory_count: int = 0
    packaging_count: int = 0


class ProductListItem(BaseModel):
    id: int
    name: str
    barcode: Optional[str] = None
    has_bom: bool = False
    bom_info: Optional[ProductBomInfo] = None
    current_stock: int = 0


class ProductListResponse(BaseModel):
    success: bool = True
    products: list[ProductListItem] = []
    total: int = 0
    pages: int = 0
    current_page: int = 1


class ProductBomResponse(BaseModel):
    success: bool = True
    product: Optional[dict] = None
    materials: list[dict] = []


class ProductStatisticsResponse(BaseModel):
    success: bool = True
    statistics: Optional[dict] = None


class SearchSuggestionItem(BaseModel):
    id: int
    name: str
    barcode: Optional[str] = None
    has_bom: Optional[bool] = None


class SearchSuggestionResponse(BaseModel):
    success: bool = True
    suggestions: list[SearchSuggestionItem] = []


class BomSaveRequest(BaseModel):
    filling: Optional[dict] = None
    fabrics: list[dict] = []
    accessories: list[dict] = []
    packagings: list[dict] = []


class MaterialCalculateRequest(BaseModel):
    orders: list[dict]


class MaterialCalculateResponse(BaseModel):
    success: bool = True
    result: Optional[dict] = None
    total_categories: Optional[dict] = None
    message: Optional[str] = None


# ============================================================
# 供应商相关
# ============================================================

class SupplierCreate(BaseModel):
    name: str
    contact_person: Optional[str] = ''
    phone: Optional[str] = ''
    address: Optional[str] = ''
    remark: Optional[str] = ''


class SupplierResponse(BaseModel):
    id: int
    name: str
    contact_person: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None


class SupplierListResponse(BaseModel):
    success: bool = True
    suppliers: list[dict] = []


class SupplierMaterialResponse(BaseModel):
    success: bool = True
    materials: list[dict] = []


# ============================================================
# 客户相关
# ============================================================

class CustomerSyncRequest(BaseModel):
    customer_ids: Optional[list[int]] = None
    force: bool = False


class CustomerBatchRequest(BaseModel):
    ids: list[int]


class CustomerStatisticsResponse(BaseModel):
    success: bool = True
    statistics: Optional[dict] = None


# ============================================================
# 采购订单相关
# ============================================================

class PurchaseOrderCreate(BaseModel):
    materials: list[dict]
    customer_id: Optional[int] = None
    customer_name: Optional[str] = ''
    customer_code: Optional[str] = ''
    remark: Optional[str] = ''
    unprocessed_order_id: Optional[int] = None


class PurchaseOrderUpdate(BaseModel):
    status: Optional[str] = None
    remark: Optional[str] = None
    supplier_name: Optional[str] = None
    customer_name: Optional[str] = None
    modify_reason: Optional[str] = ''


class PurchaseOrderComplete(BaseModel):
    order_id: int


class PurchaseOrderBatchComplete(BaseModel):
    ids: list[int]


class PurchaseOrderListResponse(BaseModel):
    success: bool = True
    orders: list[dict] = []
    total: int = 0
    pages: int = 0
    current_page: int = 1


class PurchaseOrderDetailResponse(BaseModel):
    success: bool = True
    order: Optional[dict] = None


class PurchaseOrderActionResponse(BaseModel):
    success: bool = True
    message: Optional[str] = None
    orders: Optional[list[dict]] = None
    order: Optional[dict] = None


class OneClickGenerateRequest(BaseModel):
    order_ids: list[int]


class CompletedOrdersExportRequest(BaseModel):
    order_no: Optional[str] = ''
    customer_name: Optional[str] = ''
    product_name: Optional[str] = ''
    start_date: Optional[str] = ''
    end_date: Optional[str] = ''


class BatchPrintRequest(BaseModel):
    ids: list[int]


# ============================================================
# 工厂内部采购订单
# ============================================================

class FactorySummaryRequest(BaseModel):
    ids: list[int]


class FactorySummarySaveRequest(BaseModel):
    edits: list[dict]


class GenerateFactoryOrderRequest(BaseModel):
    ids: list[int]


class GenerateSupplierOrderRequest(BaseModel):
    supplier_id: int


# ============================================================
# 供应商汇总
# ============================================================

class SupplierSummaryItem(BaseModel):
    material_name: str
    specification: Optional[str] = ""
    unit: Optional[str] = ""
    quantity: float
    material_category: Optional[str] = ""
    order_count: int


class SupplierSummary(BaseModel):
    supplier_name: str
    supplier_id: Optional[int] = None
    items: list[SupplierSummaryItem]
    orders: list[str]
    order_count: int


class SupplierSummaryRequest(BaseModel):
    ids: list[int]
    format: Optional[str] = "print"


class SupplierSummaryResponse(BaseModel):
    success: bool = True
    suppliers: Optional[list[SupplierSummary]] = None
    supplier_count: Optional[int] = None
    order_count: Optional[int] = None
    html: Optional[str] = None
    message: Optional[str] = None


class SupplierSummaryExportRequest(BaseModel):
    ids: list[int]


class SupplierOrderSummaryRequest(BaseModel):
    ids: list[int]


class SupplierOrderSummaryResponse(BaseModel):
    success: bool = True
    materials: Optional[list[dict]] = None
    order_count: Optional[int] = None
    material_count: Optional[int] = None
    message: Optional[str] = None


# ============================================================
# 汇总打印
# ============================================================

class SummaryPrintRequest(BaseModel):
    ids: list[int]
    format: Optional[str] = "print"


# ============================================================
# 修改历史
# ============================================================

class ModificationLogResponse(BaseModel):
    success: bool = True
    logs: list[dict] = []
    total: int = 0


# ============================================================
# 保存查询
# ============================================================

class SavedQueryCreate(BaseModel):
    name: str
    query_type: Optional[str] = 'purchase_order'
    conditions: Any


class SavedQueryResponse(BaseModel):
    success: bool = True
    queries: list[dict] = []
    query: Optional[dict] = None


# ============================================================
# 状态日志
# ============================================================

class StatusLogResponse(BaseModel):
    success: bool = True
    logs: list[dict] = []
    total: int = 0


# ============================================================
# 未处理订单
# ============================================================

class UnprocessedOrdersResponse(BaseModel):
    success: bool = True
    orders: list[dict] = []
    total: int = 0
    latest_sync_time: Optional[str] = None


# ============================================================
# 智能联想 & 快捷筛选
# ============================================================

class SuggestionResponse(BaseModel):
    success: bool = True
    suggestions: list[dict] = []


class QuickFilterResponse(BaseModel):
    success: bool = True
    quick_filters: list[dict] = []


# ============================================================
# 通用操作响应
# ============================================================

class ActionResponse(BaseModel):
    success: bool = True
    message: Optional[str] = None


class CacheClearResponse(BaseModel):
    success: bool = True
    message: str = ''


class CategoriesResponse(BaseModel):
    success: bool = True
    categories: dict = {}
