"""JSON 格式备份/恢复。"""
from __future__ import annotations

import ast
import asyncio
import json
import logging
from datetime import UTC, date, datetime
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


class JsonRestoreFatalError(RuntimeError):
    """JSON 还原遇非主键约束错误（外键违规等）时的中止信号。

    fail-fast（M5）:区别于可跳过的唯一主键冲突,此类错误表示备份数据与
    目标库约束不一致,继续还原只会悄无声息丢数据,必须中止并上报前端。
    """


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
        # JSON/JSONB：还原时必须交给 asyncpg 的 jsonb codec 一个**合法 JSON 字符串**。
        # 备份侧 serialize_value 已对 dict/list 做 json.dumps，正常路径返回 str 即可。
        # 但兼容历史 dump 的两种非标形态，统一归一为合法 JSON 字符串：
        #   1) 值本身是 dict/list（旧 dump 直接存 python 对象）→ asyncpg 会报
        #      'dict' object has no attribute 'encode'，须 json.dumps。
        #   2) 值是 Python repr()/str() 输出的单引号字符串（如 "[{'k': 'v'}]"），
        #      非合法 JSON → PG 报 'invalid input syntax for type json'（Token "'" is invalid），
        #      须 ast.literal_eval 还原后 json.dumps。
        if isinstance(val, (dict, list)):
            return json.dumps(val, ensure_ascii=False, default=str)
        if isinstance(val, str):
            try:
                json.loads(val)  # 已是合法 JSON，原样返回
                return val
            except (ValueError, TypeError):
                pass
            try:
                return json.dumps(ast.literal_eval(val), ensure_ascii=False, default=str)
            except (ValueError, SyntaxError):
                return val  # 无法安全还原时保持原样，交由 asyncpg 报错，不静默改错
        return val
    if isinstance(col_type, ARRAY):
        return val
    if isinstance(col_type, PG_UUID):
        if isinstance(val, str):
            return UUID(val)
        return val
    return val


def _topo_sort_self_referencing(table, rows: list) -> list:
    """对含自引用外键的表做整表拓扑排序（父行先于子行）。

    JSON 备份按 ``SELECT *`` 行序导出，不保证父节点 id 小于子节点 id；
    ``sorted_tables`` 只保证表间顺序（父表先于子表），无法约束表内行序。
    当自引用 FK 的父行 id 大于子行（如 permission.parent_id / pattern_room_bom_item.parent_id）
    时，子行先插入会触发外键违规。此处用 DFS 拓扑排序，把父行排到子行前，
    使批作业切分（BATCH_SIZE=500）也在排序后的行上执行，父子跨批也能正确落在先后批。

    仅对含自引用外键的表生效；无自引用外键或无法排序（环/孤儿）时维持原序，
    残留的孤儿行仍会走 fail-fast 显式中止（不静默丢数据）。
    """
    # 收集引用本表自身的外键本地列（如 permission.parent_id 引用 permission.id）
    self_ref_local: list[str] = []
    for constraint in getattr(table, 'foreign_key_constraints', ()):
        if getattr(constraint, 'referred_table', None) is table:
            for local_col in constraint.columns:
                self_ref_local.append(str(local_col.name))
    if not self_ref_local:
        return rows
    pk_cols = [str(c.name) for c in table.primary_key.columns]
    if not pk_cols:
        return rows

    def pk_key(row):
        if len(pk_cols) == 1:
            return row.get(pk_cols[0])
        return tuple(row.get(c) for c in pk_cols)

    def ref_key(row):
        # 与 pk_key 保持一致：单列返回标量、多列返回元组，避免类型不匹配
        vals = tuple(row.get(c) for c in self_ref_local)
        if all(v is None for v in vals):
            return None
        return vals[0] if len(vals) == 1 else vals

    # 主键 -> 行索引，用于定位子行的父行
    pk_index: dict[object, int] = {}
    for i, row in enumerate(rows):
        key = pk_key(row)
        if key is None:
            continue
        pk_index.setdefault(key, i)

    order: list[int] = []
    state = [0] * len(rows)  # 0=未访问 1=访问中(环检测) 2=已排定

    def visit(i: int) -> None:
        if state[i] == 2:
            return
        if state[i] == 1:  # 自引用成环：放弃该依赖，维持原序由 fail-fast 兜底
            return
        state[i] = 1
        row = rows[i]
        dep = ref_key(row)
        if dep is not None:
            j = pk_index.get(dep)
            if j is not None and j != i:
                visit(j)
        state[i] = 2
        order.append(i)

    for i in range(len(rows)):
        visit(i)

    if len(order) != len(rows):
        logger.warning(
            f'表 "{table.name}" 自引用拓扑排序异常（环），部分行维持原序')

    return [rows[i] for i in order]


