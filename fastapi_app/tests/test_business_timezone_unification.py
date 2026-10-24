"""AUD-02（2026-10-24 审计 P1）回归锁：时间口径族——业务时区统一渲染与筛选。

naive-UTC 列（completed_at/approval 时间列）裸 strftime 恒慢 8 小时、北京
00:00–07:59 的记录落错天；timestamptz 列（create_time/order_date）裸 strftime
按 UTC 墙钟渲染同病。修复后：naive-UTC 走 fmt_business_naive_utc、aware 走
fmt_business、筛选边界走 business_day_bounds_utc_naive（北京日界→UTC 边界）。

期望值全部手工推导（五条铁律 3）：UTC 2026-10-24 02:30 = 北京 10:30；
UTC 2026-10-24 18:00 = 北京 10-25 02:00（跨日）。
"""
from datetime import UTC, datetime

from fastapi_app.core.business_time import (
    business_day_bounds_utc_naive,
    fmt_business,
    fmt_business_naive_utc,
)


# ---------------------------------------------------------------------------
# helper 单测（期望值手工推导）
# ---------------------------------------------------------------------------
def test_fmt_business_naive_utc_converts_utc_wall_clock():
    dt = datetime(2026, 10, 24, 2, 30)  # naive，语义=UTC
    assert fmt_business_naive_utc(dt) == '2026-10-24 10:30'
    assert fmt_business_naive_utc(dt, '%Y-%m-%d') == '2026-10-24'


def test_fmt_business_naive_utc_handles_cross_day():
    # UTC 18:00 = 北京次日 02:00
    dt = datetime(2026, 10, 24, 18, 0)
    assert fmt_business_naive_utc(dt) == '2026-10-25 02:00'


def test_fmt_business_naive_utc_none_is_empty():
    assert fmt_business_naive_utc(None) == ''


def test_fmt_business_aware_value():
    dt = datetime(2026, 10, 24, 2, 30, tzinfo=UTC)
    assert fmt_business(dt) == '2026-10-24 10:30'


def test_business_day_bounds_utc_naive():
    """北京 10-24 的 [00:00, 次日00:00) = UTC naive [10-23 16:00, 10-24 16:00)。"""
    from datetime import date

    lower, upper = business_day_bounds_utc_naive(date(2026, 10, 24))
    assert lower == datetime(2026, 10, 23, 16, 0)
    assert upper == datetime(2026, 10, 24, 16, 0)


# ---------------------------------------------------------------------------
# 采购完成态序列化（_completed._serialize_completed_order 的两条时间字段）
# ---------------------------------------------------------------------------
def test_completed_order_serializes_beijing_times():
    """completed_at（naive UTC）与 create_time（timestamptz）都按北京渲染。

    夹具：naive completed_at=UTC 02:30、aware create_time=UTC 02:30 —— 序列化
    后两者都必须是 10:30（修复前分别是 02:30 与 02:30 的 UTC 墙钟）。
    """
    from types import SimpleNamespace

    from fastapi_app.services.purchase import _completed as completed_mod

    order = SimpleNamespace(
        id=1, order_no='PO-TZ-1', supplier_name='供应商A', supplier_id=None,
        customer_name='客户A', status='completed', total_amount=100,
        product_name='产品A', product_quantity=10,
        order_date=datetime(2026, 10, 24).date(),
        remark='', create_time=datetime(2026, 10, 24, 2, 30, tzinfo=UTC),
        completed_at=datetime(2026, 10, 24, 2, 30),  # naive UTC
        items=[],
    )
    result = completed_mod._serialize_completed_order(order, {}, [], None, None)
    assert result['completed_at'] == '2026-10-24 10:30'
    assert result['create_time'] == '2026-10-24 10:30'


def test_approval_fmt_dt_converts_naive_utc():
    """审批时间（naive-UTC 列）经 to_dict 必须输出北京时间（F2-1 闭环）。"""
    from fastapi_app.shared_models.approval import _fmt_dt

    assert _fmt_dt(datetime(2026, 10, 24, 2, 30)) == '2026-10-24 10:30:00'
    assert _fmt_dt(None) is None


def test_order_serializer_order_date_is_beijing():
    """客户订单列表的 order_date（timestamptz）按北京渲染（F3-03 闭环）。"""
    from fastapi_app.services.serializers.order_serializer import (
        OrderField,
        OrderSerializer,
    )

    result = OrderSerializer._format_value(
        OrderField.ORDER_DATE, datetime(2026, 10, 24, 18, 0, tzinfo=UTC))
    assert result == '2026-10-25 02:00', 'UTC 18:00 必须显示为北京次日 02:00'
