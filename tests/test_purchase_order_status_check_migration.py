"""purchase_order.status CHECK 约束结构性回归（审计 P1-16）。

约束集合必须与 ORM 的 PurchaseOrderStatus.ALL 逐字一致；迁移须是链上最后
一个声明该约束的迁移，且新增后仍保持单一 head。
"""
import ast
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
FIX_REVISION = 'pg_standalone_102_purchase_order_status_check'
_CONSTRAINT_RE = re.compile(r'ADD CONSTRAINT purchase_order_status_check')


def _apply_order_and_paths() -> list[tuple[str, pathlib.Path]]:
    """按 alembic 解析出的应用顺序（base → head）返回 (revision, 文件路径)。"""
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    cfg = Config(str(ROOT / 'alembic.ini'))
    script = ScriptDirectory.from_config(cfg)
    scripts = list(script.iterate_revisions('head', 'base'))
    return [(s.revision, pathlib.Path(s.path)) for s in reversed(scripts)]


def test_migration_set_matches_orm_authority():
    from fastapi_app.shared_models.purchase_order import PurchaseOrderStatus

    path = dict(_apply_order_and_paths())[FIX_REVISION]
    tree = ast.parse(path.read_text(encoding='utf-8'))
    literal = None
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            getattr(t, 'id', None) == 'PURCHASE_ORDER_STATUSES' for t in node.targets
        ):
            literal = ast.literal_eval(node.value)
    assert literal is not None, '未在 102 里找到 PURCHASE_ORDER_STATUSES 常量'
    assert frozenset(literal) == frozenset(PurchaseOrderStatus.ALL), (
        f'迁移集合与 ORM 不一致:\n  迁移: {sorted(literal)}\n'
        f'  ORM : {sorted(PurchaseOrderStatus.ALL)}'
    )


def test_migration_is_the_last_to_declare_the_constraint():
    declarers = [
        rev for rev, path in _apply_order_and_paths()
        if _CONSTRAINT_RE.search(path.read_text(encoding='utf-8'))
    ]
    assert declarers, '没有任何迁移声明 purchase_order_status_check'
    assert declarers[-1] == FIX_REVISION, (
        f'最后一个声明 purchase_order_status_check 的是 {declarers[-1]}，'
        f'不是 {FIX_REVISION}；完整顺序: {declarers}'
    )


def test_migration_graph_has_single_head():
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    cfg = Config(str(ROOT / 'alembic.ini'))
    heads = ScriptDirectory.from_config(cfg).get_heads()
    assert len(heads) == 1, f'出现多 head: {heads}'
