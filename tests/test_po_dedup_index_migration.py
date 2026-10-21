"""uq_po_pending_dedup 唯一索引的结构性回归（审计 Z08-R4，主报告 F1-12 族）。

背景：`purchase_order` 的 pending 去重索引在迁移链上被**三个**迁移重建过：

    add_po_dedup_unique_index          (customer_id, supplier_id, source_order_ids)
    rebuild_po_dedup_index             (COALESCE(customer_id,0), COALESCE(supplier_id,0), ...)
    rebuild_po_dedup_use_supplier_name (COALESCE(customer_id,0), COALESCE(supplier_name,''), ...)  ← 权威

前两条用 supplier_id，会把 BOM 物料里 ``supplier_id`` 全为 NULL 的不同供应商
新单并进同一 bucket 互相冲突（/purchase 一键审核报「已存在 0 个对应采购单」，
实证记录见 ``rebuild_po_dedup_use_supplier_name.py`` docstring）。修复版与旧版
**分处两条分支**，经 merge 汇合，所以终态由 alembic 的拓扑执行序决定，而不是
文件名直觉顺序。

同一形状的伪影真实发生过：`order_status_check` 因 `pg_standalone_002` 排在
`pg_standalone_008` 之后而覆盖了它，收口方式是链尾重声明 +
`tests/test_order_status_check_migration.py` 断言（本文件照该模式）。

本测试防**复发**：
  1. 应用顺序上最后一个声明该索引的迁移必须是 supplier_name 版；
  2. 该迁移的定义必须与 ORM 权威声明逐项一致（列 / UNIQUE / partial 谓词）。

不改动任何已应用到生产库的迁移 —— 只加断言，把「顺序翻转即测试变红」变成机器
门禁（审计修法给的「或改成幂等跳过」需要动存量迁移，风险高于收益，未采纳）。
"""
import ast
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
AUTHORITY_REVISION = 'rebuild_po_dedup_use_supplier_name'
INDEX_NAME = 'uq_po_pending_dedup'

_CREATE_RE = re.compile(
    rf'CREATE UNIQUE INDEX\s+(?:IF NOT EXISTS\s+)?{INDEX_NAME}(?!\w)', re.I)


def _apply_order_and_paths() -> list[tuple[str, pathlib.Path]]:
    """按 alembic 解析出的**应用顺序**（base → head）返回 (revision, 文件路径)。

    revision id 与文件名常不一致，故必须用 alembic 的 Script.path，不能按
    ``{revision}.py`` 拼路径 —— 否则会静默跳过正是要防的迁移，使断言空转。
    多 head 时 ``iterate_revisions('head', 'base')`` 直接抛错，故单 head 隐式覆盖。
    """
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    cfg = Config(str(ROOT / 'alembic.ini'))
    script = ScriptDirectory.from_config(cfg)
    scripts = list(script.iterate_revisions('head', 'base'))
    return [(s.revision, pathlib.Path(s.path)) for s in reversed(scripts)]


def _upgrade_source(path: pathlib.Path) -> str:
    """只取迁移文件里 ``upgrade()`` 的源码。

    必须按函数切：两条 rebuild 迁移的 ``downgrade()`` 会重建**旧**定义
    （supplier_id 版）。整文件 grep 会让权威迁移同时命中新旧两种列定义，
    断言变成自欺。
    """
    text = path.read_text(encoding='utf-8')
    tree = ast.parse(text)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == 'upgrade':
            return ast.get_source_segment(text, node) or ''
    return ''


def _declarers() -> list[tuple[str, str]]:
    """(revision, upgrade() 源码) —— 按应用顺序，仅含创建该索引的迁移。"""
    return [
        (rev, src) for rev, path in _apply_order_and_paths()
        if _CREATE_RE.search(src := _upgrade_source(path))
    ]


def _norm(sql: str) -> str:
    """去表名前缀、去空白、小写，便于比对 raw SQL 片段与 ORM 编译串。"""
    return re.sub(r'\s+', '', sql.replace('purchase_order.', '').lower())


def _sql_index_columns(upgrade_src: str) -> tuple[str, str]:
    """从 ``ON purchase_order (...) WHERE ...`` 取 (列清单, partial 谓词)。"""
    m = re.search(rf'{INDEX_NAME}\s+ON\s+\w+\s+\((.*)\)\s*WHERE\s+(.+?)\s*"""',
                  upgrade_src, re.DOTALL)
    assert m, f'未能从 upgrade() 里解析出 {INDEX_NAME} 的列定义：\n{upgrade_src}'
    return m.group(1), m.group(2)


