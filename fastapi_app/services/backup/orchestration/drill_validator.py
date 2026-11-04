"""灾备演练的恢复结果验证器（2026-10-15 自 recovery_test_service.py 拆出）。

搬移原因：``DisasterRecoveryTestService`` 此前 1400+ 行、27 方法，把文件锁、
psql 导入、四族验证、报告、告警、查询混在一个类里（Divergent Change：新增备份
格式、新验证规则、新报告字段、新告警渠道都会改同一个类）。本模块只承担
「拿连接 → 逐族验证 → 汇总 finding dict」这一个变更原因。

代码为纯方法搬移，行为与拆分前逐字一致。
"""
import logging
import re
from collections import defaultdict
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from fastapi_app.services.backup.verify.core import quote_table

logger = logging.getLogger(__name__)


_IDENT_RE = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')

#: 单条验证语句的服务端超时（毫秒）。验证库上的 COUNT/JOIN 卡死时，宁可让该族
#: 明确失败（错误里写着 statement timeout），也不要把整轮演练拖到外层任务超时。
_VALIDATION_STATEMENT_TIMEOUT_MS = 30_000


def _safe_sql_ident(name: str) -> str:
    """校验标识符格式并返回双引号包裹形式，防止 SQL 注入。"""
    if not name or not _IDENT_RE.match(name):
        raise ValueError(f"非法标识符: {name!r}")
    return f'"{name}"'


def _safe_sql_idents(names: list[str]) -> list[str]:
    """批量校验标识符。"""
    return [_safe_sql_ident(name) for name in names]


def _qualified_ident(schema: str | None, name: str) -> str:
    """schema 限定标识符（两段都过白名单）。

    为什么不依赖 search_path：验证连接上没有任何 ``SET search_path``，同名表若
    同时存在于多个 schema，未限定的 ``"orders"`` 会解析到 search_path 里的第一个
    命中项——即可能校验了另一张表。显式限定后结果与连接状态无关。
    """
    ident = _safe_sql_ident(name)
    if schema:
        return f'{_safe_sql_ident(schema)}.{ident}'
    return ident


