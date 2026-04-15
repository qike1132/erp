"""
来料登记路由
提供来料登记的增删改查接口，支持数据同步、状态监控、历史查询、导出

[已迁移至 FastAPI] 以下API已在FastAPI中提供等效接口（/api/v1/material-registrations/）：
  - GET  /api/registrations         → GET  /api/v1/material-registrations/registrations
  - POST /api/registrations         → POST /api/v1/material-registrations/registrations
  - GET  /api/registrations/<id>    → GET  /api/v1/material-registrations/registrations/{id}
  - PUT  /api/registrations/<id>    → PUT  /api/v1/material-registrations/registrations/{id}
  - DELETE /api/registrations/<id>  → DELETE /api/v1/material-registrations/registrations/{id}
  - GET  /api/purchase-orders/available → GET /api/v1/material-registrations/purchase-orders/available
  - GET  /api/purchase-orders/<id>/items → GET /api/v1/material-registrations/purchase-orders/{id}/items
  - GET  /api/purchase-orders/<order_no>/preview → GET /api/v1/material-registrations/purchase-orders/preview/{order_no}
  - POST /api/export                → POST /api/v1/material-registrations/export
  - GET  /api/history               → GET  /api/v1/material-registrations/history
  - GET  /api/suggestions           → GET  /api/v1/material-registrations/suggestions
  - GET  /api/stats/overview        → GET  /api/v1/material-registrations/stats/overview
  - GET  /api/stats/distribution    → GET  /api/v1/material-registrations/stats/distribution
  - GET  /api/stats/trend           → GET  /api/v1/material-registrations/stats/trend
  - POST /api/items/<id>/receive    → POST /api/v1/material-registrations/items/{id}/receive
  本路由保留用于Flask页面兼容
"""
from flask import Blueprint, request, jsonify, session, render_template
from datetime import datetime, date, timedelta
from sqlalchemy.orm import joinedload
from sqlalchemy import func, or_, and_
from app import db
from app.models import (
    MaterialRegistration, MaterialRegistrationItem,
    PurchaseOrder, PurchaseOrderItem, User
)
from app.utils.permission_decorators import api_permission_required
import logging
import json

from decimal import Decimal

logger = logging.getLogger(__name__)

material_registration_bp = Blueprint('material_registration', __name__, url_prefix='/material-registration')


@material_registration_bp.route('/page')
@api_permission_required('product_manage')
def material_registration_page():
    """来料登记页面"""
    user = db.session.get(User, session.get('user_id'))
    user_permissions = []
    is_super = False
    if user:
        is_super = user.is_super
        if user.permissions:
            user_permissions = [p.code for p in user.permissions]
            for p in user.permissions:
                if p.children:
                    user_permissions.extend([c.code for c in p.children])
    return render_template('material_registration.html', 
                          user_permissions=user_permissions, 
                          is_super=is_super)


