"""来料登记服务层"""
import logging
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.exc import DisconnectionError, OperationalError
from sqlalchemy.orm import joinedload, selectinload

from fastapi_app.core.cache import cache_result, invalidate_cache, CacheDomain, invalidate_related_caches
from fastapi_app.services import escape_like
from fastapi_app.shared_models import (
    MaterialRegistration,
    MaterialRegistrationItem,
    Order,
    PurchaseOrder,
    PurchaseOrderItem,
)

logger = logging.getLogger(__name__)


async def _get_material_stats(db) -> dict:
    """获取来料统计数据（独立缓存，不随列表请求每次执行）"""
    status_counts_result = await db.execute(
        select(MaterialRegistration.status, func.count())
        .where(MaterialRegistration.status.in_(['pending', 'partial', 'completed']))
        .group_by(MaterialRegistration.status)
    )
    status_counts = {row[0]: row[1] for row in status_counts_result}
    pending_count = status_counts.get('pending', 0)
    partial_count = status_counts.get('partial', 0)
    completed_count = status_counts.get('completed', 0)
    total_all = sum(status_counts.values())

    totals_result = await db.execute(
        select(
            func.sum(MaterialRegistrationItem.ordered_quantity),
            func.sum(MaterialRegistrationItem.received_quantity),
        )
    )
    totals_row = totals_result.one()
    total_ordered = totals_row[0] or 0
    total_received = totals_row[1] or 0

    return {
        'total': total_all, 'pending': pending_count, 'partial': partial_count,
        'completed': completed_count,
        'total_ordered': float(total_ordered), 'total_received': float(total_received),
        'overall_progress': min(round(float(total_received) / float(total_ordered or 1) * 100, 1), 99.9) if completed_count < total_all else (100.0 if total_all > 0 else 0),
    }


