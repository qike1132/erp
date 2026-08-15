"""高层编排 + 锁管理。"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from ._constants import (
    BACKUP_ENCRYPTION_ENABLED,
    BACKUP_ENCRYPTION_FALLBACK_TO_GENERATED,
    BACKUP_ENCRYPTION_KEY,
    BACKUP_ENCRYPTION_PASSWORD,
    BACKUP_FORMAT_VERSION,
    BACKUP_LOCK_ID,
    BACKUP_OPERATION_TIMEOUT,
    CONFIG_DIR,
    MEILI_HOST,
    MEILI_MASTER_KEY,
    PRE_RESTORE_DIR,
    REDIS_DUMP,
    UPLOADS_DIR,
    _backup_in_progress,
)
from .crypto import get_backup_encryption_password, sha256_file
from .dump import run_pg_dump
from .exceptions import (
    BackupError,
    BackupLockError,
    DatabaseSnapshotError,
)
from .filestore import should_exclude_file
from .json_backup import execute_legacy_backup_to_bytes
from .records import cleanup_pre_restore_backups, ensure_pre_restore_dir
from .snapshot import get_postgres_snapshot
from .verify import get_checksum_tables, quote_table

logger = logging.getLogger(__name__)


async def acquire_backup_lock(db: AsyncSession) -> bool:
    """获取备份操作的数据库级 advisory lock。"""
    try:
        result = await db.execute(
            text('SELECT pg_try_advisory_lock(:lock_id)'),
            {'lock_id': BACKUP_LOCK_ID},
        )
        return bool(result.scalar())
    except (SQLAlchemyError, OSError) as e:
        logger.warning('获取备份 advisory_lock 失败: %s', e)
        return False


async def release_backup_lock(db: AsyncSession) -> None:
    """释放备份 advisory lock。失败仅记录日志，不抛出异常。"""
    try:
        await db.execute(
            text('SELECT pg_advisory_unlock(:lock_id)'),
            {'lock_id': BACKUP_LOCK_ID},
        )
    except (SQLAlchemyError, OSError) as e:
        logger.warning('释放备份 advisory_lock 失败: %s', e)


async def create_full_backup(
    db: AsyncSession,
    user,
    remark: str,
    encrypt_password: str | bytearray | None = None,
    use_snapshot: bool = True,
    encrypt: bool | None = None,
) -> tuple[bytes, dict]:
    """执行全量备份并返回 (zip_bytes, manifest_dict)。"""
    if _backup_in_progress.locked():
        raise BackupLockError('已有备份任务正在执行中，请稍后重试')

    db_lock_acquired = await acquire_backup_lock(db)
    if not db_lock_acquired:
        raise BackupLockError('其他进程正在执行备份，请稍后重试')

    async with _backup_in_progress:
        try:
            return await asyncio.wait_for(
                _do_create_full_backup(db, user, remark, encrypt_password, use_snapshot, encrypt),
                timeout=BACKUP_OPERATION_TIMEOUT,
            )
        except asyncio.TimeoutError as e:
            logger.error('备份操作超时（%s秒）', BACKUP_OPERATION_TIMEOUT)
            raise BackupError(f'备份超时（>{BACKUP_OPERATION_TIMEOUT}s），已强制取消') from e
        finally:
            await release_backup_lock(db)

async def _do_create_full_backup(
    db: AsyncSession,
    user,
    remark: str,
    encrypt_password: str | bytearray | None,
    use_snapshot: bool,
    encrypt: bool | None = None,
) -> tuple[bytes, dict]:
    """create_full_backup 的实际实现，由锁和超时控制包裹。"""
    snapshot_id = None
    if use_snapshot:
        try:
            snapshot_id = await get_postgres_snapshot(db)
            logger.info(f"获取数据库快照成功: {snapshot_id}")
        except DatabaseSnapshotError as e:
            logger.warning(f"无法获取数据库快照，继续无快照备份: {e}")

    with tempfile.TemporaryDirectory(prefix='erp_backup_') as tmpdir:
        tmpdir_path = Path(tmpdir)
        dump_path = tmpdir_path / 'database' / 'dump.sql.gz'
        dump_info: dict = {}
        pg_dump_available = False
        try:
            dump_info = await run_pg_dump(dump_path, snapshot_id)
            pg_dump_available = True
        except (TimeoutError, OSError, RuntimeError) as e:
            logger.warning(f'pg_dump 不可用，使用 JSON 格式备份数据库: {e}')
            json_path = tmpdir_path / 'database'
            json_path.mkdir(parents=True, exist_ok=True)
            json_bytes = await execute_legacy_backup_to_bytes(user, remark, db)
            json_path_file = json_path / 'dump.json'
            json_path_file.write_bytes(json_bytes)
            dump_info = {
                'pg_version': '', 'db_name': os.getenv('DB_NAME', 'erp_system'),
                'dump_size': len(json_bytes), 'duration_seconds': 0, 'format': 'json',
            }

        from fastapi_app.shared_models import Base

        table_names = [str(t.name) for t in Base.metadata.sorted_tables]

        existing_result = await db.execute(
            text("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")
        )
        existing_tables = {r[0] for r in existing_result.fetchall()}

        async def _count_table(tname: str) -> tuple[str, int]:
            if tname not in existing_tables:
                return tname, -1
            nested = await db.begin_nested()
            try:
                qtname = quote_table(tname)
                result = await db.execute(text(f'SELECT COUNT(*) FROM {qtname}'))  # nosec B608 — qtname 经 quote_table 白名单校验
                await nested.commit()
                return tname, result.scalar() or 0
            except (OSError, ValueError, SQLAlchemyError):
                await nested.rollback()
                return tname, -1

        count_results = []
        for n in table_names:
            count_results.append(await _count_table(n))
        table_stats = dict(count_results)

        checksums = {}
        db_dump_name = 'database/dump.sql.gz' if pg_dump_available else 'database/dump.json'
        db_dump_file = dump_path if pg_dump_available else tmpdir_path / 'database' / 'dump.json'
        if db_dump_file.is_file():
            checksums[db_dump_name] = sha256_file(db_dump_file)  # REV-14

        fingerprints = {}
        for table in Base.metadata.sorted_tables:
            tname = str(table.name)
            if tname not in get_checksum_tables():
                continue
            try:
                qtname = quote_table(tname)  # REV-08
                pk_col = [c.name for c in table.primary_key.columns]
                order_col = pk_col[0] if pk_col else 'id'
                cols_result = await db.execute(
                    text('SELECT column_name FROM information_schema.columns WHERE table_name = :tname ORDER BY ordinal_position'),
                    {'tname': tname}
                )
                col_names = [r[0] for r in cols_result.fetchall()]
                agg_expr = " || '|' || ".join(f'''COALESCE("{c}"::text, '')''' for c in col_names)
                fp_result = await db.execute(text(
                    f'''SELECT MD5(STRING_AGG({agg_expr}, ',' ORDER BY "{order_col}")) FROM {qtname}'''  # nosec B608 — qtname 经 quote_table 白名单校验
                ))
                fingerprints[tname] = fp_result.scalar() or ''
            except (SQLAlchemyError, ValueError, OSError) as e:
                logger.warning(f'计算表 {tname} 指纹失败: {e}')
                fingerprints[tname] = ''

        manifest = {
            'version': BACKUP_FORMAT_VERSION, 'type': 'full', 'app_version': '2.0',
            'pg_version': dump_info.get('pg_version', ''),
            'db_name': dump_info.get('db_name', ''),
            'exported_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'exported_by': user.username if hasattr(user, 'username') else str(user.id),
            'remark': remark,
            'table_count': len(table_stats),
            'total_rows': sum(v for v in table_stats.values() if v >= 0),
            'dump_size': dump_info.get('dump_size', 0),
            'dump_duration_seconds': dump_info.get('duration_seconds', 0),
            'snapshot_id': dump_info.get('snapshot_id'),
            'tables': {k: {'rows': v} for k, v in table_stats.items()},
            'includes': {}, 'checksums': checksums, 'fingerprints': fingerprints,
        }

        zip_path = tmpdir_path / 'backup.zip'
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED, compresslevel=3) as zf:
            if pg_dump_available and dump_path.is_file():
                zf.write(dump_path, 'database/dump.sql.gz')
            elif (tmpdir_path / 'database' / 'dump.json').is_file():
                zf.write(tmpdir_path / 'database' / 'dump.json', 'database/dump.json')

            if UPLOADS_DIR.is_dir():
                file_count = 0
                for fp in sorted(UPLOADS_DIR.rglob('*')):
                    if fp.is_file():
                        arcname = f'filestore/{fp.relative_to(UPLOADS_DIR)}'
                        zf.write(fp, arcname)
                        file_count += 1
                manifest['includes']['filestore_count'] = file_count

            config_files_added = []
            config_files_excluded = []
            config_files_to_check = [
                ('jwt/private.pem', 'jwt/private.pem'),
                ('jwt/public.pem', 'jwt/public.pem'),
                ('redis.production.conf', 'redis.production.conf'),
                ('nginx.conf', 'nginx.conf'),
                ('.env.production', '.env.production'),
            ]
            for file_name, relative_path in config_files_to_check:
                file_path = CONFIG_DIR / file_name
                if file_path.is_file():
                    if should_exclude_file(file_path, relative_path):
                        config_files_excluded.append(relative_path)
                        logger.info(f"排除配置文件: {relative_path}")
                    else:
                        zf.write(file_path, f'config/{relative_path}')
                        config_files_added.append(relative_path)
            manifest['includes']['config_files'] = config_files_added
            if config_files_excluded:
                manifest['includes']['config_files_excluded'] = config_files_excluded

            if REDIS_DUMP.is_file():
                zf.write(REDIS_DUMP, 'redis/dump.rdb')
                manifest['includes']['redis_rdb'] = True

            try:
                import httpx
                async with httpx.AsyncClient() as meili_client:
                    meili_indexes_resp = await meili_client.get(
                        f'{MEILI_HOST}/indexes',
                        headers={'Authorization': f'Bearer {MEILI_MASTER_KEY}'}, timeout=10
                    )
                    if meili_indexes_resp.status_code == 200:
                        meili_indexes_data = meili_indexes_resp.json()
                        meili_index_names = [idx['uid'] for idx in meili_indexes_data.get('results', [])]
                        meili_export = {}
                        for idx_name in meili_index_names:
                            docs_resp = await meili_client.get(
                                f'{MEILI_HOST}/indexes/{idx_name}/documents',
                                headers={'Authorization': f'Bearer {MEILI_MASTER_KEY}'},
                                params={'limit': 100000}, timeout=60
                            )
                            if docs_resp.status_code == 200:
                                meili_export[idx_name] = docs_resp.json().get('results', [])
                            settings_resp = await meili_client.get(
                                f'{MEILI_HOST}/indexes/{idx_name}/settings',
                                headers={'Authorization': f'Bearer {MEILI_MASTER_KEY}'}, timeout=10
                            )
                            if settings_resp.status_code == 200:
                                meili_export[f'{idx_name}__settings'] = settings_resp.json()
                        if meili_export:
                            meili_bytes = json.dumps(meili_export, ensure_ascii=False).encode('utf-8')
                            zf.writestr('meilisearch/dump.json', meili_bytes)
                            manifest['includes']['meilisearch_indexes'] = meili_index_names
                            manifest['includes']['meilisearch_doc_count'] = sum(
                                len(v) for k, v in meili_export.items() if not k.endswith('__settings')
                            )
            except Exception as e:
                logger.warning('MeiliSearch 索引导出失败（可忽略）: %s', e)

            manifest_bytes = json.dumps(manifest, ensure_ascii=False, indent=2).encode('utf-8')
            zf.writestr('manifest.json', manifest_bytes)

        zip_bytes = zip_path.read_bytes()
        manifest['zip_size'] = len(zip_bytes)

        if encrypt is False:
            effective_encryption_password = None
        else:
            effective_encryption_password = encrypt_password or get_backup_encryption_password()
        if effective_encryption_password:
            from fastapi_app.core.backup_encryption import encrypt_backup
            try:
                encrypted_bytes, meta_dict = encrypt_backup(zip_bytes, effective_encryption_password)
                manifest['encrypted'] = True
                manifest['encryption'] = meta_dict
                if encrypt_password:
                    logger.info("使用用户提供的密码进行备份加密")
                elif BACKUP_ENCRYPTION_PASSWORD or BACKUP_ENCRYPTION_KEY:
                    logger.info("使用环境变量配置的密钥进行备份加密")
                else:
                    logger.warning(f"使用生成的随机密钥进行备份加密，密钥已记录在日志中")
                return encrypted_bytes, manifest
            except Exception as e:
                logger.error(f"备份加密失败: {e}")
                if BACKUP_ENCRYPTION_ENABLED and not BACKUP_ENCRYPTION_FALLBACK_TO_GENERATED:
                    raise BackupError(f"备份加密失败且不允许回退到未加密备份: {e}") from e
                logger.warning("加密失败，返回未加密的备份文件")

    return zip_bytes, manifest

async def create_full_backup_to_file(
    db: AsyncSession,
    user,
    remark: str,
    output_path: Path | None = None,
    use_snapshot: bool = True,
    encrypt_password: str | bytearray | None = None,
    encrypt: bool | None = None,
) -> tuple[Path, dict]:
    """执行全量备份并保存到文件，返回 (file_path, manifest_dict)。"""
    zip_bytes, manifest = await create_full_backup(
        db, user, remark, encrypt_password, use_snapshot, encrypt=encrypt
    )

    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(zip_bytes)
        return output_path, manifest
    else:
        fd, tmp_file = tempfile.mkstemp(suffix='.zip', prefix='erp_backup_')
        os.close(fd)
        Path(tmp_file).write_bytes(zip_bytes)
        return Path(tmp_file), manifest


async def create_pre_restore_backup(db: AsyncSession) -> dict:
    """创建恢复前安全备份"""
    ensure_pre_restore_dir()
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f'pre_restore_{timestamp}.zip'
    filepath = PRE_RESTORE_DIR / filename
    try:
        from fastapi_app.shared_models import User as UserModel
        dummy_user = UserModel()
        dummy_user.username = 'system'
        dummy_user.id = 0
        zip_bytes, manifest = await create_full_backup(db, dummy_user, '恢复前自动安全备份')
        filepath.write_bytes(zip_bytes)
        cleanup_pre_restore_backups()
        return {'success': True, 'filename': filename, 'filepath': str(filepath), 'size': len(zip_bytes)}
    except Exception as e:
        logger.warning(f'创建恢复前安全备份失败（不阻塞恢复）: {e}')
        return {'success': False, 'error': str(e)}
