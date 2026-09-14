# Part of Odoo. See LICENSE file for full copyright and licensing details.
#
# Original work:
#   Copyright (C) 2004-2013 OpenERP S.A. / Odoo S.A. (<https://www.odoo.com>)
#   Licensed under the GNU Lesser General Public License version 3 (LGPL-3.0)
#   <https://www.gnu.org/licenses/lgpl-3.0.html>
#
# Modifications (this project):
#   Copyright (C) 2026 the ERP project authors
#   - Ported from the Odoo 17.0 source tree; dropped only the ``__main__``
#     self-test (now covered by ``fastapi_app/tests/test_float_utils.py``,
#     including the upstream extended rounding battery from bug #882036).
#     The module-level P2-style ``round()`` shim is retained verbatim:
#     ``float_round``'s HALF-UP/HALF-DOWN paths depend on it for exact ties.
#   - Added the project-level helpers ``round_money`` / ``round_qty`` for the
#     standard 2-decimal currency / quantity precision used across the app.
#
# This library is free software: you can redistribute it and/or modify it
# under the terms of the GNU Lesser General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. This library is distributed in the hope that it
# will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty
# of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU Lesser
# General Public License for more details. You should have received a copy of
# the GNU Lesser General Public License along with this library. If not, see
# <https://www.gnu.org/licenses/lgpl-3.0.html>.
"""浮点金额/数量的规范舍入与比较工具（移植自 Odoo，LGPL-3.0）。

业务背景：本项目金额/数量列多为 Numeric(12,2)，经 ORM 读出后为 float/Decimal，
手写 ``round(x, 2)``（银行家舍入 + IEEE-754 表示误差）会出现 2.675 → 2.67、
0.1 + 0.2 != 0.3 之类的偏差。本模块通过「归一化-取整-反归一化 + 按数量级缩放的
epsilon」把误差压到 1 ulp 以内，并提供 HALF-UP（四舍五入）等 tie-break 规则。

金额与数量的展示/落库请统一使用 :func:`round_money` / :func:`round_qty`；
需要自定义精度（如 BOM 用量 4 位小数）时直接调用 :func:`float_round`。
"""
from __future__ import annotations

import builtins
import math

__all__ = [
    'float_compare',
    'float_is_zero',
    'float_repr',
    'float_round',
    'float_split',
    'float_split_str',
    'json_float_round',
    'round_money',
    'round_qty',
]

# 项目默认精度：金额与数量列均为 Numeric(12, 2)（BOM 单位用量为 Numeric(10, 4)）
MONEY_PRECISION_DIGITS = 2
QTY_PRECISION_DIGITS = 2


def round(f):
    # P3's builtin round differs from P2 in the following manner:
    # * it rounds half to even rather than up (away from 0)
    # * round(-0.) loses the sign (it returns -0 rather than 0)
    # * round(x) returns an int rather than a float
    #
    # this compatibility shim implements Python 2's round in terms of
    # Python 3's so that important rounding error under P3 can be
    # trivially fixed, assuming the P2 behaviour to be debugged and
    # correct.
    roundf = builtins.round(f)
    if builtins.round(f + 1) - roundf != 1:
        return f + math.copysign(0.5, f)
    # copysign ensures round(-0.) -> -0 *and* result is a float
    return math.copysign(roundf, f)


def _float_check_precision(precision_digits=None, precision_rounding=None):
    assert (precision_digits is not None or precision_rounding is not None) and \
        not (precision_digits and precision_rounding), \
        'exactly one of precision_digits and precision_rounding must be specified'  # noqa: S101
    assert precision_rounding is None or precision_rounding > 0, \
        'precision_rounding must be positive, got %s' % precision_rounding  # noqa: S101, UP031
    if precision_digits is not None:
        return 10 ** -precision_digits
    return precision_rounding