def _is_pk_conflict(exc) -> bool:
    """判断异常是否为「主键唯一冲突」（PostgreSQL SQLSTATE 23505）。

    JSON 还原当前依赖扩展的 dbapi 异常溯源：asyncpg 用 ``orig.sqlstate``，
    psycopg3 用 ``sqlstate``。能取到且非 23505 的约束错误一律视为外键/其他
    约束违规（fail-fast，不得静默跳过）。
    """
    orig = getattr(exc, 'orig', None)
    sqlstate = None
    if orig is not None:
        sqlstate = getattr(orig, 'sqlstate', None) or getattr(orig, 'pgcode', None)
    if not sqlstate:
        return False
    return str(sqlstate) == '23505'


async def _retry_batch_rowwise(db, qtname, batch, batch_start, columns, type_map, table_col_names, pk_cols) -> list:
    """batch 恢复失败时降级为逐行插入。

    fail-fast（M5 还原修复）:仅跳过「主键唯一冲突(23505)」的行；外键违规
    (23503) 或其他错误必须中止还原,不得静默丢弃数据——否则还原被标记成功
    却丢数据（如 customer_sampling_fabric_version 丢 3331 行）。

    返回被跳过行的索引区间标记（用于报告）。返回 None 表示整批未完成（异常而非冲突）。
    """
    from sqlalchemy.exc import IntegrityError

    skipped = []
    fatal_errors: dict[int, str] = {}
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
        # B3 修复：每行包 savepoint——行级失败只回滚该行，外层已成功批次
        # 不受影响。旧实现 db.rollback() 会回滚整个外层事务，把此前所有
        # 批次已插入的行一并清除（重复导入主键冲突场景高频触发），最终
        # "恢复完成 N 条"与库中实际行数严重不符（虚假成功）。
        row_nested = await db.begin_nested()
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
            await row_nested.commit()  # manual-tx: savepoint 嵌套事务管理
        except IntegrityError as e:
            await row_nested.rollback()  # manual-tx: 只回滚本行 savepoint
            if _is_pk_conflict(e):
                skipped.append(row)
                continue
            # 外键违规等非主键冲突:记录并继续循环,最后统一 fail-fast
            fatal_errors[idx] = str(e.__cause__ or e.orig or e)[:300]
            continue
        except (SQLAlchemyError, ValueError, TypeError) as e:
            await row_nested.rollback()  # manual-tx: 只回滚本行 savepoint
            fatal_errors[idx] = str(e)[:300]
            continue
    if fatal_errors:
        first_row_idx, first_msg = next(iter(fatal_errors.items()))
        logger.error(
            f'JSON 还原 fail-fast: {qtname} 存在 {len(fatal_errors)} 行非主键约束错误'
            f'（首行 idx={first_row_idx}: {first_msg}），中止还原'
        )
        raise JsonRestoreFatalError(
            f'还原中止: 表 "{qtname}" 有 {len(fatal_errors)} 行数据因外键/约束违规无法写入'
            f'（首行: {first_msg}）。'
        )
    # 本函数仅负责逐行、会跳过主键冲突行，因此这里不统一 flush —— 由外层事务负责
    return skipped


