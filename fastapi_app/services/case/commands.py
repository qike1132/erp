"""皮套命令域（SKU 主档增删改 / 出入库流水增删改 / 批量提交）

统一写入口：所有库存变更都在同一把行级锁内改 `Case.current_stock` 并追加
`CaseMovement` 流水，保证"单一真值来源"。
"""
import logging
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.exceptions import BusinessError
from fastapi_app.core.pg_locks import acquire_advisory_lock_async, number_lock_key
from fastapi_app.core.validators import validate_quantity_range
from fastapi_app.services.case._common import _parse_date
from fastapi_app.services.case._serializers import _serialize_item
from fastapi_app.services.numbering import generate_case_movement_number
from fastapi_app.shared.stock_concurrency import assert_stock_available
from fastapi_app.shared_models import DIRECTION_IN, DIRECTION_OUT, Case, CaseMovement, Product

logger = logging.getLogger(__name__)


async def _get_case_for_update(db: AsyncSession, case_id: int) -> Case:
    """以行级锁获取皮套 SKU（用于并发安全的库存变更）。"""
    result = await db.execute(select(Case).where(Case.id == case_id).with_for_update())
    case_obj = result.scalar_one_or_none()
    if not case_obj:
        raise ValueError(f"皮套 ID {case_id} 不存在")
    return case_obj


def _direction_delta(direction: str, quantity: int) -> int:
    """方向 + 数量 → 对 current_stock 的增减量。"""
    if direction == DIRECTION_IN:
        return quantity
    if direction == DIRECTION_OUT:
        return -quantity
    raise ValueError("方向必须是 in 或 out")


async def create_movement(db: AsyncSession, case_id: int, direction: str, quantity: int,
                          movement_date: str = '', customer: str = '', note: str = '') -> dict:
    """创建一条出入库流水并同步库存（行级锁内）。

    入库增加库存、出库扣减并在不足时拒绝。
    """
    validate_quantity_range(quantity, "入库数量" if direction == DIRECTION_IN else "出库数量")
    delta = _direction_delta(direction, quantity)  # 非法方向在此抛错

    movement_no = await generate_case_movement_number(db, direction)
    case_obj = await _get_case_for_update(db, case_id)
    assert_stock_available(
        case_obj.current_stock, delta,
        message=f"库存不足，当前库存: {case_obj.current_stock}",
    )
    case_obj.current_stock += delta
    case_obj.version += 1

    when = _parse_date(movement_date, "日期") if movement_date else datetime.now(UTC)
    movement = CaseMovement(
        case_id=case_obj.id, direction=direction, movement_no=movement_no,
        quantity=quantity, customer=customer or None, movement_date=when, note=note,
    )
    db.add(movement)
    await db.flush()
    logger.info('皮套%s成功 case_id=%s quantity=%s movement_no=%s',
                '入库' if direction == DIRECTION_IN else '出库', case_obj.id, quantity, movement_no)
    return {'success': True, 'movement_no': movement_no, 'id': movement.id}


async def update_movement(db: AsyncSession, movement_id: int, update_data: dict) -> dict:
    """更新出入库流水；数量变化时在同一把锁内同步库存。"""
    # 必须**先**锁流水行再读它的 quantity：否则并发编辑同一条流水时，两个事务都用
    # 陈旧快照算增量、先后施加到同一个 current_stock 上 → 台账与库存漂移。
    # 锁序为「流水 → case」；create_movement 只锁 case、不锁流水，故不成环。
    movement = (await db.execute(
        select(CaseMovement).where(CaseMovement.id == movement_id).with_for_update()
    )).scalar_one_or_none()
    if not movement:
        raise ValueError("流水记录不存在")

    if 'quantity' in update_data:
        new_quantity = update_data['quantity']
        validate_quantity_range(new_quantity, "数量")
        change = new_quantity - movement.quantity
        delta = change if movement.direction == DIRECTION_IN else -change
        case_obj = await _get_case_for_update(db, movement.case_id)
        assert_stock_available(
            case_obj.current_stock, delta,
            message=f"调整后库存不足，当前库存: {case_obj.current_stock + delta}",
        )
        case_obj.current_stock += delta
        case_obj.version += 1
        movement.quantity = new_quantity

    if 'movement_date' in update_data:
        movement.movement_date = _parse_date(update_data['movement_date'], "日期")
    if 'customer' in update_data:
        movement.customer = update_data['customer']
    if 'note' in update_data:
        movement.note = update_data['note']

    await db.flush()
    logger.info('皮套流水更新成功 movement_id=%s', movement_id)
    return {'success': True, 'message': '更新成功'}