@material_registration_bp.route('/api/registrations', methods=['GET'])
@api_permission_required('product_manage')
def get_registrations():
    """获取来料登记列表 - 增强版"""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    status = request.args.get('status', '')
    order_no = request.args.get('order_no', '')
    supplier = request.args.get('supplier', '')
    material_category = request.args.get('material_category', '')
    material_name = request.args.get('material_name', '')
    start_date = request.args.get('start_date', '')
    end_date = request.args.get('end_date', '')
    po_status = request.args.get('po_status', '')

    query = MaterialRegistration.query.join(
        PurchaseOrder, MaterialRegistration.purchase_order_id == PurchaseOrder.id, isouter=True
    )

    if status:
        query = query.filter(MaterialRegistration.status == status)
    if order_no:
        query = query.filter(MaterialRegistration.purchase_order_no.ilike(f'%{order_no}%'))
    if supplier:
        query = query.filter(MaterialRegistration.supplier_name.ilike(f'%{supplier}%'))
    if start_date:
        try:
            sd = datetime.strptime(start_date, '%Y-%m-%d').date()
            query = query.filter(MaterialRegistration.registration_date >= sd)
        except ValueError:
            pass
    if end_date:
        try:
            ed = datetime.strptime(end_date, '%Y-%m-%d').date()
            query = query.filter(MaterialRegistration.registration_date <= ed)
        except ValueError:
            pass
    if material_name:
        query = query.filter(
            MaterialRegistration.items.any(MaterialRegistrationItem.material_name.ilike(f'%{material_name}%'))
        )
    if material_category:
        query = query.filter(
            MaterialRegistration.items.any(MaterialRegistrationItem.material_category == material_category)
        )
    if po_status:
        query = query.filter(PurchaseOrder.status == po_status)

    query = query.order_by(MaterialRegistration.create_time.desc())
    total = query.count()
    registrations = query.offset((page - 1) * per_page).limit(per_page).all()

    pending_count = MaterialRegistration.query.filter_by(status='pending').count()
    partial_count = MaterialRegistration.query.filter_by(status='partial').count()
    completed_count = MaterialRegistration.query.filter_by(status='completed').count()
    total_count = MaterialRegistration.query.count()

    total_ordered = db.session.query(
        func.sum(MaterialRegistrationItem.ordered_quantity)
    ).scalar() or 0
    total_received = db.session.query(
        func.sum(MaterialRegistrationItem.received_quantity)
    ).scalar() or 0

    category_stats = db.session.query(
        MaterialRegistrationItem.material_category,
        func.sum(MaterialRegistrationItem.ordered_quantity),
        func.sum(MaterialRegistrationItem.received_quantity)
    ).group_by(MaterialRegistrationItem.material_category).all()

    category_data = {}
    for cat, ordered, received in category_stats:
        if cat:
            category_data[cat] = {
                'ordered': float(ordered or 0),
                'received': float(received or 0),
                'progress': round(float(received or 0) / float(ordered or 1) * 100, 1)
            }

    stats = {
        'total': total_count,
        'pending': pending_count,
        'partial': partial_count,
        'completed': completed_count,
        'total_ordered': float(total_ordered),
        'total_received': float(total_received),
        'overall_progress': min(round(float(total_received) / float(total_ordered or 1) * 100, 1), 99.9) if completed_count < total_count else (100.0 if total_count > 0 else 0),
        'category_stats': category_data,
    }

    return jsonify({
        'success': True,
        'registrations': [r.to_dict() for r in registrations],
        'total': total,
        'pages': (total + per_page - 1) // per_page,
        'current_page': page,
        'stats': stats,
    })


@material_registration_bp.route('/api/registrations/<int:reg_id>', methods=['GET'])
@api_permission_required('product_manage')
def get_registration(reg_id):
    """获取来料登记详情"""
    registration = MaterialRegistration.query.get_or_404(reg_id)
    return jsonify({'success': True, 'registration': registration.to_dict()})


