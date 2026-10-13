"""订单批次号 Pydantic Schema"""
from __future__ import annotations

from pydantic import BaseModel, Field


class BatchNoUpdate(BaseModel):
    batch_no: str | None = Field(None, max_length=100, description='批次号')
    sync_same_batch: bool = Field(False, description='是否同步更新同批次其他订单')
    record_type: str = Field('order', pattern='^(order|stockin)$', description='记录类型：order/stockin')


class BatchAssignRequest(BaseModel):
    order_ids: list[int] = Field(..., min_length=1, max_length=500, description='订单ID列表')
    batch_no: str = Field(..., min_length=1, max_length=100, description='批次号')


class BatchCompleteRequest(BaseModel):
    batch_no: str = Field(..., min_length=1, max_length=100, description='批次号')


class OrderBatchItemSchema(BaseModel):
    id: int
    order_no: str
    customer: str
    order_date: str | None = None
    product_id: int
    product_name: str | None = None
    quantity: int
    status: str | None = None
    batch_no: str | None = None
    batch_completed_at: str | None = None
    is_locked: bool | None = None

    model_config = {'from_attributes': True}


class OrderBatchListResponse(BaseModel):
    success: bool = True
    data: list[OrderBatchItemSchema] = []
    total: int = 0
    page: int = 1
    per_page: int = 50


class BatchNoUpdateResponse(BaseModel):
    success: bool = True
    message: str = ''
    updated_count: int = 0


class BatchAssignResponse(BaseModel):
    success: bool = True
    message: str = ''
    updated_count: int = 0


class BatchCompleteResponse(BaseModel):
    success: bool = True
    message: str = ''
    completed_count: int = 0
    completed_stockins: int = 0
    failed_orders: list[dict] = []


class BatchQueryItem(BaseModel):
    id: int
    order_no: str
    customer: str
    order_date: str | None = None
    product_id: int
    product_name: str | None = None
    product_barcode: str | None = None
    quantity: int
    deducted_qty: int = 0
    shipped_qty: int = 0
    status: str | None = None
    computed_status: str | None = None
    batch_no: str | None = None
    batch_completed_at: str | None = None
    is_locked: bool | None = None
    record_type: str | None = None

    model_config = {'from_attributes': True}


class BatchQueryListResponse(BaseModel):
    success: bool = True
    data: list[BatchQueryItem] = []
    total: int = 0
    page: int = 1
    per_page: int = 50


class WhitelistResponse(BaseModel):
    customers: list[str] = []
