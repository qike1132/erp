"""
湖北外发 API 端点

职责：
- 湖北工厂订单列表（复用 beile-list 逻辑，强制 factory=湖北）
- SKU 工序预设 CRUD（按产品固定配置外发工序类型）
- 订单外发工序管理（计划/实际完成时间、开始/完成、按预设生成）

权限：
- outsource_view：查看订单/工序
- outsource_manage：工序预设 CRUD
- outsource_ship：外发工序发货（外协方账号）
- outsource_receive：确认收货（贝乐账号）

说明：发货/收货原先按「用户名 == 贝乐」硬编码区分，现改为权限点；
配套授权脚本 scripts/add_outsource_ship_receive_perms.py 必须先于本代码上线执行。
"""
import logging

from fastapi import APIRouter, Depends, Query
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.database import get_async_db, get_async_read_db
from fastapi_app.core.deps import require_permission
from fastapi_app.core.exceptions import NotFoundError, db_transaction
from fastapi_app.schemas.order import OrderListResponse
from fastapi_app.schemas.outsource import (
    GenerateProcessResponse,
    HubeiProductSearchItem,
    OrderActionResponse,
    OrderProcessFlowListResponse,
    OrderProcessFlowResponse,
    OrderProcessListResponse,
    OrderProcessReceive,
    OrderProcessReceiveBatch,
    OrderProcessShip,
    OrderProcessShipBatch,
    OrderProcessUpdate,
    ProcessTypeBatchCreate,
    ProcessTypeCreate,
    ProcessTypeListResponse,
    ProcessTypeResponse,
    ProcessTypeUpdate,
    ShipmentBatchCreate,
    ShipmentBatchResponse,
    ShipmentCreate,
    ShipmentListResponse,
    ShipmentMergeCreate,
    ShipmentReceiveResponse,
    ShipmentResponse,
    ShippableProcessItem,
    ShipProcessMulti,
    UnshippedProcessItem,
)
from fastapi_app.services import outsource_service
from fastapi_app.shared_models import User

logger = logging.getLogger(__name__)
router = APIRouter()


# ==================== 湖北外发订单列表 ====================

@router.get("/orders", response_model=OrderListResponse)
async def list_outsource_orders(
    page: int = Query(1, ge=1, description="页码"),
    per_page: int = Query(50, ge=1, le=500, description="每页数量"),
    customer: str | None = Query(None, description="客户名筛选"),
    product: str | None = Query(None, max_length=100, description="产品名称/条码关键字筛选"),
    process_status: str | None = Query(
        None, description="外发工序状态筛选：pending(待开始)/in_progress(进行中)/completed(已完成)"
    ),
    db: AsyncSession = Depends(get_async_read_db),
    _user: User = Depends(require_permission("outsource_view")),
) -> OrderListResponse:
    """湖北工厂订单+备货合并列表（强制 factory=湖北，忽略前端传参）。"""
    result = await outsource_service.list_outsource_orders(
        db, page=page, per_page=per_page, customer=customer,
        product=product, process_status=process_status,
    )
    return OrderListResponse(data=result['items'], total=result['total'],
                             page=result['page'], per_page=result['per_page'])


# ==================== SKU 工序预设 ====================

@router.get("/process-types", response_model=ProcessTypeListResponse)
async def list_process_types(
    product_id: int | None = Query(None, description="产品(SKU)ID筛选"),
    product_name: str | None = Query(None, max_length=100, description="产品名称关键字"),
    keyword: str | None = Query(None, max_length=100, description="工序类型关键字"),
    is_active: bool | None = Query(None, description="是否启用筛选"),
    page: int = Query(1, ge=1, description="页码"),
    per_page: int = Query(200, ge=1, le=500, description="每页数量"),
    db: AsyncSession = Depends(get_async_read_db),
    _user: User = Depends(require_permission("outsource_view")),
) -> ProcessTypeListResponse:
    """查询 SKU 外发工序预设。"""
    result = await outsource_service.list_process_types(
        db, product_id=product_id, product_name=product_name,
        keyword=keyword, is_active=is_active,
        page=page, per_page=per_page,
    )
    return ProcessTypeListResponse(data=result['items'], total=result['total'])


