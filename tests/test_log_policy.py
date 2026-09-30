"""日志策略（config/log_policy.json）单测：默认值、持久化往返、坏值夹取、表单校验。

策略是桌面壳 / prod_runner / ARQ 三处**共用**的一份文件——所以它必须：
1. 缺失/损坏时回落默认值（三方都能跑下去，不能因为一个 JSON 写法错就不维护）；
2. 越界值被夹取（抗手改），而不是被当成合法值生效；
3. 界面表单越界**报错**（不静默替用户改写意图）。
"""
from __future__ import annotations

from pathlib import Path

from utils.log_rotation import (
    DEFAULT_LOG_POLICY,
    LogPolicy,
    load_log_policy,
    policy_from_fields,
    save_log_policy,
)


def test_missing_file_falls_back_to_defaults(tmp_path: Path) -> None:
    assert load_log_policy(tmp_path / "nope.json") == DEFAULT_LOG_POLICY


def test_corrupt_file_falls_back_to_defaults(tmp_path: Path) -> None:
    bad = tmp_path / "log_policy.json"
    bad.write_text("{ not json", encoding="utf-8")
    assert load_log_policy(bad) == DEFAULT_LOG_POLICY


def test_save_then_load_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "log_policy.json"
    policy = LogPolicy(rotate_bytes=80 * 1024 * 1024, keep_days=30,
                       max_total_bytes=1024 * 1024 * 1024)
    assert save_log_policy(policy, path) is True
    assert load_log_policy(path) == policy


def test_out_of_range_values_are_clamped(tmp_path: Path) -> None:
    path = tmp_path / "log_policy.json"
    path.write_text('{"rotate_mb": 0, "keep_days": 999999, "max_total_mb": 0}', encoding="utf-8")
    loaded = load_log_policy(path)
    assert loaded.rotate_mb == 1          # 下限
    assert loaded.keep_days == 3650       # 上限
    assert loaded.max_total_mb == 16      # 下限


def test_default_is_the_documented_triple() -> None:
    assert DEFAULT_LOG_POLICY.rotate_mb == 50
    assert DEFAULT_LOG_POLICY.keep_days == 14
    assert DEFAULT_LOG_POLICY.max_total_mb == 512


def test_form_rejects_out_of_range_instead_of_clamping() -> None:
    policy, error = policy_from_fields("0", "14", "512")
    assert policy is None and error is not None and "轮转阈值" in error


def test_form_rejects_non_integer() -> None:
    policy, error = policy_from_fields("abc", "14", "512")
    assert policy is None and error is not None and "整数" in error


def test_form_accepts_valid_triple() -> None:
    policy, error = policy_from_fields("80", "30", "1024")
    assert error is None and policy is not None
    assert policy.rotate_mb == 80 and policy.keep_days == 30 and policy.max_total_mb == 1024
