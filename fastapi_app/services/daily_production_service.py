"""
每日生产报表业务逻辑服务

统一三部门（充棉部、手工部、包装部）的 CRUD、每日汇总、月度汇总、导出。
"""
import calendar
import io
import logging
from datetime import date, datetime, timedelta

import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill, Border, Side
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.shared_models import DailyProductionRecord

logger = logging.getLogger(__name__)

DEPARTMENT_LABELS = {
    'filling': '充棉部',
    'handcraft': '手工部',
    'packaging': '包装部',
}


def _parse_date(date_str: str) -> date:
    """解析日期字符串"""
    try:
        return datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        parts = date_str.strip().split('-')
        if len(parts) != 3:
            raise ValueError(f'日期格式不正确: {date_str}，请使用 YYYY-MM-DD 格式') from None
        y, m = (int(parts[0]), int(parts[1]))
        d = min(int(parts[2]), calendar.monthrange(y, m)[1])
        return date(y, m, d)


# ==================== 校验 ====================

def validate_record_data(
    department: str,
    product_name: str,
    quantity: int,
    unit_price: float = 0,
) -> None:
    """校验生产记录数据"""
    if department not in DEPARTMENT_LABELS:
        raise ValueError(f'部门必须是 filling、handcraft、packaging 之一，当前: {department}')
    if not product_name or not product_name.strip():
        raise ValueError('产品名称不能为空')
    if quantity <= 0:
        raise ValueError('生产数量必须大于0')
    if quantity > 999999:
        raise ValueError('生产数量不能超过999999')
    if unit_price < 0:
        raise ValueError('单价不能为负数')


# ==================== CRUD ====================

async def get_records(
    db: AsyncSession,
    *,
    year: int,
    month: int,
    department: str = '',
    production_date: str = '',
    page: int = 1,
    per_page: int = 50,
) -> dict:
    """获取指定月份的生产记录（分页）"""
    month_start = date(year, month, 1)
    if month == 12:
        month_end = date(year + 1, 1, 1)
    else:
        month_end = date(year, month + 1, 1)
    conditions = [
        DailyProductionRecord.production_date >= month_start,
        DailyProductionRecord.production_date < month_end,
    ]
    if department:
        conditions.append(DailyProductionRecord.department == department)
    if production_date:
        conditions.append(DailyProductionRecord.production_date == _parse_date(production_date))

    per_page = max(1, min(per_page, 200))
    offset = (page - 1) * per_page

    # Single query: paginated data + total count via window function + stats via cross join
    from sqlalchemy import literal_column, true
    from sqlalchemy.orm import aliased

    stats_cte = (
        select(
            func.count(DailyProductionRecord.id).label('total_count'),
            func.coalesce(func.sum(DailyProductionRecord.quantity), 0).label('total_qty'),
            func.coalesce(func.sum(DailyProductionRecord.unit_price * DailyProductionRecord.quantity), 0).label('total_val'),
            func.count(func.distinct(DailyProductionRecord.product_name)).label('total_sku'),
        )
        .where(*conditions)
        .cte('stats')
    )

    from sqlalchemy.sql.expression import Join
    cross_from = Join(DailyProductionRecord.__table__, stats_cte, true())

    result = await db.execute(
        select(
            DailyProductionRecord,
            stats_cte.c.total_count,
            stats_cte.c.total_qty,
            stats_cte.c.total_val,
            stats_cte.c.total_sku,
        )
        .select_from(cross_from)
        .where(*conditions)
        .order_by(DailyProductionRecord.production_date, DailyProductionRecord.department, DailyProductionRecord.id)
        .offset(offset)
        .limit(per_page)
    )
    rows = result.all()
    records = [r[0] for r in rows]
    total = rows[0][1] if rows else 0
    total_qty = rows[0][2] if rows else 0
    total_val = rows[0][3] if rows else 0
    total_sku = rows[0][4] if rows else 0

    return {
        'data': [r.to_dict() for r in records],
        'total': total,
        'page': page,
        'per_page': per_page,
        'pages': (total + per_page - 1) // per_page if per_page > 0 else 0,
        'stats': {
            'total_quantity': int(total_qty),
            'total_value': round(float(total_val), 2),
            'total_sku': int(total_sku),
        },
    }


