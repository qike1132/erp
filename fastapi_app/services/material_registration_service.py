"""来料登记服务层"""
import io
import json
import logging
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import xlsxwriter
from sqlalchemy import func, select
from sqlalchemy.exc import DisconnectionError, OperationalError
from sqlalchemy.orm import joinedload, selectinload

from fastapi_app.core.cache import cache_result
from fastapi_app.core.exceptions import BusinessError
from fastapi_app.core.sanitizer import escape_like
from fastapi_app.shared_models import (
    MaterialRegistration,
    MaterialRegistrationItem,
    Order,
    PurchaseOrder,
    PurchaseOrderItem,
)
from fastapi_app.utils import calc_total_pages

logger = logging.getLogger(__name__)


def _parse_filter_date(date_str: str, field_name: str) -> date:
    """严格解析筛选日期，非法格式抛 400 业务异常（不再静默忽略）"""
    try:
        return datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        raise BusinessError(f'{field_name}格式错误，应为 YYYY-MM-DD') from None


@cache_result(key_prefix="material:registrations", ttl=30, local_ttl=10,
             key_builder=lambda **kw: f"{kw.get('page',1)}:{kw.get('per_page',20)}:{kw.get('status','')}:{kw.get('order_no','')}:{kw.get('supplier','')}:{kw.get('customer_name','')}:{kw.get('material_category','')}:{kw.get('start_date','')}:{kw.get('end_date','')}:{kw.get('exclude_completed',False)}")
async def get_registrations(db, page: int = 1, per_page: int = 20,
                           status: str = '', order_no: str = '', supplier: str = '',
                           customer_name: str = '', material_category: str = '',
                           start_date: str = '', end_date: str = '',
                           exclude_completed: bool = False) -> dict:
    """获取来料登记列表

    支持多维度筛选；当 exclude_completed=True 时排除已完成的登记（用于来料进度 tab）。
    L1 10s + L2 30s 缓存，写操作时通过 MATERIAL 域失效。
    """
    # Build filter conditions once, apply to both data query and count query
    conditions = []
    if status:
        conditions.append(MaterialRegistration.status == status)
    elif exclude_completed:
        conditions.append(MaterialRegistration.status != 'completed')
    if order_no:
        conditions.append(MaterialRegistration.purchase_order_no.ilike(f'%{escape_like(order_no)}%'))
    if supplier:
        conditions.append(MaterialRegistration.supplier_name.ilike(f'%{escape_like(supplier)}%'))
    if customer_name:
        conditions.append(PurchaseOrder.customer_name.ilike(f'%{escape_like(customer_name)}%'))
    if start_date:
        conditions.append(MaterialRegistration.registration_date >= _parse_filter_date(start_date, '开始日期'))
    if end_date:
        conditions.append(MaterialRegistration.registration_date <= _parse_filter_date(end_date, '结束日期'))
    if material_category:
        conditions.append(
            MaterialRegistration.items.any(MaterialRegistrationItem.material_category == material_category)
        )

    needs_po_join = bool(customer_name)
    base_query = select(MaterialRegistration)
    if needs_po_join:
        base_query = base_query.join(MaterialRegistration.purchase_order)
    query = base_query.options(
        selectinload(MaterialRegistration.items),
        selectinload(MaterialRegistration.purchase_order),
    ).where(*conditions)

    total_q = select(func.count(MaterialRegistration.id))
    if needs_po_join:
        total_q = total_q.join(MaterialRegistration.purchase_order)
    total_q = total_q.where(*conditions)
    total = (await db.execute(total_q)).scalar() or 0

    query = query.order_by(MaterialRegistration.create_time.desc())
    offset = (page - 1) * per_page
    query = query.offset(offset).limit(per_page)
    result = await db.execute(query)
    registrations = list(result.scalars().all())

    return {
        'success': True,
        'registrations': [r.to_dict() for r in registrations],
        'total': total,
        'pages': calc_total_pages(total, per_page),
        'current_page': page,
    }


