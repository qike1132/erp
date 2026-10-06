"""
退货管理 Pydantic 数据模型

用于销售退货的请求模型；列表/操作响应复用 schemas.stock 的
StockListResponse / StockActionResponse 通用模型。
"""
from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class ShipmentOption(BaseModel):
    """可退出货明细候选（按产品名搜索，带可退量）"""
    stockout_id: int
    stockout_no: str
    stockout_date: str
    product_id: int
    product_name: str
    customer: str | None
    quantity: int
    returned_quantity: int
    available: int


def _validate_date_format(v: str | None) -> str | None:
    """验证日期格式为 YYYY-MM-DD"""
    if v is not None:
        datetime.strptime(v, '%Y-%m-%d')
    return v


class StockReturnCreate(BaseModel):
    """创建退货请求（按出货明细退货：搜产品 → 选出货明细 → 录数量）

    客户/产品/订单由所选出货明细带出；可退量（出货量 − 已退量）在
    services/stock_return_service.create_stockreturn_core 校验，
    违例以 ValueError 抛出并经 db_transaction 统一映射为 400。
    """
    stockout_id: int = Field(..., gt=0, description="所选出货明细ID（来自 shipment-options 搜索）")
    quantity: int = Field(..., gt=0, le=9999999, description="退货数量")
    return_date: str | None = Field(None, description="退货日期 (YYYY-MM-DD)，缺省为当天")
    reason: str | None = Field(None, max_length=200, description="退货原因")
    note: str | None = Field(None, max_length=500, description="备注")
    request_id: str | None = Field(
        None, max_length=64, min_length=8,
        description="幂等令牌（前端每次打开弹窗生成的 UUID）；同令牌重复提交返回 400",
    )

    @field_validator('return_date')
    @classmethod
    def validate_return_date(cls, v):
        return _validate_date_format(v)
