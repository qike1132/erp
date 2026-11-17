"""customer_sampling_part: (role_id, version_no, part_name) 真正建成 UNIQUE

Revision ID: pg_standalone_122_csp_part_unique_index
Revises: pg_standalone_121_seed_outsource_preset_manage
Create Date: 2026-11-17

背景（2026-11-17 上线前审计 P1-15）
------------------------------------
ORM 在 ``CustomerSamplingPart.__table_args__`` 声明::

    Index('idx_csp_role_part_version', 'role_id', 'version_no', 'part_name', unique=True)

但**库上的同名索引是 non-unique**：``pg_standalone_028`` 建它时库里已有重复行
（该迁移注释记载「project_id=384 等项目同 (T1, 头部) 有 4 行」），故刻意按普通索引
建，只留应用层 ``_ensure_part_name_unique`` 兜底。``migrations/env.py`` 的
``_IGNORED_DB_ONLY_INDEXES`` 又把它整条豁免 —— 于是「模型声明唯一、库里不唯一」这件事
连漂移门禁都看不见：任何绕过应用层校验的写入（并发事务、脚本、直连 SQL）都能造出
重复部位行，而这一层的唯一性正是「同角色同版本部位名唯一」这条业务约束的最终防线。

本迁移把两边对齐：先去重，再建成真正的 UNIQUE，并同步摘掉 env.py 的白名单条目。

步骤
----
1. **去重**（事务内）：同 ``(role_id, version_no, part_name)`` 只保留 ``id`` 最小的一行。
   ``customer_sampling_part`` 没有任何子表外键引用它（全仓 grep 无 ``part_id`` 外键），
   故删除重复行不牵连其它数据；保留最早那行是为了让已有引用/排序尽量不变。
2. **换索引**（事务外，CONCURRENTLY）：先 DROP 掉 non-unique 的同名索引，再建 UNIQUE
   同名索引。两段之间有一个「无唯一约束」的短窗口（单条 DDL），窗口内并发写入仍由
   应用层 ``_ensure_part_name_unique`` 兜底 —— 这比锁表建索引安全得多（054 当年正是因为
   不肯锁表才没建 unique）。

幂等性：去重 DELETE 可重复执行（第二次删 0 行）；DROP/CREATE 分别带 IF EXISTS /
IF NOT EXISTS，重复升级不会失败。

回滚：恢复成 non-unique 同名索引（与 028 建出来的形态一致）。已删除的重复行不恢复。
"""
from alembic import op
from sqlalchemy import text

from migrations._legacy_base_guard import base_schema_absent, run_concurrently, table_exists

revision = 'pg_standalone_122_csp_part_unique_index'
down_revision = 'pg_standalone_121_seed_outsource_preset_manage'
branch_labels = None
depends_on = None

_INDEX_NAME = 'idx_csp_role_part_version'
_TABLE = 'customer_sampling_part'

#: 去重 SQL 模板：同 (role_id, version_no, part_name) 只留 id 最小的一行。
#: 三列在生产库里都是 NOT NULL（见 shared_models/customer_sampling.py），
#: 故用 `=` 精确匹配即可，无需 IS NOT DISTINCT FROM。
#: 表名做成参数：本仓测试库已由 ORM 建出 UNIQUE 索引（插不进重复行），
#: 回归用例改用临时表验证这段 SQL 的语义。
_DEDUPE_SQL_TEMPLATE = """
DELETE FROM {table} AS p
USING (
    SELECT role_id, version_no, part_name, MIN(id) AS keep_id
    FROM {table}
    GROUP BY role_id, version_no, part_name
    HAVING COUNT(*) > 1
) AS dup
WHERE p.role_id = dup.role_id
  AND p.version_no = dup.version_no
  AND p.part_name = dup.part_name
  AND p.id <> dup.keep_id
"""


def _dedupe_sql(table: str = _TABLE) -> str:
    """返回针对 ``table`` 的去重 DELETE 语句（默认生产表名）。"""
    return _DEDUPE_SQL_TEMPLATE.format(table=table)


def upgrade() -> None:
    # 空库守卫：pg_standalone_001 尚未建出基础 schema 时整条增量迁移空转。
    if base_schema_absent() or not table_exists(_TABLE):
        return

    # 1) 先去掉重复行 —— 必须在换索引之前、且在事务内完成（autocommit_block 会先把
    #    当前事务提交掉，保证 UNIQUE 建索引时看不到未提交的重复行）。
    op.execute(text(_dedupe_sql(_TABLE)))

    # 2) 换成真正的 UNIQUE：同名 non-unique 索引必须删掉，否则
    #    CREATE ... IF NOT EXISTS 会因同名而静默跳过（这正是 054 留下分叉的原因）。
    run_concurrently([
        f'DROP INDEX CONCURRENTLY IF EXISTS {_INDEX_NAME}',
        f'CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS {_INDEX_NAME} '
        f'ON {_TABLE} (role_id, version_no, part_name)',
    ])


def downgrade() -> None:
    if base_schema_absent() or not table_exists(_TABLE):
        return
    # 回滚到 028 的形态：普通（非唯一）索引。已删的重复行不恢复 —— 它们本身就是
    # 违反业务约束的数据。
    run_concurrently([
        f'DROP INDEX CONCURRENTLY IF EXISTS {_INDEX_NAME}',
        f'CREATE INDEX CONCURRENTLY IF NOT EXISTS {_INDEX_NAME} '
        f'ON {_TABLE} (role_id, version_no, part_name)',
    ])