@material_registration_bp.route('/api/registrations', methods=['POST'])
@api_permission_required('product_manage')
def create_registration():
    """创建来料登记"""
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'message': '无效的请求数据'}), 400

    purchase_order_id = data.get('purchase_order_id')
    if not purchase_order_id:
        return jsonify({'success': False, 'message': '请选择采购订单'}), 400
    # 获取采购订单
    purchase_order = db.session.get(PurchaseOrder, purchase_order_id)
    if not purchase_order:
        return jsonify({'success': False, 'message': '采购订单不存在'}), 404
    user_id = session.get('user_id')
    username = session.get('username', '未知')
    try:
        # 创建来料登记主记录
        registration = MaterialRegistration(
            purchase_order_id=purchase_order_id,
            purchase_order_no=purchase_order.order_no,
            supplier_id=purchase_order.supplier_id,
            supplier_name=purchase_order.supplier_name,
            registration_date=datetime.now().date(),
            status='pending',
            remark=data.get('remark', ''),
            created_by=user_id,
        )
        db.session.add(registration)
        db.session.flush()
        # 创建明细记录
        items_data = data.get('items', [])
        for item_data in items_data:
            item = MaterialRegistrationItem(
                registration_id=registration.id,
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
            db.session.add(item)
        db.session.commit()
        return jsonify({'success': True, 'message': '来料登记创建成功', 'registration': registration.to_dict()})
    except Exception as e:
        db.session.rollback()
        logger.error(f"创建来料登记失败: {e}")
        return jsonify({'success': False, 'message': '创建失败，请稍后重试'}), 500


@material_registration_bp.route('/api/registrations/<int:reg_id>', methods=['PUT'])
@api_permission_required('product_manage')
def update_registration(reg_id):
    """更新来料登记"""
    registration = MaterialRegistration.query.get_or_404(reg_id)
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'message': '无效的请求数据'}), 400
    try:
        # 更新主记录
        if 'status' in data:
            registration.status = data['status']
        if 'remark' in data:
            registration.remark = data['remark']
        # 更新明细
        if 'items' in data:
            for item_data in data['items']:
                item_id = item_data.get('id')
                if item_id:
                    item = db.session.get(MaterialRegistrationItem, item_id)
                    if item and item.registration_id == reg_id:
                        if 'received_quantity' in item_data:
                            item.received_quantity = Decimal(str(item_data['received_quantity']))
                        if 'remark' in item_data:
                            item.remark = item_data['remark']
        # 更新状态
        total_ordered = sum(float(item.ordered_quantity or 0) for item in registration.items)
        total_received = sum(float(item.received_quantity or 0) for item in registration.items)
        if total_received >= total_ordered:
            registration.status = 'completed'
        elif total_received > 0:
            registration.status = 'partial'
        else:
            registration.status = 'pending'
        db.session.commit()
        return jsonify({'success': True, 'message': '更新成功', 'registration': registration.to_dict()})
    except Exception as e:
        db.session.rollback()
        logger.error(f"更新来料登记失败: {e}")
        return jsonify({'success': False, 'message': '更新失败，请稍后重试'}), 500


@material_registration_bp.route('/api/registrations/<int:reg_id>', methods=['DELETE'])
@api_permission_required('product_manage')
def delete_registration(reg_id):
    """删除来料登记"""
    registration = MaterialRegistration.query.get_or_404(reg_id)
    try:
        db.session.delete(registration)
        db.session.commit()
        return jsonify({'success': True, 'message': '删除成功'})
    except Exception as e:
        db.session.rollback()
        logger.error(f"删除来料登记失败: {e}")
        return jsonify({'success': False, 'message': '删除失败，请稍后重试'}), 500


@material_registration_bp.route('/api/purchase-orders/<order_no>/preview', methods=['GET'])
@api_permission_required('product_manage')
def preview_purchase_order(order_no):
    """采购订单快速预览 - 弹窗用"""
    order = PurchaseOrder.query.filter_by(order_no=order_no).first()
    if not order:
        return jsonify({'success': False, 'message': '订单不存在'}), 404
    return jsonify({'success': True, 'order': order.to_dict()})


@material_registration_bp.route('/api/purchase-orders/available', methods=['GET'])
@api_permission_required('product_manage')
def get_available_purchase_orders():
    """获取可用于来料登记的采购订单列表"""
    status = request.args.get('status', 'pending')
    query = PurchaseOrder.query.options(joinedload(PurchaseOrder.items))
    if status:
        query = query.filter(PurchaseOrder.status == status)
    query = query.order_by(PurchaseOrder.create_time.desc())
    orders = query.limit(50).all()
    return jsonify({
        'success': True,
        'orders': [{
            'id': o.id,
                'order_no': o.order_no,
                'supplier_name': o.supplier_name,
                'customer_name': o.customer_name,
                'order_date': o.order_date.strftime('%Y-%m-%d') if o.order_date else None,
                'status': o.status,
                'item_count': len(o.items),
                'items': [item.to_dict() for item in o.items]
            } for o in orders]
        })


@material_registration_bp.route('/api/purchase-orders/<int:order_id>/items', methods=['GET'])
@api_permission_required('product_manage')
def get_purchase_order_items(order_id):
    """获取采购订单物料明细"""
    order = PurchaseOrder.query.get_or_404(order_id)
    items = PurchaseOrderItem.query.filter_by(order_id=order_id).all()
    return jsonify({
        'success': True,
        'items': [item.to_dict() for item in items]
    })