async def delete_movement(db: AsyncSession, movement_id: int) -> dict:
    """删除出入库流水，并回退其对库存的影响（行级锁内）。"""
    # 同 update_movement：先锁流水行，避免并发删除/编辑时用陈旧快照**双倍回退**库存。
    movement = (await db.execute(
        select(CaseMovement).where(CaseMovement.id == movement_id).with_for_update()
    )).scalar_one_or_none()
    if not movement:
        raise ValueError("流水记录不存在")

    delta = -movement.quantity if movement.direction == DIRECTION_IN else movement.quantity
    case_obj = await _get_case_for_update(db, movement.case_id)
    assert_stock_available(
        case_obj.current_stock, delta,
        message="删除该记录后库存不足，无法删除",
    )
    case_obj.current_stock += delta
    case_obj.version += 1

    await db.delete(movement)
    await db.flush()
    logger.info('皮套流水删除成功 movement_id=%s', movement_id)
    return {'success': True, 'message': '删除成功'}


async def batch_create_movements(db: AsyncSession, movements_data: list[dict]) -> dict:
    """批量提交出入库（暂存单）。

    逐条用 savepoint 隔离，单条失败不影响其它记录。
    """
    results: list[dict] = []
    failed: list[dict] = []

    for idx, item in enumerate(movements_data):
        try:
            case_id = int(item.get('case_id', item.get('caseId', item.get('product_id', 0))))
            direction = item.get('direction', '')
            quantity = int(item.get('quantity', 0))
            movement_date = item.get('movement_date', item.get('movementDate', ''))
            customer = item.get('customer', '')
            note = item.get('note', '')

            if not case_id or quantity <= 0 or direction not in (DIRECTION_IN, DIRECTION_OUT):
                failed.append({'index': idx, 'error': '皮套ID、方向或数量无效'})
                continue

            async with db.begin_nested():
                result = await create_movement(db, case_id, direction, quantity, movement_date, customer, note)
            results.append({'index': idx, **result, 'client_id': item.get('id', '')})
        except (ValueError, TypeError, RuntimeError, BusinessError) as e:
            logger.warning('批量出入库第 %s 条失败: %s', idx, e)
            failed.append({'index': idx, 'error': str(e)})

    return {'success': True, 'results': results, 'failed': failed}


async def _ensure_parent_is_root(db: AsyncSession, parent_id: int) -> None:
    """校验 `parent_id` 指向一个**主件**（根件，即 parent_id IS NULL）。

    统一不变量：**配件只能挂在主件下**（层级 ≤ 1）。这一条同时排掉了
    「配件挂配件」造成的多级与环 —— 环（A.parent=B、B.parent=A）会让两者都从
    `get_case_inventory` 的库存树里消失（它只展开根件的一层子女）。
    FK 只保证父件**存在**，不保证它是根件。
    """
    parent = await db.get(Case, parent_id)
    if not parent:
        raise ValueError("所属主件不存在")
    if parent.parent_id is not None:
        raise ValueError("所属主件本身是配件；配件只能挂在主件下")


