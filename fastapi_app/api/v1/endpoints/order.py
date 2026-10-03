"""
订单管理 API 端点

职责：
- 提供订单的增删改查接口
- 处理订单审批流程（创建、取消）
- 管理订单批次号与抵扣备货数量
- 协调缓存失效与领域事件发布
"""
import logging
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.backup_progress import _sanitize_error
from fastapi_app.core.cache import CacheDomain
from fastapi_app.core.cache_invalidation import InvalidationStrategy, cache_mgr
from fastapi_app.core.config import settings
from fastapi_app.core.database import get_async_db, get_async_read_db
from fastapi_app.core.deps import require_permission
from fastapi_app.core.domain_events import DomainEvent, DomainEventType
from fastapi_app.core.domain_events import publish as publish_domain_event
from fastapi_app.core.exceptions import AppError, NotFoundError, db_transaction
from fastapi_app.core.response import success_response
from fastapi_app.schemas.order import (
    ApprovalCancelResponse,
    ApprovalListResponse,
    OrderActionResponse,
    OrderCreate,
    OrderDetailResponse,
    OrderListResponse,
    OrderUpdate,
)
from fastapi_app.services import order_batch_service, order_crud, order_service
from fastapi_app.services.order.unified import get_unified_records
from fastapi_app.services.order_service import PermissionDeniedError
from fastapi_app.shared_models import Order, User
from fastapi_app.shared_models.order import VALID_ORDER_STATUSES

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/list", response_model=OrderListResponse)
async def list_orders(
    page: int = Query(1, ge=1, description="页码"),
    per_page: int = Query(50, ge=1, le=500, description="每页数量"),
    customer: str | None = Query(None, description="客户名筛选"),
    product_id: int | None = Query(None, description="产品ID筛选"),
    status: str | None = Query(None, description="状态筛选"),
    start_date: str | None = Query(None, description="开始日期筛选(YYYY-MM-DD)"),
    end_date: str | None = Query(None, description="结束日期筛选(YYYY-MM-DD)"),
    factory: str | None = Query(None, description="工厂筛选：东莞/湖北"),
    db: AsyncSession = Depends(get_async_read_db),
    user: User = Depends(require_permission("order_manage")),
) -> OrderListResponse:
    """获取订单列表（支持分页和多维度筛选）。

    缓存由 service 层 @cache_result 管理，端点层不重复缓存。

    工厂权限隔离：当 current_user.factory 非空且非超管时，强制按本厂过滤，
    前端传入的 factory 参数被忽略；管理员（factory 为空或 is_super=true）可手动筛选。

    Args:
        page: 页码，从 1 开始。
        per_page: 每页数量，1-500。
        customer: 客户名筛选关键字。
        product_id: 产品 ID 筛选。
        status: 订单状态筛选。
        start_date: 开始日期（YYYY-MM-DD）。
        end_date: 结束日期（YYYY-MM-DD）。
        factory: 工厂筛选（东莞/湖北）。受权限隔离约束。
        db: 异步数据库会话（只读副本）。
        user: 当前登录用户，用于工厂权限隔离。

    Returns:
        OrderListResponse: 包含订单列表和分页信息的响应。
    """
    # 权限隔离：绑定工厂的非超管用户强制按本厂过滤，忽略前端传参
    if user.factory and not user.is_super:
        factory = user.factory

    try:
        result = await order_service.get_orders(db, page=page, per_page=per_page,
                                                customer=customer, product_id=product_id,
                                                status=status,
                                                start_date=start_date, end_date=end_date,
                                                factory=factory)
    except AppError:
        raise  # 业务异常（如非法日期 400）交由全局 handler，不被吞为 500
    except (SQLAlchemyError, OSError) as e:
        # 仅捕获基础设施异常并转 500；编程错误（KeyError 等）自然抛给全局 handler 暴露真实堆栈
        logger.exception("[OrderList] 获取订单列表失败: %s", e)
        raise HTTPException(status_code=500, detail=_sanitize_error(f"获取订单列表失败: {e}")) from e

    return OrderListResponse(data=result['items'], total=result['total'],
                             page=result['page'], per_page=result['per_page'])


