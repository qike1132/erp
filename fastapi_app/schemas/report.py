"""报表统计相关 Schema"""
from pydantic import BaseModel


class ReportLogItem(BaseModel):
    # 记录级标识（2026-10-13：四 tab 改一行一记录后，逐行单号/ID 才有意义）
    record_id: int = 0
    record_no: str = ''
    # 订单流水母行-明细（2026-10-13）：订单级字段 + SKU 级字段
    order_id: int = 0
    order_no: str = ''
    item_id: int = 0
    item_count: int = 0
    order_total_qty: int = 0
    item_note: str = ''
    order_date: str = ''
    stockin_date: str = ''
    stockout_date: str = ''
    deduction_time: str = ''
    return_date: str = ''
    customer: str = ''
    product_name: str = ''
    product_barcode: str = ''
    sku: str = ''
    quantity: int = 0
    status: str = ''
    order_count: int = 0
    stockin_count: int = 0
    stockout_count: int = 0
    deduction_count: int = 0
    return_count: int = 0
    order_nos: str = ''
    stockin_nos: str = ''
    stockout_nos: str = ''
    return_nos: str = ''
    note: str = ''
    order_note: str = ''


class ReportResponse(BaseModel):
    success: bool = True
    logs: list[ReportLogItem] = []
    stats: dict = {}
    pagination: dict = {}


class ReportExportRequest(BaseModel):
    type: str = 'order'
    customer: str = ''
    product: str = ''
    status: str = ''
    start_date: str = ''
    end_date: str = ''
