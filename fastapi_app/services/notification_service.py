"""
WebSocket 实时通知服务 - 全异步版本

基于 FastAPI WebSocket + Redis Pub/Sub 实现实时库存变更通知和操作冲突预警。
所有 Redis 操作均使用 redis.asyncio，消除事件循环阻塞。

领域事件集成：订阅 DomainEventType 事件，当领域事件触发时自动广播到 WebSocket。
"""
import asyncio
import contextlib
import json
import logging
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, Literal, cast

from sqlalchemy import Row, func, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.exception_handler import INFRA_EXCEPTIONS
from fastapi_app.core.redis_client import (
    get_async_redis_client,
    reset_async_redis_client,
)
from fastapi_app.core.redis_client import (
    redis_infra_exceptions as _redis_infra_exceptions,
)
from fastapi_app.shared_models import AuditLog, Notification, Order, OrderItem, Product, User

logger = logging.getLogger(__name__)


# ===== 领域事件订阅注册 =====
# 订阅领域事件总线，当收到跨域事件时自动通过 WebSocket 广播
def _register_domain_event_subscriptions():
    """注册领域事件订阅：将领域事件转发到 WebSocket 实时通知"""
    try:
        from fastapi_app.core.domain_events import DomainEventType, subscribe

        async def _on_order_status_changed(event):
            """订单状态变更 → WebSocket 广播"""
            await publish_stock_event(StockEvent.ORDER_UPDATED, event.payload)

        async def _on_order_created(event):
            """订单创建 → WebSocket 广播"""
            await publish_stock_event(StockEvent.ORDER_CREATED, event.payload)

        async def _on_stock_out_created(event):
            """出库单创建 → WebSocket 广播"""
            await publish_stock_event("stock_changed", event.payload)

        subscribe(DomainEventType.ORDER_STATUS_CHANGED, _on_order_status_changed)
        subscribe(DomainEventType.ORDER_CREATED, _on_order_created)
        subscribe(DomainEventType.STOCK_OUT_CREATED, _on_stock_out_created)
        logger.info("领域事件订阅已注册: ORDER_STATUS_CHANGED, ORDER_CREATED, STOCK_OUT_CREATED")
    except Exception as e:  # defensive: 启动时领域事件订阅注册失败可忽略
        logger.warning("领域事件订阅注册失败（可忽略）: %s", e)


# 注册时机：由 main.py lifespan 显式调用（批次1 消除模块导入期副作用）


class StockEvent:
    STOCK_CHANGED = "stock_changed"
    SHIPMENT_PLAN_UPLOADED = "shipment_plan_uploaded"
    ORDER_LOCKED = "order_locked"
    ORDER_UNLOCKED = "order_unlocked"
    APPROVAL_REQUESTED = "approval_requested"
    APPROVAL_RESOLVED = "approval_resolved"
    ORDER_CREATED = "order_created"
    ORDER_UPDATED = "order_updated"
    ORDER_DELETED = "order_deleted"
    PURCHASE_ORDER_CREATED = "purchase_order_created"
    BATCH_NO_UPDATED = "batch_no_updated"
    BATCH_COMPLETED = "batch_completed"
    SHIPMENT_COMPLETED = "shipment_completed"
    MATERIAL_UPDATED = "material_updated"
    CASE_STOCK_CHANGED = "case_stock_changed"


EVENT_DISPLAY_MESSAGES = {
    "stock_changed": "库存数据已更新",
    "shipment_plan_uploaded": "新的出货计划已上传",
    "order_created": "新订单已创建",
    "order_updated": "订单信息已更新",
    "order_deleted": "订单已删除",
    "purchase_order_created": "新采购订单已生成",
    "batch_no_updated": "批次号已更新",
    "batch_completed": "批次已完成",
    "shipment_completed": "订单出货已完成",
    "material_updated": "物料数据已更新",
    "case_stock_changed": "皮套仓储数据已更新",
}