@router.get("/beile-list", response_model=OrderListResponse)
async def list_beile_orders(
    page: int = Query(1, ge=1, description="页码"),
    per_page: int = Query(50, ge=1, le=500, description="每页数量"),
    customer: str | None = Query(None, description="客户名筛选"),
    confirm_status: str | None = Query(None, description="湖北订单确认状态筛选：unconfirmed=未确认 / confirmed=已确认"),
    product: str | None = Query(None, description="产品关键字筛选（匹配产品名称或条码）"),
    db: AsyncSession = Depends(get_async_read_db),
    _user: User = Depends(require_permission("beile_order_view")),
) -> OrderListResponse:
    """获取湖北工厂订单+备货合并列表。

    专供湖北订单页面使用，权限要求 beile_order_view（而非 order_manage）。
    强制 factory='湖北'，忽略前端传参，确保数据隔离。
    同时包含订单（Order）和备货（StockIn）记录，通过 record_type 字段区分。
    confirm_status 生效时订单与备货均按各自 confirmed_at 过滤后合并返回。
    product 关键字在服务端过滤（订单按 SKU 名称/条码、备货按产品名称/条码），
    避免前端「先分页后过滤」漏掉后续页命中数据。
    """
    result = await order_crud.get_beile_orders_with_stockins(
        db, page=page, per_page=per_page, customer=customer, factory='湖北',
        confirm_status=confirm_status, product_kw=product,
    )

    return OrderListResponse(data=result['items'], total=result['total'],
                             page=result['page'], per_page=result['per_page'],
                             unconfirmed_count=result['unconfirmed_count'])


@router.post("/{order_id}/confirm", response_model=OrderActionResponse)
async def confirm_beile_order(
    order_id: int,
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(require_permission("beile_order_confirm")),
) -> OrderActionResponse:
    """确认湖北订单（beile-order 页面）。

    仅允许确认 factory=湖北 的订单，幂等（已确认直接返回成功）。
    """
    async with db_transaction(db):
        result = await order_crud.confirm_beile_order(db, order_id, user)
    # 事务提交后再失效缓存，避免并发请求用未提交前数据回填缓存
    await cache_mgr.invalidate(
        InvalidationStrategy.DOMAIN, CacheDomain.ORDER | CacheDomain.REPORT)
    await cache_mgr.invalidate(InvalidationStrategy.PURCHASE)
    return OrderActionResponse(**result)


@router.post("/stockin/{stockin_id}/confirm", response_model=OrderActionResponse)
async def confirm_beile_stockin(
    stockin_id: int,
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(require_permission("beile_order_confirm")),
) -> OrderActionResponse:
    """确认湖北备货（beile-order 页面，与订单确认流程对齐）。

    仅允许确认 factory=湖北 的备货记录，幂等（已确认直接返回成功）。
    """
    async with db_transaction(db):
        result = await order_crud.confirm_beile_stockin(db, stockin_id, user)
    # 事务提交后再失效缓存，避免并发请求用未提交前数据回填缓存
    await cache_mgr.invalidate(
        InvalidationStrategy.DOMAIN, CacheDomain.ORDER | CacheDomain.REPORT)
    await cache_mgr.invalidate(InvalidationStrategy.PURCHASE)
    return OrderActionResponse(**result)


@router.get("/my-approvals", response_model=ApprovalListResponse)
async def my_approvals(
    db: AsyncSession = Depends(get_async_read_db),
    user: User = Depends(require_permission("order_manage")),
) -> ApprovalListResponse:
    """查看当前用户提交的审批请求列表。

    Args:
        db: 异步数据库会话（只读副本）。
        user: 当前登录用户，用于筛选其提交的审批。

    Returns:
        ApprovalListResponse: 包含审批列表和总数的响应。
    """
    approvals = await order_service.get_my_approvals(db, user)
    return ApprovalListResponse(data=approvals, total=len(approvals))


