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
2. `test_upgrade_backs_up_then_dedupes_then_swaps_index`：顺序必须是
   「数重复 → 备份 → 删除 → 换索引」，且换索引必须显式 DROP 同名 non-unique；
3. `test_env_whitelist_no_longer_exempts_the_index`：白名单已摘掉该索引；
4. `test_model_declares_unique_index`：模型侧仍是 unique（两边口径的唯一真相源）；
5. `test_dedupe_keeps_most_filled_row_and_backup_holds_the_rest`（真实测试库、跑完回滚）：
   三行同 `(role_id, version_no, part_name)`、只有一行填过布料 → 保留**填过的那行**
   （不是最早那行，OCR 复审 H-1），被删的两行完整出现在备份表里，再建 UNIQUE 索引后
   插重复行被数据库拒绝。
"""
from __future__ import annotations

import ast
import inspect
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

    # 2026-11-28 迁移 pg_standalone_123（摘审批系统）上线后 head 前进到 123；
    # 122 回归为中间节点。断言 head 唯一且是最新迁移，并锁 121→122→123 的链。
    assert len(script.get_heads()) == 1, (
        '迁移图出现多 head —— alembic upgrade head 会直接失败'
    )
    assert script.get_heads()[0] == 'pg_standalone_123_remove_approval_system'
    rev = script.get_revision('pg_standalone_122_csp_part_unique_index')
    assert rev.down_revision == 'pg_standalone_121_seed_outsource_preset_manage'


def test_upgrade_backs_up_then_dedupes_then_swaps_index():
    src = inspect.getsource(mig.upgrade)
    # 顺序即语义：先数重复，再备份，再删除，最后换索引
    assert src.index('_count_sql(') < src.index('_backup_sql('), '必须先数重复再备份'
    assert src.index('_backup_sql(') < src.index('_dedupe_sql('), (
        '必须先备份再删除 —— 删掉的重复行要能从备份表补回（OCR 复审 H-1）'
    )
    assert src.index('_dedupe_sql(') < src.index('run_concurrently('), (
        '去重必须发生在换索引之前：UNIQUE 建在有重复行的表上会直接失败'
    )
    # 没有重复组时不许凭空建备份表（干净库上多一张 DB-only 表会让漂移门禁多报）
    assert 'if dup_rows == 0' in src
    assert 'DROP INDEX CONCURRENTLY IF EXISTS' in src, (
        '必须显式 DROP 同名 non-unique 索引 —— 否则 CREATE ... IF NOT EXISTS 因同名静默跳过'
    )
    assert 'CREATE UNIQUE INDEX CONCURRENTLY' in src
    # 空库/缺表守卫：pg_standalone_001 未建出基础 schema 时整条空转
    assert 'base_schema_absent()' in src
    assert 'table_exists(' in src


def test_dedupe_keeps_most_filled_row_not_earliest():
    """保留行的选择：信息最全者优先，并列才回落到 id 最小（OCR 复审 H-1 ②）。"""
    cte = mig._dup_cte('t')
    assert 'fabric_name IS NOT NULL' in cte and 'unit_price IS NOT NULL' in cte, (
        '保留行判定必须按「非空业务字段数量」，不能只取 MIN(id)'
    )
    assert 'DESC, id ASC' in cte, '并列时应回落到 id 最小的那行（结果可复现）'


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
# 真实 PostgreSQL：备份 + 去重语义 + UNIQUE 索引兜底效力（事务内，跑完回滚）
# ---------------------------------------------------------------------------
_PROBE_TABLE = 'p122_dedupe_probe'
_PROBE_BAK = 'p122_dedupe_probe_bak'


def _sync_test_db_url() -> str:
    from fastapi_app.tests._test_db_guard import resolve_test_db_url

    url = resolve_test_db_url()
    return url.replace('+asyncpg', '+psycopg') if '+asyncpg' in url else url


def test_dedupe_backup_and_unique_index_on_real_pg():
    """造重复行 → 备份 → 去重 → 只剩保留行 → UNIQUE 索引拒绝再插重复。零持久变更。"""
    from sqlalchemy import create_engine
    from sqlalchemy.pool import NullPool

    engine = create_engine(_sync_test_db_url(), poolclass=NullPool)
    try:
        with engine.connect() as conn:
            trans = conn.begin()
            try:
                # 用真实 customer_sampling_part 的列形状建临时探针表
                conn.execute(text(
                    f'CREATE TEMP TABLE {_PROBE_TABLE} ('
                    'id serial PRIMARY KEY, role_id integer NOT NULL, '
                    'version_no varchar(8) NOT NULL, part_name varchar(100) NOT NULL, '
                    'fabric_name varchar(200), fabric_spec varchar(200), '
                    'fabric_color_no varchar(50), supplier_id integer, '
                    'unit_price numeric(12,2), delivery_days integer, remark text)'
                ))
                # 三行同组：只有最后一行填过布料与单价（信息最全 → 应被保留）
                conn.execute(text(
                    f"INSERT INTO {_PROBE_TABLE} (role_id, version_no, part_name) "
                    "VALUES (1, 'T1', '头部'), (1, 'T1', '头部')"
                ))
                conn.execute(text(
                    f"INSERT INTO {_PROBE_TABLE} (role_id, version_no, part_name, fabric_name, unit_price) "
                    "VALUES (1, 'T1', '头部', '棉布A', 12.50)"
                ))
                # 另一组：单行填充，用于确认「未被判重复」的行不受影响
                conn.execute(text(
                    f"INSERT INTO {_PROBE_TABLE} (role_id, version_no, part_name) "
                    "VALUES (1, 'T2', '头部')"
                ))

                assert conn.execute(text(mig._count_sql(_PROBE_TABLE))).scalar() == 2, (
                    '待删行数应为 2（T1 组 3 行留 1）'
                )

                conn.execute(text(mig._backup_sql(_PROBE_BAK, _PROBE_TABLE)))
                removed = conn.execute(text(mig._dedupe_sql(_PROBE_TABLE))).rowcount
                assert removed == 2

                kept = conn.execute(text(
                    f'SELECT version_no, fabric_name FROM {_PROBE_TABLE} ORDER BY version_no'
                )).all()
                assert [row[0] for row in kept] == ['T1', 'T2'], kept
                assert kept[0][1] == '棉布A', (
                    '保留的应是「填过布料」的那行，不是最早的空壳行（OCR 复审 H-1 ②）'
                )

                backed_up = conn.execute(text(
                    f'SELECT count(*) FROM {_PROBE_BAK} WHERE fabric_name IS NULL'
                )).scalar()
                assert backed_up == 2, '被删的两行必须完整留在备份表里（可回滚恢复）'
                assert conn.execute(text(
                    f'SELECT count(*) FROM {_PROBE_BAK} WHERE _backed_up_at IS NOT NULL'
                )).scalar() == 2

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
