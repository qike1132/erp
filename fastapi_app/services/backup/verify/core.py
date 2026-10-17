"""恢复后验证 + 工具函数。"""
from __future__ import annotations

import contextlib
import hashlib
import logging
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from .._constants import (
    _CHECKSUM_EXCLUDE_TABLES,
    _TIMESTAMP_CANDIDATES,
    _ts_col_cache,
)

logger = logging.getLogger(__name__)


def quote_table(tname: str) -> str:
    """REV-08: 安全引用表名，防止 SQL 注入"""
    # 仅允许字母、数字、下划线
    if not tname.replace('_', '').replace('-', '').isalnum():
        raise ValueError(f'不安全的表名: {tname!r}')
    return f'"{tname}"'


def get_checksum_tables() -> set[str]:
    """获取需要校验和的表集合（排除 alembic_version）"""
    from fastapi_app.shared_models import Base
    return {str(t.name) for t in Base.metadata.sorted_tables if str(t.name) not in _CHECKSUM_EXCLUDE_TABLES}


async def build_schema_snapshot(db: AsyncSession) -> dict[str, list[dict]]:
    """采集表结构快照：public schema 各表列名/类型（供 L4 还原后 DDL 比对）。

    备份时写入 manifest['schema_snapshot']，还原后据此逐表比对列是否存在。
    """
    rows = (await db.execute(text(  # batch-loop: 逐表采集列定义,无法批量
        "SELECT table_name, column_name, data_type, is_nullable "
        "FROM information_schema.columns WHERE table_schema = 'public' "
        "ORDER BY table_name, ordinal_position"
    ))).fetchall()
    snapshot: dict[str, list[dict]] = {}
    for table_name, column_name, data_type, is_nullable in rows:
        snapshot.setdefault(table_name, []).append({
            'column': column_name,
            'type': data_type,
            'nullable': is_nullable == 'YES',
        })
    return snapshot


async def find_timestamp_column(tname: str, db: AsyncSession) -> str | None:
    """查找表的时间戳列（REV-33: 添加缓存）"""
    if tname in _ts_col_cache:
        return _ts_col_cache[tname]
    try:
        cols_result = await db.execute(
            text('SELECT column_name FROM information_schema.columns WHERE table_name = :tname ORDER BY ordinal_position'),
            {'tname': tname}
        )
        col_names = [r[0] for r in cols_result.fetchall()]
        for candidate in _TIMESTAMP_CANDIDATES:
            if candidate in col_names:
                _ts_col_cache[tname] = candidate
                return candidate
    except (SQLAlchemyError, OSError, ValueError) as e:
        logger.warning(f'查询表 {tname} 列信息失败: {e}')
    _ts_col_cache[tname] = None
    return None


async def query_table_rows(tname: str, db: AsyncSession, since: str | None = None) -> list[dict]:
    """查询表数据，支持按时间戳增量查询"""
    from ..json_backup import serialize_value
    ts_col = await find_timestamp_column(tname, db) if since else None
    qtname = quote_table(tname)  # REV-08
    if ts_col:
        # 时间戳列可能是 timestamptz（须绑 datetime）也可能是 varchar/text（须绑 str）。
        # 先试 datetime（覆盖绝大多数表），失败再回退字符串。
        since_dt: str | datetime | None = since
        if isinstance(since_dt, str):
            with contextlib.suppress(TypeError, ValueError):
                since_dt = datetime.strptime(since_dt, '%Y-%m-%d %H:%M:%S')
        try:
            result = await db.execute(
                text(f'SELECT * FROM {qtname} WHERE "{ts_col}" >= :since'),  # nosec B608 — qtname 经 quote_table 白名单校验; select-all: backup/restore 需要全表动态导出
                {'since': since_dt},
            )
        except DBAPIError:
            # 必须捕 DBAPIError，不能捕 sqlalchemy.exc.DataError：asyncpg 实际抛出的是
            # sqlalchemy.dialects.postgresql.asyncpg.Error（它的父类是 DBAPIError），
            # 而 DataError 永远匹配不到它 —— 原先只捕 DataError 使本回退成为**死代码**，
            # 于是 approval_request / approval_log（updated_at 为 varchar）在每一次增量
            # 备份中被静默跳过（2026-09-30 修复；证据见 logs/erp-arq.log 的
            # "增量备份表 approval_log 失败: ... (expected str, got datetime)"）。
            # 事务已失败，必须先 rollback 才能在新事务中重试
            with contextlib.suppress(SQLAlchemyError):
                await db.rollback()  # manual-tx: try/except 内显式事务控制
            result = await db.execute(
                text(f'SELECT * FROM {qtname} WHERE "{ts_col}" >= :since'),  # nosec B608 — qtname 经 quote_table 白名单校验; select-all: backup/restore 需要全表动态导出
                {'since': since},
            )
    else:
        result = await db.execute(text(f'SELECT * FROM {qtname}'))  # nosec B608 — qtname 经 quote_table 白名单校验; select-all: backup/restore 需要全表动态导出
    rows = result.mappings().all()
    columns = list(result.keys())
    serialized_rows = []
    for row in rows:
        serialized_row = {}
        for col in columns:
            serialized_row[col] = serialize_value(row[col])
        serialized_rows.append(serialized_row)
    return serialized_rows