async def _load_fk_groups(conn) -> dict[str, dict[str, Any]]:
    """按 (schema, 表, 约束名) 聚合外键定义（支持复合外键，按列位置正确配对）。

    2026-11-04 三次迭代后的最终形态，逐条记录踩过的坑：

    1. **引用不存在的列**：原实现取 ``information_schema.constraint_column_usage
       .ordinal_position``——该视图没有这一列，于是约束验证每次都以
       ``UndefinedColumnError`` 判失败（真实报告
       backups/server/recovery_tests/recovery_test_20261101_041001_fbf72c.json）。
    2. **复合外键配对语义错误**：``key_column_usage``（子表列集合）与
       ``constraint_column_usage``（被引用表列集合）之间没有跨视图的位置对应关系。
       改用 ``pg_constraint.conkey/confkey``（按约束定义顺序排列，同下标即同列对），
       下标由 ``generate_subscripts`` 生成，列名由 ``pg_attribute`` 还原。
    3. **聚合键不够唯一**（QA 复核 High-1）：PostgreSQL 只要求约束名在**同一张表**
       范围内唯一，``public.a.fk_x`` 与 ``public.b.fk_x`` 完全合法。原先按
       ``schema.constraint_name`` 聚合，会把这两条不同表的外键合并成一条跨表假复合
       外键（列与引用表混在一起）。现在聚合键改为 ``schema.table.constraint_name``，
       并把 ``con.oid`` 一并带出——它是约束的**唯一身份**，跨表同名与重建同名都可区分。

    schema 处理：系统表全限定 ``pg_catalog``，schema 走 ``pg_namespace`` 显式关联
    （不依赖 search_path）；分组后由 ``_check_fk_violations`` 用
    ``_qualified_ident`` 生成 schema 限定的表名去查询。
    """
    result = await conn.execute(text("""
        SELECT
            src_ns.nspname  AS schema_name,
            src.relname     AS table_name,
            con.conname     AS constraint_name,
            con.oid::text   AS constraint_oid,
            src_att.attname AS column_name,
            tgt_ns.nspname  AS foreign_schema_name,
            tgt.relname     AS foreign_table_name,
            tgt_att.attname AS foreign_column_name,
            k.i             AS ordinal_position
        FROM pg_catalog.pg_constraint AS con
        JOIN pg_catalog.pg_class AS src
          ON src.oid = con.conrelid
        JOIN pg_catalog.pg_namespace AS src_ns
          ON src_ns.oid = src.relnamespace
        JOIN pg_catalog.pg_class AS tgt
          ON tgt.oid = con.confrelid
        JOIN pg_catalog.pg_namespace AS tgt_ns
          ON tgt_ns.oid = tgt.relnamespace
        JOIN LATERAL pg_catalog.generate_subscripts(con.conkey, 1) AS k(i)
          ON TRUE
        JOIN pg_catalog.pg_attribute AS src_att
          ON src_att.attrelid = con.conrelid
         AND src_att.attnum = con.conkey[k.i]
        JOIN pg_catalog.pg_attribute AS tgt_att
          ON tgt_att.attrelid = con.confrelid
         AND tgt_att.attnum = con.confkey[k.i]
        WHERE con.contype = 'f'
          AND array_length(con.conkey, 1) = array_length(con.confkey, 1)
          AND src_ns.nspname NOT IN ('pg_catalog', 'information_schema', 'pg_toast')
          AND tgt_ns.nspname NOT IN ('pg_catalog', 'information_schema', 'pg_toast')
        ORDER BY con.oid, k.i
    """))
    fk_groups: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            'schema': '', 'table': '', 'columns': [],
            'foreign_schema': '', 'foreign_table': '', 'foreign_columns': [],
        }
    )
    for row in result.fetchall():
        schema, table, constraint_name, constraint_oid = row[0], row[1], row[2], row[3]
        # 键含表名：不同表上的同名约束是两条独立外键（见 docstring 第 3 点）
        group = fk_groups[f'{schema}.{table}.{constraint_name}']
        group['constraint_name'] = constraint_name
        group['constraint_oid'] = constraint_oid
        group['schema'] = schema
        group['table'] = table
        group['columns'].append(row[4])
        group['foreign_schema'] = row[5]
        group['foreign_table'] = row[6]
        group['foreign_columns'].append(row[7])
    return fk_groups


async def _load_unique_groups(conn) -> dict[str, dict[str, Any]]:
    """按 (schema, 表, 约束名) 聚合唯一约束定义（支持复合唯一约束）。

    2026-11-04（QA 复核 High-1）重写：原实现走 ``information_schema``，且 JOIN 条件
    只有 ``constraint_name``——既没有 schema 也没有表名，于是
    (a) 跨 schema 的同名约束会被串到一起，把列集合拼成不存在的复合键；
    (b) 同一 schema 内不同表的同名唯一约束同样会混合（PG 只要求约束名在表内唯一）。

    现在与 ``_load_fk_groups`` 同源：``pg_constraint``(contype='u') + ``conkey`` 下标
    + ``pg_attribute`` 列名，聚合键 ``schema.table.constraint_name``，并带出
    ``con.oid`` 作为唯一身份。
    """
    result = await conn.execute(text("""
        SELECT
            ns.nspname      AS schema_name,
            cls.relname     AS table_name,
            con.conname     AS constraint_name,
            con.oid::text   AS constraint_oid,
            att.attname     AS column_name,
            k.i             AS ordinal_position
        FROM pg_catalog.pg_constraint AS con
        JOIN pg_catalog.pg_class AS cls
          ON cls.oid = con.conrelid
        JOIN pg_catalog.pg_namespace AS ns
          ON ns.oid = cls.relnamespace
        JOIN LATERAL pg_catalog.generate_subscripts(con.conkey, 1) AS k(i)
          ON TRUE
        JOIN pg_catalog.pg_attribute AS att
          ON att.attrelid = con.conrelid
         AND att.attnum = con.conkey[k.i]
        WHERE con.contype = 'u'
          AND array_length(con.conkey, 1) >= 1
          AND ns.nspname NOT IN ('pg_catalog', 'information_schema', 'pg_toast')
        ORDER BY con.oid, k.i
    """))
    unique_groups: dict[str, dict[str, Any]] = defaultdict(
        lambda: {'schema': '', 'table': '', 'columns': []}
    )
    for row in result.fetchall():
        schema, table, constraint_name, constraint_oid = row[0], row[1], row[2], row[3]
        group = unique_groups[f'{schema}.{table}.{constraint_name}']
        group['constraint_name'] = constraint_name
        group['constraint_oid'] = constraint_oid
        group['schema'] = schema
        group['table'] = table
        group['columns'].append(row[4])
    return unique_groups


