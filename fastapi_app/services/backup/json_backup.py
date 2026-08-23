"""JSON 格式备份/恢复。"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from datetime import date, datetime
from datetime import time as time_type
from decimal import Decimal
from uuid import UUID

from sqlalchemy import ARRAY, JSON, Boolean, Date, DateTime, Numeric, Time, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from .exceptions import RestoreError
from .verify import quote_table

logger = logging.getLogger(__name__)


def serialize_value(val):
    """将数据库值序列化为 JSON 兼容类型"""
    if val is None:
        return None
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)):
        return val
    if isinstance(val, str):
        return val
    if isinstance(val, datetime):
        return val.strftime('%Y-%m-%d %H:%M:%S')
    if isinstance(val, date):
        return val.isoformat()
    if isinstance(val, Decimal):
        return float(val)
    if isinstance(val, UUID):
        return str(val)
    if isinstance(val, (bytes, bytearray)):
        return val.hex()
    if isinstance(val, (dict, list)):
        return json.dumps(val, ensure_ascii=False, default=str)
    if hasattr(val, 'isoformat'):
        return val.isoformat()
    return str(val)


def build_column_type_map(table):
    """构建 column_name -> sqlalchemy type 映射"""
    return {str(col.name): col.type for col in table.columns}


def deserialize_value(val, col_type):
    """将 JSON 反序列化的值转回正确的 Python 类型"""
    if val is None:
        return None
    if isinstance(col_type, DateTime):
        if isinstance(val, str):
            try:
                return datetime.strptime(val, '%Y-%m-%d %H:%M:%S')
            except ValueError:
                try:
                    return datetime.fromisoformat(val)
                except ValueError:
                    pass  # defensive: 可选 ValueError 静默处理,不影响主流程
        return val
    if isinstance(col_type, Date):
        if isinstance(val, str):
            try:
                return datetime.strptime(val, '%Y-%m-%d').date()
            except ValueError:
                try:
                    return date.fromisoformat(val)
                except ValueError:
                    pass  # defensive: 可选 ValueError 静默处理,不影响主流程
        return val
    if isinstance(col_type, Time):
        if isinstance(val, str):
            try:
                return datetime.strptime(val, '%H:%M:%S').time()
            except ValueError:
                try:
                    return time_type.fromisoformat(val)
                except ValueError:
                    pass  # defensive: 可选 ValueError 静默处理,不影响主流程
        return val
    if isinstance(col_type, Boolean):
        if isinstance(val, (int, float)):
            return bool(val)
        return val
    if isinstance(col_type, Numeric):
        if isinstance(val, (int, float)):
            return Decimal(str(val))
        return val
    if isinstance(col_type, JSON):
        if isinstance(val, str):
            with contextlib.suppress(ValueError, TypeError):
                return json.loads(val)  # REV-JSON: 备份时 dict/list 以合法 JSON 字符串落盘，还原时转回结构
        return val
    if isinstance(col_type, ARRAY):
        return val
    if isinstance(col_type, PG_UUID):
        if isinstance(val, str):
            return UUID(val)
        return val
    return val


async def _retry_batch_rowwise(db, qtname, batch, batch_start, columns, type_map, table_col_names, pk_cols) -> list:
    """batch 恢复失败时降级为逐行插入，跳过因唯一约束冲突而无法写入的行。

    返回被跳过行的索引区间标记（用于报告）。返回 None 表示整批未完成（异常而非冲突）。
    """
    from sqlalchemy.exc import IntegrityError

    skipped = []
    for offset, row in enumerate(batch):
        idx = batch_start + offset
        if not row:
            continue
        valid_cols = [c for c in columns if c in type_map and c in row and c in table_col_names]
        if not valid_cols:
            continue
        col_str = ', '.join(f'"{c}"' for c in valid_cols)
        val_str = ', '.join(f':{c}__row{idx}' for c in valid_cols)
        params = {}
        for c in valid_cols:
            raw_val = row[c]
            col_type = type_map.get(c)
            deserialized = deserialize_value(raw_val, col_type) if col_type else raw_val
            params[f'{c}__row{idx}'] = deserialized
        update_cols = [c for c in valid_cols if c not in pk_cols]
        try:
            if pk_cols and update_cols:
                update_str = ', '.join(f'"{c}" = EXCLUDED."{c}"' for c in update_cols)
                await db.execute(text(  # batch-loop: 逐表备份/恢复,无法批量
                    f'INSERT INTO {qtname} ({col_str}) VALUES ({val_str}) ON CONFLICT ({", ".join(pk_cols)}) DO UPDATE SET {update_str}'  # nosec B608 — qtname 经 quote_table 白名单校验
                ), params)
            else:
                await db.execute(text(  # batch-loop: 逐表备份/恢复,无法批量
                    f'INSERT INTO {qtname} ({col_str}) VALUES ({val_str}) ON CONFLICT DO NOTHING'  # nosec B608 — qtname 经 quote_table 白名单校验
                ), params)
        except IntegrityError:
            await db.rollback()  # manual-tx: 单行冲突放弃，跳过后继续
            skipped.append(row)
            continue
        except (SQLAlchemyError, ValueError, TypeError):
            await db.rollback()  # manual-tx: 单行不可恢复错误，放弃该行
            skipped.append(row)
            continue
    # 本函数仅负责逐行、会跳过失败行，因此这里不统一 flush —— 由外层事务负责
    return skipped


async def execute_legacy_backup_to_bytes(user, remark: str, db: AsyncSession) -> bytes:
    """Legacy JSON 备份 (v1.0)，用于无 pg_dump 环境"""
    from fastapi_app.shared_models import Base
    backup_data = {
        'version': '1.0',
        'exported_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'exported_by': user.username if hasattr(user, 'username') else str(user.id),
        'remark': remark,
        'tables': {},
    }
    # 先查询实际存在的表，避免查询不存在的表导致事务失败
    existing_result = await db.execute(
        text("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")
    )
    existing_tables = {r[0] for r in existing_result.fetchall()}

    for table in Base.metadata.sorted_tables:
        name = str(table.name)
        if name not in existing_tables:
            logger.warning(f'跳过不存在的表: {name}')
            backup_data['tables'][name] = {'error': '表不存在', 'count': 0, 'rows': []}
            continue
        try:
            qtname = quote_table(name)
            nested = await db.begin_nested()
            try:
                result = await db.execute(text(f'SELECT * FROM {qtname}'))  # nosec B608 — qtname 经 quote_table 白名单校验; batch-loop: 逐表备份/恢复,无法批量; select-all: backup/restore 需要全表动态导出
                rows = result.mappings().all()
                columns = list(result.keys())
                serialized_rows = []
                for row in rows:
                    serialized_row = {}
                    for col in columns:
                        serialized_row[col] = serialize_value(row[col])
                    serialized_rows.append(serialized_row)
                backup_data['tables'][name] = {'columns': columns, 'rows': serialized_rows, 'count': len(serialized_rows)}
                await nested.commit()  # manual-tx: savepoint 嵌套事务管理
            except (SQLAlchemyError, ValueError, OSError) as e:
                await nested.rollback()  # manual-tx: savepoint 嵌套事务管理
                logger.error('备份表 %s 失败: %s', name, e)
                backup_data['tables'][name] = {'error': str(e), 'count': 0, 'rows': []}
        except (SQLAlchemyError, ValueError, OSError) as e:
            logger.error('备份表 %s 初始化失败: %s', name, e)
            backup_data['tables'][name] = {'error': str(e), 'count': 0, 'rows': []}
    return json.dumps(backup_data, ensure_ascii=False, indent=2).encode('utf-8')


async def restore_database_from_json(zf, db: AsyncSession, task_id: str | None = None) -> dict:
    """从 dump.json 恢复数据库（Legacy JSON 格式）"""
    try:
        json_bytes = zf.read('database/dump.json')
        backup_data = json.loads(json_bytes)
    except (OSError, ValueError, json.JSONDecodeError) as e:
        return {'status': 'error', 'error': f'读取 JSON 数据库备份失败: {e}'}
    if 'tables' not in backup_data:
        return {'status': 'error', 'error': 'JSON 备份缺少 tables 字段'}
    result = await restore_legacy_json(backup_data, db, task_id)
    return {
        'status': 'ok' if not result['errors'] else 'partial',
        'message': f"数据库恢复完成，共 {result['total_inserted']} 条记录",
        'total_inserted': result['total_inserted'],
        'errors': result['errors'][:5],
    }


async def restore_legacy_json(backup_data: dict, db: AsyncSession, task_id: str | None = None) -> dict:
    """从 Legacy JSON 格式备份恢复数据库 (v1.0)"""
    from fastapi_app.core.backup_progress import update_progress as _upd_prog
    from fastapi_app.shared_models import Base

    from .verify import verify_restore

    async def _report(sub: float, detail: str = ''):
        if task_id:
            await _upd_prog(task_id, 'restore_db', sub, detail)
            await asyncio.sleep(0)

    results = {}
    total_inserted = 0
    errors = []
    replication_role_set = False

    # 计算需要恢复的表数量用于进度计算
    tables_to_restore = [t for t in Base.metadata.sorted_tables if str(t.name) in backup_data.get('tables', {})]
    total_tables = len(tables_to_restore)

    try:
        try:
            is_super = await db.execute(text("SELECT usesuper FROM pg_user WHERE usename = current_user"))
            if is_super.scalar():
                await db.execute(text("SET session_replication_role = 'replica'"))
                replication_role_set = True
            else:
                logger.info('当前用户非superuser，跳过禁用外键约束（将使用ON CONFLICT处理冲突）')
        except (SQLAlchemyError, OSError) as e:
            logger.warning(f'禁用外键约束失败: {e}')

        await _report(0.05, '清空现有数据...')
        for table in reversed(Base.metadata.sorted_tables):
            table_name = str(table.name)
            if table_name not in backup_data.get('tables', {}):
                continue
            qtname = quote_table(table_name)  # REV-08
            nested = await db.begin_nested()
            try:
                await db.execute(text(f'DELETE FROM {qtname}'))  # nosec; batch-loop: 逐表备份/恢复,无法批量 # sql-safe: escape_like/绑定参数/常量片段
                await nested.commit()  # manual-tx: savepoint 嵌套事务管理
            except (SQLAlchemyError, ValueError, OSError) as e:
                await nested.rollback()  # manual-tx: savepoint 嵌套事务管理
                logger.warning(f'清空表 {table_name} 失败（外键约束）: {e}')

        processed_tables = 0
        for table in tables_to_restore:
            table_name = str(table.name)
            table_data = backup_data['tables'][table_name]
            columns = table_data.get('columns', [])
            rows = table_data.get('rows', [])
            table_col_names = {c.name for c in table.columns}
            type_map = build_column_type_map(table)
            BATCH_SIZE = 500
            inserted = 0
            batch_errors = []
            qtname = quote_table(table_name)  # REV-08
            for batch_start in range(0, len(rows), BATCH_SIZE):
                batch = rows[batch_start:batch_start + BATCH_SIZE]
                nested = await db.begin_nested()
                try:
                    for offset, row in enumerate(batch):
                        idx = batch_start + offset
                        if not row:
                            continue
                        valid_cols = [c for c in columns if c in type_map and c in row and c in table_col_names]
                        if not valid_cols:
                            continue
                        col_str = ', '.join(f'"{c}"' for c in valid_cols)
                        val_str = ', '.join(f':{c}__row{idx}' for c in valid_cols)
                        params = {}
                        for c in valid_cols:
                            raw_val = row[c]
                            col_type = type_map.get(c)
                            deserialized = deserialize_value(raw_val, col_type) if col_type else raw_val
                            params[f'{c}__row{idx}'] = deserialized
                        pk_cols = [c.name for c in table.primary_key.columns]
                        update_cols = [c for c in valid_cols if c not in pk_cols]
                        if pk_cols and update_cols:
                            update_str = ', '.join(f'"{c}" = EXCLUDED."{c}"' for c in update_cols)
                            await db.execute(text(  # batch-loop: 逐表备份/恢复,无法批量
                                f'INSERT INTO {qtname} ({col_str}) VALUES ({val_str}) ON CONFLICT ({", ".join(pk_cols)}) DO UPDATE SET {update_str}'  # nosec B608 — qtname 经 quote_table 白名单校验
                            ), params)
                        else:
                            await db.execute(text(  # batch-loop: 逐表备份/恢复,无法批量
                                f'INSERT INTO {qtname} ({col_str}) VALUES ({val_str}) ON CONFLICT DO NOTHING'  # nosec B608 — qtname 经 quote_table 白名单校验
                            ), params)
                        inserted += 1
                    await nested.commit()  # manual-tx: savepoint 嵌套事务管理
                except (SQLAlchemyError, ValueError, TypeError) as e:
                    await nested.rollback()  # manual-tx: savepoint 嵌套事务管理
                    # 降级：batch 因非主键唯一约束冲突整体失败，逐行重试，跳过冲突行（REV-DO32）
                    skip = await _retry_batch_rowwise(
                        db, qtname, batch, batch_start, columns, type_map, table_col_names, pk_cols)
                    if skip:
                        batch_errors.append(
                            f'批次 {batch_start // BATCH_SIZE + 1}: 降级跳过 {len(skip)} 行（唯一约束冲突）: {skip[:5]}')
                        logger.warning(
                            f'恢复表 {table_name} 批次 {batch_start // BATCH_SIZE + 1} '
                            f'降级，跳过 {len(skip)} 行唯一约束冲突')
                    else:
                        batch_errors.append(f'批次 {batch_start // BATCH_SIZE + 1}: {e}')
                        logger.warning(f'恢复表 {table_name} 批次 {batch_start // BATCH_SIZE + 1} 失败: {e}')
            if batch_errors:
                results[table_name] = {'status': 'partial', 'inserted': inserted, 'batch_errors': batch_errors}
                errors.append(f'{table_name}: {len(batch_errors)} 个批次失败')
            else:
                results[table_name] = {'status': 'ok', 'inserted': inserted}
            total_inserted += inserted
            processed_tables += 1

            # 报告进度：0.1 到 0.9 之间按表进度递增
            sub_progress = 0.1 + 0.8 * (processed_tables / total_tables) if total_tables > 0 else 0.9
            await _report(sub_progress, f'已恢复 {processed_tables}/{total_tables} 表 ({table_name}: {inserted}条)')

        await db.flush()
        if replication_role_set:
            try:
                await db.execute(text("SET session_replication_role = 'origin'"))
            except (SQLAlchemyError, OSError) as e:
                logger.warning(f'重新启用外键约束失败: {e}')

        try:
            from fastapi_app.core.cache import CacheDomain, invalidate_related_caches
            await invalidate_related_caches(CacheDomain.ALL)
        except (RuntimeError, OSError, ValueError) as e:
            logger.warning(f'恢复后缓存清除失败: {e}')
        try:
            from fastapi_app.core.purchase_cache import invalidate_purchase_caches
            invalidate_purchase_caches()
        except (RuntimeError, OSError, ValueError) as e:
            logger.warning(f'恢复后采购缓存清除失败: {e}')

        verification = {'overall_pass': True}
        try:
            manifest_tables = {
                tname: {'rows': td.get('count', len(td.get('rows', [])))}
                for tname, td in backup_data.get('tables', {}).items()
            }
            from fastapi_app.core.database import _AsyncSessionLocal
            verify_db = None
            if _AsyncSessionLocal is not None:
                verify_db = _AsyncSessionLocal()
            try:
                verification = await verify_restore(
                    verify_db or db, manifest_tables,
                    manifest_fingerprints=backup_data.get('fingerprints'),
                    manifest_schema=backup_data.get('schema_snapshot'),
                )
            finally:
                if verify_db is not None:
                    with contextlib.suppress(OSError, ValueError, SQLAlchemyError):
                        await verify_db.close()
        except (SQLAlchemyError, ValueError, OSError) as e:
            logger.warning(f'恢复后验证失败: {e}')
            verification = {'overall_pass': False, 'error': str(e)}
    except (SQLAlchemyError, ValueError, OSError) as e:
        await db.rollback()  # manual-tx: try/except 内显式事务控制
        raise RestoreError(f'恢复过程中出错: {e}') from e

    result_dict = {
        'database': {'status': 'ok' if not errors else 'partial', 'total_inserted': total_inserted},
        'total_inserted': total_inserted, 'results': results, 'errors': errors,
        'verification': verification,
    }
    if not verification.get('overall_pass', True):
        result_dict['_verification_failed'] = True
    return result_dict
