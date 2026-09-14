"""float_utils 单元测试（fastapi_app/core/float_utils.py）

覆盖两部分：
1. 移植自 Odoo 的 float_round / float_is_zero / float_compare / float_repr /
   float_split / json_float_round 语义（含 2.675 等经典 IEEE-754 陷阱）；
2. Odoo bug #882036 的扩展舍入测试矩阵（原模块 ``__main__`` 自测块），
   覆盖 7 个数量级 × 8 种小数形态 × 正负号 × 10000 步进采样。
"""
import builtins
from decimal import Decimal

import pytest

pytestmark = pytest.mark.unit

from fastapi_app.core.float_utils import (
    float_compare,
    float_is_zero,
    float_repr,
    float_round,
    float_split,
    float_split_str,
    json_float_round,
    round_money,
    round_qty,
)


class TestFloatRound:
    """Odoo float_round 语义"""

    def test_classic_2_675_half_up(self):
        """2.675 在 IEEE-754 下是 2.67499...，HALF-UP 应得 2.68 而非 2.67"""
        assert float_repr(float_round(2.675, precision_digits=2), 2) == '2.68'

    def test_builtin_round_bankers_diverges(self):
        """反证：内建 round 是银行家舍入，同样的值会得到 2.67"""
        assert builtins.round(2.675, 2) == 2.67

    def test_half_up_tie_away_from_zero(self):
        assert float_round(0.125, precision_digits=2) == 0.13
        assert float_round(-0.125, precision_digits=2) == -0.13
        assert float_round(2.5, precision_digits=0) == 3.0
        assert float_round(-2.5, precision_digits=0) == -3.0

    def test_half_down_tie_towards_zero(self):
        assert float_round(0.125, precision_digits=2, rounding_method='HALF-DOWN') == 0.12
        assert float_round(-0.125, precision_digits=2, rounding_method='HALF-DOWN') == -0.12

    def test_half_even(self):
        assert float_round(0.125, precision_digits=2, rounding_method='HALF-EVEN') == 0.12
        assert float_round(0.135, precision_digits=2, rounding_method='HALF-EVEN') == 0.14

    def test_up_down_always_away_or_towards_zero(self):
        assert float_round(1.3, precision_digits=0, rounding_method='UP') == 2.0
        assert float_round(-1.3, precision_digits=0, rounding_method='UP') == -2.0
        assert float_round(1.7, precision_digits=0, rounding_method='DOWN') == 1.0
        assert float_round(-1.7, precision_digits=0, rounding_method='DOWN') == -1.0

    def test_zero_and_precision_aliasing(self):
        assert float_round(0.0, precision_digits=2) == 0.0
        assert float_round(-0.0, precision_digits=2) == 0.0
        # precision_rounding=0.05 → 步进 0.05
        assert float_round(1.3, precision_rounding=0.05) == 1.3
        assert float_round(1.27, precision_rounding=0.05) == 1.25

    def test_step_rounding_coin_values(self):
        """任意步长：0.25/0.5 等硬币值（Odoo 注释中的示例）"""
        assert float_round(1.3, precision_rounding=0.5) == 1.5
        assert float_round(1.6, precision_rounding=0.25) == 1.5
        assert float_round(1.62, precision_rounding=0.25) == 1.5

    def test_large_magnitude_no_representation_noise(self):
        """大数量级：浮点表示噪声不应外溢到分位"""
        f = 100000.0 + 0.675
        assert float_repr(float_round(f, precision_digits=2), 2) == '100000.68'
        f2 = 1000000.0 + 0.4555
        assert float_repr(float_round(f2, precision_digits=3), 3) == '1000000.456'

    def test_returns_float_and_zero_input(self):
        assert isinstance(float_round(1.005, precision_digits=2), float)
        assert float_round(10 ** -12, precision_digits=2) == 0.0

    def test_precision_args_mutually_exclusive(self):
        with pytest.raises(AssertionError):
            float_round(1.5, precision_digits=2, precision_rounding=0.01)
        with pytest.raises(AssertionError):
            float_round(1.5)
        with pytest.raises(AssertionError):
            float_round(1.5, precision_rounding=0)
        with pytest.raises(AssertionError):
            float_round(1.5, precision_rounding=-0.01)


class TestFloatIsZero:
    def test_tiny_values_are_zero_at_precision(self):
        assert float_is_zero(0.0, precision_digits=2)
        assert float_is_zero(0.001, precision_digits=2)
        assert float_is_zero(-0.001, precision_digits=2)
        assert float_is_zero(0.1 + 0.2 - 0.3, precision_digits=6)

    def test_small_but_visible_values_are_not_zero(self):
        assert not float_is_zero(0.01, precision_digits=2)
        assert not float_is_zero(-0.01, precision_digits=2)
        assert not float_is_zero(0.006, precision_digits=2)  # 舍入后 0.01