# 实时事件的服务端授权边界。未知事件默认拒绝，新增事件必须同步登记权限码。
_EVENT_REQUIRED_PERMISSIONS: dict[str, tuple[str, ...]] = {
    StockEvent.STOCK_CHANGED: (
        'stock_view', 'stockin_manage', 'stockout_manage', 'order_manage',
        'production_plan_view', 'production_plan_manage',
        'production_summary_view', 'production_summary_manage',
        'production_summary_view_filling', 'production_summary_view_handcraft',
        'production_summary_view_packaging', 'production_summary_manage_filling',
        'production_summary_manage_handcraft', 'production_summary_manage_packaging',
    ),
    StockEvent.SHIPMENT_PLAN_UPLOADED: (
        'production_plan_view', 'production_plan_manage', 'stockout_manage',
    ),
    StockEvent.ORDER_LOCKED: ('order_manage',),
    StockEvent.ORDER_UNLOCKED: ('order_manage',),
    StockEvent.ORDER_CREATED: (
        'order_manage', 'beile_order_view', 'purchase_center_manage',
        'production_plan_view', 'production_plan_manage', 'stockout_manage',
    ),
    StockEvent.ORDER_UPDATED: (
        'order_manage', 'beile_order_view', 'purchase_center_manage',
        'production_plan_view', 'production_plan_manage', 'stockout_manage',
    ),
    StockEvent.ORDER_DELETED: (
        'order_manage', 'beile_order_view', 'purchase_center_manage',
        'production_plan_view', 'production_plan_manage', 'stockout_manage',
    ),
    StockEvent.PURCHASE_ORDER_CREATED: ('purchase_center_manage', 'product_manage'),
    StockEvent.BATCH_NO_UPDATED: ('batch_manage', 'order_manage'),
    StockEvent.BATCH_COMPLETED: ('batch_manage', 'order_manage'),
    StockEvent.SHIPMENT_COMPLETED: ('order_manage', 'beile_order_view', 'stockout_manage'),
    StockEvent.MATERIAL_UPDATED: ('product_manage', 'material_registration'),
    StockEvent.CASE_STOCK_CHANGED: ('case_manage',),
}
_SUPER_ONLY_EVENTS = {StockEvent.APPROVAL_REQUESTED, StockEvent.APPROVAL_RESOLVED}
_WS_SEND_TIMEOUT_SECONDS = 2.0

# 共享异步 Redis 客户端已上提至 core.redis_client（批次1 解耦 core↔services）：
# 本模块保留兼容转发供既有调用方渐进迁移；新代码请直接使用 core.redis_client。


async def _get_async_redis_client():
    """兼容转发：获取共享异步 Redis 客户端（见 core.redis_client）"""
    return await get_async_redis_client()


async def _warmup_async_redis():
    """预热异步 Redis 客户端"""
    try:
        client = await get_async_redis_client()
        if client:
            await client.ping()
            logger.info("异步 Redis 客户端预热成功")
    except _redis_infra_exceptions() as e:
        logger.warning("异步 Redis 客户端预热失败: %s", e)
        reset_async_redis_client()


async def publish_stock_event(event_type: str, data: dict, redis_client=None):
    """发布库存事件到 Redis Pub/Sub 频道（异步）"""
    try:
        if redis_client is None:
            redis_client = await _get_async_redis_client()

        if redis_client is None:
            logger.debug("Redis 不可用，跳过事件发布")
            return

        event = {
            "type": event_type,
            "data": data,
            "timestamp": datetime.now(UTC).replace(tzinfo=None).isoformat(),
        }
        await redis_client.publish("erp:stock_events", json.dumps(event, ensure_ascii=False))
        logger.debug("事件已发布: %s", event_type)
    except INFRA_EXCEPTIONS as e:
        logger.warning("事件发布失败: %s", e)


async def publish_event(
    event_type: str,
    data: dict,
    redis_client=None,
):
    """统一事件发布：WebSocket 广播（FCM 推送已于 2026-08-31 随移动端一并摘除）"""
    # WebSocket 广播
    await publish_stock_event(event_type, data, redis_client)


