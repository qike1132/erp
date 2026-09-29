"""时区写入修复回归：timestamptz 列必须写 aware UTC。

背景（生产实测 2026-09-29）
--------------------------
pg_standalone_013 已把 ``order.order_date`` 等列迁移为 timestamptz，但创建代码
仍按旧注释写 naive UTC（``datetime.now(UTC).replace(tzinfo=None)``）。asyncpg
把 naive 值按会话时区 Asia/Shanghai 解释 ⇒ 存入瞬间比真实时刻早 8 小时，
/outsource 与 /beile-order 页面「下单时间」显示成 UTC 钟面值
（PO-20260929-0008 于北京 09:29 创建，页面显示 2026-09-29 01:29）。

本文件锁两个口径：
1. 创建路径传给 ORM 的时间必须是 aware（tzinfo 不为 None）；
2. outsource 的 ``_fmt_dt`` 展示口径与 beile 的 ``_fmt_beile_time`` 一致
   （aware UTC / naive UTC → 北京时间），避免裸 strftime 把 UTC 当地面时间。
"""
from datetime import UTC, datetime

import pytest


def _aware(dt: datetime | None) -> bool:
    return dt is not None and dt.tzinfo is not None


@pytest.mark.asyncio
async def test_create_order_header_writes_aware_order_date(monkeypatch):
    """批量下单主订单：order_date 必须 aware，naive 会被按 +08 解释致早 8h。"""
    from fastapi_app.services import order_batch_create

    async def _fake_number(db):
        return 'PO-20260929-0009'

    monkeypatch.setattr(
        'fastapi_app.services.numbering.generate_order_number', _fake_number
    )

    captured = []

    def _capture_add(obj):
        captured.append(obj)

    class _Db:
        add = staticmethod(_capture_add)

        async def flush(self):
            return None

    items = [{'product_id': 1, 'quantity': 3, 'note': '', 'product': None}]
    order = await order_batch_create._create_order_header(_Db(), '测试客户', items)

    assert order is captured[0]
    assert _aware(order.order_date), (
        'order_date 写成了 naive UTC：asyncpg 会按 Asia/Shanghai 解释，'
        '存入瞬间早 8 小时（页面显示 UTC 钟面值）'
    )


def test_fmt_dt_converts_utc_to_beijing():
    """outsource 序列化与 beile._fmt_beile_time 同口径：UTC → 北京时间。"""
    from fastapi_app.services.outsource._common import _fmt_dt

    # timestamptz 列：asyncpg 读回 aware UTC → 转 +8
    assert _fmt_dt(datetime(2026, 9, 29, 1, 29, tzinfo=UTC)) == '2026-09-29 09:29'
    # naive 值按 UTC 解释（历史口径），转 +8
    assert _fmt_dt(datetime(2026, 9, 29, 1, 29)) == '2026-09-29 09:29'
    # 跨日边界：北京 00:30 前 UTC 还是前一天
    assert _fmt_dt(datetime(2026, 9, 28, 16, 30, tzinfo=UTC)) == '2026-09-29 00:30'
    assert _fmt_dt(None) is None


def test_fmt_beile_time_and_fmt_dt_agree():
    """两个页面共用同一展示口径，不允许再分叉。"""
    from fastapi_app.services.order.beile import _fmt_beile_time
    from fastapi_app.services.outsource._common import _fmt_dt

    for dt in (
        datetime(2026, 9, 29, 1, 29, tzinfo=UTC),
        datetime(2026, 9, 29, 1, 29),
        None,
    ):
        assert _fmt_dt(dt) == (_fmt_beile_time(dt) or None)
