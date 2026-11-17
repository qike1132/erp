"""批次 4 的三处「静默失败」修复回归（2026-11-17 上线前审计 P1-6 / P1-9 / P1-13）。

三个缺陷同一族：**出错或不匹配时，系统不吭声**。

- P1-6 导入找不到目标 Sheet 时静默回落第一个 Sheet → 传错模板也当真实单据写库；
- P1-9 来料登记日期用 UTC 日界 → 北京 00:00–08:00 登记的单落到「昨天」，台账错位；
- P1-13 ARQ cron 的超时判定用全局 `job_timeout` → cron 自带更小 timeout 时被判「retrying」，
  死信/失败指标/`backup_schedule.last_status` 全都不更新（调度永久停在 running）。

本文件逐个锁住「不吭声」变「按预期吭声」。
"""
from __future__ import annotations

import asyncio
import contextlib
import time

import pytest

# ---------------------------------------------------------------- P1-6 Sheet 匹配


def test_find_target_sheet_matches_keyword():
    from fastapi_app.services.batch_import_parser import _find_target_sheet

    assert _find_target_sheet(['无关', '备货管理', '出货管理'], ['备货管理']) == '备货管理'


def test_find_target_sheet_single_sheet_still_falls_back():
    """单 Sheet 文件的实际命名五花八门（WPS 另存/用户改名）—— 唯一的 sheet 就是目标。

    这是既定行为（`tests/test_product_import_preview.py` 锁着「预览与导入同口径」），
    收窄后必须保留。
    """
    from fastapi_app.services.batch_import_parser import _find_target_sheet

    assert _find_target_sheet(['Sheet1'], ['新品录入', '产品管理']) == 'Sheet1'


def test_find_target_sheet_multi_sheet_no_match_returns_none():
    """多 Sheet 且都不匹配 → None（由调用方报「没有找到 X Sheet」），不再静默取第一个。

    修复前返回 `sheets[0]`：用户传错模板（多 Sheet 的工作簿）时会被当成目标 Sheet 解析，
    错模板也会变成真实单据 —— 数据污染且事后极难发现（审计 P1-6）。
    """
    from fastapi_app.services.batch_import_parser import _find_target_sheet

    assert _find_target_sheet(['汇总', '明细'], ['新品录入', '产品管理']) is None
    assert _find_target_sheet([], ['X']) is None


@pytest.mark.asyncio
async def test_read_target_sheet_reports_not_found_instead_of_parsing_first(monkeypatch):
    """整条读取链：多 Sheet 无匹配时必须返回 not_found_msg，且**不去解析任何 Sheet**。"""
    from fastapi_app.services import batch_import_parser as parser

    parsed: list[str] = []

    async def _fake_sheets(_path):
        return True, ['汇总表', '明细表'], None

    async def _fake_parse(_path, sheet):
        parsed.append(sheet)
        return True, [{'x': 1}], None

    @contextlib.asynccontextmanager
    async def _fake_save(_file):
        yield 'stub.xlsx'

    monkeypatch.setattr(parser, 'read_excel_sheets_async', _fake_sheets)
    monkeypatch.setattr(parser, 'parse_excel_file_async', _fake_parse)
    monkeypatch.setattr(parser, '_save_uploaded_file', _fake_save)

    data, err = await parser._read_excel_sheets(object(), ['新品录入'], '没有找到"新品录入"Sheet')

    assert data is None
    assert err == '没有找到"新品录入"Sheet'
    assert parsed == [], '不该解析任何 Sheet —— 静默回落第一个正是 P1-6 的缺陷'


# ---------------------------------------------------------------- P1-9 业务时区


def test_registration_date_default_is_business_today():
    """模型默认值必须是业务时区（Asia/Shanghai）的「今天」，不是 UTC 日期。"""
    from fastapi_app.shared_models.material_registration import MaterialRegistration

    default = MaterialRegistration.__table__.c.registration_date.default
    assert default is not None
    # 用「函数名 + 所属模块」判定而不是对象 identity：本仓测试树会把 app 包按不同
    # sys.path 根各导入一次，同一个函数可能有两个模块实例（identity 会假红）。
    assert getattr(default.arg, '__name__', '') == 'business_today', (
        'registration_date 默认值必须引用 business_today，而不是 UTC 日期'
    )
    assert getattr(default.arg, '__module__', '') == 'fastapi_app.core.business_time'