@material_registration_bp.route('/api/items/<int:item_id>/receive', methods=['POST'])
@api_permission_required('product_manage')
def receive_material(item_id):
    """物料收货登记"""
    item = MaterialRegistrationItem.query.get_or_404(item_id)
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'message': '无效的请求数据'}), 400
    try:
        received_qty = Decimal(str(data.get('received_quantity', 0)))
        if received_qty < 0:
            return jsonify({'success': False, 'message': '收货数量必须大于0'}), 400
        item.received_quantity = received_qty
        if data.get('remark'):
            item.remark = data['remark']
        # 更新来料登记的状态
        registration = item.registration
        registration.update_status()
        db.session.commit()
        return jsonify({
            'success': True,
            'message': '收货登记成功',
            'item': item.to_dict(),
            'registration_status': registration.computed_status,
            'auto_completed': registration.computed_status == 'completed'
        })
    except Exception as e:
        db.session.rollback()
        logger.error(f"物料收货登记失败: {e}")
        return jsonify({'success': False, 'message': '登记失败，请稍后重试'}), 500


@material_registration_bp.route('/api/stats/overview', methods=['GET'])
@api_permission_required('product_manage')
def get_stats_overview():
    """获取来料登记统计概览"""
    try:
        all_registrations = MaterialRegistration.query.all()
        pending = sum(1 for r in all_registrations if r.computed_status == 'pending')
        partial = sum(1 for r in all_registrations if r.computed_status == 'partial')
        completed = sum(1 for r in all_registrations if r.computed_status == 'completed')
        total = len(all_registrations)

        total_ordered = db.session.query(
            func.sum(MaterialRegistrationItem.ordered_quantity)
        ).scalar() or 0
        total_received = db.session.query(
            func.sum(MaterialRegistrationItem.received_quantity)
        ).scalar() or 0

        category_stats = db.session.query(
            MaterialRegistrationItem.material_category,
            func.sum(MaterialRegistrationItem.ordered_quantity),
            func.sum(MaterialRegistrationItem.received_quantity),
            func.count(MaterialRegistrationItem.id)
        ).group_by(MaterialRegistrationItem.material_category).all()

        category_data = []
        category_map = {'fabric': '面料', 'filling': '填充', 'accessory': '辅料', 'packaging': '包装'}
        for cat, ordered, received, count in category_stats:
            if cat:
                category_data.append({
                    'category': cat,
                    'category_name': category_map.get(cat, cat),
                    'ordered': float(ordered or 0),
                    'received': float(received or 0),
                    'remaining': float(ordered or 0) - float(received or 0),
                    'progress': round(float(received or 0) / float(ordered or 1) * 100, 1),
                    'item_count': count
                })

        today = datetime.now().date()
        week_ago = today - timedelta(days=7)
        month_ago = today - timedelta(days=30)

        recent_registrations = MaterialRegistration.query.filter(
            MaterialRegistration.registration_date >= week_ago
        ).count()

        overdue_items = db.session.query(func.count(MaterialRegistrationItem.id)).filter(
            MaterialRegistrationItem.ordered_quantity > MaterialRegistrationItem.received_quantity,
            MaterialRegistration.registration_date < month_ago
        ).join(MaterialRegistration).scalar() or 0

        return jsonify({
            'success': True,
            'overview': {
                'total': total,
                'pending': pending,
                'partial': partial,
                'completed': completed,
                'total_ordered': float(total_ordered),
                'total_received': float(total_received),
                'total_remaining': float(total_ordered) - float(total_received),
                'overall_progress': min(round(float(total_received) / float(total_ordered or 1) * 100, 1), 99.9) if completed < total else (100.0 if total > 0 else 0),
                'category_stats': category_data,
                'recent_registrations': recent_registrations,
                'overdue_items': overdue_items,
            }
        })
    except Exception as e:
        logger.error(f"获取统计概览失败: {e}")
        return jsonify({'success': False, 'message': '获取统计概览失败，请稍后重试'}), 500


