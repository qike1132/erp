"""皮套管理 Schema 定义

主件与配件同为 SKU；出入库统一为一张流水（direction 区分方向）。
"""
from pydantic import BaseModel, Field, field_validator

from utils.sanitizer import sanitize_url

_VALID_DIRECTIONS = ('in', 'out')


# ===== SKU 主档 =====
def _sanitize_image_url(v: str | None) -> str | None:
    """图片 URL 的统一出站校验：拒绝不安全协议（`javascript:` / `data:` 等）。

    抽成共用函数是为了 Create / Update **同口径** —— 原先只有 Create 挂了校验器，
    Update 可以直接把 `javascript:` 存进库（2026-10-02 第二轮审计）。
    """
    if v:
        sanitized = sanitize_url(v)
        if not sanitized:
            raise ValueError('图片URL包含不安全的协议')
        return sanitized
    return v


class CaseItemCreate(BaseModel):
    name: str | None = None
    barcode: str | None = None
    image: str | None = None
    unit: str | None = None
    product_id: int | None = None
    parent_id: int | None = None
    qty_per_set: int = Field(1, ge=1, le=9999999)
    initial_stock: int = Field(0, ge=0)

    @field_validator('image')
    @classmethod
    def sanitize_image_url(cls, v: str | None) -> str | None:
        return _sanitize_image_url(v)


class CaseItemUpdate(BaseModel):
    name: str | None = None
    barcode: str | None = None
    image: str | None = None
    unit: str | None = None
    parent_id: int | None = None
    qty_per_set: int | None = Field(None, ge=1, le=9999999)

    @field_validator('image')
    @classmethod
    def sanitize_image_url(cls, v: str | None) -> str | None:
        # 与 Create 同口径 —— 原先 Update 缺这个校验器，可绕过协议白名单
        return _sanitize_image_url(v)


class CaseItemOut(BaseModel):
    id: int
    name: str = ''
    barcode: str = ''
    image: str = ''
    unit: str = ''
    product_id: int | None = None
    parent_id: int | None = None
    qty_per_set: int = 1
    initial_stock: int = 0
    current_stock: int = 0
    total_in: int = 0
    total_out: int = 0


class CaseItemListResponse(BaseModel):
    items: list[CaseItemOut] = []
    total: int = 0
    page: int = 1
    per_page: int = 50
    pages: int = 0


class CaseSearchItem(BaseModel):
    id: int
    name: str = ''
    barcode: str = ''
    current_stock: int = 0
    parent_id: int | None = None


# ===== 产品列表（皮套设置：按有配件/无配件选择） =====
class CaseProductItem(BaseModel):
    id: int
    name: str = ''
    barcode: str = ''
    part_count: int = 0
    has_parts: bool = False


class CaseProductListResponse(BaseModel):
    products: list[CaseProductItem] = []
    total: int = 0
    page: int = 1
    per_page: int = 200
    pages: int = 0


class CaseItemCreateResponse(BaseModel):
    success: bool
    message: str = ''
    id: int = 0


# ===== 出入库流水 =====
class CaseMovementCreate(BaseModel):
    case_id: int
    direction: str
    quantity: int = Field(..., gt=0, le=9999999)
    movement_date: str = ''
    customer: str = ''
    note: str = ''

    @field_validator('direction')
    @classmethod
    def _check_direction(cls, v: str) -> str:
        if v not in _VALID_DIRECTIONS:
            raise ValueError("方向必须是 in 或 out")
        return v


class CaseMovementUpdate(BaseModel):
    # gt=0：负数会让数量调节绕过负库存守卫、并抬高库存
    quantity: int | None = Field(None, gt=0, le=9999999)
    movement_date: str | None = None
    customer: str | None = None
    note: str | None = None


class CaseMovementOut(BaseModel):
    id: int
    case_id: int = 0
    case_name: str = ''
    case_barcode: str = ''
    direction: str = ''
    movement_no: str = ''
    quantity: int = 0
    customer: str = ''
    movement_date: str = ''
    note: str = ''
    create_time: str = ''


class CaseMovementListResponse(BaseModel):
    movements: list[CaseMovementOut] = []
    total: int = 0
    pages: int = 0
    current_page: int = 1


class CaseMovementCreateResponse(BaseModel):
    success: bool
    movement_no: str = ''
    id: int = 0


class BatchCaseMovementRequest(BaseModel):
    movements: list[dict]


class CaseBatchFailedItem(BaseModel):
    index: int
    error: str = ''


class CaseBatchMovementResponse(BaseModel):
    success: bool
    results: list[dict] = []
    failed: list[CaseBatchFailedItem] = []


class CaseActionResponse(BaseModel):
    success: bool
    message: str = ''


# ===== 库存（主件 + 配件分组） =====
class CaseInventoryStats(BaseModel):
    total_items: int = 0
    total_stock: int = 0
    total_in: int = 0
    total_out: int = 0


class CaseInventoryNode(CaseItemOut):
    children: list[CaseItemOut] = []


class CaseInventoryResponse(BaseModel):
    inventory: list[CaseInventoryNode] = []
    total: int = 0
    page: int = 1
    per_page: int = 50
    pages: int = 0
    stats: CaseInventoryStats | None = None


# ===== 按产品取皮套树（主件 + 配件） =====
class CaseForProductRequest(BaseModel):
    product_id: int


class CaseTreeResponse(BaseModel):
    main: CaseItemOut
    parts: list[CaseItemOut] = []