async def get_registration(db, reg_id: int) -> dict:
    """获取来料登记详情"""
    result = await db.execute(
        select(MaterialRegistration).options(
            selectinload(MaterialRegistration.items),
            selectinload(MaterialRegistration.purchase_order),
        ).where(MaterialRegistration.id == reg_id)
    )
    reg = result.scalar_one_or_none()
    if not reg:
        raise ValueError("来料登记不存在")
    return {'success': True, 'registration': reg.to_dict()}


def _compute_pct(ordered: float, received: float) -> float:
    """计算完成百分比：全部到货返回 100，否则上限 99.9（与前端 computePct 对齐）"""
    if ordered <= 0:
        return 0.0
    if received >= ordered:
        return 100.0
    return min(round(received / ordered * 100 * 10) / 10, 99.9)


@cache_result(key_prefix="material:supplier_detail", ttl=30, local_ttl=10,
             key_builder=lambda **kw: kw.get('order_no', ''))
async def get_supplier_detail(db, order_no: str) -> dict:
    """获取按供应商分组的来料聚合详情（服务端预聚合，消除前端 60+ 行同步计算）。

    查询指定 order_no 的未完成登记，遍历所有 items（排除 filling 类），
    按 reg.supplier_name 分组，组内按 material_name 合并数量并计算进度。
    L1 10s + L2 30s 缓存，写操作时通过 MATERIAL 域失效。
    """
    query = (
        select(MaterialRegistration)
        .options(selectinload(MaterialRegistration.items))
        .where(
            MaterialRegistration.purchase_order_no == order_no,
            MaterialRegistration.status != 'completed',
        )
    )
    result = await db.execute(query)
    registrations = list(result.scalars().all())

    # supplier_name -> {material_name -> mat_info}
    supplier_map: dict[str, dict[str, dict]] = {}

    for reg in registrations:
        sup_name = reg.supplier_name or '未指定'
        mat_map = supplier_map.setdefault(sup_name, {})
        for item in reg.items:
            if (item.material_category or '') == 'filling':
                continue
            ordered = float(item.ordered_quantity or 0)
            received = float(item.received_quantity or 0)
            mat_name = item.material_name
            existing = mat_map.get(mat_name)
            if existing:
                existing['ordered'] += ordered
                existing['received'] += received
                existing['remaining'] = existing['ordered'] - existing['received']
                existing['pct'] = _compute_pct(existing['ordered'], existing['received'])
                existing['sub_items'].append({'id': item.id, 'ordered': ordered, 'received': received})
            else:
                mat_map[mat_name] = {
                    'name': mat_name,
                    'ordered': ordered,
                    'received': received,
                    'remaining': ordered - received,
                    'pct': _compute_pct(ordered, received),
                    'sub_items': [{'id': item.id, 'ordered': ordered, 'received': received}],
                    'unit': item.unit or '',
                    'spec': item.specification or '',
                }

    all_ordered = 0.0
    all_received = 0.0
    supplier_groups = []
    for sup_name, mat_map in supplier_map.items():
        items = list(mat_map.values())
        o_total = sum(m['ordered'] for m in items)
        r_total = sum(m['received'] for m in items)
        all_ordered += o_total
        all_received += r_total
        all_complete = all(m['received'] >= m['ordered'] for m in items)
        supplier_groups.append({
            'supplier_name': sup_name,
            'items': items,
            'total_ordered': o_total,
            'total_received': r_total,
            'pct': _compute_pct(o_total, o_total if all_complete else r_total),
        })

    all_complete = all(
        m['received'] >= m['ordered']
        for g in supplier_groups
        for m in g['items']
    )
    total_pct = _compute_pct(all_ordered, all_ordered if all_complete else all_received)

    return {
        'success': True,
        'supplier_groups': supplier_groups,
        'total_ordered': all_ordered,
        'total_received': all_received,
        'total_pct': total_pct,
    }