async def _verify_table_row_count(db: AsyncSession, table, qtname: str,
                                    expected_rows: int) -> tuple[dict, bool]:
    """L1 行数比对。返回 (l1_entry, 表是否存在)。"""
    tname = str(table.name)
    try:
        result = await db.execute(text(f'SELECT COUNT(*) FROM {qtname}'))  # nosec B608 — qtname 经 quote_table 白名单校验; batch-loop: 逐表备份/恢复,无法批量
        actual_rows = result.scalar() or 0
        table_exists = True
    except (RuntimeError, OSError, ValueError, SQLAlchemyError) as e:
        actual_rows = -1
        table_exists = False
        logger.warning(f'验证: 统计表 {tname} 行数失败: {e}')

    if not table_exists and expected_rows == 0:
        l1_pass = True
    elif expected_rows < 0:
        l1_pass = None
    else:
        l1_pass = actual_rows == expected_rows
    return {'table': tname, 'expected': expected_rows, 'actual': actual_rows, 'pass': l1_pass}, table_exists


async def _verify_table_l0_checksum(db: AsyncSession, table, qtname: str) -> str | None:
    """L0 全局校验和片段：表级 MD5 聚合（失败返回 None）。"""
    tname = str(table.name)
    try:
        pk_col = [c.name for c in table.primary_key.columns]
        order_col = pk_col[0] if pk_col else 'id'
        cols_result = await db.execute(  # batch-loop: 逐表备份/恢复,无法批量
            text('SELECT column_name FROM information_schema.columns WHERE table_name = :tname ORDER BY ordinal_position'),
            {'tname': tname}
        )
        col_names = [r[0] for r in cols_result.fetchall()]
        agg = " || '|' || ".join(f'''COALESCE("{c}"::text, '')''' for c in col_names)  # sql-safe: escape_like/绑定参数/常量片段
        row = await db.execute(text(  # batch-loop: 逐表备份/恢复,无法批量
            f'''SELECT MD5(STRING_AGG(MD5({agg}), ',' ORDER BY "{order_col}")) FROM {qtname}'''  # nosec B608 — qtname 经 quote_table 白名单校验
        ))
        t_hash = row.scalar()
        return f'{tname}:{t_hash}' if t_hash else None
    except (SQLAlchemyError, ValueError, OSError) as e:
        logger.warning(f'验证: 表 {tname} 全局校验和计算失败: {e}')
        return None


