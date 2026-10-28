"""采购单生成的请求级幂等、typed 来源预查与 PostgreSQL 锁。"""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy

from sqlalchemy import and_, cast, or_, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from fastapi_app.core.pg_locks import acquire_advisory_lock_async, number_lock_key
from fastapi_app.shared_models import (
    Order,
    PurchaseOrder,
    PurchaseOrderGenerateAttempt,
    PurchaseOrderSku,
    StockIn,
)


class IdempotencyConflictError(ValueError):
    """同一操作者的幂等键已绑定另一份来源集合。"""

    code = 'IDEMPOTENCY_CONFLICT'

    def __init__(self) -> None:
        super().__init__(self.code)
        self.detail = {'code': self.code, 'message': '同一幂等键不能用于不同来源记录'}


class LegacySourceAmbiguityError(ValueError):
    """历史裸 ID 关联无法安全区分 Order 与 StockIn。"""

    def __init__(self, composite_ids: list[str]) -> None:
        self.composite_ids = composite_ids
        super().__init__(f"历史采购单来源 ID 存在歧义: {', '.join(composite_ids)}")


def normalize_composite_ids(composite_ids: list[str]) -> list[str]:
    """规范化、去重并排序 typed ID；裸数字仅按旧 Order 格式兼容。"""
    normalized: set[str] = set()
    for raw in composite_ids:
        value = raw.strip()
        if value.isdigit():
            value = f'order:{value}'
        parts = value.split(':')
        if len(parts) != 2 or parts[0] not in {'order', 'stockin'} or not parts[1].isdigit():
            raise ValueError(f'无效来源记录 ID: {raw!r}')
        source_id = int(parts[1])
        if source_id <= 0:
            raise ValueError(f'来源记录 ID 必须为正整数: {raw!r}')
        normalized.add(f'{parts[0]}:{source_id}')
    if not normalized:
        raise ValueError('未选择任何订单')
    return sorted(normalized)


def request_hash(composite_ids: list[str]) -> str:
    """以来源集合而非客户端数组顺序计算请求指纹。"""
    normalized = normalize_composite_ids(composite_ids)
    payload = json.dumps(normalized, ensure_ascii=False, separators=(',', ':')).encode()
    return hashlib.sha256(payload).hexdigest()


async def acquire_key_lock(db: AsyncSession, actor_id: int, key: str) -> None:
    """同一用户的同一请求键串行，锁随外层事务释放。"""
    lock_key = number_lock_key('PURCHASE_GENERATE_KEY', f'{actor_id}:{key}')
    await acquire_advisory_lock_async(db, lock_key)


async def acquire_source_locks(db: AsyncSession, composite_ids: list[str]) -> None:
    """按固定 typed ID 顺序取来源锁，避免自动与人工、批量 AB-BA 竞态。"""
    for composite_id in sorted(composite_ids):
        lock_key = number_lock_key('PURCHASE_GENERATE_SOURCE', composite_id)
        await acquire_advisory_lock_async(db, lock_key)


def _typed_lookup_rows(result_rows: list) -> tuple[dict[str, list[dict]], dict[int, PurchaseOrder]]:
    grouped: dict[str, list[dict]] = {}
    orders: dict[int, PurchaseOrder] = {}
    for po, record_type, source_id in result_rows:
        orders[po.id] = po
        key = f'{record_type}:{source_id}'
        grouped.setdefault(key, [])
        if po.id not in [item['id'] for item in grouped[key]]:
            grouped[key].append(po.to_dict())
    for items in grouped.values():
        items.sort(key=lambda item: item['id'])
    return grouped, orders


async def _find_typed_existing(
    db: AsyncSession, composite_ids: list[str],
) -> dict[str, list[dict]]:
    conditions = []
    for composite_id in composite_ids:
        record_type, raw_id = composite_id.split(':', 1)
        conditions.append(and_(
            PurchaseOrderSku.source_record_type == record_type,
            PurchaseOrderSku.source_order_id == int(raw_id),
        ))
    result = await db.execute(
        select(PurchaseOrder, PurchaseOrderSku.source_record_type, PurchaseOrderSku.source_order_id)
        .join(PurchaseOrderSku, PurchaseOrderSku.po_id == PurchaseOrder.id)
        .options(selectinload(PurchaseOrder.items))
        .where(or_(*conditions))
        .order_by(PurchaseOrder.id)
    )
    grouped, _orders = _typed_lookup_rows(list(result.all()))
    return grouped


def _json_source_ids(po: PurchaseOrder) -> set[int]:
    try:
        values = json.loads(po.source_order_ids or '[]')
    except (TypeError, ValueError):
        return set()
    if not isinstance(values, list):
        return set()
    return {value for value in values if type(value) is int}


