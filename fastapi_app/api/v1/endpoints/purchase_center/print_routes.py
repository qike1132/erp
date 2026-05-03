"""
采购中心 — 汇总打印 / Excel 导出路由
"""
import io
import zipfile
from datetime import datetime
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.exc import DisconnectionError, OperationalError
from sqlalchemy.orm import Session, selectinload

from fastapi_app.api.v1.endpoints.purchase_center.export_utils import (
    create_supplier_workbook,
    generate_factory_summary_print,
    generate_normal_summary_print,
    generate_supplier_summary_print,
)
from fastapi_app.api.v1.endpoints.purchase_center.schemas import OrderIdsRequest, SummaryPrintRequest
from fastapi_app.core.database import get_sync_db as get_db
from fastapi_app.core.deps import require_permission
from fastapi_app.core.logger import logger
from fastapi_app.services import purchase_center_service as svc

router = APIRouter()

@router.post('/orders/summary-print')
def api_summary_print(data: SummaryPrintRequest, db: Session=Depends(get_db), _user=Depends(require_permission('product_manage'))):
    ids = data.ids
    format_type = data.format
    try:
        from fastapi_app.shared_models import PurchaseOrder, PurchaseOrderItem
        orders = db.query(PurchaseOrder).filter(PurchaseOrder.id.in_(ids)).options(selectinload(PurchaseOrder.items)).all()
        if format_type in ['factory', 'supplier']:
            source_order_ids = list({o.source_order_id for o in orders if o.source_order_id})
            if source_order_ids:
                related = db.query(PurchaseOrder).filter(PurchaseOrder.source_order_id.in_(source_order_ids)).options(selectinload(PurchaseOrder.items)).all()
                all_order_ids = list(set(ids) | {o.id for o in related})
            else:
                all_order_ids = list(ids)
            if len(all_order_ids) != len(ids):
                orders = db.query(PurchaseOrder).filter(PurchaseOrder.id.in_(all_order_ids)).options(selectinload(PurchaseOrder.items)).all()
                ids = all_order_ids
        items = db.query(PurchaseOrderItem).filter(PurchaseOrderItem.order_id.in_(ids)).all()
        order_items_map = {}
        for item in items:
            order_items_map.setdefault(item.order_id, []).append(item)
        if format_type == 'factory':
            html = generate_factory_summary_print(db, orders, order_items_map)
            return {'success': True, 'html': html, 'order_count': len(orders)}
        elif format_type == 'supplier':
            sorted_suppliers = svc.query_supplier_groups(db, ids)
            html = generate_supplier_summary_print(sorted_suppliers, orders)
            return {'success': True, 'html': html, 'supplier_count': len(sorted_suppliers), 'order_count': len(orders)}
        else:
            html = generate_normal_summary_print(orders, order_items_map)
            return {'success': True, 'html': html, 'order_count': len(orders)}
    except (OperationalError, DisconnectionError, ValueError, RuntimeError) as e:
        logger.exception(f'汇总打印失败: {str(e)}')
        raise HTTPException(status_code=500, detail='操作失败，请稍后重试') from e

@router.post('/orders/supplier-summary-export')
def export_supplier_summary_excel(data: OrderIdsRequest, db: Session=Depends(get_db), _user=Depends(require_permission('product_manage'))):
    """按供应商维度导出采购订单汇总 Excel，单文件直接下载，多文件 ZIP 打包"""
    order_ids = data.ids
    try:
        sorted_suppliers = svc.query_supplier_groups(db, order_ids)
        if not sorted_suppliers:
            raise HTTPException(status_code=404, detail='未找到供应商数据')
        date_prefix = datetime.now().strftime('%Y-%m-%d')
        if len(sorted_suppliers) == 1:
            supplier = sorted_suppliers[0]
            wb = create_supplier_workbook(supplier)
            excel_buffer = io.BytesIO()
            wb.save(excel_buffer)
            wb.close()
            excel_buffer.seek(0)
            filename = f"{date_prefix}-{supplier['supplier_name']}_采购订单汇总.xlsx"
            encoded_filename = quote(filename, safe='')
            return StreamingResponse(excel_buffer, media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', headers={'Content-Disposition': f"attachment; filename*=UTF-8''{encoded_filename}"})
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
            for supplier in sorted_suppliers:
                wb = create_supplier_workbook(supplier)
                excel_buffer = io.BytesIO()
                wb.save(excel_buffer)
                wb.close()
                excel_buffer.seek(0)
                filename = f"{supplier['supplier_name']}_采购订单汇总.xlsx"
                zf.writestr(filename, excel_buffer.read())
        zip_buffer.seek(0)
        zip_filename = f'{date_prefix}-供应商采购订单汇总.zip'
        encoded_filename = quote(zip_filename, safe='')
        return StreamingResponse(zip_buffer, media_type='application/zip', headers={'Content-Disposition': f"attachment; filename*=UTF-8''{encoded_filename}"})
    except HTTPException:
        raise
    except (OSError, ValueError, RuntimeError) as e:
        logger.exception(f'导出供应商汇总Excel失败: {str(e)}')
        raise HTTPException(status_code=500, detail='导出失败，请稍后重试') from e
