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
    """按供应商维度导出采购订单 Excel。

    汇总下单场景下「一家供应商 = 一张采购订单」，故按供应商归并选中的采购订单明细：
    - 同一供应商（明细级 supplier_name 回退订单级）的物料合并为一份工作簿，
      相同物料（名称 + 规格 + 单位）数量跨订单累加；
    - 单个供应商返回 .xlsx，多个供应商打包为 .zip。
    """
    if not data.ids:
        raise HTTPException(status_code=400, detail='请至少选择一个订单')
    try:
        orders = await svc.get_purchase_orders_with_items(db, data.ids)
        if not orders:
            raise HTTPException(status_code=404, detail='未找到采购订单数据')

        supplier_groups = [
            group for group in await svc.build_supplier_export_groups(db, orders) if group['items']
        ]
        if not supplier_groups:
            raise HTTPException(status_code=404, detail='未找到可导出的采购订单明细数据')

        date_prefix = datetime.now().strftime('%Y-%m-%d')

        def _generate_export(supplier_groups, date_prefix):
            if len(supplier_groups) == 1:
                supplier = supplier_groups[0]
                wb = create_supplier_workbook(supplier)
                excel_buffer = io.BytesIO()
                wb.save(excel_buffer)
                wb.close()
                excel_buffer.seek(0)
                filename = f"{date_prefix}-{supplier['supplier_name']}_采购订单汇总.xlsx"
                encoded_filename = quote(filename, safe='')
                return ('excel', excel_buffer, encoded_filename)
            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
                for supplier in supplier_groups:
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
            return ('zip', zip_buffer, encoded_filename)

        export_type, buffer, encoded_filename = await asyncio.to_thread(_generate_export, supplier_groups, date_prefix)
        if export_type == 'excel':
            return StreamingResponse(buffer, media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', headers={'Content-Disposition': f"attachment; filename*=UTF-8''{encoded_filename}"})
        return StreamingResponse(buffer, media_type='application/zip', headers={'Content-Disposition': f"attachment; filename*=UTF-8''{encoded_filename}"})
    except HTTPException:
        raise
    except (OSError, ValueError, RuntimeError) as e:
        logger.exception(f'导出供应商汇总Excel失败: {e!s}')
        raise HTTPException(status_code=500, detail='导出失败，请稍后重试') from e