async def execute_legacy_backup_to_bytes(
    user, remark: str, db: AsyncSession,
    tables: list[str] | None = None,
    exclude_tables: list[str] | None = None,
) -> bytes:
    """Legacy JSON 备份 (v1.0)，用于无 pg_dump 环境。

    tables / exclude_tables（P1-2）：表级过滤，二选一；默认全表。
    """
    from fastapi_app.shared_models import Base
    table_payloads: dict[str, dict[str, object]] = {}
    backup_data = {
        'version': '1.0',
        'exported_at': datetime.now(UTC).strftime('%Y-%m-%d %H:%M:%S'),
        'exported_by': user.username if hasattr(user, 'username') else str(user.id),
        'remark': remark,
        'tables': table_payloads,
    }
    # 先查询实际存在的表，避免查询不存在的表导致事务失败
    existing_result = await db.execute(
        text("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")
    )
    existing_tables = {r[0] for r in existing_result.fetchall()}

    include_set = set(tables) if tables else None
    exclude_set = set(exclude_tables) if exclude_tables else None
    for table in Base.metadata.sorted_tables:
        name = str(table.name)
        if include_set is not None and name not in include_set:
            continue
        if exclude_set is not None and name in exclude_set:
            continue
        if name not in existing_tables:
            logger.warning(f'跳过不存在的表: {name}')
            table_payloads[name] = {'error': '表不存在', 'count': 0, 'rows': []}
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
                table_payloads[name] = {'columns': columns, 'rows': serialized_rows, 'count': len(serialized_rows)}
                await nested.commit()  # manual-tx: savepoint 嵌套事务管理
            except (SQLAlchemyError, ValueError, OSError) as e:
                await nested.rollback()  # manual-tx: savepoint 嵌套事务管理
                logger.error('备份表 %s 失败: %s', name, e)
                table_payloads[name] = {'error': str(e), 'count': 0, 'rows': []}
        except (SQLAlchemyError, ValueError, OSError) as e:
            logger.error('备份表 %s 初始化失败: %s', name, e)
            table_payloads[name] = {'error': str(e), 'count': 0, 'rows': []}
    return _encode_backup_json(backup_data)


def _encode_backup_json(backup_data: dict) -> bytes:
    """紧凑序列化：indent 会让备份体积放大约一倍，恢复侧只依赖 JSON 结构。"""
    return json.dumps(backup_data, ensure_ascii=False, separators=(',', ':')).encode('utf-8')


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


async def _disable_fk_constraints(db: AsyncSession) -> bool:
    """superuser 时禁用外键约束，返回是否已设置 replica 角色。"""
    try:
        is_super = await db.execute(text("SELECT usesuper FROM pg_user WHERE usename = current_user"))
        if is_super.scalar():
            await db.execute(text("SET session_replication_role = 'replica'"))
            return True
        logger.info('当前用户非superuser，跳过禁用外键约束（将使用ON CONFLICT处理冲突）')
    except (SQLAlchemyError, OSError) as e:
        logger.warning(f'禁用外键约束失败: {e}')
    return False


async def _re_enable_fk_constraints(db: AsyncSession, replication_role_set: bool) -> None:
    if replication_role_set:
        try:
            await db.execute(text("SET session_replication_role = 'origin'"))
        except (SQLAlchemyError, OSError) as e:
            logger.warning(f'重新启用外键约束失败: {e}')


async def _clear_tables_for_restore(db: AsyncSession, backup_data: dict) -> list[str]:
    """清空备份包含的表，返回清空失败的表名（F7: 失败必须显式上报，不能静默合并）。"""
    from fastapi_app.shared_models import Base

    delete_failed: list[str] = []
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
            delete_failed.append(table_name)
            logger.warning(f'清空表 {table_name} 失败（外键约束）: {e}')
    return delete_failed