async def create_record(
    db: AsyncSession,
    *,
    department: str,
    product_id: int | None,
    product_name: str,
    barcode: str,
    unit_price: float,
    quantity: int,
    production_date_str: str,
    remark: str = '',
    created_by: str = '',
) -> DailyProductionRecord:
    """创建生产记录"""
    validate_record_data(department, product_name, quantity, unit_price)
    prod_date = _parse_date(production_date_str)

    # 限制不能录入未来日期的数据
    if prod_date > date.today():
        raise ValueError('不能录入未来日期的生产数据')

    record = DailyProductionRecord(
        department=department,
        product_id=product_id,
        product_name=product_name.strip(),
        barcode=barcode or '',
        unit_price=unit_price,
        quantity=quantity,
        production_date=prod_date,
        remark=remark.strip() if remark else None,
        created_by=created_by,
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)
    logger.info(f'生产记录创建: {department} - {product_name} - {quantity} by {created_by}')
    return record


async def update_record(
    db: AsyncSession,
    record_id: int,
    *,
    created_by: str = '',
    **kwargs,
) -> DailyProductionRecord:
    """更新生产记录"""
    result = await db.execute(
        select(DailyProductionRecord).where(DailyProductionRecord.id == record_id)
    )
    record = result.scalar_one_or_none()
    if not record:
        raise ValueError('记录不存在')

    # 校验更新数据
    dept = kwargs.get('department', record.department)
    name = kwargs.get('product_name', record.product_name)
    qty = kwargs.get('quantity', record.quantity)
    price = kwargs.get('unit_price', record.unit_price)
    validate_record_data(dept, name, qty, price)

    for field in ('department', 'product_id', 'product_name', 'barcode', 'unit_price', 'quantity', 'remark'):
        if field in kwargs and kwargs[field] is not None:
            if field == 'product_name' and isinstance(kwargs[field], str):
                setattr(record, field, kwargs[field].strip())
            elif field == 'remark' and isinstance(kwargs[field], str):
                setattr(record, field, kwargs[field].strip() or None)
            else:
                setattr(record, field, kwargs[field])
    if 'production_date' in kwargs and kwargs['production_date'] is not None:
        new_date = _parse_date(kwargs['production_date'])
        if new_date > date.today():
            raise ValueError('不能将生产日期修改为未来日期')
        record.production_date = new_date

    await db.commit()
    await db.refresh(record)
    logger.info(f'生产记录更新: {record_id} by {created_by}')
    return record


async def delete_record(db: AsyncSession, record_id: int) -> None:
    """删除生产记录"""
    result = await db.execute(
        select(DailyProductionRecord).where(DailyProductionRecord.id == record_id)
    )
    record = result.scalar_one_or_none()
    if not record:
        raise ValueError('记录不存在')
    await db.delete(record)
    await db.commit()
    logger.info(f'生产记录删除: {record_id}')


# ==================== 每日汇总 ====================

async def get_daily_summary(db: AsyncSession, target_date: str) -> dict:
    """获取指定日期的各部门汇总"""
    d = _parse_date(target_date)
    result = await db.execute(
        select(DailyProductionRecord)
        .where(DailyProductionRecord.production_date == d)
        .order_by(DailyProductionRecord.department, DailyProductionRecord.id)
    )
    records = list(result.scalars().all())

    dept_data = {}
    for r in records:
        dept = r.department
        if dept not in dept_data:
            dept_data[dept] = {'quantity': 0, 'value': 0.0, 'skus': set()}
        dept_data[dept]['quantity'] += r.quantity
        dept_data[dept]['value'] += float(r.unit_price or 0) * r.quantity
        if r.product_name:
            dept_data[dept]['skus'].add(r.product_name)

    departments = []
    overall_quantity = 0
    overall_value = 0.0
    overall_skus = set()

    for dept_key in ('filling', 'handcraft', 'packaging'):
        d_info = dept_data.get(dept_key, {'quantity': 0, 'value': 0.0, 'skus': set()})
        overall_quantity += d_info['quantity']
        overall_value += d_info['value']
        overall_skus.update(d_info['skus'])
        departments.append({
            'department': dept_key,
            'department_label': DEPARTMENT_LABELS.get(dept_key, dept_key),
            'total_quantity': d_info['quantity'],
            'total_value': round(d_info['value'], 2),
            'sku_count': len(d_info['skus']),
        })

    return {
        'date': target_date,
        'departments': departments,
        'overall_quantity': overall_quantity,
        'overall_value': round(overall_value, 2),
        'overall_sku_count': len(overall_skus),
    }


# ==================== 月度汇总 ====================

