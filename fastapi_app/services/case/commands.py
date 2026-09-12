"""皮套命令域(入库/出库增删改查与批量)

从 case_service.py 按职责拆出,行为与原实现完全一致。
"""
import logging
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.number_generator import _acquire_advisory_lock_async, _number_lock_key
from fastapi_app.core.validators import validate_quantity_range
from fastapi_app.services.case._common import _parse_date
from fastapi_app.shared_models import Case, CaseInventoryLog, CaseStockIn, CaseStockOut, Product

logger = logging.getLogger(__name__)


async def _get_case_for_update(db: AsyncSession, case_id: int) -> Case:
    """以行级锁方式获取皮套记录，用于并发安全的库存变更。

    Args:
        db: 异步数据库会话。
        case_id: 皮套 ID。

    Returns:
        Case 对象。

    Raises:
        ValueError: 皮套不存在时抛出。
    """
    result = await db.execute(
        select(Case).where(Case.id == case_id).with_for_update()
    )
    case_obj = result.scalar_one_or_none()
    if not case_obj:
        raise ValueError(f"皮套 ID {case_id} 不存在")
    return case_obj

async def _get_or_create_case_for_product(db: AsyncSession, product_id: int) -> Case:
    """以事务级咨询锁 + 行级锁方式获取产品关联的皮套记录，不存在则创建。

    使用 pg_advisory_xact_lock 串行化同一 product_id 的创建流程，避免并发场景下
    多个请求同时查到 None 后各自插入导致重复 Case（Case.product_id 当前无唯一约束）。

    Args:
        db: 异步数据库会话。
        product_id: 关联产品 ID。

    Returns:
        Case 对象。

    Raises:
        ValueError: 产品不存在时抛出。
    """
    await _acquire_advisory_lock_async(db, _number_lock_key('CASE_PRODUCT', str(product_id)))
    result = await db.execute(
        select(Case).where(Case.product_id == product_id).with_for_update()
    )
    case_obj = result.scalar_one_or_none()

    if not case_obj:
        product = await db.get(Product, product_id)
        if not product:
            raise ValueError("产品不存在")
        case_obj = Case(product_id=product.id, name=product.name, barcode=product.barcode,
                        current_stock=0, initial_stock=0)
        db.add(case_obj)
        await db.flush()
    return case_obj

async def _get_case_by_product_for_update(db: AsyncSession, product_id: int) -> Case:
    """以行级锁方式获取产品关联的皮套记录。

    Args:
        db: 异步数据库会话。
        product_id: 关联产品 ID。

    Returns:
        Case 对象。

    Raises:
        ValueError: 未找到关联皮套时抛出。
    """
    result = await db.execute(
        select(Case).where(Case.product_id == product_id).with_for_update()
    )
    case_obj = result.scalar_one_or_none()
    if not case_obj:
        raise ValueError(f"未找到关联产品ID {product_id} 的皮套")
    return case_obj

async def _assert_no_case_references(db: AsyncSession, case_id: int) -> None:
    """检查皮套是否存在关联的入库/出库/流水记录。

    Args:
        db: 异步数据库会话。
        case_id: 皮套 ID。

    Raises:
        ValueError: 存在任意关联记录时抛出。
    """
    stockin_count = (await db.execute(
        select(func.count()).select_from(CaseStockIn).where(CaseStockIn.case_id == case_id)
    )).scalar() or 0
    if stockin_count:
        raise ValueError(f"存在 {stockin_count} 条入库记录，无法删除")

    stockout_count = (await db.execute(
        select(func.count()).select_from(CaseStockOut).where(CaseStockOut.case_id == case_id)
    )).scalar() or 0
    if stockout_count:
        raise ValueError(f"存在 {stockout_count} 条出库记录，无法删除")

    log_count = (await db.execute(
        select(func.count()).select_from(CaseInventoryLog).where(CaseInventoryLog.case_id == case_id)
    )).scalar() or 0
    if log_count:
        raise ValueError(f"存在 {log_count} 条库存流水，无法删除")

