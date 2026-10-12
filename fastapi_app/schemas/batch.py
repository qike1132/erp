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


class ProductImportPreviewRow(BaseModel):
    """产品导入预览的单行结果（**只分类，不写库**）。

    ``action`` 取值：``create`` 新增 / ``backfill`` 补全 / ``skip`` 跳过 / ``error`` 错误。
    """
    row_no: int = Field(..., description="Excel 行号（表头为第 1 行，数据从 2 起）")
    action: str = Field(..., description="create=新增 / backfill=补全 / skip=跳过 / error=错误")
    name: str = Field(default="", description="产品名称（原样，未做匹配）")
    barcode: str = Field(default="", description="69码")
    price: str = Field(default="", description="解析后的价格（错误/空行为空串）")
    price_raw: str = Field(default="", description="文件里的价格原值，便于核对识别是否正确")
    factory: str = Field(default="", description="工厂")
    customer_name: str = Field(default="", description="客户列原值")
    customer_matched: bool = Field(default=False, description="客户名是否命中客户主数据")
    has_image: bool = Field(default=False, description="该行是否带图片")
    changes: list[str] = Field(default_factory=list, description="将改动的字段（补全行给出改前改后）")
    messages: list[str] = Field(default_factory=list, description="行级提示（客户未匹配等）")


class ProductImportPreviewSummary(BaseModel):
    """产品导入预览的汇总计数（与行分类一一对应）。"""
    create: int = Field(default=0, description="将新增的行数")
    backfill: int = Field(default=0, description="将补全的行数")
    skip: int = Field(default=0, description="将跳过的行数")
    error: int = Field(default=0, description="无法导入的行数")


class ProductImportPreviewResult(BaseModel):
    """产品导入预览结果（**不写库**，由前端人工核对后再确认导入）。"""
    success: bool = Field(..., description="是否成功解析出可预览的行")
    message: str = Field(..., description="结果消息")
    filename: str = Field(default="", description="文件名")
    row_count: int = Field(default=0, description="解析出的数据行数")
    summary: ProductImportPreviewSummary = Field(
        default_factory=ProductImportPreviewSummary, description="汇总计数")
    rows: list[ProductImportPreviewRow] = Field(default_factory=list, description="逐行结果")


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