async def _legacy_candidates(db: AsyncSession, source_ids: list[int]) -> list[PurchaseOrder]:
    jsonb_col = cast(PurchaseOrder.source_order_ids, JSONB)
    result = await db.execute(
        select(PurchaseOrder)
        .options(selectinload(PurchaseOrder.items), selectinload(PurchaseOrder.skus))
        .where(
            PurchaseOrder.source_order_ids.isnot(None),
            PurchaseOrder.source_order_ids.op('~')(r'^\s*\['),
            or_(*[jsonb_col.contains([source_id]) for source_id in source_ids]),
        )
        .order_by(PurchaseOrder.id)
    )
    return list(result.scalars().unique().all())


async def _source_table_ids(db: AsyncSession, source_ids: list[int]) -> tuple[set[int], set[int]]:
    order_rows = await db.execute(select(Order.id).where(Order.id.in_(source_ids)))
    stockin_rows = await db.execute(select(StockIn.id).where(StockIn.id.in_(source_ids)))
    return set(order_rows.scalars().all()), set(stockin_rows.scalars().all())


async def _merge_legacy_existing(
    db: AsyncSession,
    composite_ids: list[str],
    grouped: dict[str, list[dict]],
) -> None:
    unresolved = [cid for cid in composite_ids if not grouped.get(cid)]
    if not unresolved:
        return
    source_ids = [int(cid.split(':', 1)[1]) for cid in unresolved]
    candidates = await _legacy_candidates(db, sorted(set(source_ids)))
    if not candidates:
        return
    order_ids, stockin_ids = await _source_table_ids(db, source_ids)
    ambiguous: list[str] = []
    for composite_id in unresolved:
        record_type, raw_id = composite_id.split(':', 1)
        source_id = int(raw_id)
        matches = [po for po in candidates if source_id in _json_source_ids(po)]
        if not matches:
            continue
        safe_matches: list[PurchaseOrder] = []
        for po in matches:
            typed_types = {
                sku.source_record_type
                for sku in po.skus
                if sku.source_order_id == source_id
            }
            if typed_types:
                # 已有 typed 快照时以快照为准：同号的另一来源单不能被当成
                # 当前来源的「重复单」，否则 Order/StockIn 同号会互相阻断。
                if record_type in typed_types:
                    safe_matches.append(po)
                continue
            unambiguous = (
                source_id in order_ids and source_id not in stockin_ids and record_type == 'order'
            ) or (
                source_id in stockin_ids and source_id not in order_ids and record_type == 'stockin'
            )
            if not unambiguous or po.skus:
                ambiguous.append(composite_id)
                break
            safe_matches.append(po)
        if composite_id in ambiguous:
            continue
        if safe_matches:
            grouped[composite_id] = [po.to_dict() for po in safe_matches]
    if ambiguous:
        raise LegacySourceAmbiguityError(ambiguous)


async def find_existing_by_source(
    db: AsyncSession, composite_ids: list[str],
) -> dict[str, list[dict]]:
    """按 typed 来源查任意状态关联单；历史裸 ID 只在无歧义时兜底。"""
    normalized = normalize_composite_ids(composite_ids)
    grouped = await _find_typed_existing(db, normalized)
    await _merge_legacy_existing(db, normalized, grouped)
    return {cid: grouped.get(cid, []) for cid in normalized}


async def load_replay(
    db: AsyncSession, actor_id: int, key: str, fingerprint: str,
) -> dict | None:
    """成功结果直接重放；预期业务失败只校验指纹并允许重新校验。"""
    attempt = await db.scalar(
        select(PurchaseOrderGenerateAttempt).where(
            PurchaseOrderGenerateAttempt.actor_id == actor_id,
            PurchaseOrderGenerateAttempt.idempotency_key == key,
        )
    )
    if attempt is None:
        return None
    if attempt.request_hash != fingerprint:
        raise IdempotencyConflictError()
    body = attempt.response_body
    if not body or not body.get('success'):
        return None
    replay = deepcopy(body)
    replay.update({
        'code': 'OK',
        'created_count': 0,
        'idempotent': True,
        'message': '已复用首次生成结果，无需重复下单',
    })
    return replay


async def save_result(
    db: AsyncSession,
    actor_id: int,
    key: str,
    fingerprint: str,
    result: dict,
) -> None:
    """在同一数据库事务内登记成功或预期业务结果。"""
    attempt = await db.scalar(
        select(PurchaseOrderGenerateAttempt).where(
            PurchaseOrderGenerateAttempt.actor_id == actor_id,
            PurchaseOrderGenerateAttempt.idempotency_key == key,
        )
    )
    if attempt is None:
        attempt = PurchaseOrderGenerateAttempt(
            actor_id=actor_id,
            idempotency_key=key,
            request_hash=fingerprint,
        )
        db.add(attempt)
    if attempt.request_hash != fingerprint:
        raise IdempotencyConflictError()
    attempt.response_body = deepcopy(result)
    await db.flush()