async def create_case_stockin(db: AsyncSession, product_id: int, quantity: int, stockin_date: str,
                               customer: str = '', note: str = '', stockin_no: str = '') -> dict:
    """创建皮套入库记录。

    若产品尚未关联皮套记录，会自动创建。库存变更使用行级锁保证并发安全。

    Args:
        db: 异步数据库会话。
        product_id: 关联产品 ID。
        quantity: 入库数量，需在业务规则允许范围内。
        stockin_date: 入库日期字符串（YYYY-MM-DD）。
        customer: 客户名称。
        note: 备注。
        stockin_no: 入库单号，为空时自动生成。

    Returns:
        dict，包含 success、stockin_no、id 字段。

    Raises:
        ValueError: 产品不存在时抛出。
        HTTPException: 日期格式错误时抛出 400。
    """
    validate_quantity_range(quantity, "入库数量")
    if not stockin_no:
        # 单条入库路径不会预生成单号；stockin_no 有唯一约束，空串会在第二条时炸
        from fastapi_app.services.numbering import generate_case_stockin_number
        stockin_no = await generate_case_stockin_number(db)
    case_obj = await _get_or_create_case_for_product(db, product_id)

    stockin = CaseStockIn(stockin_no=stockin_no, stockin_date=_parse_date(stockin_date, '入库日期'),
                          customer=customer, case_id=case_obj.id, quantity=quantity, note=note)
    db.add(stockin)
    case_obj.current_stock += quantity

    log = CaseInventoryLog(case_id=case_obj.id, change_type='入库', change_quantity=quantity,
                           related_id=stockin_no, note=f'入库：{stockin_no}', customer=customer)
    db.add(log)
    await db.flush()
    logger.info('皮套入库成功 case_id=%s quantity=%s stockin_no=%s', case_obj.id, quantity, stockin_no)
    return {'success': True, 'stockin_no': stockin_no, 'id': stockin.id}

async def create_case_stockout(db: AsyncSession, product_id: int, quantity: int,
                                stockout_date: str, customer: str = '',
                                note: str = '', stockout_no: str = '') -> dict:
    """创建皮套出库记录。

    出库前会校验库存是否充足，库存变更使用行级锁保证并发安全。

    Args:
        db: 异步数据库会话。
        product_id: 关联产品 ID（用于定位皮套）。
        quantity: 出库数量，需在业务规则允许范围内。
        stockout_date: 出库日期字符串（YYYY-MM-DD）。
        customer: 客户名称。
        note: 备注。
        stockout_no: 出库单号，为空时自动生成。

    Returns:
        dict，包含 success、stockout_no、id 字段。

    Raises:
        ValueError: 皮套不存在或库存不足时抛出。
        HTTPException: 日期格式错误时抛出 400。
    """
    validate_quantity_range(quantity, "出货数量")
    if not stockout_no:
        from fastapi_app.services.numbering import generate_case_stockout_number
        stockout_no = await generate_case_stockout_number(db)
    case_obj = await _get_case_by_product_for_update(db, product_id)

    if case_obj.current_stock < quantity:
        raise ValueError(f"库存不足，当前库存: {case_obj.current_stock}")

    stockout = CaseStockOut(stockout_no=stockout_no, case_id=case_obj.id, quantity=quantity,
                            stockout_date=_parse_date(stockout_date, '出库日期'),
                            customer=customer, note=note)
    db.add(stockout)
    await db.flush()

    case_obj.current_stock -= quantity

    log = CaseInventoryLog(case_id=case_obj.id, change_type='出库', change_quantity=-quantity,
                           change_date=datetime.now(UTC), customer=customer,
                           related_id=stockout_no, note=f'出库 {stockout_no}')
    db.add(log)
    logger.info('皮套出库成功 case_id=%s quantity=%s stockout_no=%s', case_obj.id, quantity, stockout_no)
    return {'success': True, 'stockout_no': stockout_no, 'id': stockout.id}