async def _check_fk_violations(conn, fk_groups: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """对每个 FK 执行 orphan row 检查（外键列非空但引用行缺失）。

    子表/引用表都用 ``_load_fk_groups`` 带回的 schema 全限定，与连接上的
    search_path 无关（见 ``_qualified_ident``）。

    列数不一致属于「元数据自相矛盾」，必须显式报错（``zip(strict=True)`` 抛
    ValueError），不能靠 ``strict=False`` 静默截断——截断后的 JOIN 会漏掉列，
    让真实的 orphan 行数被低估成 0，等于把违规检查变成「永远通过」。
    """
    fk_violations = []
    for group in fk_groups.values():
        table = _qualified_ident(group.get('schema'), group['table'])
        columns = _safe_sql_idents(group['columns'])
        foreign_table = _qualified_ident(group.get('foreign_schema'), group['foreign_table'])
        foreign_columns = _safe_sql_idents(group['foreign_columns'])
        join_clause = ' AND '.join(
            f't.{c} = f.{fc}' for c, fc in zip(columns, foreign_columns, strict=True)
        )
        not_null_clause = ' AND '.join(f't.{c} IS NOT NULL' for c in columns)
        orphan_sql = text(f"""
            SELECT COUNT(*) FROM {table} t
            LEFT JOIN {foreign_table} f ON {join_clause}
            WHERE {not_null_clause} AND f.{foreign_columns[0]} IS NULL
        """)  # nosec B608
        orphan_count = (await conn.execute(orphan_sql)).scalar() or 0  # batch-loop: 逐表备份/恢复,无法批量
        if orphan_count > 0:
            fk_violations.append({
                'constraint_name': group['constraint_name'],
                'schema': group.get('schema', ''),
                'table': group['table'],
                'columns': group['columns'],
                'foreign_table': group['foreign_table'],
                'foreign_columns': group['foreign_columns'],
                'orphan_count': orphan_count,
            })
    return fk_violations


async def _check_unique_violations(conn, unique_groups: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """对每个 UNIQUE 约束执行重复值检查（表名 schema 限定）。"""
    unique_violations = []
    for group in unique_groups.values():
        table = _qualified_ident(group.get('schema'), group['table'])
        columns = _safe_sql_idents(group['columns'])
        col_list = ', '.join(columns)
        dup_sql = text(f"""
            SELECT COUNT(*) FROM (
                SELECT {col_list} FROM {table}
                WHERE {' AND '.join(f'{c} IS NOT NULL' for c in columns)}
                GROUP BY {col_list} HAVING COUNT(*) > 1
            ) t
        """)  # nosec B608
        dup_groups = (await conn.execute(dup_sql)).scalar() or 0  # batch-loop: 逐表备份/恢复,无法批量
        if dup_groups > 0:
            unique_violations.append({
                'constraint_name': group['constraint_name'],
                'schema': group.get('schema', ''),
                'table': group['table'],
                'columns': group['columns'],
                'duplicate_groups': dup_groups,
            })
    return unique_violations


class DrillValidator:
    """恢复结果验证器：连接测试库，按 schema/数据完整性/约束/性能四族验证并汇总。

    纯方法搬移自 ``DisasterRecoveryTestService._validate_recovery`` 及其四个子方法
    （2026-10-15 拆分），行为逐字一致。
    """

    def __init__(self, test_config: dict[str, Any]):
        self.test_config = test_config

    async def _run_family(self, family: str, func, *args) -> dict[str, Any]:
        """执行单个验证族并逐族兜底，保证「一族的意外」不吞掉其余族的结果。

        四个族的子方法各自已捕获 SQLAlchemyError/ValueError，但调用点仍可能抛出
        其它类型（例如 future 改动里漏网的 TypeError）。此前这类异常只能由
        ``validate_recovery`` 最外层的 except 接住，整份报告退化为
        ``{'error': ...}``，其余三族已算出的结果全部丢弃——对灾备体检这种
        「证据优先」的场景，比单族失败伤害大得多。
        """
        try:
            return await func(*args)
        except Exception as e:  # broad-except: 单族异常必须隔离，不得吞掉其余验证族结果
            logger.error(f"验证族 {family} 执行失败: {e}")
            return {
                'passed': False,
                'error': str(e),
                'details': {}
            }

    async def validate_recovery(self,
                               test_id: str,
                               test_env: dict[str, Any],
                               backup_info: dict[str, Any]) -> dict[str, Any]:
        """验证恢复结果。

        失败语义（2026-11-04 收敛）：任何阶段异常都返回**结构化失败结果**
        （``success=False`` + ``error`` + 完整 ``results`` 骨架），不再让异常逃逸
        到调用方。原因：连接阶段抛出的 asyncpg ``PostgresError`` 不一定被包成
        ``SQLAlchemyError``，逃逸后调用方只能记一条日志，报告与告警都拿不到信息。
        """
        validation_start_time = datetime.now()

        try:
            # 连接到测试数据库
            test_db_url = (
                f"postgresql+asyncpg://{test_env['test_db_user']}:"  # sql-safe: escape_like/绑定参数/常量片段
                f"{test_env['test_db_password']}@{test_env['test_db_host']}:"
                f"{test_env['test_db_port']}/{test_env['test_db_name']}"
            )

            # 2026-11-04：验证连接改用 AUTOCOMMIT（单语句自动提交）。
            # 根因：四族验证此前共用一个 AsyncConnection 的**隐式事务**。任一族里
            # 单条 SQL 失败（如 constraint 族的 UndefinedColumnError）后，PostgreSQL
            # 会把这个事务标记为 aborted，后续每一条 SQL 都只返回
            # InFailedSQLTransactionError —— 一个查询写错被放大成「除首族外整份
            # 体检报告全灭」（真实报告 recovery_test_20261101_041001_fbf72c.json：
            # performance 三项全部 InFailedSQLTransactionError）。
            # 为什么安全：验证族只做**只读**的元数据查询与 COUNT(*)（不含 INSERT/
            # UPDATE/DELETE/DDL），没有跨语句原子性要求；自动提交下每条语句自成
            # 事务，失败只影响它自己，不会留下 aborted 事务污染后续验证。
            # statement_timeout：验证库上一条卡死的 COUNT/JOIN 会把整轮演练拖到
            # 外层任务超时（调用方看到的是「演练超时」，看不到是哪条 SQL）。给每条
            # 语句一个明确上限，失败就是可读的 statement timeout 错误。
            test_engine = create_async_engine(
                test_db_url,
                poolclass=NullPool,
                isolation_level='AUTOCOMMIT',
                connect_args={'server_settings': {
                    'statement_timeout': str(_VALIDATION_STATEMENT_TIMEOUT_MS),
                }},
            )

            validation_results = {
                'schema_validation': {'passed': False, 'details': {}},
                'data_validation': {'passed': False, 'details': {}},
                'constraint_validation': {'passed': False, 'details': {}},
                'performance_validation': {'passed': False, 'details': {}}
            }

            try:
                async with test_engine.connect() as conn:
                    # 1. 验证模式
                    if self.test_config['validate_schema']:
                        validation_results['schema_validation'] = await self._run_family(
                            'schema', self._validate_schema, conn, backup_info,
                        )

                    # 2. 验证数据完整性
                    if self.test_config['validate_data_integrity']:
                        validation_results['data_validation'] = await self._run_family(
                            'data_integrity', self._validate_data_integrity, conn, backup_info,
                        )

                    # 3. 验证约束
                    if self.test_config['validate_constraints']:
                        validation_results['constraint_validation'] = await self._run_family(
                            'constraints', self._validate_constraints, conn,
                        )

                    # 4. 验证性能
                    validation_results['performance_validation'] = await self._run_family(
                        'performance', self._validate_performance, conn,
                    )
            finally:
                # 连接/驱动异常也要释放引擎（NullPool 下泄漏的是 asyncpg 连接与
                # 其事件循环回调，后续轮次会报 "Event loop is closed"）
                await test_engine.dispose()

            # 计算总体验证结果
            all_passed = all(
                result['passed']
                for key, result in validation_results.items()
                if key.endswith('_validation')
            )

            validation_duration = (datetime.now() - validation_start_time).total_seconds()

            result = {
                'success': all_passed,
                'test_id': test_id,
                'all_passed': all_passed,
                'validation_duration_seconds': round(validation_duration, 2),
                'results': validation_results,
                'start_time': validation_start_time.isoformat(),
                'end_time': datetime.now().isoformat()
            }

            logger.info(f"恢复验证完成: {test_id}, 结果: {'通过' if all_passed else '失败'}")
            return result

        except Exception as e:  # broad-except: 连接阶段异常形态不受控（见 docstring）
            # 2026-11-04：连接/驱动层的异常不一定被包成 SQLAlchemyError —— asyncpg 的
            # PostgresError（如 3D000 invalid_catalog_name、28P01 认证失败）在
            # ``engine.connect()`` 阶段可能原样抛出；只捕 SQLAlchemyError 会让整轮
            # 验证以未处理异常结束，调用方拿不到结构化失败结果，也无法进报告/告警
            # （只留一行日志 = 演练「静默失败」）。这里统一收敛成可归档的失败 dict。
            logger.error(f"恢复验证失败 {test_id}: {type(e).__name__}: {e}")
            return {
                'success': False,
                'test_id': test_id,
                'all_passed': False,
                'error': f'{type(e).__name__}: {e}',
                'results': {},
                'start_time': validation_start_time.isoformat(),
                'validation_duration_seconds': round((datetime.now() - validation_start_time).total_seconds(), 2)
            }

    async def _validate_schema(self, conn, backup_info: dict[str, Any]) -> dict[str, Any]:
        """验证数据库模式"""
        try:
            # 查询所有表
            result = await conn.execute(text("""
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public'
            """))
            tables = [row[0] for row in result.fetchall()]

            # 期望表清单取自 manifest['tables']。原先取 manifest['includes'] ——
            # 那里装的是 filestore_count / config_files / redis_rdb 这类**打包项、不是表名**，
            # 于是 missing_tables 恒非空、schema 验证**恒判失败** → 报告 overall_success=False
            # → 发"灾备演练失败"告警（该任务已登记为月度调度，会周期性误报、淹没真故障）。
            expected_tables = list(backup_info.get('manifest', {}).get('tables', {}).keys())
            if not expected_tables:
                expected_tables = list(backup_info.get('tables', {}).keys())

            missing_tables = [t for t in expected_tables if t not in tables]
            extra_tables = [t for t in tables if t not in expected_tables and not t.startswith('backup_test_')]

            # 若测试库仅包含 dummy 表，说明真实 schema 未恢复，必须判失败
            only_dummy_tables = len(tables) > 0 and all(t.startswith('backup_test_') for t in tables)
            passed = len(missing_tables) == 0 and not only_dummy_tables

            return {
                'passed': passed,
                'schema_reconstruction_unimplemented': only_dummy_tables,
                'table_count': len(tables),
                'expected_tables': len(expected_tables),
                'missing_tables': missing_tables,
                'extra_tables': extra_tables,
                'details': {
                    'tables_found': tables,
                    'tables_expected': expected_tables
                }
            }

        except SQLAlchemyError as e:
            logger.error(f"验证模式失败: {e}")
            return {
                'passed': False,
                'error': str(e),
                'details': {}
            }

    async def _validate_data_integrity(self, conn, backup_info: dict[str, Any]) -> dict[str, Any]:
        """验证数据完整性"""
        try:
            # B5 修复：tables 只存在于 manifest（_get_backup_info 从不设置顶层
            # 'tables' 键），旧实现恒取空 dict → 0 表 → 0% 通过率 → 演练恒失败
            tables = backup_info.get('tables') or backup_info.get('manifest', {}).get('tables', {})
            validation_results = {}

            for table_name, table_data in tables.items():
                if table_name.startswith('_'):
                    continue

                try:
                    # 查询表中的行数（使用 quote_table 白名单校验防止注入）
                    result = await conn.execute(  # batch-loop: 逐表备份/恢复,无法批量
                        text(f'SELECT COUNT(*) FROM {quote_table(table_name)}')  # nosec B608 — quote_table 白名单校验
                    )
                    row_count = result.scalar() or 0

                    # 期望行数：**全量** manifest 的键是 'rows'（int），**增量**才是 'count'；
                    # 增量与旧 dump.json 的 'rows' 是序列化行列表。原先只读 'count'，
                    # 全量演练时恒得 0 → `row_count >= min(0, sample)` 恒真 → **校验恒通过**
                    # （恢复少导/漏表也报"数据验证通过"，给出虚假的灾备就绪结论）。
                    raw_expected = table_data.get('count')
                    if raw_expected is None:
                        rows_val = table_data.get('rows', 0)
                        raw_expected = len(rows_val) if isinstance(rows_val, list) else rows_val
                    expected_rows = int(raw_expected or 0)

                    validation_results[table_name] = {
                        'expected': expected_rows,
                        'actual': row_count,
                        # 第八轮审计：原 `row_count >= min(expected_rows, test_sample_size)`
                        # 让 10 万行的表只还原 100 行（= sample_size）即判通过 → 演练对
                        # 「几乎空库」报成功。行数校验改为**必须全量一致**；sample_size
                        # 仅保留用于其它抽样展示，不参与 pass 判定。
                        'passed': row_count == expected_rows,
                        'match_percentage': round((row_count / expected_rows * 100) if expected_rows > 0 else 0, 2)
                    }

                except SQLAlchemyError as e:
                    validation_results[table_name] = {
                        'expected': table_data.get('count', 0),
                        'actual': 0,
                        'passed': False,
                        'error': str(e)
                    }

            # 计算总体结果
            total_tables = len(validation_results)
            passed_tables = sum(1 for result in validation_results.values() if result.get('passed', False))
            pass_percentage = (passed_tables / total_tables * 100) if total_tables > 0 else 0

            return {
                # Z05-R23：灾备就绪不允许「最多 1/5 表数据不符仍通过」，与单表口径
                # （全量一致）对齐，仅 100% 通过才算通过。
                'passed': total_tables > 0 and passed_tables == total_tables,
                'pass_percentage': round(pass_percentage, 2),
                'total_tables': total_tables,
                'passed_tables': passed_tables,
                'failed_tables': total_tables - passed_tables,
                'details': validation_results
            }

        except Exception as e:  # defensive: data integrity validation must report partial results
            logger.error(f"验证数据完整性失败: {e}")
            return {
                'passed': False,
                'error': str(e),
                'details': {}
            }

    async def _validate_constraints(self, conn) -> dict[str, Any]:
        """验证数据库约束完整性。

        对每个外键约束执行 orphan row 检查（外键列非空但引用行缺失），
        对每个唯一约束执行重复值检查，存在违反即视为验证失败。
        支持复合外键与复合唯一约束，按约束名分组后按列组合检查。
        """
        try:
            fk_groups = await _load_fk_groups(conn)
            unique_groups = await _load_unique_groups(conn)
            fk_violations = await _check_fk_violations(conn, fk_groups)
            unique_violations = await _check_unique_violations(conn, unique_groups)

            # 约束总数为零（schema 损坏或无约束定义）时视为验证失败，
            # 避免空约束列表场景下 passed=True 掩盖"约束缺失"灾难情况
            total_constraints = len(fk_groups) + len(unique_groups)
            coverage_warning = total_constraints == 0
            passed = (
                not coverage_warning
                and len(fk_violations) == 0
                and len(unique_violations) == 0
            )
            return {
                'passed': passed,
                'coverage_warning': coverage_warning,
                'foreign_key_count': len(fk_groups),
                'unique_constraint_count': len(unique_groups),
                'fk_violations': fk_violations,
                'unique_violations': unique_violations,
                'details': {
                    'foreign_keys': list(fk_groups.values()),
                    'unique_constraints': list(unique_groups.values()),
                }
            }

        except (SQLAlchemyError, ValueError) as e:
            # ValueError 来自 _safe_sql_ident 对非法标识符的拒绝；
            # SQLAlchemyError 来自 information_schema 查询失败。
            # 两者均视为约束验证失败，避免异常逃逸至端点 500。
            logger.error(f"验证约束失败: {e}")
            return {
                'passed': False,
                'error': str(e),
                'details': {}
            }

    async def _validate_performance(self, conn) -> dict[str, Any]:
        """验证性能"""
        try:
            performance_metrics: dict[str, dict[str, Any]] = {}

            # 测试查询性能
            test_queries = [
                ("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'public'", "count_tables"),
                ("SELECT version()", "db_version"),
                ("SELECT pg_database_size(current_database())", "db_size"),
            ]

            for query, name in test_queries:
                start_time = datetime.now()
                try:
                    result = await conn.execute(text(query))  # batch-loop: 逐表备份/恢复,无法批量
                    result.fetchall()  # 确保查询执行
                    end_time = datetime.now()
                    duration_ms = (end_time - start_time).total_seconds() * 1000

                    performance_metrics[name] = {
                        'query': query,
                        'duration_ms': round(duration_ms, 2),
                        'status': 'success'
                    }
                except SQLAlchemyError as e:
                    performance_metrics[name] = {
                        'query': query,
                        'duration_ms': 0,
                        'status': 'failed',
                        'error': str(e)
                    }

            # 检查所有查询是否在合理时间内完成
            durations = [
                metric.get('duration_ms', 0)
                for metric in performance_metrics.values()
                if metric.get('status') == 'success'
            ]
            max_duration = max(durations, default=0)
            # 全部查询失败时 durations 为空——不能因 max(default=0) 误判为通过
            passed = bool(durations) and max_duration < 5000

            return {
                'passed': passed,
                'max_duration_ms': round(max_duration, 2),
                'threshold_ms': 5000,
                'details': performance_metrics
            }

        except (SQLAlchemyError, ValueError) as e:
            logger.error(f"验证性能失败: {e}")
            return {
                'passed': False,
                'error': str(e),
                'details': {}
            }