async def create_registration(db, purchase_order_id: int, user_id: int | None = None,
                              username: str = '未知', remark: str = '',
                              items_data: list[dict] | None = None) -> dict:
    """创建来料登记"""
    po = await db.get(PurchaseOrder, purchase_order_id)
    if not po:
        raise ValueError("采购订单不存在")

    reg = MaterialRegistration(
        purchase_order_id=purchase_order_id,
        purchase_order_no=po.order_no,
        supplier_id=po.supplier_id,
        supplier_name=po.supplier_name,
        registration_date=datetime.now(UTC).replace(tzinfo=None).date(),
        status='pending',
        remark=remark,
        created_by=user_id,
    )
    db.add(reg)
    await db.flush()

    items_data = items_data or []
    for item_data in items_data:
        item = MaterialRegistrationItem(
            registration_id=reg.id,
            order_item_id=item_data.get('order_item_id'),
            material_code=item_data.get('material_code', ''),
            material_name=item_data.get('material_name', ''),
            specification=item_data.get('specification', ''),
            unit=item_data.get('unit', ''),
            ordered_quantity=Decimal(str(item_data.get('ordered_quantity', 0))),
            received_quantity=Decimal(str(item_data.get('received_quantity', 0))),
            material_category=item_data.get('material_category', ''),
            remark=item_data.get('remark', ''),
        )
        db.add(item)

    await db.flush()
    return {'success': True, 'message': '来料登记创建成功', 'registration': reg.to_dict()}


async def update_registration(db, reg_id: int, status: str | None = None,
                              remark: str | None = None, items: list[dict] | None = None) -> dict:
    """更新来料登记"""
    result = await db.execute(
        select(MaterialRegistration)
        .options(
            selectinload(MaterialRegistration.items),
            joinedload(MaterialRegistration.purchase_order),
        )
        .where(MaterialRegistration.id == reg_id)
    )
    reg = result.unique().scalar_one_or_none()
    if not reg:
        raise ValueError("来料登记不存在")

    if status is not None:
        reg.status = status
    if remark is not None:
        reg.remark = remark

    if items is not None:
        for item_data in items:
            item_id = item_data.get('id')
            if item_id:
                item = await db.get(MaterialRegistrationItem, item_id)
                if item and item.registration_id == reg_id:
                    if 'received_quantity' in item_data:
                        item.received_quantity = Decimal(str(item_data['received_quantity']))
                    if 'remark' in item_data:
                        item.remark = item_data['remark']

    # 自动更新状态
    reg.update_status()

    return {'success': True, 'message': '更新成功', 'registration': reg.to_dict()}


async def delete_registration(db, reg_id: int) -> dict:
    """删除来料登记"""
    reg = await db.get(MaterialRegistration, reg_id)
    if not reg:
        raise ValueError("来料登记不存在")
    await db.delete(reg)
    await db.flush()
    return {'success': True, 'message': '删除成功'}


async def get_available_purchase_orders(db, status: str = 'pending') -> dict:
    """获取可用于来料登记的采购订单"""
    query = select(PurchaseOrder).options(joinedload(PurchaseOrder.items))
    if status:
        query = query.where(PurchaseOrder.status == status)
    query = query.order_by(PurchaseOrder.create_time.desc()).limit(50)
    result = await db.execute(query)
    orders = list(result.unique().scalars().all())

    return {
        'success': True,
        'orders': [{
            'id': o.id, 'order_no': o.order_no, 'supplier_name': o.supplier_name,
            'customer_name': o.customer_name,
            'order_date': o.order_date.strftime('%Y-%m-%d') if o.order_date else None,
            'status': o.status, 'item_count': len(o.items),
            'items': [i.to_dict() for i in o.items],
        } for o in orders]
    }


