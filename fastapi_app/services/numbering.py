"""
编号生成服务（业务专用异步实现）

从 batch_service.py 提取的编号生成逻辑，消除 order_service ↔ batch_service 的循环依赖。

本模块与 fastapi_app.core.number_generator 的区别：
- 本模块：仅异步；使用 UTC 时间；使用独立短事务执行 FOR UPDATE 查询后立即提交，
  避免调用方长事务持有行锁。适用于批量操作等长事务场景。
- core/number_generator：提供同步 + 异步双实现；使用本地时间；使用调用方会话执行
  FOR UPDATE，锁随调用方事务提交才释放。适用于短事务场景。

两者未合并的原因：datetime 时区与 FOR UPDATE 事务边界行为不同，直接 re-export 会
改变运行时行为（跨午夜编号切换时机、锁持有时长）。如需统一，须先对齐时区与事务策略。

所有编号生成函数均通过 AsyncNumberGenerator 单例管理内存计数器，
结合数据库 FOR UPDATE 行锁确保跨进程安全。
"""
import asyncio
import logging
from datetime import UTC, datetime
from typing import ClassVar

from sqlalchemy.ext.asyncio import AsyncSession

# 向后兼容：re-export core 的同步实现（本模块无同步版本，直接复用 core 的实现是安全的）
from fastapi_app.core.number_generator import (
    _acquire_advisory_lock_async,  # noqa: F401 - 兼容 re-export，旧调用方可能经本模块引用
    _number_lock_key,  # noqa: F401 - 同上
    generate_number_sync,  # noqa: F401
)
from fastapi_app.services.numbering_sequence import (  # noqa: F401 - 兼容 re-export
    allocate_sequence,
    read_daily_max,
)
from fastapi_app.shared_models import Order, PurchaseOrder, StockIn, StockOut

logger = logging.getLogger(__name__)


# ==================== 编号生成 ====================

class AsyncNumberGenerator:
    """异步编号生成器，在批量操作中维护序号计数器"""
    _instance = None
    _counters: ClassVar[dict] = {}
    _lock = asyncio.Lock()
    _last_cleanup_date = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @classmethod
    def _cleanup_old_entries(cls):
        """清理非当日的计数器条目，防止内存泄漏"""
        today_str = datetime.now(UTC).replace(tzinfo=None).strftime('%Y%m%d')
        # 防御性清理：条目过多时强制清理（即使日期相同）
        if cls._last_cleanup_date == today_str and len(cls._counters) < 500:
            return
        expired_keys = [k for k in cls._counters if not k.endswith(today_str)]
        for k in expired_keys:
            cls._counters.pop(k, None)
        cls._last_cleanup_date = today_str


_async_number_generator = AsyncNumberGenerator()


async def generate_number_async(prefix: str, model, date_field: str, number_field: str, db: AsyncSession) -> str:
    """
    异步编号生成器（跨进程安全）

    生成策略：
    1. 协程内 asyncio.Lock 串行化同进程调用，降低计数表争用
    2. 以当日已落库最大编号为种子（无锁读，仅保证首日连续性），通过
       numbering_counter 表原子递增分配序号，多 worker 下无重号
    3. 计数独立短事务提交，业务事务回滚仅产生跳号（见 numbering_sequence）

    Args:
        prefix: 编号前缀 (如 'PO', 'BH', 'SO')
        model: 数据模型类
        date_field: 日期字段名称
        number_field: 编号字段名称
        db: 异步数据库会话（用于种子读取，可见本事务内未提交编号）

    Returns:
        str: 生成的编号,格式: PREFIX-YYYYMMDD-XXXX
    """
    date_str = datetime.now(UTC).strftime('%Y%m%d')

    async with _async_number_generator._lock:
        _async_number_generator._cleanup_old_entries()

        db_max = await read_daily_max(db, model, date_field, number_field)
        current_seq = await allocate_sequence(prefix, date_str, seed=db_max)
        return '-'.join((prefix, date_str, str(current_seq).zfill(4)))


async def generate_order_number(db: AsyncSession) -> str:
    """生成订单编号 PO-YYYYMMDD-XXXX"""
    return await generate_number_async('PO', Order, 'order_date', 'order_no', db)


async def generate_stockin_number(db: AsyncSession) -> str:
    """生成备货编号 BH-YYYYMMDD-XXXX"""
    return await generate_number_async('BH', StockIn, 'stockin_date', 'stockin_no', db)


async def generate_stockout_number(db: AsyncSession) -> str:
    """生成出货编号 SO-YYYYMMDD-XXXX"""
    return await generate_number_async('SO', StockOut, 'stockout_date', 'stockout_no', db)


async def generate_case_stockout_number(db: AsyncSession) -> str:
    """生成皮套出库编号 CSO-YYYYMMDD-XXXX"""
    from fastapi_app.shared_models import CaseStockOut
    return await generate_number_async('CSO', CaseStockOut, 'stockout_date', 'stockout_no', db)


async def generate_case_stockin_number(db: AsyncSession) -> str:
    """生成皮套入库编号 CSI-YYYYMMDD-XXXX"""
    from fastapi_app.shared_models import CaseStockIn
    return await generate_number_async('CSI', CaseStockIn, 'stockin_date', 'stockin_no', db)


async def generate_purchase_order_number(db: AsyncSession) -> str:
    """生成采购订单编号 CG-YYYYMMDD-XXXX"""
    return await generate_number_async('CG', PurchaseOrder, 'create_time', 'order_no', db)


async def generate_customer_sampling_number(db: AsyncSession) -> str:
    """生成按客户分类打样项目序列号 CS-YYYYMMDD-XXXX

    格式约定（design.md 2.3.4）：
    - CS：Customer Sampling 前缀
    - YYYYMMDD：UTC 日期
    - XXXX：当日序号，zfill(4)，从 0001 开始

    唯一性由 DB 唯一索引 + numbering 服务的 advisory lock + FOR UPDATE 跨进程保证。
    """
    from fastapi_app.shared_models import CustomerSamplingProject
    return await generate_number_async('CS', CustomerSamplingProject, 'created_at', 'sequence_no', db)
