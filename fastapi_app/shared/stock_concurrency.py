"""
库存并发安全工具

提供悲观锁 + 乐观锁双重保障，确保 product.current_stock 在并发场景下不会出现数据不一致。
用法参照 Case 模型的 with_for_update() 模式。
"""
import logging
import os

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.exceptions import ConflictError
from fastapi_app.shared_models import Product

logger = logging.getLogger(__name__)

# 乐观锁冲突时的最大重试次数
MAX_RETRY = 3

# 负库存策略（P1-2）：默认拒绝扣减后库存为负，只有显式配置才放行。
# 策略键 ALLOW_NEGATIVE_STOCK 声明在 .env / .env.example（scripts/ops/check_env_drift.py 校验）
_TRUTHY = frozenset({"1", "true", "yes", "on"})


def allow_negative_stock() -> bool:
    """负库存策略开关：读取 env ALLOW_NEGATIVE_STOCK（缺省/假值 = 拒绝）。"""
    return os.getenv("ALLOW_NEGATIVE_STOCK", "").strip().lower() in _TRUTHY


def _shortage_message(current_stock: int, delta: int) -> str:
    """库存不足文案的唯一来源（逐字沿用历史 stock_concurrency 文案）。

    数据库原子守卫（UPDATE ... WHERE current_stock + delta >= 0，P1-6）在竞态下
    拦下扣减时同样复用本函数，避免出现第二套「库存不足」文案；该守卫仅在策略
    拒绝负库存时附加（见 allow_negative_stock）。
    """
    return f'库存不足！当前库存: {current_stock}，需要: {abs(delta)}'


def check_stock_available(
    current_stock: int,
    delta: int,
    *,
    message: str | None = None,
) -> str | None:
    """统一负库存校验入口（不抛异常版）。

    全仓唯一的负库存判定点：扣减后库存为负时，默认拒绝；只有
    ALLOW_NEGATIVE_STOCK 为真值才放行。

    Args:
        current_stock: 变更前的库存。
        delta: 本次库存变化量（负数=扣减，正数=入库）。
        message: 自定义拒绝文案；缺省沿用历史 stock_concurrency 文案。

    Returns:
        None 表示放行；字符串为拒绝原因（调用方可直接展示或收集为错误行）。
    """
    if allow_negative_stock():
        return None
    if current_stock + delta < 0:
        return message or _shortage_message(current_stock, delta)
    return None


def assert_stock_available(
    current_stock: int,
    delta: int,
    *,
    message: str | None = None,
) -> None:
    """统一负库存校验入口（抛异常版）。

    被拒绝时抛 ValueError —— 异常类型与历史内联判断一致，缺省文案也与
    历史 stock_concurrency 文案逐字一致；调用点可用 message 保持自身文案。

    Raises:
        ValueError: 策略拒绝且 current_stock + delta < 0。
    """
    reason = check_stock_available(current_stock, delta, message=message)
    if reason is not None:
        raise ValueError(reason)


class StockConcurrentError(ConflictError):
    """库存并发冲突异常，返回 HTTP 409 而非 500"""

    def __init__(self, message: str = "库存数据并发冲突，请重试"):
        super().__init__(message=message)


async def get_product_for_update(db: AsyncSession, product_id: int) -> Product:
    """
    获取产品并加行级悲观锁（SELECT ... FOR UPDATE）。

    在事务内使用，确保同一产品的库存不会被并发修改。事务提交由
    get_async_db / db_transaction 统一控制，本函数不提交。
    """
    result = await db.execute(
        select(Product).where(Product.id == product_id).with_for_update()
    )
    product = result.scalar_one_or_none()
    if not product:
        raise ValueError(f'产品ID {product_id} 不存在')
    return product


class _StockVersionConflictError(Exception):
    """内部信号：本轮 version 条件 UPDATE 未命中，需要回滚 savepoint 后重试。"""

    def __init__(self, product_id: int, attempt: int):
        super().__init__(f'产品ID={product_id}, 第{attempt}次尝试')
        self.product_id = product_id
        self.attempt = attempt


