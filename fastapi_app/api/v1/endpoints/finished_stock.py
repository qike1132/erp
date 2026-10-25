"""成品库存（批次级）API 端点

按 客户/产品/批次 聚合成品库存 + 某产品的批次可用量列表 + Excel 导出 + 页面备注维护。
真相源与 /stock 同源（daily_production_record 包装部 + stock_out 批次扣减）。
"""
import io
from urllib.parse import quote

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.database import get_async_db, get_async_read_db
from fastapi_app.core.deps import require_any_permission
from fastapi_app.core.exceptions import db_transaction
from fastapi_app.schemas.finished_stock import (
    BatchAvailableItem,
    BatchListResponse,
    FinishedStockRemarkResponse,
    FinishedStockRemarkUpdate,
    FinishedStockSummaryResponse,
)
from fastapi_app.services import finished_stock_service
from fastapi_app.shared.factory_scope import assert_product_factory_scoped
from fastapi_app.shared_models import User

# Excel 公式注入清洗（审查 H12）：customer_name/product_name/batch_no 等是
# 用户可控文本，复用权威清洗器（与 purchase_center/export_utils.py 同口径）。
from utils.report_exporter import _sanitize_excel_value

router = APIRouter()

# 导出最大行数（仿 stock.py 的 MAX_EXPORT_INVENTORY_ROWS），防 openpyxl 全量内存构建 OOM
MAX_EXPORT_ROWS = 10000


def _factory_scope(user: User) -> str:
    """读侧工厂范围：厂绑定（factory 非空）非超管收窄到本厂，其余全量。

    与 stock.py::_factory_scope、report.py::_factory_scope 同口径；读端点不得信任
    调用方传参，工厂一律由服务端当前用户派生（2026-10-25 上线前检查 H1）。
    """
    return user.factory if (user.factory and not user.is_super) else ''


@router.get('/summary', response_model=FinishedStockSummaryResponse)
async def finished_stock_summary(
    customer: str = Query('', description='客户名称筛选（精确）'),
    product: str = Query('', description='产品名称/69码搜索'),
    batch_no: str = Query('', description='批次号筛选（精确）'),
    page: int = Query(1, ge=1, description='页码'),
    per_page: int = Query(20, ge=1, le=200, description='每页数量'),
    db: AsyncSession = Depends(get_async_read_db),
    # 与 /stock/inventory 同权限用户（stock_view / stockin_manage），外加本页导航权限码
    # finished_stock_view（见 seed_nav.py）——否则管理员按导航勾选「成品库存」的用户
    # 能看到入口却拿 403（导航码↔接口码错配）。
    user: User = Depends(require_any_permission('stockin_manage', 'stock_view', 'finished_stock_view')),
) -> FinishedStockSummaryResponse:
    """按 客户/产品/批次 聚合成品库存（只读副本，厂绑定用户限本厂产品）。"""
    result = await finished_stock_service.get_finished_stock_summary(
        db,
        customer_name=customer,
        product_search=product,
        batch_no=batch_no,
        page=page,
        per_page=per_page,
        factory=_factory_scope(user),
    )
    return FinishedStockSummaryResponse(**result)


@router.get('/batches', response_model=BatchListResponse)
async def product_batches(
    product_id: int = Query(..., gt=0, description='产品ID'),
    customer: str = Query('', description='客户名称（可选，精确）'),
    db: AsyncSession = Depends(get_async_read_db),
    # 唯一消费方是出库管理页（StockOutTab → finishedStockApi.batches），其权限码是
    # stockout_manage；只授该码的用户也须能取批次，否则出货页批次下拉静默 403。
    user: User = Depends(require_any_permission('stockin_manage', 'stock_view', 'finished_stock_view', 'stockout_manage')),
) -> BatchListResponse:
    """某产品的批次可用量列表（供 /stock-out 录入 SKU 后带出批次选择）。"""
    # product_id 由调用方提供，必须先过工厂闸门（与写端点同口径）：他厂产品 404，
    # 不暴露存在性（2026-10-25 上线前检查 H1）。
    await assert_product_factory_scoped(db, product_id, user, what='产品')
    rows = await finished_stock_service.get_batches_by_product(
        db, product_id, customer_name=customer, factory=_factory_scope(user))
    # 服务层返回 list[dict]，显式构造成模型（与 response_model 的隐式校验等价），mypy 可查字段
    return BatchListResponse(data=[BatchAvailableItem(**row) for row in rows])


