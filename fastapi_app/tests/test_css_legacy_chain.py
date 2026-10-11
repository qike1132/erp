"""CSS 降级链回归测试（2026-10-11 复核 N6）。

旧内核兼容的 CSS 降级链此前零回归保护：postcss 解包 @layer、oklch→rgb 替换、
构建后 check-css-legacy.mjs 自检，任一环节失效都表现为「旧内核样式/颜色全丢」
的静默回归。本测试锁住静态契约（链路存在且检查项齐全）。
"""

from __future__ import annotations

from pathlib import Path

FE = Path(__file__).resolve().parents[2] / "frontend-vite"


def test_check_css_legacy_script_checks_oklch() -> None:
    """构建自检脚本必须同时查 @layer 与 oklch(，缺一项 = 链路半失效。"""
    script = (FE / "scripts" / "check-css-legacy.mjs").read_text(encoding="utf-8")
    assert "/@layer\\b/g" in script, "check-css-legacy.mjs 丢失 @layer 检查"
    assert "/oklch\\(/g" in script, "check-css-legacy.mjs 丢失 oklch( 检查（旧内核颜色全失效）"


def test_postcss_config_wires_both_plugins() -> None:
    """postcss 配置必须同时接解包插件与 oklab 替换插件（preserve:false）。"""
    cfg = (FE / "postcss.config.mjs").read_text(encoding="utf-8")
    assert "unwrapCascadeLayers" in cfg
    assert "postcss-oklab-function" in cfg
    assert "preserve: false" in cfg, (
        "oklab 插件必须 preserve:false 直接替换——自定义属性后者胜出，"
        "保留 oklch 兜底会被盖掉，旧内核仍拿不到值"
    )


def test_build_atomic_runs_css_check() -> None:
    """build:atomic 必须在 swap 前跑 check-css-legacy（否则自检形同虚设）。"""
    pkg = (FE / "package.json").read_text(encoding="utf-8")
    build_line = next(l for l in pkg.splitlines() if '"build:atomic"' in l)
    order = build_line.index("check-css-legacy")
    assert order < build_line.index("swap-dist"), "自检必须发生在 swap-dist 之前"