@router.get("/records", response_model=OrderListResponse)
async def list_unified_records(
    page: int = Query(1, ge=1, description="页码"),
    per_page: int = Query(50, ge=1, le=500, description="每页数量"),
    record_type: Literal['all', 'order', 'stockin'] = Query(
        'all', description="记录类型：all=全部 / order=订单 / stockin=备货"),
    product: str | None = Query(None, description="产品关键字（匹配名称或条码）"),
    order_no: str | None = Query(None, description="单号关键字"),
    customer: str | None = Query(None, description="客户名筛选"),
    status: str | None = Query(None, description="订单状态筛选"),
    factory: str | None = Query(None, description="工厂筛选：东莞/湖北"),
    start_date: str | None = Query(None, description="开始日期筛选(YYYY-MM-DD)"),
    end_date: str | None = Query(None, description="结束日期筛选(YYYY-MM-DD)"),
    keyword: str | None = Query(None, description="搜索框 OR 关键字：单号/客户/产品名/条码"),
    db: AsyncSession = Depends(get_async_read_db),
    user: User = Depends(require_permission("order_manage")),
) -> OrderListResponse:
    """获取订单+备货合并记录列表（只读，支持分页和多维度筛选）。

    订单与备货统一按 sort_date DESC NULLS LAST, record_type, source_id 稳定排序，
    通过 record_type 字段区分（order=订单 / stockin=备货）。
    工厂权限隔离：非超管且绑定工厂时强制按本厂过滤，前端传参被忽略。
    状态筛选仅对订单行生效；record_type 非法值由 FastAPI 以 422 拒绝。
    """
    # 状态白名单校验：非法状态直接 400，避免静默返回空列表
    if status and status not in VALID_ORDER_STATUSES:
        valid = "、".join(sorted(VALID_ORDER_STATUSES))
        raise HTTPException(status_code=400, detail=f"无效的订单状态：{status}，合法值：{valid}")

    # 权限隔离：绑定工厂的非超管用户强制按本厂过滤，忽略前端传参
    if user.factory and not user.is_super:
        factory = user.factory

    try:
        result = await get_unified_records(
            db, page=page, per_page=per_page, record_type=record_type,
            product_kw=product, order_no_kw=order_no, customer=customer,
            status=status, factory=factory,
            start_date=start_date, end_date=end_date,
            keyword=keyword,
        )
    except AppError:
        raise  # 业务异常（如非法日期 400）交由全局 handler，不被吞为 500
    except (SQLAlchemyError, OSError) as e:
        logger.exception("[OrderRecords] 获取合并记录失败: %s", e)
        raise HTTPException(status_code=500, detail=_sanitize_error(f"获取合并记录失败: {e}")) from e

    return OrderListResponse(data=result['items'], total=result['total'],
                             page=result['page'], per_page=result['per_page'])


@router.get("/{order_id}", response_model=OrderDetailResponse)
async def get_order(
    order_id: int,
    db: AsyncSession = Depends(get_async_read_db),
    _user: User = Depends(require_permission("order_manage")),
) -> dict[str, Any]:
    """获取单个订单详情。

    Args:
        order_id: 订单 ID。
        db: 异步数据库会话（只读副本）。
        _user: 当前登录用户（仅需通过权限校验）。

    Returns:
        OrderDetailResponse: 订单详情。

    Raises:
        HTTPException: 订单不存在时抛出 404。
    """
    # 权限隔离：与列表端点（list_orders）同口径 —— 绑定工厂的非超管用户只能看本厂订单。
    # 隔离下推到 service 的 WHERE，查不到即 404，不暴露"该订单存在但不属于你"。
    scoped_factory = _user.factory if (_user.factory and not _user.is_super) else None
    result = await order_service.get_order_by_id(db, order_id, factory=scoped_factory)
    if not result:
        logger.info("订单详情查询失败：order_id=%s 不存在", order_id)
        raise HTTPException(status_code=404, detail="订单不存在")
    return result


@router.post("/create", response_model=OrderActionResponse)
async def create_order(
    data: OrderCreate,
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(require_permission("order_manage")),
) -> OrderActionResponse:
    """创建订单。

    事务提交后再失效缓存，避免并发请求用旧数据回填缓存。

    Args:
        data: 订单创建参数（产品、数量、客户、类型等）。
        db: 异步数据库会话（读写主库）。
        user: 当前登录用户，作为订单创建人。

    Returns:
        OrderActionResponse: 包含成功标志和提示消息的响应。
    """
    async with db_transaction(db):
        await order_service.create_order(
            db, product_id=data.product_id, quantity=data.quantity,
            customer=data.customer, note=data.note or '', current_user=user,
        )
    # 事务提交后再失效缓存，避免并发请求用旧数据回填缓存
    await cache_mgr.invalidate_dashboard()
    return OrderActionResponse(success=True, message="订单添加成功！")