@router.post("/process-types", response_model=ProcessTypeResponse)
async def create_process_type(
    data: ProcessTypeCreate,
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(require_permission("outsource_manage")),
) -> ProcessTypeResponse:
    """创建 SKU 外发工序预设。"""
    async with db_transaction(db, error_map={
        IntegrityError: (409, '该产品已存在同名工序，请刷新后重试'),
    }):
        pt = await outsource_service.create_process_type(
            db, data.model_dump(), username=user.username,
        )
        # 预设变更后自动同步：把该 SKU 的所有订单实例对齐到当前预设（新增补齐）
        await outsource_service.sync_orders_for_product(
            db, data.product_id, username=user.username,
        )
    return ProcessTypeResponse(**pt)


@router.post("/process-types/batch", response_model=GenerateProcessResponse)
async def batch_create_process_types(
    data: ProcessTypeBatchCreate,
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(require_permission("outsource_manage")),
) -> GenerateProcessResponse:
    """为一个 SKU 批量添加多个工序预设（自由输入工序名称，幂等去重）。"""
    async with db_transaction(db, error_map={
        IntegrityError: (409, '该产品已存在同名工序，请刷新后重试'),
    }):
        result = await outsource_service.batch_create_process_types(
            db, product_id=data.product_id,
            process_types=data.process_types, username=user.username,
        )
        # 预设变更后自动同步：把该 SKU 的所有订单实例对齐到当前预设
        sync = await outsource_service.sync_orders_for_product(
            db, data.product_id, username=user.username,
        )
    return GenerateProcessResponse(
        success=True,
        message=(
            f"已添加 {result['created']} 道工序，跳过 {result['skipped']} 道重复工序；"
            f"已同步订单工序（新增 {sync['created']}、移除 {sync['removed']}、保留 {sync['kept']}）"
        ),
        created=result['created'],
        skipped=result['skipped'],
    )


@router.put("/process-types/{pt_id}", response_model=ProcessTypeResponse)
async def update_process_type(
    pt_id: int,
    data: ProcessTypeUpdate,
    db: AsyncSession = Depends(get_async_db),
    _user: User = Depends(require_permission("outsource_manage")),
) -> ProcessTypeResponse:
    """更新 SKU 外发工序预设（部分更新）。"""
    async with db_transaction(db, error_map={
        IntegrityError: (409, '该产品已存在同名工序，请刷新后重试'),
    }):
        pt = await outsource_service.update_process_type(
            db, pt_id, data.model_dump(exclude_unset=True),
        )
        # 预设变更后自动同步：把该 SKU 的所有订单实例对齐到当前预设
        await outsource_service.sync_orders_for_product(
            db, pt['product_id'], username=_user.username,
        )
    return ProcessTypeResponse(**pt)


@router.delete("/process-types/{pt_id}", response_model=OrderActionResponse)
async def delete_process_type(
    pt_id: int,
    db: AsyncSession = Depends(get_async_db),
    _user: User = Depends(require_permission("outsource_manage")),
) -> OrderActionResponse:
    """删除 SKU 外发工序预设。"""
    async with db_transaction(db):
        product_id = await outsource_service.delete_process_type(db, pt_id)
        # 预设变更后自动同步：把该 SKU 的所有订单实例对齐到当前预设（移除未发货工序）
        sync = await outsource_service.sync_orders_for_product(
            db, product_id, username=_user.username,
        )
    return OrderActionResponse(
        success=True,
        message=(
            f"工序预设已删除；已同步订单工序"
            f"（新增 {sync['created']}、移除 {sync['removed']}、保留 {sync['kept']}）"
        ),
    )