class ConnectionManager:
    """WebSocket 连接管理器 + Redis Pub/Sub 桥梁"""

    def __init__(self):
        self.active_connections: dict[int, list] = {}
        self._principals: dict[object, Any] = {}
        self._redis_task: asyncio.Task | None = None
        self._async_redis = None
        self._pubsub = None
        self._redis_url = None

    async def connect(self, websocket, user_id: int, *, principal=None):
        await websocket.accept()
        self._register(websocket, user_id, principal)

    def connect_existing(self, websocket, user_id: int, *, principal=None):
        self._register(websocket, user_id, principal)

    def _register(self, websocket, user_id: int, principal=None):
        if user_id not in self.active_connections:
            self.active_connections[user_id] = []
        self.active_connections[user_id].append(websocket)
        self._principals[websocket] = principal
        logger.info("WebSocket 连接: user_id=%s, 当前连接数=%s", user_id, len(self.active_connections))

    def update_principal(self, websocket, principal) -> None:
        """周期性复核后刷新权限与工厂范围，避免长连接长期使用旧授权。"""
        if websocket in self._principals:
            self._principals[websocket] = principal

    def disconnect(self, websocket, user_id: int):
        # 必须幂等：广播发送失败与端点 finally 可重复进入本方法。
        self._principals.pop(websocket, None)
        conns = self.active_connections.get(user_id)
        if conns is not None:
            with contextlib.suppress(ValueError):
                conns.remove(websocket)
            if not conns:
                del self.active_connections[user_id]
        logger.info("WebSocket 断开: user_id=%s, 当前连接数=%s", user_id, len(self.active_connections))

    def _event_allowed(self, websocket, event: dict) -> bool:
        principal = self._principals.get(websocket)
        if principal is None:
            return False
        event_type = event.get('type', '')
        is_super = bool(getattr(principal, 'is_super', False))
        if event_type in _SUPER_ONLY_EVENTS:
            return is_super
        required = _EVENT_REQUIRED_PERMISSIONS.get(event_type)
        if not required:
            return False
        if not is_super and not any(principal.has_permission(code) for code in required):
            return False

        raw_data = event.get('data')
        data: dict = raw_data if isinstance(raw_data, dict) else {}
        factories = data.get('factories')
        if factories is None:
            factory = data.get('factory')
            factories = [factory] if factory else []
        user_factory = getattr(principal, 'factory', None)
        return is_super or not (user_factory and factories and user_factory not in factories)

    async def _send_to_targets(self, targets: list[tuple[int, Any]], event: dict) -> None:
        """并发发送并限制单连接等待；慢客户端不得堵住 Redis 监听协程。"""
        if not targets:
            return

        async def _send(user_id: int, websocket):
            try:
                await asyncio.wait_for(
                    websocket.send_json(event), timeout=_WS_SEND_TIMEOUT_SECONDS,
                )
                return None
            except Exception:  # defensive: 单连接失败不得影响其他接收者
                logger.debug("WebSocket 发送失败，标记断开: user_id=%s", user_id, exc_info=True)
                return user_id, websocket

        disconnected = await asyncio.gather(*(_send(uid, ws) for uid, ws in targets))
        for item in disconnected:
            if item is not None:
                self.disconnect(item[1], item[0])

    async def broadcast_event(self, event: dict):
        targets = [
            (user_id, ws)
            for user_id, connections in list(self.active_connections.items())
            for ws in list(connections)
            if self._event_allowed(ws, event)
        ]
        await self._send_to_targets(targets, event)

    async def send_to_user(self, user_id: int, event: dict):
        targets = [(user_id, ws) for ws in list(self.active_connections.get(user_id, []))]
        await self._send_to_targets(targets, event)

    def _build_redis_url(self):
        from fastapi_app.core.config import settings
        url = settings.REDIS_URL
        if settings.REDIS_PASSWORD and settings.REDIS_PASSWORD not in url:
            if url.startswith("rediss://"):
                url = url.replace("rediss://", f"rediss://:{settings.REDIS_PASSWORD}@")
            elif url.startswith("redis://"):
                url = url.replace("redis://", f"redis://:{settings.REDIS_PASSWORD}@")
        return url

    async def start_redis_listener(self):

        self._redis_url = self._build_redis_url()
        self._redis_task = asyncio.create_task(self._listen_loop())

    async def _listen_loop(self):
        import redis.asyncio as aioredis

        while True:
            try:
                self._async_redis = aioredis.from_url(
                    self._redis_url, decode_responses=True
                )
                self._pubsub = self._async_redis.pubsub()
                await self._pubsub.subscribe("erp:stock_events")
                logger.info("Redis Pub/Sub 订阅已启动: erp:stock_events")

                async for message in self._pubsub.listen():
                    if message["type"] == "message":
                        # 单条消息的任何异常**不得**打死整个监听任务：broadcast_event
                        # 里的 ValueError（socket 竞态）等不在 INFRA_EXCEPTIONS 内，
                        # 会逃出外层 while True 使 _redis_task 结束且不重连。
                        try:
                            data = message["data"]
                            if isinstance(data, bytes):
                                data = data.decode("utf-8")
                            event = json.loads(data)
                            if "message" not in event:
                                event["message"] = EVENT_DISPLAY_MESSAGES.get(
                                    event.get("type", ""), "收到新通知"
                                )
                            await self.broadcast_event(event)
                        except Exception as e:  # noqa: BLE001 - 单条消息失败必须隔离，循环续跑
                            logger.error("处理通知消息失败（已跳过该条）: %s", e, exc_info=True)

            except asyncio.CancelledError:
                logger.info("Redis Pub/Sub 监听任务已取消")
                break
            except INFRA_EXCEPTIONS as e:
                logger.error("Redis Pub/Sub 监听异常: %s，5s 后重连", e)

            await self._cleanup_connections()

            if not self._redis_task or self._redis_task.done():
                break

            await asyncio.sleep(5)

    async def _cleanup_connections(self):
        if self._pubsub:
            try:
                await self._pubsub.unsubscribe("erp:stock_events")
                await self._pubsub.close()
            except INFRA_EXCEPTIONS as e:
                logger.debug("PubSub 关闭异常（可忽略）: %s", e)
            self._pubsub = None
        if self._async_redis:
            try:
                await self._async_redis.close()
            except INFRA_EXCEPTIONS as e:
                logger.debug("Redis 连接关闭异常（可忽略）: %s", e)
            self._async_redis = None

    async def stop_redis_listener(self):
        if self._redis_task and not self._redis_task.done():
            self._redis_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._redis_task
        self._redis_task = None
        await self._cleanup_connections()
        logger.info("Redis Pub/Sub 订阅已停止")