async def receive_material(db, item_id: int, received_quantity: float,
                           remark: str | None = None) -> dict:
    """物料收货登记

    使用 SELECT ... FOR UPDATE 悲观锁，防止并发收货导致 received_quantity 丢失更新。
    purchase_order 改用 selectinload 单独加载，避免 FOR UPDATE 锁定采购订单表。
    """
    result = await db.execute(
        select(MaterialRegistrationItem)
        .options(
            selectinload(MaterialRegistrationItem.registration).selectinload(MaterialRegistration.items),
            selectinload(MaterialRegistrationItem.registration).selectinload(MaterialRegistration.purchase_order),
        )
        .where(MaterialRegistrationItem.id == item_id)
        .with_for_update()
    )
    item = result.unique().scalar_one_or_none()
    if not item:
        raise ValueError("物料明细不存在")

    if received_quantity <= 0:
        raise ValueError("收货数量必须大于0")

    old_qty = item.received_quantity or Decimal('0')
    new_qty = old_qty + Decimal(str(received_quantity))
    if new_qty > (item.ordered_quantity or Decimal('0')):
        raise ValueError("收货数量不能超过采购数量")
    item.received_quantity = new_qty
    if remark:
        item.remark = remark

    # 更新状态
    reg = item.registration
    reg.update_status()
    await db.flush()

    logger.info("收货登记成功 item_id=%s, %s→%s (+%s), 状态=%s",
                item_id, old_qty, item.received_quantity, received_quantity, reg.status)

    return {
        'success': True, 'message': '收货登记成功',
        'registration': reg.to_dict(),
    }


@cache_result(key_prefix="material:overview", ttl=60, local_ttl=15,
             key_builder=lambda *a, **kw: "global")
async def get_stats_overview(db) -> dict:
    """统计概览（L1 15s + L2 60s 缓存，写操作时通过 MATERIAL 域失效）"""
    status_counts_result = await db.execute(
        select(MaterialRegistration.status, func.count())
        .where(MaterialRegistration.status.in_(['pending', 'partial', 'completed']))
        .group_by(MaterialRegistration.status)
    )
    status_counts = {row[0]: row[1] for row in status_counts_result}
    pending = status_counts.get('pending', 0)
    partial = status_counts.get('partial', 0)
    completed = status_counts.get('completed', 0)
    total_all_num = sum(status_counts.values())

    totals_result = await db.execute(
        select(
            func.sum(MaterialRegistrationItem.ordered_quantity),
            func.sum(MaterialRegistrationItem.received_quantity),
        )
    )
    totals_row = totals_result.one()
    total_ordered = totals_row[0] or 0
    total_received = totals_row[1] or 0

    today = datetime.now(UTC).replace(tzinfo=None).date()
    week_ago = today - timedelta(days=7)

    recent = (await db.execute(
        select(func.count()).where(MaterialRegistration.registration_date >= week_ago)
    )).scalar() or 0

    return {
        'success': True,
        'overview': {
            'total': total_all_num, 'pending': pending, 'partial': partial,
            'completed': completed,
            'total_ordered': float(total_ordered),
            'total_received': float(total_received),
            'total_remaining': float(total_ordered) - float(total_received),
            'overall_progress': min(round(float(total_received) / float(total_ordered or 1) * 100, 1), 99.9) if completed < total_all_num else (100.0 if total_all_num > 0 else 0),
            'recent_registrations': recent,
        }
    }


async def get_purchase_order_items(db, order_id: int) -> dict:
    """获取采购订单物料明细"""
    po = await db.get(PurchaseOrder, order_id)
    if not po:
        raise ValueError("采购订单不存在")
    result = await db.execute(
        select(PurchaseOrderItem).where(PurchaseOrderItem.order_id == order_id)
    )
    items = list(result.scalars().all())
    return {'success': True, 'items': [item.to_dict() for item in items]}