async def _verify_table_l2_fingerprint(db: AsyncSession, table, qtname: str,
                                       expected_fp: str) -> dict:
    """L2 数据指纹：MD5 聚合关键业务表（失败置空串）。"""
    tname = str(table.name)
    try:
        pk_col = [c.name for c in table.primary_key.columns]
        order_col = pk_col[0] if pk_col else 'id'
        cols_result = await db.execute(  # batch-loop: 逐表备份/恢复,无法批量
            text('SELECT column_name FROM information_schema.columns WHERE table_name = :tname ORDER BY ordinal_position'),
            {'tname': tname}
        )
        col_names = [r[0] for r in cols_result.fetchall()]
        agg_expr = " || '|' || ".join(f'''COALESCE("{c}"::text, '')''' for c in col_names)  # sql-safe: escape_like/绑定参数/常量片段
        fp_result = await db.execute(text(  # batch-loop: 逐表备份/恢复,无法批量
            f'''SELECT MD5(STRING_AGG({agg_expr}, ',' ORDER BY "{order_col}")) FROM {qtname}'''  # nosec B608 — qtname 经 quote_table 白名单校验
        ))
        fingerprint = fp_result.scalar() or ''
    except (ValueError, TypeError, OSError, SQLAlchemyError) as e:
        fingerprint = ''
        logger.warning(f'验证: 表 {tname} 指纹计算失败: {e}')
    fp_match = fingerprint == expected_fp if expected_fp else None
    return {'table': tname, 'fingerprint': fingerprint, 'expected_fingerprint': expected_fp, 'match': fp_match}


async def _verify_table_l3_sampling(db: AsyncSession, table, qtname: str) -> dict:
    """L3 ID 抽样：取前 3 个主键值，确认恢复后仍存在。"""
    tname = str(table.name)
    try:
        pk_col_sample = [c.name for c in table.primary_key.columns]
        sample_col = pk_col_sample[0] if pk_col_sample else 'id'
        sample_result = await db.execute(text(  # batch-loop: 逐表备份/恢复,无法批量
            f'SELECT "{sample_col}" FROM {qtname} ORDER BY "{sample_col}" LIMIT 3'  # nosec B608 — qtname 经 quote_table 白名单校验
        ))
        found_ids = [r[0] for r in sample_result.fetchall()]
    except (SQLAlchemyError, ValueError, OSError) as e:
        found_ids = []
        logger.warning(f'验证: 表 {tname} 抽样查询失败: {e}')
    return {'table': tname, 'sample_ids': found_ids, 'count_found': len(found_ids)}


def _build_l0_summary(l0_parts: list[str]) -> dict:
    """L0 全局校验和汇总（无贡献表则返回空 dict）。"""
    if not l0_parts:
        return {}
    l0_db_hash = hashlib.md5('|'.join(l0_parts).encode(), usedforsecurity=False).hexdigest()
    return {
        'db_checksum': l0_db_hash, 'tables_contributed': len(l0_parts),
        'note': '恢复后数据库全局 MD5（可与备份时比对，全量备份 manifest 中可附带此值）',
    }


async def _verify_schema(db: AsyncSession, manifest_schema: dict[str, list[dict]] | None) -> tuple[list[dict], str]:
    """L4 表结构（DDL）比对（M3 新增）。返回 (l4_results, l4_note)。"""
    l4_results: list[dict] = []
    if not manifest_schema:
        return l4_results, 'manifest 无 schema_snapshot（旧备份），跳过 L4 表结构比对'
    try:
        current_schema = await build_schema_snapshot(db)
        for tname in sorted(set(manifest_schema) | set(current_schema)):
            expected_cols = {c['column'] for c in manifest_schema.get(tname, [])}
            actual_cols = {c['column'] for c in current_schema.get(tname, [])}
            missing = sorted(expected_cols - actual_cols)
            extra = sorted(actual_cols - expected_cols)
            l4_results.append({
                'table': tname, 'pass': (not missing and not extra),
                'missing_columns': missing, 'extra_columns': extra,
            })
        return l4_results, ''
    except (ValueError, TypeError, OSError, SQLAlchemyError) as e:
        l4_note = f'L4 表结构比对失败: {e}'
        logger.warning(l4_note)
        return l4_results, l4_note


