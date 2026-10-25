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


# ---------------------------------------------------------------------------
# M-1（2026-10-25 上线前审计）残留簇：报表导出/统一流水/箱包流水的 aware 列
# 裸 strftime 收口 fmt_business。期望值手工推导：UTC 18:00/18:05/18:30 = 北京
# 次日 02:00/02:05/02:30（跨日）。
# ---------------------------------------------------------------------------
def test_fmt_business_variants_cover_m1_call_sites():
    """date-only / 月份键 / 带秒三种 fmt 变体（M-1 各落点的口径锁）。"""
    dt = datetime(2026, 10, 24, 18, 30, 5, tzinfo=UTC)
    assert fmt_business(dt, '%Y-%m-%d') == '2026-10-25'
    assert fmt_business(dt, '%Y-%m') == '2026-10'
    assert fmt_business(dt, '%Y-%m-%d %H:%M:%S') == '2026-10-25 02:30:05'
    assert fmt_business(None, '%Y-%m') == ''


def test_unified_fmt_datetime_is_beijing():
    """订单统一流水 _fmt_datetime（order/stockin 两类 timestamptz 共用）。"""
    from fastapi_app.services.order.unified import _fmt_datetime

    assert _fmt_datetime(datetime(2026, 10, 24, 18, 0, tzinfo=UTC)) == '2026-10-25 02:00'
    assert _fmt_datetime(None) == ''


def test_case_movement_serializer_is_beijing():
    """箱包出入库流水序列化（movement_date/create_time 均 timestamptz）。"""
    from types import SimpleNamespace

    from fastapi_app.services.case._serializers import _serialize_movement

    m = SimpleNamespace(
        id=1, case_id=1, case=None, direction='in', movement_no='CM-1',
        quantity=2, customer='客户A', note=None,
        movement_date=datetime(2026, 10, 24, 18, 5, tzinfo=UTC),
        create_time=datetime(2026, 10, 24, 18, 30, 5, tzinfo=UTC),
    )
    d = _serialize_movement(m)
    assert d['movement_date'] == '2026-10-25', 'UTC 18:05 = 北京次日 02:05 → 日期落 10-25'
    assert d['create_time'] == '2026-10-25 02:30:05'


def test_auxiliary_business_month_str_business_tz():
    """L-2（2026-10-25 审计）：辅助台账月份键与单号系统同源（业务时区）。

    旧实现 ``datetime.now(UTC).strftime('%Y-%m')`` 与 numbering_sequence 的
    业务时区是两个"当期"源——月末/月初 8 小时窗口内单号落本月、台账落邻月。
    """
    from fastapi_app.services.auxiliary_service import business_month_str

    # UTC 10-31 20:30 = 北京 11-01 04:30 → 键必须落 11 月（旧 UTC 实现落 10 月）
    assert business_month_str(datetime(2026, 10, 31, 20, 30, tzinfo=UTC)) == '2026-11'
    assert business_month_str(datetime(2026, 10, 31, 10, 30, tzinfo=UTC)) == '2026-10'
    assert business_month_str(datetime(2026, 11, 1, 3, 0, tzinfo=UTC)) == '2026-11'
