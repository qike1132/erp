"""
皮套管理路由蓝图
包含皮套入库、出库和库存查询功能
"""
from flask import Blueprint, render_template, request, jsonify, session, current_app
from app import db, csrf
from app.models import Case, CaseStockIn, CaseStockOut, CaseInventoryLog, Product, User, Customer
from utils.number_generator import generate_case_stockin_number, generate_case_stockout_number
from datetime import datetime, timedelta
from sqlalchemy.orm import joinedload, contains_eager
from app.utils.permission_decorators import api_permission_required, page_permission_required
from app.services.shared import escape_like

case_page_bp = Blueprint('case', __name__, url_prefix='/case')
case_api_bp = Blueprint('case_api', __name__)

csrf.exempt(case_api_bp)


# ==================== 页面路由 ====================

@case_page_bp.route('/')
@case_page_bp.route('/stockins')
@page_permission_required('case_manage')
def case_management_page():
    """皮套管理主页面（包含入库、出库、库存三个标签页）"""
    customers = Customer.query.filter_by(status=True).order_by(Customer.name).limit(2000).all()
    customers_list = [c.name for c in customers]
    return render_template('case.html', customers=customers_list, is_home=False)


# ==================== API路由 ====================

@case_api_bp.route('/api/case-search')
@api_permission_required('case_manage')
def case_search():
    """皮套搜索 API (返回所有产品，并附带皮套库存)"""
    query = request.args.get('q', '')
    
    if query:
        products = Product.query.filter(
            Product.name.like(f'%{escape_like(query)}%') | Product.barcode.like(f'%{escape_like(query)}%')
        ).outerjoin(
            Case, Product.id == Case.product_id
        ).options(
            contains_eager(Product.cases)
        ).limit(500).all()
    else:
        products = Product.query.outerjoin(
            Case, Product.id == Case.product_id
        ).options(
            contains_eager(Product.cases)
        ).limit(20).all()
        
    result = []
    for p in products:
        case_stock = p.cases[0].current_stock if p.cases else 0
        
        result.append({
            'id': p.id,
            'name': p.name,
            'barcode': p.barcode or '',
            'current_stock': case_stock
        })
        
    return jsonify(result)


@csrf.exempt
@case_api_bp.route('/api/batch-submit-case-stockins', methods=['POST'])
@api_permission_required('case_manage')
def batch_submit_case_stockins():
    """批量提交皮套入库 API"""
    try:
        data = request.get_json()
        stockins_data = data.get('stockins', [])

        if not stockins_data:
            return jsonify({'success': False, 'error': '没有入库数据'}), 400

        success_count = 0
        failed_stockins = []

        for stockin_data in stockins_data:
            try:
                stockin_no = generate_case_stockin_number(db, CaseStockIn)

                product_id_str = str(stockin_data.get('productId', '')).strip()
                quantity_str = str(stockin_data.get('quantity', '')).strip()
                stockin_date_str = stockin_data.get('stockinDate', '')

                if not product_id_str:
                    failed_stockins.append({'stockin': stockin_data, 'error': '请选择皮套'})
                    continue

                if not quantity_str or quantity_str == '0':
                    failed_stockins.append({'stockin': stockin_data, 'error': '请输入有效的数量'})
                    continue

                if not stockin_date_str:
                    failed_stockins.append({'stockin': stockin_data, 'error': '请选择入库时间'})
                    continue

                try:
                    product_id = int(product_id_str)
                    quantity = int(quantity_str)
                    stockin_date = datetime.strptime(stockin_date_str, '%Y-%m-%d')
                except ValueError:
                    failed_stockins.append({'stockin': stockin_data, 'error': '数据格式错误'})
                    continue

                case_obj = Case.query.filter_by(product_id=product_id).with_for_update().first()
                if not case_obj:
                    linked_product = db.session.get(Product, product_id)
                    if linked_product:
                        case_obj = Case(
                            product_id=linked_product.id,
                            name=linked_product.name,
                            barcode=linked_product.barcode,
                            current_stock=0,
                            initial_stock=0
                        )
                        db.session.add(case_obj)
                        db.session.flush()
                    else:
                        failed_stockins.append({'stockin': stockin_data, 'error': '皮套不存在且未关联有效产品'})
                        continue

                if quantity <= 0:
                    failed_stockins.append({'stockin': stockin_data, 'error': '数量必须大于 0'})
                    continue

                note = stockin_data.get('note', '')
                customer = stockin_data.get('customer', '')

                stockin = CaseStockIn(
                    stockin_no=stockin_no,
                    stockin_date=stockin_date,
                    customer=customer,
                    case_id=case_obj.id,
                    quantity=quantity,
                    note=note
                )
                db.session.add(stockin)

                case_obj.current_stock += quantity

                log = CaseInventoryLog(
                    case_id=case_obj.id,
                    change_type='入库',
                    change_quantity=quantity,
                    related_id=stockin_no,
                    note=f'入库：{stockin_no}',
                    customer=customer
                )
                db.session.add(log)

                success_count += 1
            except Exception as e:
                current_app.logger.error(f'皮套入库处理失败: {e}', exc_info=True)
                failed_stockins.append({'stockin': stockin_data, 'error': '入库处理失败'})

        db.session.commit()

        return jsonify({
            'success': True,
            'message': f'成功提交 {success_count} 条入库记录',
            'failed': failed_stockins
        })
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'皮套入库批量提交失败: {e}', exc_info=True)
        return jsonify({'success': False, 'error': '更新失败，请稍后重试'}), 500




