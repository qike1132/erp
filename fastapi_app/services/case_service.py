"""皮套管理服务层"""
import logging
from datetime import datetime, timedelta
from sqlalchemy import select, func, or_
from sqlalchemy.orm import joinedload

from fastapi_app.shared_models import Case, CaseStockIn, CaseStockOut, CaseInventoryLog, Product

logger = logging.getLogger(__name__)


async def search_cases(db, query: str = '') -> list[dict]:
    """搜索皮套（附库存信息）"""
    q = select(Product).outerjoin(Case, Product.id == Case.product_id).options(
        joinedload(Product.cases)
    )
    if query:
        q = q.where(Product.name.contains(query) | Product.barcode.contains(query))
    else:
        q = q.limit(20)

    result = await db.execute(q)
    products = list(result.unique().scalars().all())

    return [{
        'id': p.id,
        'name': p.name,
        'barcode': p.barcode or '',
        'current_stock': p.cases[0].current_stock if p.cases else 0,
    } for p in products]


async def get_case_stockins(db, page: int = 1, per_page: int = 20, customer: str = '',
                             start_date: str = '', end_date: str = '',
                             quantity_min: int | None = None, quantity_max: int | None = None) -> dict:
    """获取皮套入库列表"""
    query = select(CaseStockIn).options(joinedload(CaseStockIn.case).joinedload(Case.product))

    if customer:
        query = query.where(CaseStockIn.customer.contains(customer))
    if start_date:
        query = query.where(CaseStockIn.stockin_date >= datetime.strptime(start_date, '%Y-%m-%d'))
    if end_date:
        query = query.where(CaseStockIn.stockin_date < datetime.strptime(end_date, '%Y-%m-%d') + timedelta(days=1))
    if quantity_min is not None:
        query = query.where(CaseStockIn.quantity >= quantity_min)
    if quantity_max is not None:
        query = query.where(CaseStockIn.quantity <= quantity_max)

    # 总数
    count_q = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_q)).scalar() or 0

    query = query.order_by(CaseStockIn.stockin_date.desc())
    offset = (page - 1) * per_page
    query = query.offset(offset).limit(per_page)
    result = await db.execute(query)
    stockins = list(result.unique().scalars().all())

    return {
        'stockins': [{
            'id': s.id, 'stockin_no': s.stockin_no,
            'stockin_date': s.stockin_date.strftime('%Y-%m-%d') if s.stockin_date else '',
            'customer': s.customer, 'case_id': s.case_id,
            'case_name': s.case.sync_name if s.case else '',
            'case_barcode': s.case.sync_barcode if s.case else '',
            'quantity': s.quantity, 'note': s.note or '',
        } for s in stockins],
        'total': total,
        'pages': (total + per_page - 1) // per_page if per_page else 0,
        'current_page': page,
    }


async def get_case_stockout_list(db, page: int = 1, per_page: int = 20, customer: str = '',
                                 start_date: str = '', end_date: str = '',
                                 quantity_min: int | None = None, quantity_max: int | None = None) -> dict:
    """获取皮套出库列表"""
    query = select(CaseStockOut).options(joinedload(CaseStockOut.case).joinedload(Case.product))

    if customer:
        query = query.where(CaseStockOut.customer.contains(customer))
    if start_date:
        query = query.where(CaseStockOut.stockout_date >= datetime.strptime(start_date, '%Y-%m-%d'))
    if end_date:
        query = query.where(CaseStockOut.stockout_date < datetime.strptime(end_date, '%Y-%m-%d') + timedelta(days=1))
    if quantity_min is not None:
        query = query.where(CaseStockOut.quantity >= quantity_min)
    if quantity_max is not None:
        query = query.where(CaseStockOut.quantity <= quantity_max)

    count_q = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_q)).scalar() or 0

    query = query.order_by(CaseStockOut.stockout_date.desc())
    offset = (page - 1) * per_page
    query = query.offset(offset).limit(per_page)
    result = await db.execute(query)
    stockouts = list(result.unique().scalars().all())

    return {
        'stockouts': [{
            'id': s.id, 'stockout_no': s.stockout_no,
            'stockout_date': s.stockout_date.strftime('%Y-%m-%d') if s.stockout_date else '',
            'customer': s.customer or '', 'case_id': s.case_id,
            'case_name': s.case.sync_name if s.case else '',
            'case_barcode': s.case.sync_barcode if s.case else '',
            'quantity': s.quantity, 'note': s.note or '',
        } for s in stockouts],
        'total': total,
        'pages': (total + per_page - 1) // per_page if per_page else 0,
        'current_page': page,
    }


