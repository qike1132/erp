"""
灾难恢复测试服务

定期从备份中恢复测试数据到临时环境，验证恢复数据的完整性和可用性
"""

import contextlib
import json
import logging
import secrets
import shutil
import tempfile
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from fastapi_app.services.backup._constants import BACKUP_DIR, RECOVERY_TEST_LOCK_ID
from fastapi_app.services.backup.metrics.alert_service import alert_service
from fastapi_app.services.backup.orchestration.drill_validator import DrillValidator
from fastapi_app.services.backup.orchestration.recovery_test_history import RecoveryTestHistoryService
from fastapi_app.services.backup.records import ensure_backup_dir
from fastapi_app.services.backup.verify.core import quote_table

logger = logging.getLogger(__name__)

# 标识符校验与 FK/UNIQUE 违规检查 helpers（_safe_sql_ident 系、_load_fk_groups 等）
# 已于 2026-10-15 随验证族一起迁至 drill_validator.py（纯搬移）。


class DisasterRecoveryTestService:
    """灾难恢复测试服务类"""

    def __init__(self):
        self.test_config = self._load_test_config()
        self.test_results_dir = BACKUP_DIR / 'recovery_tests'

    def _load_test_config(self) -> dict[str, Any]:
        """加载测试配置"""
        import os

        return {
            # 测试频率（天）
            'test_frequency_days': int(os.environ.get('BACKUP_RECOVERY_TEST_FREQUENCY', '7')),

            # M3: 加密备份演练密码（也可逐次传入），用于解密历史 .enc 包
            'test_password': os.environ.get('BACKUP_TEST_PASSWORD', ''),

            # 测试数据库配置（F5: 凭据缺省回落主库配置——此前默认 postgres/空密码
            # 在本机必然认证失败，演练从未真正连通过）
            # 第十四轮：用 `or` 而非 `.get(k, default)` —— .env 里 BACKUP_TEST_DB_PASSWORD=
            # 这类**键存在但值为空**时 `.get` 不会回退，仍拿空口令连库 → 认证失败。
            'test_db_host': os.environ.get('BACKUP_TEST_DB_HOST') or os.environ.get('DB_HOST', 'localhost'),
            'test_db_port': int(os.environ.get('BACKUP_TEST_DB_PORT') or os.environ.get('DB_PORT', '5432')),
            'test_db_name': os.environ.get('BACKUP_TEST_DB_NAME') or 'erp_backup_test',
            'test_db_user': os.environ.get('BACKUP_TEST_DB_USER') or os.environ.get('DB_USER', 'erp_app'),
            'test_db_password': os.environ.get('BACKUP_TEST_DB_PASSWORD') or os.environ.get('DB_PASSWORD', ''),

            # 测试设置
            'test_sample_size': int(os.environ.get('BACKUP_TEST_SAMPLE_SIZE', '100')),
            'test_timeout_minutes': int(os.environ.get('BACKUP_TEST_TIMEOUT_MINUTES', '30')),
            'cleanup_test_db': os.environ.get('BACKUP_CLEANUP_TEST_DB', 'true').lower() == 'true',

            # 验证设置
            'validate_data_integrity': os.environ.get('BACKUP_VALIDATE_INTEGRITY', 'true').lower() == 'true',
            'validate_schema': os.environ.get('BACKUP_VALIDATE_SCHEMA', 'true').lower() == 'true',
            'validate_constraints': os.environ.get('BACKUP_VALIDATE_CONSTRAINTS', 'true').lower() == 'true',

            # 通知设置
            'notify_on_test_success': os.environ.get('BACKUP_NOTIFY_TEST_SUCCESS', 'true').lower() == 'true',
            'notify_on_test_failure': os.environ.get('BACKUP_NOTIFY_TEST_FAILURE', 'true').lower() == 'true',
            'test_report_retention_days': int(os.environ.get('BACKUP_TEST_REPORT_RETENTION_DAYS', '30')),
        }

    def _acquire_recovery_test_lock(self):
        """获取跨进程的恢复演练互斥锁（PG advisory lock）。

        第十四轮：演练会 DROP/CREATE 同名测试库，同秒两次触发（cron 撞手动）会互毁。
        返回 (engine, conn) 持锁句柄；已被占用时抛 RuntimeError（fail-fast）。
        """
        cfg = self.test_config
        engine = create_engine(
            f"postgresql+psycopg://{cfg['test_db_user']}:{cfg['test_db_password']}"
            f"@{cfg['test_db_host']}:{cfg['test_db_port']}/postgres",  # sql-safe: 常量片段
            poolclass=NullPool,
        )
        conn = engine.connect()
        got = conn.execute(
            text("SELECT pg_try_advisory_lock(:lock_id)"), {"lock_id": RECOVERY_TEST_LOCK_ID}
        ).scalar()
        if not got:
            conn.close()
            engine.dispose()
            raise RuntimeError('已有灾难恢复演练在进行中，请稍后重试')
        return engine, conn

    @staticmethod
    def _release_recovery_test_lock(lock) -> None:
        """释放 `_acquire_recovery_test_lock` 的锁与连接（失败仅记日志）。"""
        engine, conn = lock
        with contextlib.suppress(Exception):
            conn.execute(
                text("SELECT pg_advisory_unlock(:lock_id)"), {"lock_id": RECOVERY_TEST_LOCK_ID}
            )
        with contextlib.suppress(Exception):
            conn.close()
            engine.dispose()

    async def perform_recovery_test(self, backup_file: str | None = None) -> dict[str, Any]:
        """
        执行灾难恢复测试

        Args:
            backup_file: 指定要测试的备份文件，如果为None则使用最新备份

        Returns:
            Dict[str, Any]: 测试结果
        """
        logger.info("开始执行灾难恢复测试...")

        test_start_time = datetime.now()
        # 第十四轮：秒级 test_id 在并发/同秒双触发下会同名测试库互毁 —— 加随机后缀保证唯一。
        test_id = test_start_time.strftime('%Y%m%d_%H%M%S') + '_' + secrets.token_hex(3)

        # 跨进程互斥：同一时刻只允许一个演练（建/删测试库是破坏性且同名的）
        lock = self._acquire_recovery_test_lock()
        test_env: dict[str, Any] | None = None
        cleanup_result: dict[str, Any] | None = None
        try:
            # 1. 准备测试环境
            test_env = await self._prepare_test_environment(test_id)

            # 2. 选择备份文件
            selected_backup = await self._select_backup_for_test(backup_file)
            if not selected_backup:
                return {
                    'test_id': test_id,
                    'success': False,
                    'error': '没有找到可用的备份文件进行测试',
                    'start_time': test_start_time.isoformat(),
                    'end_time': datetime.now().isoformat(),
                    'duration_seconds': (datetime.now() - test_start_time).total_seconds()
                }

            # 3. 执行恢复测试
            recovery_result = await self._execute_recovery_test(
                test_id, test_env, selected_backup
            )

            # 4. 验证恢复结果（2026-10-15 拆至 DrillValidator，纯搬移）
            validation_result = await DrillValidator(self.test_config).validate_recovery(
                test_id, test_env, selected_backup
            )

            # 6. 生成测试报告
            test_report = await self._generate_test_report(
                test_id, test_start_time, selected_backup,
                recovery_result, validation_result, cleanup_result or {'cleaned': False, 'message': '清理在 finally 中执行'}
            )

            # 7. 保存测试结果
            await self._save_test_result(test_report)

            # 8. 发送通知
            await self._send_test_notification(test_report)

            logger.info(f"灾难恢复测试完成: {test_id}")
            return test_report

        except Exception as e:  # defensive: recovery test orchestration must report failure gracefully
            logger.error(f"灾难恢复测试失败: {e}")

            # 发送错误告警
            await alert_service.send_alert(
                task_name='disaster_recovery_test',
                error=f"灾难恢复测试失败: {e!s}",
                task_type='recovery_test',
                severity='error',
                additional_info={
                    'test_id': test_id,
                    'error': str(e)
                }
            )

            return {
                'test_id': test_id,
                'success': False,
                'error': str(e),
                'start_time': test_start_time.isoformat(),
                'end_time': datetime.now().isoformat(),
                'duration_seconds': (datetime.now() - test_start_time).total_seconds()
            }
        finally:
            # B5 修复：无论成功/失败/异常都必须清理测试环境，否则每次演练
            # 都会在 PostgreSQL 泄漏一个 erp_backup_test_* 数据库及目录
            if test_env is not None:
                try:
                    cleanup_result = await self._cleanup_test_environment(test_env)
                except Exception as cleanup_err:  # broad-except: 清理失败不能掩盖主流程结果
                    logger.error(f"清理测试环境异常（{test_id}）: {cleanup_err}")
            # 释放演练互斥锁（第十四轮）
            self._release_recovery_test_lock(lock)

    async def _prepare_test_environment(self, test_id: str) -> dict[str, Any]:
        """准备测试环境"""
        try:
            # 创建测试数据库
            test_db_name = f"{self.test_config['test_db_name']}_{test_id}"

            # 使用主数据库连接创建测试数据库
            import os

            from sqlalchemy import create_engine

            # 获取主数据库连接信息
            db_host = os.environ.get('DB_HOST', 'localhost')
            db_port = os.environ.get('DB_PORT', '5432')
            db_user = os.environ.get('DB_USER', 'postgres')
            db_password = os.environ.get('DB_PASSWORD', '')

            # 创建同步引擎用于管理数据库
            sync_engine = create_engine(
                f"postgresql+psycopg://{db_user}:{db_password}@{db_host}:{db_port}/postgres",  # sql-safe: escape_like/绑定参数/常量片段
                poolclass=NullPool
            )

            # 检查测试数据库是否已存在
            # CREATE/DROP DATABASE 属于 DDL，不能在事务块中执行，使用 AUTOCOMMIT 模式
            with sync_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
                result = conn.execute(
                    text("SELECT 1 FROM pg_database WHERE datname = :dbname"),
                    {'dbname': test_db_name}
                )
                db_exists = result.scalar() is not None

                if db_exists:
                    # 删除现有测试数据库（使用 quote_table 白名单校验防止注入）
                    conn.execute(text(f'DROP DATABASE IF EXISTS {quote_table(test_db_name)}'))  # nosec B608 — quote_table 白名单校验
                    logger.info(f"删除已存在的测试数据库: {test_db_name}")

                # 创建新的测试数据库（使用 quote_table 白名单校验防止注入）
                conn.execute(text(f'CREATE DATABASE {quote_table(test_db_name)}'))  # nosec B608 — quote_table 白名单校验
                logger.info(f"创建测试数据库: {test_db_name}")

            sync_engine.dispose()

            # 创建测试目录
            test_dir = self.test_results_dir / test_id
            test_dir.mkdir(parents=True, exist_ok=True)

            test_env = {
                'test_id': test_id,
                'test_db_name': test_db_name,
                'test_db_host': self.test_config['test_db_host'],
                'test_db_port': self.test_config['test_db_port'],
                'test_db_user': self.test_config['test_db_user'],
                'test_db_password': self.test_config['test_db_password'],
                'test_dir': str(test_dir),
                'created_at': datetime.now().isoformat()
            }

            logger.info(f"测试环境准备完成: {test_id}")
            return test_env

        except (SQLAlchemyError, OSError) as e:
            logger.error(f"准备测试环境失败: {e}")
            raise Exception(f"准备测试环境失败: {e!s}") from e

    async def _select_backup_for_test(self, backup_file: str | None = None) -> dict[str, Any] | None:
        """选择用于测试的备份文件"""
        try:
            ensure_backup_dir()

            if backup_file:
                # 使用指定的备份文件
                backup_path = BACKUP_DIR / backup_file
                if not backup_path.exists():
                    logger.warning(f"指定的备份文件不存在: {backup_file}")
                    return None

                backup_info = await self._get_backup_info(backup_path)
                if backup_info:
                    return backup_info
                return None

            # 选择最新的备份文件（含加密包；无密码时由 _get_backup_info 报出需密码）
            backup_files: list[Path] = []
            for ext in ['.zip', '.enc']:
                backup_files.extend(BACKUP_DIR.glob(f'*{ext}'))
            # 排除孤儿 .enc.meta（仅元数据，无对应加密包）
            backup_files = [f for f in backup_files if f.is_file() and not f.name.endswith('.enc.meta')]

            if not backup_files:
                logger.warning("没有找到备份文件")
                return None

            # 按时间从新到旧逐个尝试（2026-10-17 审计 P2-13：此前只取最新一个，
            # 最新文件损坏/无密码时整个演练恒失败，不回退次新的完好备份）
            for candidate in sorted(backup_files, key=lambda f: f.stat().st_mtime, reverse=True):
                backup_info = await self._get_backup_info(candidate)
                # 2026-10-18 OCR 评审：_get_backup_info 对「ZIP 损坏 / 缺密码」仍返回
                # dict（integrity_check.passed=False），只看 truthy 会选中坏备份。
                if backup_info and backup_info.get('integrity_check', {}).get('passed', True):
                    logger.info(f"选择备份文件进行测试: {candidate.name}")
                    return backup_info
                logger.warning(f"备份文件损坏或无效，尝试更早的备份: {candidate.name}")

            logger.warning("没有可用的备份文件")
            return None

        except OSError as e:
            logger.error(f"选择备份文件失败: {e}")
            return None

    async def _get_backup_info(self, backup_path: Path) -> dict[str, Any] | None:
        """获取备份文件信息"""
        try:
            if not backup_path.exists() or not backup_path.is_file():
                return None

            # 检查文件大小
            file_size = backup_path.stat().st_size
            if file_size == 0:
                return None

            # 读取manifest信息
            backup_info = {
                'filename': backup_path.name,
                'path': str(backup_path),
                'size_bytes': file_size,
                'size_mb': round(file_size / (1024 ** 2), 2),
                'mtime': datetime.fromtimestamp(backup_path.stat().st_mtime).isoformat(),
                'is_incremental': 'incremental' in backup_path.name,
                'is_manual': backup_path.name.startswith('erp_backup_'),
                'is_auto': backup_path.name.startswith('erp_auto_'),
            }

            # 读取manifest
            try:
                readable = self._open_backup_content(backup_path)
                try:
                    with zipfile.ZipFile(readable, 'r') as zf:
                        if 'manifest.json' in zf.namelist():
                            manifest = json.loads(zf.read('manifest.json'))
                            backup_info.update({
                                'manifest': manifest,
                                'backup_type': manifest.get('type', 'unknown'),
                                'backup_version': manifest.get('version', 'unknown'),
                                'exported_at': manifest.get('exported_at'),
                                'exported_by': manifest.get('exported_by'),
                                'table_count': manifest.get('table_count', 0),
                                'total_rows': manifest.get('total_rows', 0),
                                'base_timestamp': manifest.get('base_timestamp'),
                            })
                            backup_info['integrity_check'] = self._check_backup_integrity(zf, manifest)
                        else:
                            backup_info['integrity_check'] = {'passed': False, 'error': '缺少manifest.json'}
                finally:
                    if readable != backup_path:
                        readable.unlink(missing_ok=True)
            except zipfile.BadZipFile:
                backup_info['integrity_check'] = {'passed': False, 'error': 'ZIP 文件损坏(或加密包未成功解密)'}
            except ValueError as e:
                backup_info['integrity_check'] = {'passed': False, 'error': str(e)}
            except (OSError, json.JSONDecodeError) as e:
                backup_info['integrity_check'] = {'passed': False, 'error': str(e)}

            return backup_info

        except OSError as e:
            logger.error(f"获取备份信息失败 {backup_path.name}: {e}")
            return None

    def _open_backup_content(self, backup_path: Path) -> Path:
        """返回可读取的明文 ZIP 路径；加密备份(.enc/.zip.enc)先解密。

        - 明文 ZIP：原样返回。
        - 加密包：需 BACKUP_TEST_PASSWORD，解密后写入临时文件返回；
          未提供密码时抛明确的 KeyboardInterrupt 之外的 ValueError，供上层报「需密码」。
        """
        name = backup_path.name
        if not (name.endswith('.enc') or '.enc' in name):
            return backup_path
        try:
            from fastapi_app.core.backup_encryption import decrypt_backup_auto
            password = self.test_config.get('test_password', '')
            if not password:
                raise ValueError(f'备份 {name} 已加密，但未配置 BACKUP_TEST_PASSWORD，无法解密还原')
            encrypted_bytes = backup_path.read_bytes()
            # 2026-10-17 审计 AUD-06：auto 版本兼容 meta 前缀（旧 /save 格式），
            # 与恢复主链路同口径；decrypt_backup 只认裸信封会误报密码错误。
            plain_bytes, _meta = decrypt_backup_auto(encrypted_bytes, password)
            with tempfile.NamedTemporaryFile(
                prefix='dr_decrypt_', suffix='.zip', delete=False
            ) as tmp_file:
                tmp_file.write(plain_bytes)
            return Path(tmp_file.name)
        except ValueError:
            raise
        except Exception as e:  # defensive: 解密失败给出明确原因
            raise ValueError(f'解密备份 {name} 失败，请核对密码: {e}') from e

    def _check_backup_integrity(self, zip_file: zipfile.ZipFile, manifest: dict[str, Any]) -> dict[str, Any]:  # log-context: internal helper 无请求上下文
        """检查备份完整性"""
        try:
            # 检查必要的文件（数据库可以是 dump.sql.gz 或 dump.json）
            required_files = ['manifest.json']
            missing_files = []
            for req_file in required_files:
                if req_file not in zip_file.namelist():
                    missing_files.append(req_file)

            # 检查数据库文件（至少需要一种格式）
            has_db = ('database/dump.sql.gz' in zip_file.namelist() or
                      'database/dump.json' in zip_file.namelist())
            if not has_db:
                missing_files.append('database/dump.sql.gz or database/dump.json')

            if missing_files:
                return {
                    'passed': False,
                    'error': f'缺少必要文件: {", ".join(missing_files)}'
                }

            # 检查checksums
            checksums = manifest.get('checksums', {})
            failed_checks = []

            for file_path, expected_hash in checksums.items():
                if file_path in zip_file.namelist():
                    import hashlib
                    file_data = zip_file.read(file_path)
                    actual_hash = hashlib.sha256(file_data).hexdigest()

                    if actual_hash != expected_hash:
                        failed_checks.append(f'{file_path}: SHA256不匹配')
                else:
                    failed_checks.append(f'{file_path}: 文件缺失')

            if failed_checks:
                return {
                    'passed': False,
                    'error': f'完整性检查失败: {"; ".join(failed_checks)}'
                }

            return {
                'passed': True,
                'message': '备份文件完整性检查通过'
            }

        except (OSError, ValueError, KeyError) as e:
            return {
                'passed': False,
                'error': f'完整性检查异常: {e!s}'
            }

    async def _execute_recovery_test(self,
                                   test_id: str,
                                   test_env: dict[str, Any],
                                   backup_info: dict[str, Any]) -> dict[str, Any]:
        """执行恢复测试"""
        recovery_start_time = datetime.now()

        try:
            backup_path = Path(backup_info['path'])

            # 提取备份文件（加密包先解密）
            with tempfile.TemporaryDirectory() as temp_dir:
                temp_path = Path(temp_dir)
                readable = self._open_backup_content(backup_path)
                try:
                    with zipfile.ZipFile(readable, 'r') as zf:
                        # zip-slip 防护：拒绝绝对路径或「..」逃逸出临时目录的成员
                        for member in zf.namelist():
                            member_path = (temp_path / member).resolve()
                            if not member_path.is_relative_to(temp_path.resolve()):
                                raise ValueError(f'备份包含非法路径成员（zip-slip），拒绝解包: {member}')
                        zf.extractall(temp_path)
                finally:
                    if readable != backup_path:
                        readable.unlink(missing_ok=True)

                # 读取manifest
                manifest_path = temp_path / 'manifest.json'
                with open(manifest_path, encoding='utf-8') as f:
                    manifest = json.load(f)

                # 读取数据（支持 dump.json 和 dump.sql.gz 两种格式）
                backup_data: dict[str, Any] = {'tables': {}}
                data_path_json = temp_path / 'database' / 'dump.json'
                data_path_sql_gz = temp_path / 'database' / 'dump.sql.gz'

                if data_path_json.exists():
                    with open(data_path_json, encoding='utf-8') as f:
                        backup_data = json.load(f)
                elif data_path_sql_gz.exists():
                    # SQL dump 格式，无法直接解析为 JSON，记录基本信息
                    import gzip as gzip_mod
                    with gzip_mod.open(data_path_sql_gz, 'rt', encoding='utf-8') as f:
                        sql_content = f.read()
                    backup_data = {
                        'format': 'sql',
                        'sql_size': len(sql_content),
                        'tables': manifest.get('tables', {})
                    }
                else:
                    logger.warning("备份文件中未找到数据库导出数据")

                # 连接到测试数据库
                test_db_url = (
                    f"postgresql+asyncpg://{test_env['test_db_user']}:"  # sql-safe: escape_like/绑定参数/常量片段
                    f"{test_env['test_db_password']}@{test_env['test_db_host']}:"
                    f"{test_env['test_db_port']}/{test_env['test_db_name']}"
                )

                test_engine = create_async_engine(test_db_url, poolclass=NullPool)

                if data_path_sql_gz.exists():
                    # F5: SQL 物理备份走 psql 真实导入（与生产还原同参数）
                    import_result = await self._psql_import(test_env, data_path_sql_gz)
                    import_result['format'] = 'sql'
                    if not import_result.get('success'):
                        # 导入失败即整体失败，跳过后续验证（测试库无有效数据）
                        return {
                            'success': False,
                            'test_id': test_id,
                            'error': f"SQL 导入失败: {import_result.get('error', 'unknown')}",
                            'recovery_duration_seconds': round((datetime.now() - recovery_start_time).total_seconds(), 2)
                        }
                else:
                    from sqlalchemy.ext.asyncio import AsyncSession
                    async with test_engine.begin() as conn:
                        await self._create_test_schema(conn, backup_data)
                    async with AsyncSession(test_engine, expire_on_commit=False) as session:
                        import_result = await self._import_test_data(session, backup_data)
                    import_result['format'] = 'json'

                await test_engine.dispose()

                recovery_duration = (datetime.now() - recovery_start_time).total_seconds()

                result = {
                    'success': True,
                    'test_id': test_id,
                    'backup_file': backup_info['filename'],
                    'backup_type': backup_info.get('backup_type', 'unknown'),
                    'table_count': backup_info.get('table_count', 0),
                    'total_rows': backup_info.get('total_rows', 0),
                    'imported_rows': import_result.get('imported_rows', 0),
                    'failed_rows': import_result.get('failed_rows', 0),
                    'recovery_duration_seconds': round(recovery_duration, 2),
                    'start_time': recovery_start_time.isoformat(),
                    'end_time': datetime.now().isoformat(),
                    'details': import_result.get('details', {})
                }

                logger.info(f"恢复测试执行成功: {test_id}, 导入 {result['imported_rows']} 行数据")
                return result

        except (OSError, ValueError, SQLAlchemyError) as e:
            logger.error(f"恢复测试执行失败 {test_id}: {e}")
            return {
                'success': False,
                'test_id': test_id,
                'error': str(e),
                'recovery_duration_seconds': round((datetime.now() - recovery_start_time).total_seconds(), 2)
            }

    async def _psql_import(self, test_env: dict[str, Any], sql_gz_path: Path) -> dict[str, Any]:
        """把 dump.sql.gz 通过 psql 导入测试数据库（B5 修复）。

        与生产还原同参数：--single-transaction + ON_ERROR_STOP=1。
        返回 {'success', 'imported_rows', 'error'}，异常转为失败结果而非向上抛。
        """
        import gzip as gzip_mod
        import os
        import subprocess

        from fastapi_app.services.backup.dump import resolve_pg_tool

        try:
            with gzip_mod.open(sql_gz_path, 'rb') as f:
                dump_sql = f.read()

            env = os.environ.copy()
            env['PGPASSWORD'] = test_env['test_db_password']
            psql_args = [
                resolve_pg_tool('psql'),
                '-h', test_env['test_db_host'],
                '-p', str(test_env['test_db_port']),
                '-U', test_env['test_db_user'],
                '-d', test_env['test_db_name'],
                '--single-transaction',
                '-v', 'ON_ERROR_STOP=1',
            ]
            proc = subprocess.run(  # 参数为固定白名单列表
                psql_args, input=dump_sql,
                capture_output=True,  # 等价于 stdout=PIPE + stderr=PIPE
                env=env, timeout=600,
            )
            if proc.returncode != 0:
                stderr = (proc.stderr or b'').decode(errors='replace')[:500]
                logger.error(f"psql 演练导入失败 (rc={proc.returncode}): {stderr}")
                return {'success': False, 'imported_rows': 0, 'error': f'psql rc={proc.returncode}: {stderr}'}
            # psql 不返回行计数，用语句数近似（-q 模式无逐行统计）
            return {'success': True, 'imported_rows': -1, 'details': {'note': 'sql 格式不统计行数'}}
        except (TimeoutError, OSError, ValueError) as e:
            logger.error(f"psql 演练导入异常: {e}")
            return {'success': False, 'imported_rows': 0, 'error': str(e)}

    async def _create_test_schema(self, conn, backup_data: dict[str, Any]) -> None:
        """按 ORM 元数据在测试库创建真实业务 schema（F5：替换原 dummy 表 stub）。"""
        from fastapi_app.shared_models import Base
        await conn.run_sync(Base.metadata.create_all)

    async def _import_test_data(self, session, backup_data: dict[str, Any]) -> dict[str, Any]:
        """把 dump.json 导入测试库（F5：复用生产导入器 restore_legacy_json）。

        与"一键还原"走完全相同的数据写入路径（DELETE+upsert+批次降级），
        演练结论因此对生产还原路径具有直接代表性。
        """
        from fastapi_app.services.backup.json_backup import restore_legacy_json

        result = await restore_legacy_json(backup_data, session)
        await session.commit()  # manual-tx: 与生产 JsonRestoreStrategy 一致，导入后显式提交
        errors = result.get('errors') or []
        return {
            'success': not errors,
            'imported_rows': result.get('total_inserted', 0),
            'failed_rows': len(errors),
            'details': {'per_table': result.get('results', {}), 'errors': errors[:10]},
        }

    # _validate_recovery 及四个 _validate_* 子方法已于 2026-10-15 迁至
    # drill_validator.DrillValidator（纯搬移），调用点见 perform_recovery_test。

    async def _cleanup_test_environment(self, test_env: dict[str, Any]) -> dict[str, Any]:
        """清理测试环境"""
        try:
            if not self.test_config['cleanup_test_db']:
                return {
                    'cleaned': False,
                    'message': '测试数据库清理已禁用',
                    'test_db_name': test_env['test_db_name']
                }

            # 删除测试数据库
            import os

            from sqlalchemy import create_engine

            db_host = os.environ.get('DB_HOST', 'localhost')
            db_port = os.environ.get('DB_PORT', '5432')
            db_user = os.environ.get('DB_USER', 'postgres')
            db_password = os.environ.get('DB_PASSWORD', '')

            sync_engine = create_engine(
                f"postgresql+psycopg://{db_user}:{db_password}@{db_host}:{db_port}/postgres",  # sql-safe: escape_like/绑定参数/常量片段
                poolclass=NullPool
            )

            # DROP DATABASE 属于 DDL，不能在事务块中执行，使用 AUTOCOMMIT 模式
            with sync_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
                # 断开其他连接（参数化查询防止注入）
                conn.execute(
                    text("""
                        SELECT pg_terminate_backend(pid)
                        FROM pg_stat_activity
                        WHERE datname = :dbname
                        AND pid <> pg_backend_pid()
                    """),
                    {'dbname': test_env['test_db_name']}
                )

                # 删除数据库（使用 quote_table 白名单校验防止注入）
                conn.execute(text(f'DROP DATABASE IF EXISTS {quote_table(test_env["test_db_name"])}'))  # nosec B608 — quote_table 白名单校验

            sync_engine.dispose()

            # 清理测试目录
            test_dir = Path(test_env['test_dir'])
            if test_dir.exists():
                shutil.rmtree(test_dir)

            return {
                'cleaned': True,
                'message': '测试环境清理完成',
                'test_db_name': test_env['test_db_name'],
                'test_dir': test_env['test_dir']
            }

        except (SQLAlchemyError, OSError) as e:
            logger.error(f"清理测试环境失败: {e}")
            return {
                'cleaned': False,
                'error': str(e),
                'test_db_name': test_env.get('test_db_name', 'unknown'),
                'test_dir': test_env.get('test_dir', 'unknown')
            }

    async def _generate_test_report(self,
                                  test_id: str,
                                  start_time: datetime,
                                  backup_info: dict[str, Any],
                                  recovery_result: dict[str, Any],
                                  validation_result: dict[str, Any],
                                  cleanup_result: dict[str, Any]) -> dict[str, Any]:
        """生成测试报告"""
        try:
            end_time = datetime.now()
            duration_seconds = (end_time - start_time).total_seconds()

            # 计算总体结果
            recovery_success = recovery_result.get('success', False)
            validation_success = validation_result.get('success', False)
            overall_success = recovery_success and validation_success

            # 生成报告
            report = {
                'test_id': test_id,
                'start_time': start_time.isoformat(),
                'end_time': end_time.isoformat(),
                'duration_seconds': round(duration_seconds, 2),
                'overall_success': overall_success,
                'backup_info': {
                    'filename': backup_info.get('filename'),
                    'size_mb': backup_info.get('size_mb'),
                    'backup_type': backup_info.get('backup_type'),
                    'table_count': backup_info.get('table_count'),
                    'total_rows': backup_info.get('total_rows'),
                    'integrity_check': backup_info.get('integrity_check', {})
                },
                'recovery_result': recovery_result,
                'validation_result': validation_result,
                'cleanup_result': cleanup_result,
                'summary': {
                    'recovery_success': recovery_success,
                    'validation_success': validation_success,
                    'cleanup_success': cleanup_result.get('cleaned', False),
                    'imported_rows': recovery_result.get('imported_rows', 0),
                    'failed_rows': recovery_result.get('failed_rows', 0),
                    'validation_passed': validation_result.get('all_passed', False),
                    'total_duration_seconds': round(duration_seconds, 2)
                },
                'recommendations': self._generate_test_recommendations(
                    recovery_result, validation_result, cleanup_result
                )
            }

            return report

        except Exception as e:  # defensive: report generation must return error payload gracefully
            logger.error(f"生成测试报告失败: {e}")
            return {
                'test_id': test_id,
                'error': str(e),
                'overall_success': False,
                'message': '生成测试报告失败'
            }

    def _generate_test_recommendations(self,
                                     recovery_result: dict[str, Any],
                                     validation_result: dict[str, Any],
                                     cleanup_result: dict[str, Any]) -> list[str]:
        """生成测试建议"""
        recommendations = []

        # 恢复结果建议
        if not recovery_result.get('success', False):
            recommendations.append("恢复过程失败，建议检查备份文件完整性和数据库连接")

        failed_rows = recovery_result.get('failed_rows', 0)
        if failed_rows > 0:
            recommendations.append(f"恢复过程中有 {failed_rows} 行数据导入失败，建议检查数据完整性")

        # 验证结果建议
        if not validation_result.get('success', False):
            recommendations.append("数据验证失败，建议检查恢复数据的完整性和一致性")

        validation_details = validation_result.get('results', {})
        for validation_type, result in validation_details.items():
            if not result.get('passed', False):
                recommendations.append(f"{validation_type.replace('_', ' ').title()} 验证失败")

        # 清理结果建议
        if not cleanup_result.get('cleaned', False):
            recommendations.append("测试环境清理失败，建议手动清理测试数据库")

        # 性能建议
        performance_result = validation_details.get('performance_validation', {})
        if performance_result.get('passed', False):
            max_duration = performance_result.get('max_duration_ms', 0)
            if max_duration > 1000:
                recommendations.append(f"查询性能较慢 (最大 {max_duration}ms)，建议优化数据库配置")

        # 如果没有问题，添加正面反馈
        if not recommendations:
            recommendations.append("灾难恢复测试通过，备份文件可正常恢复")

        return recommendations

    async def _save_test_result(self, test_report: dict[str, Any]) -> None:
        """保存测试结果"""
        try:
            ensure_backup_dir()
            test_results_dir = self.test_results_dir
            test_results_dir.mkdir(parents=True, exist_ok=True)

            test_id = test_report.get('test_id', 'unknown')
            report_file = test_results_dir / f'recovery_test_{test_id}.json'

            with open(report_file, 'w', encoding='utf-8') as f:
                json.dump(test_report, f, ensure_ascii=False, indent=2)

            logger.info(f"恢复测试报告已保存: {report_file}")

            # 清理旧报告
            await self._cleanup_old_reports(test_results_dir)

        except OSError as e:
            logger.error(f"保存测试结果失败: {e}")

    async def _cleanup_old_reports(self, reports_dir: Path) -> None:
        """清理旧的测试报告"""
        try:
            retention_days = self.test_config['test_report_retention_days']
            cutoff_date = datetime.now() - timedelta(days=retention_days)

            report_files = list(reports_dir.glob('recovery_test_*.json'))
            deleted_count = 0

            for report_file in report_files:
                try:
                    # 从文件名解析日期
                    filename = report_file.stem
                    date_str = filename.replace('recovery_test_', '')
                    file_date = datetime.strptime(date_str[:15], '%Y%m%d_%H%M%S')

                    if file_date < cutoff_date:
                        report_file.unlink()
                        deleted_count += 1

                except (ValueError, IndexError):
                    # 如果无法解析日期，使用文件修改时间
                    file_mtime = datetime.fromtimestamp(report_file.stat().st_mtime)
                    if file_mtime < cutoff_date:
                        report_file.unlink()
                        deleted_count += 1

            if deleted_count > 0:
                logger.info(f"清理了 {deleted_count} 个旧的测试报告")

        except OSError as e:
            logger.error(f"清理测试报告失败: {e}")

    async def _send_test_notification(self, test_report: dict[str, Any]) -> None:
        """发送测试通知"""
        try:
            overall_success = test_report.get('overall_success', False)
            test_id = test_report.get('test_id', 'unknown')
            duration_seconds = test_report.get('duration_seconds', 0)

            if overall_success and self.test_config['notify_on_test_success']:
                message = (
                    f"灾难恢复测试成功\n"
                    f"测试ID: {test_id}\n"
                    f"耗时: {duration_seconds:.2f}秒\n"
                    f"备份文件: {test_report.get('backup_info', {}).get('filename', 'unknown')}\n"
                    f"恢复行数: {test_report.get('summary', {}).get('imported_rows', 0)}\n"
                    f"验证结果: 通过"
                )

                severity = 'info'

            elif not overall_success and self.test_config['notify_on_test_failure']:
                message = (
                    f"灾难恢复测试失败\n"
                    f"测试ID: {test_id}\n"
                    f"耗时: {duration_seconds:.2f}秒\n"
                    f"错误: {test_report.get('error', '未知错误')}\n"
                    f"建议检查备份文件和恢复流程"
                )

                severity = 'error'
            else:
                return  # 不发送通知

            await alert_service.send_alert(
                task_name='disaster_recovery_test',
                error=message,
                task_type='recovery_test',
                severity=severity,
                additional_info=test_report
            )

        except Exception as e:  # defensive: test notification failure must not propagate
            logger.error(f"发送测试通知失败: {e}")

    async def get_test_history(self, days: int = 30) -> list[dict[str, Any]]:
        """获取测试历史记录（2026-10-15 拆至 RecoveryTestHistoryService，此处保留薄委托）"""
        return await RecoveryTestHistoryService(self.test_results_dir).get_test_history(days)

    async def get_test_summary(self, days: int = 30) -> dict[str, Any]:
        """获取测试摘要（2026-10-15 拆至 RecoveryTestHistoryService，此处保留薄委托）"""
        return await RecoveryTestHistoryService(self.test_results_dir).get_test_summary(days)


# 全局灾难恢复测试服务实例
recovery_test_service = DisasterRecoveryTestService()
