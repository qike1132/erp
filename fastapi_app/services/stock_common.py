"""
库存模块共享辅助工具

存放被入库/出库/退货/订单抵扣多个子模块共用的工具函数，避免重复定义。
"""
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.services.numbering_sequence import _BUSINESS_TZ
from fastapi_app.shared_models import StockOut, StockReturn


async def guard_stockout_deletion(db: AsyncSession, stockout: StockOut) -> None:
    """出货行删除前的退货守卫（迁移 072 的 ``ON DELETE RESTRICT`` 应用层前置）。

    出货行只要被退货记录引用（**无论是否已取消**）就删不掉。active 退货拒绝删除
    （``ValueError`` → 400，保留可追溯台账）；已取消退货解除关联后放行（退货行保留）。

    删出货行的各条路径（``stock_out_service.delete_stockout_core``、
    ``order/deduction._decrease_deduction``）共用此守卫——逐点各写一份必然漂移：
    2026-10-08/09 两次实测都是「某条路径漏挂守卫」→ 撞 RESTRICT 外键冒未映射的
    ``IntegrityError``（500）。
    """
    linked = list((await db.execute(
        select(StockReturn).where(StockReturn.stockout_id == stockout.id)
    )).scalars().all())
    if any(r.status != 'cancelled' for r in linked):
        raise ValueError('该出货存在未取消的退货记录，为保留可追溯记录无法删除！')
    for r in linked:
        r.stockout_id = None


def business_now() -> datetime:
    """业务口径（北京时间）当前时间，naive（DB 列为 TIMESTAMP WITHOUT TIME ZONE）。

    用 UTC 的时分秒去拼 naive 业务时间，会让北京时间 00:00–08:00 的入库
    落到前一天（UTC 落后 8 小时）。时区源与编号模块同源，不另起一套
    （fastapi_app/services/numbering_sequence.py::_BUSINESS_TZ，2026-10-01 P0-5）。
    """
    return datetime.now(_BUSINESS_TZ).replace(tzinfo=None)


def _parse_date_preserve_time(date_str: str, old_time: datetime | None = None) -> datetime:
    """解析入库日期（保留原始时间部分），返回 **aware 北京时间**。

    Z03-R2：StockIn/StockOut/StockReturn 的日期列均为 timestamptz；旧实现返回
    naive 北京墙钟，asyncpg 按机器本地时区解释——生产机（Asia/Shanghai）碰巧正确，
    换机器/改时区即偏 8 小时。统一挂 _BUSINESS_TZ，调用方零改动收敛。

    old_time 来自 timestamptz 列，asyncpg 返回的是 **aware UTC**：直接取 .hour
    会在编辑时把墙钟整体挪 8 小时（北京 14:30 变成 06:30）。必须先换算到业务时区
    再取时分秒，「保留原始时间」才成立。
    """
    try:
        base = datetime.strptime(date_str, '%Y-%m-%d')
    except ValueError:
        raise ValueError('日期格式不正确！') from None
    now = business_now()
    old_local = old_time.astimezone(_BUSINESS_TZ) if old_time is not None and old_time.tzinfo else old_time
    if old_local and (old_local.hour != 0 or old_local.minute != 0 or old_local.second != 0):
        return datetime(
            base.year, base.month, base.day,
            old_local.hour, old_local.minute, old_local.second, tzinfo=_BUSINESS_TZ,
        )
    return datetime(
        base.year, base.month, base.day,
        now.hour, now.minute, now.second, tzinfo=_BUSINESS_TZ,
    )