async def create_case_item(db: AsyncSession, name: str | None = None, barcode: str | None = None,
                           image: str | None = None, unit: str | None = None,
                           product_id: int | None = None, parent_id: int | None = None,
                           qty_per_set: int = 1, initial_stock: int = 0) -> dict:
    """创建皮套 SKU（主件或配件）。需 name 或 product_id 至少一项。"""
    if not name and not product_id:
        raise ValueError("皮套名称或关联产品不能为空")

    if product_id and not name:
        linked = await db.get(Product, product_id)
        if linked:
            name = linked.name
            if not barcode:
                barcode = linked.barcode

    if parent_id is not None:
        await _ensure_parent_is_root(db, parent_id)

    case_obj = Case(
        name=name or '', barcode=barcode or '', image=image, unit=unit,
        product_id=product_id or None, parent_id=parent_id or None,
        qty_per_set=qty_per_set or 1, initial_stock=initial_stock, current_stock=initial_stock,
    )
    db.add(case_obj)
    await db.flush()
    logger.info('皮套 SKU 创建成功 case_id=%s name=%s parent_id=%s', case_obj.id, name, parent_id)
    return {'success': True, 'message': '添加成功', 'id': case_obj.id}


async def get_or_create_case_tree_for_product(db: AsyncSession, product_id: int) -> dict:
    """取（不存在则以产品信息创建）该产品的「皮套主件」，返回 {main, parts}。

    用 advisory lock 串行化同一 product 的创建，避免并发重复建主件
    （`case.product_id` 无唯一约束）。parts 为主件下挂的配件（parent_id = 主件）。
    """
    await acquire_advisory_lock_async(db, number_lock_key('CASE_PRODUCT', str(product_id)))
    case_obj = (await db.execute(
        select(Case).where(Case.product_id == product_id).with_for_update()
    )).scalar_one_or_none()
    if not case_obj:
        product = await db.get(Product, product_id)
        if not product:
            raise ValueError('产品不存在')
        case_obj = Case(
            product_id=product.id, name=product.name, barcode=product.barcode,
            current_stock=0, initial_stock=0,
        )
        db.add(case_obj)
        await db.flush()
        logger.info('皮套主件自动创建 case_id=%s product_id=%s', case_obj.id, product_id)
    parts = list((await db.execute(
        select(Case).where(Case.parent_id == case_obj.id).order_by(Case.id)
    )).scalars().all())
    return {'main': _serialize_item(case_obj), 'parts': [_serialize_item(p) for p in parts]}


async def update_case_item(db: AsyncSession, case_id: int, update_data: dict) -> dict:
    """更新皮套 SKU 的静态字段（名称/条码/图片/单位/所属主件/配比）。"""
    case_obj = await db.get(Case, case_id)
    if not case_obj:
        raise ValueError("皮套不存在")

    if 'parent_id' in update_data:
        parent_id = update_data['parent_id']
        if parent_id == case_id:
            raise ValueError("不能把自己设为主件")
        if parent_id is not None:
            await _ensure_parent_is_root(db, parent_id)
        case_obj.parent_id = parent_id

    for field in ('name', 'barcode', 'image', 'unit', 'qty_per_set'):
        if field in update_data and update_data[field] is not None:
            setattr(case_obj, field, update_data[field])

    await db.flush()
    logger.info('皮套 SKU 更新成功 case_id=%s', case_id)
    return {'success': True, 'message': '更新成功'}


async def delete_case_item(db: AsyncSession, case_id: int) -> None:
    """删除皮套 SKU。存在流水或下挂配件时禁止删除。"""
    case_obj = await db.get(Case, case_id)
    if not case_obj:
        raise ValueError("皮套不存在")

    movement_count = (await db.execute(
        select(func.count()).select_from(CaseMovement).where(CaseMovement.case_id == case_id)
    )).scalar() or 0
    if movement_count:
        raise ValueError(f"存在 {movement_count} 条出入库记录，无法删除")

    child_count = (await db.execute(
        select(func.count()).select_from(Case).where(Case.parent_id == case_id)
    )).scalar() or 0
    if child_count:
        raise ValueError(f"存在 {child_count} 个配件，无法删除")

    await db.delete(case_obj)
    await db.flush()
    logger.info('皮套 SKU 删除成功 case_id=%s', case_id)
