"""订单删除的库存抵扣回滚——逐 SKU 归位（P0-1，2026-10-18 审计修复）。

此前直删（order/commands._rollback_order_stock_deduction）与审批删
（approval_service._rollback_deduction_for_approval）两处实现同款缺陷：
把「整张订单全部 SKU 的净扣减量」一次性加回 ``order.product_id``（多 SKU
模型下的首 SKU 兼容值）锁定的单行 Product，InventoryLog 也全记首 SKU——
每删一张多 SKU 订单必然：首 SKU 库存虚增、其余 SKU 漏回滚、流水无法还原。
（2026-10-19 OCR 迭代：这两个包装函数已删，两条路径的调用点直接调本模块。）

本模块把回滚收敛为**单一实现**（两条删除路径此前是复制分叉关系，历次
修复屡次只落一侧）：

- 按 ``stockout.product_id`` 分组求净扣减量（quantity − returned_quantity），
  各 SKU 单独行锁（get_product_for_update，按 product_id 升序取锁）、
  各自走统一库存写入口（apply_stock_delta_locked：version 递增 + 非负守卫）；
- InventoryLog 逐 SKU 记 ``抵扣回滚``，product_id 取该 SKU 自己的归属
  （change_type 维持既名——stock_inventory_service 的「已出货净额」口径
  列表按它排除回滚行，改名会破坏两处 CTE 同步）；
- 单 SKU 订单（全部出库行挂在 order.product_id 上）行为与旧实现等价：
  净量合计、一次加回、一条「订单删除」汇总流水；
- 产品为 NULL 的出库行（历史行 product_id 不可能为 NULL——StockOut FK
  非空；防御性跳过并告警）与 product 行不存在（并发删除）跳过告警，
  不阻断删除主流程（与旧实现「order.product_id 为 NULL 时跳过」同语义）。

锁序契约（2026-10-19 OCR Medium 修复）：本函数内部按 product_id 升序逐行
取锁。调用方在进入前**不得持有任何 product 行锁**（如审批删路径）；若因
外层锁序约定必须预锁（如直删路径为保持与 update_order/出库创建的 P→O
约定），必须**按升序一次性预锁本订单回滚涉及的全部产品行**（与内部序
一致，重锁为 no-op）——严禁只预锁 order.product_id 单行：当它不是回滚
集合的最小 id 时，两条并发删除会互等行锁，构成 AB-BA 死锁窗口。
"""
import logging
from collections import defaultdict

from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.shared.stock_concurrency import (
    apply_stock_delta_locked,
    get_product_for_update,
)
from fastapi_app.shared_models import InventoryLog, Order, StockOut

logger = logging.getLogger(__name__)

# 多 SKU 订单删除时写「抵扣回滚」流水的 change_type（沿用旧值，两处 CTE 按名排除）
_ROLLBACK_LOG_TYPE = '抵扣回滚'


async def rollback_order_stock_by_sku(
    db: AsyncSession,
    order: Order,
    order_stockouts: list[StockOut],
) -> int:
    """删除订单时按 SKU 回滚净抵扣量，返回总回滚量。

    逐 product 分组：组内净量 <= 0 跳过；组产品行不存在时告警跳过
    （不阻断删除）。负库存守卫与 version 递增由 apply_stock_delta_locked
    统一承担（修掉了旧实现直改 ``product.current_stock`` 不递增 version 的问题）。
    """
    net_by_product: dict[int, int] = defaultdict(int)
    for stockout in order_stockouts:
        net_by_product[stockout.product_id] += (
            stockout.quantity - stockout.returned_quantity)

    total_rolled_back = 0
    # 按 product_id 升序取锁：与 order_batch_create._lock_products 的全局
    # 升序锁约定一致，避免与其他删除/编辑路径形成交叉死锁窗口。
    for product_id in sorted(net_by_product):
        net_qty = net_by_product[product_id]
        if net_qty <= 0:
            continue
        # get_product_for_update 对不存在的产品抛 ValueError（其余调用方依赖
        # 该语义，不改它本身）；此处按 docstring 承诺宽容化为跳过+告警，
        # 使下方 None 分支真正可达（2026-10-18 P0 遗留修复，原为死代码）。
        try:
            product = await get_product_for_update(db, product_id)
        except ValueError:
            product = None
        if product is None:
            logger.warning(
                '订单 %s 删除回滚：产品 %s 不存在（并发删除？），跳过 %d 件回滚',
                order.order_no, product_id, net_qty)
            continue
        await apply_stock_delta_locked(db, product, net_qty)
        total_rolled_back += net_qty
        db.add(InventoryLog(
            product_id=product_id,
            change_type=_ROLLBACK_LOG_TYPE,
            change_quantity=net_qty,
            related_id=order.order_no,
            note=f'订单删除回滚抵扣：{order.order_no}，恢复产品「{product.name}」净 {net_qty} 件',
        ))
    if total_rolled_back:
        db.add(InventoryLog(
            product_id=order.product_id,
            change_type='订单删除',
            change_quantity=total_rolled_back,
            related_id=order.order_no,
            note=(f'订单删除：{order.order_no}，订单数量：{order.quantity}，'
                  f'抵扣回滚数量：{total_rolled_back}'),
        ))
    return total_rolled_back