# ==================== 订单外发工序 ====================

@router.get("/orders/{order_id}/processes", response_model=OrderProcessListResponse)
async def list_order_processes(
    order_id: int,
    db: AsyncSession = Depends(get_async_read_db),
    _user: User = Depends(require_permission("outsource_view")),
) -> OrderProcessListResponse:
    """查询订单外发工序列表。"""
    items = await outsource_service.list_order_processes(db, order_id)
    return OrderProcessListResponse(data=items, total=len(items))


@router.get("/orders/{order_id}/flows", response_model=OrderProcessFlowListResponse)
async def list_order_process_flows(
    order_id: int,
    db: AsyncSession = Depends(get_async_read_db),
    _user: User = Depends(require_permission("outsource_view")),
) -> OrderProcessFlowListResponse:
    """查询订单外发工序流水（发货/收货记录，台账用）。"""
    items = await outsource_service.list_order_flows(db, order_id)
    return OrderProcessFlowListResponse(data=[OrderProcessFlowResponse.model_validate(i) for i in items], total=len(items))


@router.post("/orders/{order_id}/processes/generate", response_model=GenerateProcessResponse)
async def generate_order_processes(
    order_id: int,
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(require_permission("outsource_manage")),
) -> GenerateProcessResponse:
    """按 SKU 预设为订单生成外发工序（返单自动带出的手动触发）。"""
    async with db_transaction(db):
        result = await outsource_service.generate_order_processes(
            db, order_id, username=user.username,
        )
    return GenerateProcessResponse(
        success=True,
        message=f"已生成 {result['created']} 道工序，跳过 {result['skipped']} 道重复工序",
        created=result['created'],
        skipped=result['skipped'],
    )


@router.put("/processes/{process_id}", response_model=OrderProcessListResponse)
async def update_order_process(
    process_id: int,
    data: OrderProcessUpdate,
    db: AsyncSession = Depends(get_async_db),
    _user: User = Depends(require_permission("outsource_manage")),
) -> OrderProcessListResponse:
    """更新订单外发工序（计划时间/工序类型/备注）。"""
    async with db_transaction(db):
        item = await outsource_service.update_order_process(
            db, process_id, data.model_dump(exclude_unset=True),
        )
    return OrderProcessListResponse(data=[item], total=1)


@router.post("/processes/{process_id}/ship", response_model=OrderProcessListResponse)
async def ship_order_process(
    process_id: int,
    data: OrderProcessShip,
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(require_permission("outsource_ship")),
) -> OrderProcessListResponse:
    """发货外发工序：录入发货数量，状态 pending → shipped。"""
    async with db_transaction(db):
        item = await outsource_service.ship_order_process(
            db, process_id, shipped_quantity=data.shipped_quantity, username=user.username,
        )
    return OrderProcessListResponse(data=[item], total=1)


@router.post("/processes/{process_id}/receive", response_model=OrderProcessListResponse)
async def receive_order_process(
    process_id: int,
    data: OrderProcessReceive | None = None,
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(require_permission("outsource_receive")),
) -> OrderProcessListResponse:
    """确认收货外发工序：状态 shipped → received。收货数量可选，缺省等于发货数量。"""
    async with db_transaction(db):
        item = await outsource_service.receive_order_process(
            db, process_id, username=user.username,
            received_quantity=data.received_quantity if data else None,
        )
    return OrderProcessListResponse(data=[item], total=1)


@router.post("/orders/{order_id}/processes/ship-batch", response_model=OrderProcessListResponse)
async def ship_order_processes_batch(
    order_id: int,
    data: OrderProcessShipBatch,
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(require_permission("outsource_ship")),
) -> OrderProcessListResponse:
    """批量发货（单事务原子）：一次请求完成多道工序发货，任一条失败整批回滚。"""
    async with db_transaction(db):
        items = await outsource_service.ship_order_processes_batch(
            db, order_id,
            [(i.process_id, i.quantity) for i in data.items],
            username=user.username,
        )
    return OrderProcessListResponse(data=items, total=len(items))


