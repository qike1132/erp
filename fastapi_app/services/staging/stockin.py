"""暂存备货实体业务

从 staging_service.py 按实体拆出,行为与原实现完全一致。
"""
import logging
from datetime import UTC, datetime
from typing import cast

from sqlalchemy import CursorResult, delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.exceptions import NotFoundError
from fastapi_app.core.state_machine import StagingAction, StagingStatus, staging_machine
from fastapi_app.services.numbering import generate_stockin_number
from fastapi_app.services.staging._generic import (
    _generic_import_staging_from_excel,
    _generic_update_staging_entity,
)
from fastapi_app.shared_models import InventoryLog, StagingStockIn, StockIn
from fastapi_app.utils import parse_date_value, validate_customer_name

logger = logging.getLogger(__name__)


def _build_stockin_entity(
    fields: dict, session_id: str, product_id: int | None, qty: int,
    is_validated: bool, validation_error: str, product_name: str,
) -> StagingStockIn:
    stockin_date = parse_date_value(fields.get('stockin_date')) or datetime.now(UTC)  # aware UTC：staging_stock_in.stockin_date 列为 timestamptz
    return StagingStockIn(
        session_id=session_id,
        customer=str(fields.get('customer', '')).strip(),
        stockin_date=stockin_date,
        product_name=product_name,
        product_barcode='',
        product_id=product_id,
        quantity=qty,
        note=str(fields.get('note', '') or '').strip(),
        is_validated=is_validated,
        validation_error=validation_error,
        status=StagingStatus.PENDING,
    )

async def _validate_stockin_customer(row_data: dict, idx: int) -> list[str]:
    customer = row_data.get('客户名称') or row_data.get('客户')
    if not customer:
        return []
    is_valid, error_msg = validate_customer_name(str(customer).strip())
    if not is_valid:
        return [f'第{idx}行：{error_msg}']
    return []

def _stockin_extra_updates(entity, data: dict, _db: AsyncSession) -> None:
    if 'stockin_date' in data:
        entity.stockin_date = parse_date_value(data['stockin_date']) or datetime.now(UTC)  # aware UTC：列已迁移为 timestamptz
    if 'note' in data:
        entity.note = data['note']

async def get_staging_stockins(db: AsyncSession, session_id: str) -> list[dict]:
    result = await db.execute(
        select(StagingStockIn)
        .where(StagingStockIn.session_id == session_id, StagingStockIn.status == StagingStatus.PENDING)
        .order_by(StagingStockIn.created_at.desc())
    )
    stockins = result.scalars().all()
    return [stockin.to_dict() for stockin in stockins]

async def clear_staging_stockins_by_session(db: AsyncSession, session_id: str) -> int:
    result = await db.execute(
        delete(StagingStockIn).where(StagingStockIn.session_id == session_id)
    )
    await db.flush()
    # DELETE 的 execute 结果为 CursorResult（与 staging/stockout.py 同写法）
    return cast(CursorResult, result).rowcount

async def clear_staging_stockins(db: AsyncSession, session_id: str):
    await clear_staging_stockins_by_session(db, session_id)

async def delete_staging_stockin(db: AsyncSession, stockin_id: int, session_scope: str | None = None):
    conditions = [StagingStockIn.id == stockin_id]
    if session_scope:
        conditions.append(StagingStockIn.session_id.like(f'{session_scope}%'))
    result = await db.execute(select(StagingStockIn).where(*conditions))
    stockin = result.scalar_one_or_none()
    if not stockin:
        raise NotFoundError(f"暂存备货 {stockin_id} 不存在")
    await db.delete(stockin)
    await db.flush()

async def update_staging_stockin(db: AsyncSession, stockin_id: int, data: dict,
                                 session_scope: str | None = None) -> dict:
    return await _generic_update_staging_entity(
        db, stockin_id, data, StagingStockIn, '暂存备货',
        extra_updates=_stockin_extra_updates,
        session_scope=session_scope,
    )

async def confirm_staging_stockins(
    db: AsyncSession, session_id: str
) -> tuple[int, list[str]]:
    from fastapi_app.shared.stock_concurrency import apply_stock_delta_locked, get_product_for_update

    result = await db.execute(
        select(StagingStockIn).where(
            StagingStockIn.session_id == session_id,
            StagingStockIn.status == StagingStatus.PENDING,
            StagingStockIn.is_validated.is_(True),
        )
    )
    staging_stockins = result.scalars().all()

    if not staging_stockins:
        return 0, ["没有可确认的备货"]

    confirmed = 0
    errors: list[str] = []

    for staging in staging_stockins:
        try:
            async with db.begin_nested():
                if staging.quantity <= 0:
                    errors.append(f'备货{staging.customer}-{staging.product_name}数量无效: {staging.quantity}')
                    staging.status = staging_machine.transition(staging.status, StagingAction.REJECT)
                    continue

                stockin_no = await generate_stockin_number(db)

                stockin = StockIn(
                    stockin_no=stockin_no,
                    stockin_date=staging.stockin_date or datetime.now(UTC),  # aware UTC：stockin_date 列为 timestamptz
                    customer=staging.customer,
                    product_id=staging.product_id,
                    quantity=staging.quantity,
                    note=staging.note,
                )
                db.add(stockin)

                product_id = staging.product_id
                if product_id is None:
                    raise ValueError(f'备货{staging.customer}-{staging.product_name}产品不存在(ID:{product_id})')
                product = await get_product_for_update(db, product_id)
                if not product:
                    raise ValueError(f'备货{staging.customer}-{staging.product_name}产品不存在(ID:{staging.product_id})')
                # 统一写入口：持锁路径也要带 version 守卫并递增 version，
                # 否则与走乐观锁的写入口并发时会因 WHERE version=旧值 仍命中而丢失更新。
                await apply_stock_delta_locked(db, product, staging.quantity)

                log = InventoryLog(
                    product_id=staging.product_id,
                    change_type='备货',
                    change_quantity=staging.quantity,
                    related_id=stockin_no,
                    note=f'批量导入备货：{stockin_no}',
                )
                db.add(log)

                staging.status = staging_machine.transition(staging.status, StagingAction.APPROVE)
                confirmed += 1

        except (ValueError, TypeError, OSError) as e:
            errors.append(f'备货{staging.customer}-{staging.product_name}确认失败: {e!s}')
            staging.status = staging_machine.transition(staging.status, StagingAction.REJECT)

    await db.execute(
        delete(StagingStockIn).where(
            StagingStockIn.session_id == session_id,
            StagingStockIn.status == StagingStatus.REJECTED,
        )
    )
    await db.flush()

    return confirmed, errors

async def import_staging_stockins_from_excel(
    db: AsyncSession, file_content: bytes, session_id: str
) -> tuple[int, str, list[str]]:
    return await _generic_import_staging_from_excel(
        db, file_content, session_id,
        staging_model=StagingStockIn,
        clear_func=clear_staging_stockins_by_session,
        sheet_keyword='备货管理',
        entity_label='备货',
        build_entity=_build_stockin_entity,
        column_names={
            'customer': '客户名称',
            'product_name': '产品名称',
            'quantity': '备货数量',
            'stockin_date': '时间',
            'note': '备注',
        },
        required_fields=['customer', 'product_name', 'quantity'],
        extra_row_validations=_validate_stockin_customer,
    )


# ==================== 暂存出货服务 ====================
