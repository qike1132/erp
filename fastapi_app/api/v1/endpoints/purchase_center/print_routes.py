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
from sqlalchemy.exc import DisconnectionError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.api.v1.endpoints.purchase_center.export_utils import (
    create_supplier_workbook,
    generate_factory_summary_print,
    generate_normal_summary_print,
    generate_supplier_summary_print,
)
from fastapi_app.api.v1.endpoints.purchase_center.schemas import OrderIdsRequest, SummaryPrintRequest
from fastapi_app.core.database import get_async_db as get_db
from fastapi_app.core.deps import require_permission
from fastapi_app.core.logger import logger
from fastapi_app.schemas.purchase_center import SupplierSummaryResponse
from fastapi_app.services import purchase_center_service as svc

router = APIRouter()

@router.post('/orders/summary-print', response_model=SupplierSummaryResponse)
async def api_summary_print(data: SummaryPrintRequest, db: AsyncSession=Depends(get_db), _user=Depends(require_permission('product_manage'))):
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
            return {'success': True, 'html': html, 'order_count': len(orders)}
        elif format_type == 'supplier':
            sorted_suppliers = await svc.query_supplier_groups(db)
            html = generate_supplier_summary_print(sorted_suppliers, orders)
            return {'success': True, 'html': html, 'supplier_count': len(sorted_suppliers), 'order_count': len(orders)}
        else:
            html = generate_normal_summary_print(orders, order_items_map)
            return {'success': True, 'html': html, 'order_count': len(orders)}
    except (OperationalError, DisconnectionError, ValueError, RuntimeError) as e:
        logger.exception(f'汇总打印失败: {e!s}')
        raise HTTPException(status_code=500, detail='操作失败，请稍后重试') from e

@router.post('/orders/supplier-summary-export')
async def export_supplier_summary_excel(data: OrderIdsRequest, db: AsyncSession=Depends(get_db), _user=Depends(require_permission('product_manage'))):
    """根据选中的采购订单 ID 列表，按供应商分组导出采购订单 Excel。
    重载触发标记

    使用 get_supplier_order_summary 获取物料明细，按 supplier_name 分组，
    每组生成一个独立的供应商采购订单 Excel 工作簿（基于模板）。
    单个供应商返回 .xlsx，多个供应商打包为 .zip。
    """
    if not data.ids:
        raise HTTPException(status_code=400, detail='请至少选择一个订单')
    try:
        from fastapi_app.services.purchase_order_query import get_supplier_order_summary

        summary = await get_supplier_order_summary(db, data.ids)
        materials = summary.get('materials', [])
        if not materials:
            raise HTTPException(status_code=404, detail='未找到供应商物料数据')

        # 按 supplier_name 分组，构建 create_supplier_workbook 所需的数据结构
        supplier_map: dict[str, dict] = {}
        order: list[str] = []
        for m in materials:
            sname = m.get('supplier_name') or '未指定供应商'
            if sname not in supplier_map:
                supplier_map[sname] = {
                    'supplier_name': sname,
                    'items': [],
                }
                order.append(sname)
            supplier_map[sname]['items'].append({
                'material_name': m.get('material_name', ''),
                'specification': m.get('specification', ''),
                'quantity': float(m.get('total_quantity', 0)),
                'unit': m.get('unit', ''),
            })

        sorted_suppliers = [supplier_map[s] for s in order]
        date_prefix = datetime.now().strftime('%Y-%m-%d')

        def _generate_export(sorted_suppliers, date_prefix):
            if len(sorted_suppliers) == 1:
                supplier = sorted_suppliers[0]
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
            return ('zip', zip_buffer, encoded_filename)

        export_type, buffer, encoded_filename = await asyncio.to_thread(_generate_export, sorted_suppliers, date_prefix)
        if export_type == 'excel':
            return StreamingResponse(buffer, media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', headers={'Content-Disposition': f"attachment; filename*=UTF-8''{encoded_filename}"})
        return StreamingResponse(buffer, media_type='application/zip', headers={'Content-Disposition': f"attachment; filename*=UTF-8''{encoded_filename}"})
    except HTTPException:
        raise
    except (OSError, ValueError, RuntimeError) as e:
        logger.exception(f'导出供应商汇总Excel失败: {e!s}')
        raise HTTPException(status_code=500, detail='导出失败，请稍后重试') from e