async def get_case_inventory_summary(db) -> list[dict]:
    """获取皮套库存汇总"""
    in_sq = select(CaseStockIn.case_id, func.sum(CaseStockIn.quantity).label('total_in')).group_by(CaseStockIn.case_id).subquery()
    out_sq = select(CaseStockOut.case_id, func.sum(CaseStockOut.quantity).label('total_out')).group_by(CaseStockOut.case_id).subquery()

    result = await db.execute(
        select(Case, func.coalesce(in_sq.c.total_in, 0), func.coalesce(out_sq.c.total_out, 0))
        .outerjoin(in_sq, Case.id == in_sq.c.case_id)
        .outerjoin(out_sq, Case.id == out_sq.c.case_id)
    )

    data = []
    for case_obj, total_in, total_out in result.all():
        calc_stock = int(total_in or 0) - int(total_out or 0)
        if total_in == 0 and total_out == 0 and calc_stock == 0:
            continue
        data.append({
            'id': case_obj.id, 'name': case_obj.sync_name, 'barcode': case_obj.sync_barcode or '',
            'initial_stock': case_obj.initial_stock, 'current_stock': calc_stock,
            'total_in': int(total_in or 0), 'total_out': int(total_out or 0),
        })
    return data


async def get_case_inventory_logs(db, case_id: int, page: int = 1, per_page: int = 20,
                                   log_type: str = '', start_date: str = '', end_date: str = '') -> dict:
    """获取皮套库存流水"""
    query = select(CaseInventoryLog).where(CaseInventoryLog.case_id == case_id)

    if log_type:
        query = query.where(CaseInventoryLog.change_type == log_type)
    if start_date:
        query = query.where(CaseInventoryLog.change_date >= datetime.strptime(start_date, '%Y-%m-%d'))
    if end_date:
        query = query.where(CaseInventoryLog.change_date < datetime.strptime(end_date, '%Y-%m-%d') + timedelta(days=1))

    count_q = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_q)).scalar() or 0

    query = query.order_by(CaseInventoryLog.change_date.desc())
    offset = (page - 1) * per_page
    query = query.offset(offset).limit(per_page)
    result = await db.execute(query)
    logs = list(result.scalars().all())

    return {
        'success': True,
        'logs': [{
            'id': l.id, 'change_type': l.change_type, 'change_quantity': l.change_quantity,
            'change_date': l.change_date.strftime('%Y-%m-%d %H:%M:%S') if l.change_date else '',
            'customer': l.customer or '', 'related_id': l.related_id or '', 'note': l.note or '',
        } for l in logs],
        'pagination': {
            'page': page, 'pages': (total + per_page - 1) // per_page if per_page else 0,
            'total': total,
        },
    }


async def create_case_stockin(db, product_id: int, quantity: int, stockin_date: str,
                               customer: str = '', note: str = '', stockin_no: str = '') -> dict:
    """创建皮套入库记录"""
    case_obj = await db.execute(select(Case).where(Case.product_id == product_id).with_for_update())
    case_obj = case_obj.scalar_one_or_none()

    if not case_obj:
        product = await db.get(Product, product_id)
        if not product:
            raise ValueError("产品不存在")
        case_obj = Case(product_id=product.id, name=product.name, barcode=product.barcode,
                        current_stock=0, initial_stock=0)
        db.add(case_obj)
        await db.flush()

    stockin = CaseStockIn(stockin_no=stockin_no, stockin_date=datetime.strptime(stockin_date, '%Y-%m-%d'),
                          customer=customer, case_id=case_obj.id, quantity=quantity, note=note)
    db.add(stockin)
    case_obj.current_stock += quantity

    log = CaseInventoryLog(case_id=case_obj.id, change_type='入库', change_quantity=quantity,
                           related_id=stockin_no, note=f'入库：{stockin_no}', customer=customer)
    db.add(log)
    await db.flush()
    return {'success': True, 'stockin_no': stockin_no, 'id': stockin.id}