def _orm_index():
    from fastapi_app.shared_models.purchase_order import PurchaseOrder

    for idx in PurchaseOrder.__table__.indexes:
        if idx.name == INDEX_NAME:
            return idx
    raise AssertionError('ORM 未声明 uq_po_pending_dedup')


def _orm_definition() -> tuple[list[str], bool, str]:
    """ORM 权威声明 → (归一化列清单, unique, 归一化谓词)。"""
    from sqlalchemy.dialects import postgresql

    idx = _orm_index()
    dialect = postgresql.dialect()
    cols = [_norm(str(e.compile(dialect=dialect, compile_kwargs={'literal_binds': True})))
            for e in idx.expressions]
    where = idx.dialect_options['postgresql'].get('where')
    where_str = _norm(str(where.compile(dialect=dialect, compile_kwargs={'literal_binds': True}))) \
        if where is not None else ''
    return cols, bool(idx.unique), where_str


def test_authority_revision_declares_the_index_in_upgrade():
    """扫描方式自证：权威迁移的 upgrade() 里是 supplier_name 版，且不含 supplier_id。

    这条锁定「整文件 grep 会把 downgrade() 的旧定义一起算进来」这个坑 ——
    downgrade() 里确实另有一份列定义，若查找方式退化成整文件搜索，
    同一条 CREATE 会被数两遍、新旧定义会混在一起，断言变成自欺。
    """
    path = dict(_apply_order_and_paths())[AUTHORITY_REVISION]
    whole = path.read_text(encoding='utf-8')
    upgrade = _upgrade_source(path)
    assert _CREATE_RE.search(upgrade), 'upgrade() 未创建 uq_po_pending_dedup'
    assert 'supplier_name' in upgrade, f'upgrade() 不是 supplier_name 版:\n{upgrade}'
    assert 'supplier_id' not in upgrade, 'upgrade() 里混入 supplier_id 列定义'
    assert len(_CREATE_RE.findall(whole)) > len(_CREATE_RE.findall(upgrade)), (
        '该迁移的 downgrade() 不再用另一份定义重建索引 —— 本文件按 upgrade() 切分扫描'
        '的理由需要同步复核（若已改成幂等跳过，可放宽本断言）'
    )


def test_index_is_rebuilt_by_three_migrations():
    """链上声明该索引的迁移数量与身份不得悄悄变化（防扫描退化 / 新增声明者）。"""
    revisions = [rev for rev, _ in _declarers()]
    assert revisions == [
        'add_po_dedup_unique_index',
        'rebuild_po_dedup_index',
        AUTHORITY_REVISION,
    ], f'声明 {INDEX_NAME} 的迁移序列变化: {revisions}'


def test_last_migration_to_declare_the_index_is_the_supplier_name_version():
    """应用顺序上最后一个声明者必须是 supplier_name 版（终态正确性的核心断言）。"""
    declarers = _declarers()
    assert declarers[-1][0] == AUTHORITY_REVISION, (
        f'最后声明 {INDEX_NAME} 的是 {declarers[-1][0]}（{AUTHORITY_REVISION} 之后又有人重建了它），'
        f'去重终态会静默回退到 supplier_id 版；完整顺序: {[r for r, _ in declarers]}'
    )


def test_tail_migration_definition_matches_orm_authority():
    """链尾迁移的列清单 / UNIQUE / partial 谓词必须逐项等于 ORM 声明。"""
    tail_src = _declarers()[-1][1]
    orm_cols, orm_unique, orm_where = _orm_definition()
    sql_cols, sql_where = _sql_index_columns(tail_src)

    assert _norm(sql_cols) == ','.join(orm_cols), (
        f'迁移列定义与 ORM 不一致:\n  迁移: {_norm(sql_cols)}\n  ORM : {",".join(orm_cols)}'
    )
    assert 'unique' in _CREATE_RE.search(tail_src).group(0).lower(), '迁移侧丢了 UNIQUE'
    assert orm_unique, 'ORM 侧索引不是 unique'
    assert _norm(sql_where) == orm_where, (
        f'partial 谓词与 ORM 不一致:\n  迁移: {_norm(sql_where)}\n  ORM : {orm_where}'
    )


def test_orm_authority_uses_supplier_name_not_supplier_id():
    """ORM 权威本身也必须是 supplier_name 版（否则上面的比对会一起错）。"""
    orm_cols, _, orm_where = _orm_definition()
    assert orm_cols == [
        _norm('coalesce(customer_id, 0)'),
        _norm("coalesce(supplier_name, '')"),
        _norm('source_order_ids'),
    ], f'ORM 列清单变化: {orm_cols}'
    assert orm_where == _norm("status = 'pending'"), f'ORM 谓词变化: {orm_where}'
