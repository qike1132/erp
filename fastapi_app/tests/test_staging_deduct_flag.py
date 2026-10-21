"""staging 通用解析：数字型「是否抵扣」标志不得被 Float64 形态静默丢弃。

审计 P1-8：openpyxl/Polars 读数字列时整数会以 3.0 到达，旧实现只看
``str(x).isdigit()``（"3.0" 不是纯数字），导致导入订单的抵扣标志丢失。

Z04-R3③ 后本函数定义在 ``batch_import_parser._parse_deduct_flag``，staging 只做
re-export —— 这里**刻意继续从 staging 路径导入**：它同时是「三条导入路径共用一份
解析」的语义锁（收敛接线由 ``tests/test_deduct_flag_single_implementation.py`` 负责）。
"""
from __future__ import annotations

import pytest

from fastapi_app.services.staging._generic import _parse_deduct_flag


def test_float64_integer_flag_is_accepted() -> None:
    assert _parse_deduct_flag(3.0, 10) == (True, 3)


@pytest.mark.parametrize(
    ('raw', 'expected'),
    [
        (3.0, (True, 3)),
        (3, (True, 3)),
        ('3', (True, 3)),
        ('3.0', (True, 3)),
        (3.5, (False, 0)),
        ('3.5', (False, 0)),
        ('是', (True, 10)),
        ('yes', (True, 10)),
        ('y', (True, 10)),
        (None, (False, 0)),
        ('', (False, 0)),
        (0, (False, 0)),
        (0.0, (False, 0)),
        ('0', (False, 0)),
        (-2.0, (False, 0)),
        (True, (False, 0)),
    ],
)
def test_parse_deduct_flag_matrix(raw, expected) -> None:
    assert _parse_deduct_flag(raw, 10) == expected
