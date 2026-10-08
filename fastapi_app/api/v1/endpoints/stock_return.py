"""
退货管理 API 端点

职责：
- 提供销售退货的查询 / 创建 / 删除接口
- 业务规则（防超退、订单抵扣出货禁退、库存回补、订单状态重算、
  流水与领域事件）全部在 services/stock_return_service.py，本层只做鉴权与事务编排
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.database import get_async_db, get_async_read_db
from fastapi_app.core.deps import require_any_permission, require_permission
from fastapi_app.core.exceptions import db_transaction
from fastapi_app.schemas.stock import StockActionResponse, StockListResponse
from fastapi_app.schemas.stock_return import ShipmentOption, StockReturnCreate, StockReturnUpdate
from fastapi_app.services.stock_common import business_now
from fastapi_app.services.stock_inventory_service import get_stockreturn_records, get_stockreturns
from fastapi_app.services.stock_return_service import (
    cancel_stockreturn,
    create_stockreturn,
    edit_stockreturn,
    search_returnable_stockouts,
)
from fastapi_app.shared_models import StockReturn, User

logger = logging.getLogger(__name__)
router = APIRouter()

# 新增退货弹窗的产品候选窗口大小（与前端约定）
PRODUCT_OPTIONS_LIMIT = 500


@router.get('/shipment-options', response_model=list[ShipmentOption])
async def list_shipment_options(
    q: str = Query('', max_length=100, description='产品名称模糊搜索（空=最近可退明细）'),
    db: AsyncSession = Depends(get_async_read_db),
    _user: User = Depends(require_permission('stock_return_manage')),
) -> list[ShipmentOption]:
    """按产品名搜索可退的出货明细（退货单录入第二步）。

    仅列可退量 > 0 的明细；客户/订单由所选明细带出。模块内自建端点的原因
    同 /customers/active-names 先例：/products/list 要求 product_manage，
    只授退货权限的用户会 403。

    Args:
        q: 产品名称模糊关键词（空=最近可退明细）。
        db: 异步数据库会话（只读副本）。
        _user: 当前登录用户（仅需通过权限校验）。

    Returns:
        list[ShipmentOption]: 出货明细（单号/客户/产品/数量/已退/可退/日期）。
    """
    items = await search_returnable_stockouts(db, q.strip(), limit=50)
    return [ShipmentOption(**item) for item in items]


@router.get('/list', response_model=StockListResponse)
async def list_stock_returns(
    page: int = Query(1, ge=1, description='页码'),
    per_page: int = Query(50, ge=1, le=500, description='每页数量'),
    customer: str | None = Query(None, description='客户'),
    start_date: str | None = Query(None, description='开始日期'),
    end_date: str | None = Query(None, description='结束日期'),
    db: AsyncSession = Depends(get_async_read_db),
    _user: User = Depends(require_permission('stock_return_view')),
) -> StockListResponse:
    """获取退货列表（支持分页和筛选）。

    Args:
        page: 页码，从 1 开始。
        per_page: 每页数量，1-500。
        customer: 客户名筛选关键字。
        start_date: 开始日期（YYYY-MM-DD）。
        end_date: 结束日期（YYYY-MM-DD）。
        db: 异步数据库会话（只读副本）。
        _user: 当前登录用户（仅需通过权限校验）。

    Returns:
        StockListResponse: 包含退货列表和分页信息的响应。
    """
    result = await get_stockreturns(
        db, page=page, per_page=per_page, customer=customer,
        start_date=start_date, end_date=end_date,
    )
    return StockListResponse(
        data=result['items'], total=result['total'],
        page=result['page'], per_page=result['per_page'],
    )


@router.get('/records', response_model=StockListResponse)
async def list_return_records(
    nos: str = Query('', description='逗号分隔的退货单号（报表聚合行还原用）'),
    db: AsyncSession = Depends(get_async_read_db),
    _user: User = Depends(require_any_permission(
        'stock_return_view', 'stock_return_manage', 'return_edit', 'return_delete',
    )),
) -> StockListResponse:
    """按退货单号还原退货明细行（报表聚合行 → 具体记录，供行内编辑/删除）。仅 active。

    Args:
        nos: 逗号分隔的退货单号（return_no）。
        db: 只读数据库会话。
        _user: 当前登录用户（仅需通过权限校验）。

    Returns:
        StockListResponse: 匹配的退货明细行（带 id/数量/客户/日期/原因/备注等）。
    """
    items = await get_stockreturn_records(db, nos=nos)
    return StockListResponse(data=items, total=len(items), page=1, per_page=len(items))


@router.post('/create', response_model=StockActionResponse)
async def create_stock_return(
    data: StockReturnCreate,
    db: AsyncSession = Depends(get_async_db),
    _user: User = Depends(require_permission('stock_return_manage')),
) -> StockActionResponse:
    """添加退货记录（P1 按产品制：回补库存、写退货流水；不关联出货单/订单）。

    Args:
        data: 退货创建参数（产品、数量、客户、原因等）。
        db: 异步数据库会话（读写主库）。
        _user: 当前登录用户（仅需通过权限校验）。

    Returns:
        StockActionResponse: 包含成功标志、提示消息与退货单号。
    """
    # 缺省日期用业务口径（北京时间）：UTC 日期会让 00:00–08:00 的退货落到前一天
    # （business_now docstring 记录的同一坑，编号模块 2026-10-01 P0-5 修过）
    return_date = data.return_date or business_now().strftime('%Y-%m-%d')
    # error_map 兜底：并发同 request_id 时唯一索引冲突可能在 commit 期才浮现
    # （服务层 savepoint 已拦截 flush 期），两者共同保证重试风暴拿到 400 而非 500
    async with db_transaction(
        db,
        error_map={
            IntegrityError: (400, '请勿重复提交：该请求已登记过退货'),
        },
    ):
        result = await create_stockreturn(
            db, stockout_id=data.stockout_id, quantity=data.quantity,
            return_date_str=return_date, reason=data.reason, note=data.note,
            request_id=data.request_id, operator_id=_user.id,
        )
    logger.info('退货创建成功：%s（stockout_id=%s，数量=%s）',
                result['return_no'], data.stockout_id, data.quantity)
    return StockActionResponse(success=True, message=f"退货添加成功！单号 {result['return_no']}")


@router.put('/{return_id}', response_model=StockActionResponse)
async def edit_stock_return(
    return_id: int,
    data: StockReturnUpdate,
    db: AsyncSession = Depends(get_async_db),
    # 报表流水行内编辑（迁移 079）：return_edit 或页面级 stock_return_manage
    _user: User = Depends(require_any_permission('stock_return_manage', 'return_edit')),
) -> StockActionResponse:
    """编辑退货记录（单事务内「取消原退货 + 按同一出货明细重建」，原子）。

    未提供的字段沿用原值。新记录带新的 SR 单号，旧记录**被删除**
    （2026-10-09 起取消即删行，不再软取消保留）；库存、出货已退量、订单状态按净变化对称调整。

    Args:
        return_id: 退货记录 ID。
        data: 退货更新参数（仅包含需要修改的字段）。
        db: 异步数据库会话（读写主库）。
        _user: 当前登录用户（仅需通过权限校验）。

    Returns:
        StockActionResponse: 包含成功标志、提示消息与新退货单号。

    Raises:
        HTTPException: 退货记录不存在时抛出 404。
    """
    stock_return = await db.get(StockReturn, return_id)
    if not stock_return:
        logger.info('编辑退货失败：return_id=%s 不存在', return_id)
        raise HTTPException(status_code=404, detail='退货记录不存在')
    async with db_transaction(
        db,
        error_map={IntegrityError: (400, '请勿重复提交：该请求已登记过退货')},
    ):
        result = await edit_stockreturn(
            db, return_id=return_id, quantity=data.quantity,
            return_date_str=data.return_date, reason=data.reason, note=data.note,
            operator_id=_user.id,
        )
    logger.info('退货编辑成功：%s（return_id=%s）', result['return_no'], return_id)
    return StockActionResponse(success=True, message=f"退货修改成功！单号 {result['return_no']}")


@router.delete('/{return_id}', response_model=StockActionResponse)
async def cancel_stock_return(
    return_id: int,
    db: AsyncSession = Depends(get_async_db),
    # 报表流水行内删除（迁移 079）：return_delete 或页面级 stock_return_manage
    _user: User = Depends(require_any_permission('stock_return_manage', 'return_delete')),
) -> StockActionResponse:
    """取消退货记录（回冲库存/订单状态后**删除该行**，记录不留存）。

    Args:
        return_id: 退货记录 ID。
        db: 异步数据库会话（读写主库）。
        _user: 当前登录用户（仅需通过权限校验）。

    Returns:
        StockActionResponse: 包含成功标志和提示消息。

    Raises:
        HTTPException: 退货记录不存在时抛出 404。
    """
    stock_return = await db.get(StockReturn, return_id)
    if not stock_return:
        logger.info('取消退货失败：return_id=%s 不存在', return_id)
        raise HTTPException(status_code=404, detail='退货记录不存在')
    async with db_transaction(db):
        await cancel_stockreturn(db, stockreturn_id=return_id, operator_id=_user.id)
    return StockActionResponse(success=True, message='退货已删除！库存已扣回')