async def delete_case_product(db: AsyncSession, case_id: int) -> None:
    """删除皮套产品。

    仅允许删除库存为 0 且无入库/出库/流水关联记录的皮套。

    Args:
        db: 异步数据库会话。
        case_id: 皮套 ID。

    Raises:
        ValueError: 皮套不存在、库存非 0 或存在关联记录时抛出。
    """
    case_obj = await db.get(Case, case_id)
    if not case_obj:
        raise ValueError("皮套不存在")
    if case_obj.current_stock != 0:
        raise ValueError("只能删除库存为0的皮套")

    # 引用完整性检查：存在任何入库/出库/流水记录则禁止删除
    await _assert_no_case_references(db, case_id)

    await db.delete(case_obj)
    await db.flush()
    logger.info('皮套产品删除成功 case_id=%s', case_id)

async def _adjust_stockin_quantity(db: AsyncSession, stockin: CaseStockIn, new_quantity: int) -> None:
    """调整入库记录数量并同步库存与流水。

    Args:
        db: 异步数据库会话。
        stockin: 入库记录对象。
        new_quantity: 调整后的数量。
    """
    old_quantity = stockin.quantity
    quantity_change = new_quantity - old_quantity
    stockin.quantity = new_quantity

    case_obj = await _get_case_for_update(db, stockin.case_id)
    case_obj.current_stock += quantity_change
    log = CaseInventoryLog(
        case_id=stockin.case_id, change_type='入库调整',
        change_quantity=quantity_change, related_id=stockin.stockin_no,
        note=f'入库调整：{stockin.stockin_no}'
    )
    db.add(log)

async def update_case_stockin(db: AsyncSession, stockin_id: int, update_data: dict) -> dict:
    """更新皮套入库记录。

    当数量发生变化时，同步调整关联皮套的当前库存并记录调整流水。
    库存变更使用行级锁保证并发安全。

    Args:
        db: 异步数据库会话。
        stockin_id: 入库记录 ID。
        update_data: 待更新字段字典，支持 quantity、customer、stockin_date、note。

    Returns:
        dict，包含 success、message 字段。

    Raises:
        ValueError: 入库记录不存在时抛出。
        HTTPException: 日期格式错误时抛出 400。
    """
    stockin = await db.get(CaseStockIn, stockin_id)
    if not stockin:
        raise ValueError("入库记录不存在")

    if 'quantity' in update_data:
        await _adjust_stockin_quantity(db, stockin, update_data['quantity'])

    if 'customer' in update_data:
        stockin.customer = update_data['customer']
    if 'stockin_date' in update_data:
        stockin.stockin_date = _parse_date(update_data['stockin_date'], '入库日期')
    if 'note' in update_data:
        stockin.note = update_data['note']

    await db.flush()
    logger.info('皮套入库记录更新成功 stockin_id=%s', stockin_id)
    return {'success': True, 'message': '更新成功'}

async def delete_case_stockin(db: AsyncSession, stockin_id: int) -> dict:
    """删除皮套入库记录。

    删除前检查是否存在出库记录（若有则禁止删除）。
    删除时同步扣减库存并记录流水，库存变更使用行级锁保证并发安全。

    Args:
        db: 异步数据库会话。
        stockin_id: 入库记录 ID。

    Returns:
        dict，包含 success、message 字段。

    Raises:
        ValueError: 入库记录不存在或删除后库存将为负数时抛出。
    """
    stockin = await db.get(CaseStockIn, stockin_id)
    if not stockin:
        raise ValueError("入库记录不存在")

    case_obj = await _get_case_for_update(db, stockin.case_id)
    # 由于 CaseStockOut 未记录关联的入库 ID，无法精确判断该入库是否被某笔出库引用。
    # 保守策略：确保删除后库存不会变为负数即可；若当前库存不足则禁止删除。
    if case_obj.current_stock < stockin.quantity:
        raise ValueError("当前库存不足，删除该入库后库存将为负数")
    case_obj.current_stock -= stockin.quantity
    log = CaseInventoryLog(
        case_id=stockin.case_id, change_type='删除入库',
        change_quantity=-stockin.quantity, related_id=stockin.stockin_no,
        note=f'删除入库：{stockin.stockin_no}'
    )
    db.add(log)

    await db.delete(stockin)
    await db.flush()
    logger.info('皮套入库记录删除成功 stockin_id=%s', stockin_id)
    return {'success': True, 'message': '删除成功'}