@case_api_bp.route('/api/case-stockin/<int:stockin_id>', methods=['DELETE'])
@api_permission_required('case_manage')
def delete_case_stockin(stockin_id):
    """删除皮套入库记录"""
    try:
        stockin = CaseStockIn.query.get_or_404(stockin_id)

        if CaseStockOut.query.filter_by(case_id=stockin.case_id).first():
            return jsonify({'success': False, 'error': '该入库记录已有出库，无法删除'}), 400

        case_obj = Case.query.with_for_update().get(stockin.case_id)
        if case_obj:
            case_obj.current_stock -= stockin.quantity

            log = CaseInventoryLog(
                case_id=stockin.case_id,
                change_type='删除入库',
                change_quantity=-stockin.quantity,
                related_id=stockin.stockin_no,
                note=f'删除入库：{stockin.stockin_no}'
            )
            db.session.add(log)

        db.session.delete(stockin)
        db.session.commit()

        return jsonify({'success': True, 'message': '删除成功'})
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'皮套入库删除失败: {e}', exc_info=True)
        return jsonify({'success': False, 'error': '删除失败，请稍后重试'}), 500


@csrf.exempt
@case_api_bp.route('/api/case-stockouts')
@api_permission_required('case_manage')
def api_case_stockouts():
    """获取皮套出库列表 API（支持搜索）"""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    customer = request.args.get('customer', '')
    start_date = request.args.get('start_date', '')
    end_date = request.args.get('end_date', '')
    quantity_min = request.args.get('quantity_min', type=int)
    quantity_max = request.args.get('quantity_max', type=int)

    query = CaseStockOut.query

    if customer:
        query = query.filter(CaseStockOut.customer.like(f'%{escape_like(customer)}%'))

    if start_date:
        start = datetime.strptime(start_date, '%Y-%m-%d')
        query = query.filter(CaseStockOut.stockout_date >= start)

    if end_date:
        end = datetime.strptime(end_date, '%Y-%m-%d') + timedelta(days=1)
        query = query.filter(CaseStockOut.stockout_date < end)

    if quantity_min:
        query = query.filter(CaseStockOut.quantity >= quantity_min)

    if quantity_max:
        query = query.filter(CaseStockOut.quantity <= quantity_max)

    query = query.order_by(CaseStockOut.stockout_date.desc())
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    result = []
    for stockout in pagination.items:
        result.append({
            'id': stockout.id,
            'stockout_no': stockout.stockout_no,
            'stockout_date': stockout.stockout_date.strftime('%Y-%m-%d'),
            'customer': stockout.customer or '',
            'case_id': stockout.case_id,
            'case_name': stockout.case.sync_name,
            'case_barcode': stockout.case.sync_barcode or '',
            'quantity': stockout.quantity,
            'note': stockout.note or ''
        })

    return jsonify({
        'stockouts': result,
        'total': pagination.total,
        'pages': pagination.pages,
        'current_page': page
    })