manager = ConnectionManager()


# ==================== 工厂通知派发（Task 2） ====================


async def dispatch_factory_notifications(
    session: AsyncSession,
    order: Order,
    action: Literal['new_order', 'order_updated'],
    changed_items: list[OrderItem] | None = None,
    skip_factory: str | None = None,
) -> int:
    """根据订单涉及的工厂，向对应工厂的启用用户派发系统内通知。

    逻辑：
    1. 遍历 order.items（若 changed_items 提供则仅遍历 changed_items 的 product_id/quantity），收集涉及的工厂集合（product.factory 非空）
    2. 对每个工厂，查询 User.factory == 该工厂 且 User.status == True 的用户列表
    3. 为每个用户批量插入 Notification 记录（type/title/content/related_order_id/is_read）
    4. 写入 AuditLog（resource_type='notification', action='CREATE', resource_id=str(order.id), detail 含派发摘要）
    5. 返回派发的通知总数
    6. skip_factory：跳过指定工厂的派发（湖北订单确认流程去重用：含湖北 SKU 的订单
       由 dispatch_beile_unconfirmed_notifications 覆盖湖北用户，避免同一订单给同一
       用户派发两条重复通知；其他地区工厂不受影响）

    注意：
    - 如果订单不涉及任何工厂（所有 product.factory 为 NULL），直接返回 0，不写 AuditLog
    - 使用 session.add_all 批量插入 Notification，await session.flush() 但不 commit（由调用方控制事务）
    - AuditLog 同样 session.add()，不 commit
    - content 摘要格式示例：'订单 SO20260804001（客户：张三）包含湖北产品：枕头A x10、被套B x5'
    - 异步实现：内部用 await 查询 items/products/users，避免在 async 上下文中触发 lazy load
    """
    # 确定要扫描的 items（用 await 查询，避免 lazy load；changed_items 仅取 product_id/quantity）
    # 两个分支分别为列表字面量与 Result.all()（静态为 Row 序列），统一为同一序列类型
    items_data: Sequence[tuple[int, int] | Row[tuple[int, int]]]
    if changed_items is not None:
        items_data = [(it.product_id, it.quantity) for it in changed_items]
    else:
        result = await session.execute(
            select(OrderItem.product_id, OrderItem.quantity)
            .where(OrderItem.order_id == order.id)
        )
        items_data = result.all()

    if not items_data:
        return 0

    # 一次性查询所有 products（避免 N+1 与 lazy load）
    product_ids = {pid for pid, _ in items_data}
    result = await session.execute(
        select(Product).where(Product.id.in_(product_ids))
    )
    products = {p.id: p for p in result.scalars().all()}

    # 按工厂分组收集 SKU 摘要：factory -> [(product_name, quantity), ...]
    factory_skus: dict[str, list[tuple[str, int]]] = {}
    for product_id, quantity in items_data:
        product = products.get(product_id)
        if product is None or not product.factory:
            continue
        factory_skus.setdefault(product.factory, []).append((product.name, quantity))

    if not factory_skus:
        return 0

    title = '新订单通知' if action == 'new_order' else '订单修改通知'
    order_no = order.order_no
    customer = order.customer

    notifications: list[Notification] = []
    factory_user_counts: dict[str, int] = {}

    for factory, sku_list in factory_skus.items():
        if skip_factory and factory == skip_factory:
            # 被跳过的工厂记 0 人，保证 AuditLog 汇总不会 KeyError
            factory_user_counts[factory] = 0
            continue
        result = await session.execute(  # batch-loop: 有意逐行处理,非 N+1
            select(User.id).where(User.factory == factory, User.status.is_(True))
        )
        user_ids = [row[0] for row in result.all()]
        factory_user_counts[factory] = len(user_ids)

        if not user_ids:
            continue

        content_payload = {
            'format_version': 2,
            'order_type': '贝乐订单',
            'order_no': order_no,
            'customer': customer,
            'factory': factory,
            'products': [
                {'name': name, 'quantity': qty}
                for name, qty in sku_list
            ],
        }
        content = json.dumps(content_payload, ensure_ascii=False)

        for uid in user_ids:
            notifications.append(Notification(
                user_id=uid,
                type=action,
                title=title,
                content=content,
                related_order_id=order.id,
                is_read=False,
            ))

    session.add_all(notifications)
    session.add(AuditLog(
        action='CREATE',
        resource_type='notification',
        resource_id=str(order.id),
        detail=json.dumps({
            'action': action,
            'order_no': order_no,
            'customer': customer,
            'factories': {
                f: {'users': factory_user_counts[f], 'sku_count': len(sku_list)}
                for f, sku_list in factory_skus.items()
            },
            'dispatched': len(notifications),
        }, ensure_ascii=False),
    ))
    await session.flush()
    return len(notifications)


