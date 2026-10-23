"""P2-102 回归：部署脚本与服务管理器的停机序必须同源。

`server_manager/constants.py::_SVC_REVERSE` 是拓扑推导的唯一真相源；
`deploy/install_package.ps1` 曾手写一份枚举并自称权威，已漂移（erp-web 位置不同）。
本测试锁住两者逐项一致。
"""
import re
from pathlib import Path

from server_manager.constants import _SVC_REVERSE

_PS1 = Path(__file__).resolve().parents[1] / 'deploy' / 'install_package.ps1'


def test_install_stop_order_matches_server_manager():
    text = _PS1.read_text(encoding='utf-8')
    match = re.search(r"\$stopOrder\s*=\s*@\(([^)]*)\)", text)
    assert match, 'install_package.ps1 缺少 $stopOrder 定义'
    order = tuple(item.strip().strip("'\"") for item in match.group(1).split(',') if item.strip())
    assert order == tuple(_SVC_REVERSE)
