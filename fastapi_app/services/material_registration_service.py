"""来料登记服务层"""
import logging
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.exc import DisconnectionError, OperationalError
from sqlalchemy.orm import joinedload, selectinload

from fastapi_app.core.cache import cache_result
from fastapi_app.core.sanitizer import escape_like
from fastapi_app.utils import calc_total_pages
from fastapi_app.services.purchase_order_query import _build_po_source_sku_map
from fastapi_app.shared_models import (
    MaterialRegistration,
    MaterialRegistrationItem,
    Order,
    PurchaseOrder,
    PurchaseOrderItem,
)

logger = logging.getLogger(__name__)


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

    # 批量查询每条来料登记关联的采购订单明细中的供应商分布，
    # 以便前端能展示同一采购订单下不同物料供应商（BOM 可配置多个供应商）
    po_ids = [r.purchase_order_id for r in registrations if r.purchase_order_id]
    supplier_map: dict[int, set[str]] = {}
    # item_id -> supplier_name 映射，用于给每个来料登记明细注入供应商信息
    item_supplier_map: dict[int | None, str] = {}
    # 查询每个采购订单的 SKU 明细（产品名、条码、数量），用于前端分列显示多 SKU
    po_sku_map: dict[int, list[dict]] = {}
    if po_ids:
        po_for_sku = [r.purchase_order for r in registrations if r.purchase_order]
        po_sku_map = await _build_po_source_sku_map(db, po_for_sku)
    if po_ids:
        sup_result = await db.execute(
            select(
                PurchaseOrderItem.order_id,
                PurchaseOrderItem.id,
                PurchaseOrderItem.supplier_name,
                PurchaseOrderItem.material_name,
            ).where(
                PurchaseOrderItem.order_id.in_(po_ids),
                PurchaseOrderItem.supplier_name.isnot(None),
                PurchaseOrderItem.supplier_name != '',
            )
        )
        # material_name -> supplier_name 映射（按 order_id 分组），用于回填无 order_item_id 的明细
        po_material_supplier: dict[int, dict[str, str]] = {}
        for po_id, item_id, sup_name, mat_name in sup_result.all():
            supplier_map.setdefault(po_id, set()).add(sup_name)
            if item_id is not None:
                item_supplier_map[item_id] = sup_name
            if mat_name:
                po_material_supplier.setdefault(po_id, {})[mat_name] = sup_name

    reg_dicts = []
    for r in registrations:
        d = r.to_dict()
        names = sorted(supplier_map.get(r.purchase_order_id, set()))
        d['supplier_names'] = names if names else ([d.get('supplier_name')] if d.get('supplier_name') else [])
        # 订单时间：采购订单生成时间（用户要求展示"来料登记生成订单的时间"）
        po = r.purchase_order
        if po and po.create_time:
            d['po_create_time'] = po.create_time.strftime('%Y/%m/%d')
        else:
            d['po_create_time'] = ''
        # SKU 明细列表（多 SKU 订单时前端按 SKU 分行显示产品名称和数量）
        d['sku_items'] = po_sku_map.get(r.purchase_order_id, [])
        # 给每个明细注入 supplier_name（优先用 order_item_id 匹配，回退用 material_name 匹配）
        mat_map = po_material_supplier.get(r.purchase_order_id, {})
        for item in d.get('items', []):
            oid = item.get('order_item_id')
            if oid and oid in item_supplier_map:
                item['supplier_name'] = item_supplier_map[oid]
            elif item.get('material_name') in mat_map:
                item['supplier_name'] = mat_map[item['material_name']]
            else:
                item['supplier_name'] = r.supplier_name or ''
        reg_dicts.append(d)

    return {
        'success': True,
        'registrations': reg_dicts,
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
    d = reg.to_dict()
    # 给每个明细注入 supplier_name（与列表接口保持一致，便于前端按供应商汇总）
    po_id = reg.purchase_order_id
    if po_id:
        sup_result = await db.execute(
            select(
                PurchaseOrderItem.id,
                PurchaseOrderItem.supplier_name,
                PurchaseOrderItem.material_name,
            ).where(
                PurchaseOrderItem.order_id == po_id,
                PurchaseOrderItem.supplier_name.isnot(None),
                PurchaseOrderItem.supplier_name != '',
            )
        )
        item_supplier_map: dict[int, str] = {}
        material_supplier_map: dict[str, str] = {}
        for item_id, sup_name, mat_name in sup_result.all():
            if item_id is not None:
                item_supplier_map[item_id] = sup_name
            if mat_name:
                material_supplier_map[mat_name] = sup_name
        for item in d.get('items', []):
            oid = item.get('order_item_id')
            if oid and oid in item_supplier_map:
                item['supplier_name'] = item_supplier_map[oid]
            elif item.get('material_name') in material_supplier_map:
                item['supplier_name'] = material_supplier_map[item['material_name']]
            else:
                item['supplier_name'] = reg.supplier_name or ''
    return {'success': True, 'registration': d}


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


async def export_registrations(db, order_no: str = '', supplier: str = '',
                               customer_name: str = '', material_category: str = '',
                               start_date: str = '', end_date: str = '') -> dict:
    """导出来料登记数据（返回HTML用于Excel打开）"""
    needs_po_join = bool(customer_name)
    base_query = select(MaterialRegistration)
    if needs_po_join:
        base_query = base_query.join(MaterialRegistration.purchase_order)
    query = base_query.options(
        selectinload(MaterialRegistration.items),
        selectinload(MaterialRegistration.purchase_order),
    )
    if order_no:
        query = query.where(MaterialRegistration.purchase_order_no.ilike(f'%{escape_like(order_no)}%'))
    if supplier:
        query = query.where(MaterialRegistration.supplier_name.ilike(f'%{escape_like(supplier)}%'))
    if customer_name:
        query = query.where(PurchaseOrder.customer_name.ilike(f'%{escape_like(customer_name)}%'))
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
    if material_category:
        query = query.where(
            MaterialRegistration.items.any(MaterialRegistrationItem.material_category == material_category)
        )

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