async def _invalidate_caches_after_restore() -> None:
    try:
        from fastapi_app.core.cache import CacheDomain, invalidate_related_caches
        await invalidate_related_caches(CacheDomain.ALL)
    except (RuntimeError, OSError, ValueError) as e:
        logger.warning(f'恢复后缓存清除失败: {e}')
    try:
        from fastapi_app.core.purchase_cache import invalidate_purchase_caches
        await invalidate_purchase_caches()  # 2026-08-24 审计修正: 协程必须 await
    except (RuntimeError, OSError, ValueError) as e:
        logger.warning(f'恢复后采购缓存清除失败: {e}')


async def _verify_restored_json(db: AsyncSession, backup_data: dict) -> dict[str, object]:
    """恢复后校验（JSON 路径：L2 指纹退化为跳过）。"""
    from .verify import verify_restore

    verification: dict[str, object] = {'overall_pass': True}
    try:
        manifest_tables = {
            tname: {'rows': td.get('count', len(td.get('rows', [])))}
            for tname, td in backup_data.get('tables', {}).items()
        }
        # 2026-10-03 第八轮审计：此前用**独立连接** `_AsyncSessionLocal()` 校验，而此刻
        # 主事务只 `flush()` 未 `commit`（commit 在 strategies.py 的调用方）→ READ COMMITTED
        # 下独立连接看不到未提交的 DELETE/INSERT，读到的是**还原前**数据，「还原后校验」
        # 实际没在校验还原结果。verify_restore 只做 SELECT，改用同一 session 即看到还原结果。
        # JSON 路径不传 manifest_fingerprints：JSON 序列化会改变列的精确定文本
        # 表示（float/字节/JSON 格式化/timestamptz 等），即便数据逻辑等价，基于
        # COALESCE(col::text) 的 L2 指纹也必然假阴性。故 L2 对 JSON 路径退化为
        # 跳过（match=None，不计 mismatch），overall_pass 依赖真实可验证的
        # L1 行数 + L4 表结构。psql 路径（二进制级精确）仍完整校验 L2。
        verification = await verify_restore(
            db, manifest_tables,
            manifest_fingerprints=None,
            manifest_schema=backup_data.get('schema_snapshot'),
        )
    except (SQLAlchemyError, ValueError, OSError) as e:
        logger.warning(f'恢复后验证失败: {e}')
        verification = {'overall_pass': False, 'error': str(e)}
    return verification


async def _reset_sequences_after_json_restore(db, tables) -> tuple[list[str], list[str]]:
    """P1-11：JSON 导入走显式主键，不消耗也不重置序列——收尾按 MAX(id) 对齐。

    返回 (已重置的表名, 错误列表)。单表失败只记错误、不中止：数据已恢复，
    序列问题应进 errors 让 database.status 报 partial，而不是静默或推翻整次恢复。
    """
    reset: list[str] = []
    errors: list[str] = []
    for t in tables:
        if 'id' not in t.c:
            continue
        table_name = str(t.name)
        try:
            seq = (await db.execute(
                text("SELECT pg_get_serial_sequence(:tbl, 'id')"), {'tbl': table_name},
            )).scalar()
            if not seq:
                continue
            quoted = quote_table(table_name)
            await db.execute(
                text(
                    # 必须用 CAST(...) 而不是 :seq::regclass：SQLAlchemy 的绑定参数
                    # 正则会把 `:seq::` 解析成 `:se`（回溯到 (?!:) 能过的最短前缀），
                    # 编译后原样保留 `:seq::regclass` → 服务端语法错误 → 整个恢复事务被
                    # 中止（提交变回滚），而结果只报 partial。
                    f'SELECT setval(CAST(:seq AS regclass), '
                    f'COALESCE((SELECT MAX(id) FROM {quoted}), 1), '
                    f'(SELECT MAX(id) FROM {quoted}) IS NOT NULL)'
                ),
                {'seq': seq},
            )
        except (SQLAlchemyError, OSError, ValueError) as exc:
            # defensive: 单表序列失败不得推翻已恢复的数据，但必须可见（status=partial）
            errors.append(f'{table_name}: 主键序列重置失败（{exc}）')
            logger.warning('JSON 恢复后重置 %s 主键序列失败: %s', table_name, exc)
            continue
        reset.append(table_name)
    return reset, errors


