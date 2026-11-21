"""M-6 / M-11 回归：计划状态白名单（2026-11-21 全量审计）。

purchase_plan / production_plan 的更新入口此前收自由字符串 status：
completed 被改回 pending 绕过状态机（M-6）、任意字符串使计划从所有状态
筛选中消失（M-11）。修复=shared_models 状态常量 + schema Literal +
service 层守卫（守卫先于取数，非法值零 DB 访问，仿 PO 侧 P1-16）。

会话替身故意「一触即炸」：守卫必须在任何 DB 访问前拦截——修复前守卫不存在，
请求穿透到 execute 触发 NotImplementedError 而非「非法状态」ValueError（Red）。
"""
import pytest
from pydantic import ValidationError

from fastapi_app.schemas.production_plan import ProductionPlanUpdate
from fastapi_app.schemas.purchase_plan import PurchasePlanUpdate
from fastapi_app.services import production_plan_service as pps
from fastapi_app.services import purchase_plan_crud_ops as ppo


class _ForbiddenSession:
    """任何 DB 访问即炸——证明守卫先于取数。"""

    async def execute(self, *args, **kwargs):
        raise NotImplementedError("守卫应先于取数拦截非法状态，不应触达 DB")


@pytest.mark.parametrize("bad", ["garbage", "", "PENDING", "completed "])
async def test_purchase_plan_update_rejects_unknown_status(bad):
    with pytest.raises(ValueError, match="非法采购计划状态"):
        await ppo.update_plan(_ForbiddenSession(), 1, status=bad)


async def test_production_plan_update_rejects_unknown_status():
    with pytest.raises(ValueError, match="非法排产计划状态"):
        await pps.update_plan(_ForbiddenSession(), 1, status="garbage")


@pytest.mark.parametrize("bad", ["garbage", "", "PENDING", "cancelled "])
def test_purchase_plan_schema_rejects_unknown_status(bad):
    with pytest.raises(ValidationError):
        PurchasePlanUpdate(status=bad)


@pytest.mark.parametrize("good", ["pending", "confirmed", "completed", "cancelled"])
def test_purchase_plan_schema_accepts_known_status(good):
    assert PurchasePlanUpdate(status=good).status == good


@pytest.mark.parametrize("bad", ["garbage", "", "PENDING", "cancelled "])
def test_production_plan_schema_rejects_unknown_status(bad):
    with pytest.raises(ValidationError):
        ProductionPlanUpdate(status=bad)


@pytest.mark.parametrize("good", ["pending", "confirmed", "completed"])
def test_production_plan_schema_accepts_known_status(good):
    assert ProductionPlanUpdate(status=good).status == good