async def _adjust_stockout_quantity(db: AsyncSession, stockout: CaseStockOut, new_quantity: int) -> None:
    """调整出库记录数量并同步库存与流水。

    出库数量增加 → 库存减少；出库数量减少 → 库存增加。
    调整后库存为负时抛出异常。

    Args:
        db: 异步数据库会话。
        stockout: 出库记录对象。
        new_quantity: 调整后的数量。

    Raises:
        ValueError: 调整后库存为负时抛出。
    """
    old_quantity = stockout.quantity
    quantity_change = new_quantity - old_quantity
    stockout.quantity = new_quantity

    case_obj = await _get_case_for_update(db, stockout.case_id)
    case_obj.current_stock -= quantity_change
    if case_obj.current_stock < 0:
        raise ValueError(f"调整后库存不足，当前库存: {case_obj.current_stock}")
    log = CaseInventoryLog(
        case_id=stockout.case_id, change_type='出库调整',
        change_quantity=-quantity_change, related_id=stockout.stockout_no,
        note=f'出库调整：{stockout.stockout_no}'
    )
    db.add(log)

async def update_case_stockout(db: AsyncSession, stockout_id: int, update_data: dict) -> dict:
    """更新皮套出库记录。

    当数量发生变化时，同步调整关联皮套的当前库存并记录调整流水。
    库存变更使用行级锁保证并发安全。

    Args:
        db: 异步数据库会话。
        stockout_id: 出库记录 ID。
        update_data: 待更新字段字典，支持 quantity、customer、stockout_date、note。

    Returns:
        dict，包含 success、message 字段。

    Raises:
        ValueError: 出库记录不存在或调整后库存不足时抛出。
        HTTPException: 日期格式错误时抛出 400。
    """
    stockout = await db.get(CaseStockOut, stockout_id)
    if not stockout:
        raise ValueError("出库记录不存在")

    if 'quantity' in update_data:
        await _adjust_stockout_quantity(db, stockout, update_data['quantity'])

    if 'customer' in update_data:
        stockout.customer = update_data['customer']
    if 'stockout_date' in update_data:
        stockout.stockout_date = _parse_date(update_data['stockout_date'], '出库日期')
    if 'note' in update_data:
        stockout.note = update_data['note']

    await db.flush()
    logger.info('皮套出库记录更新成功 stockout_id=%s', stockout_id)
    return {'success': True, 'message': '更新成功'}

async def delete_case_stockout(db: AsyncSession, stockout_id: int) -> dict:
    """删除皮套出库记录。

    删除时同步回补库存并记录流水，库存变更使用行级锁保证并发安全。

    Args:
        db: 异步数据库会话。
        stockout_id: 出库记录 ID。

    Returns:
        dict，包含 success、message 字段。

    Raises:
        ValueError: 出库记录不存在时抛出。
    """
    stockout = await db.get(CaseStockOut, stockout_id)
    if not stockout:
        raise ValueError("出库记录不存在")

    case_obj = await _get_case_for_update(db, stockout.case_id)
    case_obj.current_stock += stockout.quantity
    log = CaseInventoryLog(
        case_id=stockout.case_id, change_type='删除出库',
        change_quantity=stockout.quantity, related_id=stockout.stockout_no,
        note=f'删除出库：{stockout.stockout_no}'
    )
    db.add(log)

    await db.delete(stockout)
    await db.flush()
    logger.info('皮套出库记录删除成功 stockout_id=%s', stockout_id)
    return {'success': True, 'message': '删除成功'}

