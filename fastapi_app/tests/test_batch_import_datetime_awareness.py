"""P1-01 回归：batch_import_service 不得再出现无参 datetime.now()。

order_date / stockout_date 是 timestamptz 列。全仓同列写入点统一用
`datetime.now(UTC)`（aware），避免 naive/aware 混用导致不同驱动/会话时区下
的解释不一致；本文件的定点锁禁止无参 now() 回潮。
（注：asyncpg 对 naive 值按进程本地时区编码，本机 CST 下 now() 与 now(UTC)
落库等价；此处的目标是统一口径，不是修复 8 小时偏移。）
"""
import ast
from pathlib import Path

_SERVICE = Path(__file__).resolve().parents[1] / 'services' / 'batch_import_service.py'


def test_batch_import_service_has_no_naive_datetime_now():
    tree = ast.parse(_SERVICE.read_text(encoding='utf-8'))
    offenders = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == 'now'
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == 'datetime'
            and not node.args
            and not node.keywords
        ):
            offenders.append(node.lineno)
    assert offenders == [], f'发现 naive datetime.now() 调用行号: {offenders}'