@router.get("/processes/shippable", response_model=list[ShippableProcessItem])
async def list_shippable_processes(
    db: AsyncSession = Depends(get_async_read_db),
    _user: User = Depends(require_permission("outsource_ship")),
) -> list[ShippableProcessItem]:
    """跨全部湖北订单聚合待发货工序（批量发货面板数据源）。"""
    items = await outsource_service.list_shippable_processes(db)
    return [ShippableProcessItem(**it) for it in items]


@router.post("/processes/ship-multi", response_model=OrderProcessListResponse)
async def ship_processes_multi(
    data: ShipProcessMulti,
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(require_permission("outsource_ship")),
) -> OrderProcessListResponse:
    """跨订单批量发货（单事务原子）：一次请求完成多道工序发货，任一条失败整批回滚。"""
    async with db_transaction(db):
        items = await outsource_service.ship_processes_multi(
            db, [(i.process_id, i.quantity) for i in data.items], username=user.username,
        )
    return OrderProcessListResponse(data=items, total=len(items))


@router.post("/orders/{order_id}/processes/receive-batch", response_model=OrderProcessListResponse)
async def receive_order_processes_batch(
    order_id: int,
    data: OrderProcessReceiveBatch,
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(require_permission("outsource_receive")),
) -> OrderProcessListResponse:
    """批量确认收货（单事务原子）：一次请求完成多道工序收货，缺省按剩余待收数量。"""
    async with db_transaction(db):
        items = await outsource_service.receive_order_processes_batch(
            db, order_id,
            [(i.process_id, i.quantity) for i in data.items],
            username=user.username,
        )
    return OrderProcessListResponse(data=items, total=len(items))


@router.delete("/processes/{process_id}", response_model=OrderActionResponse)
async def delete_order_process(
    process_id: int,
    db: AsyncSession = Depends(get_async_db),
    _user: User = Depends(require_permission("outsource_manage")),
) -> OrderActionResponse:
    """删除订单外发工序。"""
    async with db_transaction(db):
        await outsource_service.delete_order_process(db, process_id)
    return OrderActionResponse(success=True, message="外发工序已删除")


# ==================== 湖北 SKU 搜索 / 未到货明细 ====================

@router.get("/products/search", response_model=list[HubeiProductSearchItem])
async def search_hubei_products(
    q: str = Query('', max_length=100, description="搜索关键词"),
    db: AsyncSession = Depends(get_async_read_db),
    _user: User = Depends(require_permission("outsource_view")),
) -> list[HubeiProductSearchItem]:
    """搜索工厂=湖北 的 SKU（工序预设页搜索框数据源）。

    与 /product 的工厂标记联动：标记为湖北的 SKU 自动成为 presets 搜索候选。
    """
    items = await outsource_service.search_hubei_products(db, q)
    return [HubeiProductSearchItem(**it) for it in items]


@router.get("/unshipped", response_model=list[UnshippedProcessItem])
async def list_unshipped_processes(
    db: AsyncSession = Depends(get_async_read_db),
    _user: User = Depends(require_permission("outsource_view")),
) -> list[UnshippedProcessItem]:
    """跨全部湖北订单聚合未发完工序明细（导出/打印未到货清单）。"""
    items = await outsource_service.list_unshipped_processes(db)
    return [UnshippedProcessItem(**it) for it in items]


# ==================== 外发发货单（一键发货工作流） ====================

