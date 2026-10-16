"""RoundedButton 配色回归锁：真 Tk 渲染取证（不靠文本猜色）。

背景（2026-10-16）：`_BUTTON_VARIANT_PALETTE['neutral']` 的 `fill` 错填成
表面底色 '#f2f2f7'，而 `outlined` 变体拿 `tone_cfg['fill']` 当**边框色+字色**
（widgets.py 的 outlined 分支）——「刷新」「打开日志」两个按钮画出来是
灰框白底灰字，看起来褪色/半透明（用户实测报障）。`solid` 用法下恰好正常
（灰底按钮），故存量自包化首步 b03d3510 起从未暴露。

本文件用真 Tk 实例化按钮、读 canvas item 的**实际填充色**断言，
因为：①文本断言只能锁「调色表里有什么」，锁不住「画出来是什么」；
②本文档所述的缺陷恰是调色表字段错配，纯文本断言会漏判。

运行: python -m pytest tests/test_sm_button_colors.py -q（需 Windows Tk；非 Windows skip）
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

pytestmark = pytest.mark.skipif(
    sys.platform != "win32",
    reason="RoundedButton 是 Tk Canvas 控件，渲染取证需 Windows Tk",
)


def _draw_colors(btn) -> list[str]:
    """读按钮 canvas 上实际绘制出的 fill 色序列（外框 → 内底 → …）。"""
    fills = [btn.itemcget(i, "fill") for i in range(1, 60)]
    return [f for f in fills if f]


@pytest.fixture(scope="module")
def tk_root():
    import tkinter as tk
    root = tk.Tk()
    root.withdraw()
    root.update()
    yield root
    root.destroy()


class TestNeutralOutlinedColors:
    """core 修复锁：outlined+neutral 必须有可见描边（不得再用表面底色）。"""

    def test_border_is_brand_gray_not_surface(self, tk_root):
        from server_manager.widgets import RoundedButton
        btn = RoundedButton(tk_root, text="刷新", variant="outlined", tone="neutral", canvas_bg="#ffffff")
        btn.pack()
        tk_root.update()
        border, bg, fg = _draw_colors(btn)[0], _draw_colors(btn)[1], btn._fg
        assert border == "#6e6e73", f"描边应为品牌灰 #6e6e73，实际 {border}"
        assert bg == "#ffffff"
        assert fg == "#6e6e73", f"字色应跟随描边，实际 {fg}"

    def test_contrast_against_card_background(self, tk_root):
        """边框/文字对白底的相对亮度差必须足够（灰框白底褪色缺陷的判据）。"""
        from server_manager.widgets import RoundedButton
        btn = RoundedButton(tk_root, text="打开日志", variant="outlined", tone="neutral", canvas_bg="#ffffff")
        btn.pack()
        tk_root.update()
        fg = btn._fg
        r, g, b = (int(fg[i:i + 2], 16) for i in (1, 3, 5))
        lum = 0.299 * r + 0.587 * g + 0.114 * b   # 相对亮度近似（0-255）
        assert lum < 160, f"字色 {fg} 太浅，灰框白底下会褪色（亮度 {lum:.0f}）"


class TestOtherCombosUnchanged:
    """修复不得波及其它 tone/variant（逐一与修复前渲染值比对）。"""

    @pytest.mark.parametrize("variant,tone,border,fg", [
        ("outlined", "accent", "#007aff", "#007aff"),
        ("outlined", "danger", "#ff3b30", "#ff3b30"),
        ("solid", "accent", "#007aff", "#ffffff"),
        ("solid", "success", "#34c759", "#ffffff"),
        ("subtle", "danger", "#f5b8b1", "#ff3b30"),
        ("subtle", "accent", "#c8dcfb", "#007aff"),
    ])
    def test_colors_preserved(self, tk_root, variant, tone, border, fg):
        from server_manager.widgets import RoundedButton
        btn = RoundedButton(tk_root, text="x", variant=variant, tone=tone, canvas_bg="#ffffff")
        btn.pack()
        tk_root.update()
        colors = _draw_colors(btn)
        assert colors[0] == border, f"{variant}+{tone} 外框 {colors[0]} ≠ {border}"
        assert btn._fg == fg, f"{variant}+{tone} 字色 {btn._fg} ≠ {fg}"


class TestDisabledUnaffected:
    """disabled 态走硬编码 _DISABLED_*，与 tone 无关 —— 停止按钮初始置灰不可被本轮改动波及。"""

    def test_disabled_outlined_neutral(self, tk_root):
        from server_manager.widgets import RoundedButton
        btn = RoundedButton(tk_root, text="停止", variant="outlined", tone="neutral",
                            canvas_bg="#ffffff", state="disabled")
        btn.pack()
        tk_root.update()
        assert _draw_colors(btn)[0] == "#e5e5ea", "disabled 外框必须仍是 _DISABLED_BORDER"
        assert _draw_colors(btn)[1] == "#f2f2f7", "disabled 内底必须仍是 _DISABLED_BG"

    def test_toggle_back_to_normal_restores_colors(self, tk_root):
        """启用 → 置灰 → 再启用，颜色必须逐态正确（_set_actions_enabled 复用 config 路径）。"""
        from server_manager.widgets import RoundedButton
        btn = RoundedButton(tk_root, text="刷新", variant="outlined", tone="neutral", canvas_bg="#ffffff")
        btn.pack()
        tk_root.update()
        btn.config(state="disabled")
        tk_root.update()
        btn.config(state="normal")
        tk_root.update()
        assert _draw_colors(btn)[0] == "#6e6e73", "重新启用后描边应恢复品牌灰"


class TestPaletteTableIntegrity:
    """调色表字段契约：fill 是可作描边的品牌色，tint 是表面淡色 —— 两者不得互相错填。"""

    def test_neutral_fill_is_not_a_surface_tint(self):
        from server_manager.widgets import _BUTTON_VARIANT_PALETTE
        neutral = _BUTTON_VARIANT_PALETTE["neutral"]
        assert neutral["fill"] != neutral["tint"], (
            "neutral.fill 与 neutral.tint 相同意味着 outlined 描边 = 表面底色（褪色缺陷）")
        assert neutral["fill"].lower() != "#f2f2f7", "fill 不得回填表面底色 #f2f2f7"

    def test_all_tones_have_fill_distinct_from_tint(self):
        from server_manager.widgets import _BUTTON_VARIANT_PALETTE
        for tone, cfg in _BUTTON_VARIANT_PALETTE.items():
            assert cfg["fill"] != cfg["tint"], (
                f"tone {tone}: fill 与 tint 相同，outlined 变体会用表面底色描边")
