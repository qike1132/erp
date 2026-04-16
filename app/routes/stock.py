"""
库存管理路由蓝图
包含入库、出库和库存查看功能
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, session, make_response
from app import db
from app.models import Product, StockIn, StockOut, InventoryLog, User, Customer, Order
from app.services.stock_service import (
    calculate_available_shipment_quantity,
    create_stockin as svc_create_stockin,
    update_stockin as svc_update_stockin,
    delete_stockin as svc_delete_stockin,
    create_stockout as svc_create_stockout,
    update_stockout as svc_update_stockout,
    delete_stockout as svc_delete_stockout,
)
from app.services.shared import validate_quantity, validate_customer, validate_note, parse_date, build_datetime_with_time, escape_like
from fastapi_app.services.stock_concurrency import get_product_for_update_sync
from datetime import datetime
from utils.number_generator import generate_stockin_number, generate_stockout_number
from sqlalchemy.orm import joinedload, selectinload
from sqlalchemy.exc import SQLAlchemyError
import json
import logging
from app.utils.permission_decorators import api_permission_required, page_permission_required
from utils.cache_manager import no_cache, clear_database_session_cache
from utils.sanitizer import sanitize_plain_text
from urllib.parse import quote

logger = logging.getLogger(__name__)

stock_bp = Blueprint('stock', __name__, url_prefix='/stock')


# ==================== 入库管理 ====================

@stock_bp.route('/in/list', methods=['GET', 'POST'])
@page_permission_required('stockin_manage')
def stockins():
    """入库列表和添加"""
    if request.method == 'POST':
        try:
            product_id_str = request.form.get('product_id', '').strip()
            quantity_str = request.form.get('quantity', '').strip()
            
            if not product_id_str:
                flash('请选择产品！', 'error')
                return redirect(url_for('stock.stockins'))
            
            if not quantity_str:
                flash('请输入数量！', 'error')
                return redirect(url_for('stock.stockins'))
            
            try:
                product_id = int(product_id_str)
                quantity = int(quantity_str)
            except ValueError:
                flash('产品ID和数量必须是有效的整数！', 'error')
                return redirect(url_for('stock.stockins'))
            
            if quantity <= 0:
                flash('数量必须大于0！', 'error')
                return redirect(url_for('stock.stockins'))
            
            if quantity > 100000:
                flash('数量超出合理范围（最大100000）！', 'error')
                return redirect(url_for('stock.stockins'))
            
            customer = sanitize_plain_text(request.form.get('customer', '').strip())
            if not customer:
                flash('客户名称不能为空！', 'error')
                return redirect(url_for('stock.stockins'))
            if len(customer) > 100:
                flash('客户名称过长（最大100字符）！', 'error')
                return redirect(url_for('stock.stockins'))
            
            stockin_date_str = request.form.get('stockin_date', '').strip()
            if not stockin_date_str:
                flash('请选择入库日期！', 'error')
                return redirect(url_for('stock.stockins'))
            
            try:
                stockin_date_base = datetime.strptime(stockin_date_str, '%Y-%m-%d')
            except ValueError:
                flash('日期格式不正确！', 'error')
                return redirect(url_for('stock.stockins'))
            
            now = datetime.now()
            stockin_date = datetime(
                stockin_date_base.year, 
                stockin_date_base.month, 
                stockin_date_base.day,
                now.hour,
                now.minute,
                now.second
            )
            note = sanitize_plain_text(request.form.get('note', '').strip())
            if len(note) > 500:
                flash('备注过长（最大500字符）！', 'error')
                return redirect(url_for('stock.stockins'))

            product = get_product_for_update_sync(db.session, product_id)

            stockin = StockIn(
                stockin_no=generate_stockin_number(db, StockIn),
                product_id=product_id,
                quantity=quantity,
                customer=customer,
                stockin_date=stockin_date,
                note=note
            )
            db.session.add(stockin)
            db.session.flush()

            product.current_stock += quantity

            log = InventoryLog(
                product_id=product_id,
                change_type='入库',
                change_quantity=quantity,
                related_id=str(stockin.id),
                note=f'入库ID：{stockin.id}'
            )
            db.session.add(log)

            db.session.commit()
            logger.info(f'入库添加成功：{stockin.stockin_no}，客户：{customer}，产品：{product.name}，数量：{quantity}')
            flash('入库添加成功！', 'success')
            return redirect(url_for('stock.stockins'))
            
        except SQLAlchemyError as e:
            db.session.rollback()
            logger.error(f'入库添加数据库错误：{str(e)}', exc_info=True)
            flash('数据库操作失败，请稍后重试！', 'error')
            return redirect(url_for('stock.stockins'))
        except Exception as e:
            db.session.rollback()
            logger.error(f'入库添加未知错误：{str(e)}', exc_info=True)
            flash('系统错误，请联系管理员！', 'error')
            return redirect(url_for('stock.stockins'))

    stockins = StockIn.query.options(
        joinedload(StockIn.product),
        selectinload(StockIn.stockin_stockouts)
    ).order_by(StockIn.stockin_date.desc()).all()
    products = Product.query.all()
    customers = Customer.query.filter_by(status=True).order_by(Customer.name).all()
    preview_stockin_no = generate_stockin_number(db, StockIn)
    
    stockins_json = json.dumps([{
        'id': s.id,
        'stockin_no': s.stockin_no,
        'stockin_date': s.stockin_date.strftime('%Y-%m-%d') if s.stockin_date else '',
        'customer': s.customer,
        'product': {
            'id': s.product.id,
            'name': s.product.name,
            'barcode': s.product.barcode or '',
            'image': s.product.image or ''
        },
        'quantity': s.quantity,
        'deducted': sum(so.quantity for so in s.stockin_stockouts) if s.stockin_stockouts else 0,
        'note': s.note or ''
    } for s in stockins])
    
    current_date = datetime.now().strftime('%Y-%m-%d')
    
    return render_template('stockin.html', stockins=stockins, products=products, customers=customers, stockins_json=stockins_json, preview_stockin_no=preview_stockin_no, current_date=current_date)


@stock_bp.route('/in/edit/<int:id>', methods=['GET', 'POST'])
@page_permission_required('stockin_manage')
def edit_stockin(id):
    """编辑入库记录"""
    stockin = StockIn.query.get_or_404(id)

    if request.method == 'POST':
        try:
            new_quantity_str = request.form.get('quantity', '').strip()
            if not new_quantity_str:
                flash('请输入数量！', 'error')
                return redirect(url_for('stock.edit_stockin', id=id))
            
            try:
                new_quantity = int(new_quantity_str)
            except ValueError:
                flash('数量必须是有效的整数！', 'error')
                return redirect(url_for('stock.edit_stockin', id=id))
            
            if new_quantity <= 0:
                flash('数量必须大于0！', 'error')
                return redirect(url_for('stock.edit_stockin', id=id))
            
            if new_quantity > 100000:
                flash('数量超出合理范围（最大100000）！', 'error')
                return redirect(url_for('stock.edit_stockin', id=id))
            
            customer = sanitize_plain_text(request.form.get('customer', '').strip())
            if not customer:
                flash('客户名称不能为空！', 'error')
                return redirect(url_for('stock.edit_stockin', id=id))
            if len(customer) > 100:
                flash('客户名称过长（最大100字符）！', 'error')
                return redirect(url_for('stock.edit_stockin', id=id))
            
            stockin_date_str = request.form.get('stockin_date', '').strip()
            if not stockin_date_str:
                flash('请选择入库日期！', 'error')
                return redirect(url_for('stock.edit_stockin', id=id))
            
            try:
                stockin_date_base = datetime.strptime(stockin_date_str, '%Y-%m-%d')
            except ValueError:
                flash('日期格式不正确！', 'error')
                return redirect(url_for('stock.edit_stockin', id=id))
            
            old_quantity = stockin.quantity
            old_time = stockin.stockin_date
            if old_time and (old_time.hour != 0 or old_time.minute != 0 or old_time.second != 0):
                stockin.stockin_date = datetime(
                    stockin_date_base.year,
                    stockin_date_base.month,
                    stockin_date_base.day,
                    old_time.hour,
                    old_time.minute,
                    old_time.second
                )
            else:
                now = datetime.now()
                stockin.stockin_date = datetime(
                    stockin_date_base.year,
                    stockin_date_base.month,
                    stockin_date_base.day,
                    now.hour,
                    now.minute,
                    now.second
                )
            
            note = sanitize_plain_text(request.form.get('note', '').strip())
            if len(note) > 500:
                flash('备注过长（最大500字符）！', 'error')
                return redirect(url_for('stock.edit_stockin', id=id))

            stockin.quantity = new_quantity
            stockin.customer = customer
            stockin.note = note

            if new_quantity != old_quantity:
                product = get_product_for_update_sync(db.session, stockin.product_id)
                product.current_stock += (new_quantity - old_quantity)

                log = InventoryLog(
                    product_id=stockin.product_id,
                    change_type='入库修改',
                    change_quantity=new_quantity - old_quantity,
                    related_id=str(stockin.id),
                    note=f'入库修改ID：{stockin.id}'
                )
                db.session.add(log)

            db.session.commit()
            logger.info(f'入库编辑成功：{stockin.stockin_no}，数量变更：{old_quantity} -> {new_quantity}')
            flash('入库编辑成功！', 'success')
            return redirect(url_for('stock.stockins'))
            
        except SQLAlchemyError as e:
            db.session.rollback()
            logger.error(f'入库编辑数据库错误：{str(e)}', exc_info=True)
            flash('数据库操作失败，请稍后重试！', 'error')
            return redirect(url_for('stock.edit_stockin', id=id))
        except Exception as e:
            db.session.rollback()
            logger.error(f'入库编辑未知错误：{str(e)}', exc_info=True)
            flash('系统错误，请联系管理员！', 'error')
            return redirect(url_for('stock.edit_stockin', id=id))

    products = Product.query.all()
    customers = Customer.query.filter_by(status=True).order_by(Customer.name).all()
    return render_template('edit_stockin.html', stockin=stockin, products=products, customers=customers)


@stock_bp.route('/in/delete/<int:id>')
@page_permission_required('stockin_manage')
def delete_stockin(id):
    """删除入库记录"""
    stockin = StockIn.query.get_or_404(id)

    if stockin.stockin_stockouts:
        flash('该入库记录已有出库关联，无法删除！', 'error')
        return redirect(url_for('stock.stockins'))

    try:
        product = get_product_for_update_sync(db.session, stockin.product_id)
        product.current_stock -= stockin.quantity

        log = InventoryLog(
            product_id=stockin.product_id,
            change_type='入库删除',
            change_quantity=-stockin.quantity,
            related_id=str(stockin.id),
            note=f'入库删除ID：{stockin.id}'
        )
        db.session.add(log)

        db.session.delete(stockin)
        db.session.commit()
        logger.info(f'入库删除成功：{stockin.stockin_no}，数量：{stockin.quantity}')
        flash('入库删除成功！', 'success')
        return redirect(url_for('stock.stockins'))
        
    except SQLAlchemyError as e:
        db.session.rollback()
        logger.error(f'入库删除数据库错误：{str(e)}', exc_info=True)
        flash('数据库操作失败，请稍后重试！', 'error')
        return redirect(url_for('stock.stockins'))
    except Exception as e:
        db.session.rollback()
        logger.error(f'入库删除未知错误：{str(e)}', exc_info=True)
        flash('系统错误，请联系管理员！', 'error')
        return redirect(url_for('stock.stockins'))


# ==================== 出库管理 ====================

@stock_bp.route('/out/list', methods=['GET', 'POST'])
@page_permission_required('stockout_manage')
def stockouts():
    """出库列表和添加"""
    if request.method == 'POST':
        try:
            product_id_str = request.form.get('product_id', '').strip()
            quantity_str = request.form.get('quantity', '').strip()
            
            if not product_id_str:
                flash('请选择产品！', 'error')
                return redirect(url_for('stock.stockouts'))
            
            if not quantity_str:
                flash('请输入数量！', 'error')
                return redirect(url_for('stock.stockouts'))
            
            try:
                product_id = int(product_id_str)
                quantity = int(quantity_str)
            except ValueError:
                flash('产品ID和数量必须是有效的整数！', 'error')
                return redirect(url_for('stock.stockouts'))
            
            if quantity <= 0:
                flash('数量必须大于0！', 'error')
                return redirect(url_for('stock.stockouts'))
            
            if quantity > 100000:
                flash('数量超出合理范围（最大100000）！', 'error')
                return redirect(url_for('stock.stockouts'))
            
            stockout_date_str = request.form.get('stockout_date', '').strip()
            if not stockout_date_str:
                flash('请选择出库日期！', 'error')
                return redirect(url_for('stock.stockouts'))
            
            try:
                stockout_date = datetime.strptime(stockout_date_str, '%Y-%m-%d')
            except ValueError:
                flash('日期格式不正确！', 'error')
                return redirect(url_for('stock.stockouts'))
            
            customer = sanitize_plain_text(request.form.get('customer', '').strip())
            if not customer:
                flash('出货必须选择客户！出货操作需要有订单支持。', 'error')
                return redirect(url_for('stock.stockouts'))
            if len(customer) > 100:
                flash('客户名称过长（最大100字符）！', 'error')
                return redirect(url_for('stock.stockouts'))
            
            note = sanitize_plain_text(request.form.get('note', '').strip())
            if len(note) > 500:
                flash('备注过长（最大500字符）！', 'error')
                return redirect(url_for('stock.stockouts'))

            product = get_product_for_update_sync(db.session, product_id)

            if product.current_stock < quantity:
                flash('库存不足！', 'error')
                return redirect(url_for('stock.stockouts'))

            shipment_info = calculate_available_shipment_quantity(product_id, customer)
            if shipment_info['available_quantity'] <= 0:
                flash(f'该客户没有可用的订单支持出货！请先创建订单。', 'error')
                return redirect(url_for('stock.stockouts'))
            
            if quantity > shipment_info['available_quantity']:
                flash(f'出货数量超过可出货量！订单总量：{shipment_info["order_quantity"]}，已出货：{shipment_info["shipped_quantity"]}，可出货：{shipment_info["available_quantity"]}', 'error')
                return redirect(url_for('stock.stockouts'))

            remaining_qty = quantity
            for order_detail in shipment_info['orders']:
                if remaining_qty <= 0:
                    break
                if order_detail['available'] > 0:
                    ship_qty = min(remaining_qty, order_detail['available'])
                    stockout = StockOut(
                        stockout_no=generate_stockout_number(db, StockOut),
                        product_id=product_id,
                        quantity=ship_qty,
                        stockout_date=stockout_date,
                        customer=customer,
                        order_id=order_detail['order_id'],
                        note=note
                    )
                    db.session.add(stockout)
                    remaining_qty -= ship_qty

            product.current_stock -= quantity

            log = InventoryLog(
                product_id=product_id,
                change_type='出库',
                change_quantity=-quantity,
                related_id='',
                note=f'出库数量：{quantity}'
            )
            db.session.add(log)

            db.session.commit()
            logger.info(f'出库添加成功：产品{product.name}，数量：{quantity}，客户：{customer or "无"}')
            flash('出库添加成功！', 'success')
            return redirect(url_for('stock.stockouts'))
            
        except SQLAlchemyError as e:
            db.session.rollback()
            logger.error(f'出库添加数据库错误：{str(e)}', exc_info=True)
            flash('数据库操作失败，请稍后重试！', 'error')
            return redirect(url_for('stock.stockouts'))
        except Exception as e:
            db.session.rollback()
            logger.error(f'出库添加未知错误：{str(e)}', exc_info=True)
            flash('系统错误，请联系管理员！', 'error')
            return redirect(url_for('stock.stockouts'))

    stockouts = StockOut.query.options(
        joinedload(StockOut.product)
    ).filter(StockOut.stockin_id.is_(None)).order_by(StockOut.stockout_date.desc()).all()
    products = Product.query.all()
    customers = Customer.query.filter_by(status=True).order_by(Customer.name).all()
    preview_stockout_no = generate_stockout_number(db, StockOut)
    current_date = datetime.now().strftime('%Y-%m-%d')
    
    stockouts_json = json.dumps([{
        'id': s.id,
        'stockout_no': s.stockout_no,
        'stockout_date': s.stockout_date.strftime('%Y-%m-%d') if s.stockout_date else '',
        'customer': s.customer,
        'product': {
            'id': s.product.id,
            'name': s.product.name,
            'barcode': s.product.barcode or '',
            'image': s.product.image or ''
        },
        'quantity': s.quantity,
        'note': s.note or ''
    } for s in stockouts])
    
    return render_template('stockout.html', stockouts=stockouts, products=products, customers=customers, stockouts_json=stockouts_json, preview_stockout_no=preview_stockout_no, current_date=current_date)


@stock_bp.route('/out/edit/<int:id>', methods=['GET', 'POST'])
@page_permission_required('stockout_manage')
def edit_stockout(id):
    """编辑出库记录"""
    stockout = StockOut.query.get_or_404(id)

    if stockout.stockin_id is not None:
        flash('订单抵扣的出货记录不能直接编辑！请通过订单管理进行修改。', 'error')
        return redirect(url_for('stock.stockouts'))

    if request.method == 'POST':
        try:
            new_quantity_str = request.form.get('quantity', '').strip()
            if not new_quantity_str:
                flash('请输入数量！', 'error')
                return redirect(url_for('stock.edit_stockout', id=id))
            
            try:
                new_quantity = int(new_quantity_str)
            except ValueError:
                flash('数量必须是有效的整数！', 'error')
                return redirect(url_for('stock.edit_stockout', id=id))
            
            if new_quantity <= 0:
                flash('数量必须大于0！', 'error')
                return redirect(url_for('stock.edit_stockout', id=id))
            
            if new_quantity > 100000:
                flash('数量超出合理范围（最大100000）！', 'error')
                return redirect(url_for('stock.edit_stockout', id=id))
            
            customer = sanitize_plain_text(request.form.get('customer', '').strip())
            if customer and len(customer) > 100:
                flash('客户名称过长（最大100字符）！', 'error')
                return redirect(url_for('stock.edit_stockout', id=id))
            
            stockout_date_str = request.form.get('stockout_date', '').strip()
            if not stockout_date_str:
                flash('请选择出库日期！', 'error')
                return redirect(url_for('stock.edit_stockout', id=id))
            
            try:
                stockout_date = datetime.strptime(stockout_date_str, '%Y-%m-%d')
            except ValueError:
                flash('日期格式不正确！', 'error')
                return redirect(url_for('stock.edit_stockout', id=id))
            
            note = sanitize_plain_text(request.form.get('note', '').strip())
            if len(note) > 500:
                flash('备注过长（最大500字符）！', 'error')
                return redirect(url_for('stock.edit_stockout', id=id))
            
            old_quantity = stockout.quantity

            product = get_product_for_update_sync(db.session, stockout.product_id)

            if product.current_stock + old_quantity < new_quantity:
                flash('库存不足！', 'error')
                return redirect(url_for('stock.edit_stockout', id=id))

            if customer:
                shipment_info = calculate_available_shipment_quantity(stockout.product_id, customer)
                available_with_current = shipment_info['available_quantity'] + old_quantity
                if new_quantity > available_with_current:
                    flash(f'出货数量超过可出货量！订单总量：{shipment_info["order_quantity"]}，已出货（不含当前记录）：{shipment_info["shipped_quantity"] - old_quantity}，可出货：{available_with_current}', 'error')
                    return redirect(url_for('stock.edit_stockout', id=id))

            stockout.quantity = new_quantity
            stockout.stockout_date = stockout_date
            stockout.customer = customer
            stockout.note = note

            if new_quantity != old_quantity:
                product.current_stock -= (new_quantity - old_quantity)

                log = InventoryLog(
                    product_id=stockout.product_id,
                    change_type='出库修改',
                    change_quantity=-(new_quantity - old_quantity),
                    related_id=str(stockout.id),
                    note=f'出库修改ID：{stockout.id}'
                )
                db.session.add(log)

            db.session.commit()
            logger.info(f'出库编辑成功：{stockout.stockout_no}，数量变更：{old_quantity} -> {new_quantity}')
            flash('出库编辑成功！', 'success')
            return redirect(url_for('stock.stockouts'))
            
        except SQLAlchemyError as e:
            db.session.rollback()
            logger.error(f'出库编辑数据库错误：{str(e)}', exc_info=True)
            flash('数据库操作失败，请稍后重试！', 'error')
            return redirect(url_for('stock.edit_stockout', id=id))
        except Exception as e:
            db.session.rollback()
            logger.error(f'出库编辑未知错误：{str(e)}', exc_info=True)
            flash('系统错误，请联系管理员！', 'error')
            return redirect(url_for('stock.edit_stockout', id=id))

    products = Product.query.all()
    customers = Customer.query.filter_by(status=True).order_by(Customer.name).all()
    return render_template('edit_stockout.html', stockout=stockout, products=products, customers=customers)


@stock_bp.route('/out/delete/<int:id>')
@page_permission_required('stockout_manage')
def delete_stockout(id):
    """删除出库记录"""
    stockout = StockOut.query.get_or_404(id)

    if stockout.stockin_id is not None:
        flash('订单抵扣的出货记录不能直接删除！请通过订单管理进行修改。', 'error')
        return redirect(url_for('stock.stockouts'))

    try:
        product = get_product_for_update_sync(db.session, stockout.product_id)
        product.current_stock += stockout.quantity

        log = InventoryLog(
            product_id=stockout.product_id,
            change_type='出库删除',
            change_quantity=stockout.quantity,
            related_id=str(stockout.id),
            note=f'出库删除ID：{stockout.id}'
        )
        db.session.add(log)

        db.session.delete(stockout)
        db.session.commit()
        logger.info(f'出库删除成功：{stockout.stockout_no}，数量：{stockout.quantity}')
        flash('出库删除成功！', 'success')
        return redirect(url_for('stock.stockouts'))
        
    except SQLAlchemyError as e:
        db.session.rollback()
        logger.error(f'出库删除数据库错误：{str(e)}', exc_info=True)
        flash('数据库操作失败，请稍后重试！', 'error')
        return redirect(url_for('stock.stockouts'))
    except Exception as e:
        db.session.rollback()
        logger.error(f'出库删除未知错误：{str(e)}', exc_info=True)
        flash('系统错误，请联系管理员！', 'error')
        return redirect(url_for('stock.stockouts'))


# ==================== 库存查看 ====================

@stock_bp.route('/inventory')
@no_cache
@page_permission_required('stockin_manage')
def inventory():
    """库存查看"""
    from app.models import Order, StockIn, Customer
    
    clear_database_session_cache()

    # 获取搜索参数
    search_customer = request.args.get('customer', '').strip()
    search_product = request.args.get('product', '').strip()

    # 获取所有启用的客户列表
    customers = Customer.query.filter_by(status=True).order_by(Customer.name).all()

    products_query = Product.query.options(
        selectinload(Product.orders),
        selectinload(Product.stockins).selectinload(StockIn.stockin_stockouts)
    )

    # 应用产品名称筛选
    if search_product:
        products_query = products_query.filter(Product.name.like(f'%{escape_like(search_product)}%'))

    products = products_query.all()

    inventory_data = []
    total_order_qty = 0
    total_stockin_qty = 0
    total_total_qty = 0

    # 批量预加载所有产品的出库记录（避免N+1查询）
    product_ids = [p.id for p in products]
    
    # 一次性查询所有相关StockOut（stockin_id=None的独立出库）
    all_stockouts = StockOut.query.filter(
        StockOut.product_id.in_(product_ids),
        StockOut.stockin_id.is_(None)
    ).all()
    
    # 按product_id + customer分组
    stockout_map = {}
    for so in all_stockouts:
        key = (so.product_id, so.customer or '')
        if key not in stockout_map:
            stockout_map[key] = {'direct': 0, 'order': 0, 'total': 0}
        stockout_map[key]['total'] += so.quantity
        if so.order_id:
            stockout_map[key]['order'] += so.quantity
        else:
            stockout_map[key]['direct'] += so.quantity

    # 一次性查询所有相关订单（已通过selectinload加载到product.orders）
    # orders已在product对象中，无需额外查询

    for product in products:
        # 获取该产品所有备货记录
        stockins = product.stockins
        # 如果有客户筛选，只处理该客户的备货
        if search_customer:
            stockins = [s for s in stockins if s.customer == search_customer]

        # 获取所有相关客户
        product_customers = set()
        
        # 从备货记录中获取客户
        for s in stockins:
            if s.customer:
                product_customers.add(s.customer)
        
        # 从出库记录中获取客户（使用预加载数据）
        all_stockouts_for_product = [so for so in all_stockouts if so.product_id == product.id]
        if search_customer:
            all_stockouts_for_product = [so for so in all_stockouts_for_product if so.customer == search_customer]
        
        for so in all_stockouts_for_product:
            if so.customer:
                product_customers.add(so.customer)
        
        # 从订单记录中获取客户（使用预加载数据）
        orders = product.orders
        if search_customer:
            orders = [o for o in orders if o.customer == search_customer]
        
        order_customers = set(o.customer for o in orders)
        product_customers.update(order_customers)

        # 对每个客户计算库存
        for customer in product_customers:
            # 计算该客户的备货剩余数量
            cust_stockin_qty = sum(
                s.quantity - sum(so.quantity for so in s.stockin_stockouts)
                for s in product.stockins if s.customer == customer
            )

            # 计算该客户的直接出库数量（使用预加载数据）
            so_key = (product.id, customer)
            so_data = stockout_map.get(so_key, {'direct': 0, 'order': 0, 'total': 0})
            cust_stockout_qty = so_data['total']
            
            # 计算该客户的订单可用数量
            customer_orders = [o for o in orders if o.customer == customer]
            cust_order_total = sum(o.quantity for o in customer_orders)

            # 使用预计算的出货数据
            direct_shipped = so_data['direct']
            order_shipped = so_data['order']

            # 实际出货总量 = 直接出货 + 订单出货（不包括备货抵扣）
            total_shipped = direct_shipped + order_shipped

            available_order_qty = max(0, cust_order_total - total_shipped)

            # 计算总库存：备货剩余 + 订单可用
            total_stock = max(0, cust_stockin_qty + available_order_qty)

            # 只显示有业务记录且数量大于0的数据
            has_stockin_record = any(s.customer == customer for s in product.stockins)
            has_order_record = len(customer_orders) > 0

            # 只有当数量大于0时才显示
            has_positive_stock = (available_order_qty > 0 or
                                   cust_stockin_qty > 0 or
                                   total_stock > 0)

            if (has_stockin_record or has_order_record) and has_positive_stock:
                inventory_data.append({
                    'customer': customer,
                    'product_name': product.name,
                    'product_barcode': product.barcode or '',
                    'order_quantity': available_order_qty if available_order_qty > 0 else '',
                    'stockin_quantity': cust_stockin_qty if cust_stockin_qty > 0 else '',
                    'stockout_quantity': cust_stockout_qty if cust_stockout_qty > 0 else '',
                    'total_stock': total_stock if total_stock > 0 else ''
                })

                total_stockin_qty += cust_stockin_qty
                total_order_qty += available_order_qty
                total_total_qty += total_stock

    return render_template('inventory.html',
                          products=products,
                          inventory_data=inventory_data,
                          total_order_qty=total_order_qty,
                          total_stockin_qty=total_stockin_qty,
                          total_total_qty=total_total_qty,
                          search_customer=search_customer,
                          search_product=search_product,
                          customers=customers)


@stock_bp.route('/api/export-inventory')
@api_permission_required('stockin_manage')
def export_inventory():
    """导出库存数据API

    [已迁移至 FastAPI] 新代码请使用 GET /api/v1/stock/export-inventory
    """
    try:
        from app.models import Order, StockIn
        from utils.report_exporter import ReportExporter, generate_filename

        search_customer = request.args.get('customer', '').strip()
        search_product = request.args.get('product', '').strip()

        products_query = Product.query.options(
            selectinload(Product.orders),
            selectinload(Product.stockins).selectinload(StockIn.stockin_stockouts)
        )

        if search_product:
            products_query = products_query.filter(Product.name.like(f'%{escape_like(search_product)}%'))

        products = products_query.all()

        # 预加载：批量聚合查询，避免 N+1
        product_ids = [p.id for p in products]

        # StockOut 聚合：按 (product_id, customer, order_id IS NULL) 分组
        stockout_rows = db.session.query(
            StockOut.product_id,
            StockOut.customer,
            StockOut.order_id.is_(None).label('is_direct'),
            db.func.sum(StockOut.quantity).label('total_qty')
        ).filter(
            StockOut.product_id.in_(product_ids),
            StockOut.stockin_id.is_(None)
        ).group_by(
            StockOut.product_id, StockOut.customer, StockOut.order_id.is_(None)
        ).all()

        # 构建查找字典: (product_id, customer) → {direct_qty, order_qty}
        stockout_map = {}
        stockout_customers = {}  # product_id → set of customers
        for row in stockout_rows:
            key = (row.product_id, row.customer)
            if key not in stockout_map:
                stockout_map[key] = {'direct_qty': 0, 'order_qty': 0}
            if row.is_direct:
                stockout_map[key]['direct_qty'] = row.total_qty
            else:
                stockout_map[key]['order_qty'] = row.total_qty
            if row.customer:
                stockout_customers.setdefault(row.product_id, set()).add(row.customer)

        # Order 聚合：按 (product_id, customer) 分组
        order_rows = db.session.query(
            Order.product_id,
            Order.customer,
            db.func.sum(Order.quantity).label('total_qty')
        ).filter(
            Order.product_id.in_(product_ids)
        ).group_by(
            Order.product_id, Order.customer
        ).all()

        order_map = {(r.product_id, r.customer): r.total_qty for r in order_rows}
        order_customers_map = {}  # product_id → set of customers
        for row in order_rows:
            if row.customer:
                order_customers_map.setdefault(row.product_id, set()).add(row.customer)

        inventory_data = []
        total_order_qty = 0
        total_stockin_qty = 0
        total_total_qty = 0

        for product in products:
            stockins = product.stockins
            if search_customer:
                stockins = [s for s in stockins if s.customer == search_customer]

            customers = set()

            for s in stockins:
                if s.customer:
                    customers.add(s.customer)

            for c in stockout_customers.get(product.id, set()):
                if not search_customer or c == search_customer:
                    customers.add(c)

            for c in order_customers_map.get(product.id, set()):
                if not search_customer or c == search_customer:
                    customers.add(c)

            for customer in customers:
                cust_stockin_qty = sum(
                    s.quantity - sum(so.quantity for so in s.stockin_stockouts)
                    for s in product.stockins if s.customer == customer
                )

                so_data = stockout_map.get((product.id, customer), {'direct_qty': 0, 'order_qty': 0})
                direct_shipped = so_data['direct_qty']
                order_shipped = so_data['order_qty']
                total_shipped = direct_shipped + order_shipped

                cust_order_total = order_map.get((product.id, customer), 0)

                available_order_qty = max(0, cust_order_total - total_shipped)
                total_stock = max(0, cust_stockin_qty + available_order_qty)

                has_stockin_record = any(s.customer == customer for s in product.stockins)
                has_order_record = (product.id, customer) in order_map

                has_positive_stock = (available_order_qty > 0 or
                                       cust_stockin_qty > 0 or
                                       total_stock > 0)

                if (has_stockin_record or has_order_record) and has_positive_stock:
                    inventory_data.append({
                        'customer': customer,
                        'product_name': product.name,
                        'product_barcode': product.barcode or '',
                        'order_quantity': available_order_qty if available_order_qty > 0 else '',
                        'stockin_quantity': cust_stockin_qty if cust_stockin_qty > 0 else '',
                        'total_stock': total_stock if total_stock > 0 else ''
                    })

                    total_stockin_qty += cust_stockin_qty
                    total_order_qty += available_order_qty
                    total_total_qty += total_stock
        
        if len(inventory_data) > 10000:
            return jsonify({
                'success': False,
                'error': f'数据量过大({len(inventory_data)}条)，请缩小查询范围后重试'
            }), 400
        
        stats = {
            'total_count': len(inventory_data),
            'total_order_quantity': total_order_qty,
            'total_stockin_quantity': total_stockin_qty,
            'total_stock': total_total_qty
        }
        
        exporter = ReportExporter()
        excel_data = exporter.export_inventory_data(inventory_data, stats)
        
        filename = generate_filename('inventory')
        encoded_filename = quote(filename)
        
        response = make_response(excel_data)
        response.headers['Content-Type'] = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        response.headers['Content-Disposition'] = f"attachment; filename*=UTF-8''{encoded_filename}"
        
        return response
        
    except Exception as e:
        logger.error(f'导出库存数据失败: {str(e)}')
        return jsonify({
            'success': False,
            'error': '导出库存数据失败'
        }), 500
