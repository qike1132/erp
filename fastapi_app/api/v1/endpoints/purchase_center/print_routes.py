"""
采购中心 — 供应商汇总 Excel 导出路由（旧后端打印端点已下线）
"""
import asyncio
import io
import re
import zipfile
from datetime import datetime
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.api.v1.endpoints.purchase_center.export_utils import create_supplier_workbook
from fastapi_app.api.v1.endpoints.purchase_center.schemas import SupplierSummaryExportRequest
from fastapi_app.core.database import get_async_db as get_db
from fastapi_app.core.deps import require_any_permission
from fastapi_app.core.logger import logger
from fastapi_app.services import purchase_center_service as svc

router = APIRouter()

def _normalize_supplier_name(name: str | None) -> str:
    """供应商名称归一化：空值统一为「未指定供应商」（与汇总 / 页面口径一致）。"""
    return name or '未指定供应商'


def rebuild_supplier_groups_from_page(supplier_groups: list[dict], rows) -> list[dict]:
    """按页面展示行**重建**导出分组：行集、行序、数量严格等于页面。

    页面「供应商采购订单」已按 (供应商, 物料, 规格, 单位) 聚合，且**排除填充物**
    （``_is_filling_category``）。导出的采购订单必须与用户确认过的页面一致，故以页面行集为准：
    - 页面不展示的行（填充物等）不再出现在 Excel 中；
    - 页面展示而明细分组缺失的行（BOM 用量回退场景）也能正常导出；
    - 供应商联系信息仍取数据库口径（主数据缺失时回退采购订单冗余字段），
      按供应商名从原分组继承，避免因重建丢失抬头信息。

    ``rows`` 为空时原样返回（旧客户端 / 无页面数据 → 保持原有明细口径）。
    """
    if not rows:
        return supplier_groups
    source_by_supplier = {
        _normalize_supplier_name(group.get('supplier_name')): group for group in supplier_groups
    }
    # 来源订单明细按 (供应商, 物料, 规格, 单位) 从原分组继承：
    # 页面行只带展示数量，逐单贡献量只有数据库分组里有。
    source_items = {
        (
            _normalize_supplier_name(group.get('supplier_name')),
            item.get('material_name'),
            item.get('specification') or '',
            item.get('unit') or '',
        ): item
        for group in supplier_groups
        for item in (group.get('items') or [])
    }
    supplier_order: list[str] = []
    items_by_supplier: dict[str, list[dict]] = {}
    for row in rows:
        supplier_name = _normalize_supplier_name(row.supplier_name)
        if supplier_name not in items_by_supplier:
            items_by_supplier[supplier_name] = []
            supplier_order.append(supplier_name)
        source_item = source_items.get((
            supplier_name, row.material_name, row.specification or '', row.unit or '',
        )) or {}
        item = {
            'material_name': row.material_name,
            'specification': row.specification or '',
            'unit': row.unit or '',
            'quantity': row.quantity,
        }
        # 页面已按「主行合计」分配好逐单展示数量（整数），优先使用；
        # 缺省（旧客户端 / 页面行无来源）时回退数据库分组的原始逐单量。
        page_breakdown = [
            {'order_no': entry.order_no, 'quantity': entry.quantity}
            for entry in (getattr(row, 'order_breakdown', None) or [])
        ]
        if page_breakdown:
            item['order_breakdown'] = page_breakdown
        elif source_item.get('order_breakdown'):
            item['order_breakdown'] = source_item['order_breakdown']
        items_by_supplier[supplier_name].append(item)
    rebuilt = []
    for supplier_name in supplier_order:
        source = source_by_supplier.get(supplier_name) or {}
        rebuilt.append({
            'supplier_name': supplier_name,
            'items': items_by_supplier[supplier_name],
            'contact_person': source.get('contact_person', ''),
            'phone': source.get('phone', ''),
            'address': source.get('address', ''),
        })
    return rebuilt


@router.post('/orders/supplier-summary-export')
async def export_supplier_summary_excel(data: SupplierSummaryExportRequest, db: AsyncSession=Depends(get_db), _user=Depends(require_any_permission('product_manage', 'purchase_center_manage'))):
    """按供应商维度导出采购订单 Excel。

    汇总下单场景下「一家供应商 = 一张采购订单」，故按供应商归并选中的采购订单明细：
    - 同一供应商（明细级 supplier_name 回退订单级）的物料合并为一份工作簿，
      相同物料（名称 + 规格 + 单位）数量跨订单累加；
    - 单个供应商返回 .xlsx，多个供应商打包为 .zip。

    ``supplier_quantities`` 非空时，导出**严格等于页面行集**：行、顺序、数量都取页面
    「供应商采购订单」页签的展示值（含损耗率加放与取整），页面不展示的填充物等明细不再导出。
    """
    if not data.ids:
        raise HTTPException(status_code=400, detail='请至少选择一个订单')
    try:
        orders = await svc.get_purchase_orders_with_items(db, data.ids)
        if not orders:
            raise HTTPException(status_code=404, detail='未找到采购订单数据')

        db_groups = [
            group for group in await svc.build_supplier_export_groups(db, orders) if group['items']
        ]
        supplier_groups = (
            rebuild_supplier_groups_from_page(db_groups, data.supplier_quantities)
            if data.supplier_quantities
            else db_groups
        )
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
                    # L-29（2026-11-21 审计）：供应商名来自用户提交，直接拼 zip 条目名
                    # 可构造 `..\` 跨目录条目（zip-slip）——滤掉路径分隔符与父目录片段。
                    _safe_name = re.sub(r'[\\/:*?"<>|]|\.\.', '_', supplier['supplier_name'])
                    filename = f"{_safe_name}_采购订单汇总.xlsx"
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
