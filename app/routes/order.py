"""
订单管理路由蓝图
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from app import db
from app.models import Order, Product, InventoryLog, ApprovalRequest, Customer
from datetime import datetime
import json
import logging
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import joinedload, selectinload
from app.utils.approval_helpers import create_approval_log
from app.utils.permission_decorators import api_permission_required, get_current_user, is_admin
from utils.sanitizer import sanitize_plain_text
from fastapi_app.shared.stock_concurrency import get_product_for_update_sync

logger = logging.getLogger(__name__)

order_bp = Blueprint('order', __name__, url_prefix='/order')


def generate_order_number(db, Order):
    """生成订单编号"""
    today = datetime.now()
    prefix = f"ORD{today.strftime('%Y%m%d')}"

    last_order = Order.query.filter(
        Order.order_no.like(f"{prefix}%")
    ).order_by(Order.order_no.desc()).first()

    if last_order:
        last_num = int(last_order.order_no[-4:])
        new_num = last_num + 1
    else:
        new_num = 1

    return f"{prefix}{new_num:04d}"


@order_bp.route('/list', methods=['GET', 'POST'])
@api_permission_required('order_manage')
def orders():
    """订单列表和添加"""
    if request.method == 'POST':
        try:
            order_no = generate_order_number(db, Order)

            product_id_str = request.form.get('product_id', '').strip()
            quantity_str = request.form.get('quantity', '').strip()

            if not product_id_str:
                flash('请选择产品！', 'error')
                return redirect(url_for('order.orders'))
            if not quantity_str or quantity_str == '0':
                flash('请输入有效的数量！', 'error')
                return redirect(url_for('order.orders'))

            try:
                product_id = int(product_id_str)
                quantity = int(quantity_str)
            except ValueError:
                flash('产品ID和数量必须是有效的整数！', 'error')
                return redirect(url_for('order.orders'))

            if quantity <= 0:
                flash('数量必须大于0！', 'error')
                return redirect(url_for('order.orders'))

            if quantity > 100000:
                flash('数量超出合理范围（最大100000）！', 'error')
                return redirect(url_for('order.orders'))

            note = sanitize_plain_text(request.form.get('note', '').strip())
            if len(note) > 500:
                flash('备注过长（最大500字符）！', 'error')
                return redirect(url_for('order.orders'))

            customer = sanitize_plain_text(request.form.get('customer', '').strip())
            if not customer:
                flash('客户名称不能为空！', 'error')
                return redirect(url_for('order.orders'))
            if len(customer) > 100:
                flash('客户名称过长（最大100字符）！', 'error')
                return redirect(url_for('order.orders'))

            order_date = datetime.now()

            existing_order = Order.query.filter_by(order_no=order_no).first()
            if existing_order:
                flash('订单编号已存在！', 'error')
                return redirect(url_for('order.orders'))

            try:
                product = get_product_for_update_sync(db.session, product_id)
            except ValueError:
                flash('产品不存在！', 'error')
                return redirect(url_for('order.orders'))

            order = Order(
                order_no=order_no,
                customer=customer,
                order_date=order_date,
                product_id=product_id,
                quantity=quantity,
                note=note,
                status='待备货'
            )
            db.session.add(order)
            db.session.flush()

            product.current_stock += quantity

            log = InventoryLog(
                product_id=product_id,
                change_type='订单',
                change_quantity=quantity,
                related_id=order_no,
                note=f'订单：{order_no}'
            )
            db.session.add(log)

            current_user = get_current_user()
            
            # 不再需要同步，采购中心直接读取Order表
            db.session.commit()
            
            logger.info(f'订单添加成功：{order_no}，客户：{customer}，产品：{product.name}，数量：{quantity}')
            flash('订单添加成功！', 'success')
            return redirect(url_for('order.orders'))
            
        except SQLAlchemyError as e:
            db.session.rollback()
            logger.error(f'订单添加数据库错误：{str(e)}', exc_info=True)
            flash('数据库操作失败，请稍后重试！', 'error')
            return redirect(url_for('order.orders'))
        except Exception as e:
            db.session.rollback()
            logger.error(f'订单添加未知错误：{str(e)}', exc_info=True)
            flash('系统错误，请联系管理员！', 'error')
            return redirect(url_for('order.orders'))

    orders = Order.query.options(
        joinedload(Order.product),
        selectinload(Order.order_stockouts),
        joinedload(Order.locked_by)
    ).order_by(Order.order_date.desc()).limit(2000).all()
    products = Product.query.limit(5000).all()
    customers = Customer.query.filter_by(status=True).order_by(Customer.name).limit(2000).all()
    
    orders_json = json.dumps([{
        'id': o.id,
        'order_no': o.order_no,
        'customer': o.customer,
        'order_date': o.order_date.strftime('%Y-%m-%d %H:%M') if o.order_date else '',
        'product': {
            'id': o.product.id,
            'name': o.product.name,
            'barcode': o.product.barcode or '',
            'image': o.product.image or ''
        },
        'quantity': o.quantity,
        'deduct_quantity': sum(so.quantity for so in o.order_stockouts) if o.order_stockouts else 0,
        'status': o.status,
        'note': o.note or '',
        'is_locked': o.is_locked,
        'locked_by_name': o.locked_by.username if o.locked_by else None
    } for o in orders])
    
    current_user = get_current_user()
    
    return render_template('order.html', orders=orders, products=products, customers=customers, orders_json=orders_json, datetime=datetime, current_user=current_user)


@order_bp.route('/edit/<int:id>', methods=['GET', 'POST'])
@api_permission_required('order_manage')
def edit_order(id):
    """编辑订单"""
    order = Order.query.get_or_404(id)
    current_user = get_current_user()
    
    if not current_user:
        flash('请先登录！', 'error')
        return redirect(url_for('main.login'))
    
    if order.is_locked_by_other(current_user.id):
        pending_approval = ApprovalRequest.query.filter_by(
            order_id=id, 
            status='pending'
        ).first()
        if pending_approval:
            flash(f'该订单正在等待审批（申请人：{pending_approval.requester.username}），暂时无法编辑！', 'warning')
        else:
            flash('该订单已被其他用户锁定，暂时无法编辑！', 'warning')
        return redirect(url_for('order.orders'))
    
    if request.method == 'POST':
        try:
            new_quantity = int(request.form['quantity'])
        except (ValueError, KeyError):
            flash('数量必须是有效的整数！', 'error')
            return redirect(url_for('order.orders'))
        
        if new_quantity <= 0:
            flash('数量必须大于0！', 'error')
            return redirect(url_for('order.orders'))
        
        if new_quantity > 100000:
            flash('数量超出合理范围（最大100000）！', 'error')
            return redirect(url_for('order.orders'))
        
        customer = sanitize_plain_text(request.form.get('customer', '').strip())
        if not customer:
            flash('客户名称不能为空！', 'error')
            return redirect(url_for('order.orders'))

        if len(customer) > 100:
            flash('客户名称过长（最大100字符）！', 'error')
            return redirect(url_for('order.orders'))

        note = sanitize_plain_text(request.form.get('note', '').strip())
        if len(note) > 500:
            flash('备注过长（最大500字符）！', 'error')
            return redirect(url_for('order.orders'))

        order_type = request.form.get('order_type', 'regular')
        country = request.form.get('country', '').strip() if order_type == 'custom' else ''
        if order_type == 'custom' and not country:
            flash('定制订单必须填写国家名称！', 'error')
            return redirect(url_for('order.orders'))
        
        try:
            if is_admin(current_user):
                old_quantity = order.quantity

                order.customer = customer
                order.quantity = new_quantity
                order.note = note
                order.order_type = order_type
                order.country = country if order_type == 'custom' else None

                if new_quantity != old_quantity:
                    product = get_product_for_update_sync(db.session, order.product_id)
                    product.current_stock += (new_quantity - old_quantity)

                    log = InventoryLog(
                        product_id=order.product_id,
                        change_type='订单修改',
                        change_quantity=new_quantity - old_quantity,
                        related_id=order.order_no,
                        note=f'订单修改：{order.order_no}'
                    )
                    db.session.add(log)

                # 不再需要同步，采购中心直接读取Order表
                db.session.commit()
                
                logger.info(f'订单编辑成功：{order.order_no}，操作人：{current_user.username}')
                flash('订单编辑成功！', 'success')
                return redirect(url_for('order.orders'))
            else:
                pending_approval = ApprovalRequest.query.filter_by(
                    order_id=id, 
                    requester_id=current_user.id,
                    status='pending'
                ).first()
                
                if pending_approval:
                    flash('您已提交过该订单的编辑审批请求，请等待管理员审批！', 'warning')
                    return redirect(url_for('order.orders'))
                
                order.lock(current_user.id)
                
                operation_data = {
                    'customer': customer,
                    'quantity': new_quantity,
                    'note': note,
                    'order_type': order_type,
                    'country': country,
                    'original_customer': order.customer,
                    'original_quantity': order.quantity,
                    'original_note': order.note or '',
                    'original_order_type': getattr(order, 'order_type', 'regular') or 'regular',
                    'original_country': getattr(order, 'country', '') or ''
                }
                
                approval_request = ApprovalRequest(
                    order_id=id,
                    requester_id=current_user.id,
                    operation_type='edit',
                    operation_data=json.dumps(operation_data, ensure_ascii=False),
                    status='pending',
                    lock_time=datetime.now()
                )
                db.session.add(approval_request)
                db.session.flush()
                
                create_approval_log(
                    approval_request, 
                    'create', 
                    current_user,
                    {'operation_data': operation_data}
                )
                
                db.session.commit()
                logger.info(f'订单编辑审批请求已提交：{order.order_no}，申请人：{current_user.username}')
                flash('已提交编辑审批请求，请等待管理员审批！', 'info')
                return redirect(url_for('order.orders'))
                
        except SQLAlchemyError as e:
            db.session.rollback()
            logger.error(f'订单编辑数据库错误：{str(e)}', exc_info=True)
            flash('数据库操作失败，请稍后重试！', 'error')
            return redirect(url_for('order.orders'))
        except Exception as e:
            db.session.rollback()
            logger.error(f'订单编辑未知错误：{str(e)}', exc_info=True)
            flash('系统错误，请联系管理员！', 'error')
            return redirect(url_for('order.orders'))

    products = Product.query.limit(5000).all()
    customers = Customer.query.filter_by(status=True).order_by(Customer.name).limit(2000).all()

    # 获取已有国家列表（用于定制订单的国家补全）
    from sqlalchemy import distinct
    existing_countries = [row[0] for row in db.session.query(distinct(Order.country)).filter(Order.country.isnot(None), Order.country != '').all()]
    
    deducted_quantity = sum(stockout.quantity for stockout in order.order_stockouts) if order.order_stockouts else 0
    
    return render_template('edit_order.html', order=order, products=products, customers=customers, countries=existing_countries, current_user=current_user, deducted_quantity=deducted_quantity)


@order_bp.route('/my-approvals')
@api_permission_required('order_manage')
def my_approvals():
    """查看我的审批请求"""
    current_user = get_current_user()
    if not current_user:
        flash('请先登录！', 'error')
        return redirect(url_for('main.login'))
    
    approvals = ApprovalRequest.query.filter_by(
        requester_id=current_user.id
    ).order_by(ApprovalRequest.request_time.desc()).all()
    
    return render_template('my_approvals.html', approvals=approvals, current_user=current_user)


# ==================== AJAX 分页 API ====================

from flask import Blueprint as _Bp
from app import csrf

order_api_bp = _Bp('order_api', __name__, url_prefix='/order/api')
csrf.exempt(order_api_bp)


@order_api_bp.route('/orders')
@api_permission_required('order_manage')
def api_orders():
    """订单列表分页 API"""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)

    query = Order.query.options(
        joinedload(Order.product),
        selectinload(Order.order_stockouts),
        joinedload(Order.locked_by)
    ).order_by(Order.order_date.desc())

    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    result = []
    for o in pagination.items:
        result.append({
            'id': o.id,
            'order_no': o.order_no,
            'customer': o.customer,
            'order_date': o.order_date.strftime('%Y-%m-%d %H:%M') if o.order_date else '',
            'product': {
                'id': o.product.id,
                'name': o.product.name,
                'barcode': o.product.barcode or '',
                'image': o.product.image or ''
            },
            'quantity': o.quantity,
            'deduct_quantity': sum(so.quantity for so in o.order_stockouts) if o.order_stockouts else 0,
            'status': o.status,
            'note': o.note or '',
            'order_type': getattr(o, 'order_type', 'regular') or 'regular',
            'country': getattr(o, 'country', '') or '',
            'is_locked': o.is_locked,
            'locked_by_name': o.locked_by.username if o.locked_by else None
        })

    return jsonify({
        'items': result,
        'total': pagination.total,
        'pages': pagination.pages,
        'current_page': page
    })