@router.put("/edit/{order_id}", response_model=OrderActionResponse)
async def edit_order(
    order_id: int,
    data: OrderUpdate,
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(require_permission("order_manage")),
) -> OrderActionResponse:
    """编辑订单（管理员直接编辑，非管理员提交审批）。

    未提供的字段沿用订单原值，实现部分更新语义。

    Args:
        order_id: 订单 ID。
        data: 订单更新参数（仅包含需要修改的字段）。
        db: 异步数据库会话（读写主库）。
        user: 当前登录用户，用于权限判断和审批流程。

    Returns:
        OrderActionResponse: 包含成功标志和提示消息的响应。

    Raises:
        HTTPException: 订单不存在时抛出 404。
    """
    order = await db.get(Order, order_id)
    if not order:
        logger.info("编辑订单失败：order_id=%s 不存在", order_id)
        raise HTTPException(status_code=404, detail="订单不存在")

    # 未传入的字段沿用原值，实现部分更新
    # TODO(multi-sku-order): 读取 order.quantity 在多 SKU 下为首 item 兼容值，待后续 spec 改造为按 OrderItem 维度。
    quantity = data.quantity if data.quantity is not None else order.quantity
    customer = data.customer if data.customer is not None else order.customer
    note = data.note if data.note is not None else (order.note or '')

    async with db_transaction(db):
        result = await order_service.update_order(
            db, order_id=order_id, quantity=quantity,
            customer=customer, note=note, current_user=user
        )
    await cache_mgr.invalidate_dashboard()
    return OrderActionResponse(success=result['success'], message=result['message'])


@router.delete("/delete/{order_id}", response_model=OrderActionResponse)
async def delete_order(
    order_id: int,
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(require_permission("order_manage")),
) -> OrderActionResponse:
    """删除订单（管理员直接删除，非管理员提交审批）。

    事务模式：db_transaction + error_map（TRANSACTION_BOUNDARY_GUIDE §2.3：
    端点层无 commit 例外）。提交在响应返回前完成，200 与「已落库」保持一致；
    IntegrityError→409 经 error_map 映射（端点无需手动 commit/catch），
    缓存失效与实时广播由 service 注册的 post-commit 回调在提交成功后自动执行。

    Args:
        order_id: 订单 ID。
        db: 异步数据库会话（读写主库）。
        user: 当前登录用户，用于权限判断。

    Returns:
        OrderActionResponse: 包含成功标志和提示消息的响应。

    Raises:
        HTTPException: 关联数据冲突返回 409；权限不足返回 403；
            参数错误返回 400；订单删除前备份失败或数据库异常返回 500。
    """
    def _to_409(e: Exception) -> HTTPException:
        logger.warning("删除订单完整性约束冲突: %s", e)
        return HTTPException(status_code=409, detail='订单存在关联数据，无法删除')

    def _to_403(e: Exception) -> HTTPException:
        return HTTPException(status_code=403, detail=settings.sanitize_business_error(e))

    def _backup_failed(e: Exception) -> HTTPException:
        logger.error("删除订单备份失败: %s", e, exc_info=True)
        return HTTPException(status_code=500, detail='订单删除前备份失败，操作已回滚，请稍后重试')

    def _db_failed(e: Exception) -> HTTPException:
        logger.error("删除订单数据库异常: %s", e, exc_info=True)
        return HTTPException(status_code=500, detail='数据库操作失败，删除已回滚')

    async with db_transaction(db, error_map={
        # 注册顺序即命中顺序：IntegrityError 是 SQLAlchemyError 子类，必须在前
        IntegrityError: _to_409,
        PermissionDeniedError: _to_403,
        # NotFoundError 保持既有行为映射为 400（service 实际抛的是 ValueError）
        NotFoundError: lambda e: HTTPException(status_code=400, detail=str(e)),
        OSError: _backup_failed,
        SQLAlchemyError: _db_failed,
    }):
        result = await order_service.delete_order(db, order_id, user)

    await cache_mgr.invalidate_dashboard()
    # 领域事件：ORDER_DELETED 在事务提交后发布（订阅者使用独立 session，需可见已提交变更）；
    # 面向前端的实时广播已由 service 的 schedule_post_commit_event 注册并执行。
    if result.get('success'):
        try:
            await publish_domain_event(DomainEvent(
                event_type=DomainEventType.ORDER_DELETED,
                domain='order',
                payload={'order_id': order_id},
            ))
        except Exception:  # defensive: 领域事件发布失败不影响删除操作结果
            logger.warning("ORDER_DELETED 领域事件发布失败", exc_info=True)
            from fastapi_app.core.metrics import DOMAIN_EVENT_PUBLISH_FAILURES
            DOMAIN_EVENT_PUBLISH_FAILURES.labels(event_type='order_deleted').inc()
    return OrderActionResponse(success=result['success'], message=result['message'])