async def create_case_stockout(db, case_id_or_product_id: int, quantity: int,
                                stockout_date: str, customer: str = '',
                                note: str = '', stockout_no: str = '') -> dict:
    """创建皮套出库记录"""
    case_obj = await db.execute(select(Case).where(Case.product_id == case_id_or_product_id).with_for_update())
    case_obj = case_obj.scalar_one_or_none()

    if not case_obj:
        raise ValueError(f"未找到关联产品ID {case_id_or_product_id} 的皮套")
    if case_obj.current_stock < quantity:
        raise ValueError(f"库存不足，当前库存: {case_obj.current_stock}")

    stockout = CaseStockOut(stockout_no=stockout_no, case_id=case_obj.id, quantity=quantity,
                            stockout_date=datetime.strptime(stockout_date, '%Y-%m-%d'),
                            customer=customer, note=note)
    db.add(stockout)
    await db.flush()

    case_obj.current_stock -= quantity

    log = CaseInventoryLog(case_id=case_obj.id, change_type='出库', change_quantity=-quantity,
                           change_date=datetime.now(), customer=customer,
                           related_id=stockout_no, note=f'出库 {stockout_no}')
    db.add(log)
    return {'success': True, 'stockout_no': stockout_no, 'id': stockout.id}


async def delete_case_product(db, case_id: int) -> None:
    """删除皮套产品"""
    case_obj = await db.get(Case, case_id)
    if not case_obj:
        raise ValueError("皮套不存在")
    if case_obj.current_stock != 0:
        raise ValueError("只能删除库存为0的皮套")
    await db.delete(case_obj)
    await db.flush()


async def update_case_stockin(db, stockin_id: int, update_data: dict) -> dict:
    """更新皮套入库记录"""
    stockin = await db.get(CaseStockIn, stockin_id)
    if not stockin:
        raise ValueError("入库记录不存在")

    old_quantity = stockin.quantity
    if 'quantity' in update_data:
        new_quantity = update_data['quantity']
        quantity_change = new_quantity - old_quantity
        stockin.quantity = new_quantity

        case_obj = await db.execute(select(Case).where(Case.id == stockin.case_id).with_for_update())
        case_obj = case_obj.scalar_one_or_none()
        if case_obj:
            case_obj.current_stock += quantity_change
            log = CaseInventoryLog(
                case_id=stockin.case_id, change_type='入库调整',
                change_quantity=quantity_change, related_id=stockin.stockin_no,
                note=f'入库调整：{stockin.stockin_no}'
            )
            db.add(log)

    if 'customer' in update_data:
        stockin.customer = update_data['customer']
    if 'stockin_date' in update_data:
        stockin.stockin_date = datetime.strptime(update_data['stockin_date'], '%Y-%m-%d')
    if 'note' in update_data:
        stockin.note = update_data['note']

    await db.flush()
    return {'success': True, 'message': '更新成功'}


async def delete_case_stockin(db, stockin_id: int) -> dict:
    """删除皮套入库记录"""
    stockin = await db.get(CaseStockIn, stockin_id)
    if not stockin:
        raise ValueError("入库记录不存在")

    # 检查是否有出库关联
    has_stockout = (await db.execute(
        select(func.count()).select_from(CaseStockOut).where(CaseStockOut.case_id == stockin.case_id)
    )).scalar()
    if has_stockout:
        raise ValueError("该入库记录已有出库，无法删除")

    case_obj = await db.execute(select(Case).where(Case.id == stockin.case_id).with_for_update())
    case_obj = case_obj.scalar_one_or_none()
    if case_obj:
        case_obj.current_stock -= stockin.quantity
        log = CaseInventoryLog(
            case_id=stockin.case_id, change_type='删除入库',
            change_quantity=-stockin.quantity, related_id=stockin.stockin_no,
            note=f'删除入库：{stockin.stockin_no}'
        )
        db.add(log)

    await db.delete(stockin)
    await db.flush()
    return {'success': True, 'message': '删除成功'}