@material_registration_bp.route('/api/stats/distribution', methods=['GET'])
@api_permission_required('product_manage')
def get_stats_distribution():
    """获取来料登记状态分布"""
    try:
        all_registrations = MaterialRegistration.query.all()
        pending = sum(1 for r in all_registrations if r.computed_status == 'pending')
        partial = sum(1 for r in all_registrations if r.computed_status == 'partial')
        completed = sum(1 for r in all_registrations if r.computed_status == 'completed')

        today = datetime.now().date()
        month_ago = today - timedelta(days=30)
        overdue_items = db.session.query(func.count(MaterialRegistrationItem.id)).filter(
            MaterialRegistrationItem.ordered_quantity > MaterialRegistrationItem.received_quantity,
            MaterialRegistration.registration_date < month_ago
        ).join(MaterialRegistration).scalar() or 0

        return jsonify({
            'success': True,
            'distribution': [
                {'status': 'pending', 'count': pending},
                {'status': 'partial', 'count': partial},
                {'status': 'completed', 'count': completed},
                {'status': 'overdue', 'count': overdue_items},
            ]
        })
    except Exception as e:
        logger.error(f"获取状态分布失败: {e}")
        return jsonify({'success': False, 'message': '获取状态分布失败，请稍后重试'}), 500


@material_registration_bp.route('/api/stats/trend', methods=['GET'])
@api_permission_required('product_manage')
def get_stats_trend():
    """获取来料登记趋势数据"""
    try:
        days = request.args.get('days', 30, type=int)
        end_date = datetime.now().date()
        start_date = end_date - timedelta(days=days)

        registrations = MaterialRegistration.query.filter(
            MaterialRegistration.registration_date >= start_date,
            MaterialRegistration.registration_date <= end_date
        ).all()

        date_map = {}
        current = start_date
        while current <= end_date:
            date_map[current.strftime('%Y-%m-%d')] = {'registered': 0, 'received': 0}
            current += timedelta(days=1)

        for reg in registrations:
            date_key = reg.registration_date.strftime('%Y-%m-%d') if reg.registration_date else None
            if date_key and date_key in date_map:
                date_map[date_key]['registered'] += 1

        received_items = db.session.query(
            func.date(MaterialRegistration.update_time).label('receive_date'),
            func.sum(MaterialRegistrationItem.received_quantity).label('received_qty')
        ).join(MaterialRegistrationItem).filter(
            MaterialRegistration.update_time >= start_date,
            MaterialRegistrationItem.received_quantity > 0
        ).group_by(func.date(MaterialRegistration.update_time)).all()

        for recv_date, qty in received_items:
            if recv_date:
                date_key = recv_date.strftime('%Y-%m-%d') if hasattr(recv_date, 'strftime') else str(recv_date)
                if date_key in date_map:
                    date_map[date_key]['received'] = float(qty or 0)

        trend_data = [{'date': k, 'registered': v['registered'], 'received': v['received']} for k, v in sorted(date_map.items())]

        return jsonify({
            'success': True,
            'trend': trend_data
        })
    except Exception as e:
        logger.error(f"获取趋势数据失败: {e}")
        return jsonify({'success': False, 'message': '获取趋势数据失败，请稍后重试'}), 500


@material_registration_bp.route('/api/export', methods=['POST'])
@api_permission_required('product_manage')
def export_registrations():
    """导出来料登记数据"""
    data = request.get_json() or {}
    try:
        query = MaterialRegistration.query

        order_no = data.get('order_no', '')
        if order_no:
            query = query.filter(MaterialRegistration.purchase_order_no.ilike(f'%{order_no}%'))
        supplier = data.get('supplier', '')
        if supplier:
            query = query.filter(MaterialRegistration.supplier_name.ilike(f'%{supplier}%'))
        start_date = data.get('start_date', '')
        if start_date:
            query = query.filter(MaterialRegistration.registration_date >= start_date)
        end_date = data.get('end_date', '')
        if end_date:
            query = query.filter(MaterialRegistration.registration_date <= end_date)

        registrations = query.order_by(MaterialRegistration.create_time.desc()).all()

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

        status_map = {'pending': '待收货', 'partial': '部分收货', 'completed': '已完成'}
        for reg in registrations:
            items = list(reg.items)
            computed_status = reg.computed_status
            if not items:
                html_parts.append(f'<tr><td>{reg.registration_date or "-"}</td><td>{reg.purchase_order_no}</td><td>{reg.supplier_name or "-"}</td><td>-</td><td>-</td><td>-</td><td>-</td><td>{status_map.get(computed_status, computed_status)}</td></tr>')
            else:
                for idx, item in enumerate(items):
                    html_parts.append(f'<tr>')
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

        return jsonify({'success': True, 'html': ''.join(html_parts)})
    except Exception as e:
        logger.error(f"导出来料登记失败: {e}")
        return jsonify({'success': False, 'message': '导出来料登记失败，请稍后重试'}), 500


