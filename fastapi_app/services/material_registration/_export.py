"""物料登记导出

从 material_registration_service.py 按职责拆出,行为与原实现完全一致。
"""
import io
import logging

import xlsxwriter
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from fastapi_app.core.sanitizer import escape_like
from fastapi_app.services.material_registration._queries import _parse_filter_date
from fastapi_app.shared_models import MaterialRegistration, MaterialRegistrationItem, PurchaseOrder

logger = logging.getLogger(__name__)


def _sanitize_xlsx_formula(val: str) -> str:
    """防 xlsx 公式注入：以 =+-@ 开头的字符串前置撇号（供 merge_range 使用，
    其内部按 write 语义会将 '=' 开头字符串当公式执行）"""
    if val and val[0] in '=+-@':
        return "'" + val
    return val

async def export_registrations(db, order_no: str = '', supplier: str = '',
                               customer_name: str = '', material_category: str = '',
                               start_date: str = '', end_date: str = '') -> io.BytesIO:
    """导出来料登记数据（真 xlsx 格式，替代旧 HTML 伪装 Excel 方案）

    Returns:
        io.BytesIO: xlsx 文件字节流（已 seek(0)，可直接用于 StreamingResponse）。
    """
    needs_po_join = bool(customer_name)
    base_query = select(MaterialRegistration)
    if needs_po_join:
        base_query = base_query.join(MaterialRegistration.purchase_order)
    query = base_query.options(
        selectinload(MaterialRegistration.items),
        selectinload(MaterialRegistration.purchase_order),
    )
    if order_no:
        query = query.where(MaterialRegistration.purchase_order_no.ilike(f'%{escape_like(order_no)}%'))  # sql-safe: escape_like/绑定参数/常量片段
    if supplier:
        query = query.where(MaterialRegistration.supplier_name.ilike(f'%{escape_like(supplier)}%'))  # sql-safe: escape_like/绑定参数/常量片段
    if customer_name:
        query = query.where(PurchaseOrder.customer_name.ilike(f'%{escape_like(customer_name)}%'))  # sql-safe: escape_like/绑定参数/常量片段
    if start_date:
        query = query.where(MaterialRegistration.registration_date >= _parse_filter_date(start_date, '开始日期'))
    if end_date:
        query = query.where(MaterialRegistration.registration_date <= _parse_filter_date(end_date, '结束日期'))
    if material_category:
        query = query.where(
            MaterialRegistration.items.any(MaterialRegistrationItem.material_category == material_category)
        )

    query = query.order_by(MaterialRegistration.create_time.desc()).limit(5000)

    # 独立 COUNT 查询总数，检测 limit(5000) 截断并向日志留痕（本函数返回 BytesIO 文件流，
    # 响应头需由 endpoint 层设置，故此处以 WARNING 日志标注截断事实与筛选条件）
    count_query = select(func.count()).select_from(query.order_by(None).limit(None).subquery())
    total_count = (await db.execute(count_query)).scalar() or 0
    if total_count > 5000:
        logger.warning(
            '来料登记导出被截断：符合条件的记录共 %d 条，仅导出前 5000 条 '
            '（order_no=%r, supplier=%r, customer_name=%r, category=%r, %s~%s）',
            total_count, order_no, supplier, customer_name, material_category, start_date, end_date,
        )

    result = await db.execute(query)
    registrations = list(result.unique().scalars().all())

    status_map = {'pending': '待收货', 'partial': '部分收货', 'completed': '已完成'}

    output = io.BytesIO()
    workbook = xlsxwriter.Workbook(output, {'in_memory': True})
    try:
        ws = workbook.add_worksheet('来料登记汇总')
        header_fmt = workbook.add_format({
            'bold': True, 'bg_color': '#E6E6E6', 'border': 1,
            'align': 'center', 'valign': 'vcenter',
        })
        cell_fmt = workbook.add_format({'border': 1, 'align': 'center', 'valign': 'vcenter'})

        headers = ['登记日期', '订单号', '供应商', '物料名称', '规格', '采购数量', '已收货', '状态']
        for col, title in enumerate(headers):
            ws.write(0, col, title, header_fmt)

        row = 1
        for reg in registrations:
            items = list(reg.items)
            status_text = status_map.get(reg.computed_status, reg.computed_status)
            date_text = reg.registration_date.strftime('%Y-%m-%d') if reg.registration_date else '-'
            span = max(len(items), 1)

            # 左侧固定列与状态列：多行明细时纵向合并（对齐旧版 rowspan 效果）
            # 文本列统一 write_string / 合并前转义，防用户录入数据的公式注入
            fixed_cols = [(0, date_text), (1, reg.purchase_order_no or '-'),
                          (2, reg.supplier_name or '-'), (7, status_text)]
            for col, val in fixed_cols:
                text_val = str(val)
                if span > 1:
                    ws.merge_range(row, col, row + span - 1, col,
                                   _sanitize_xlsx_formula(text_val), cell_fmt)
                else:
                    ws.write_string(row, col, text_val, cell_fmt)

            if not items:
                for col in (3, 4, 5, 6):
                    ws.write(row, col, '-', cell_fmt)
            else:
                for idx, item in enumerate(items):
                    r = row + idx
                    ws.write_string(r, 3, item.material_name or '-', cell_fmt)
                    ws.write_string(r, 4, item.specification or '-', cell_fmt)
                    ws.write(r, 5, float(item.ordered_quantity or 0), cell_fmt)
                    ws.write(r, 6, float(item.received_quantity or 0), cell_fmt)
            row += span

        for col, width in enumerate([12, 18, 20, 24, 16, 10, 10, 10]):
            ws.set_column(col, col, width)
    finally:
        workbook.close()

    output.seek(0)
    return output
