"""
外发模块 Pydantic 数据模型

用于 SKU 工序预设（outsource_process_type）与订单外发工序
（order_outsource_process）的请求/响应模型。
"""
from datetime import datetime

from pydantic import BaseModel, Field


class ProcessTypeCreate(BaseModel):
    """SKU 工序预设创建请求"""
    product_id: int = Field(..., gt=0, description="产品(SKU)ID")
    process_type: str = Field(..., min_length=1, max_length=50, description="工序类型：电绣/转印/配件等")
    sort_order: int = Field(0, ge=0, le=9999, description="工序顺序")
    remark: str | None = Field(None, max_length=200, description="备注")


class ProcessTypeBatchCreate(BaseModel):
    """为一个 SKU 批量添加多个工序预设（自由输入工序名称）"""
    product_id: int = Field(..., gt=0, description="产品(SKU)ID")
    process_types: list[str] = Field(..., min_length=1, max_length=50, description="工序名称列表（去重后按顺序生成）")


class ProcessTypeUpdate(BaseModel):
    """SKU 工序预设更新请求（部分更新）"""
    process_type: str | None = Field(None, min_length=1, max_length=50, description="工序类型")
    sort_order: int | None = Field(None, ge=0, le=9999, description="工序顺序")
    is_active: bool | None = Field(None, description="是否启用")
    remark: str | None = Field(None, max_length=200, description="备注")


class ProcessTypeResponse(BaseModel):
    """SKU 工序预设响应"""
    id: int
    product_id: int
    product_name: str | None = None
    product_barcode: str | None = None
    factory: str | None = None
    process_type: str
    sort_order: int = 0
    is_active: bool = True
    remark: str | None = None
    created_by: str | None = None
    create_time: datetime | None = None
    update_time: datetime | None = None


class ProcessTypeListResponse(BaseModel):
    """SKU 工序预设列表响应"""
    success: bool = True
    data: list[dict]
    total: int = 0


class OrderProcessUpdate(BaseModel):
    """订单外发工序更新请求（部分更新：计划时间/备注/工序类型）"""
    process_type: str | None = Field(None, min_length=1, max_length=50, description="工序类型")
    sort_order: int | None = Field(None, ge=0, le=9999, description="工序顺序")
    planned_start_time: datetime | None = Field(None, description="计划开始时间")
    planned_end_time: datetime | None = Field(None, description="计划完成时间")
    remark: str | None = Field(None, max_length=500, description="备注")


class OrderProcessShip(BaseModel):
    """订单外发工序发货请求：录入发货数量（每道工序独立）。"""
    shipped_quantity: int = Field(..., gt=0, le=9999999, description="发货数量")


class OrderProcessReceive(BaseModel):
    """订单外发工序收货请求：收货数量可选，缺省等于发货数量。"""
    received_quantity: int | None = Field(None, gt=0, le=9999999, description="收货数量")


class OrderProcessShipItem(BaseModel):
    """批量发货单条明细"""
    process_id: int = Field(..., gt=0, description="工序ID")
    quantity: int = Field(..., gt=0, le=9999999, description="本批发货数量")


class OrderProcessReceiveItem(BaseModel):
    """批量收货单条明细"""
    process_id: int = Field(..., gt=0, description="工序ID")
    quantity: int | None = Field(None, gt=0, le=9999999, description="本批收货数量（缺省=剩余待收）")


class OrderProcessShipBatch(BaseModel):
    """批量发货请求（单事务原子）：一次请求完成多道工序发货"""
    items: list[OrderProcessShipItem] = Field(..., min_length=1, max_length=200)


class OrderProcessReceiveBatch(BaseModel):
    """批量收货请求（单事务原子）：一次请求完成多道工序收货"""
    items: list[OrderProcessReceiveItem] = Field(..., min_length=1, max_length=200)


class OrderProcessListResponse(BaseModel):
    """订单外发工序列表响应"""
    success: bool = True
    data: list[dict]
    total: int = 0


class OrderProcessFlowResponse(BaseModel):
    """外发工序流水（发货/收货记录）"""
    id: int
    process_id: int
    process_type: str | None = None
    action: str
    quantity: int
    operator: str | None = None
    create_time: datetime | None = None


class OrderProcessFlowListResponse(BaseModel):
    """订单外发工序流水列表响应（台账）"""
    success: bool = True
    data: list[OrderProcessFlowResponse] = []
    total: int = 0


class GenerateProcessResponse(BaseModel):
    """按 SKU 预设生成订单工序的响应"""
    success: bool
    message: str
    created: int = 0
    skipped: int = 0


class OrderActionResponse(BaseModel):
    """通用操作响应"""
    success: bool
    message: str


