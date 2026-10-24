"""暂存出货实体业务

从 staging_service.py 按实体拆出,行为与原实现完全一致。
"""
import logging
from datetime import UTC, datetime
from typing import cast

from sqlalchemy import delete, select
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.cache_invalidation import cache_mgr, schedule_post_commit_invalidation
from fastapi_app.core.exceptions import NotFoundError
from fastapi_app.core.state_machine import StagingAction, StagingStatus, staging_machine
from fastapi_app.services.batch_import_core import _import_idem_key, _row_failure_message
from fastapi_app.services.batch_service import calculate_available_shipment_quantity
from fastapi_app.services.numbering import generate_stockout_number
from fastapi_app.services.staging._generic import (
    _generic_import_staging_from_excel,
    _generic_update_staging_entity,
)
from fastapi_app.services.staging.stockin import _validate_stockin_customer
from fastapi_app.shared.stock_concurrency import check_stock_available
from fastapi_app.shared_models import InventoryLog, Order, Product, StagingStockOut, StockOut
from fastapi_app.shared_models.order import ORDER_STATUS_SHIPPED
from fastapi_app.utils import inventory_balance_bounds, parse_date_value

logger = logging.getLogger(__name__)


def _build_stockout_entity(
    fields: dict, session_id: str, product_id: int | None, qty: int,
    is_validated: bool, validation_error: str, product_name: str,
    product=None,
) -> StagingStockOut:
    stockout_date = parse_date_value(fields.get('stockout_date')) or datetime.now(UTC)  # aware UTC：staging_stock_out.stockout_date 列为 timestamptz
    customer = str(fields.get('customer', '')).strip()

    # 2026-10-17 审计 AUD-04：预检必须真查库存。此前 Excel 导入只要产品匹配就
    # 硬编码「库存充足」，用户在确认弹窗里基于假信号拍板；与 OCR 路径
    # （services/ocr/_import.py）的真实 check_stock_available 口径分裂。
    stock_check_passed = False
    stock_check_message = ''
    if is_validated:
        if qty <= 0:
            # 2026-10-18 OCR 评审：0/负数行不得被判「库存充足」（确认环节会拒绝）
            stock_check_message = f'数量无效: {qty}'
        elif product is None:
            stock_check_message = '未能读取当前库存，请在确认前核对'
        else:
            reason = check_stock_available(product.current_stock, -qty)
            stock_check_passed = reason is None
            # B1-04：current_stock 是备货口径（含备货/半成品），与确认环节的结余
            # 闸门口径不同——此处只是同步路径下的参考信号，导入完成后
            # _recalc_stock_check_by_balance 会按结余口径重算（文案含"结余"）。
            stock_check_message = (
                '库存充足（备货口径预检，确认按结余）' if reason is None else reason
            )

    return StagingStockOut(
        session_id=session_id,
        customer=customer,
        stockout_date=stockout_date,
        product_name=product_name,
        product_barcode='',
        product_id=product_id,
        quantity=qty,
        note=str(fields.get('note', '') or '').strip(),
        is_validated=is_validated,
        validation_error=validation_error,
        stock_check_passed=stock_check_passed,
        stock_check_message=stock_check_message,
        status=StagingStatus.PENDING,
    )

