"""L1 ruff 严重度映射测试（2026-10-11 复核 P1-6）。

原实现把所有 ruff 命中硬编码 Severity.HIGH，导致 29 条 scripts/ 机械违规
（UP031/SIM105 等）全部挤进 high 阻断计数。现按规则族映射：
E9/F63/F7/F82 前缀（语法/未定义名）→ HIGH；bandit 码（B + S1xx~S6xx，
fullmatch 防 SIM 前缀误伤）→ MEDIUM；其余风格类 → LOW。
"""

from __future__ import annotations

from scripts.prod_audit.layers.l1_static import L1StaticAnalysis


def _parse(layer: L1StaticAnalysis, sample: str):
    return layer._parse_ruff_output(sample, builder_placeholder=None)


def test_syntax_error_maps_to_high() -> None:
    layer = L1StaticAnalysis.__new__(L1StaticAnalysis)  # 只测纯解析，不跑工具
    issues = _parse(layer, "foo.py:1:1: F821 undefined name 'x'\n")
    assert len(issues) == 1
    assert issues[0].severity.value == "high"


def test_security_rule_maps_to_medium() -> None:
    layer = L1StaticAnalysis.__new__(L1StaticAnalysis)
    issues = _parse(layer, "foo.py:2:5: S324 hashlib.md5 used for security\n")
    assert len(issues) == 1
    assert issues[0].severity.value == "medium"


def test_style_rule_maps_to_low() -> None:
    layer = L1StaticAnalysis.__new__(L1StaticAnalysis)
    issues = _parse(layer, "foo.py:3:9: UP031 Use format specifiers instead of percent format\n")
    assert len(issues) == 1
    assert issues[0].severity.value == "low"


def test_bandit_code_maps_to_medium() -> None:
    layer = L1StaticAnalysis.__new__(L1StaticAnalysis)
    issues = _parse(layer, "foo.py:4:1: B324 hashlib use of md5\n")
    assert issues[0].severity.value == "medium"


def test_s_bandit_code_maps_to_medium_not_sim() -> None:
    """S1xx~S6xx 是 bandit 安全码 → MEDIUM；SIM105 是风格类 → LOW（防 S 前缀误伤）。"""
    layer = L1StaticAnalysis.__new__(L1StaticAnalysis)
    assert _parse(layer, "foo.py:5:1: S324 hashlib use of md5\n")[0].severity.value == "medium"
    assert _parse(layer, "foo.py:6:9: SIM105 Use contextlib.suppress\n")[0].severity.value == "low"


def test_unmatched_lines_ignored() -> None:
    layer = L1StaticAnalysis.__new__(L1StaticAnalysis)
    assert _parse(layer, "All checks passed!\n") == []
