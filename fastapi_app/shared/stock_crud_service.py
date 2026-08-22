"""
同步编号生成别名（库存域）

职责演变说明：
- 历史版本曾包含完整的同步库存 CRUD（create_stockin/update_stockin/...）与可出货量计算，
  与 services/stock_in_service.py 等异步实现构成"同步/异步双轨"。
- 业务 CRUD 已统一到异步实现（services/stock_*_service.py），本模块的同步 CRUD 均为死代码，
  已全部移除；可出货量计算统一至 shared/shipment_calc.py（异步/同步共用）。
- 本模块当前仅保留"同步编号生成"便捷别名，供 ARQ 同步任务（tasks/batch_tasks.py）使用。
  编号实际实现统一在 core/number_generator.py（同步+异步双实现），此处为薄包装。

编号实现说明（与 services/numbering.py 的区别）：
- 本模块（同步）：调用方会话执行 FOR UPDATE，锁随调用方事务提交才释放；
- services/numbering.py（异步）：使用独立短事务，避免长事务持有行锁。
两者时区策略也不同，属有意设计，未合并。
"""
from sqlalchemy.orm import Session

from fastapi_app.core.number_generator import generate_number_sync
from fastapi_app.shared_models import Order, StockIn, StockOut, StockReturn


def generate_order_number_sync(session: Session) -> str:
    """生成订单编号 PO-YYYYMMDD-XXXX"""
    return generate_number_sync('PO', Order, 'order_date', 'order_no', session)


def generate_stockin_number_sync(session: Session) -> str:
    """生成备货编号 BH-YYYYMMDD-XXXX"""
    return generate_number_sync('BH', StockIn, 'stockin_date', 'stockin_no', session)


def generate_stockout_number_sync(session: Session) -> str:
    """生成出货编号 SO-YYYYMMDD-XXXX"""
    return generate_number_sync('SO', StockOut, 'stockout_date', 'stockout_no', session)


def generate_stockreturn_number_sync(session: Session) -> str:
    """生成退货编号 SR-YYYYMMDD-XXXX"""
    return generate_number_sync('SR', StockReturn, 'return_date', 'return_no', session)