@csrf.exempt
@case_api_bp.route('/api/case-stockout/<int:stockout_id>', methods=['GET'])
@api_permission_required('case_manage')
def get_case_stockout(stockout_id):
    """获取单个皮套出库记录"""
    stockout = CaseStockOut.query.get_or_404(stockout_id)
    return jsonify({
        'id': stockout.id,
        'stockout_no': stockout.stockout_no,
        'stockout_date': stockout.stockout_date.strftime('%Y-%m-%d'),
        'customer': stockout.customer,
        'case_id': stockout.case_id,
        'case_name': stockout.case.sync_name,
        'quantity': stockout.quantity,
        'note': stockout.note or ''
    })


@case_api_bp.route('/api/case-stockout/<int:stockout_id>', methods=['PUT'])
@api_permission_required('case_manage')
def update_case_stockout(stockout_id):
    """更新皮套出库记录"""
    try:
        data = request.get_json()
        stockout = CaseStockOut.query.get_or_404(stockout_id)

        old_quantity = stockout.quantity
        new_quantity = data.get('quantity', old_quantity)
        quantity_change = new_quantity - old_quantity

        stockout.customer = data.get('customer', stockout.customer)
        stockout.stockout_date = datetime.strptime(data.get('stockout_date', stockout.stockout_date.strftime('%Y-%m-%d')), '%Y-%m-%d')
        stockout.quantity = new_quantity
        stockout.note = data.get('note', stockout.note)

        case_obj = Case.query.with_for_update().get(stockout.case_id)
        if case_obj:
            case_obj.current_stock -= quantity_change
            if case_obj.current_stock < 0:
                current_app.logger.warning(f'皮套库存出现负数：{case_obj.name}(ID:{case_obj.id})，当前库存{case_obj.current_stock}')

            log = CaseInventoryLog(
                case_id=stockout.case_id,
                change_type='出库调整',
                change_quantity=-quantity_change,
                related_id=stockout.stockout_no,
                note=f'出库调整：{stockout.stockout_no}'
            )
            db.session.add(log)

        db.session.commit()

        return jsonify({'success': True, 'message': '更新成功'})
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'皮套出库更新失败: {e}', exc_info=True)
        return jsonify({'success': False, 'error': '更新失败，请稍后重试'}), 500




@case_api_bp.route('/api/case-stockout/<int:stockout_id>', methods=['DELETE'])
@api_permission_required('case_manage')
def delete_case_stockout(stockout_id):
    """删除皮套出库记录"""
    try:
        stockout = CaseStockOut.query.get_or_404(stockout_id)

        case_obj = Case.query.with_for_update().get(stockout.case_id)
        if case_obj:
            case_obj.current_stock += stockout.quantity

            log = CaseInventoryLog(
                case_id=stockout.case_id,
                change_type='删除出库',
                change_quantity=stockout.quantity,
                related_id=stockout.stockout_no,
                note=f'删除出库：{stockout.stockout_no}'
            )
            db.session.add(log)

        db.session.delete(stockout)
        db.session.commit()

        return jsonify({'success': True, 'message': '删除成功'})
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'皮套出库删除失败: {e}', exc_info=True)
        return jsonify({'success': False, 'error': '删除失败，请稍后重试'}), 500