async def _stockout_extra_updates(entity, data: dict, db: AsyncSession) -> None:
    # 2026-10-18 OCR 评审：改产品名（generic 层会重解析 product_id）或改数量，
    # 都必须重算预检；此前只看 quantity，换产品后仍沿用旧产品的结论。
    if 'product_name' in data and entity.product_id is None:
        # 新名称匹配不到任何产品：_generic_update_staging_entity 已把 product_id 置 None、
        # is_validated 置 False。此时下面按 product_id 非空的重算分支不会执行，旧的
        # stock_check_passed/message 会残留（前端确认弹窗据此放行），且
        # confirm_staging_stockouts 的筛选条件含 stock_check_passed IS TRUE，
        # 残留 True 会让这行进入确认流程再被 _confirm_one_staging_stockout 拒。
        # 必须显式作废预检：置 False 并清空文案，与导入路径「产品未匹配」的口径一致。
        entity.stock_check_passed = False
        entity.stock_check_message = ''
    elif entity.product_id and ('quantity' in data or 'product_name' in data):
        # 2026-10-17 审计 AUD-04：编辑数量后必须重算库存预检（此前是空实现，
        # 数量改大后暂存行仍显示导入时的旧结论）。
        product = await db.get(Product, entity.product_id)
        if product is not None:
            # B1-04：编辑路径有 db，直接按结余口径重算（与确认闸门同源），不再
            # 沿用备货口径的 current_stock 快查。
            from fastapi_app.services.stock_inventory_service import get_inventory_balance

            balance = await get_inventory_balance(db, entity.product_id)
            qty = int(entity.quantity)
            entity.stock_check_passed = qty <= balance
            entity.stock_check_message = (
                '结余充足（按包装部入库−已出货）' if qty <= balance
                else f'库存不足（结余 {balance}，本次 {qty}）'
            )
    if 'stockout_date' in data:
        entity.stockout_date = parse_date_value(data['stockout_date']) or datetime.now(UTC)  # aware UTC：列已迁移为 timestamptz
    if 'note' in data:
        entity.note = data['note']

async def get_staging_stockouts(db: AsyncSession, session_id: str) -> list[dict]:
    result = await db.execute(
        select(StagingStockOut)
        .where(StagingStockOut.session_id == session_id, StagingStockOut.status == StagingStatus.PENDING)
        .order_by(StagingStockOut.created_at.desc())
    )
    stockouts = result.scalars().all()
    return [stockout.to_dict() for stockout in stockouts]

async def clear_staging_stockouts_by_session(db: AsyncSession, session_id: str) -> int:
    result = await db.execute(
        delete(StagingStockOut).where(StagingStockOut.session_id == session_id)
    )
    await db.flush()
    # Core DML 运行时返回 CursorResult；SQLAlchemy 的 execute() 只声明基类 Result
    return cast(CursorResult, result).rowcount

async def clear_staging_stockouts(db: AsyncSession, session_id: str):
    await clear_staging_stockouts_by_session(db, session_id)

async def delete_staging_stockout(db: AsyncSession, stockout_id: int, session_scope: str | None = None):
    conditions = [StagingStockOut.id == stockout_id]
    if session_scope:
        conditions.append(StagingStockOut.session_id.like(f'{session_scope}%'))
    result = await db.execute(select(StagingStockOut).where(*conditions))
    stockout = result.scalar_one_or_none()
    if not stockout:
        raise NotFoundError(f"暂存出货 {stockout_id} 不存在")
    await db.delete(stockout)
    await db.flush()

async def update_staging_stockout(db: AsyncSession, stockout_id: int, data: dict,
                                  session_scope: str | None = None) -> dict:
    return await _generic_update_staging_entity(
        db, stockout_id, data, StagingStockOut, '暂存出货',
        extra_updates=_stockout_extra_updates,
        session_scope=session_scope,
    )

class _NegativeQuantityError(Exception):
    """单行数量无效——穿越 savepoint 回滚后由外层统一置 REJECTED（保持原 continue 语义）。"""


async def _allocate_ship_fifo(db: AsyncSession, staging, product_id,
                              shipment_info: dict) -> tuple[set[int], list[StockOut]]:
    """按订单 FIFO 分摊出库数量，生成 StockOut 行。

    返回 (受影响订单 id 集, 新建的 StockOut 列表)。列表用于回填库存流水的
    related_id（P2，2026-10-24：原先 related_id 恒为空，出货行↔流水的唯一关联断掉）。
    """
    affected_order_ids: set[int] = set()
    created: list[StockOut] = []
    remaining_qty = staging.quantity
    for order_detail in shipment_info['orders']:
        if remaining_qty <= 0:
            break
        if order_detail['available'] > 0:
            ship_qty = min(remaining_qty, order_detail['available'])
            stockout_no = await generate_stockout_number(db)
            stockout = StockOut(
                stockout_no=stockout_no,
                stockout_date=staging.stockout_date or datetime.now(UTC),  # aware UTC：stock_out.stockout_date 列为 timestamptz
                product_id=staging.product_id,
                quantity=ship_qty,
                customer=staging.customer,
                order_id=order_detail['order_id'],
                note=staging.note,
            )
            db.add(stockout)
            created.append(stockout)
            affected_order_ids.add(order_detail['order_id'])
            remaining_qty -= ship_qty
    return affected_order_ids, created


