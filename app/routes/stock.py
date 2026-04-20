"""
库存管理路由蓝图
包含入库、出库和库存查看功能
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, make_response
from app import db
from app.models import Product, StockIn, StockOut, Customer
from fastapi_app.shared.stock_crud_service import (
    calculate_available_shipment_quantity,
    create_stockin as shared_create_stockin,
    update_stockin as shared_update_stockin,
    create_stockout as shared_create_stockout,
    update_stockout as shared_update_stockout,
    get_inventory as shared_get_inventory,
    generate_stockin_number_sync,
    generate_stockout_number_sync,
)
from app.services.shared import validate_quantity, validate_customer, validate_note, parse_date, build_datetime_with_time, escape_like
from datetime import datetime
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

            try:
                shared_create_stockin(
                    session=db.session,
                    product_id=product_id,
                    quantity=quantity,
                    customer=customer,
                    stockin_date=stockin_date,
                    note=note
                )
            except ValueError as e:
                flash(str(e), 'error')
                return redirect(url_for('stock.stockins'))

            db.session.commit()
            logger.info(f'入库添加成功：客户：{customer}，产品ID：{product_id}，数量：{quantity}')
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
    ).order_by(StockIn.stockin_date.desc()).limit(2000).all()
    products = Product.query.limit(5000).all()
    customers = Customer.query.filter_by(status=True).order_by(Customer.name).limit(2000).all()
    preview_stockin_no = generate_stockin_number_sync(db.session)
    
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
            stockin_date_dt = None
            old_time = stockin.stockin_date
            if old_time and (old_time.hour != 0 or old_time.minute != 0 or old_time.second != 0):
                stockin_date_dt = datetime(
                    stockin_date_base.year,
                    stockin_date_base.month,
                    stockin_date_base.day,
                    old_time.hour,
                    old_time.minute,
                    old_time.second
                )
            else:
                now = datetime.now()
                stockin_date_dt = datetime(
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

            try:
                shared_update_stockin(
                    session=db.session,
                    stockin=stockin,
                    new_quantity=new_quantity,
                    customer=customer,
                    stockin_date=stockin_date_dt,
                    note=note
                )
            except ValueError as e:
                flash(str(e), 'error')
                return redirect(url_for('stock.edit_stockin', id=id))

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

    products = Product.query.limit(5000).all()
    customers = Customer.query.filter_by(status=True).order_by(Customer.name).limit(2000).all()
    return render_template('edit_stockin.html', stockin=stockin, products=products, customers=customers)





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

            order_type = request.form.get('order_type', 'regular').strip() or 'regular'
            country = request.form.get('country', '').strip()
            if order_type == 'custom' and not country:
                flash('定制订单必须填写国家名称！', 'error')
                return redirect(url_for('stock.stockouts'))

            try:
                shared_create_stockout(
                    session=db.session,
                    product_id=product_id,
                    quantity=quantity,
                    customer=customer,
                    stockout_date=stockout_date,
                    note=note,
                    order_type=order_type,
                    country=country or None
                )
            except ValueError as e:
                flash(str(e), 'error')
                return redirect(url_for('stock.stockouts'))

            db.session.commit()
            logger.info(f'出库添加成功：产品ID：{product_id}，数量：{quantity}，客户：{customer or "无"}')
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
        joinedload(StockOut.product),
        joinedload(StockOut.order)
    ).filter(StockOut.stockin_id.is_(None)).order_by(StockOut.stockout_date.desc()).limit(2000).all()
    products = Product.query.limit(5000).all()
    customers = Customer.query.filter_by(status=True).order_by(Customer.name).limit(2000).all()
    preview_stockout_no = generate_stockout_number_sync(db.session)
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
        'note': s.note or '',
        'order_type': s.order.order_type if s.order else 'regular',
        'country': s.order.country if s.order and s.order.country else ''
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

            try:
                shared_update_stockout(
                    session=db.session,
                    stockout=stockout,
                    new_quantity=new_quantity,
                    customer=customer,
                    stockout_date=stockout_date,
                    note=note
                )
            except ValueError as e:
                flash(str(e), 'error')
                return redirect(url_for('stock.edit_stockout', id=id))

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

    products = Product.query.limit(5000).all()
    customers = Customer.query.filter_by(status=True).order_by(Customer.name).limit(2000).all()
    return render_template('edit_stockout.html', stockout=stockout, products=products, customers=customers)




# ==================== 库存查看 ====================

@stock_bp.route('/inventory')
@no_cache
@page_permission_required('stockin_manage')
def inventory():
    """库存查看"""
    clear_database_session_cache()

    # 获取搜索参数
    search_customer = request.args.get('customer', '').strip()
    search_product = request.args.get('product', '').strip()

    # 获取所有启用的客户列表（用于下拉框）
    customers = Customer.query.filter_by(status=True).order_by(Customer.name).limit(2000).all()

    # 使用统一的库存计算服务
    result = shared_get_inventory(db.session, search_customer, search_product)

    return render_template('inventory.html',
                          products=[],
                          inventory_data=result['inventory_data'],
                          total_order_qty=result['total_order_qty'],
                          total_stockin_qty=result['total_stockin_qty'],
                          total_total_qty=result['total_stock'],
                          all_countries=result['all_countries'],
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
        from utils.report_exporter import ReportExporter, generate_filename

        search_customer = request.args.get('customer', '').strip()
        search_product = request.args.get('product', '').strip()

        result = shared_get_inventory(db.session, search_customer, search_product)

        inventory_data = result['inventory_data']
        if len(inventory_data) > 10000:
            return jsonify({
                'success': False,
                'error': f'数据量过大({len(inventory_data)}条)，请缩小查询范围后重试'
            }), 400

        stats = {
            'total_count': len(inventory_data),
            'total_order_quantity': result['total_order_qty'],
            'total_stockin_quantity': result['total_stockin_qty'],
            'total_stock': result['total_stock'],
            'all_countries': result['all_countries'],
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


# ==================== AJAX 分页 API ====================

from flask import Blueprint as _Bp
from app import csrf

stock_api_bp = _Bp('stock_api', __name__, url_prefix='/stock/api')
csrf.exempt(stock_api_bp)


@stock_api_bp.route('/stockins')
@api_permission_required('stockin_manage')
def api_stockins():
    """入库列表分页 API"""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)

    query = StockIn.query.options(
        joinedload(StockIn.product),
        selectinload(StockIn.stockin_stockouts)
    ).order_by(StockIn.stockin_date.desc())

    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    result = []
    for s in pagination.items:
        result.append({
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
        })

    return jsonify({
        'items': result,
        'total': pagination.total,
        'pages': pagination.pages,
        'current_page': page
    })


@stock_api_bp.route('/stockouts')
@api_permission_required('stockout_manage')
def api_stockouts():
    """出库列表分页 API"""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)

    query = StockOut.query.options(
        joinedload(StockOut.product),
        joinedload(StockOut.order)
    ).filter(StockOut.stockin_id.is_(None)).order_by(StockOut.stockout_date.desc())

    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    result = []
    for s in pagination.items:
        result.append({
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
            'note': s.note or '',
            'order_type': s.order.order_type if s.order else 'regular',
            'country': s.order.country if s.order and s.order.country else ''
        })

    return jsonify({
        'items': result,
        'total': pagination.total,
        'pages': pagination.pages,
        'current_page': page
    })