def float_round(value, precision_digits=None, precision_rounding=None, rounding_method='HALF-UP'):
    """Return ``value`` rounded to ``precision_digits`` decimal digits,
    minimizing IEEE-754 floating point representation errors, and applying
    the tie-breaking rule selected with ``rounding_method``, by default
    HALF-UP (away from zero).
    Precision must be given by ``precision_digits`` or ``precision_rounding``,
    not both!

    :param float value: the value to round
    :param int precision_digits: number of fractional digits to round to.
    :param float precision_rounding: decimal number representing the minimum
        non-zero value at the desired precision (for example, 0.01 for a
        2-digit precision).
    :param rounding_method: the rounding method used:
        - 'HALF-UP' will round to the closest number with ties going away from zero.
        - 'HALF-DOWN' will round to the closest number with ties going towards zero.
        - 'HALF-EVEN' will round to the closest number with ties going to the closest
          even number.
        - 'UP' will always round away from 0.
        - 'DOWN' will always round towards 0.
    :return: rounded float
    """
    rounding_factor = _float_check_precision(precision_digits=precision_digits,
                                             precision_rounding=precision_rounding)
    if rounding_factor == 0 or value == 0:
        return 0.0

    # NORMALIZE - ROUND - DENORMALIZE
    # In order to easily support rounding to arbitrary 'steps' (e.g. coin values),
    # we normalize the value before rounding it as an integer, and de-normalize
    # after rounding: e.g. float_round(1.3, precision_rounding=.5) == 1.5
    #
    # Due to IEEE754 float/double representation limits, the approximation of the
    # real value may be slightly below the tie limit, resulting in an error of
    # 1 unit in the last place (ulp) after rounding.
    # For example 2.675 == 2.6749999999999998.
    # To correct this, we add a very small epsilon value, scaled to the
    # order of magnitude of the value, to tip the tie-break in the right
    # direction.
    # Credit: discussion with OpenERP community members on bug 882036
    normalized_value = value / rounding_factor  # normalize
    sign = math.copysign(1.0, normalized_value)
    epsilon_magnitude = math.log(abs(normalized_value), 2)
    epsilon = 2 ** (epsilon_magnitude - 52)

    # TIE-BREAKING: UP/DOWN (for ceiling[resp. flooring] operations)
    # When rounding the value up [resp. down], we instead subtract [resp. add] the epsilon value
    # as the approximation of the real value may be slightly *above* the
    # tie limit, this would result in incorrectly rounding up [resp. down] to the next number
    #
    # The math.ceil[resp. math.floor] operation is applied on the absolute value in order to
    # round "away from zero" and not "towards infinity", then the sign is
    # restored.
    if rounding_method == 'UP':
        normalized_value -= sign * epsilon
        rounded_value = math.ceil(abs(normalized_value)) * sign

    # TIE-BREAKING: HALF-EVEN
    # We want to apply HALF-EVEN tie-breaking rules, i.e. 0.5 rounds towards closest even number.
    elif rounding_method == 'HALF-EVEN':
        rounded_value = math.copysign(builtins.round(normalized_value), normalized_value)

    # TIE-BREAKING: HALF-DOWN
    # We want to apply HALF-DOWN tie-breaking rules, i.e. 0.5 rounds towards 0.
    elif rounding_method == 'HALF-DOWN':
        normalized_value -= math.copysign(epsilon, normalized_value)
        rounded_value = round(normalized_value)

    elif rounding_method == 'DOWN':
        normalized_value += sign * epsilon
        rounded_value = math.floor(abs(normalized_value)) * sign

    # TIE-BREAKING: HALF-UP (for normal rounding)
    # We want to apply HALF-UP tie-breaking rules, i.e. 0.5 rounds away from 0.
    else:
        normalized_value += math.copysign(epsilon, normalized_value)
        rounded_value = round(normalized_value)  # round to integer

    result = rounded_value * rounding_factor  # de-normalize
    return result


def float_is_zero(value, precision_digits=None, precision_rounding=None):
    """Returns true if ``value`` is small enough to be treated as
    zero at the given precision (smaller than the corresponding *epsilon*).
    The precision (``10**-precision_digits`` or ``precision_rounding``)
    is used as the zero *epsilon*: values less than that are considered
    to be zero.
    Precision must be given by ``precision_digits`` or ``precision_rounding``,
    not both!

    Warning: ``float_is_zero(value1-value2)`` is not equivalent to
    ``float_compare(value1,value2) == 0``, as the former will round after
    computing the difference, while the latter will round before, giving
    different results for e.g. 0.006 and 0.002 at 2 digits precision.

    :param int precision_digits: number of fractional digits to round to.
    :param float precision_rounding: decimal number representing the minimum
        non-zero value at the desired precision (for example, 0.01 for a
        2-digit precision).
    :param float value: value to compare with the precision's zero
    :return: True if ``value`` is considered zero
    """
    epsilon = _float_check_precision(precision_digits=precision_digits,
                                     precision_rounding=precision_rounding)
    return abs(float_round(value, precision_rounding=epsilon)) < epsilon


def float_compare(value1, value2, precision_digits=None, precision_rounding=None):
    """Compare ``value1`` and ``value2`` after rounding them according to the
    given precision. A value is considered lower/greater than another value
    if their rounded value is different. This is not the same as having a
    non-zero difference!
    Precision must be given by ``precision_digits`` or ``precision_rounding``,
    not both!

    Example: 1.432 and 1.431 are equal at 2 digits precision,
    so this method would return 0
    However 0.006 and 0.002 are considered different (this method returns 1)
    because they respectively round to 0.01 and 0.0, even though
    0.006-0.002 = 0.004 which would be considered zero at 2 digits precision.

    Warning: ``float_is_zero(value1-value2)`` is not equivalent to
    ``float_compare(value1,value2) == 0``, as the former will round after
    computing the difference, while the latter will round before, giving
    different results for e.g. 0.006 and 0.002 at 2 digits precision.

    :param int precision_digits: number of fractional digits to round to.
    :param float precision_rounding: decimal number representing the minimum
        non-zero value at the desired precision (for example, 0.01 for a
        2-digit precision).
    :param float value1: first value to compare
    :param float value2: second value to compare
    :return: (resp.) -1, 0 or 1, if ``value1`` is (resp.) lower than,
        equal to, or greater than ``value2``, at the given precision.
    """
    rounding_factor = _float_check_precision(precision_digits=precision_digits,
                                             precision_rounding=precision_rounding)
    value1 = float_round(value1, precision_rounding=rounding_factor)
    value2 = float_round(value2, precision_rounding=rounding_factor)
    delta = value1 - value2
    if float_is_zero(delta, precision_rounding=rounding_factor):
        return 0
    return -1 if delta < 0.0 else 1


