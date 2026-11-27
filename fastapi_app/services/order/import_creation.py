"""Excel 订单导入的**唯一**建单入口（审计 O-30 / D-H2，2026-11-27）。

三条订单导入路径原先各内联一份建单逻辑，且**都漏写 ``OrderItem``、都不调
``auto_generate_for_order``**：

- ARQ 端点 ``/tasks/import-orders`` → ``tasks/batch_tasks.batch_import_orders_task``
- 综合导入「订单管理」Sheet → ``services/batch_import_core.import_orders_from_data``
- 单 Sheet 端点 ``/batch/import-orders`` → ``services/batch_import_service.import_orders_service``

湖北订单页/外发进度页只按 ``Order.items.any(OrderItem.product.has(factory==…))``
入选（``services/order/beile.py``，没有 ``Order.product_id`` 回退），故导入的
湖北订单在湖北侧完全不可见（确认流程 404、不带出外发工序）。三份实现各自漂移
正是根因——某次修复只改一条就会重现，故收敛成一个函数，并配结构守卫
（``tests/test_order_import_creates_order_item.py``）钉住「三条路径都必须调它」。

## 收敛时拍板的差异口径

| 差异 | 选择 | 理由 |
|---|---|---|
| ``InventoryLog.change_type`` | ``'订单'`` | 与 ``order/commands.create_order``、暂存确认一致；``'订单创建'`` 除 ARQ 外只有批量创建一条在用，且 ``inventory_reconcile`` 对两者都按「需求类」处理，无功能差异 |
| ``related_id`` | ``order_no`` | 与 commands / 暂存 / 核销回滚一致（ARQ 原为 ``str(order.id)``） |
| ``customer`` | 写入 | ARQ 原本就写；core/service 漏写导致流水按客户筛不出来 |
| 客户主数据校验 | 三条都校验 | 客户名是无外键快照，不校验会留下孤儿单据（2026-08-10 事故）；ARQ 原先不校验 |
| 多命中产品 | 行级报错 | ARQ 原 ``scalar_one_or_none`` 抛 ``MultipleResultsFound`` 失败整批（D-M4） |
| 锁序 | ``Product → Order`` | 本函数**不加锁**，要求调用方先锁产品再建单；单 Sheet 路径原先把锁放在 flush 之后（A-M1 死锁环）已顺带修正 |

## 契约

- 本函数**不加锁**。需要库存抵扣/并发敏感的调用方必须先锁产品再调用
  （锁序 Product → Order；ARQ 与单 Sheet 路径已在调用前取锁）。
- **综合导入路径仍是「先建单、后抵扣时取锁」**（A-M1 残留，2026-11-27 评审）：
  订单插入会对 ``Product`` 持 FK ``KEY SHARE``，随后 ``process_order_deduction``
  里的 ``get_product_for_update`` 要升级成 ``FOR UPDATE``——与另一条同时持
  ``FOR UPDATE`` 的路径交错即成 40P01 死锁环。本函数**不能**替调用方补锁
  （无锁版本被单 Sheet/ARQ 依赖），综合导入的 deduct 行处理器需自己先
  ``get_product_for_update`` 再建单。现有测试无法覆盖锁序，勿删本说明。
- ``auto_generate_for_order`` 在本函数内调用（失败自身吞掉、不影响建单），
  这样三条路径不会再有「忘记带出外发工序」的分支。
"""
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.services.order_deduction_service import clamp_deduct_to_quantity
from fastapi_app.shared_models import InventoryLog, Order, OrderItem
from fastapi_app.shared_models.order import ORDER_STATUS_PENDING_STOCK


async def create_imported_order(
    db: AsyncSession,
    *,
    order_no: str,
    product_id: int,
    product_name: str | None,
    product_barcode: str | None,
    customer: str,
    quantity: int,
    order_date: datetime,
    note: str = '',
    deduct_stock: bool = False,
    deduct_quantity: int = 0,
    idem_key: str | None = None,
    log_prefix: str = '批量导入订单',
) -> tuple[Order, OrderItem]:
    """写一笔导入订单：``Order`` + ``OrderItem`` + ``InventoryLog`` + 外发工序。

    Args:
        order_no: 已由调用方取号的订单号（取号函数因路径不同而可注入/可打桩）。
        product_name/product_barcode: SKU 快照；调用方手头已有产品对象，避免本函数再查库
            （导入行处理器跑在 savepoint 内，多余查询会被假会话测试直接拒绝）。
        order_date: aware UTC；同时作为库存流水的 ``change_date`` 与幂等键业务日。
        deduct_stock/deduct_quantity: 抵扣意图；明细先按订单数量收口落库，
            **实际扣减由调用方调 ``process_order_deduction`` 后按实扣回写**
            （P1-17：明细必须与实扣同口径，备货不足时实扣 < 申请量）。
        idem_key: 行级幂等键（``batch_import_core._import_idem_key`` 口径），
            由调用方计算以保留各路径的打桩点。
        log_prefix: 流水备注前缀，保留各路径既有文案。

    返回 ``(order, order_item)``：两者均已 flush、``id`` 可用。调用方在
    ``process_order_deduction`` 之后必须把返回的实扣量写回
    ``order_item.deduct_quantity``（先例：``order_batch_create.py:303-312``）。
    """
    order = Order(
        order_no=order_no,
        customer=customer,
        order_date=order_date,
        product_id=product_id,
        quantity=quantity,
        note=note,
        status=ORDER_STATUS_PENDING_STOCK,
    )
    db.add(order)
    await db.flush()

    order_item = OrderItem(
        order_id=order.id,
        product_id=product_id,
        product_name=product_name,
        product_barcode=product_barcode,
        quantity=quantity,
        deduct_stock=bool(deduct_stock),
        deduct_quantity=(
            clamp_deduct_to_quantity(deduct_quantity, quantity) if deduct_stock else 0
        ),
        note=note,
    )
    db.add(order_item)
    db.add(InventoryLog(
        product_id=product_id,
        change_type='订单',
        change_quantity=quantity,
        change_date=order_date,
        customer=customer,
        related_id=order_no,
        idem_key=idem_key,
        note=f'{log_prefix}：{order_no}',
    ))
    await db.flush()

    # 返单自动带出外发工序：按 SKU 预设生成（失败不影响订单创建）。
    # 延迟导入：测试与调用方都通过 ``fastapi_app.services.outsource_service`` 打桩。
    from fastapi_app.services.outsource_service import auto_generate_for_order
    await auto_generate_for_order(db, order)
    return order, order_item