async def get_monthly_summary(db: AsyncSession, year: int, month: int) -> dict:
    """获取月度汇总数据"""
    start = date(year, month, 1)
    end = date(year, month, calendar.monthrange(year, month)[1])
    days_in_month = calendar.monthrange(year, month)[1]

    # 按日+部门聚合
    result = await db.execute(
        select(
            DailyProductionRecord.production_date,
            DailyProductionRecord.department,
            func.coalesce(func.sum(DailyProductionRecord.quantity), 0).label('total_qty'),
            func.coalesce(func.sum(DailyProductionRecord.unit_price * DailyProductionRecord.quantity), 0).label('total_val'),
            func.count(func.distinct(DailyProductionRecord.product_name)).label('sku_count'),
        )
        .where(and_(
            DailyProductionRecord.production_date >= start,
            DailyProductionRecord.production_date <= end,
        ))
        .group_by(DailyProductionRecord.production_date, DailyProductionRecord.department)
        .order_by(DailyProductionRecord.production_date, DailyProductionRecord.department)
    )
    rows = result.all()

    # 组织为 daily_data
    daily_map: dict[str, dict] = {}
    for row in rows:
        d_str = row.production_date.isoformat()
        if d_str not in daily_map:
            daily_map[d_str] = {
                'date': d_str,
                'day': row.production_date.day,
                'filling': {'quantity': 0, 'value': 0.0, 'sku_count': 0},
                'handcraft': {'quantity': 0, 'value': 0.0, 'sku_count': 0},
                'packaging': {'quantity': 0, 'value': 0.0, 'sku_count': 0},
            }
        dept = row.department
        if dept in ('filling', 'handcraft', 'packaging'):
            daily_map[d_str][dept] = {
                'quantity': int(row.total_qty),
                'value': round(float(row.total_val), 2),
                'sku_count': int(row.sku_count),
            }

    daily_data = []
    for day in range(1, days_in_month + 1):
        d_str = date(year, month, day).isoformat()
        entry = daily_map.get(d_str, {
            'date': d_str,
            'day': day,
            'filling': {'quantity': 0, 'value': 0.0, 'sku_count': 0},
            'handcraft': {'quantity': 0, 'value': 0.0, 'sku_count': 0},
            'packaging': {'quantity': 0, 'value': 0.0, 'sku_count': 0},
        })
        entry['day'] = day
        entry['total'] = {
            'quantity': entry['filling']['quantity'] + entry['handcraft']['quantity'] + entry['packaging']['quantity'],
            'value': round(entry['filling']['value'] + entry['handcraft']['value'] + entry['packaging']['value'], 2),
            'sku_count': entry['filling']['sku_count'] + entry['handcraft']['sku_count'] + entry['packaging']['sku_count'],
        }
        daily_data.append(entry)

    # 月度部门汇总
    monthly_depts = []
    for dept_key in ('filling', 'handcraft', 'packaging'):
        dept_total_qty = sum(d[dept_key]['quantity'] for d in daily_data)
        dept_total_val = round(sum(d[dept_key]['value'] for d in daily_data), 2)
        dept_total_sku = sum(d[dept_key]['sku_count'] for d in daily_data)
        monthly_depts.append({
            'department': dept_key,
            'department_label': DEPARTMENT_LABELS.get(dept_key, dept_key),
            'total_quantity': dept_total_qty,
            'total_value': dept_total_val,
            'sku_count': dept_total_sku,
        })

    return {
        'year': year,
        'month': month,
        'daily_data': daily_data,
        'monthly_departments': monthly_depts,
        'monthly_total_quantity': sum(d['total']['quantity'] for d in daily_data),
        'monthly_total_value': round(sum(d['total']['value'] for d in daily_data), 2),
    }


async def get_monthly_summary_for_auto(
    db: AsyncSession,
    year: int,
    month: int,
) -> dict:
    """月度自动汇总（用于定时任务），与 get_monthly_summary 相同逻辑但独立入口便于扩展"""
    return await get_monthly_summary(db, year, month)


# ==================== 导出 ====================