async def _classify_update_miss(
    db: AsyncSession,
    product_id: int,
    old_version: int,
    delta: int,
) -> None:
    """UPDATE 影响 0 行时区分原因，避免把「库存不足」误报成「并发冲突」。

    WHERE 带 version = old_version，并在策略拒绝负库存时附加 P1-6 原子扣减守卫
    current_stock + delta >= 0；此时命中 0 行有两种可能。此处按
    (id, version == old_version) 重读该行判定：
    （策略放行、守卫未附加时 0 行只可能是 version 冲突，下面的判定自然落空。）

    * version 未变但 current_stock + delta < 0 ⇒ 抛 ValueError（精确库存不足，
      文案复用 _shortage_message），交由调用方直接上抛，不进入重试；
    * 其余情况（version 已变 / 行已删除 / 读不到）⇒ 直接返回，由调用方维持既有
      并发冲突语义（重试或抛 StockConcurrentError）。

    populate_existing=True 保证读到的是数据库当前行值（而非身份映射里的陈旧
    对象状态）——持锁路径下对象可能已过期，正是需要判定的场景。
    """
    latest = (await db.execute(
        select(Product)
        .where(Product.id == product_id)
        .execution_options(populate_existing=True)
    )).scalar_one_or_none()
    if latest is None:
        return
    if latest.version == old_version and latest.current_stock + delta < 0:
        raise ValueError(_shortage_message(latest.current_stock, delta))


async def apply_stock_delta_locked(
    db: AsyncSession,
    product: Product,
    delta: int,
) -> Product:
    """库存统一写入口（P1-3）—— 调用方已持有该行悲观锁时的单次写入。

    调用方必须先经 get_product_for_update 拿到行锁（SELECT ... FOR UPDATE）。
    持锁期间该行不可能被并发改写，因此不需要 savepoint 与重试；但仍然带上
    WHERE version = 旧值 条件：一旦对象/锁已过期（version 被并发改写），
    UPDATE 影响 0 行，此时抛 StockConcurrentError 而不是静默丢失更新。

    WHERE 除 version 外还带 current_stock + delta >= 0 —— P1-6 原子扣减守卫，
    且**仅在策略拒绝负库存时附加**（allow_negative_stock() 为假）。未命中时按
    (id, version == old_version) 重读区分原因，抛精确的「库存不足」（ValueError）
    而不是并发冲突；策略放行、守卫未附加时，0 行只可能是 version 冲突。

    与 update_stock_with_optimistic_lock 的分工：
    * 已持锁路径（如批量出库这类自包含、要求无嵌套事务的流程）→ 本函数；
    * 未持锁路径 → update_stock_with_optimistic_lock（savepoint + 重试）。

    Args:
        db: 异步数据库会话
        product: 调用方已加行锁的 Product 对象
        delta: 库存变化量（正数为增加，负数为减少）

    Returns:
        更新后的 Product 对象（current_stock / version 已同步到内存对象）

    Raises:
        StockConcurrentError: UPDATE 未命中 version（对象已过期）
        ValueError: 库存不足（统一策略入口）
    """
    old_version = product.version
    new_stock = product.current_stock + delta

    # 库存不足检查（统一策略入口：env ALLOW_NEGATIVE_STOCK，缺省拒绝）
    assert_stock_available(product.current_stock, delta)

    # 乐观锁更新：WHERE version = old_version；P1-6 原子非负守卫
    # （current_stock + delta >= 0 与迁移 pg_standalone_061 的 CHECK 同口径）
    # 仅在策略拒绝负库存时附加：ALLOW_NEGATIVE_STOCK=true 时守卫与上面的预检一起
    # 解除；缺省/假值路径与改动前逐字一致（守卫存在）。
    from sqlalchemy import update
    conditions = [
        Product.id == product.id,
        Product.version == old_version,
    ]
    if not allow_negative_stock():
        conditions.append(Product.current_stock + delta >= 0)
    stmt = (
        update(Product)
        .where(*conditions)
        .values(current_stock=new_stock, version=old_version + 1)
    )
    result = await db.execute(stmt)

    # 只有明确的「0 行命中」才判定为未命中；驱动未报告 rowcount 时不误判
    if result.rowcount == 0:
        # 先区分「库存不足」与「并发冲突」：不足时抛精确错误（不重试）
        await _classify_update_miss(db, product.id, old_version, delta)
        raise StockConcurrentError(
            f'库存并发冲突，持锁写入未命中: 产品ID={product.id}, version={old_version}'
        )

    # 同步内存对象，保证调用方后续读到的库存/版本一致
    product.current_stock = new_stock
    product.version = old_version + 1
    logger.info(f'库存更新成功(持锁): 产品ID={product.id}, delta={delta}, '
                f'new_stock={new_stock}, version={old_version}->{old_version + 1}')
    return product