def _build_verification_report(l1_results: list[dict], l2_results: list[dict],
                               l3_results: list[dict], l0_summary: dict,
                               l4_results: list[dict], l4_note: str) -> dict:
    """汇总四层结果，产出对外报告 dict。"""
    l4_mismatch = [r for r in l4_results if not r['pass']]
    l4_all_pass = len(l4_mismatch) == 0 and not l4_note.startswith('L4 表结构比对失败')

    l1_match = sum(1 for r in l1_results if r['pass'] is True)
    l1_indeterminate = sum(1 for r in l1_results if r['pass'] is None)
    l1_mismatch = [r for r in l1_results if r['pass'] is False]
    l1_verifiable = sum(1 for r in l1_results if r['pass'] is not None)
    l1_pass_rate = round(l1_match / l1_verifiable * 100, 1) if l1_verifiable > 0 else 100.0

    l2_match = sum(1 for r in l2_results if r['match'] is True)
    l2_total = len(l2_results)
    l2_mismatch = [r for r in l2_results if r['match'] is False]

    l1_all_pass = len(l1_mismatch) == 0
    l2_all_pass = len(l2_mismatch) == 0
    all_passed = l1_all_pass and l2_all_pass and l4_all_pass

    return {
        'overall_pass': all_passed,
        'verification_verdict': '通过' if all_passed else '失败',
        'l0_global_checksum': l0_summary,
        'l1_row_count': {
            'total_tables': len(l1_results), 'verifiable_tables': l1_verifiable,
            'match': l1_match, 'indeterminate': l1_indeterminate, 'mismatch': l1_mismatch,
            'pass_rate_pct': l1_pass_rate,
            'summary': f'行数匹配: {l1_match}/{l1_verifiable} ({l1_pass_rate}%)',
        },
        'l2_fingerprint': {
            'tables_checked': l2_total, 'match': l2_match, 'mismatch': l2_mismatch,
            'results': l2_results,
            'summary': f'指纹匹配: {l2_match}/{l2_total}' if l2_total > 0 else '无业务表需校验',
        },
        'l3_sampling': {'tables_checked': len(l3_results), 'results': l3_results},
        'l4_schema': {
            'tables_checked': len(l4_results), 'mismatch': l4_mismatch, 'results': l4_results,
            'note': l4_note or ('表结构一致' if l4_all_pass else '存在表结构差异'),
        },
    }


async def verify_restore(
    db: AsyncSession,
    manifest_tables: dict[str, dict],
    manifest_fingerprints: dict[str, str] | None = None,
    manifest_schema: dict[str, list[dict]] | None = None,
) -> dict:
    """四层恢复后验证

    L0 — 全局校验和: MD5 hash 跨所有表数据
    L1 — 行数: SELECT COUNT(*) 与 manifest 比对
    L2 — 数据指纹: MD5 聚合关键业务表
    L3 — ID 抽样: 检查备份中前 3 个 ID 恢复后是否存在
    L4 — 表结构(DDL)比对: manifest['schema_snapshot'] vs 当前 info_schema.columns（M3 新增）

    2026-10-11（复核 P2-14⑤）：原 154 行拆为逐表层校验（行数/L0/L2/L3 各成 helper）
    + L4 schema 比对 + 聚合报告，主函数只保留遍历与汇总。
    """
    from fastapi_app.shared_models import Base
    checksum_tables = get_checksum_tables()
    l1_results: list[dict] = []
    l2_results: list[dict] = []
    l3_results: list[dict] = []
    l0_parts: list[str] = []

    for table in Base.metadata.sorted_tables:
        tname = str(table.name)
        qtname = quote_table(tname)  # REV-08
        expected = manifest_tables.get(tname, {})
        expected_rows = expected.get('rows', -1)

        l1_entry, table_exists = await _verify_table_row_count(db, table, qtname, expected_rows)
        l1_results.append(l1_entry)
        if not table_exists:
            continue

        if l1_entry['actual'] > 0:
            l0_part = await _verify_table_l0_checksum(db, table, qtname)
            if l0_part:
                l0_parts.append(l0_part)

        if tname in checksum_tables and expected_rows and expected_rows > 0:
            l2_results.append(await _verify_table_l2_fingerprint(
                db, table, qtname, (manifest_fingerprints or {}).get(tname, '')
            ))

        if expected_rows and expected_rows > 0:
            l3_results.append(await _verify_table_l3_sampling(db, table, qtname))

    l0_summary = _build_l0_summary(l0_parts)
    l4_results, l4_note = await _verify_schema(db, manifest_schema)
    return _build_verification_report(l1_results, l2_results, l3_results, l0_summary, l4_results, l4_note)
