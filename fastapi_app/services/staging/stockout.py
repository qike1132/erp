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
from fastapi_app.shared_models import InventoryLog, Order, StagingStockOut, StockOut
from fastapi_app.shared_models.order import ORDER_STATUS_SHIPPED
from fastapi_app.utils import parse_date_value

logger = logging.getLogger(__name__)


def _build_stockout_entity(
    fields: dict, session_id: str, product_id: int | None, qty: int,
    is_validated: bool, validation_error: str, product_name: str,
) -> StagingStockOut:
    stockout_date = parse_date_value(fields.get('stockout_date')) or datetime.now(UTC)  # aware UTC：staging_stock_out.stockout_date 列为 timestamptz
    customer = str(fields.get('customer', '')).strip()

    stock_check_passed = False
    stock_check_message = ''
    if is_validated:
        stock_check_passed = True
        stock_check_message = '库存充足'

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

def _stockout_extra_updates(entity, data: dict, _db: AsyncSession) -> None:
    if 'quantity' in data and entity.product_id:
        # extra_updates runs after quantity is set; perform stock check here
        pass
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
                              shipment_info: dict) -> set[int]:
    """按订单 FIFO 分摊出库数量，生成 StockOut 行。返回受影响订单 id 集。"""
    affected_order_ids: set[int] = set()
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
            affected_order_ids.add(order_detail['order_id'])
            remaining_qty -= ship_qty
    return affected_order_ids


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

    affected_order_ids = await _allocate_ship_fifo(db, staging, product_id, shipment_info)

    # 统一写入口：带 version 守卫并递增 version（原先直写两者都不做，
    # 与走乐观锁的写入口并发时会丢失更新）。
    await apply_stock_delta_locked(db, product, -staging.quantity)

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

    log = InventoryLog(
        product_id=staging.product_id,
        change_type='出库',
        change_quantity=-staging.quantity,
        related_id='',
        idem_key=_import_idem_key(
            'stockout', staging.customer, product_id, staging.quantity,
            staging.stockout_date or datetime.now(UTC),
        ),
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
    return await _generic_import_staging_from_excel(
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

async def import_staging_stockouts_from_file(
    db: AsyncSession, file_content: bytes, session_id: str,
    filename: str = '', task_id: str = '',
) -> tuple[int, str, list[str]]:
    """从 OCR 文件（PDF/图片）导入出货到暂存区 — 委托给 OCR service"""
    from fastapi_app.services.ocr_service import import_staging_stockouts_from_file as _ocr_import
    return await _ocr_import(db, file_content, session_id, filename=filename, task_id=task_id)