async def _confirm_one_staging_stockout(db: AsyncSession, staging,
                                        completed_orders: list[dict]) -> None:
    """确认单条暂存出货（在 savepoint 内运行，异常由调用方捕获）。

    校验链：数量为正 → 客户必填 → 产品存在 → 库存充足 → 订单可出 → 按订单分摊出库。
    """
    from fastapi_app.services.order_utils import compute_order_status_from_db
    from fastapi_app.shared.stock_concurrency import (
        apply_stock_delta_locked,
        assert_stock_available,
        get_product_for_update,
    )

    # 数量必须为正。缺这道校验时负数量会被一路放行：
    #   `assert_stock_available(stock, -quantity)` 传的是 -(-N)=+N，恒通过；
    #   FIFO 循环 `if remaining_qty <= 0: break` 立即跳出 → 不生成任何 StockOut；
    #   末尾 `current_stock -= quantity` 变成 `-= 负数` → **库存被加**，
    #   还写一条 change_type='出库'、change_quantity=正数的假日志。
    # 同族的 staging/stockin.py 与 staging/order.py 都有这道闸门，出货路径此前漏了。
    if staging.quantity <= 0:
        raise _NegativeQuantityError(f'出货{staging.customer}-{staging.product_name}数量无效: {staging.quantity}')

    if not staging.customer:
        raise ValueError(f'出货{staging.product_name}确认失败: 必须选择客户，需要有订单支持')

    product_id = staging.product_id
    if product_id is None:
        # 暂存行允许未匹配产品（product_id 可空）；与原先 get_product_for_update(db, None) 查不到时的报错逐字一致
        raise ValueError(f'出货{staging.customer}-{staging.product_name}确认失败: 产品不存在')
    product = await get_product_for_update(db, product_id)
    if not product:
        raise ValueError(f'出货{staging.customer}-{staging.product_name}确认失败: 产品不存在')

    # 负库存判定统一走统一入口（P1-2b），文案与改动前逐字一致
    assert_stock_available(
        product.current_stock, -staging.quantity,
        message=f'出货{staging.customer}-{staging.product_name}确认失败: 库存不足',
    )
    # 结余闸门（口径见 stock_inventory_service.get_inventory_balance 的 docstring）：
    # 与手工出货/批量出货同口径 —— 可出库存 = 包装部入库 − 已出货。
    # 放在 _allocate_ship_fifo 之前：否则会先建出 StockOut 行再被拒，留下半成品数据。
    # 没有它时，导入路径只看 current_stock（含备货/半成品），
    # 会出现「手工出货被拒、同一张表导入却成功」。
    from fastapi_app.services.stock_inventory_service import get_inventory_balance

    _balance = await get_inventory_balance(db, product_id)
    if staging.quantity > _balance:
        raise ValueError(
            f'出货{staging.customer}-{staging.product_name}确认失败: '
            f'库存不足（可用 {_balance}，本次 {staging.quantity}）'
        )

    shipment_info = await calculate_available_shipment_quantity(
        db, product_id, staging.customer
    )
    if shipment_info['available_quantity'] <= 0:
        raise ValueError(f'出货{staging.customer}-{staging.product_name}确认失败: 没有可用的订单支持出货')

    if staging.quantity > shipment_info['available_quantity']:
        raise ValueError(
            f'出货{staging.customer}-{staging.product_name}确认失败: '
            f'出货数量{staging.quantity}超过可出货量{shipment_info["available_quantity"]}'
        )

    affected_order_ids, created_stockouts = await _allocate_ship_fifo(db, staging, product_id, shipment_info)

    # 统一写入口：带 version 守卫并递增 version（原先直写两者都不做，
    # 与走乐观锁的写入口并发时会丢失更新）。
    updated_product = await apply_stock_delta_locked(db, product, -staging.quantity)

    # 批量查询受影响的订单，避免N+1
    if affected_order_ids:
        order_result = await db.execute(  # batch-loop: 有意逐行处理,非 N+1
            select(Order).where(Order.id.in_(affected_order_ids))
        )
        order_map = {o.id: o for o in order_result.scalars().all()}
    else:
        order_map = {}

    for oid in affected_order_ids:
        order = order_map.get(oid)
        if order:
            old_status = order.status
            order.status = await compute_order_status_from_db(db, order)
            if order.status == ORDER_STATUS_SHIPPED and old_status != ORDER_STATUS_SHIPPED:
                completed_orders.append({
                    'order_id': order.id,
                    'order_no': order.order_no,
                    'customer': order.customer,
                })

    # P2（2026-10-24）：流水补齐 quantity_before/after 与 related_id。
    # 原先手写 InventoryLog 时三列全空，/stock 流水与 inventory_reconcile 的
    # 「结存 vs 流水」追溯在这批行上只剩变动量，且 related_id='' 断开了出货行↔流水关联。
    # 必须先 flush 拿到新建 StockOut 的 id（同 stock_out_service 的 ','.join 口径）。
    await db.flush()
    before, after = inventory_balance_bounds(updated_product.current_stock, -staging.quantity)
    log = InventoryLog(
        product_id=staging.product_id,
        change_type='出库',
        change_quantity=-staging.quantity,
        related_id=','.join(str(s.id) for s in created_stockouts),
        idem_key=_import_idem_key(
            'stockout', staging.customer, product_id, staging.quantity,
            staging.stockout_date or datetime.now(UTC),
        ),
        customer=staging.customer,
        quantity_before=before,
        quantity_after=after,
        product_name=updated_product.name,
        note=f'批量导入出货：客户{staging.customer}，数量{staging.quantity}',
    )
    db.add(log)


