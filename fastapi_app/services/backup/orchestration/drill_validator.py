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


def _safe_sql_ident(name: str) -> str:
    """校验标识符格式并返回双引号包裹形式，防止 SQL 注入。"""
    if not name or not _IDENT_RE.match(name):
        raise ValueError(f"非法标识符: {name!r}")
    return f'"{name}"'


def _safe_sql_idents(names: list[str]) -> list[str]:
    """批量校验标识符。"""
    return [_safe_sql_ident(name) for name in names]


async def _load_fk_groups(conn) -> dict[str, dict[str, Any]]:
    """按约束名聚合外键定义（支持复合外键）。

    子表列与引用表列分别聚合后再按 ordinal_position 对齐，避免直接 JOIN
    information_schema.constraint_column_usage 产生笛卡尔积导致列错位。
    """
    result = await conn.execute(text("""
        WITH fk_base AS (
            SELECT
                tc.constraint_name,
                tc.table_name,
                kcu.column_name,
                kcu.ordinal_position
            FROM
                information_schema.table_constraints AS tc
                JOIN information_schema.key_column_usage AS kcu
                  ON tc.constraint_name = kcu.constraint_name
            WHERE tc.constraint_type = 'FOREIGN KEY'
        ),
        fk_ref AS (
            SELECT
                tc.constraint_name,
                ccu.table_name AS foreign_table_name,
                ccu.column_name AS foreign_column_name,
                ccu.ordinal_position
            FROM
                information_schema.table_constraints AS tc
                JOIN information_schema.constraint_column_usage AS ccu
                  ON ccu.constraint_name = tc.constraint_name
            WHERE tc.constraint_type = 'FOREIGN KEY'
        )
        SELECT
            b.constraint_name,
            b.table_name,
            b.column_name,
            r.foreign_table_name,
            r.foreign_column_name,
            b.ordinal_position
        FROM fk_base b
        JOIN fk_ref r
          ON b.constraint_name = r.constraint_name
         AND b.ordinal_position = r.ordinal_position
        ORDER BY b.constraint_name, b.ordinal_position
    """))
    fk_groups: dict[str, dict[str, Any]] = defaultdict(
        lambda: {'table': '', 'columns': [], 'foreign_table': '', 'foreign_columns': []}
    )
    for row in result.fetchall():
        constraint_name = row[0]
        group = fk_groups[constraint_name]
        group['constraint_name'] = constraint_name
        group['table'] = row[1]
        group['columns'].append(row[2])
        group['foreign_table'] = row[3]
        group['foreign_columns'].append(row[4])
    return fk_groups


async def _load_unique_groups(conn) -> dict[str, dict[str, Any]]:
    """按约束名聚合唯一约束定义（支持复合唯一索引）。"""
    result = await conn.execute(text("""
        SELECT
            tc.constraint_name,
            tc.table_name,
            kcu.column_name,
            kcu.ordinal_position
        FROM
            information_schema.table_constraints AS tc
            JOIN information_schema.key_column_usage AS kcu
              ON tc.constraint_name = kcu.constraint_name
        WHERE tc.constraint_type = 'UNIQUE'
        ORDER BY tc.constraint_name, kcu.ordinal_position
    """))
    unique_groups: dict[str, dict[str, Any]] = defaultdict(
        lambda: {'table': '', 'columns': []}
    )
    for row in result.fetchall():
        constraint_name = row[0]
        group = unique_groups[constraint_name]
        group['constraint_name'] = constraint_name
        group['table'] = row[1]
        group['columns'].append(row[2])
    return unique_groups


async def _check_fk_violations(conn, fk_groups: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """对每个 FK 执行 orphan row 检查（外键列非空但引用行缺失）。"""
    fk_violations = []
    for group in fk_groups.values():
        table = _safe_sql_ident(group['table'])
        columns = _safe_sql_idents(group['columns'])
        foreign_table = _safe_sql_ident(group['foreign_table'])
        foreign_columns = _safe_sql_idents(group['foreign_columns'])
        join_clause = ' AND '.join(
            f't.{c} = f.{fc}' for c, fc in zip(columns, foreign_columns, strict=False)
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
                'table': group['table'],
                'columns': group['columns'],
                'foreign_table': group['foreign_table'],
                'foreign_columns': group['foreign_columns'],
                'orphan_count': orphan_count,
            })
    return fk_violations


async def _check_unique_violations(conn, unique_groups: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """对每个 UNIQUE 约束执行重复值检查。"""
    unique_violations = []
    for group in unique_groups.values():
        table = _safe_sql_ident(group['table'])
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

    async def validate_recovery(self,
                               test_id: str,
                               test_env: dict[str, Any],
                               backup_info: dict[str, Any]) -> dict[str, Any]:
        """验证恢复结果"""
        validation_start_time = datetime.now()

        try:
            # 连接到测试数据库
            test_db_url = (
                f"postgresql+asyncpg://{test_env['test_db_user']}:"  # sql-safe: escape_like/绑定参数/常量片段
                f"{test_env['test_db_password']}@{test_env['test_db_host']}:"
                f"{test_env['test_db_port']}/{test_env['test_db_name']}"
            )

            test_engine = create_async_engine(test_db_url, poolclass=NullPool)

            validation_results = {
                'schema_validation': {'passed': False, 'details': {}},
                'data_validation': {'passed': False, 'details': {}},
                'constraint_validation': {'passed': False, 'details': {}},
                'performance_validation': {'passed': False, 'details': {}}
            }

            async with test_engine.connect() as conn:
                # 1. 验证模式
                if self.test_config['validate_schema']:
                    schema_result = await self._validate_schema(conn, backup_info)
                    validation_results['schema_validation'] = schema_result

                # 2. 验证数据完整性
                if self.test_config['validate_data_integrity']:
                    data_result = await self._validate_data_integrity(conn, backup_info)
                    validation_results['data_validation'] = data_result

                # 3. 验证约束
                if self.test_config['validate_constraints']:
                    constraint_result = await self._validate_constraints(conn)
                    validation_results['constraint_validation'] = constraint_result

                # 4. 验证性能
                performance_result = await self._validate_performance(conn)
                validation_results['performance_validation'] = performance_result

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

        except SQLAlchemyError as e:
            logger.error(f"恢复验证失败 {test_id}: {e}")
            return {
                'success': False,
                'test_id': test_id,
                'error': str(e),
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
                'passed': pass_percentage >= 80,  # 80%的表通过即认为通过
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
            max_duration = max(
                metric.get('duration_ms', 0)
                for metric in performance_metrics.values()
                if metric.get('status') == 'success'
            )

            passed = max_duration < 5000  # 所有查询应在5秒内完成

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
