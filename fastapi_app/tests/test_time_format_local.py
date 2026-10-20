"""UTC → 北京时间展示口径（审计 P1-1 / P1-2）。

客户打样全模块与批次查询列表曾直接 strftime UTC 值，页面时间比北京时间早 8 小时。
修法统一走 shared.time_format.format_local_time。
"""
from __future__ import annotations

import inspect
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from fastapi_app.services import order_batch_service
from fastapi_app.services.customer_sampling.grouping import _project_to_summary
from fastapi_app.services.order.beile import _fmt_beile_time
from fastapi_app.services.outsource._common import _fmt_dt
from fastapi_app.shared.time_format import format_local_time
from fastapi_app.shared_models.customer_sampling import CustomerSamplingProject

_REPO = Path(__file__).resolve().parents[2]


def test_aware_utc_is_converted_to_beijing() -> None:
    assert format_local_time(datetime(2026, 10, 20, 2, 0, tzinfo=UTC)) == '2026-10-20 10:00:00'


def test_naive_utc_is_treated_as_utc() -> None:
    assert format_local_time(datetime(2026, 10, 20, 2, 0)) == '2026-10-20 10:00:00'


def test_cross_midnight_shifts_date() -> None:
    assert format_local_time(datetime(2026, 10, 19, 18, 0, tzinfo=UTC)) == '2026-10-20 02:00:00'


def test_custom_format_and_none_value() -> None:
    assert format_local_time(datetime(2026, 10, 20, 2, 0, tzinfo=UTC), '%Y-%m-%d %H:%M') == '2026-10-20 10:00'
    assert format_local_time(None) == ''
    assert format_local_time(None, none_value=None) is None


def test_naive_local_value_can_skip_conversion() -> None:
    assert format_local_time(datetime(2026, 10, 20, 10, 0), naive_is_utc=False) == '2026-10-20 10:00:00'


def test_customer_sampling_model_to_dict_uses_beijing_time() -> None:
    project = CustomerSamplingProject(
        created_at=datetime(2026, 10, 20, 2, 0, tzinfo=UTC),
        updated_at=datetime(2026, 10, 20, 3, 0, tzinfo=UTC),
        completed_at=datetime(2026, 10, 19, 18, 0, tzinfo=UTC),
    )

    data = project.to_dict()

    assert data['created_at'] == '2026-10-20 10:00:00'
    assert data['updated_at'] == '2026-10-20 11:00:00'
    assert data['completed_at'] == '2026-10-20 02:00:00'


def test_grouping_summary_uses_beijing_time() -> None:
    project = SimpleNamespace(
        product_image_file_id=None,
        id=1,
        sequence_no='C001',
        product_name='测试产品',
        current_version=1,
        status='in_progress',
        completed_at=datetime(2026, 10, 19, 18, 0, tzinfo=UTC),
        updated_at=datetime(2026, 10, 20, 2, 0, tzinfo=UTC),
    )

    data = _project_to_summary(project, {})

    assert data['completed_at'] == '2026-10-20 02:00:00'
    assert data['updated_at'] == '2026-10-20 10:00:00'


def test_beile_and_outsource_helpers_share_the_same_rule() -> None:
    aware = datetime(2026, 9, 18, 5, 38, tzinfo=UTC)
    naive = datetime(2026, 9, 18, 6, 31)

    assert _fmt_beile_time(aware) == '2026-09-18 13:38'
    assert _fmt_beile_time(naive) == '2026-09-18 14:31'
    assert _fmt_beile_time(None) == ''
    assert _fmt_dt(aware) == '2026-09-18 13:38'
    assert _fmt_dt(None) is None


def test_customer_sampling_serializers_have_no_bare_utc_strftime() -> None:
    for rel in (
        'fastapi_app/shared_models/customer_sampling.py',
        'fastapi_app/services/customer_sampling/grouping.py',
        'fastapi_app/services/customer_sampling/projects.py',
        'fastapi_app/services/customer_sampling/version_diff.py',
    ):
        source = (_REPO / rel).read_text(encoding='utf-8')
        assert ".strftime('%Y-%m-%d %H:%M:%S')" not in source, rel


def test_batch_query_serializer_uses_local_formatter() -> None:
    source = inspect.getsource(order_batch_service._serialize_batch_stockins)

    assert 'format_local_time(s.stockin_date' in source
    assert 'format_local_time(s.batch_completed_at' in source
    assert 's.stockin_date.strftime(' not in source
    assert 's.batch_completed_at.strftime(' not in source
