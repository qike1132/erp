"""仪表盘各数据来源的有效读取范围。"""
import json
from dataclasses import dataclass, fields

from fastapi_app.core.production_scope import production_scope_of
from fastapi_app.shared.factory_scope import factory_scope_of
from fastapi_app.shared_models import User


@dataclass(frozen=True, slots=True)
class DashboardReadScope:
    factory: str = ''
    departments: tuple[str, ...] | None = ()
    orders: bool = False
    stockin: bool = False
    stockout: bool = False
    inventory: bool = False
    warehouse: bool = False
    plans: bool = False
    purchases: bool = False
    materials: bool = False
    amounts: bool = False

    @classmethod
    def for_user(cls, user: User) -> 'DashboardReadScope':
        factory = factory_scope_of(user)
        departments = production_scope_of(user)
        can = user.has_permission
        orders = can('order_manage')
        stockin = can('stockin_manage')
        return cls(
            factory=factory,
            departments=None if departments is None else tuple(sorted(departments)),
            orders=orders,
            stockin=stockin or orders,
            stockout=can('stockout_manage'),
            inventory=stockin or can('stock_view'),
            warehouse=can('case_manage'),
            plans=can('production_plan_view'),
            # 旧采购单与来料记录没有可证明的产品工厂归属，不给厂绑定用户返回全厂数据。
            purchases=not factory and (can('product_manage') or can('purchase_center_manage')),
            materials=not factory and (can('product_manage') or can('material_registration')),
            amounts=can('report_view'),
        )


def dashboard_cache_key(*, scope: DashboardReadScope, query_date: str | None = None, **_) -> str:
    # 结构化编码确保字段边界明确；版本隔开仍在 TTL 窗口内的旧数据。
    return 'scope-v1:' + json.dumps([query_date, *(getattr(scope, f.name) for f in fields(scope))])
