"""库存 / 退货 / 批量提交端点共用的工厂隔离闸门。

2026-10-18 审计 P0-2 引入（原 stock.py::_assert_product_factory_scoped）；
2026-10-19 OCR 第三轮 H1 抽到 shared：aux 批量端点此前无任何工厂校验，
且 stock_return.py 在函数体内 import 端点私有 helper（分层倒挂），统一
收敛到本模块做单一真相源。
"""
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.shared_models import Product, User


def factory_scope_of(user: User) -> str:
    """读侧工厂范围的单一真相源（2026-10-25 上线前检查 H1 评审 finding 7）。

    此前 stock.py / report.py / finished_stock.py 各持一份逐字拷贝，靠注释引用
    「与 xx 同口径」人肉同步。厂绑定（User.factory 非空）非超管收窄到本厂，
    其余（超管/未绑定厂）返回空串 = 不限。
    """
    return user.factory if (user.factory and not user.is_super) else ''


async def assert_product_factory_scoped(
    db: AsyncSession, product_id: int | None, user: User, *, what: str,
) -> None:
    """库存/退货/批量写端点的工厂隔离闸门（2026-10-18 审计 P0-2）。

    与 order.py::_assert_order_factory_scoped 同口径（2026-10-17 F-BE-API-01）：
    厂绑定（User.factory 非空）的非超管用户只能写本厂产品名下的记录；此前
    写端点只认权限码、按自增 id 直取——厂绑定用户可改删他厂的
    入库/出库/退货记录（水平越权）。不匹配一律 404（不暴露「该记录存在
    但不属于你」）。

    放行面（2026-10-19 OCR 第三轮 M1）：产品 factory 为 **NULL 或空串** 的
    历史行、产品不存在、product_id 为空、超管/未绑定厂用户。空串必须放行：
    product_service.create_product 落库写 ``factory=factory or ''``——未分配
    工厂是空串而非 NULL，旧判 ``is not None`` 会把这些产品对厂绑定用户 404，
    而产品列表页不按厂过滤仍显示这些行，读放行写拦截口径自相矛盾。
    产品不存在时放行（由后续业务逻辑报 404/400）。
    """
    scoped_factory = user.factory if (user.factory and not user.is_super) else None
    if not scoped_factory or product_id is None:
        return
    row_factory = (await db.execute(
        select(Product.factory).where(Product.id == product_id)
    )).scalar_one_or_none()
    if row_factory and row_factory != scoped_factory:
        raise HTTPException(
            status_code=404, detail=f'{what}不存在')