# ==================== 湖北新订单未确认提醒（湖北订单确认流程） ====================

BEILE_UNCONFIRMED_TYPE = 'beile_unconfirmed'
BEILE_UNCONFIRMED_TITLE = '湖北新订单待确认'


async def dispatch_beile_unconfirmed_notifications(
    session: AsyncSession,
    order: Order,
    product_quantities: list[tuple[int, int]],
) -> int:
    """湖北新订单未确认提醒：向湖北工厂启用用户派发系统内通知。

    湖北订单确认流程的提醒推送（独立于 dispatch_factory_notifications 的通用
    工厂通知）：新到湖北订单需在 beile-order 页面人工确认，确认前通过通知中心
    提醒相关用户。

    逻辑：
    1. 仅当订单包含 factory=湖北 的 SKU 时触发（其他地区订单不参与本流程）
    2. 通知标题「湖北新订单待确认」，type=beile_unconfirmed
    3. content 采用 v2 结构化 JSON（与 dispatch_factory_notifications 一致），
       通知中心点击后跳转 /beile-order 并高亮该订单
    4. 订单被确认时（order_crud.confirm_beile_order）自动将这些通知标记为已读
    5. 派发失败不影响订单创建（由调用方 try/except 包裹）

    Args:
        session: 数据库会话
        order: 新创建的订单
        product_quantities: [(product_id, quantity), ...]（订单全部 SKU，
            函数内部自行过滤 factory=湖北 的 SKU）

    Returns:
        派发的通知条数
    """
    if not product_quantities:
        return 0

    # 一次性查询所有 products（避免 N+1 与 lazy load）
    product_ids = {pid for pid, _ in product_quantities}
    result = await session.execute(
        select(Product).where(Product.id.in_(product_ids))
    )
    products = {p.id: p for p in result.scalars().all()}

    # 仅收集湖北 SKU 摘要
    hubei_skus: list[tuple[str, int]] = []
    for product_id, quantity in product_quantities:
        product = products.get(product_id)
        if product is not None and product.factory == '湖北':
            hubei_skus.append((product.name, quantity))

    if not hubei_skus:
        return 0

    # 派发给湖北工厂的启用用户
    result = await session.execute(
        select(User.id).where(User.factory == '湖北', User.status.is_(True))
    )
    user_ids = [row[0] for row in result.all()]
    if not user_ids:
        return 0

    content = json.dumps({
        'format_version': 2,
        'order_type': '贝乐订单',
        'order_no': order.order_no,
        'customer': order.customer,
        'factory': '湖北',
        'products': [
            {'name': name, 'quantity': qty}
            for name, qty in hubei_skus
        ],
    }, ensure_ascii=False)

    notifications = [
        Notification(
            user_id=uid,
            type=BEILE_UNCONFIRMED_TYPE,
            title=BEILE_UNCONFIRMED_TITLE,
            content=content,
            related_order_id=order.id,
            is_read=False,
        )
        for uid in user_ids
    ]
    session.add_all(notifications)
    await session.flush()
    logger.info(
        '湖北新订单未确认提醒派发 order_no=%s：%d 条（湖北用户 %d 人，SKU %d 个）',
        order.order_no, len(notifications), len(user_ids), len(hubei_skus),
    )
    return len(notifications)