@material_registration_bp.route('/api/history', methods=['GET'])
@api_permission_required('product_manage')
def get_history():
    """获取来料登记历史记录 - 仅显示已完成的订单(进度100%)"""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    order_no = request.args.get('order_no', '')
    supplier = request.args.get('supplier', '')
    customer_name = request.args.get('customer_name', '')
    material_category = request.args.get('material_category', '')
    start_date = request.args.get('start_date', '')
    end_date = request.args.get('end_date', '')

    query = MaterialRegistration.query.join(
        PurchaseOrder, MaterialRegistration.purchase_order_id == PurchaseOrder.id, isouter=True
    )

    if order_no:
        query = query.filter(MaterialRegistration.purchase_order_no.ilike(f'%{order_no}%'))
    if supplier:
        query = query.filter(MaterialRegistration.supplier_name.ilike(f'%{supplier}%'))
    if customer_name:
        query = query.filter(PurchaseOrder.customer_name.ilike(f'%{customer_name}%'))
    if start_date:
        try:
            sd = datetime.strptime(start_date, '%Y-%m-%d').date()
            query = query.filter(MaterialRegistration.registration_date >= sd)
        except ValueError:
            pass
    if end_date:
        try:
            ed = datetime.strptime(end_date, '%Y-%m-%d').date()
            query = query.filter(MaterialRegistration.registration_date <= ed)
        except ValueError:
            pass
    if material_category:
        query = query.filter(
            MaterialRegistration.items.any(MaterialRegistrationItem.material_category == material_category)
        )

    query = query.order_by(MaterialRegistration.update_time.desc())
    all_registrations = [r for r in query.all() if r.computed_status == 'completed']
    total = len(all_registrations)
    registrations = all_registrations[(page - 1) * per_page:page * per_page]

    return jsonify({
        'success': True,
        'registrations': [r.to_dict() for r in registrations],
        'total': total,
        'pages': (total + per_page - 1) // per_page,
        'current_page': page,
    })


@material_registration_bp.route('/api/suggestions', methods=['GET'])
@api_permission_required('product_manage')
def get_suggestions():
    """获取搜索联想建议"""
    field = request.args.get('field', '')
    keyword = request.args.get('keyword', '')
    limit = request.args.get('limit', 10, type=int)

    if not field or not keyword or len(keyword) < 1:
        return jsonify({'success': True, 'suggestions': []})

    suggestions = []
    try:
        if field == 'order_no':
            results = db.session.query(MaterialRegistration.purchase_order_no).filter(
                MaterialRegistration.purchase_order_no.ilike(f'%{keyword}%')
            ).distinct().limit(limit).all()
            suggestions = [r[0] for r in results if r[0]]
        elif field == 'supplier':
            results = db.session.query(MaterialRegistration.supplier_name).filter(
                MaterialRegistration.supplier_name.ilike(f'%{keyword}%')
            ).distinct().limit(limit).all()
            suggestions = [r[0] for r in results if r[0]]
        elif field == 'material_name':
            results = db.session.query(MaterialRegistrationItem.material_name).filter(
                MaterialRegistrationItem.material_name.ilike(f'%{keyword}%')
            ).distinct().limit(limit).all()
            suggestions = [r[0] for r in results if r[0]]
    except Exception as e:
        logger.error(f"获取联想建议失败: {e}")

    return jsonify({'success': True, 'suggestions': suggestions[:limit]})