async def preview_purchase_order(db, order_no: str) -> dict:
    """采购订单快速预览"""
    result = await db.execute(
        select(PurchaseOrder)
        .options(joinedload(PurchaseOrder.items))
        .where(PurchaseOrder.order_no == order_no)
    )
    order = result.unique().scalar_one_or_none()
    if not order:
        raise ValueError("订单不存在")

    # Fetch source sales orders info
    source_orders = {}
    source_order_ids = set()
    if order.source_order_id:
        source_order_ids.add(order.source_order_id)
    if order.source_order_ids:
        try:
            for sid in json.loads(order.source_order_ids):
                if sid:
                    source_order_ids.add(sid)
        except (json.JSONDecodeError, TypeError):
            pass  # defensive: 异常静默处理,不影响主流程
    if source_order_ids:
        so_result = await db.execute(
            select(Order).options(joinedload(Order.product)).where(Order.id.in_(source_order_ids))
        )
        for so in so_result.unique().scalars().all():
            source_orders[so.id] = so

    order_dict = order.to_dict(source_orders=source_orders)
    order_dict['source_order_ids'] = order.source_order_ids

    # Enrich source order details for display
    source_details = []
    for so in source_orders.values():
        detail: dict = {'id': so.id, 'order_no': so.order_no}
        if hasattr(so, 'product') and so.product:
            detail['product_name'] = so.product.name
        if hasattr(so, 'quantity') and so.quantity:
            detail['quantity'] = float(so.quantity)
        detail['customer_name'] = so.customer if hasattr(so, 'customer') else None
        source_details.append(detail)
    order_dict['source_orders'] = source_details

    return {'success': True, 'order': order_dict}


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


async def get_history(db, page: int = 1, per_page: int = 20,
                      order_no: str = '', supplier: str = '',
                      customer_name: str = '', material_category: str = '',
                      start_date: str = '', end_date: str = '') -> dict:
    # Build filter conditions (shared between count and data queries)
    conditions = [MaterialRegistration.status == 'completed']

    if order_no:
        conditions.append(MaterialRegistration.purchase_order_no.ilike(f'%{escape_like(order_no)}%'))
    if supplier:
        conditions.append(MaterialRegistration.supplier_name.ilike(f'%{escape_like(supplier)}%'))
    if customer_name:
        conditions.append(PurchaseOrder.customer_name.ilike(f'%{escape_like(customer_name)}%'))
    if start_date:
        conditions.append(MaterialRegistration.registration_date >= _parse_filter_date(start_date, '开始日期'))
    if end_date:
        conditions.append(MaterialRegistration.registration_date <= _parse_filter_date(end_date, '结束日期'))
    if material_category:
        conditions.append(
            MaterialRegistration.items.any(MaterialRegistrationItem.material_category == material_category)
        )

    # customer_name 筛选需要 JOIN purchase_order；count 与 data 查询共用同一 JOIN 决策
    needs_po_join = bool(customer_name)

    # Count query — no eager loading, just count
    count_query = select(func.count(MaterialRegistration.id))
    if needs_po_join:
        count_query = count_query.join(MaterialRegistration.purchase_order)
    count_query = count_query.where(*conditions)
    total = (await db.execute(count_query)).scalar() or 0

    # Data query — DB-level pagination with eager loading only for the page
    offset = (page - 1) * per_page
    data_query = select(MaterialRegistration).options(
        selectinload(MaterialRegistration.items),
        joinedload(MaterialRegistration.purchase_order),
    )
    if needs_po_join:
        data_query = data_query.join(MaterialRegistration.purchase_order)
    data_query = (
        data_query.where(*conditions)
        .order_by(MaterialRegistration.update_time.desc())
        .offset(offset)
        .limit(per_page)
    )
    result = await db.execute(data_query)
    page_regs = list(result.unique().scalars().all())

    return {
        'success': True,
        'registrations': [r.to_dict() for r in page_regs],
        'total': total,
        'pages': calc_total_pages(total, per_page),
        'current_page': page,
    }