async def confirm_staging_stockouts(
    db: AsyncSession, session_id: str
) -> tuple[int, list[str]]:
    """批量确认暂存出货（2026-10-11 复核 P2-14⑥ 拆分：单行确认见 _confirm_one_staging_stockout）。"""
    result = await db.execute(
        select(StagingStockOut).where(
            StagingStockOut.session_id == session_id,
            StagingStockOut.status == StagingStatus.PENDING,
            # 可空布尔列在 WHERE 里取真值（与裸列写法同义：SQL 三值逻辑下 NULL 同样不入选），仓库既有写法
            StagingStockOut.is_validated.is_(True),
            StagingStockOut.stock_check_passed.is_(True),
        )
    )
    staging_stockouts = result.scalars().all()

    if not staging_stockouts:
        return 0, ["没有可确认的出货（请确保所有出货库存检查通过）"]

    confirmed = 0
    errors: list[str] = []
    completed_orders: list[dict] = []

    for staging in staging_stockouts:
        try:
            async with db.begin_nested():
                await _confirm_one_staging_stockout(db, staging, completed_orders)
                staging.status = staging_machine.transition(staging.status, StagingAction.APPROVE)
                confirmed += 1
        except _NegativeQuantityError as e:
            # 数量无效：异常已使 savepoint 回滚，此处在外层事务重置 REJECTED，
            # 错误格式与改动前逐字一致（无「确认失败」字样）
            errors.append(str(e))
            staging.status = staging_machine.transition(staging.status, StagingAction.REJECT)
        except (ValueError, TypeError, OSError, SQLAlchemyError) as e:
            errors.append(f'出货{staging.customer}-{staging.product_name}确认失败: {_row_failure_message(e)}')
            staging.status = staging_machine.transition(staging.status, StagingAction.REJECT)

    await db.execute(
        delete(StagingStockOut).where(
            StagingStockOut.session_id == session_id,
            StagingStockOut.status == StagingStatus.REJECTED,
        )
    )
    await db.flush()

    # 发送出货完成事件
    if completed_orders:
        from fastapi_app.services.notification_service import StockEvent, publish_event
        for co in completed_orders:
            try:
                await publish_event(StockEvent.SHIPMENT_COMPLETED, co)
            except Exception as e:  # defensive: 单个事件发布失败不影响确认结果
                logger.warning("出货完成事件发布失败: %s", e)

    if confirmed > 0:
        # 本路径写的是**真实** stock_out + inventory_log + product.current_stock ——
        # 全是 /stock 缓存（inventory:paginated，ttl=120s）的输入表。不失效则确认后
        # 页面最长 120s 仍显示旧数（2026-10-13 评审发现的漏点；同族写路径
        # stock_out_service.py 等处都有这两行）。
        await cache_mgr.invalidate_stock_and_order()
        schedule_post_commit_invalidation(db, cache_mgr.invalidate_stock_and_order)

    return confirmed, errors