@router.post("/shipments", response_model=ShipmentResponse)
async def create_shipment(
    data: ShipmentCreate,
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(require_permission("outsource_ship")),
) -> ShipmentResponse:
    """一键发货：按订单生成发货单（贝乐用户端「待收货」订单）并逐工序发货。

    单事务原子：任一工序发货失败整批回滚。发货完成后向 outsource_receive
    权限账号派发「新发货单待收货」通知。
    """
    async with db_transaction(db):
        result = await outsource_service.create_shipment(
            db, data.order_id,
            [(i.process_id, i.quantity) for i in data.items],
            username=user.username,
        )
    return ShipmentResponse(**result)


@router.post("/shipments/batch", response_model=ShipmentBatchResponse)
async def create_shipments_batch(
    data: ShipmentBatchCreate,
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(require_permission("outsource_ship")),
) -> ShipmentBatchResponse:
    """批量发货（多订单一次性）：每个订单生成一张发货单，单事务原子。

    orders: [{order_id, items:[{process_id, quantity}]}, ...]。
    任一订单发货失败整批回滚。每订单发货单独立、customer 独立，确认收货仍按单张发货单闭环。
    """
    async with db_transaction(db):
        results = await outsource_service.create_shipments_batch(
            db,
            [(o.order_id, [(i.process_id, i.quantity) for i in o.items]) for o in data.orders],
            username=user.username,
        )
    return ShipmentBatchResponse(
        success=True,
        data=[ShipmentResponse.model_validate(r) for r in results],
        total=len(results),
        message=f'已生成 {len(results)} 张发货单',
    )


@router.post("/shipments/merged", response_model=ShipmentResponse)
async def create_merged_shipment(
    data: ShipmentMergeCreate,
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(require_permission("outsource_ship")),
) -> ShipmentResponse:
    """合并发货：把跨订单/跨客户的多道工序合并生成一张发货单（单事务原子）。

    items: [{process_id, quantity}]，不限定订单归属；发货单 order_id/customer 置空，
    明细行仍记录各工序。任一工序发货失败整批回滚，成功后派发「待收货」通知（无客户名）。
    """
    async with db_transaction(db):
        result = await outsource_service.create_merged_shipment(
            db,
            [(i.process_id, i.quantity) for i in data.items],
            username=user.username,
        )
    return ShipmentResponse(**result)


@router.get("/shipments", response_model=ShipmentListResponse)
async def list_shipments(
    status: str | None = Query(None, description="状态筛选：shipped=待收货 / received=已完成"),
    page: int = Query(1, ge=1, description="页码"),
    per_page: int = Query(50, ge=1, le=500, description="每页数量"),
    db: AsyncSession = Depends(get_async_read_db),
    _user: User = Depends(require_permission("outsource_view")),
) -> ShipmentListResponse:
    """发货单列表（待收货/已完成筛选 + 计数横幅）。"""
    result = await outsource_service.list_shipments(
        db, status=status, page=page, per_page=per_page,
    )
    return ShipmentListResponse(
        data=result['items'],
        total=result['total'],
        page=result['page'],
        per_page=result['per_page'],
        shipped_count=result['shipped_count'],
        received_count=result['received_count'],
    )


@router.get("/shipments/{shipment_id}", response_model=ShipmentResponse)
async def get_shipment(
    shipment_id: int,
    db: AsyncSession = Depends(get_async_read_db),
    _user: User = Depends(require_permission("outsource_view")),
) -> ShipmentResponse:
    """发货单明细（SKU + 工序 + 发货/收货数量）。"""
    result = await outsource_service.get_shipment(db, shipment_id)
    if not result:
        raise NotFoundError('发货单不存在')
    return ShipmentResponse(**result)


@router.post("/shipments/{shipment_id}/receive", response_model=ShipmentReceiveResponse)
async def receive_shipment(
    shipment_id: int,
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(require_permission("outsource_receive")),
) -> ShipmentReceiveResponse:
    """确认收货（贝乐账号）：发货单状态 shipped → received，闭环。幂等。"""
    async with db_transaction(db):
        result = await outsource_service.receive_shipment(
            db, shipment_id, username=user.username,
        )
    return ShipmentReceiveResponse(**result)
