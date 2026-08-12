"""
湖北外发 API 端点

职责：
- 湖北工厂订单列表（复用 beile-list 逻辑，强制 factory=湖北）
- SKU 工序预设 CRUD（按产品固定配置外发工序类型）
- 订单外发工序管理（计划/实际完成时间、开始/完成、按预设生成）
- 订单进度看板（时间轴/进度条数据）

权限：
- outsource_view：查看订单/工序/看板
- outsource_manage：工序预设 CRUD + 工序状态管理
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.database import get_async_db, get_async_read_db
from fastapi_app.core.deps import require_permission
from fastapi_app.schemas.order import OrderListResponse
from fastapi_app.schemas.outsource import (
    GenerateProcessResponse,
    KanbanResponse,
    OrderActionResponse,
    OrderProcessListResponse,
    OrderProcessUpdate,
    ProcessTypeBatchCreate,
    ProcessTypeCreate,
    ProcessTypeListResponse,
    ProcessTypeResponse,
    ProcessTypeUpdate,
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
    process_status: str | None = Query(
        None, description="外发工序状态筛选：pending(待开始)/in_progress(进行中)/completed(已完成)"
    ),
    db: AsyncSession = Depends(get_async_read_db),
    _user: User = Depends(require_permission("outsource_view")),
) -> OrderListResponse:
    """湖北工厂订单+备货合并列表（强制 factory=湖北，忽略前端传参）。"""
    result = await outsource_service.list_outsource_orders(
        db, page=page, per_page=per_page, customer=customer,
        process_status=process_status,
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
    try:
        pt = await outsource_service.create_process_type(
            db, data.model_dump(), username=user.username,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return ProcessTypeResponse(**pt)


@router.post("/process-types/batch", response_model=GenerateProcessResponse)
async def batch_create_process_types(
    data: ProcessTypeBatchCreate,
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(require_permission("outsource_manage")),
) -> GenerateProcessResponse:
    """为一个 SKU 批量添加多个工序预设（自由输入工序名称，幂等去重）。"""
    try:
        result = await outsource_service.batch_create_process_types(
            db, product_id=data.product_id,
            process_types=data.process_types, username=user.username,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return GenerateProcessResponse(
        success=True,
        message=f"已添加 {result['created']} 道工序，跳过 {result['skipped']} 道重复工序",
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
    try:
        pt = await outsource_service.update_process_type(
            db, pt_id, data.model_dump(exclude_unset=True),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return ProcessTypeResponse(**pt)


@router.delete("/process-types/{pt_id}", response_model=OrderActionResponse)
async def delete_process_type(
    pt_id: int,
    db: AsyncSession = Depends(get_async_db),
    _user: User = Depends(require_permission("outsource_manage")),
) -> OrderActionResponse:
    """删除 SKU 外发工序预设。"""
    try:
        await outsource_service.delete_process_type(db, pt_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return OrderActionResponse(success=True, message="工序预设已删除")


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


@router.post("/orders/{order_id}/processes/generate", response_model=GenerateProcessResponse)
async def generate_order_processes(
    order_id: int,
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(require_permission("outsource_manage")),
) -> GenerateProcessResponse:
    """按 SKU 预设为订单生成外发工序（返单自动带出的手动触发）。"""
    try:
        result = await outsource_service.generate_order_processes(
            db, order_id, username=user.username,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
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
    try:
        item = await outsource_service.update_order_process(
            db, process_id, data.model_dump(exclude_unset=True),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return OrderProcessListResponse(data=[item], total=1)


@router.post("/processes/{process_id}/start", response_model=OrderProcessListResponse)
async def start_order_process(
    process_id: int,
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(require_permission("outsource_manage")),
) -> OrderProcessListResponse:
    """开始外发工序：记录实际开始时间。"""
    try:
        item = await outsource_service.start_order_process(
            db, process_id, username=user.username,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return OrderProcessListResponse(data=[item], total=1)


@router.post("/processes/{process_id}/complete", response_model=OrderProcessListResponse)
async def complete_order_process(
    process_id: int,
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(require_permission("outsource_manage")),
) -> OrderProcessListResponse:
    """完成外发工序：记录实际完成时间。"""
    try:
        item = await outsource_service.complete_order_process(
            db, process_id, username=user.username,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return OrderProcessListResponse(data=[item], total=1)


@router.delete("/processes/{process_id}", response_model=OrderActionResponse)
async def delete_order_process(
    process_id: int,
    db: AsyncSession = Depends(get_async_db),
    _user: User = Depends(require_permission("outsource_manage")),
) -> OrderActionResponse:
    """删除订单外发工序。"""
    try:
        await outsource_service.delete_order_process(db, process_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return OrderActionResponse(success=True, message="外发工序已删除")


# ==================== 进度看板 ====================

@router.get("/kanban", response_model=KanbanResponse)
async def get_kanban(
    page: int = Query(1, ge=1, description="页码"),
    per_page: int = Query(20, ge=1, le=100, description="每页数量"),
    customer: str | None = Query(None, description="客户名筛选"),
    db: AsyncSession = Depends(get_async_read_db),
    _user: User = Depends(require_permission("outsource_view")),
) -> KanbanResponse:
    """订单进度看板：湖北工厂订单 + 外发工序时间轴/进度。"""
    result = await outsource_service.get_kanban(
        db, page=page, per_page=per_page, customer=customer,
    )
    return KanbanResponse(data=result['items'], total=result['total'],
                          page=result['page'], per_page=result['per_page'])