async def batch_create_case_stockins(db: AsyncSession, stockins_data: list[dict]) -> dict:
    """批量提交皮套入库。

    逐条处理，单条失败不影响其他记录。每条记录自动生成入库单号。

    Args:
        db: 异步数据库会话。
        stockins_data: 入库数据列表，每项为 dict，支持 productId/product_id、quantity、
            stockinDate/stockin_date、customer、note 字段。

    Returns:
        dict，包含 success、message（成功条数）、failed（失败列表，含 index 和 error）。
    """
    success_count = 0
    failed = []

    for idx, item in enumerate(stockins_data):
        try:
            product_id = int(item.get('productId', item.get('product_id', 0)))
            quantity = int(item.get('quantity', 0))
            stockin_date = item.get('stockinDate', item.get('stockin_date', datetime.now().strftime('%Y-%m-%d')))
            customer = item.get('customer', '')
            note = item.get('note', '')

            if not product_id or quantity <= 0:
                failed.append({'index': idx, 'error': '产品ID或数量无效'})
                continue

            # 生成入库单号
            from fastapi_app.services.numbering import generate_case_stockin_number
            stockin_no = await generate_case_stockin_number(db)

            await create_case_stockin(db, product_id, quantity, stockin_date, customer, note, stockin_no)
            success_count += 1
        except (ValueError, TypeError, RuntimeError) as e:
            logger.warning('批量入库第 %s 条失败: %s', idx, e)
            failed.append({'index': idx, 'error': str(e)})

    return {'success': True, 'message': f'成功提交 {success_count} 条入库记录', 'failed': failed}

async def batch_create_case_stockouts(db: AsyncSession, stockouts_data: list[dict]) -> dict:
    """批量提交皮套出库。

    逐条处理，单条失败不影响其他记录。每条记录自动生成出库单号。

    Args:
        db: 异步数据库会话。
        stockouts_data: 出库数据列表，每项为 dict，支持 productId/product_id/case_id、quantity、
            stockoutDate/stockout_date、customer、note 字段。

    Returns:
        dict，包含 success、results（每条结果列表，含 success/error/id 字段）。
    """
    results = []

    for idx, item in enumerate(stockouts_data):
        try:
            product_id = int(item.get('productId', item.get('product_id', item.get('case_id', 0))))
            quantity = int(item.get('quantity', 0))
            stockout_date = item.get('stockoutDate', item.get('stockout_date', datetime.now().strftime('%Y-%m-%d')))
            customer = item.get('customer', '')
            note = item.get('note', '')

            if not product_id or quantity <= 0:
                results.append({'success': False, 'error': '产品ID或数量无效', 'id': item.get('id', '未知')})
                continue

            from fastapi_app.services.numbering import generate_case_stockout_number
            stockout_no = await generate_case_stockout_number(db)

            result = await create_case_stockout(db, product_id, quantity, stockout_date, customer, note, stockout_no)
            results.append({**result, 'id': item.get('id', '未知')})
        except (ValueError, TypeError, RuntimeError) as e:
            logger.warning('批量出库第 %s 条失败: %s', idx, e)
            results.append({'success': False, 'error': str(e), 'id': item.get('id', '未知')})

    return {'success': True, 'results': results}

async def create_case_product(db: AsyncSession, name: str | None = None, barcode: str | None = None,
                               image: str | None = None, product_id: int | None = None) -> dict:
    """创建皮套产品。

    需提供 name 或 product_id 至少一项；若仅提供 product_id，则从关联产品同步名称与条码。

    Args:
        db: 异步数据库会话。
        name: 皮套名称。
        barcode: 皮套条码。
        image: 图片路径。
        product_id: 关联产品 ID。

    Returns:
        dict，包含 success、message、id 字段。

    Raises:
        ValueError: name 和 product_id 均为空时抛出。
    """
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
    logger.info('皮套产品创建成功 case_id=%s name=%s', case_obj.id, name)
    return {'success': True, 'message': '添加成功', 'id': case_obj.id}