@case_api_bp.route('/api/case-inventory-summary')
@api_permission_required('case_manage')
def case_inventory_summary():
    """获取皮套库存汇总"""
    from sqlalchemy import func
    
    total_in_subquery = db.session.query(
        CaseStockIn.case_id,
        func.sum(CaseStockIn.quantity).label('total_in')
    ).group_by(CaseStockIn.case_id).subquery()
    
    total_out_subquery = db.session.query(
        CaseStockOut.case_id,
        func.sum(CaseStockOut.quantity).label('total_out')
    ).group_by(CaseStockOut.case_id).subquery()
    
    results = db.session.query(
        Case,
        func.coalesce(total_in_subquery.c.total_in, 0).label('total_in'),
        func.coalesce(total_out_subquery.c.total_out, 0).label('total_out')
    ).outerjoin(
        total_in_subquery, Case.id == total_in_subquery.c.case_id
    ).outerjoin(
        total_out_subquery, Case.id == total_out_subquery.c.case_id
    ).limit(5000).all()
    
    data = []
    for case, total_in, total_out in results:
        calculated_stock = int(total_in or 0) - int(total_out or 0)
        
        if total_in == 0 and total_out == 0 and calculated_stock == 0:
            continue
        
        data.append({
            'id': case.id,
            'name': case.sync_name,
            'barcode': case.sync_barcode or '',
            'initial_stock': case.initial_stock,
            'current_stock': calculated_stock,
            'total_in': int(total_in or 0),
            'total_out': int(total_out or 0)
        })
    return jsonify(data)


@case_api_bp.route('/api/case-inventory-logs/<int:case_id>')
@api_permission_required('case_manage')
def case_inventory_logs(case_id):
    """获取皮套库存流水"""
    try:
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 20, type=int)
        log_type = request.args.get('type', '')
        start_date = request.args.get('start_date', '')
        end_date = request.args.get('end_date', '')

        query = CaseInventoryLog.query.filter_by(case_id=case_id)

        if log_type:
            query = query.filter(CaseInventoryLog.change_type == log_type)

        if start_date:
            start = datetime.strptime(start_date, '%Y-%m-%d')
            query = query.filter(CaseInventoryLog.change_date >= start)

        if end_date:
            end = datetime.strptime(end_date, '%Y-%m-%d') + timedelta(days=1)
            query = query.filter(CaseInventoryLog.change_date < end)

        logs = query.order_by(CaseInventoryLog.change_date.desc())\
            .paginate(page=page, per_page=per_page, error_out=False)

        result = [{
            'id': log.id,
            'change_type': log.change_type,
            'change_quantity': log.change_quantity,
            'change_date': log.change_date.strftime('%Y-%m-%d %H:%M:%S'),
            'customer': log.customer or '',
            'related_id': log.related_id or '',
            'note': log.note or ''
        } for log in logs.items]

        return jsonify({
            'success': True,
            'logs': result,
            'pagination': {
                'page': logs.page,
                'pages': logs.pages,
                'total': logs.total,
                'has_next': logs.has_next,
                'has_prev': logs.has_prev
            }
        })
    except Exception as e:
        current_app.logger.error(f"皮套库存日志查询失败: {e}", exc_info=True)
        return jsonify({'success': False, 'error': '查询日志失败，请稍后重试'}), 500


