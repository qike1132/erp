"""空库守卫与历史迁移加固工具。

背景
----
head（`pg_standalone_054_sync_schema_with_orm_metadata`）之下混着两类迁移：

* `pg_standalone_001` —— 自包含的建库迁移，从 ORM 模型建出全部表；
* 其余大量「增量」迁移（MySQL 时代 + 早期 PG 期）—— 假定目标表**已经存在**。

Alembic 按拓扑序执行，`pg_standalone_001` 并不总是排在前面，因此空库上
`alembic upgrade head` 会因表/列不存在而失败，`.github/workflows/ci-cd.yml`
的 `upgrade head` + `check` 门禁因此无法通过。

守卫语义
--------
`base_schema_absent()` 仅在**基础 schema 完全不存在**时为真：

* 空库首次 `upgrade head`：`product` / `customer` 都还没建 -> 该增量迁移整体空转；
* 遗留库（由 MySQL 迁移而来）或已建库：标记表存在 -> 返回假，迁移照常执行。

即：本守卫只把「原本必然报错」的场景变成 no-op，不改变任何正常升级路径的语义。
标记表取 MySQL 时代就存在的 `product` 与 `customer`，且要求**两者同时缺失**
才判定为空库，避免误跳过。

其余工具函数（`table_exists` / `table_columns` / `create_index_if_columns_exist`
/ `execute_if_columns_exist` / `run_concurrently`）用于让历史迁移在**空库重放**
时对「表/列稍后才由其它分支迁移建出」的情形免疫；重放终态与 ORM 元数据的一致性
由 `pg_standalone_054_sync_schema_with_orm_metadata` 统一兜底。
"""

from alembic import context, op
from sqlalchemy import inspect as sa_inspect
from sqlalchemy import text

_BASE_SCHEMA_MARKERS = ('product', 'customer')


def base_schema_absent() -> bool:
    """基础 schema 完全不存在时返回 True（空库首次 upgrade head）。"""
    if context.is_offline_mode():
        return False
    bind = op.get_bind()
    for name in _BASE_SCHEMA_MARKERS:
        found = bind.execute(
            text('SELECT to_regclass(:n) IS NOT NULL'), {'n': name}
        ).scalar()
        if found:
            return False
    return True


def table_columns(table_name: str):
    """返回表的列名集合；表不存在时返回 None。"""
    inspector = sa_inspect(op.get_bind())
    if not inspector.has_table(table_name):
        return None
    return {col['name'] for col in inspector.get_columns(table_name)}


def table_exists(table_name: str) -> bool:
    """表是否存在（offline 模式无法探测，按存在处理）。"""
    if context.is_offline_mode():
        return True
    return table_columns(table_name) is not None


def _columns_ready(*requirements) -> bool:
    for table, column in requirements:
        present = table_columns(table)
        if present is None or column not in present:
            return False
    return True


def create_index_if_columns_exist(index_name, table_name, columns, **kwargs):
    """表与全部列都存在时才建索引，否则整体跳过。

    历史迁移引用的列名可能已被后续迁移改名或删除，例如 `purchase_order`
    的 `created_at` / `customer` 在 PG 基线 schema 中分别叫 `create_time` /
    `customer_name`。空库重放时这类索引本就无从建立，且 ORM 元数据也不再
    声明它，跳过即可；正常增量升级路径下这些列都存在，行为与改动前一致。

    offline（`--sql`）模式无 DB 可探测，退回无条件的 `create_index`。
    """
    columns = list(columns)
    if context.is_offline_mode():
        op.create_index(index_name, table_name, columns, **kwargs)
        return
    present = table_columns(table_name)
    # 仅校验字符串列名；表达式索引（sa.literal_column 等）无法直接比对列名
    if present is None or any(c not in present for c in columns if isinstance(c, str)):
        return
    op.create_index(index_name, table_name, columns, **kwargs)


def drop_index_if_columns_exist(index_name, table_name, columns, **kwargs):
    """`create_index_if_columns_exist` 的 downgrade 对应实现。"""
    columns = list(columns)
    if context.is_offline_mode():
        op.drop_index(index_name, table_name=table_name, **kwargs)
        return
    present = table_columns(table_name)
    if present is None or any(c not in present for c in columns if isinstance(c, str)):
        return
    op.drop_index(index_name, table_name=table_name, **kwargs)


def execute_if_columns_exist(sql, *requirements):
    """裸 SQL 版的 `create_index_if_columns_exist`。

    `requirements` 为若干 `(表名, 列名)` 对；全部存在才执行 `sql`，
    否则整体跳过并返回 False。
    """
    if context.is_offline_mode():
        op.execute(text(sql))
        return True
    if not _columns_ready(*requirements):
        return False
    op.execute(text(sql))
    return True


def filter_ready(statements):
    """`(sql, [(表, 列), ...])` 序列 -> 只保留前置表列齐备的 sql 列表。"""
    if context.is_offline_mode():
        return [sql for sql, _ in statements]
    return [sql for sql, reqs in statements if _columns_ready(*reqs)]