def _build_finished_stock_excel(rows: list[dict]) -> bytes:
    """生成成品库存导出 Excel（在线程中调用，避免阻塞事件循环）。"""
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = '成品库存'
    ws.append(['客户', '产品名称', '69码', '批次号', '库存', '定制', '定制国家'])
    for r in rows:
        ws.append([
            _sanitize_excel_value(r['customer_name'] or ''),
            _sanitize_excel_value(r['product_name'] or ''),
            _sanitize_excel_value(r['barcode'] or ''),
            _sanitize_excel_value(r['batch_no'] or ''),
            r['batch_available'],
            '是' if r['is_custom'] else '',
            _sanitize_excel_value(r['custom_country'] or ''),
        ])
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


@router.get('/export')
async def export_finished_stock(
    customer: str = Query('', description='客户名称筛选（精确）'),
    product: str = Query('', description='产品名称/69码搜索'),
    batch_no: str = Query('', description='批次号筛选（精确）'),
    db: AsyncSession = Depends(get_async_read_db),
    user: User = Depends(require_any_permission('stockin_manage', 'stock_view', 'finished_stock_view')),
) -> StreamingResponse:
    """导出当前筛选（客户 + 搜索词）的成品库存为 Excel（厂绑定用户限本厂）。"""
    import asyncio

    result = await finished_stock_service.get_finished_stock_summary(
        db, customer_name=customer, product_search=product, batch_no=batch_no,
        page=1, per_page=MAX_EXPORT_ROWS, factory=_factory_scope(user),
    )
    if result['total'] > MAX_EXPORT_ROWS:
        raise HTTPException(status_code=400, detail=f'数据量过大({result["total"]}条)，请缩小查询范围后重试')

    excel = await asyncio.to_thread(_build_finished_stock_excel, result['data'])
    buffer = io.BytesIO(excel)
    buffer.seek(0)
    filename = '成品库存.xlsx'
    return StreamingResponse(
        buffer,
        media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        headers={'Content-Disposition': f"attachment; filename*=UTF-8''{quote(filename)}"},
    )


@router.put('/remark', response_model=FinishedStockRemarkResponse)
async def upsert_remark(
    data: FinishedStockRemarkUpdate = Body(...),
    db: AsyncSession = Depends(get_async_db),
    # 备注是页面维护动作，与 /finished-stock 读同权限（含本页导航码）
    user: User = Depends(require_any_permission('stockin_manage', 'stock_view', 'finished_stock_view')),
) -> FinishedStockRemarkResponse:
    """页面级备注 UPSERT：键 (客户,产品,批次) 一行一条；内容清空即删除。"""
    # product_id 由请求体提供：他厂产品的备注读写一律 404（与读端点同口径，
    # 防厂绑定用户借备注写探到他厂产品存在性——2026-10-25 上线前检查 H1）。
    await assert_product_factory_scoped(db, data.product_id, user, what='产品')
    async with db_transaction(db):
        await finished_stock_service.upsert_remark(
            db,
            customer_name=data.customer_name,
            product_id=data.product_id,
            batch_no=data.batch_no,
            remark=data.remark,
        )
    # 回显归一化后的值：service 会 strip 并在空结果时删行，回显原始输入会让响应
    # 与实际落库状态矛盾（例如纯空白输入会报一个非空 remark）
    return FinishedStockRemarkResponse(success=True, remark=(data.remark or '').strip())