async def get_suggestions(db, field: str, keyword: str, limit: int = 10) -> dict:
    """获取搜索联想建议"""
    if not field or not keyword or len(keyword) < 1:
        return {'success': True, 'suggestions': []}

    suggestions = []
    try:
        if field == 'order_no':
            result = await db.execute(
                select(MaterialRegistration.purchase_order_no)
                .where(MaterialRegistration.purchase_order_no.ilike(f'%{escape_like(keyword)}%'))
                .distinct().limit(limit)
            )
            suggestions = [r[0] for r in result.all() if r[0]]
        elif field == 'supplier':
            result = await db.execute(
                select(MaterialRegistration.supplier_name)
                .where(MaterialRegistration.supplier_name.ilike(f'%{escape_like(keyword)}%'))
                .distinct().limit(limit)
            )
            suggestions = [r[0] for r in result.all() if r[0]]
        elif field == 'material_name':
            result = await db.execute(
                select(MaterialRegistrationItem.material_name)
                .where(MaterialRegistrationItem.material_name.ilike(f'%{escape_like(keyword)}%'))
                .distinct().limit(limit)
            )
            suggestions = [r[0] for r in result.all() if r[0]]
    except (OperationalError, DisconnectionError) as e:
        logger.error(f"获取联想建议失败: {e}")

    return {'success': True, 'suggestions': suggestions[:limit]}


@cache_result(key_prefix="material:distribution", ttl=60, local_ttl=15,
             key_builder=lambda *a, **kw: "global")
async def get_stats_distribution(db) -> dict:
    """状态分布（L1 15s + L2 60s 缓存，写操作时通过 MATERIAL 域失效）"""
    status_counts_result = await db.execute(
        select(MaterialRegistration.status, func.count())
        .where(MaterialRegistration.status.in_(['pending', 'partial', 'completed']))
        .group_by(MaterialRegistration.status)
    )
    status_counts = {row[0]: row[1] for row in status_counts_result}
    pending = status_counts.get('pending', 0)
    partial = status_counts.get('partial', 0)
    completed = status_counts.get('completed', 0)

    month_ago = datetime.now(UTC).replace(tzinfo=None).date() - timedelta(days=30)
    overdue_items = (await db.execute(
        select(func.count(MaterialRegistrationItem.id)).where(
            MaterialRegistrationItem.ordered_quantity > MaterialRegistrationItem.received_quantity,
            MaterialRegistration.registration_date < month_ago
        ).join(MaterialRegistration)
    )).scalar() or 0

    return {
        'success': True,
        'distribution': [
            {'status': 'pending', 'count': pending},
            {'status': 'partial', 'count': partial},
            {'status': 'completed', 'count': completed},
            {'status': 'overdue', 'count': overdue_items},
        ]
    }


@cache_result(key_prefix="material:trend", ttl=60, local_ttl=15,
             key_builder=lambda **kwargs: str(kwargs.get('days', 30)))
async def get_stats_trend(db, days: int = 30) -> dict:
    """趋势数据（SQL GROUP BY 替代全量 ORM 加载，L1 15s + L2 60s 缓存）"""
    end_date = datetime.now(UTC).replace(tzinfo=None).date()
    start_date = end_date - timedelta(days=days)

    # 生成完整日期骨架
    date_map = {}
    current = start_date
    while current <= end_date:
        date_map[current.strftime('%Y-%m-%d')] = {'registered': 0, 'received': 0}
        current += timedelta(days=1)

    # SQL 聚合：只返回 date + count，不加载 ORM 对象
    reg_counts = (await db.execute(
        select(MaterialRegistration.registration_date, func.count())
        .where(
            MaterialRegistration.registration_date >= start_date,
            MaterialRegistration.registration_date <= end_date
        )
        .group_by(MaterialRegistration.registration_date)
    )).all()

    for reg_date, cnt in reg_counts:
        key = reg_date.strftime('%Y-%m-%d') if reg_date else None
        if key and key in date_map:
            date_map[key]['registered'] = cnt

    trend = [{'date': k, **v} for k, v in sorted(date_map.items())]

    return {'success': True, 'trend': trend}
