"""customer_sampling_part: (role_id, version_no, part_name) 真正建成 UNIQUE

Revision ID: pg_standalone_122_csp_part_unique_index
Revises: pg_standalone_121_seed_outsource_preset_manage
Create Date: 2026-11-17

背景（2026-11-17 上线前审计 P1-15）
------------------------------------
ORM 在 ``CustomerSamplingPart.__table_args__`` 声明::

    Index('idx_csp_role_part_version', 'role_id', 'version_no', 'part_name', unique=True)

但**库上的同名索引是 non-unique**：``pg_standalone_028`` 建它时库里已有重复行
（该迁移注释记载「project_id=384 等项目同 (T1, 头部) 有 4 行」），故刻意按普通索引建，
只留应用层 ``_ensure_part_name_unique`` 兜底。``migrations/env.py`` 的
``_IGNORED_DB_ONLY_INDEXES`` 又把它整条豁免 —— 于是「模型声明唯一、库里不唯一」这件事连
漂移门禁都看不见：任何绕过应用层校验的写入（并发事务、脚本、直连 SQL）都能造出重复部位
行，而这一层的唯一性正是「同角色同版本部位名唯一」这条业务约束的最终防线。

本迁移把两边对齐：先备份+去重，再建成真正的 UNIQUE，并同步摘掉 env.py 的白名单条目。

步骤（顺序即语义）
------------------
1. **数重复**（事务内）：同 ``(role_id, version_no, part_name)`` 且 ``count(*) > 1`` 的组。
   没有任何重复组时**整步跳过** —— 不建备份表、不写库，避免在干净库上凭空多出一张
   DB-only 表（那会让漂移门禁多报一项）。
2. **先备份、后删除**（同一事务，2026-11-17 OCR 复审 H-1）：
   - 把**即将被删的行**整行拷进 ``csp_part_dedupe_bak_20261117``（附 ``_backed_up_at``），
     删错了可以原样补回；这张表按需创建，人工复核后可 DROP（它的存在会在漂移报告里
     显式出现 —— 这是刻意的，不做白名单隐身）。
   - 保留哪一行**不是简单取 MIN(id)**：按「非空业务字段数量」降序、再按 id 升序取第一
     行。重复行是同一部位在同角色同版本下的历史残留，用户往往只在其中一行上填过布料/
     供应商/单价，取最早那行可能留下一个空壳、丢掉后来补录的信息。
   - 删除行数、组数、保留/删除的 id 全部写进迁移日志（alembic 输出），事后可复核。
3. **换索引**（事务外，CONCURRENTLY）：先 DROP 掉 non-unique 的同名索引，再建 UNIQUE
   同名索引。

失败语义（务必知道）
--------------------
- 第 1、2 步在同一事务内，失败则整体回滚（数据不动）。
- ``autocommit_block()`` 会先提交第 1、2 步再跑第 3 步 —— 这是 ``CREATE INDEX
  CONCURRENTLY`` 不能在事务块内执行的硬约束。因此若第 3 步失败（例如并发写入恰好撞上
  唯一键），**数据已去重并已备份**，但表处于「旧索引已删、新索引未建成」状态：
  此时必须**重跑本迁移**（全流程幂等：备份表 IF NOT EXISTS、删除第二次 0 行、DDL 带
  IF EXISTS/IF NOT EXISTS），重跑前该表没有唯一索引，应用层校验仍在兜底。
- ``downgrade`` 只换回 non-unique 索引，**不恢复已删数据** —— 需要时从
  ``csp_part_dedupe_bak_20261117`` 手工补回。

幂等性：重复升级不会失败（数重复/备份/删除/DDL 各自幂等）。
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
#: 去重时被删行的备份表（按需创建；人工复核后可 DROP）
_BACKUP_TABLE = 'csp_part_dedupe_bak_20261117'

#: 重复组与「保留行」的判定。三列在生产库里都是 NOT NULL
#: （见 shared_models/customer_sampling.py；迁移链里 part_name/version_no/role_id 均已
#: NOT NULL），故用 `=` 精确匹配即可，无需 IS NOT DISTINCT FROM。
#: 保留行 = 非空业务字段最多者（信息最全），并列时取 id 最小的（最早那行）。
_DUP_CTE = """
  SELECT role_id, version_no, part_name,
         (array_agg(id ORDER BY (
              (fabric_name IS NOT NULL)::int
            + (fabric_spec IS NOT NULL)::int
            + (fabric_color_no IS NOT NULL)::int
            + (supplier_id IS NOT NULL)::int
            + (unit_price IS NOT NULL)::int
            + (delivery_days IS NOT NULL)::int
            + (remark IS NOT NULL)::int
         ) DESC, id ASC))[1] AS keep_id,
         count(*) AS dup_count
  FROM {table}
  GROUP BY role_id, version_no, part_name
  HAVING count(*) > 1
