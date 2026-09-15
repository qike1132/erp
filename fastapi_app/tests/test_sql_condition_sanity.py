"""SQL 条件构造回归测试 —— `not <SQLAlchemy 列>` 陷阱

## 缺陷背景（2026-09-14 由 mypy `arg-type` 顺藤摸瓜发现）

`not X.column` 是 **Python 的 `not` 运算符**，走 `X.column.__bool__`，
求值为**普通布尔值**，而不是 SQL 表达式：

    >>> not Order.is_deleted
    False                     # ← 不是 SQL 条件！

把它放进 `where()` 会让整个条件**恒假**：

    select(func.count()).where(Order.customer == name, not Order.is_deleted)
    # 实际生成：  SELECT count(*) FROM "order" WHERE false
    #             ↑ 连 customer = :name 都被优化掉了

→ 计数**永远为 0** → 「存在则拒绝」的守卫**永不触发**。

## 两处真实缺陷（均已修复）

| 位置 | 失效的守卫 |
|---|---|
| `services/customer_service.py` `delete_customer` | 「客户有相关单据则拒绝删除」 |
| `services/user_service.py` `delete_user` | 「用户锁定了订单则拒绝删除」 |

**为什么长期未被发现**：这两处的测试都用 `mock_db`（`AsyncMock`）mock 掉了
`db.execute`，**从不执行真实 SQL** —— 测试断言的是"mock 返回真值时抛异常"，
与真实 SQL 是否恒假完全无关。

## 本测试的价值

1. **行为层**：断言正确写法编译出的 SQL 不含恒假条件（不依赖 DB，只编译 SQL）；
2. **静态层**：AST 扫描全库，禁止 `where(... not <Model>.<col> ...)` 再次出现。
   这是 mock 测试**无法覆盖**的层面，也是对同类问题的长期护栏。
"""
import ast
import pathlib

import pytest

pytestmark = pytest.mark.unit

from sqlalchemy import func, select
from sqlalchemy.dialects import postgresql

from fastapi_app.shared_models import Order

_SERVICES_ROOT = pathlib.Path(__file__).resolve().parent.parent / 'services'
_SQL_DIALECT = postgresql.dialect()


def _compiled(stmt) -> str:
    return str(stmt.compile(dialect=_SQL_DIALECT)).lower()


class TestNotOperatorTrap:
    """记录陷阱本身，防止有人"简化"回 `not X.col`"""

    def test_python_not_yields_plain_bool(self):
        """`not <列>` 得到的是 Python 布尔，不是 SQL 表达式。"""
        assert (not Order.is_deleted) is False

    def test_wrong_form_generates_always_false(self):
        wrong = select(func.count()).where(
            Order.customer == 'X', not Order.is_deleted
        )
        sql = _compiled(wrong)
        assert 'where false' in sql, '前提变化：SQLAlchemy 不再把 not 列降级为恒假？'

    def test_correct_form_is_not_always_false(self):
        right = select(func.count()).where(
            Order.customer == 'X', Order.is_deleted.isnot(True)
        )
        sql = _compiled(right)
        assert 'where false' not in sql
        assert 'is_deleted is not true' in sql
        assert 'customer' in sql, '正确写法应保留 customer 条件'


class TestNoBareNotOnModelColumns:
    """静态护栏：services 层不得对模型类列使用 Python `not`"""

    def test_no_not_on_model_attribute(self):
        offenders: list[str] = []
        for path in sorted(_SERVICES_ROOT.rglob('*.py')):
            if path.name == '__pycache__':
                continue
            try:
                tree = ast.parse(path.read_text(encoding='utf-8'))
            except SyntaxError:                      # pragma: no cover
                continue
            for node in ast.walk(tree):
                # 匹配 `not Xxx.attr`：Xxx 首字母大写 → 判定为模型类
                if not isinstance(node, ast.UnaryOp) or not isinstance(node.op, ast.Not):
                    continue
                operand = node.operand
                if not isinstance(operand, ast.Attribute):
                    continue
                base = operand.value
                if isinstance(base, ast.Name) and base.id[:1].isupper():
                    rel = path.relative_to(_SERVICES_ROOT.parent).as_posix()
                    offenders.append(f'{rel}:{node.lineno}  not {base.id}.{operand.attr}')

        assert not offenders, (
            '检测到对模型列使用 Python `not`（会求值为普通布尔，使 SQL 条件恒假）：\n  '
            + '\n  '.join(offenders)
            + '\n请改用 SQLAlchemy 表达式，如 `Xxx.col.isnot(True)` / `~Xxx.col` / `Xxx.col == False`'
        )