async def update_stock_with_optimistic_lock(
    db: AsyncSession,
    product_id: int,
    delta: int,
    retries: int = MAX_RETRY,
) -> Product:
    """
    使用乐观锁更新产品库存（未持锁路径：savepoint + 重试）。

    1. 读取产品（含 version）
    2. 修改 current_stock
    3. 提交时 WHERE 条件包含 version（以及**策略拒绝负库存时**附加的 P1-6 原子
       守卫 current_stock + delta >= 0），任一不满足则影响行数为 0
    4. 影响行数为 0 时先区分原因：被守卫拦下（扣成负数）⇒ 抛精确「库存不足」
       （不重试）；version 变化 ⇒ 回滚本轮 savepoint 并重试（最多 retries 次）

    Args:
        db: 异步数据库会话
        product_id: 产品ID
        delta: 库存变化量（正数为增加，负数为减少）
        retries: 最大重试次数

    Returns:
        更新后的 Product 对象

    Raises:
        StockConcurrentError: 重试耗尽仍冲突
        ValueError: 库存不足
    """
    product: Product | None = None
    for attempt in range(retries):
        try:
            async with db.begin_nested():
                if attempt > 0 and product is not None:
                    db.expunge(product)
                result = await db.execute(select(Product).where(Product.id == product_id))
                product = result.scalar_one_or_none()
                if not product:
                    raise ValueError(f'产品ID {product_id} 不存在')

                old_version = product.version
                new_stock = product.current_stock + delta

                # 库存不足检查（统一策略入口：env ALLOW_NEGATIVE_STOCK，缺省拒绝）
                assert_stock_available(product.current_stock, delta)

                # 2. 乐观锁更新：WHERE version = old_version；P1-6 原子非负守卫
                #    （current_stock + delta >= 0，与迁移 pg_standalone_061 的 CHECK
                #    同口径）仅在策略拒绝负库存时附加。
                from sqlalchemy import update
                conditions = [
                    Product.id == product_id,
                    Product.version == old_version,
                ]
                if not allow_negative_stock():
                    conditions.append(Product.current_stock + delta >= 0)
                stmt = (
                    update(Product)
                    .where(*conditions)
                    .values(current_stock=new_stock, version=old_version + 1)
                )
                result = await db.execute(stmt)

                if result.rowcount != 1:
                    # 先区分「库存不足」与「版本冲突」：扣成负数时抛精确的库存不足
                    # 错误（ValueError 随 savepoint 回滚后上抛，不进入重试）
                    await _classify_update_miss(db, product_id, old_version, delta)
                    # 版本冲突：抛异常让 savepoint 真正回滚（丢弃本轮 SELECT/UPDATE，
                    # 事务中其他有效修改保留），由外层 except 捕获后重试
                    raise _StockVersionConflictError(product_id, attempt + 1)

                # 更新成功，刷新对象
                await db.refresh(product)
                logger.info(f'库存更新成功: 产品ID={product_id}, delta={delta}, '
                            f'new_stock={new_stock}, version={old_version}->{old_version + 1}')
                return product
        except _StockVersionConflictError as exc:
            logger.warning(f'库存乐观锁冲突: 产品ID={product_id}, 第{exc.attempt}次重试')

    raise StockConcurrentError(
        f'库存并发冲突，重试{retries}次后仍失败: 产品ID={product_id}'
    )