def float_repr(value, precision_digits):
    """Returns a string representation of a float with the
    given number of fractional digits. This should not be
    used to perform a rounding operation (this is done via
    :func:`~.float_round`), but only to produce a suitable
    string representation for a float.

    :param float value:
    :param int precision_digits: number of fractional digits to include in the output
    """
    # Can't use str() here because it seems to have an intrinsic
    # rounding to 12 significant digits, which causes a loss of
    # precision. e.g. str(123456789.1234) == str(123456789.123)!!
    # (keep upstream %-format: it is the reference implementation)
    return ('%%.%sf' % precision_digits) % value  # noqa: UP031


_float_repr = float_repr


def float_split_str(value, precision_digits):
    """Splits the given float 'value' in its unitary and decimal parts,
    returning each of them as a string, rounding the value using
    the provided ``precision_digits`` argument.
    The length of the string returned for decimal places will always
    be equal to ``precision_digits``, adding zeros at the end if needed.
    In case ``precision_digits`` is zero, an empty string is returned for
    the decimal places.

    Examples:
        1.432 with precision 2 => ('1', '43')
        1.49 with precision 1 => ('1', '5')
        1.1 with precision 3 => ('1', '100')
        1.12 with precision 0 => ('1', '')

    :param float value: value to split.
    :param int precision_digits: number of fractional digits to round to.
    :return: returns the tuple(<unitary part>, <decimal part>) of the given value
    :rtype: tuple(str, str)
    """
    value = float_round(value, precision_digits=precision_digits)
    value_repr = float_repr(value, precision_digits)
    return tuple(value_repr.split('.')) if precision_digits else (value_repr, '')


def float_split(value, precision_digits):
    """ same as float_split_str() except that it returns the unitary and decimal
    parts as integers instead of strings. In case ``precision_digits`` is zero,
    0 is always returned as decimal part.
    :rtype: tuple(int, int)
    """
    units, cents = float_split_str(value, precision_digits)
    if not cents:
        return int(units), 0
    return int(units), int(cents)


def json_float_round(value, precision_digits, rounding_method='HALF-UP'):
    """Not suitable for float calculations! Similar to float_repr except that it
    returns a float suitable for json dump
    This may be necessary to produce "exact" representations of rounded float
    values during serialization, such as what is done by `json.dumps()`.
    Unfortunately `json.dumps` does not allow any form of custom float representation,
    nor any custom types, everything is serialized from the basic JSON types.

    :param int precision_digits: number of fractional digits to round to.
    :param rounding_method: the rounding method used: 'HALF-UP', 'UP' or 'DOWN',
        the first one rounding up to the closest number with the rule that
        number>=0.5 is rounded up to 1, the second always rounding up and the
        latest one always rounding down.
    :return: a rounded float value that must not be used for calculations, but
        is ready to be serialized in JSON with minimal chances of
        representation errors.
    """
    rounded_value = float_round(value, precision_digits=precision_digits, rounding_method=rounding_method)
    rounded_repr = float_repr(rounded_value, precision_digits=precision_digits)
    # As of Python 3.1, rounded_repr should be the shortest representation for our
    # rounded float, so we create a new float whose repr is expected
    # to be the same value, or a value that is semantically identical
    # and will be used in the json serialization.
    # e.g. if rounded_repr is '3.1750', the new float repr could be 3.175
    # but not 3.174999999999322452.
    # Cfr. bpo-1580: https://bugs.python.org/issue1580
    return float(rounded_repr)


def round_money(value, precision_digits: int = MONEY_PRECISION_DIGITS, rounding_method: str = 'HALF-UP') -> float:
    """金额舍入：按项目金额精度（默认 2 位）做 HALF-UP 舍入。

    基于 :func:`json_float_round`：返回值的 repr 即为十进制舍入结果，
    不带 float_round 反归一化的 1 ulp 噪声，可直接进 JSON/Excel 展示
    （也使 ``round_money(x) == 0.7`` 这类断言成立）。

    输入须为 float（Numeric 列经 ORM 读出的 Decimal 请先 ``float()``）。
    """
    return json_float_round(value, precision_digits, rounding_method=rounding_method)


def round_qty(value, precision_digits: int = QTY_PRECISION_DIGITS, rounding_method: str = 'HALF-UP') -> float:
    """数量舍入：按项目数量精度（默认 2 位）做 HALF-UP 舍入。

    语义同 :func:`round_money`（json_float_round 口径）。
    BOM 单位用量等 4 位小数场景请显式传 ``precision_digits=4``。
    """
    return json_float_round(value, precision_digits, rounding_method=rounding_method)