@router.post("/cancel-approval/{approval_id}", response_model=ApprovalCancelResponse)
async def cancel_approval(
    approval_id: int,
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(require_permission("order_manage")),
) -> ApprovalCancelResponse:
    """取消审批请求（仅审批发起者或超级用户可取消）。

    Args:
        approval_id: 审批记录 ID。
        db: 异步数据库会话（读写主库）。
        user: 当前登录用户，用于权限校验。

    Returns:
        ApprovalCancelResponse: 包含成功标志和提示消息的响应。

    Raises:
        HTTPException: 权限不足时抛出 403。
    """
    try:
        async with db_transaction(db):
            await order_service.cancel_approval(db, approval_id, user)
    except PermissionDeniedError as e:
        raise HTTPException(status_code=403, detail=settings.sanitize_business_error(e)) from e
    await cache_mgr.invalidate(
        InvalidationStrategy.DOMAIN,
        CacheDomain.ORDER_AND_INVENTORY | CacheDomain.REPORT,
    )
    await cache_mgr.invalidate_dashboard()
    return ApprovalCancelResponse(success=True, message="审批请求已取消")


@router.put("/batch-no/{order_id}", response_model=OrderActionResponse)
async def update_batch_no(
    order_id: int,
    batch_no: str = Query("", max_length=100, description="批次号"),
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(require_permission("order_manage")),
) -> dict[str, Any]:
    """更新订单批次号。

    Args:
        order_id: 订单 ID。
        batch_no: 批次号，最长 100 字符。
        db: 异步数据库会话（读写主库）。
        user: 当前登录用户，作为操作人。

    Returns:
        OrderActionResponse: 包含成功标志和提示消息的响应。
    """
    async with db_transaction(db):
        await order_batch_service.update_batch_no(
            db, order_id=order_id, batch_no=batch_no,
            sync_same_batch=False, user=user,
        )
    await cache_mgr.invalidate(
        InvalidationStrategy.DOMAIN, CacheDomain.ORDER | CacheDomain.REPORT)
    await cache_mgr.invalidate_dashboard()
    return success_response(message="批次号已更新")


@router.put("/deduct/{order_id}", response_model=OrderActionResponse)
async def update_deduct_quantity(
    order_id: int,
    deduct_quantity: int = Query(..., ge=0, description="新的抵扣备货数量"),
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(require_permission("order_manage")),
) -> OrderActionResponse:
    """修改订单的抵扣备货数量。

    Args:
        order_id: 订单 ID。
        deduct_quantity: 新的抵扣备货数量，必须 >= 0。
        db: 异步数据库会话（读写主库）。
        user: 当前登录用户，用于权限校验。

    Returns:
        OrderActionResponse: 包含成功标志和提示消息的响应。

    Raises:
        HTTPException: 参数校验失败时抛出 400。
    """
    try:
        async with db_transaction(db):
            result = await order_service.update_deduct_quantity(
                db, order_id=order_id,
                new_deduct_quantity=deduct_quantity, current_user=user,
            )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=settings.sanitize_business_error(e)) from e
    await cache_mgr.invalidate_dashboard()
    return OrderActionResponse(success=True, message=result['message'])
