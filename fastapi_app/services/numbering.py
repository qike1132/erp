"""
编号生成服务（业务专用异步实现）

从 batch_service.py 提取的编号生成逻辑，消除 order_service ↔ batch_service 的循环依赖。

本模块是全系统统一的编号生成内核：期间段采用**北京口径**（business_period_str，
YYMM 月流水），序号由 numbering_counter 表原子递增分配（见 numbering_sequence），
是全系统唯一水位源。单号（generate_number_async）与批量（generate_number_batch）
共用同一张表、同一套冲突语义与同一把进程内锁，混用也不重号。

所有取号以当期（本月）已落库最大编号为种子（read_period_max，按编号自身期间段过滤），
计数独立短事务提交——业务事务回滚仅产生跳号、不回收序号。
"""
import asyncio
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.services.numbering_sequence import (
    allocate_sequence,
    allocate_sequence_range,
    business_period_str,
    read_period_max,
)
from fastapi_app.shared_models import Order, PurchaseOrder, StockIn, StockOut

logger = logging.getLogger(__name__)


# ==================== 编号生成 ====================

# 进程内串行化取号，降低计数表争用；跨进程唯一性由 numbering_counter 原子递增保证。
_allocate_lock = asyncio.Lock()


async def generate_number_async(prefix: str, model, number_field: str, db: AsyncSession) -> str:
    """
    异步编号生成器（跨进程安全）

    生成策略：
    1. 协程内 asyncio.Lock 串行化同进程调用，降低计数表争用
    2. 以当期（本月）已落库最大编号为种子（无锁读，仅保证首月连续性），通过
       numbering_counter 表原子递增分配序号，多 worker 下无重号
    3. 计数独立短事务提交，业务事务回滚仅产生跳号（见 numbering_sequence）

    Args:
        prefix: 编号前缀 (如 'PO', 'BH', 'SO')
        model: 数据模型类
        number_field: 编号字段名称
        db: 异步数据库会话（用于种子读取，可见本事务内未提交编号）

    Returns:
        str: 生成的编号，格式 ``PREFIX-YYMM-NNN``（YYMM 为北京口径，如 PO-2611-001）
    """
    period_str = business_period_str()

    async with _allocate_lock:
        db_max = await read_period_max(db, model, number_field, period_str)
        current_seq = await allocate_sequence(prefix, period_str, seed=db_max)
        return '-'.join((prefix, period_str, str(current_seq).zfill(3)))


async def generate_order_number(db: AsyncSession) -> str:
    """生成订单编号 PO-YYMM-NNN"""
    return await generate_number_async('PO', Order, 'order_no', db)


async def generate_number_batch(
    prefix: str,
    model,
    number_field: str,
    db: AsyncSession,
    count: int,
) -> list[str]:
    """一次预留 ``count`` 个连号，返回编号列表（ITER-2 T2）。

    与 :func:`generate_number_async` 共用同一把 ``asyncio.Lock``、同一张
    ``numbering_counter`` 表与同一套冲突语义，因此**单号与批量混用也不会重号**。
    业务事务回滚只会一次跳掉整段号（而非逐个跳），这是既有「允许跳号」语义的
    放大，已在 ``numbering_sequence`` 的 docstring 中明确；重号才是致命的，而它
    由 :func:`allocate_sequence_range` 的单语句原子递增杜绝。

    Args:
        prefix: 编号前缀，如 ``'PO'``。
        model: 目标模型类（用于读取当期（本月）最大编号作连续性种子）。
        number_field: 编号字段名。
        db: 调用方会话（种子读取要能看到本事务内未提交的编号，保证批内连续）。
        count: 需要几个号。

    Returns:
        编号列表，格式 ``PREFIX-YYMM-NNN``，**按序连续**。

    Note:
        序号用 ``zfill(3)`` 补齐但不截断：当月超过 999 条时会出现 4 位
        （``PO-2611-1000``），编号仍唯一，只是字符串长度变长；按单号排序的
        场景必须用 ``CAST(split_part(...,3) AS BIGINT)`` 而不是字符串排序。
    """
    if count <= 0:
        return []

    period_str = business_period_str()

    async with _allocate_lock:
        db_max = await read_period_max(db, model, number_field, period_str)
        start = await allocate_sequence_range(prefix, period_str, count=count, seed=db_max)

    return ['-'.join((prefix, period_str, str(start + i).zfill(3))) for i in range(count)]


async def generate_stockin_number(db: AsyncSession) -> str:
    """生成备货编号 BH-YYMM-NNN"""
    return await generate_number_async('BH', StockIn, 'stockin_no', db)


async def generate_stockout_number(db: AsyncSession) -> str:
    """生成出货编号 SO-YYMM-NNN"""
    return await generate_number_async('SO', StockOut, 'stockout_no', db)


async def generate_case_movement_number(db: AsyncSession, direction: str) -> str:
    """生成皮套出入库编号（入库 CSI- / 出库 CSO-，格式 YYMM-NNN）。

    两个前缀共写 CaseMovement.movement_no（列唯一）；read_period_max 按期间段
    过滤、前缀无关，故混用不重号。
    """
    from fastapi_app.shared_models import CaseMovement
    prefix = 'CSI' if direction == 'in' else 'CSO'
    return await generate_number_async(prefix, CaseMovement, 'movement_no', db)


async def generate_case_stockout_number(db: AsyncSession) -> str:
    """生成皮套出库编号 CSO-YYMM-NNN"""
    return await generate_case_movement_number(db, 'out')


async def generate_case_stockin_number(db: AsyncSession) -> str:
    """生成皮套入库编号 CSI-YYMM-NNN"""
    return await generate_case_movement_number(db, 'in')


async def generate_purchase_order_number(db: AsyncSession) -> str:
    """生成采购订单编号 PO-YYMM-NNN。

    与客户订单（``generate_order_number``）共用 ``PO`` 前缀 ⇒ 共用
    ``numbering_counter`` 的 ``(PO, 日期)`` 水位，故两类单据不会重号；代价是
    同一字符串可能同时存在于 ``order`` 与 ``purchase_order``（靠来源/类型区分）。
    2026-10-10 由 ``CG`` 统一为 ``PO``，见迁移 ``pg_standalone_089_po_prefix_unify``。
    """
    return await generate_number_async('PO', PurchaseOrder, 'order_no', db)


async def generate_customer_sampling_number(db: AsyncSession) -> str:
    """生成按客户分类打样项目序列号 CS-YYMM-NNN

    格式约定（design.md 2.3.4）：
    - CS：Customer Sampling 前缀
    - YYMM：北京口径期间（business_period_str），如 2611
    - NNN：月内序号，zfill(3)，从 001 开始

    唯一性由 DB 唯一索引 + numbering 服务的 advisory lock + FOR UPDATE 跨进程保证。
    """
    from fastapi_app.shared_models import CustomerSamplingProject
    return await generate_number_async('CS', CustomerSamplingProject, 'sequence_no', db)


async def generate_shipment_number(db: AsyncSession) -> str:
    """生成外发发货单编号 FH-YYMM-NNN

    格式与订单/备货编号一致（PREFIX-YYMM-NNN），前缀 FH = 发货（FaHuo）。
    唯一性由 numbering 服务的 advisory lock + 计数表原子递增跨进程保证。
    """
    from fastapi_app.shared_models import OutsourceShipment
    return await generate_number_async('FH', OutsourceShipment, 'shipment_no', db)
