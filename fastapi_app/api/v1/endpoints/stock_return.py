"""
退货管理 API 端点

职责：
- 提供销售退货的查询 / 创建 / 删除接口
- 业务规则（防超退、订单抵扣出货禁退、库存回补、订单状态重算、
  流水与领域事件）全部在 services/stock_return_service.py，本层只做鉴权与事务编排
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.database import get_async_db, get_async_read_db
from fastapi_app.core.deps import require_permission
from fastapi_app.core.exceptions import db_transaction
from fastapi_app.schemas.stock import StockActionResponse, StockListResponse
from fastapi_app.schemas.stock_return import NameOption, StockReturnCreate
from fastapi_app.services.stock_common import business_now
from fastapi_app.services.stock_inventory_service import get_stockreturns
from fastapi_app.services.stock_return_service import cancel_stockreturn, create_stockreturn
from fastapi_app.shared_models import Order, Product, StockOut, StockReturn, User

logger = logging.getLogger(__name__)
router = APIRouter()

# 新增退货弹窗的产品候选窗口大小（与前端约定）
PRODUCT_OPTIONS_LIMIT = 500


@router.get('/product-options', response_model=list[NameOption])
async def list_product_options(
    customer: str = Query(..., min_length=1, description='客户名称（产品随客户过滤）'),
    db: AsyncSession = Depends(get_async_read_db),
    _user: User = Depends(require_permission('stock_return_manage')),
) -> list[NameOption]:
    """获取指定客户的产品名称候选（新增退货弹窗，客户/产品均硬性必填）。

    产品集合 = 该客户「订单 ∪ 出货」中出现过的产品（去重、按名称排序）：
    退货是客户把与本公司业务往来的货退回，产品范围必须限定在该客户名下，
    而非全量产品字典。

    为什么模块内自建而不复用 /products/list：后者要求 product_manage，
    只授退货权限的用户（迁移 069 最小授权模型）会 403——与
    /customers/active-names 放宽为仅登录的先例同因，本端点按退货模块
    自身的 manage 权限门控，随弹窗入口一起出现。

    Args:
        customer: 客户名称（精确匹配，来自客户字典）。
        db: 异步数据库会话（只读副本）。
        _user: 当前登录用户（仅需通过权限校验）。

    Returns:
        list[NameOption]: 该客户关联的产品 id/name 列表（按名称排序）。
    """
    name = customer.strip()
    if not name:
        raise HTTPException(status_code=422, detail='客户名称不能为空')
    result = await db.execute(
        select(Product.id, Product.name)
        .where(
            or_(
                Product.id.in_(
                    select(Order.product_id).where(
                        Order.customer == name, Order.product_id.isnot(None)
                    )
                ),
                Product.id.in_(
                    select(StockOut.product_id).where(StockOut.customer == name)
                ),
            )
        )
        .order_by(Product.name)
        .limit(PRODUCT_OPTIONS_LIMIT)
    )
    return [NameOption(id=row[0], name=row[1]) for row in result.all()]


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
            db, product_id=data.product_id, quantity=data.quantity,
            return_date_str=return_date, reason=data.reason, note=data.note,
            customer=data.customer, request_id=data.request_id,
        )
    logger.info('退货创建成功：%s（product_id=%s，数量=%s）',
                result['return_no'], data.product_id, data.quantity)
    return StockActionResponse(success=True, message=f"退货添加成功！单号 {result['return_no']}")


@router.delete('/{return_id}', response_model=StockActionResponse)
async def cancel_stock_return(
    return_id: int,
    db: AsyncSession = Depends(get_async_db),
    _user: User = Depends(require_permission('stock_return_manage')),
) -> StockActionResponse:
    """取消退货记录（P1-① 软取消：记录保留，库存对称扣回、订单状态重算）。

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
        await cancel_stockreturn(db, stockreturn_id=return_id)
    return StockActionResponse(success=True, message='退货取消成功！库存已扣回')
