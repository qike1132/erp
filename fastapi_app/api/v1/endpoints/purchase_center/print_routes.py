"""
采购中心 — 汇总打印 / Excel 导出路由
"""
import asyncio
import io
import zipfile
from datetime import datetime
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.exc import DisconnectionError, OperationalError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.api.v1.endpoints.purchase_center.export_utils import (
    create_supplier_workbook,
    generate_factory_summary_print,
    generate_normal_summary_print,
    generate_supplier_summary_print,
)
from fastapi_app.api.v1.endpoints.purchase_center.schemas import OrderIdsRequest, SummaryPrintRequest
from fastapi_app.core.database import get_async_db as get_db
from fastapi_app.core.deps import require_any_permission
from fastapi_app.core.logger import logger
from fastapi_app.core.response import success_response
from fastapi_app.schemas.purchase_center import SupplierSummaryResponse
from fastapi_app.services import purchase_center_service as svc

router = APIRouter()

@router.post('/orders/summary-print', response_model=SupplierSummaryResponse)
async def api_summary_print(data: SummaryPrintRequest, db: AsyncSession=Depends(get_db), _user=Depends(require_any_permission('product_manage', 'purchase_center_manage'))):
    ids = data.ids
    format_type = data.format
    try:
        orders = await svc.get_purchase_orders_with_items(db, ids)

        if format_type in ['factory', 'supplier']:
            source_order_ids = list({o.source_order_id for o in orders if o.source_order_id})
            if source_order_ids:
                related = await svc.get_purchase_orders_by_source_ids(db, source_order_ids)
                all_order_ids = list(set(ids) | {o.id for o in related})
            else:
                all_order_ids = list(ids)
            if len(all_order_ids) != len(ids):
                orders = await svc.get_purchase_orders_with_items(db, all_order_ids)
                ids = all_order_ids

        items = await svc.get_purchase_order_items_by_order_ids(db, ids)
        order_items_map = {}
        for item in items:
            order_items_map.setdefault(item.order_id, []).append(item)

        if format_type == 'factory':
            source_order_ids = [o.source_order_id for o in orders if o.source_order_id]
            source_orders = None
            if source_order_ids:
                source_orders = await svc.get_system_orders_by_ids(db, source_order_ids)
            html = generate_factory_summary_print(orders, order_items_map, source_orders)
            return success_response(html=html, order_count=len(orders))
        elif format_type == 'supplier':
            sorted_suppliers = await svc.query_supplier_groups(db)
            html = generate_supplier_summary_print(sorted_suppliers, orders)
            return success_response(html=html, supplier_count=len(sorted_suppliers), order_count=len(orders))
        else:
            html = generate_normal_summary_print(orders, order_items_map)
            return success_response(html=html, order_count=len(orders))
    except (OperationalError, DisconnectionError, SQLAlchemyError, ValueError, RuntimeError) as e:
        logger.exception(f'汇总打印失败: {e!s}')
        raise HTTPException(status_code=500, detail='操作失败，请稍后重试') from e

@router.post('/orders/supplier-summary-export')
async def export_supplier_summary_excel(data: OrderIdsRequest, db: AsyncSession=Depends(get_db), _user=Depends(require_any_permission('product_manage', 'purchase_center_manage'))):
    """根据选中的采购订单 ID 列表，按每个采购订单单独导出供应商采购订单 Excel。
    重载触发标记

    一份采购订单对应一家供应商，因此按 order_no 逐单导出：
    - 每张采购订单生成一个独立的工作簿（基于模板，含该单供应商信息与物料明细）。
    - 单个订单返回 .xlsx，多个订单打包为 .zip。
    """
    if not data.ids:
        raise HTTPException(status_code=400, detail='请至少选择一个订单')
    try:
        orders = await svc.get_purchase_orders_with_items(db, data.ids)
        if not orders:
            raise HTTPException(status_code=404, detail='未找到采购订单数据')

        # 每张采购订单 → 一个独立供应商工作簿的数据结构
        supplier_order_items = []
        for order in orders:
            items = [
                {
                    'material_name': item.material_name,
                    'specification': item.specification or '',
                    'quantity': float(item.quantity or 0),
                    'unit': item.unit or '',
                }
                for item in (order.items or [])
            ]
            if not items:
                continue
            supplier_order_items.append({
                'supplier_name': order.supplier_name or '未指定供应商',
                'order_no': order.order_no,
                'address': order.supplier_address or '',
                'phone': order.supplier_phone or '',
                'contact_person': order.supplier_contact_person or '',
                'items': items,
            })

        if not supplier_order_items:
            raise HTTPException(status_code=404, detail='未找到可导出的采购订单明细数据')

        date_prefix = datetime.now().strftime('%Y-%m-%d')

        def _generate_export(supplier_order_items, date_prefix):
            if len(supplier_order_items) == 1:
                order_data = supplier_order_items[0]
                wb = create_supplier_workbook(order_data)
                excel_buffer = io.BytesIO()
                wb.save(excel_buffer)
                wb.close()
                excel_buffer.seek(0)
                filename = f"{order_data['order_no']}_采购订单.xlsx"
                encoded_filename = quote(filename, safe='')
                return ('excel', excel_buffer, encoded_filename)
            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
                for order_data in supplier_order_items:
                    wb = create_supplier_workbook(order_data)
                    excel_buffer = io.BytesIO()
                    wb.save(excel_buffer)
                    wb.close()
                    excel_buffer.seek(0)
                    filename = f"{order_data['order_no']}_采购订单.xlsx"
                    zf.writestr(filename, excel_buffer.read())
            zip_buffer.seek(0)
            zip_filename = f'{date_prefix}-供应商采购订单汇总.zip'
            encoded_filename = quote(zip_filename, safe='')
            return ('zip', zip_buffer, encoded_filename)

        export_type, buffer, encoded_filename = await asyncio.to_thread(_generate_export, supplier_order_items, date_prefix)
        if export_type == 'excel':
            return StreamingResponse(buffer, media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', headers={'Content-Disposition': f"attachment; filename*=UTF-8''{encoded_filename}"})
        return StreamingResponse(buffer, media_type='application/zip', headers={'Content-Disposition': f"attachment; filename*=UTF-8''{encoded_filename}"})
    except HTTPException:
        raise
    except (OSError, ValueError, RuntimeError) as e:
        logger.exception(f'导出供应商汇总Excel失败: {e!s}')
        raise HTTPException(status_code=500, detail='导出失败，请稍后重试') from e
