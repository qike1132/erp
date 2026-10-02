"""order.status CHECK 约束的结构性回归测试。

背景（2026-10-02 存量审计 P6）：`order_status_check` 被两条迁移先后 DROP+ADD，
而**后执行的那条**（`pg_standalone_002`，集合缺 '批次已完成'）覆盖了先执行的
`pg_standalone_008`，使重建库拒绝合法状态。修复方式是在链尾新增
`pg_standalone_063_fix_order_status_check` 重声明。

本测试防**复发**：
  1. 链尾那条迁移的集合必须与 ORM 的 `VALID_ORDER_STATUSES` 逐字一致；
  2. 该迁移必须确实是**应用顺序上最后一个**声明 `order_status_check` 的迁移
     （否则将来新增一条晚执行的迁移又会把约束改错）。
"""
import ast
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
FIX_REVISION = 'pg_standalone_063_fix_order_status_check'
_CONSTRAINT_RE = re.compile(r'ADD CONSTRAINT order_status_check')


def _apply_order_and_paths() -> list[tuple[str, pathlib.Path]]:
    """按 alembic 解析出的**应用顺序**（base → head）返回 (revision, 文件路径)。

    注意：**revision id 与文件名常不一致**（如 id `pg_standalone_002` 落在
    `pg_standalone_002_add_indexes_and_order_status_constraint.py`），故必须用
    alembic 的 Script.path，不能按 `{revision}.py` 拼路径 —— 否则会静默跳过
    002/008 这些正是要防的迁移，使断言空转。
    """
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    cfg = Config(str(ROOT / 'alembic.ini'))
    script = ScriptDirectory.from_config(cfg)
    scripts = list(script.iterate_revisions('head', 'base'))
    return [(s.revision, pathlib.Path(s.path)) for s in reversed(scripts)]


def test_fix_migration_set_matches_orm_authority():
    """063 的集合必须与 ORM 的 VALID_ORDER_STATUSES 逐字一致（防漂移）。"""
    from fastapi_app.shared_models.order import VALID_ORDER_STATUSES

    path = dict(_apply_order_and_paths())[FIX_REVISION]
    tree = ast.parse(path.read_text(encoding='utf-8'))
    literal = None
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            getattr(t, 'id', None) == 'ORDER_STATUSES' for t in node.targets
        ):
            literal = ast.literal_eval(node.value)
    assert literal is not None, '未在 063 里找到 ORDER_STATUSES 常量'
    assert frozenset(literal) == frozenset(VALID_ORDER_STATUSES), (
        f'迁移集合与 ORM 不一致:\n  迁移: {sorted(literal)}\n  ORM : {sorted(VALID_ORDER_STATUSES)}'
    )


def test_fix_migration_is_the_last_to_declare_the_constraint():
    """063 必须是**应用顺序上最后一个**声明 order_status_check 的迁移。

    这条至关重要：`pg_standalone_002`（错误集合）正是因为排在 008 之后而覆盖了它。
    """
    declarers = [
        rev for rev, path in _apply_order_and_paths()
        if _CONSTRAINT_RE.search(path.read_text(encoding='utf-8'))
    ]
    assert len(declarers) >= 2, (
        f'预期至少 002/008/063 三条声明该约束，实际只找到 {declarers} —— '
        '查找方式可能又退化成按文件名拼路径'
    )
    assert declarers[-1] == FIX_REVISION, (
        f'最后一个声明 order_status_check 的是 {declarers[-1]}，不是 {FIX_REVISION}；'
        f'完整顺序: {declarers}'
    )


def test_migration_graph_has_single_head():
    """新增迁移后仍须保持单一 head。"""
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    cfg = Config(str(ROOT / 'alembic.ini'))
    heads = ScriptDirectory.from_config(cfg).get_heads()
    assert len(heads) == 1, f'出现多 head: {heads}'