def run_concurrently(statements) -> None:
    """按序执行一批 DDL，且保证在事务块之外。

    `CREATE/DROP INDEX CONCURRENTLY` 不允许出现在事务块内。历史上多处用
    `connection.execute(text("COMMIT"))` 绕开事务，在 SQLAlchemy 2.x 下
    无效（COMMIT 不生效，随后语句以 InFailedSqlTransaction 失败），
    这里统一改用 Alembic 的 `autocommit_block()`。
    """
    statements = list(statements)
    if not statements:
        return
    if context.is_offline_mode():
        for ddl in statements:
            op.execute(text(ddl))
        return
    with op.get_context().autocommit_block():
        for ddl in statements:
            op.execute(text(ddl))


# --------------------------------------------------------------------------
# 收口迁移（pg_standalone_054）用的幂等包装
#
# 054 由 alembic autogenerate 依据「空库重放终态 vs ORM 元数据」的差异生成，
# 其中的 add/drop 操作按空库重放的状态书写；直接套用到已有库（如现网
# erp_system，其漂移项与本仓库空库重放并不一致）会以 Duplicate* / DoesNotExist
# 失败。下列包装保持相同调用签名，仅在对象已存在/不存在时跳过。
# --------------------------------------------------------------------------


def create_index_if_absent(index_name, table_name, columns, **kwargs):
    """按**索引名**判重后建索引（054 收口迁移专用，表达式索引同样适用）。

    与 `create_index_if_columns_exist` 的区别：后者按列存在性判断，适合历史
    增量迁移；本函数按名字判断，适合「把已有库对齐到 ORM」的收口迁移——此时
    索引可能已由别的迁移建好，只要同名就跳过，避免 DuplicateTable。
    """
    if context.is_offline_mode():
        op.create_index(index_name, table_name, columns, **kwargs)
        return
    if table_columns(table_name) is None:
        return
    existing = {ix['name'] for ix in sa_inspect(op.get_bind()).get_indexes(table_name)}
    if str(index_name) in existing:
        return
    op.create_index(index_name, table_name, columns, **kwargs)


def create_table_if_absent(table_name, *args, **kwargs):
    if table_exists(table_name):
        return
    op.create_table(table_name, *args, **kwargs)


def drop_table_if_exists(table_name, **kwargs):
    op.drop_table(table_name, if_exists=True, **kwargs)


def drop_table_if_empty(table_name, **kwargs):
    """仅在表不存在或行数为 0 时删除，防止破坏性 DDL 意外丢数据。

    offline 模式无法查询行数，按存在且可能非空处理并直接跳过删除。
    """
    if context.is_offline_mode() or not table_exists(table_name):
        return
    bind = op.get_bind()
    count = bind.execute(text(f'SELECT COUNT(*) FROM "{table_name}"')).scalar()
    if count:
        raise RuntimeError(
            f'表 {table_name} 非空（{count} 行），拒绝执行 054 的清理删除；'
            '请先人工确认并迁移/清理数据。'
        )
    op.drop_table(table_name, if_exists=True, **kwargs)


def drop_column_if_absent(table_name, column_name, **kwargs):
    """仅在列存在时删除；offline 模式退回 Alembic 的 if_exists 语义。"""
    if context.is_offline_mode():
        op.drop_column(table_name, column_name, if_exists=True, **kwargs)
        return
    if not table_exists(table_name):
        return
    present = table_columns(table_name)
    if present is None or column_name not in present:
        return
    op.drop_column(table_name, column_name, **kwargs)


# 兼容 054 自动生成代码的别名：语义是「列存在才删除」，不是列缺席才删除。
drop_column_if_exists = drop_column_if_absent


def add_column_if_absent(table_name, column):
    present = table_columns(table_name)
    if present is None or column.name in present:
        return
    op.add_column(table_name, column)


def alter_column_if_exists(table_name, column_name, **kwargs):
    present = table_columns(table_name)
    if present is None or column_name not in present:
        return
    op.alter_column(table_name, column_name, **kwargs)


def drop_index_if_exists(index_name, table_name=None, **kwargs):
    op.drop_index(index_name, table_name=table_name, if_exists=True, **kwargs)


def drop_constraint_if_exists(constraint_name, table_name, type_=None, **kwargs):
    op.drop_constraint(constraint_name, table_name, type_=type_, if_exists=True, **kwargs)


def _constraint_names(table_name, kind):
    if context.is_offline_mode():
        return None
    inspector = sa_inspect(op.get_bind())
    try:
        if kind == 'foreignkey':
            return {fk['name'] for fk in inspector.get_foreign_keys(table_name)}
        if kind == 'unique':
            return {uc['name'] for uc in inspector.get_unique_constraints(table_name)}
        if kind == 'check':
            return {cc['name'] for cc in inspector.get_check_constraints(table_name)}
    except Exception:  # 表不存在等 -> 交给 op 自身报错
        return None
    return None


def create_foreign_key_if_absent(constraint_name, source_table, referent_table,
                                 local_cols, remote_cols, **kwargs):
    names = _constraint_names(source_table, 'foreignkey')
    if constraint_name is not None and names is not None and constraint_name in names:
        return
    op.create_foreign_key(constraint_name, source_table, referent_table,
                          local_cols, remote_cols, **kwargs)


def create_unique_constraint_if_absent(constraint_name, table_name, columns, **kwargs):
    inspector = sa_inspect(op.get_bind())
    if table_exists(table_name):
        for constraint in inspector.get_unique_constraints(table_name):
            if sorted(constraint.get('column_names') or []) == sorted(columns):
                return
    op.create_unique_constraint(constraint_name, table_name, columns, **kwargs)
