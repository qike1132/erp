"""限流开关回归。

背景（上线前审计）：`core/limiter.py` 里 `Limiter(..., enabled=False)` 把
**所有** `@limiter.limit(...)` 装饰器变成了空操作 —— 于是
`auth.py:212`(100/min)、`daily_production.py:215`、`report.py:154`、`stock.py:351`
这些已经写好的限流全部不生效，导出/报表端点实际上没有任何限流。
"""
from __future__ import annotations

import pytest


def test_limiter_is_enabled_by_default() -> None:
    """默认必须开启：否则全部 @limiter.limit 装饰器静默失效。"""
    from fastapi_app.core.limiter import limiter

    assert limiter.enabled is True, (
        '全局限流默认应为开启（排障时可用环境变量 RATE_LIMIT_ENABLED=false 临时关闭）'
    )


def test_decorated_endpoints_are_not_noop() -> None:
    """至少确认导出类端点确实挂了限流装饰器，且 limiter 处于启用态。"""
    import pathlib
    import re

    src = pathlib.Path('fastapi_app/api/v1/endpoints').rglob('*.py')
    decorated = []
    for f in src:
        text = f.read_text(encoding='utf-8')
        if re.search(r'@limiter\.limit\(', text):
            decorated.append(f.name)

    assert decorated, '未找到任何 @limiter.limit 装饰器 —— 限流覆盖面可能被误删'

    from fastapi_app.core.limiter import limiter

    assert limiter.enabled is True


@pytest.mark.parametrize(
    ('value', 'expected'),
    [
        ('true', True),
        ('True', True),
        ('1', True),
        ('', True),          # 空值按默认（开启）处理
        ('false', False),
        ('FALSE', False),
        ('0', False),
    ],
)
def test_env_flag_parsing(monkeypatch: pytest.MonkeyPatch, value: str, expected: bool) -> None:
    from fastapi_app.core.limiter import limiter_enabled_from_env

    monkeypatch.setenv('RATE_LIMIT_ENABLED', value)
    assert limiter_enabled_from_env() is expected


def test_env_flag_defaults_to_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi_app.core.limiter import limiter_enabled_from_env

    monkeypatch.delenv('RATE_LIMIT_ENABLED', raising=False)
    assert limiter_enabled_from_env() is True


def test_global_default_limit_is_off_by_default() -> None:
    """开关要开，但**不设**全局默认限流值。

    原值 `60/minute` 写下来后限流长期被 `enabled=False` 架空，从未在真实流量下
    验证过；按用户计 60 次/分钟，正常用户快速浏览就可能触顶 —— 上线日给用户弹 429
    比不限流更糟（实测：启用该全局值后单次后端测试会话产生 172 次 429）。
    因此只让作者显式标注 `@limiter.limit` 的端点限流。
    """
    from fastapi_app.core.limiter import (
        limiter,
        limiter_default_limits_from_env,
        limiter_enabled_from_env,
    )

    assert limiter_enabled_from_env() is True
    assert limiter_default_limits_from_env() == []
    assert limiter._default_limits == []


@pytest.mark.parametrize(
    ('value', 'expected'),
    [
        ('', []),
        ('300/minute', ['300/minute']),
        ('  120/minute  ', ['120/minute']),
    ],
)
def test_default_limit_env_parsing(
    monkeypatch: pytest.MonkeyPatch, value: str, expected: list[str]
) -> None:
    """需要时可用 RATE_LIMIT_DEFAULT 显式开启全局上限（观察无误拦后再逐步收紧）。"""
    from fastapi_app.core.limiter import limiter_default_limits_from_env

    monkeypatch.setenv('RATE_LIMIT_DEFAULT', value)
    assert limiter_default_limits_from_env() == expected