# ==================== 通知查询函数（自 notification.py 端点下沉） ====================

async def count_unread_notifications(db: AsyncSession, user_id: int) -> int:
    """统计指定用户的未读通知数"""
    count = await db.scalar(
        select(func.count())
        .select_from(Notification)
        .where(Notification.user_id == user_id, Notification.is_read == False)  # noqa: E712
    )
    return int(count or 0)


async def get_notifications_page(
    db: AsyncSession, user_id: int, page: int, page_size: int, only_unread: bool = False,
) -> tuple[list[Notification], int]:
    """分页获取指定用户的通知列表（按 created_at 倒序），返回 (通知列表, 总数)"""
    base_filters = [Notification.user_id == user_id]
    if only_unread:
        base_filters.append(Notification.is_read == False)  # noqa: E712

    total = await db.scalar(
        select(func.count()).select_from(Notification).where(*base_filters)
    )
    total = int(total or 0)

    result = await db.execute(
        select(Notification)
        .where(*base_filters)
        .order_by(Notification.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return list(result.scalars().all()), total


async def mark_all_notifications_read(db: AsyncSession, user_id: int) -> int:
    """将指定用户所有未读通知标记为已读，返回更新条数（事务由调用方管理）"""
    result = await db.execute(
        update(Notification)
        .where(Notification.user_id == user_id, Notification.is_read == False)  # noqa: E712
        .values(is_read=True)
    )
    # Core DML 运行时返回 CursorResult；SQLAlchemy 的 execute() 只声明基类 Result
    return cast(CursorResult, result).rowcount or 0