def test_create_registration_uses_business_today(monkeypatch):
    """写入侧（_commands.create_registration）必须用 business_today，而不是 UTC 日期。"""
    import inspect

    from fastapi_app.services.material_registration import _commands

    src = inspect.getsource(_commands.create_registration)
    assert 'business_today()' in src
    assert 'datetime.now(UTC)' not in src, '写入侧仍在用 UTC 日界（P1-9）'


@pytest.mark.asyncio
async def test_stats_trend_buckets_by_business_timezone(monkeypatch):
    """趋势图的日期骨架与 SQL 日界都必须是 Asia/Shanghai（与写入侧同边界）。"""
    import datetime as dt

    from fastapi_app.services.material_registration import _queries

    fixed = dt.date(2026, 1, 2)
    monkeypatch.setattr(_queries, 'business_today', lambda: fixed)

    captured: list[str] = []

    class _FakeResult:
        def all(self):
            return []

        def scalars(self):
            return self

        def unique(self):
            return self

        def scalar(self):
            return 0

    class _FakeDB:
        async def execute(self, stmt):
            # 用 literal_binds 编译：AT TIME ZONE 的时区是绑定参数，str(stmt) 里只有 :param
            try:
                captured.append(str(stmt.compile(compile_kwargs={'literal_binds': True})))
            except Exception:  # pragma: no cover - 编译不了就退回原样
                captured.append(str(stmt))
            return _FakeResult()

    payload = await _queries.get_stats_trend(_FakeDB(), days=2)
    trend = payload['trend']

    joined = '\n'.join(captured)
    assert "AT TIME ZONE 'Asia/Shanghai'" in joined, (
        '趋势 SQL 仍按 UTC 取日界 —— 与写入侧 business_today() 差一天（P1-9）'
    )
    assert "AT TIME ZONE 'UTC'" not in joined
    # 日期骨架以业务时区的今天收尾（days=2 → 3 个点：T-2、T-1、T）
    assert trend[-1]['date'] == '2026-01-02', trend
    assert trend[0]['date'] == '2025-12-31', trend


# ---------------------------------------------------------------- P1-13 cron 超时


def _cancel_after(elapsed_seconds: float):
    """造一个「跑了 elapsed_seconds 后被取消」的任务：直接改 ctx 里的起始时刻再抛。"""
    async def _job(ctx, *_a, **_kw):
        ctx['_start_monotonic'] = time.monotonic() - elapsed_seconds
        raise asyncio.CancelledError()
    return _job


@pytest.mark.asyncio
async def test_cron_timeout_uses_own_budget(monkeypatch):
    """cron 自带 timeout=300，跑到 300s 被取消 → 必须判 failed（而不是 retrying）。

    修复前一律与全局 `WorkerSettings.job_timeout`（1800s）比，elapsed≈300 远小于 1798，
    于是判成「retrying」→ 死信/失败指标/schedule.last_status 全不更新（审计 P1-13）。
    """
    from fastapi_app.core import arq_app

    monkeypatch.setattr(arq_app.WorkerSettings, 'job_timeout', 1800, raising=False)
    wrapped = arq_app._tracked_job(_cancel_after(300), max_tries=3, timeout=300)
    ctx: dict = {'job_try': 1}

    with pytest.raises(asyncio.CancelledError):
        await wrapped(ctx)

    assert ctx['_job_outcome'] == 'failed'
    assert isinstance(ctx['_job_exception'], TimeoutError)
    assert '300' in str(ctx['_job_exception'])


@pytest.mark.asyncio
async def test_stop_cancel_still_treated_as_retrying(monkeypatch):
    """对照组：没有给 per-cron timeout 时，跑 300s 被取消仍按「停机重放」记 retrying。"""
    from fastapi_app.core import arq_app

    monkeypatch.setattr(arq_app.WorkerSettings, 'job_timeout', 1800, raising=False)
    wrapped = arq_app._tracked_job(_cancel_after(300), max_tries=3)
    ctx: dict = {'job_try': 1}

    with pytest.raises(asyncio.CancelledError):
        await wrapped(ctx)

    assert ctx['_job_outcome'] == 'retrying', '停机/abort 的取消不该被误判成超时失败'


@pytest.mark.asyncio
async def test_cron_jobs_pass_their_own_timeout_into_wrapper(monkeypatch):
    """接线：cron_jobs 必须把 `s['timeout']` 同时传给 ARQ 与 _tracked_job。"""
    import inspect

    from fastapi_app.core import arq_app

    src = inspect.getsource(arq_app)
    assert '_tracked_job(s[\'func\'], MAX_TRIES, timeout=s.get(\'timeout\'))' in src
