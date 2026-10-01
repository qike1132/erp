"""暂存区通用导入/更新骨架与辅助

从 staging_service.py 按实体拆出,行为与原实现完全一致。
"""
import asyncio
import contextlib
import logging
import os
import tempfile
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.cache import cache_result
from fastapi_app.core.exceptions import NotFoundError
from fastapi_app.services.batch_service import (
    parse_excel_file_async,
    read_excel_sheets_async,
)
from fastapi_app.shared_models import Product

logger = logging.getLogger(__name__)


async def _find_product_by_name_or_barcode(db: AsyncSession, name_or_barcode: str):
    result = await db.execute(
        select(Product).where(
            (Product.name == name_or_barcode) | (Product.barcode == name_or_barcode)
        )
    )
    return result.scalar_one_or_none()

@cache_result(key_prefix='products:staging_map', ttl=300, local_ttl=60, key_builder=lambda **kwargs: 'v1')
async def _cached_product_id_map(db: AsyncSession) -> dict:
    """产品名称/条码 → id 映射（纯数据，可序列化）。

    产品变更低频（变更时经 CacheDomain.PRODUCT 的 products:* 模式失效），
    避免每次 Excel 导入全表加载 Product。缓存返回 dict[str, int]。
    """
    result = await db.execute(select(Product.id, Product.name, Product.barcode))
    id_map: dict[str, int] = {}
    for pid, name, barcode in result.all():
        if name:
            id_map.setdefault(name.lower().strip(), pid)
        if barcode:
            id_map.setdefault(barcode, pid)
    return id_map

async def _build_product_map(db: AsyncSession) -> dict[str, Product]:
    """构建 name/barcode → Product 对象映射（数据来自缓存的产品 id 映射）。

    仅当 Excel 中存在缓存中未命中的产品时回退全表查询，避免常见场景的全表加载。
    """
    id_map = await _cached_product_id_map(db)
    ids = set(id_map.values())
    products = {}
    if ids:
        result = await db.execute(select(Product).where(Product.id.in_(ids)))
        products = {p.id: p for p in result.scalars().all()}
    product_map: dict[str, Product] = {name: products[pid] for name, pid in id_map.items() if pid in products}
    return product_map

async def _validate_and_map_product(
    product_map: dict[str, Product], product_name: str
) -> tuple[bool, str, int | None]:
    product = product_map.get(product_name.lower().strip())
    product = product or product_map.get(product_name)
    if product:
        return True, '', product.id
    return False, f'产品"{product_name}"不存在', None

def _format_import_result(imported: int, entity_label: str, errors: list[str]) -> str:
    result_msg = f'成功导入 {imported} 个{entity_label}到暂存区'
    if errors:
        total_err = len(errors)
        result_msg += f'。共{total_err}个错误: {"; ".join(errors[:5])}'
        if total_err > 5:
            result_msg += f'...（仅显示前5条，共{total_err}条）'
    return result_msg

def _parse_deduct_flag(deduct_flag: Any, qty: int) -> tuple[bool, int]:
    if not deduct_flag:
        return False, 0
    deduct_str = str(deduct_flag).strip()
    if deduct_str.isdigit():
        deduct_qty = int(deduct_str)
        return deduct_qty > 0, deduct_qty
    if deduct_str.lower() in ('是', 'yes', 'y'):
        return True, qty
    return False, 0

async def _generic_import_staging_from_excel(
    db: AsyncSession,
    file_content: bytes,
    session_id: str,
    staging_model: type,
    clear_func: Callable,
    sheet_keyword: str,
    entity_label: str,
    build_entity: Callable[[dict[str, Any], str, int | None, int, bool, str, str], object],
    column_names: dict[str, str],
    required_fields: list[str],
    extra_row_validations: Callable[[dict[str, Any], int], Awaitable[list[str]]] | None = None,
) -> tuple[int, str, list[str]]:
    await clear_func(db, session_id)

    temp_path = None
    try:
        temp_fd, temp_path = tempfile.mkstemp(suffix='.xlsx')
        await asyncio.to_thread(os.write, temp_fd, file_content)
        os.close(temp_fd)

        success, sheets, err = await read_excel_sheets_async(temp_path)
        if not success:
            return 0, f'Excel读取失败: {err}', []

        target_sheet = next((s for s in sheets if sheet_keyword in s), None)
        if not target_sheet:
            return 0, f'没有找到"{sheet_keyword}"Sheet', []

        success, data_list, err = await parse_excel_file_async(temp_path, target_sheet)
        if not success:
            return 0, f'数据解析失败: {err}', []

        product_map = await _build_product_map(db)
        imported = 0
        errors: list[str] = []

        for idx, row_data in enumerate(data_list, start=2):
            try:
                if extra_row_validations:
                    # 校验器是 async 的（见 staging/stockin.py 的 _validate_stockin_customer），未 await 会把协程当列表 extend
                    extra_errs = await extra_row_validations(row_data, idx)
                    if extra_errs:
                        errors.extend(extra_errs)
                        continue

                field_values: dict[str, Any] = {}
                missing = []
                for req_field in required_fields:
                    value = row_data.get(column_names.get(req_field, req_field))
                    if not value:
                        missing.append(req_field)
                    field_values[req_field] = value

                if missing:
                    errors.append(f'第{idx}行缺少必填字段（{"/".join(missing)}）')
                    continue

                product_name = str(field_values.get('product_name', '')).strip()
                is_validated, validation_error, product_id = await _validate_and_map_product(
                    product_map, product_name
                )

                qty = 0
                with contextlib.suppress(ValueError, TypeError):
                    qty = int(field_values.get('quantity', 0))

                entity = build_entity(
                    field_values, session_id, product_id, qty,
                    is_validated, validation_error, product_name,
                )
                db.add(entity)
                imported += 1

            except (ValueError, TypeError, OSError) as e:
                errors.append(f'第{idx}行处理失败: {e!s}')
                continue

        await db.flush()
        return imported, _format_import_result(imported, entity_label, errors), errors

    except (ValueError, TypeError, OSError) as e:
        logger.error('%s导入失败: %s', entity_label, str(e), exc_info=True)
        return 0, '导入失败，请稍后重试', []
    finally:
        if temp_path and os.path.exists(temp_path):
            with contextlib.suppress(OSError):
                os.unlink(temp_path)

async def _generic_update_staging_entity(
    db: AsyncSession,
    entity_id: int,
    data: dict,
    model_class: type[Any],
    entity_label: str,
    extra_updates: Callable[[Any, dict, AsyncSession], None] | None = None,
) -> dict:
    result = await db.execute(select(model_class).where(model_class.id == entity_id))
    entity = result.scalar_one_or_none()
    if not entity:
        raise NotFoundError(f'{entity_label} {entity_id} 不存在')

    if 'customer' in data:
        entity.customer = data['customer']
    if 'product_name' in data:
        entity.product_name = data['product_name']
        product = await _find_product_by_name_or_barcode(db, data['product_name'])
        if product:
            entity.is_validated = True
            entity.product_id = product.id
            entity.validation_error = ''
        else:
            entity.is_validated = False
            entity.product_id = None
            entity.validation_error = f'产品"{data["product_name"]}"不存在'
    if 'quantity' in data:
        entity.quantity = int(data['quantity'])
    if extra_updates:
        extra_updates(entity, data, db)

    await db.flush()
    await db.refresh(entity)
    return entity.to_dict()
