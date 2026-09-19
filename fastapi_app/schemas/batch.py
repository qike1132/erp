"""
批量导入 Pydantic 数据模型
"""

from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field


@runtime_checkable
class ExcelUpload(Protocol):
    """上传的 Excel 文件的最小契约（传输层无关）。

    FastAPI 的 ``UploadFile`` 结构化地满足本协议；服务层因此无需 import
    ``fastapi.UploadFile``，ARQ 任务 / CLI 也可传入任意等价实现。
    """

    filename: str | None

    async def read(self, size: int = -1) -> bytes:
        ...


class BatchImportResult(BaseModel):
    """批量导入结果"""
    success: bool = Field(..., description="是否成功")
    message: str = Field(..., description="结果消息")
    imported: int = Field(default=0, description="成功导入数量")
    skipped: int = Field(default=0, description="跳过数量")


class ComprehensiveImportResult(BaseModel):
    """综合批量导入结果"""
    success: bool = Field(..., description="是否成功")
    message: str = Field(default="", description="结果消息")
    imported: dict = Field(
        default_factory=lambda: {"products": 0, "orders": 0, "stockins": 0, "stockouts": 0},
        description="各类型导入数量"
    )
    errors: list[str] = Field(default_factory=list, description="错误列表")


class DeductionDetail(BaseModel):
    """抵扣详情"""
    stockin_id: int
    stockin_no: str
    deduct_amount: int
    stockout_no: str
    remaining_in_stockin: int