@case_api_bp.route('/api/batch-submit-case-stockouts', methods=['POST'])
@api_permission_required('case_manage')
def batch_submit_case_stockouts():
    """批量提交皮套出库"""
    try:
        data = request.get_json()
        stockouts_data = data.get('stockouts', [])
        
        results = []
        for stockout_data in stockouts_data:
            try:
                case_id = stockout_data.get('case_id') or stockout_data.get('productId')
                quantity = stockout_data.get('quantity')
                
                if not all([case_id, quantity]):
                    results.append({
                        'success': False,
                        'error': '缺少必填字段',
                        'id': stockout_data.get('id', '未知')
                    })
                    continue
                
                case = Case.query.filter_by(product_id=case_id).with_for_update().first()
                if not case:
                    results.append({
                        'success': False,
                        'error': f'未找到关联产品ID {case_id} 的皮套，可能尚未入库',
                        'id': stockout_data.get('id', '未知')
                    })
                    continue
                
                if case.current_stock < int(quantity):
                    results.append({
                        'success': False,
                        'error': f'库存不足，当前库存: {case.current_stock}',
                        'id': stockout_data.get('id', '未知')
                    })
                    continue
                
                stockout = CaseStockOut(
                    stockout_no=generate_case_stockout_number(db, CaseStockOut),
                    case_id=case.id,
                    quantity=int(quantity),
                    stockout_date=datetime.strptime(
                        stockout_data.get('stockout_date', datetime.now().strftime('%Y-%m-%d')),
                        '%Y-%m-%d'
                    ),
                    customer=stockout_data.get('customer', ''),
                    note=stockout_data.get('note', '')
                )
                db.session.add(stockout)
                db.session.flush()
                
                case.current_stock -= int(quantity)
                
                log = CaseInventoryLog(
                    case_id=case.id,
                    change_type='出库',
                    change_quantity=-int(quantity),
                    change_date=datetime.now(),
                    customer=stockout_data.get('customer', ''),
                    related_id=stockout.stockout_no,
                    note=f'出库 {stockout.stockout_no}'
                )
                db.session.add(log)
                
                results.append({
                    'success': True,
                    'stockout_no': stockout.stockout_no,
                    'id': stockout.id
                })
            except Exception as e:
                current_app.logger.error(f"皮套出库单项失败: {e}", exc_info=True)
                results.append({
                    'success': False,
                    'error': '出库处理失败',
                    'id': stockout_data.get('id', '未知')
                })
        
        db.session.commit()
        return jsonify({'success': True, 'results': results})
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"批量提交皮套出库失败: {e}", exc_info=True)
        return jsonify({'success': False, 'error': '批量出库提交失败，请稍后重试'}), 500


@case_api_bp.route('/api/case-product/<int:case_id>', methods=['DELETE'])
@api_permission_required('case_manage')
def delete_case_product(case_id):
    """删除皮套产品"""
    try:
        case_obj = Case.query.get_or_404(case_id)
        if case_obj.current_stock != 0:
            return jsonify({'success': False, 'error': '只能删除库存为0的皮套'}), 400
        db.session.delete(case_obj)
        db.session.commit()
        return jsonify({'success': True, 'message': '删除成功'})
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'皮套产品删除失败: {e}', exc_info=True)
        return jsonify({'success': False, 'error': '删除失败，请稍后重试'}), 500


@case_api_bp.route('/api/case-products', methods=['GET', 'POST'])
@api_permission_required('case_manage')
def case_products():
    """皮套产品管理 API"""
    if request.method == 'POST':
        name = request.form.get('name')
        barcode = request.form.get('barcode')
        image = request.form.get('image')
        product_id = request.form.get('product_id')

        if not name and not product_id:
            return jsonify({'success': False, 'error': '皮套名称或关联产品不能为空'}), 400

        if product_id and not name:
            linked_product = db.session.get(Product, product_id)
            if linked_product:
                name = linked_product.name
                if not barcode:
                    barcode = linked_product.barcode

        case = Case(name=name or '', barcode=barcode or '', image=image, product_id=product_id if product_id else None)
        db.session.add(case)
        db.session.commit()
        return jsonify({'success': True, 'message': '添加成功'})

    cases = Case.query.options(
        joinedload(Case.product)
    ).order_by(Case.create_time.desc()).limit(2000).all()
    return jsonify({'cases': [{
        'id': c.id,
        'name': c.sync_name,
        'barcode': c.sync_barcode or '',
        'image': c.image or '',
        'current_stock': c.current_stock,
        'create_time': c.create_time.strftime('%Y-%m-%d')
    } for c in cases]})



