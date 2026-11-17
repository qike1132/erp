"""P1-15：`idx_csp_role_part_version` 真正建成 UNIQUE（迁移 pg_standalone_122）。

## 拦哪种出错

ORM 在 `CustomerSamplingPart.__table_args__` 声明
`Index('idx_csp_role_part_version', 'role_id','version_no','part_name', unique=True)`，
而库上同名索引是 **non-unique**：`pg_standalone_028` 建它时库里已有重复行，刻意按普通
索引建，只留应用层 `_ensure_part_name_unique` 兜底。随后 `migrations/env.py` 的
`_IGNORED_DB_ONLY_INDEXES` 又把它整条豁免 —— 于是「模型要唯一、库里不唯一」这件事
连漂移门禁都看不见，任何人绕过应用层校验写入（并发事务、脚本、直连 SQL）都能造出
重复部位行。

## 本文件各锁一件事

1. `test_migration_is_single_head_revising_121`：迁移图仍是单 head，且 122 接在 121 上；
2. `test_upgrade_dedupes_before_swapping_index`：必须先跑去重 SQL、再在事务外
   DROP 旧索引并 CREATE **UNIQUE**（顺序反了或少了 DROP 都会让 IF NOT EXISTS 空转）；
3. `test_env_whitelist_no_longer_exempts_the_index`：白色单已摘掉该索引，漂移门禁重新看得见它；
4. `test_model_declares_unique_index`：模型侧仍是 unique（两边口径的唯一真相源）；
5. `test_dedupe_sql_and_unique_index_on_real_pg`：真实测试库（事务内、跑完回滚）造重复行 →
   跑迁移用的同一段去重 SQL → 只剩每组最小 id → 再建 UNIQUE 索引后插重复行被数据库拒绝。
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

import migrations.versions.pg_standalone_122_csp_part_unique_index as mig
from fastapi_app.shared_models.customer_sampling import CustomerSamplingPart

_REPO = Path(__file__).resolve().parents[2]
_ENV_PY = _REPO / 'migrations' / 'env.py'
_INDEX = 'idx_csp_role_part_version'


def test_migration_is_single_head_revising_121():
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    # 显式给 script_location（alembic.ini 里那行是相对路径，取决于 CWD；
    # alembic.ini 顶部注释也建议手工构造 Config 时这样写）
    cfg = Config()
    cfg.set_main_option('script_location', str(_REPO / 'migrations'))
    script = ScriptDirectory.from_config(cfg)
    assert script.get_heads() == ['pg_standalone_122_csp_part_unique_index'], (
        '迁移图出现多 head —— alembic upgrade head 会直接失败'
    )
    rev = script.get_revision('pg_standalone_122_csp_part_unique_index')
    assert rev.down_revision == 'pg_standalone_121_seed_outsource_preset_manage'


def test_upgrade_dedupes_before_swapping_index():
    import inspect

    src = inspect.getsource(mig.upgrade)
    assert '_dedupe_sql(' in src, 'upgrade 没有跑去重'
    assert src.index('_dedupe_sql(') < src.index('run_concurrently('), (
        '去重必须发生在换索引之前：UNIQUE 建在有重复行的表上会直接失败'
    )
    assert 'DROP INDEX CONCURRENTLY IF EXISTS' in src, (
        '必须显式 DROP 同名 non-unique 索引 —— 否则 CREATE ... IF NOT EXISTS 因同名静默跳过'
    )
    assert 'CREATE UNIQUE INDEX CONCURRENTLY' in src
    # 空库/缺表守卫：pg_standalone_001 未建出基础 schema 时整条空转
    assert 'base_schema_absent()' in src
    assert 'table_exists(' in src


def test_env_whitelist_no_longer_exempts_the_index():
    """白名单若仍豁免该索引，漂移门禁就永远看不到「模型 unique / 库 non-unique」。"""
    tree = ast.parse(_ENV_PY.read_text(encoding='utf-8'))
    assignment = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == '_IGNORED_DB_ONLY_INDEXES' for t in node.targets)
    )
    entries = {
        elt.value for elt in assignment.value.elts
        if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
    }
    assert _INDEX not in entries, f'{_INDEX} 仍在 _IGNORED_DB_ONLY_INDEXES 里'


def test_model_declares_unique_index():
    indexes = {ix.name: ix for ix in CustomerSamplingPart.__table__.indexes}
    ix = indexes.get(_INDEX)
    assert ix is not None, '模型不再声明该索引'
    assert ix.unique is True, '模型侧必须保持 unique —— 迁移的目标状态就是它'


# ---------------------------------------------------------------------------
# 真实 PostgreSQL：去重 SQL 的语义 + UNIQUE 索引的兜底效力（事务内，跑完回滚）
# ---------------------------------------------------------------------------
_PROBE_TABLE = 'p122_dedupe_probe'


def _sync_test_db_url() -> str:
    from fastapi_app.tests._test_db_guard import resolve_test_db_url

    url = resolve_test_db_url()
    return url.replace('+asyncpg', '+psycopg') if '+asyncpg' in url else url


def test_dedupe_sql_and_unique_index_on_real_pg():
    """造重复行 → 跑去重 → 只剩每组最小 id → UNIQUE 索引拒绝再插重复。零持久变更。"""
    from sqlalchemy import create_engine
    from sqlalchemy.pool import NullPool

    engine = create_engine(_sync_test_db_url(), poolclass=NullPool)
    try:
        with engine.connect() as conn:
            trans = conn.begin()
            try:
                conn.execute(text(
                    f'CREATE TEMP TABLE {_PROBE_TABLE} ('
                    'id serial PRIMARY KEY, role_id integer NOT NULL, '
                    'version_no varchar(8) NOT NULL, part_name varchar(100) NOT NULL)'
                ))
                for _ in range(3):
                    conn.execute(text(
                        f"INSERT INTO {_PROBE_TABLE} (role_id, version_no, part_name) "
                        "VALUES (1, 'T1', '头部')"
                    ))
                conn.execute(text(
                    f"INSERT INTO {_PROBE_TABLE} (role_id, version_no, part_name) "
                    "VALUES (1, 'T2', '头部')"
                ))

                conn.execute(text(mig._dedupe_sql(_PROBE_TABLE)))

                kept = conn.execute(text(
                    f'SELECT id, version_no FROM {_PROBE_TABLE} ORDER BY version_no'
                )).all()
                assert [row[1] for row in kept] == ['T1', 'T2'], kept
                assert kept[0][0] == 1, '应保留每组 id 最小的那行'

                # 换索引后的兜底效力：UNIQUE 索引必须拒绝重复
                conn.execute(text(
                    f'CREATE UNIQUE INDEX {_PROBE_TABLE}_uq '
                    f'ON {_PROBE_TABLE} (role_id, version_no, part_name)'
                ))
                with pytest.raises(IntegrityError):
                    with conn.begin_nested():
                        conn.execute(text(
                            f"INSERT INTO {_PROBE_TABLE} (role_id, version_no, part_name) "
                            "VALUES (1, 'T1', '头部')"
                        ))
            finally:
                trans.rollback()
    finally:
        engine.dispose()
