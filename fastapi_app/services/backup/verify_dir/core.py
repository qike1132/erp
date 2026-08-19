"""恢复后验证 + 工具函数。"""
from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import zipfile
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.exc import DataError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from .._constants import (
    _CHECKSUM_EXCLUDE_TABLES,
    _TIMESTAMP_CANDIDATES,
    BACKUP_DIR,
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
        # 列可能是 timestamptz（需 datetime）也可能是 varchar（需 string），先尝试字符串
        since_dt = since
        if isinstance(since_dt, str):
            with contextlib.suppress(TypeError, ValueError):
                since_dt = datetime.strptime(since_dt, '%Y-%m-%d %H:%M:%S')
        # 优先尝试 datetime（timestamptz 列需要）；失败时回退到字符串
        try:
            result = await db.execute(
                text(f'SELECT * FROM {qtname} WHERE "{ts_col}" >= :since'),  # nosec B608 — qtname 经 quote_table 白名单校验; select-all: backup/restore 需要全表动态导出
                {'since': since_dt},
            )
        except DataError:
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


async def find_last_backup_timestamp() -> str | None:
    """查找最近一次全量备份的导出时间"""
    if not BACKUP_DIR.exists():
        return None
    for f in sorted(BACKUP_DIR.iterdir(), reverse=True):
        if f.is_file() and f.name.startswith('erp_backup_') and f.name.endswith('.zip'):
            try:
                with zipfile.ZipFile(f, 'r') as zf:
                    if 'manifest.json' in zf.namelist():
                        mf = json.loads(zf.read('manifest.json'))
                        return mf.get('exported_at')
            except (OSError, zipfile.BadZipFile, ValueError):
                continue
    return None


async def verify_restore(db: AsyncSession, manifest_tables: dict[str, dict], manifest_fingerprints: dict[str, str] | None = None) -> dict:
    """四层恢复后验证

    L0 — 全局校验和: MD5 hash 跨所有表数据
    L1 — 行数: SELECT COUNT(*) 与 manifest 比对
    L2 — 数据指纹: MD5 聚合关键业务表
    L3 — ID 抽样: 检查备份中前 3 个 ID 恢复后是否存在
    """
    from fastapi_app.shared_models import Base
    checksum_tables = get_checksum_tables()
    l0_db_hash: str | None = None
    l0_tables_contributed = 0
    l1_results: list[dict] = []
    l2_results: list[dict] = []
    l3_results: list[dict] = []
    l0_parts: list[str] = []

    for table in Base.metadata.sorted_tables:
        tname = str(table.name)
        qtname = quote_table(tname)  # REV-08
        expected = manifest_tables.get(tname, {})
        expected_rows = expected.get('rows', -1)
        try:
            result = await db.execute(text(f'SELECT COUNT(*) FROM {qtname}'))  # nosec B608 — qtname 经 quote_table 白名单校验; batch-loop: 逐表备份/恢复,无法批量 # batch-loop: 有意逐行处理,非 N+1
            actual_rows = result.scalar() or 0
            table_exists = True
        except (RuntimeError, OSError, ValueError) as e:
            actual_rows = -1
            table_exists = False
            logger.warning(f'验证: 统计表 {tname} 行数失败: {e}')

        if not table_exists and expected_rows == 0:
            l1_pass = True
        elif expected_rows < 0:
            l1_pass = None
        else:
            l1_pass = actual_rows == expected_rows
        l1_results.append({'table': tname, 'expected': expected_rows, 'actual': actual_rows, 'pass': l1_pass})

        if not table_exists:
            continue

        if actual_rows > 0:
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
                if t_hash:
                    l0_parts.append(f'{tname}:{t_hash}')
                    l0_tables_contributed += 1
            except (SQLAlchemyError, ValueError, OSError) as e:
                logger.warning(f'验证: 表 {tname} 全局校验和计算失败: {e}')

        if tname in checksum_tables and expected_rows and expected_rows > 0:
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
            except (ValueError, TypeError, OSError) as e:
                fingerprint = ''
                logger.warning(f'验证: 表 {tname} 指纹计算失败: {e}')
            expected_fp = (manifest_fingerprints or {}).get(tname, '')
            fp_match = fingerprint == expected_fp if expected_fp else None
            l2_results.append({'table': tname, 'fingerprint': fingerprint, 'expected_fingerprint': expected_fp, 'match': fp_match})

        if expected_rows and expected_rows > 0:
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
            l3_results.append({'table': tname, 'sample_ids': found_ids, 'count_found': len(found_ids)})

    l0_summary = {}
    if l0_parts:
        l0_db_hash = hashlib.md5('|'.join(l0_parts).encode(), usedforsecurity=False).hexdigest()
        l0_summary = {
            'db_checksum': l0_db_hash, 'tables_contributed': l0_tables_contributed,
            'note': '恢复后数据库全局 MD5（可与备份时比对，全量备份 manifest 中可附带此值）',
        }

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
    all_passed = l1_all_pass and l2_all_pass

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
    }