async def update_case_stockout(db, stockout_id: int, update_data: dict) -> dict:
    """更新皮套出库记录"""
    stockout = await db.get(CaseStockOut, stockout_id)
    if not stockout:
        raise ValueError("出库记录不存在")

    old_quantity = stockout.quantity
    if 'quantity' in update_data:
        new_quantity = update_data['quantity']
        quantity_change = new_quantity - old_quantity
        stockout.quantity = new_quantity

        case_obj = await db.execute(select(Case).where(Case.id == stockout.case_id).with_for_update())
        case_obj = case_obj.scalar_one_or_none()
        if case_obj:
            case_obj.current_stock -= quantity_change
            log = CaseInventoryLog(
                case_id=stockout.case_id, change_type='出库调整',
                change_quantity=-quantity_change, related_id=stockout.stockout_no,
                note=f'出库调整：{stockout.stockout_no}'
            )
            db.add(log)

    if 'customer' in update_data:
        stockout.customer = update_data['customer']
    if 'stockout_date' in update_data:
        stockout.stockout_date = datetime.strptime(update_data['stockout_date'], '%Y-%m-%d')
    if 'note' in update_data:
        stockout.note = update_data['note']

    await db.flush()
    return {'success': True, 'message': '更新成功'}


async def delete_case_stockout(db, stockout_id: int) -> dict:
    """删除皮套出库记录"""
    stockout = await db.get(CaseStockOut, stockout_id)
    if not stockout:
        raise ValueError("出库记录不存在")

    case_obj = await db.execute(select(Case).where(Case.id == stockout.case_id).with_for_update())
    case_obj = case_obj.scalar_one_or_none()
    if case_obj:
        case_obj.current_stock += stockout.quantity
        log = CaseInventoryLog(
            case_id=stockout.case_id, change_type='删除出库',
            change_quantity=stockout.quantity, related_id=stockout.stockout_no,
            note=f'删除出库：{stockout.stockout_no}'
        )
        db.add(log)

    await db.delete(stockout)
    await db.flush()
    return {'success': True, 'message': '删除成功'}


async def batch_create_case_stockins(db, stockins_data: list) -> dict:
    """批量提交皮套入库"""
    success_count = 0
    failed = []

    for i, item in enumerate(stockins_data):
        try:
            product_id = int(item.get('productId', item.get('product_id', 0)))
            quantity = int(item.get('quantity', 0))
            stockin_date = item.get('stockinDate', item.get('stockin_date', datetime.now().strftime('%Y-%m-%d')))
            customer = item.get('customer', '')
            note = item.get('note', '')

            if not product_id or quantity <= 0:
                failed.append({'index': i, 'error': '产品ID或数量无效'})
                continue

            # 生成入库单号
            from fastapi_app.services.batch_service import generate_case_stockin_number
            stockin_no = await generate_case_stockin_number(db)

            await create_case_stockin(db, product_id, quantity, stockin_date, customer, note, stockin_no)
            success_count += 1
        except Exception as e:
            failed.append({'index': i, 'error': str(e)})

    return {'success': True, 'message': f'成功提交 {success_count} 条入库记录', 'failed': failed}


async def batch_create_case_stockouts(db, stockouts_data: list) -> dict:
    """批量提交皮套出库"""
    results = []

    for i, item in enumerate(stockouts_data):
        try:
            product_id = int(item.get('productId', item.get('product_id', item.get('case_id', 0))))
            quantity = int(item.get('quantity', 0))
            stockout_date = item.get('stockoutDate', item.get('stockout_date', datetime.now().strftime('%Y-%m-%d')))
            customer = item.get('customer', '')
            note = item.get('note', '')

            if not product_id or quantity <= 0:
                results.append({'success': False, 'error': '产品ID或数量无效', 'id': item.get('id', '未知')})
                continue

            from fastapi_app.services.batch_service import generate_case_stockout_number
            stockout_no = await generate_case_stockout_number(db)

            result = await create_case_stockout(db, product_id, quantity, stockout_date, customer, note, stockout_no)
            results.append({**result, 'id': item.get('id', '未知')})
        except Exception as e:
            results.append({'success': False, 'error': str(e), 'id': item.get('id', '未知')})

    return {'success': True, 'results': results}


async def create_case_product(db, name: str = None, barcode: str = None,
                               image: str = None, product_id: int = None) -> dict:
    """创建皮套产品"""
    if not name and not product_id:
        raise ValueError("皮套名称或关联产品不能为空")

    if product_id and not name:
        linked_product = await db.get(Product, product_id)
        if linked_product:
            name = linked_product.name
            if not barcode:
                barcode = linked_product.barcode

    case_obj = Case(name=name or '', barcode=barcode or '', image=image,
                    product_id=product_id if product_id else None)
    db.add(case_obj)
    await db.flush()
    return {'success': True, 'message': '添加成功', 'id': case_obj.id}
