"""告警规则 / Redis 默认值 的对齐回归测试。

背景（评审 2026-10-11，v2/v3 报告）：
- ``config/alert_rules.yml`` 曾有两条规则引用了 ``metrics.py`` **从未导出** 的
  指标名（``pg_stat_activity_count`` / ``pg_settings_max_connections`` /
  ``arq_dead_letter_queue_depth``），规则永不触发 → 连接池打满与死信堆积都没
  监控。本测试锁死「规则 expr 里出现的每个指标名都必须由 metrics.py 导出」。
- ``config.py`` 的 ``REDIS_URL`` / ``REDIS_HOST`` 默认值是 ``localhost``，
  Windows 上解析优先 ``::1`` 而 redis 只 bind ``127.0.0.1``，漏配 ``.env`` 的
  新环境会连不上（生产备份链路曾因此 fail-closed 停摆）。
"""
import re
from pathlib import Path

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
_METRICS_PY = _REPO_ROOT / "fastapi_app" / "core" / "metrics.py"
_CONFIG_PY = _REPO_ROOT / "fastapi_app" / "core" / "config.py"
_ALERT_RULES = _REPO_ROOT / "config" / "alert_rules.yml"

# PromQL 函数 / 聚合算子，非指标名
_PROMQL_FUNCS = frozenset({
    "histogram_quantile", "sum", "rate", "increase", "irate", "avg", "min",
    "max", "count", "stddev", "stdvar", "quantile", "topk", "bottomk",
    "delta", "abs", "ceil", "floor", "vector", "time", "absent",
    "count_values", "group", "label_replace", "label_join",
})


def _exported_metric_names() -> set[str]:
    """解析 metrics.py 源码里 ``_get_or_create_*`` 的首个字符串参数（= 指标名）。"""
    src = _METRICS_PY.read_text(encoding="utf-8")
    return set(
        re.findall(
            r"_get_or_create_(?:counter|histogram|gauge)\(\s*'([^']+)'",
            src,
        )
    )


def _metric_refs(expr: str) -> set[str]:
    """从一条 PromQL 表达式里提取被引用的指标名（剔除函数、标签、区间）。"""
    s = re.sub(r"\{[^}]*\}", " ", expr)              # 去标签选择器 {k=v}
    s = re.sub(r"\[[^\]]*\]", " ", s)                # 去区间 [5m]
    s = re.sub(                                       # 去分组子句 by (...)
        r"\b(?:by|without|on|ignoring|group_left|group_right)\s*\([^)]*\)",
        " ",
        s,
    )
    return {
        tok
        for tok in re.findall(r"[a-zA-Z_][a-zA-Z0-9_]*", s)
        if tok not in _PROMQL_FUNCS
    }


def _is_exported(ref: str, exported: set[str]) -> bool:
    """``ref`` 本身被导出，或是某已导出直方图的 _bucket/_sum/_count 序列。"""
    if ref in exported:
        return True
    base = re.sub(r"_(?:bucket|sum|count)$", "", ref)
    return base in exported


def _load_alert_rules() -> list[dict]:
    data = yaml.safe_load(_ALERT_RULES.read_text(encoding="utf-8"))
    rules: list[dict] = []
    for group in data.get("groups", []):
        rules.extend(group.get("rules", []))
    return rules


def test_alert_rules_reference_only_exported_metrics():
    """每条告警规则的 expr 引用的指标名，必须由 metrics.py 导出。"""
    exported = _exported_metric_names()
    missing: list[str] = []
    for rule in _load_alert_rules():
        expr = rule.get("expr", "")
        for ref in _metric_refs(expr):
            if not _is_exported(ref, exported):
                missing.append(f"{rule.get('alert')}: {ref}  (expr={expr!r})")
    assert not missing, (
        "以下告警规则引用了 metrics.py 未导出的指标，规则将永不触发：\n"
        + "\n".join(missing)
    )


def test_redis_defaults_use_ipv4_loopback():
    """REDIS_URL/REDIS_HOST 的代码默认值必须是 127.0.0.1，不得是 localhost。"""
    src = _CONFIG_PY.read_text(encoding="utf-8")
    assert '"redis://localhost:6379/0"' not in src, "REDIS_URL 默认值仍是 localhost"
    assert 'os.getenv("REDIS_HOST", "localhost")' not in src, "REDIS_HOST 默认值仍是 localhost"
    assert '"redis://127.0.0.1:6379/0"' in src, "REDIS_URL 默认值未改为 127.0.0.1"


def test_refresh_dead_letter_queue_depth_sets_gauge():
    """refresh_dead_letter_queue_depth 把 Redis LLEN 的返回值写进 gauge。

    行为测试：mock 掉共享 Redis 客户端，断言真实调用 llen 并把值 set 进
    ARQ_DEAD_LETTER_QUEUE_DEPTH（防止再次出现「导入了名字却没真正刷新」的
    静默失效，如把 DLQ_KEY 写错成 DLK_KEY 被 except 吞掉）。
    """
    import asyncio
    import sys
    import types
    from unittest.mock import AsyncMock, MagicMock, patch

    from fastapi_app.core import metrics as m

    if not m.METRICS_AVAILABLE:
        pytest.skip("prometheus_client 未安装，指标为 NoOp")

    fake_client = AsyncMock()
    fake_client.llen = AsyncMock(return_value=7)
    # arq_callbacks 会传递性导入 config（非提权下 .env 的 ACL 读不了），
    # 用轻量 stub 替换其 DLQ_KEY，隔离出被测的「get_client → LLEN → gauge.set」。
    stub = types.ModuleType("fastapi_app.core.arq_callbacks")
    stub.DLQ_KEY = "arq:dead_letter"
    with patch.dict(sys.modules, {"fastapi_app.core.arq_callbacks": stub}), \
            patch("fastapi_app.core.redis_wrapper.get_client",
                  MagicMock(return_value=fake_client)):
        asyncio.run(m.refresh_dead_letter_queue_depth())

    fake_client.llen.assert_awaited_once_with("arq:dead_letter")
    assert m.ARQ_DEAD_LETTER_QUEUE_DEPTH._value.get() == 7