async def import_staging_stockouts_from_excel(
    db: AsyncSession, file_content: bytes, session_id: str
) -> tuple[int, str, list[str]]:
    imported, msg, errors = await _generic_import_staging_from_excel(
        db, file_content, session_id,
        staging_model=StagingStockOut,
        clear_func=clear_staging_stockouts_by_session,
        sheet_keyword='出货管理',
        entity_label='出货',
        build_entity=_build_stockout_entity,
        column_names={
            'customer': '客户名称',
            'product_name': '产品名称',
            'quantity': '出货数量',
            'stockout_date': '时间',
            'note': '备注',
        },
        required_fields=['product_name', 'quantity'],
        extra_row_validations=_validate_stockin_customer,
    )
    # B1-04（2026-10-24 审计）：导入后的预检统一按「结余」口径重算——builder 里
    # 的 current_stock 快查是同步路径下的参考信号（备货口径恒 ≥ 结余），不重算会让
    # 确认弹窗绿灯、确认时却被结余闸门拒绝，且被拒行随即批删（暂存数据丢失）。
    await _recalc_stock_check_by_balance(db, session_id)
    return imported, msg, errors


async def _recalc_stock_check_by_balance(db: AsyncSession, session_id: str) -> None:
    """对暂存出货行按「结余」（包装部入库 − 已出货）口径重算 stock_check。

    与 confirm 环节的 _confirm_one_staging_stockout 闸门（get_inventory_balance）
    同口径；失败行的文案与确认拒绝文案一致，用户在弹窗里看到的即最终判定。
    """
    from fastapi_app.services.stock_inventory_service import get_inventory_balance

    result = await db.execute(
        select(StagingStockOut).where(
            StagingStockOut.session_id == session_id,
            StagingStockOut.is_validated.is_(True),
            StagingStockOut.product_id.isnot(None),
        )
    )
    for row in result.scalars().all():
        qty = int(row.quantity)
        if qty <= 0 or row.product_id is None:
            continue
        balance = await get_inventory_balance(db, row.product_id)
        if qty > balance:
            row.stock_check_passed = False
            row.stock_check_message = f'库存不足（结余 {balance}，本次 {qty}）'
        else:
            row.stock_check_passed = True
            row.stock_check_message = '结余充足（按包装部入库−已出货）'

async def import_staging_stockouts_from_file(
    db: AsyncSession, file_content: bytes, session_id: str,
    filename: str = '', task_id: str = '',
) -> tuple[int, str, list[str]]:
    """从 OCR 文件（PDF/图片）导入出货到暂存区 — 委托给 OCR service"""
    from fastapi_app.services.ocr_service import import_staging_stockouts_from_file as _ocr_import
    return await _ocr_import(db, file_content, session_id, filename=filename, task_id=task_id)