async def export_records(
    db: AsyncSession,
    *,
    start_date: str = '',
    end_date: str = '',
    department: str = '',
) -> bytes:
    """导出生产记录为 Excel（企业标准格式）"""
    conditions = []
    if start_date:
        conditions.append(DailyProductionRecord.production_date >= _parse_date(start_date))
    if end_date:
        conditions.append(DailyProductionRecord.production_date <= _parse_date(end_date))
    if department:
        conditions.append(DailyProductionRecord.department == department)

    query = select(DailyProductionRecord).order_by(
        DailyProductionRecord.production_date,
        DailyProductionRecord.department,
        DailyProductionRecord.id,
    )
    if conditions:
        query = query.where(*conditions)

    result = await db.execute(query)
    records = list(result.scalars().all())

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = '生产报表'

    # 样式定义
    header_fill = PatternFill(start_color='B0E0E6', end_color='B0E0E6', fill_type='solid')
    header_font = Font(bold=True, size=11, color='5A4A4A')
    header_align = Alignment(horizontal='center', vertical='center')
    thin_border = Border(
        left=Side(style='thin', color='D4F1F4'),
        right=Side(style='thin', color='D4F1F4'),
        top=Side(style='thin', color='D4F1F4'),
        bottom=Side(style='thin', color='D4F1F4'),
    )
    summary_fill = PatternFill(start_color='F0F9FF', end_color='F0F9FF', fill_type='solid')
    summary_font = Font(bold=True, size=11, color='1d4ed8')

    # 标题行
    headers = ['生产日期', '部门', '产品名称', '69码', '单价', '数量', '产值', '备注', '创建人', '创建时间']
    ws.append(headers)
    for cell in ws[1]:
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = header_align
        cell.border = thin_border

    # 数据行
    total_qty = 0
    total_val = 0.0
    for r in records:
        val = round(float(r.unit_price or 0) * r.quantity, 2)
        total_qty += r.quantity
        total_val += val
        ws.append([
            r.production_date.isoformat() if r.production_date else '',
            DEPARTMENT_LABELS.get(r.department, r.department),
            r.product_name,
            r.barcode or '',
            float(r.unit_price) if r.unit_price else 0,
            r.quantity,
            val,
            r.remark or '',
            r.created_by or '',
            r.create_time.strftime('%Y-%m-%d %H:%M:%S') if r.create_time else '',
        ])

    # 数据行样式
    for row in ws.iter_rows(min_row=2, max_row=ws.max_row):
        for cell in row:
            cell.border = thin_border
            cell.alignment = Alignment(vertical='center')

    # 空数据提示
    if not records:
        ws.append(['暂无数据', '', '', '', '', '', '', '', '', ''])

    # 汇总行
    ws.append(['全部门合计', '', '', '', '', total_qty, round(total_val, 2), '', '', ''])
    for cell in ws[ws.max_row]:
        cell.fill = summary_fill
        cell.font = summary_font
        cell.border = thin_border

    # 按部门汇总
    ws.append([])
    ws.append(['部门汇总', '生产数量', '产值', '', '', '', '', '', '', ''])
    for cell in ws[ws.max_row]:
        cell.fill = header_fill
        cell.font = header_font
        cell.border = thin_border

    dept_summary: dict[str, dict] = {}
    for r in records:
        dept = r.department
        if dept not in dept_summary:
            dept_summary[dept] = {'quantity': 0, 'value': 0.0}
        dept_summary[dept]['quantity'] += r.quantity
        dept_summary[dept]['value'] += float(r.unit_price or 0) * r.quantity

    for dept_key in ('filling', 'handcraft', 'packaging'):
        if dept_key in dept_summary:
            ws.append([
                DEPARTMENT_LABELS.get(dept_key, dept_key),
                dept_summary[dept_key]['quantity'],
                round(dept_summary[dept_key]['value'], 2),
                '', '', '', '', '', '', '',
            ])
            for cell in ws[ws.max_row]:
                cell.border = thin_border

    # 列宽
    col_widths = [12, 10, 32, 15, 10, 10, 12, 24, 10, 20]
    for i, w in enumerate(col_widths, 1):
        ws.column_dimensions[openpyxl.utils.get_column_letter(i)].width = w

    # 冻结首行
    ws.freeze_panes = 'A2'

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    return output.getvalue()


# ==================== 产品清单集成 ====================

async def get_product_for_production(
    db: AsyncSession,
    product_id: int,
) -> dict | None:
    """获取产品信息用于生产记录（集成产品清单API）"""
    from fastapi_app.shared_models import Product
    result = await db.execute(
        select(Product).where(Product.id == product_id)
    )
    product = result.scalar_one_or_none()
    if not product:
        return None
    return {
        'id': product.id,
        'name': product.name,
        'barcode': product.barcode or '',
        'price': float(product.price) if hasattr(product, 'price') and product.price else 0,
    }