"""


def _dup_cte(table: str = _TABLE) -> str:
    """重复组 CTE（``role_id, version_no, part_name, keep_id, dup_count``）。

    表名做成参数：本仓测试库已由 ORM 建出 UNIQUE 索引（插不进重复行），
    回归用例改用临时表验证这段 SQL 的语义。
    """
    return _DUP_CTE.format(table=table)


def _count_sql(table: str = _TABLE) -> str:
    """待删（重复且非保留）行数。"""
    return (
        f'SELECT count(*) FROM {table} AS p JOIN ({_dup_cte(table)}) AS d '
        'USING (role_id, version_no, part_name) '
        'WHERE p.id <> d.keep_id'
    )


def _backup_sql(backup_table: str = _BACKUP_TABLE, table: str = _TABLE) -> str:
    """把「即将被删的重复行」整行备份出来（含 ``_backed_up_at``）。"""
    return (
        f'CREATE TABLE IF NOT EXISTS {backup_table} AS '
        f'SELECT p.*, now() AS _backed_up_at FROM {table} AS p '
        f'JOIN ({_dup_cte(table)}) AS d USING (role_id, version_no, part_name) '
        'WHERE p.id <> d.keep_id'
    )


def _dedupe_sql(table: str = _TABLE) -> str:
    """删除重复行、每组保留一行（与 :func:`_backup_sql` 同一判定）。"""
    return (
        f'DELETE FROM {table} AS p USING ({_dup_cte(table)}) AS d '
        'WHERE p.role_id = d.role_id AND p.version_no = d.version_no '
        'AND p.part_name = d.part_name AND p.id <> d.keep_id'
    )


def upgrade() -> None:
    # 空库守卫：pg_standalone_001 尚未建出基础 schema 时整条增量迁移空转。
    if base_schema_absent() or not table_exists(_TABLE):
        return

    bind = op.get_bind()

    # 1) 数重复：没有重复组就什么都不做（不在干净库上凭空建备份表）
    dup_rows = int(bind.execute(text(_count_sql(_TABLE))).scalar() or 0)
    if dup_rows == 0:
        print(f'[pg_standalone_122] {_TABLE} 无重复行，跳过备份/去重')
    else:
        # 2) 先备份、后删除（同一事务；失败整体回滚，数据不动）
        bind.execute(text(_backup_sql(_BACKUP_TABLE, _TABLE)))
        removed = bind.execute(text(_dedupe_sql(_TABLE))).rowcount
        print(
            f'[pg_standalone_122] {_TABLE} 重复行 {dup_rows} 行已备份到 {_BACKUP_TABLE}，'
            f'已删除 {removed} 行（每组保留信息最全、id 最小的那行）'
        )

    # 3) 换成真正的 UNIQUE：同名 non-unique 索引必须删掉，否则
    #    CREATE ... IF NOT EXISTS 会因同名而静默跳过（这正是 054 留下分叉的原因）。
    run_concurrently([
        f'DROP INDEX CONCURRENTLY IF EXISTS {_INDEX_NAME}',
        f'CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS {_INDEX_NAME} '
        f'ON {_TABLE} (role_id, version_no, part_name)',
    ])


def downgrade() -> None:
    if base_schema_absent() or not table_exists(_TABLE):
        return
    # 回滚到 028 的形态：普通（非唯一）索引。
    # **不恢复已删数据** —— 需要时从 _BACKUP_TABLE 手工补回（重复行本身违反业务约束）。
    run_concurrently([
        f'DROP INDEX CONCURRENTLY IF EXISTS {_INDEX_NAME}',
        f'CREATE INDEX CONCURRENTLY IF NOT EXISTS {_INDEX_NAME} '
        f'ON {_TABLE} (role_id, version_no, part_name)',
    ])