async def _restore_tables_from_json(db, tables_to_restore, backup_data, _report, total_tables) -> tuple[dict, int, list]:
    """逐表从 JSON 恢复数据，返回 (results, total_inserted, errors)。"""
    results = {}
    total_inserted = 0
    errors = []
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
        # 自引用外键（如 permission.parent_id）需父行先于子行插入，
        # 否则主键行序导致子行先插触发外键违规。整表排序后再切分批。
        rows = _topo_sort_self_referencing(table, rows)
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

    return results, total_inserted, errors


async def restore_legacy_json(backup_data: dict, db: AsyncSession, task_id: str | None = None) -> dict:
    """从 Legacy JSON 格式备份恢复数据库 (v1.0)"""
    from fastapi_app.core.backup_progress import update_progress as _upd_prog
    from fastapi_app.shared_models import Base

    async def _report(sub: float, detail: str = ''):
        if task_id:
            await _upd_prog(task_id, 'restore_db', sub, detail)
            await asyncio.sleep(0)

    # 计算需要恢复的表数量用于进度计算
    tables_to_restore = [t for t in Base.metadata.sorted_tables if str(t.name) in backup_data.get('tables', {})]
    total_tables = len(tables_to_restore)

    # 2026-10-17 审计 P2-14：session_replication_role 是会话级设置，rollback 不会
    # 复位。此前只有成功路径重新启用，失败路径直接 raise，连接归还池后仍带
    # replica 角色（后续写入绕过外键）。改为 finally 统一复位。
    replication_role_set = None
    try:
        replication_role_set = await _disable_fk_constraints(db)

        await _report(0.05, '清空现有数据...')
        delete_failed = await _clear_tables_for_restore(db, backup_data)

        results, total_inserted, errors = await _restore_tables_from_json(
            db, tables_to_restore, backup_data, _report, total_tables
        )

        await db.flush()
        # P1-11：显式主键导入后序列与表内 MAX(id) 脱钩，跨环境恢复首次自然插入必 23505。
        sequences_reset, seq_errors = await _reset_sequences_after_json_restore(db, tables_to_restore)
        errors.extend(seq_errors)
        await _invalidate_caches_after_restore()
        verification = await _verify_restored_json(db, backup_data)
    except (SQLAlchemyError, ValueError, OSError) as e:
        await db.rollback()  # manual-tx: try/except 内显式事务控制
        raise RestoreError(f'恢复过程中出错: {e}') from e
    finally:
        if replication_role_set:
            try:
                await _re_enable_fk_constraints(db, replication_role_set)
            except (SQLAlchemyError, OSError, ValueError) as exc:
                # defensive: 复位失败不能覆盖原始恢复异常，只告警
                logger.warning('恢复后重新启用外键约束失败: %s', exc)

    # F7: 清空失败的表以"合并"而非"回滚"语义恢复——快照之后新增/变更的旧行会残留，
    # 必须先进入 errors，database.status 才能与端点口径一致地报 partial。
    # （此前在构造 result_dict 之后才 append，导致 database.status 恒为 ok，
    #  与其自身非空的 errors 自相矛盾；端点虽按 errors 报 partial，但该字段会误导直接读它的人。）
    for t in delete_failed:
        errors.append(f'{t}: 清空失败，本表为合并恢复（备份点之后的旧行可能残留）')

    result_dict = {
        'database': {
            'status': 'ok' if not errors else 'partial',
            'total_inserted': total_inserted,
            'sequences_reset': len(sequences_reset),
        },
        'total_inserted': total_inserted, 'results': results, 'errors': errors,
        'verification': verification,
    }
    if not verification.get('overall_pass', True):
        result_dict['_verification_failed'] = True
    return result_dict