class TestFloatCompare:
    def test_equal_at_precision(self):
        assert float_compare(1.432, 1.431, precision_digits=2) == 0

    def test_classic_0_006_vs_0_002_documented_divergence(self):
        """Odoo 文档案例：0.006 与 0.002 比较（先舍入再比较）≠ 0"""
        assert float_compare(0.006, 0.002, precision_digits=2) == 1

    def test_is_zero_of_difference_differs_from_compare(self):
        """Odoo 警告案例：is_zero(a-b) 与 compare(a,b) 在 0.006/0.002 上不同"""
        assert float_compare(0.006, 0.002, precision_digits=2) == 1
        assert float_is_zero(0.006 - 0.002, precision_digits=2)

    def test_ordering(self):
        assert float_compare(1.0, 2.0, precision_digits=2) == -1
        assert float_compare(2.0, 1.0, precision_digits=2) == 1
        assert float_compare(-1.5, -1.5, precision_digits=2) == 0

    def test_float_noise_does_not_flip_ordering(self):
        """0.1+0.2 与 0.3 在 2 位精度下必须相等"""
        assert float_compare(0.1 + 0.2, 0.3, precision_digits=2) == 0

    def test_rounding_factor_alias(self):
        assert float_compare(1.3, 1.26, precision_rounding=0.05) == 1
        assert float_compare(1.3, 1.28, precision_rounding=0.05) == 0


class TestFloatReprAndSplit:
    def test_repr_keeps_trailing_zeros(self):
        assert float_repr(1.5, 2) == '1.50'
        assert float_repr(0.0, 2) == '0.00'

    def test_repr_avoids_12_sig_digits_truncation(self):
        assert float_repr(123456789.1234, 4) == '123456789.1234'
        assert float_repr(123456789.123, 4) == '123456789.1230'

    def test_split_str(self):
        assert float_split_str(1.432, 2) == ('1', '43')
        assert float_split_str(1.49, 1) == ('1', '5')
        assert float_split_str(1.1, 3) == ('1', '100')
        assert float_split_str(1.12, 0) == ('1', '')

    def test_split_int(self):
        assert float_split(1.432, 2) == (1, 43)
        assert float_split(1.49, 1) == (1, 5)
        assert float_split(1.12, 0) == (1, 0)


class TestJsonFloatRound:
    def test_json_safe_representation(self):
        """返回的 float 经 repr 序列化时应是最短表示而非 ...999322452"""
        value = json_float_round(3.1750, 4)
        assert repr(value) == '3.175'
        assert value == 3.175

    def test_json_float_round_half_up(self):
        assert json_float_round(2.675, 2) == 2.68
        assert json_float_round(-2.675, 2) == -2.68


class TestProjectHelpers:
    """round_money / round_qty 项目级封装"""

    def test_round_money_default_2_digits_half_up(self):
        assert round_money(2.675) == 2.68
        assert round_money(-2.675) == -2.68
        assert round_money(0.0) == 0.0
        assert round_money(10.005) == 10.01

    def test_round_money_explicit_precision(self):
        # float_round 的反归一化允许 1 ulp 表示误差，展示层用 float_repr 收口
        assert float_repr(round_money(1.005, precision_digits=3), 3) == '1.005'

    def test_round_qty_default_and_4_digit_bom_usage(self):
        assert round_qty(0.125) == 0.13
        assert float_repr(round_qty(0.12345, precision_digits=4), 4) == '0.1235'

    def test_numeric_column_input_requires_float(self):
        """Numeric 列读出的 Decimal 需先转 float（文档约定）"""
        assert round_money(float(Decimal('2.675'))) == 2.68


class TestOdooExtendedRoundingBattery:
    """Odoo bug #882036 扩展矩阵（原 ``__main__`` 自测块移植）

    对 7 个数量级 × 8 种小数形态 × 正负号 × (0..10000, 步长 97) 采样，
    断言 float_round 结果的字符串表示与十进制期望完全一致。
    """

    FRACTIONS: tuple = (.0, .015, .01499, .675, .67499, .4555, .4555, .45555)
    EXPECTEDS: tuple = ('.00', '.02', '.01', '.68', '.67', '.46', '.456', '.4556')
    PRECISIONS: tuple = (2, 2, 2, 2, 2, 2, 3, 4)

    @pytest.mark.parametrize('magnitude', range(7))
    def test_magnitude(self, magnitude):
        errors = []
        for frac, exp, prec in zip(self.FRACTIONS, self.EXPECTEDS, self.PRECISIONS, strict=True):
            for sign in (-1, 1):
                for x in range(0, 10000, 97):
                    n = x * 10 ** magnitude
                    f = sign * (n + frac)
                    f_exp = ('-' if f != 0 and sign == -1 else '') + str(n) + exp
                    result = float_repr(float_round(f, precision_digits=prec), prec)
                    if result != f_exp:
                        errors.append((f, result, f_exp))
        assert not errors, f'float_round 偏差: {errors[:5]} (共 {len(errors)} 处)'