async def get_registrations(db, page: int = 1, per_page: int = 20,
                           status: str = '', order_no: str = '', supplier: str = '',
                           start_date: str = '', end_date: str = '') -> dict:
    """获取来料登记列表"""
    query = select(MaterialRegistration).options(
        selectinload(MaterialRegistration.items),
        selectinload(MaterialRegistration.purchase_order),
    )

    if status:
        query = query.where(MaterialRegistration.status == status)
    if order_no:
        query = query.where(MaterialRegistration.purchase_order_no.ilike(f'%{escape_like(order_no)}%'))
    if supplier:
        query = query.where(MaterialRegistration.supplier_name.ilike(f'%{escape_like(supplier)}%'))
    if start_date:
        try:
            sd = datetime.strptime(start_date, '%Y-%m-%d').date()
            query = query.where(MaterialRegistration.registration_date >= sd)
        except ValueError:
            pass
    if end_date:
        try:
            ed = datetime.strptime(end_date, '%Y-%m-%d').date()
            query = query.where(MaterialRegistration.registration_date <= ed)
        except ValueError:
            pass

    count_conditions = []
    if status:
        count_conditions.append(MaterialRegistration.status == status)
    if order_no:
        count_conditions.append(MaterialRegistration.purchase_order_no.ilike(f'%{escape_like(order_no)}%'))
    if supplier:
        count_conditions.append(MaterialRegistration.supplier_name.ilike(f'%{escape_like(supplier)}%'))
    if start_date:
        try:
            sd = datetime.strptime(start_date, '%Y-%m-%d').date()
            count_conditions.append(MaterialRegistration.registration_date >= sd)
        except ValueError:
            pass
    if end_date:
        try:
            ed = datetime.strptime(end_date, '%Y-%m-%d').date()
            count_conditions.append(MaterialRegistration.registration_date <= ed)
        except ValueError:
            pass
    total_q = select(func.count(MaterialRegistration.id)).where(*count_conditions)
    total = (await db.execute(total_q)).scalar() or 0

    query = query.order_by(MaterialRegistration.create_time.desc())
    offset = (page - 1) * per_page
    query = query.offset(offset).limit(per_page)
    result = await db.execute(query)
    registrations = list(result.scalars().all())

    stats = await _get_material_stats(db)

    return {
        'success': True,
        'registrations': [r.to_dict() for r in registrations],
        'total': total,
        'pages': (total + per_page - 1) // per_page if per_page else 0,
        'current_page': page,
        'stats': stats,
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
        registration_date=datetime.now().date(),
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
    """物料收货登记"""
    result = await db.execute(
        select(MaterialRegistrationItem)
        .options(
            joinedload(MaterialRegistrationItem.registration).selectinload(MaterialRegistration.items),
            joinedload(MaterialRegistrationItem.registration).joinedload(MaterialRegistration.purchase_order),
        )
        .where(MaterialRegistrationItem.id == item_id)
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


async def get_stats_overview(db) -> dict:
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

    today = datetime.now().date()
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
            import json
            for sid in json.loads(order.source_order_ids):
                if sid:
                    source_order_ids.add(sid)
        except (json.JSONDecodeError, TypeError):
            pass
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


async def export_registrations(db, order_no: str = '', supplier: str = '',
                               start_date: str = '', end_date: str = '') -> dict:
    """导出来料登记数据（返回HTML用于Excel打开）"""
    query = select(MaterialRegistration).options(
        selectinload(MaterialRegistration.items),
        selectinload(MaterialRegistration.purchase_order),
    )
    if order_no:
        query = query.where(MaterialRegistration.purchase_order_no.ilike(f'%{escape_like(order_no)}%'))
    if supplier:
        query = query.where(MaterialRegistration.supplier_name.ilike(f'%{escape_like(supplier)}%'))
    if start_date:
        try:
            sd = datetime.strptime(start_date, '%Y-%m-%d').date()
            query = query.where(MaterialRegistration.registration_date >= sd)
        except ValueError:
            pass
    if end_date:
        try:
            ed = datetime.strptime(end_date, '%Y-%m-%d').date()
            query = query.where(MaterialRegistration.registration_date <= ed)
        except ValueError:
            pass

    query = query.order_by(MaterialRegistration.create_time.desc()).limit(5000)
    result = await db.execute(query)
    registrations = list(result.unique().scalars().all())

    status_map = {'pending': '待收货', 'partial': '部分收货', 'completed': '已完成'}
    html_parts = []
    html_parts.append('''<!DOCTYPE html>
<html xmlns:o="urn:schemas-microsoft-com:office:office"
      xmlns:x="urn:schemas-microsoft-com:office:excel"
      xmlns="http://www.w3.org/TR/REC-html40">
<head><meta charset="utf-8"><title>来料登记汇总</title>
<style>
@page { margin: 0in; }
body { font-family: 宋体; margin: 0; padding: 0; }
.header { text-align: center; margin-bottom: 10px; }
.header h1 { margin: 0; color: #333; font-size: 24pt; }
table { width: 100%; border-collapse: collapse; table-layout: fixed; }
th, td { border: 1.0pt solid #000000; padding: 1px; text-align: center; vertical-align: middle; font-size: 10.5pt; }
th { background: #E6E6E6; font-weight: bold; }
</style></head><body>
<div class="header"><h1>来料登记汇总</h1></div>
<table><thead><tr><th>登记日期</th><th>订单号</th><th>供应商</th><th>物料名称</th><th>规格</th><th>采购数量</th><th>已收货</th><th>状态</th></tr></thead><tbody>''')

    for reg in registrations:
        items = list(reg.items)
        computed_status = reg.computed_status
        if not items:
            html_parts.append(f'<tr><td>{reg.registration_date or "-"}</td><td>{reg.purchase_order_no}</td><td>{reg.supplier_name or "-"}</td><td>-</td><td>-</td><td>-</td><td>-</td><td>{status_map.get(computed_status, computed_status)}</td></tr>')
        else:
            for idx, item in enumerate(items):
                html_parts.append('<tr>')
                if idx == 0:
                    html_parts.append(f'<td rowspan="{len(items)}">{reg.registration_date or "-"}</td>')
                    html_parts.append(f'<td rowspan="{len(items)}">{reg.purchase_order_no}</td>')
                    html_parts.append(f'<td rowspan="{len(items)}">{reg.supplier_name or "-"}</td>')
                html_parts.append(f'<td>{item.material_name}</td>')
                html_parts.append(f'<td>{item.specification or "-"}</td>')
                html_parts.append(f'<td>{float(item.ordered_quantity or 0)}</td>')
                html_parts.append(f'<td>{float(item.received_quantity or 0)}</td>')
                if idx == 0:
                    html_parts.append(f'<td rowspan="{len(items)}">{status_map.get(computed_status, computed_status)}</td>')
                html_parts.append('</tr>')

    html_parts.append('</tbody></table></body></html>')
    return {'success': True, 'html': ''.join(html_parts)}


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
        try:
            sd = datetime.strptime(start_date, '%Y-%m-%d').date()
            conditions.append(MaterialRegistration.registration_date >= sd)
        except ValueError:
            pass
    if end_date:
        try:
            ed = datetime.strptime(end_date, '%Y-%m-%d').date()
            conditions.append(MaterialRegistration.registration_date <= ed)
        except ValueError:
            pass
    if material_category:
        conditions.append(
            MaterialRegistration.items.any(MaterialRegistrationItem.material_category == material_category)
        )

    # Count query — no eager loading, just count
    count_query = select(func.count(MaterialRegistration.id))
    if customer_name:
        count_query = count_query.join(MaterialRegistration.purchase_order)
    count_query = count_query.where(*conditions)
    total = (await db.execute(count_query)).scalar() or 0

    # Data query — DB-level pagination with eager loading only for the page
    offset = (page - 1) * per_page
    data_query = select(MaterialRegistration).options(
        selectinload(MaterialRegistration.items),
        joinedload(MaterialRegistration.purchase_order),
    )
    if customer_name:
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
        'pages': (total + per_page - 1) // per_page if per_page else 0,
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
    except (OperationalError, DisconnectionError, ValueError) as e:
        logger.error(f"获取联想建议失败: {e}")

    return {'success': True, 'suggestions': suggestions[:limit]}


async def get_stats_distribution(db) -> dict:
    status_counts_result = await db.execute(
        select(MaterialRegistration.status, func.count())
        .where(MaterialRegistration.status.in_(['pending', 'partial', 'completed']))
        .group_by(MaterialRegistration.status)
    )
    status_counts = {row[0]: row[1] for row in status_counts_result}
    pending = status_counts.get('pending', 0)
    partial = status_counts.get('partial', 0)
    completed = status_counts.get('completed', 0)

    month_ago = datetime.now().date() - timedelta(days=30)
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


async def get_stats_trend(db, days: int = 30) -> dict:
    """趋势数据"""
    end_date = datetime.now().date()
    start_date = end_date - timedelta(days=days)

    regs = (await db.execute(
        select(MaterialRegistration).where(
            MaterialRegistration.registration_date >= start_date,
            MaterialRegistration.registration_date <= end_date
        )
    )).scalars().all()

    date_map = {}
    current = start_date
    while current <= end_date:
        date_map[current.strftime('%Y-%m-%d')] = {'registered': 0, 'received': 0}
        current += timedelta(days=1)

    for reg in regs:
        key = reg.registration_date.strftime('%Y-%m-%d') if reg.registration_date else None
        if key and key in date_map:
            date_map[key]['registered'] += 1

    trend = [{'date': k, **v} for k, v in sorted(date_map.items())]

    return {'success': True, 'trend': trend}
