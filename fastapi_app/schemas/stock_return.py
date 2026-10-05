"""
退货管理 Pydantic 数据模型

用于销售退货的请求模型；列表/操作响应复用 schemas.stock 的
StockListResponse / StockActionResponse 通用模型。
"""
from datetime import datetime

from pydantic import BaseModel, Field, field_validator


def _validate_date_format(v: str | None) -> str | None:
    """验证日期格式为 YYYY-MM-DD"""
    if v is not None:
        datetime.strptime(v, '%Y-%m-%d')
    return v


class StockReturnCreate(BaseModel):
    """创建退货请求（P1 录入变更：按产品退货，不关联出货单/订单）

    客户与产品为硬性必填（与备货/出货的 customer 必填口径一致）；
    数量无上限校验（不存在"可退上限"概念，以实物为准）；
    幂等校验在 services/stock_return_service.create_stockreturn_core，
    违例以 ValueError 抛出并经 db_transaction 统一映射为 400。
    """
    product_id: int = Field(..., gt=0, description="产品ID")
    quantity: int = Field(..., gt=0, le=9999999, description="退货数量")
    customer: str = Field(..., min_length=1, max_length=100, description="客户名称（硬性必填）")
    return_date: str | None = Field(None, description="退货日期 (YYYY-MM-DD)，缺省为当天")
    reason: str | None = Field(None, max_length=200, description="退货原因")
    note: str | None = Field(None, max_length=500, description="备注")
    request_id: str | None = Field(
        None, max_length=64, min_length=8,
        description="幂等令牌（前端每次打开弹窗生成的 UUID）；同令牌重复提交返回 400",
    )

    @field_validator('customer')
    @classmethod
    def validate_customer_not_blank(cls, v: str) -> str:
        """strip 后必须非空（纯空白视为缺失）"""
        stripped = v.strip()
        if not stripped:
            raise ValueError('客户名称不能为空')
        return stripped

    @field_validator('return_date')
    @classmethod
    def validate_return_date(cls, v):
        return _validate_date_format(v)
