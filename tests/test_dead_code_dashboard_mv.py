"""死代码防复活（2026-11-17 上线前审计 V-9 确证）。

## 拦哪种出错

`dashboard/stats.py` 曾有一个 `_get_mv_daily_quantity(db, mv_name, stat_date)`：
按名字拼 f-string SQL 读物化视图（带 `# nosec B608`）、异常时回滚并降级返回 None。
全仓（含 tests）**零业务调用**，唯一痕迹是 `dashboard_service.py` 的一句
`from ... import _get_mv_daily_quantity  # noqa: F401` re-export。

它的害处不是"多几行"，而是**读起来像"物化视图已接入"**：

- 审计/评审看到 `_mv_or_base` 旁边的 MV 读取函数，会以为 dashboard 已走物化视图加速，
  实际每次统计都打基表；
- 那个 re-export 让 `grep _get_mv_daily_quantity` 在 services 层就有命中，进一步坐实
  "有人在用"的错觉；
- 同时它携带一处 `nosec B608`（手写 SQL 豁免）与两处 `db.rollback()`（事务控制豁免），
  白占安全/事务豁免预算。

## 本文件各锁一件事

1. `test_stats_module_no_longer_defines_mv_helper`：`dashboard/stats.py` 不再定义它；
2. `test_service_facade_no_longer_reexports_mv_helper`：门面不再 re-export（re-export 是
   它看起来"被用"的直接原因）；
3. `test_no_module_references_mv_helper`：整棵 `fastapi_app` 树的 AST 里再无该名字 ——
   一旦有人把它抄回来（哪怕只是 import），这里立刻红。

删除前本文件 3 条全红（1、2 直接红；3 也会红，因为定义与 re-export 都是引用）。
"""
import ast
from pathlib import Path

from fastapi_app.services import dashboard_service
from fastapi_app.services.dashboard import stats as stats_mod

_NAME = '_get_mv_daily_quantity'
_REPO = Path(__file__).resolve().parent.parent
_APP_ROOT = _REPO / 'fastapi_app'


def test_stats_module_no_longer_defines_mv_helper():
    assert not hasattr(stats_mod, _NAME), (
        f'{_NAME} 仍定义在 dashboard/stats.py —— 它零业务调用，只会让人误以为物化视图已接入'
    )


def test_service_facade_no_longer_reexports_mv_helper():
    assert not hasattr(dashboard_service, _NAME), (
        f'dashboard_service 仍在 re-export {_NAME} —— 这正是 grep 时"看起来有人在用"的来源'
    )


def test_no_module_references_mv_helper():
    """整棵 fastapi_app 树（AST 级）不得再出现该名字：定义/import/调用都算。"""
    offenders: list[str] = []
    for path in sorted(_APP_ROOT.rglob('*.py')):
        if '__pycache__' in path.parts:
            continue
        try:
            tree = ast.parse(path.read_text(encoding='utf-8', errors='replace'))
        except SyntaxError:  # pragma: no cover - 语法错误由 ruff/AST 门禁负责
            continue
        for node in ast.walk(tree):
            hit = (
                (isinstance(node, ast.Name) and node.id == _NAME)
                or (isinstance(node, ast.Attribute) and node.attr == _NAME)
                or (isinstance(node, ast.alias) and _NAME in (node.name, node.asname))
            )
            if hit:
                offenders.append(f'{path.relative_to(_REPO)}:{node.lineno}')

    assert offenders == [], f'{_NAME} 被重新引入：{offenders}'
