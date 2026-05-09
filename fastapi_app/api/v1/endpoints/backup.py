"""数据备份与恢复 API — 全量 ZIP 备份方案（v2.0）

备份包结构（类 Odoo ZIP 格式）：
  erp_backup_YYYYMMDD_HHMMSS.zip
  ├── manifest.json           # 元数据清单（版本、表数、行数、SHA256 校验和）
  ├── database/
  │   └── dump.sql.gz         # pg_dump 导出（gzip 压缩）
  ├── filestore/              # static/uploads/ 全量打包
  ├── config/                 # 关键配置文件（JWT密钥、.env、nginx等）
  └── redis/
      └── dump.rdb            # Redis 快照

向后兼容：仍支持 v1.0 JSON 格式的导入/导出。
"""
import asyncio
import gzip
import hashlib
import io
import json
import logging
import os
import shutil
import tempfile
import traceback
import zipfile
from datetime import date, datetime
from datetime import time as time_type
from decimal import Decimal
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import ARRAY, JSON, Boolean, Date, DateTime, Numeric, Time, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.database import get_async_db, get_async_db_context
from fastapi_app.core.deps import require_permission
from fastapi_app.shared_models import User

logger = logging.getLogger(__name__)
router = APIRouter()
BACKUP_DIR = Path(os.environ.get('BACKUP_DIR', 'backups/server'))
MAX_BACKUP_FILE_SIZE = 500 * 1024 * 1024
RESTORE_LOCK_ID = 20240426
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
UPLOADS_DIR = PROJECT_ROOT / 'static' / 'uploads'
CONFIG_DIR = PROJECT_ROOT / 'config'
ENV_FILE = PROJECT_ROOT / '.env.production'
REDIS_DUMP = PROJECT_ROOT / 'dump.rdb'
MEILI_HOST = os.environ.get('MEILI_HOST', 'http://localhost:7700')
MEILI_MASTER_KEY = os.environ.get('MEILI_MASTER_KEY', '')
BACKUP_FORMAT_VERSION = '2.0'
PRE_RESTORE_DIR = BACKUP_DIR / 'pre_restore'

def _ensure_backup_dir():
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)

def _ensure_pre_restore_dir():
    PRE_RESTORE_DIR.mkdir(parents=True, exist_ok=True)

_MAX_PRE_RESTORE_BACKUPS = 5

async def _create_pre_restore_backup(db: AsyncSession) -> dict:
    _ensure_pre_restore_dir()
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f'pre_restore_{timestamp}.zip'
    filepath = PRE_RESTORE_DIR / filename
    try:
        from fastapi_app.shared_models import User as UserModel
        dummy_user = UserModel()
        dummy_user.username = 'system'
        dummy_user.id = 0
        zip_bytes, manifest = await _execute_backup_to_zip(dummy_user, '恢复前自动安全备份', db)
        filepath.write_bytes(zip_bytes)
        _cleanup_pre_restore_backups()
        return {'success': True, 'filename': filename, 'filepath': str(filepath), 'size': len(zip_bytes)}
    except Exception as e:
        logger.warning(f'创建恢复前安全备份失败（不阻塞恢复）: {e}')
        return {'success': False, 'error': str(e)}

def _cleanup_pre_restore_backups():
    if not PRE_RESTORE_DIR.exists():
        return
    backups = sorted(
        [f for f in PRE_RESTORE_DIR.iterdir() if f.is_file() and f.name.startswith('pre_restore_') and f.name.endswith('.zip')],
        key=lambda f: f.name,
        reverse=True
    )
    for old_backup in backups[_MAX_PRE_RESTORE_BACKUPS:]:
        try:
            old_backup.unlink()
            logger.info(f'已清理旧安全备份: {old_backup.name}')
        except OSError as e:
            logger.warning(f'清理旧安全备份失败: {old_backup.name}: {e}')

_TIMESTAMP_CANDIDATES = ('updated_at', 'modified_at', 'created_at', 'deleted_at')

async def _find_timestamp_column(tname: str, db: AsyncSession) -> str | None:
    try:
        cols_result = await db.execute(text('SELECT column_name FROM information_schema.columns WHERE table_name = :tname ORDER BY ordinal_position'), {'tname': tname})
        col_names = [r[0] for r in cols_result.fetchall()]
        for candidate in _TIMESTAMP_CANDIDATES:
            if candidate in col_names and candidate in _TIMESTAMP_CANDIDATES:
                return candidate
    except (SQLAlchemyError, OSError, ValueError) as e:
        logger.warning(f'查询表 {tname} 列信息失败: {e}')
    return None

async def _query_table_rows(tname: str, db: AsyncSession, since: str | None = None) -> list[dict]:
    ts_col = await _find_timestamp_column(tname, db) if since else None
    if ts_col:
        result = await db.execute(text(f'SELECT * FROM "{tname}" WHERE "{ts_col}" >= :since'), {'since': since})
    else:
        result = await db.execute(text(f'SELECT * FROM "{tname}"'))
    rows = result.mappings().all()
    columns = list(result.keys())
    serialized_rows = []
    for row in rows:
        serialized_row = {}
        for col in columns:
            serialized_row[col] = _serialize_value(row[col])
        serialized_rows.append(serialized_row)
    return serialized_rows

async def _find_last_backup_timestamp() -> str | None:
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

def _sha256_bytes(data: bytes) -> str:
    """Compute SHA256 hex digest for bytes."""
    return hashlib.sha256(data).hexdigest()

def _sha256_file(filepath: Path) -> str | None:
    """Compute SHA256 hex digest for a file, return None if file missing."""
    if not filepath.is_file():
        return None
    h = hashlib.sha256()
    with open(filepath, 'rb') as f:
        for chunk in iter(lambda: f.read(65536), b''):
            h.update(chunk)
    return h.hexdigest()

async def _run_pg_dump(output_path: Path) -> dict:
    """Run pg_dump to export the database as compressed SQL (gzip).

    Returns a dict with: pg_version, db_name, dump_size, duration_seconds.
    """
    import time
    start = time.monotonic()
    db_host = os.getenv('DB_HOST', 'localhost')
    db_port = os.getenv('DB_PORT', '5432')
    db_user = os.getenv('DB_USER', 'erp_app')
    db_name = os.getenv('DB_NAME', 'erp_system')
    # SECURITY: validate database name contains only safe characters
    if not db_name.isidentifier():
        raise ValueError(f'Invalid database name: {db_name!r}')
    db_password = os.getenv('DB_PASSWORD', '')
    env = os.environ.copy()
    env['PGPASSWORD'] = db_password
    try:
        proc = await asyncio.create_subprocess_exec('pg_dump', '-h', db_host, '-p', db_port, '-U', db_user, '-d', db_name, '--no-owner', '--no-privileges', stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=env)
        gzip_proc = await asyncio.create_subprocess_exec('gzip', '-1', stdin=proc.stdout, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout, _ = await gzip_proc.communicate()
        await proc.wait()
        if proc.returncode != 0:
            stderr_data = await proc.stderr.read() if proc.stderr else b''
            raise RuntimeError(f"pg_dump failed (rc={proc.returncode}): {stderr_data.decode(errors='replace')}")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(stdout)
        duration = time.monotonic() - start
        return {'pg_version': await _get_pg_version(db_host, db_port, db_user, db_password, env), 'db_name': db_name, 'dump_size': len(stdout), 'duration_seconds': round(duration, 2)}
    except FileNotFoundError:
        raise RuntimeError('pg_dump 命令未找到，请确保 PostgreSQL 客户端工具已安装') from None
    except RuntimeError:
        raise
    except (TimeoutError, OSError, ValueError) as e:
        raise RuntimeError(f'pg_dump 执行失败: {e}') from e

async def _get_pg_version(host, port, user, password, env) -> str:
    """Get PostgreSQL version string."""
    try:
        proc = await asyncio.create_subprocess_exec('psql', '-h', host, '-p', port, '-U', user, '-d', os.getenv('DB_NAME', 'erp_system'), '-t', '-c', 'SELECT version();', stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=env)
        stdout, _ = await proc.communicate()
        if proc.returncode == 0:
            return stdout.decode(errors='replace').strip().split(',')[0]
    except (TimeoutError, OSError, ValueError) as e:
        logger.warning(f'获取 PG 版本失败: {e}')
    return 'unknown'

async def _execute_backup_to_zip(user: User, remark: str, db: AsyncSession) -> tuple[bytes, dict]:
    """Run full backup and return (zip_bytes, manifest_dict).

    Falls back to JSON database export if pg_dump is not available.
    """
    with tempfile.TemporaryDirectory(prefix='erp_backup_') as tmpdir:
        tmpdir_path = Path(tmpdir)
        dump_path = tmpdir_path / 'database' / 'dump.sql.gz'
        dump_info: dict = {}
        pg_dump_available = False
        try:
            dump_info = await _run_pg_dump(dump_path)
            pg_dump_available = True
        except (TimeoutError, OSError, RuntimeError) as e:
            logger.warning(f'pg_dump 不可用，使用 JSON 格式备份数据库: {e}')
            json_path = tmpdir_path / 'database'
            json_path.mkdir(parents=True, exist_ok=True)
            json_bytes = await _execute_legacy_backup_to_bytes(user, remark, db)
            json_path_file = json_path / 'dump.json'
            json_path_file.write_bytes(json_bytes)
            dump_info = {'pg_version': '', 'db_name': os.getenv('DB_NAME', 'erp_system'), 'dump_size': len(json_bytes), 'duration_seconds': 0, 'format': 'json'}
        from fastapi_app.shared_models import Base
        table_stats = {}
        for table in Base.metadata.sorted_tables:
            name = str(table.name)
            try:
                result = await db.execute(text(f'SELECT COUNT(*) FROM "{name}"'))  # nosec
                count = result.scalar()
                table_stats[name] = count
            except (OSError, ValueError, SQLAlchemyError):
                table_stats[name] = -1
        checksums = {}
        db_dump_name = 'database/dump.sql.gz' if pg_dump_available else 'database/dump.json'
        db_dump_file = dump_path if pg_dump_available else tmpdir_path / 'database' / 'dump.json'
        if db_dump_file.is_file():
            checksums[db_dump_name] = _sha256_file(db_dump_file)
        fingerprints = {}
        for table in Base.metadata.sorted_tables:
            tname = str(table.name)
            if tname not in _get_checksum_tables():
                continue
            try:
                pk_col = [c.name for c in table.primary_key.columns]
                order_col = pk_col[0] if pk_col else 'id'
                cols_result = await db.execute(text('SELECT column_name FROM information_schema.columns WHERE table_name = :tname ORDER BY ordinal_position'), {'tname': tname})
                col_names = [r[0] for r in cols_result.fetchall()]
                agg_expr = " || '|' || ".join(f'''COALESCE("{c}"::text, '')''' for c in col_names)
                fp_result = await db.execute(text(f'''SELECT MD5(STRING_AGG({agg_expr}, ',' ORDER BY "{order_col}")) FROM "{tname}"'''))  # nosec
                fingerprints[tname] = fp_result.scalar() or ''
            except (SQLAlchemyError, ValueError, OSError) as e:
                logger.warning(f'计算表 {tname} 指纹失败: {e}')
                fingerprints[tname] = ''
        manifest = {'version': BACKUP_FORMAT_VERSION, 'type': 'full', 'app_version': '2.0', 'pg_version': dump_info.get('pg_version', ''), 'db_name': dump_info.get('db_name', ''), 'exported_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'), 'exported_by': user.username if hasattr(user, 'username') else str(user.id), 'remark': remark, 'table_count': len(table_stats), 'total_rows': sum(v for v in table_stats.values() if v >= 0), 'dump_size': dump_info.get('dump_size', 0), 'dump_duration_seconds': dump_info.get('duration_seconds', 0), 'tables': {k: {'rows': v} for k, v in table_stats.items()}, 'includes': {}, 'checksums': checksums, 'fingerprints': fingerprints}
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
            for key_file in ['jwt/private.pem', 'jwt/public.pem']:
                key_path = CONFIG_DIR / key_file
                if key_path.is_file():
                    zf.write(key_path, f'config/{key_file}')
                    config_files_added.append(key_file)
            redis_conf = CONFIG_DIR / 'redis.production.conf'
            if redis_conf.is_file():
                zf.write(redis_conf, 'config/redis.production.conf')
                config_files_added.append('redis.production.conf')
            nginx_conf = CONFIG_DIR / 'nginx.conf'
            if nginx_conf.is_file():
                zf.write(nginx_conf, 'config/nginx.conf')
                config_files_added.append('nginx.conf')
            if ENV_FILE.is_file():
                zf.write(ENV_FILE, 'config/.env.production')
                config_files_added.append('.env.production')
            manifest['includes']['config_files'] = config_files_added
            if REDIS_DUMP.is_file():
                zf.write(REDIS_DUMP, 'redis/dump.rdb')
                manifest['includes']['redis_rdb'] = True
            try:
                import httpx
                meili_indexes_resp = httpx.get(f'{MEILI_HOST}/indexes', headers={'Authorization': f'Bearer {MEILI_MASTER_KEY}'}, timeout=10)
                if meili_indexes_resp.status_code == 200:
                    meili_indexes_data = meili_indexes_resp.json()
                    meili_index_names = [idx['uid'] for idx in meili_indexes_data.get('results', [])]
                    meili_export = {}
                    for idx_name in meili_index_names:
                        docs_resp = httpx.get(f'{MEILI_HOST}/indexes/{idx_name}/documents', headers={'Authorization': f'Bearer {MEILI_MASTER_KEY}'}, params={'limit': 100000}, timeout=60)
                        if docs_resp.status_code == 200:
                            meili_export[idx_name] = docs_resp.json().get('results', [])
                        settings_resp = httpx.get(f'{MEILI_HOST}/indexes/{idx_name}/settings', headers={'Authorization': f'Bearer {MEILI_MASTER_KEY}'}, timeout=10)
                        if settings_resp.status_code == 200:
                            meili_export[f'{idx_name}__settings'] = settings_resp.json()
                    if meili_export:
                        meili_bytes = json.dumps(meili_export, ensure_ascii=False).encode('utf-8')
                        zf.writestr('meilisearch/dump.json', meili_bytes)
                        manifest['includes']['meilisearch_indexes'] = meili_index_names
                        manifest['includes']['meilisearch_doc_count'] = sum(len(v) for k, v in meili_export.items() if not k.endswith('__settings'))
            except Exception as e:
                logger.warning(f'MeiliSearch 索引导出失败（可忽略）: {e}')
            manifest_bytes = json.dumps(manifest, ensure_ascii=False, indent=2).encode('utf-8')
            zf.writestr('manifest.json', manifest_bytes)
        zip_bytes = zip_path.read_bytes()
        manifest['zip_size'] = len(zip_bytes)
        return (zip_bytes, manifest)

async def _dispose_and_reinit_pool():
    import fastapi_app.core.database as db_mod
    engine = db_mod._async_engine
    if engine is not None:
        try:
            await engine.dispose()
        except (RuntimeError, OSError) as e:
            logger.warning(f'释放引擎连接池异常（可忽略）: {e}')
    db_mod._async_engine = None
    db_mod._AsyncSessionLocal = None
    db_mod.async_engine = None
    # 同时重置只读副本引擎，避免恢复后查询走旧副本看不到数据
    read_engine = db_mod._read_engine
    if read_engine is not None:
        try:
            await read_engine.dispose()
        except (RuntimeError, OSError) as e:
            logger.warning(f'释放只读副本引擎异常（可忽略）: {e}')
    db_mod._read_engine = None
    db_mod._ReadSessionLocal = None
    try:
        db_mod._init_async_engine()
        db_mod._init_read_engine()
        logger.info('数据库连接池已重建')
    except Exception as e:
        logger.error(f'数据库连接池重建失败: {e}')
        raise RuntimeError(f'数据库连接池重建失败: {e}') from e

async def _restore_from_zip(zip_bytes: bytes, db: AsyncSession) -> dict:
    """Restore from a ZIP backup file."""
    try:
        zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except zipfile.BadZipFile:
        raise HTTPException(status_code=400, detail='无效的 ZIP 备份文件') from None
    if 'manifest.json' not in zf.namelist():
        raise HTTPException(status_code=400, detail='备份文件缺少 manifest.json')
    manifest = json.loads(zf.read('manifest.json'))
    results = {'version': manifest.get('version'), 'exported_at': manifest.get('exported_at'), 'exported_by': manifest.get('exported_by'), 'remark': manifest.get('remark', ''), 'database': {}, 'filestore': {}, 'config': {}, 'redis': {}, 'meilisearch': {}, 'errors': [], 'warnings': []}
    stored_checksums = manifest.get('checksums', {})
    for db_file in ('database/dump.sql.gz', 'database/dump.json'):
        if stored_checksums.get(db_file):
            actual = _sha256_bytes(zf.read(db_file))
            if actual != stored_checksums[db_file]:
                results['warnings'].append(f'{db_file} 校验和不匹配，备份文件可能已损坏')
    pre_restore_info = await _create_pre_restore_backup(db)
    results['pre_restore_backup'] = pre_restore_info
    lock_acquired = False
    try:
        lock_result = await db.execute(text('SELECT pg_try_advisory_lock(:lock_id)'), {'lock_id': RESTORE_LOCK_ID})
        if not lock_result.scalar():
            raise HTTPException(status_code=409, detail='另一个恢复操作正在执行中，请稍后重试')
        lock_acquired = True
    except HTTPException:
        raise
    except (RuntimeError, OSError):
        logger.warning('获取恢复锁失败，继续执行恢复操作')
    psql_restored = False
    psql_attempted = False
    try:
        if 'database/dump.sql.gz' in zf.namelist():
            psql_attempted = True
            db_result = await _restore_database_via_psql(zf, db)
            results['database'] = db_result
            if db_result.get('status') == 'error':
                raise RuntimeError(f"数据库恢复失败: {db_result.get('error') or db_result.get('message', '未知错误')}")
            if db_result.get('status') in ('ok', 'partial'):
                psql_restored = True
        elif 'database/dump.json' in zf.namelist():
            db_result = await _restore_database_from_json(zf, db)
            results['database'] = db_result
            if db_result.get('status') == 'error':
                raise RuntimeError(f"数据库恢复失败: {db_result.get('error') or db_result.get('message', '未知错误')}")
        else:
            results['warnings'].append('备份文件中无数据库导出')
        if any(n.startswith('filestore/') for n in zf.namelist()):
            fs_result = _restore_filestore(zf)
            results['filestore'] = fs_result
        else:
            results['warnings'].append('备份文件中无附件数据')
        if any(n.startswith('config/') for n in zf.namelist()):
            cfg_result = _restore_config(zf)
            results['config'] = cfg_result
        if 'redis/dump.rdb' in zf.namelist():
            redis_result = _restore_redis_rdb(zf)
            results['redis'] = redis_result
        if any(n.startswith('meilisearch/') for n in zf.namelist()):
            meili_result = _restore_meilisearch(zf)
            results['meilisearch'] = meili_result
        if psql_restored or psql_attempted:
            await _dispose_and_reinit_pool()
        else:
            await db.commit()
        try:
            from fastapi_app.core.cache import CacheDomain, invalidate_related_caches
            await invalidate_related_caches(CacheDomain.ALL)
        except (OSError, ValueError) as e:
            logger.warning(f'恢复后缓存清除失败: {e}')
        try:
            from fastapi_app.core.purchase_cache import invalidate_purchase_caches
            invalidate_purchase_caches()
        except (OSError, ValueError) as e:
            logger.warning(f'恢复后采购缓存清除失败: {e}')
        verify_db = None
        if psql_restored:
            from fastapi_app.core.database import _AsyncSessionLocal
            if _AsyncSessionLocal is not None:
                verify_db = _AsyncSessionLocal()
        try:
            target_db = verify_db or db
            verification = await _verify_restore(target_db, manifest.get('tables', {}), manifest.get('fingerprints'))
            results['verification'] = verification
            if not verification.get('overall_pass', True):
                results['_verification_failed'] = True
                logger.warning(f'恢复后验证未通过: {verification.get("l1_row_count", {}).get("summary", "")} ; {verification.get("l2_fingerprint", {}).get("summary", "")}')
        except (SQLAlchemyError, ValueError, OSError) as e:
            logger.warning(f'恢复后验证失败: {e}')
            results['verification'] = {'overall_pass': False, 'error': str(e)}
        finally:
            if verify_db is not None:
                try:
                    await verify_db.close()
                except (OSError, ValueError, SQLAlchemyError):
                    logger.warning('关闭验证数据库会话失败')
    except HTTPException:
        if not psql_attempted:
            try:
                await db.rollback()
            except (OSError, SQLAlchemyError):
                logger.warning('HTTP异常后回滚失败')
        raise
    except (RuntimeError, OSError, ValueError) as e:
        if not psql_attempted:
            try:
                await db.rollback()
            except (OSError, SQLAlchemyError):
                logger.warning('恢复异常后回滚失败')
        if pre_restore_info.get('success') and psql_attempted:
            logger.info('恢复失败，尝试从安全备份回滚...')
            try:
                rollback_path = Path(pre_restore_info['filepath'])
                if rollback_path.exists():
                    rollback_bytes = rollback_path.read_bytes()
                    await _restore_database_via_psql_from_bytes(rollback_bytes, db)
                    logger.info('从安全备份回滚成功')
                    results['rollback'] = {'success': True, 'from': pre_restore_info['filename']}
            except Exception as rb_err:
                logger.error(f'从安全备份回滚失败: {rb_err}')
                results['rollback'] = {'success': False, 'error': str(rb_err)}
        raise HTTPException(status_code=500, detail=f'恢复过程中出错: {e}') from e
    finally:
        if lock_acquired:
            if not psql_attempted:
                try:
                    await db.execute(text('SELECT pg_advisory_unlock(:lock_id)'), {'lock_id': RESTORE_LOCK_ID})
                except (RuntimeError, OSError, SQLAlchemyError):
                    logger.warning('释放恢复锁失败')
            else:
                try:
                    from fastapi_app.core.database import _AsyncSessionLocal
                    if _AsyncSessionLocal is not None:
                        lock_db = _AsyncSessionLocal()
                        try:
                            await lock_db.execute(text('SELECT pg_advisory_unlock(:lock_id)'), {'lock_id': RESTORE_LOCK_ID})
                        except (RuntimeError, OSError, SQLAlchemyError):
                            logger.warning('在新会话中释放恢复锁失败')
                        finally:
                            await lock_db.close()
                except (RuntimeError, OSError, ValueError, SQLAlchemyError):
                    logger.warning('创建锁释放会话失败')
        if psql_attempted:
            try:
                await db.close()
            except (OSError, SQLAlchemyError):
                logger.warning('psql后关闭数据库会话失败')
    return results

async def _restore_database_via_psql(zf: zipfile.ZipFile, db: AsyncSession, task_id: str = None) -> dict:
    """Restore database from dump.sql.gz using psql.

    The Python app's db session is closed and the connection pool disposed
    before DROP DATABASE, so that psql can drop the database without
    "database is being accessed by other users" errors.
    """
    import time as time_mod
    from fastapi_app.core.restore_progress import update_progress as _upd_prog

    async def _report(sub: float, detail: str):
        if task_id:
            await _upd_prog(task_id, 'restore_db', sub, detail)

    dump_gz = zf.read('database/dump.sql.gz')
    dump_sql = gzip.decompress(dump_gz)
    if not dump_sql or not dump_sql.strip():
        return {'status': 'error', 'error': '数据库备份文件为空，无法恢复'}
    db_host = os.getenv('DB_HOST', 'localhost')
    db_port = os.getenv('DB_PORT', '5432')
    db_user = os.getenv('DB_USER', 'erp_app')
    db_name = os.getenv('DB_NAME', 'erp_system')
    if not db_name.isidentifier():
        raise ValueError(f'Invalid database name: {db_name!r}')
    db_password = os.getenv('DB_PASSWORD', '')
    env = os.environ.copy()
    env['PGPASSWORD'] = db_password

    await _report(0.02, '关闭应用数据库连接')
    try:
        await db.close()
    except (OSError, SQLAlchemyError):
        logger.warning('psql前关闭数据库会话失败')
    try:
        from fastapi_app.core.database import _async_engine
        if _async_engine is not None:
            await _async_engine.dispose()
    except (OSError, ValueError):
        logger.warning('psql前释放连接池失败')

    await _report(0.06, '等待活跃连接释放')
    for _retry in range(3):
        await asyncio.sleep(1)
        try:
            check_proc = await asyncio.create_subprocess_exec('psql', '-h', db_host, '-p', db_port, '-U', db_user, '-d', 'postgres', '-t', '-c', f"SELECT COUNT(*) FROM pg_stat_activity WHERE datname = '{db_name}';", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=env)
            check_stdout, _ = await check_proc.communicate()
            if check_proc.returncode == 0:
                active_count = int(check_stdout.decode(errors='replace').strip() or '0')
                if active_count == 0:
                    break
                logger.warning(f'仍有 {active_count} 个活跃连接，重试 {_retry + 1}/3')
        except (TimeoutError, OSError, ValueError):
            pass

    await _report(0.10, '终止残留数据库连接')
    try:
        term_proc = await asyncio.create_subprocess_exec('psql', '-h', db_host, '-p', db_port, '-U', db_user, '-d', 'postgres', '-c', f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '{db_name}' AND pid <> pg_backend_pid();", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=env)  # nosec
        await term_proc.wait()
    except (TimeoutError, OSError, ValueError) as e:
        logger.warning(f'终止现有连接失败: {e}')

    await _report(0.14, '重建数据库')
    try:
        pg_major = 13
        try:
            ver_proc = await asyncio.create_subprocess_exec('psql', '-h', db_host, '-p', db_port, '-U', db_user, '-d', 'postgres', '-t', '-c', 'SHOW server_version;', stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=env)
            ver_stdout, _ = await ver_proc.communicate()
            if ver_proc.returncode == 0:
                ver_str = ver_stdout.decode(errors='replace').strip()
                pg_major = int(ver_str.split('.')[0])
        except (TimeoutError, OSError, ValueError):
            pass
        if pg_major >= 13:
            drop_cmd = f'DROP DATABASE IF EXISTS "{db_name}" WITH (FORCE);'
        else:
            drop_cmd = f'DROP DATABASE IF EXISTS "{db_name}";'
        drop_proc = await asyncio.create_subprocess_exec('psql', '-h', db_host, '-p', db_port, '-U', db_user, '-d', 'postgres', '-c', drop_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=env)
        _, stderr = await drop_proc.communicate()
        if drop_proc.returncode != 0:
            logger.warning(f"DROP DATABASE: {stderr.decode(errors='replace')}")
        create_proc = await asyncio.create_subprocess_exec('psql', '-h', db_host, '-p', db_port, '-U', db_user, '-d', 'postgres', '-c', f'CREATE DATABASE "{db_name}" OWNER "{db_user}";', stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=env)  # nosec
        _, stderr = await create_proc.communicate()
        if create_proc.returncode != 0:
            logger.warning(f"CREATE DATABASE: {stderr.decode(errors='replace')}")  # nosec
    except (TimeoutError, OSError, ValueError) as e:
        return {'status': 'error', 'error': f'数据库重建失败: {e}'}

    psql_start_time = time_mod.monotonic()

    try:
        await _report(0.20, '开始导入数据库数据')
        proc = await asyncio.create_subprocess_exec('psql', '-h', db_host, '-p', db_port, '-U', db_user, '-d', db_name, '-v', 'ON_ERROR_STOP=0', stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=env)
        try:
            # 增量写入 stdin 并读取 stdout/stderr，避免 communicate() 阻塞事件循环
            # 导致 heartbeat 协程无法调度、前端进度卡住
            total_size = len(dump_sql)
            written = 0
            chunk_size = 256 * 1024  # 256KB per chunk

            async def _write_stdin():
                nonlocal written
                while written < total_size:
                    end = min(written + chunk_size, total_size)
                    proc.stdin.write(dump_sql[written:end])
                    await proc.stdin.drain()
                    written = end
                    # 更新进度：写入阶段 0.20~0.50
                    sub = 0.20 + 0.30 * (written / total_size)
                    elapsed = int(time_mod.monotonic() - psql_start_time)
                    await _report(sub, f'写入数据 {written * 100 // total_size}% ({elapsed}s)')
                proc.stdin.close()

            async def _read_stream(stream, chunks):
                while True:
                    chunk = await stream.read(65536)
                    if not chunk:
                        break
                    chunks.append(chunk)

            stdout_chunks = []
            stderr_chunks = []
            write_task = asyncio.create_task(_write_stdin())
            read_out_task = asyncio.create_task(_read_stream(proc.stdout, stdout_chunks))
            read_err_task = asyncio.create_task(_read_stream(proc.stderr, stderr_chunks))

            # 等待写入完成，同时持续更新进度
            await asyncio.wait_for(write_task, timeout=600)

            # 写入完成后，读取阶段进度 0.50~0.85
            while not read_out_task.done() or not read_err_task.done():
                await asyncio.sleep(2)
                elapsed = int(time_mod.monotonic() - psql_start_time)
                await _report(0.70, f'等待 psql 完成... ({elapsed}s)')

            await asyncio.wait_for(asyncio.gather(read_out_task, read_err_task), timeout=600)
            await proc.wait()

            stdout = b''.join(stdout_chunks)
            stderr = b''.join(stderr_chunks)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return {'status': 'error', 'error': '数据库恢复超时（超过 600 秒），进程已终止'}
        stderr_text = stderr.decode(errors='replace')
        error_count = stderr_text.lower().count('error:')
        await _report(0.95, '数据导入完成，验证结果')
        if proc.returncode != 0:
            logger.warning(f'psql restore failed (returncode={proc.returncode}): {stderr_text[:2000]}')
            return {'status': 'error', 'message': '数据库恢复失败', 'errors': stderr_text[:2000]}
        if error_count > 0:
            logger.warning(f'psql restore completed with {error_count} errors: {stderr_text[:2000]}')
            return {'status': 'partial', 'message': f'数据库已恢复，但有 {error_count} 个语句执行失败', 'errors': stderr_text[:2000]}
        return {'status': 'ok', 'message': '数据库恢复成功'}
    except FileNotFoundError:
        return {'status': 'error', 'error': 'psql 命令未找到，请确保 PostgreSQL 客户端工具已安装'}
    except (TimeoutError, OSError, ValueError) as e:
        return {'status': 'error', 'error': f'数据库恢复失败: {e}'}
    finally:
        pass

async def _restore_database_via_psql_from_bytes(zip_bytes: bytes, db: AsyncSession) -> dict:
    try:
        zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except zipfile.BadZipFile:
        return {'status': 'error', 'error': '无效的 ZIP 备份文件'}
    if 'database/dump.sql.gz' not in zf.namelist():
        return {'status': 'error', 'error': '安全备份中无 database/dump.sql.gz'}
    return await _restore_database_via_psql(zf, db)

async def _restore_database_from_json(zf: zipfile.ZipFile, db: AsyncSession) -> dict:
    """Restore database from dump.json inside ZIP (legacy JSON format)."""
    try:
        json_bytes = zf.read('database/dump.json')
        backup_data = json.loads(json_bytes)
    except (OSError, ValueError, json.JSONDecodeError) as e:
        return {'status': 'error', 'error': f'读取 JSON 数据库备份失败: {e}'}
    if 'tables' not in backup_data:
        return {'status': 'error', 'error': 'JSON 备份缺少 tables 字段'}
    result = await _restore_legacy_json(backup_data, db)
    return {'status': 'ok' if not result['errors'] else 'partial', 'message': f"数据库恢复完成，共 {result['total_inserted']} 条记录", 'total_inserted': result['total_inserted'], 'errors': result['errors'][:5]}

def _restore_filestore(zf: zipfile.ZipFile) -> dict:
    """Restore filestore files to static/uploads/."""
    restored = 0
    errors = []
    for name in zf.namelist():
        if not name.startswith('filestore/') or name.endswith('/'):
            continue
        rel_path = name[len('filestore/'):]
        if '..' in rel_path or rel_path.startswith('/') or rel_path.startswith('\\'):
            errors.append(f'{rel_path}: 路径不安全，已跳过')
            continue
        target = UPLOADS_DIR / rel_path
        try:
            target.resolve().relative_to(UPLOADS_DIR.resolve())
        except ValueError:
            errors.append(f'{rel_path}: 路径越界，已跳过')
            continue
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(zf.read(name))
            restored += 1
        except (OSError, ValueError) as e:
            errors.append(f'{rel_path}: {e}')
    return {'status': 'ok' if not errors else 'partial', 'restored': restored, 'errors': errors}

def _restore_config(zf: zipfile.ZipFile) -> dict:
    """Restore config files to config/ directory."""
    restored = []
    errors = []
    for name in zf.namelist():
        if not name.startswith('config/') or name.endswith('/'):
            continue
        rel_path = name[len('config/'):]
        if '..' in rel_path or rel_path.startswith('/') or rel_path.startswith('\\'):
            errors.append(f'{rel_path}: 路径不安全，已跳过')
            continue
        target = CONFIG_DIR / rel_path
        try:
            target.resolve().relative_to(CONFIG_DIR.resolve())
        except ValueError:
            errors.append(f'{rel_path}: 路径越界，已跳过')
            continue
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(zf.read(name))
            restored.append(rel_path)
        except (OSError, ValueError) as e:
            errors.append(f'{rel_path}: {e}')
    return {'status': 'ok' if not errors else 'partial', 'restored': restored, 'errors': errors}

def _restore_redis_rdb(zf: zipfile.ZipFile) -> dict:
    try:
        rdb_data = zf.read('redis/dump.rdb')
        if REDIS_DUMP.is_file():
            backup_path = REDIS_DUMP.with_suffix('.rdb.bak')
            shutil.copy2(REDIS_DUMP, backup_path)
        REDIS_DUMP.write_bytes(rdb_data)
        reload_result = _reload_redis()
        if reload_result:
            return {'status': 'ok', 'message': 'Redis RDB 已恢复并重新加载'}
        return {'status': 'ok', 'message': 'Redis RDB 已恢复，需手动重启 Redis 生效', 'auto_reload_failed': True}
    except (OSError, ValueError) as e:
        return {'status': 'error', 'error': f'Redis RDB 恢复失败: {e}'}

def _restore_meilisearch(zf: zipfile.ZipFile) -> dict:
    try:
        meili_data = json.loads(zf.read('meilisearch/dump.json'))
    except (json.JSONDecodeError, KeyError, OSError) as e:
        return {'status': 'error', 'error': f'MeiliSearch 数据读取失败: {e}'}
    try:
        import httpx
    except ImportError:
        return {'status': 'error', 'error': 'httpx 未安装，无法恢复 MeiliSearch'}
    restored_indexes = []
    errors = []
    for key, data in meili_data.items():
        if key.endswith('__settings'):
            continue
        idx_name = key
        if not idx_name.replace('_', '').replace('-', '').isalnum():
            errors.append(f'{idx_name}: 索引名不合法，已跳过')
            continue
        settings_key = f'{idx_name}__settings'
        try:
            create_resp = httpx.post(f'{MEILI_HOST}/indexes', headers={'Authorization': f'Bearer {MEILI_MASTER_KEY}'}, json={'uid': idx_name, 'primaryKey': 'id'}, timeout=10)
            if create_resp.status_code not in (200, 201, 409):
                errors.append(f'{idx_name}: 创建索引失败 ({create_resp.status_code})')
                continue
            if settings_key in meili_data:
                httpx.patch(f'{MEILI_HOST}/indexes/{idx_name}/settings', headers={'Authorization': f'Bearer {MEILI_MASTER_KEY}'}, json=meili_data[settings_key], timeout=10)
            if data:
                docs_resp = httpx.post(f'{MEILI_HOST}/indexes/{idx_name}/documents', headers={'Authorization': f'Bearer {MEILI_MASTER_KEY}'}, json=data, timeout=60)
                if docs_resp.status_code in (200, 201, 202):
                    restored_indexes.append(idx_name)
                else:
                    errors.append(f'{idx_name}: 文档导入失败 ({docs_resp.status_code})')
            else:
                restored_indexes.append(idx_name)
        except (OSError, ValueError) as e:
            errors.append(f'{idx_name}: {e}')
    return {'status': 'ok' if not errors else 'partial', 'restored_indexes': restored_indexes, 'errors': errors}

def _reload_redis() -> bool:
    import subprocess
    redis_cli = shutil.which('redis-cli')
    if not redis_cli:
        logger.warning('未找到 redis-cli，无法自动重新加载 Redis')
        return False
    try:
        from fastapi_app.core.config import settings
        cmd = [redis_cli]
        cli_env = os.environ.copy()
        redis_url = settings.REDIS_URL
        if redis_url:
            from urllib.parse import urlparse
            parsed = urlparse(redis_url)
            if parsed.hostname:
                cmd.extend(['-h', parsed.hostname])
            if parsed.port:
                cmd.extend(['-p', str(parsed.port)])
            if parsed.password:
                cli_env['REDISCLI_AUTH'] = parsed.password
        cmd.extend(['DEBUG', 'RELOAD'])
        result = subprocess.run(cmd, capture_output=True, timeout=10, env=cli_env)
        if result.returncode == 0:
            logger.info('Redis DEBUG RELOAD 成功')
            return True
        stderr = result.stderr.decode(errors='replace')
        logger.warning(f'Redis DEBUG RELOAD 失败: {stderr}')
        try:
            shutdown_cmd = cmd[:-2] + ['SHUTDOWN', 'NOSAVE']
            subprocess.run(shutdown_cmd, capture_output=True, timeout=5, env=cli_env)
            logger.info('Redis SHUTDOWN NOSAVE 已发送，等待自动重启')
            import time
            time.sleep(2)
            ping_cmd = cmd[:-2] + ['PING']
            for _ in range(5):
                ping_result = subprocess.run(ping_cmd, capture_output=True, timeout=3, env=cli_env)
                if ping_result.returncode == 0:
                    logger.info('Redis 已重启成功')
                    return True
                time.sleep(1)
            logger.warning('Redis 重启后未能响应 PING')
            return False
        except (OSError, subprocess.TimeoutExpired) as e2:
            logger.warning(f'Redis SHUTDOWN 尝试失败: {e2}')
            return False
    except (OSError, subprocess.TimeoutExpired) as e:
        logger.warning(f'Redis 重新加载失败: {e}')
        return False

def _serialize_value(val):
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
    if hasattr(val, 'isoformat'):
        return val.isoformat()
    return str(val)

def _build_column_type_map(table):
    """Build a mapping of column_name -> sqlalchemy type for a given table."""
    return {str(col.name): col.type for col in table.columns}

def _deserialize_value(val, col_type):
    """Convert a JSON-deserialized value back to the proper Python type."""
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
                    pass
        return val
    if isinstance(col_type, Date):
        if isinstance(val, str):
            try:
                return datetime.strptime(val, '%Y-%m-%d').date()
            except ValueError:
                try:
                    return date.fromisoformat(val)
                except ValueError:
                    pass
        return val
    if isinstance(col_type, Time):
        if isinstance(val, str):
            try:
                return datetime.strptime(val, '%H:%M:%S').time()
            except ValueError:
                try:
                    return time_type.fromisoformat(val)
                except ValueError:
                    pass
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
        return val
    if isinstance(col_type, ARRAY):
        return val
    if isinstance(col_type, PG_UUID):
        if isinstance(val, str):
            return UUID(val)
        return val
    return val

async def _execute_legacy_backup_to_bytes(user: User, remark: str, db: AsyncSession) -> bytes:
    """Legacy JSON backup (v1.0) for environments without pg_dump."""
    from fastapi_app.shared_models import Base
    backup_data = {'version': '1.0', 'exported_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'), 'exported_by': user.username if hasattr(user, 'username') else str(user.id), 'remark': remark, 'tables': {}}
    for table in Base.metadata.sorted_tables:
        name = str(table.name)
        try:
            result = await db.execute(text(f'SELECT * FROM "{name}"'))  # nosec
            rows = result.mappings().all()
            columns = list(result.keys())
            serialized_rows = []
            for row in rows:
                serialized_row = {}
                for col in columns:
                    serialized_row[col] = _serialize_value(row[col])
                serialized_rows.append(serialized_row)
            backup_data['tables'][name] = {'columns': columns, 'rows': serialized_rows, 'count': len(serialized_rows)}
        except (SQLAlchemyError, ValueError, OSError) as e:
            logger.error(f'备份表 {name} 失败: {e}')
            backup_data['tables'][name] = {'error': str(e), 'count': 0, 'rows': []}
    return json.dumps(backup_data, ensure_ascii=False, indent=2).encode('utf-8')

async def _restore_legacy_json(backup_data: dict, db: AsyncSession) -> dict:
    """Restore from legacy JSON format backup (v1.0)."""
    from fastapi_app.shared_models import Base
    results = {}
    total_inserted = 0
    errors = []
    replication_role_set = False
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
        for table in reversed(Base.metadata.sorted_tables):
            table_name = str(table.name)
            if table_name not in backup_data.get('tables', {}):
                continue
            nested = await db.begin_nested()
            try:
                await db.execute(text(f'DELETE FROM "{table_name}"'))  # nosec
                await nested.commit()
            except (SQLAlchemyError, ValueError, OSError) as e:
                await nested.rollback()
                logger.warning(f'清空表 {table_name} 失败（外键约束）: {e}')
        for table in Base.metadata.sorted_tables:
            table_name = str(table.name)
            if table_name not in backup_data.get('tables', {}):
                continue
            table_data = backup_data['tables'][table_name]
            columns = table_data.get('columns', [])
            rows = table_data.get('rows', [])
            table_col_names = {c.name for c in table.columns}
            type_map = _build_column_type_map(table)
            BATCH_SIZE = 500
            inserted = 0
            batch_errors = []
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
                            deserialized = _deserialize_value(raw_val, col_type) if col_type else raw_val
                            params[f'{c}__row{idx}'] = deserialized
                        pk_cols = [c.name for c in table.primary_key.columns]
                        update_cols = [c for c in valid_cols if c not in pk_cols]
                        if pk_cols and update_cols:
                            update_str = ', '.join(f'"{c}" = EXCLUDED."{c}"' for c in update_cols)
                            await db.execute(text(f'INSERT INTO "{table_name}" ({col_str}) VALUES ({val_str}) ON CONFLICT ({", ".join(f"{c}" for c in pk_cols)}) DO UPDATE SET {update_str}'), params)
                        else:
                            await db.execute(text(f'INSERT INTO "{table_name}" ({col_str}) VALUES ({val_str}) ON CONFLICT DO NOTHING'), params)
                        inserted += 1
                    await nested.commit()
                except (SQLAlchemyError, ValueError, TypeError) as e:
                    await nested.rollback()
                    batch_errors.append(f'批次 {batch_start // BATCH_SIZE + 1}: {e}')
                    logger.warning(f'恢复表 {table_name} 批次 {batch_start // BATCH_SIZE + 1} 失败: {e}')
            if batch_errors:
                results[table_name] = {'status': 'partial', 'inserted': inserted, 'batch_errors': batch_errors}
                errors.append(f'{table_name}: {len(batch_errors)} 个批次失败')
            else:
                results[table_name] = {'status': 'ok', 'inserted': inserted}
            total_inserted += inserted
        await db.commit()
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
        try:
            manifest_tables = {tname: {'rows': td.get('count', len(td.get('rows', [])))} for tname, td in backup_data.get('tables', {}).items()}
            from fastapi_app.core.database import _AsyncSessionLocal
            verify_db = None
            if _AsyncSessionLocal is not None:
                verify_db = _AsyncSessionLocal()
            try:
                verification = await _verify_restore(verify_db or db, manifest_tables)
            finally:
                if verify_db is not None:
                    try:
                        await verify_db.close()
                    except (OSError, ValueError, SQLAlchemyError):
                        pass
        except (SQLAlchemyError, ValueError, OSError) as e:
            logger.warning(f'恢复后验证失败: {e}')
            verification = {'overall_pass': False, 'error': str(e)}
    except HTTPException:
        await db.rollback()
        raise
    except (SQLAlchemyError, ValueError, OSError) as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f'恢复过程中出错: {e}') from e
    db_status = 'ok' if not errors else 'partial'
    result_dict = {'database': {'status': db_status, 'total_inserted': total_inserted}, 'total_inserted': total_inserted, 'results': results, 'errors': errors, 'verification': verification}
    if not verification.get('overall_pass', True):
        result_dict['_verification_failed'] = True
    return result_dict
_CHECKSUM_EXCLUDE_TABLES = {'alembic_version'}

def _get_checksum_tables() -> set[str]:
    from fastapi_app.shared_models import Base
    return {str(t.name) for t in Base.metadata.sorted_tables if str(t.name) not in _CHECKSUM_EXCLUDE_TABLES}

async def _verify_restore(db: AsyncSession, manifest_tables: dict[str, dict], manifest_fingerprints: dict[str, str] | None=None) -> dict:
    """Four-layer post-restore verification.

    L0 — Global checksum: MD5 hash computed across ALL table data (database-level).
    L1 — Row count:  SELECT COUNT(*) for every table, compare with manifest.
    L2 — Data fingerprint:  MD5 aggregate of key business tables.
    L3 — ID sampling:  Check that the first 3 IDs from backup exist after restore.

    Returns a verification report dict with overall_pass (bool) and detailed breakdown.
    """
    from fastapi_app.shared_models import Base
    checksum_tables = _get_checksum_tables()
    l0_db_hash: str | None = None
    l0_tables_contributed = 0
    l1_results: list[dict] = []
    l2_results: list[dict] = []
    l3_results: list[dict] = []
    l0_parts: list[str] = []
    for table in Base.metadata.sorted_tables:
        tname = str(table.name)
        expected = manifest_tables.get(tname, {})
        expected_rows = expected.get('rows', -1)
        try:
            result = await db.execute(text(f'SELECT COUNT(*) FROM "{tname}"'))  # nosec
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
                cols_result = await db.execute(text('SELECT column_name FROM information_schema.columns WHERE table_name = :tname ORDER BY ordinal_position'), {'tname': tname})
                col_names = [r[0] for r in cols_result.fetchall()]
                agg = " || '|' || ".join(f'''COALESCE("{c}"::text, '')''' for c in col_names)
                row = await db.execute(text(f'''SELECT MD5(STRING_AGG(MD5({agg}), ',' ORDER BY "{order_col}")) FROM "{tname}"'''))  # nosec
                t_hash = row.scalar()
                if t_hash:
                    l0_parts.append(f'{tname}:{t_hash}')
                    l0_tables_contributed += 1
            except (SQLAlchemyError, ValueError, OSError) as e:
                logger.warning(f'验证: 表 {tname} 全局校验和计算失败: {e}')
        if tname in checksum_tables and expected_rows and (expected_rows > 0):
            try:
                pk_col = [c.name for c in table.primary_key.columns]
                order_col = pk_col[0] if pk_col else 'id'
                cols_result = await db.execute(text('SELECT column_name FROM information_schema.columns WHERE table_name = :tname ORDER BY ordinal_position'), {'tname': tname})
                col_names = [r[0] for r in cols_result.fetchall()]
                agg_expr = " || '|' || ".join(f'''COALESCE("{c}"::text, '')''' for c in col_names)
                fp_result = await db.execute(text(f'''SELECT MD5(STRING_AGG({agg_expr}, ',' ORDER BY "{order_col}")) FROM "{tname}"'''))  # nosec
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
                sample_result = await db.execute(text(f'SELECT "{sample_col}" FROM "{tname}" ORDER BY "{sample_col}" LIMIT 3'))  # nosec
                found_ids = [r[0] for r in sample_result.fetchall()]
            except (SQLAlchemyError, ValueError, OSError) as e:
                found_ids = []
                logger.warning(f'验证: 表 {tname} 抽样查询失败: {e}')
            l3_results.append({'table': tname, 'sample_ids': found_ids, 'count_found': len(found_ids)})
    l0_summary = {}
    if l0_parts:
        l0_db_hash = hashlib.md5('|'.join(l0_parts).encode(), usedforsecurity=False).hexdigest()
        l0_summary = {'db_checksum': l0_db_hash, 'tables_contributed': l0_tables_contributed, 'note': '恢复后数据库全局 MD5（可与备份时比对，全量备份 manifest 中可附带此值）'}
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
    # overall_pass 仅基于 L1 行数验证；L2 指纹因 pg_dump/psql 恢复过程中的
    # 序列值、扩展元数据等差异可能导致误判，仅作为参考信息
    all_passed = l1_all_pass
    return {'overall_pass': all_passed, 'verification_verdict': '通过' if all_passed else '失败', 'l0_global_checksum': l0_summary, 'l1_row_count': {'total_tables': len(l1_results), 'verifiable_tables': l1_verifiable, 'match': l1_match, 'indeterminate': l1_indeterminate, 'mismatch': l1_mismatch, 'pass_rate_pct': l1_pass_rate, 'summary': f'行数匹配: {l1_match}/{l1_verifiable} ({l1_pass_rate}%)'}, 'l2_fingerprint': {'tables_checked': l2_total, 'match': l2_match, 'mismatch': l2_mismatch, 'results': l2_results, 'summary': f'指纹匹配: {l2_match}/{l2_total}' if l2_total > 0 else '无业务表需校验'}, 'l3_sampling': {'tables_checked': len(l3_results), 'results': l3_results}}

@router.get('/ping')
async def ping(user: User=Depends(require_permission('backup_manage'))):
    """快速诊断端点"""
    from fastapi_app.shared_models import Base
    return {'status': 'ok', 'table_count': len(Base.metadata.sorted_tables), 'format_version': BACKUP_FORMAT_VERSION, 'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

@router.get('/tables')
async def list_backup_tables(user: User=Depends(require_permission('backup_manage')), db: AsyncSession=Depends(get_async_db)):
    """列出所有可备份的数据库表及行数"""
    from fastapi_app.shared_models import Base
    table_info = []
    try:
        for table in Base.metadata.sorted_tables:
            name = str(table.name)
            try:
                result = await db.execute(text(f'SELECT COUNT(*) FROM "{name}"'))  # nosec
                count = result.scalar()
            except (SQLAlchemyError, ValueError, OSError) as e:
                logger.warning(f'统计表 {name} 行数失败: {e}')
                count = -1
            table_info.append({'name': name, 'rows': count})
    except (SQLAlchemyError, OSError, ValueError) as e:
        logger.error(f'列出备份表失败: {e}\n{traceback.format_exc()}')
        raise HTTPException(status_code=500, detail=f'获取表信息失败: {e}') from e
    return {'success': True, 'tables': table_info, 'total': len(table_info)}

@router.get('/export')
async def export_backup(remark: str='', format: str='zip', user: User=Depends(require_permission('backup_manage')), db: AsyncSession=Depends(get_async_db)):
    """一键备份全部数据

    format=zip (默认): ZIP 格式，包含数据库 + 附件 + 配置 + Redis
    format=json: 旧版 JSON 格式（仅数据库表数据）
    """
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    if format == 'json':
        try:
            json_bytes = await _execute_legacy_backup_to_bytes(user, remark, db)
        except (OSError, ValueError, SQLAlchemyError) as e:
            logger.error(f'JSON 备份导出失败: {e}\n{traceback.format_exc()}')
            raise HTTPException(status_code=500, detail=f'备份失败: {e}') from e
        filename = f'erp_backup_{timestamp}.json'
        return StreamingResponse(io.BytesIO(json_bytes), media_type='application/json', headers={'Content-Disposition': f'attachment; filename="{filename}"'})
    try:
        zip_bytes, manifest = await _execute_backup_to_zip(user, remark, db)
    except (OSError, ValueError, SQLAlchemyError) as e:
        logger.error(f'ZIP 备份导出失败: {e}\n{traceback.format_exc()}')
        raise HTTPException(status_code=500, detail=f'备份失败: {e}') from e
    filename = f'erp_backup_{timestamp}.zip'
    return StreamingResponse(io.BytesIO(zip_bytes), media_type='application/zip', headers={'Content-Disposition': f'attachment; filename="{filename}"'})

@router.post('/import')
async def import_backup(file: UploadFile=File(...), confirm: bool=False, user: User=Depends(require_permission('backup_manage')), db: AsyncSession=Depends(get_async_db)):
    """一键恢复：从备份文件恢复全部数据

    支持 ZIP 格式（v2.0）和 JSON 格式（v1.0）。
    """
    if not confirm:
        raise HTTPException(status_code=400, detail='恢复操作需要二次确认，请传入 confirm=true')
    filename = file.filename or ''
    ext = os.path.splitext(filename)[1].lower()
    if ext not in ('.zip', '.json', '.gz'):
        raise HTTPException(status_code=400, detail=f'不支持的文件类型: {ext}，仅支持 .zip / .json')
    try:
        content = await file.read()
        if len(content) > MAX_BACKUP_FILE_SIZE:
            raise HTTPException(status_code=400, detail=f'备份文件超过大小限制({MAX_BACKUP_FILE_SIZE // 1024 // 1024}MB)')
    except HTTPException:
        raise
    except (OSError, ValueError) as e:
        raise HTTPException(status_code=400, detail=f'读取文件失败: {e}') from e
    if not content:
        raise HTTPException(status_code=400, detail='备份文件内容为空')
    is_zip = filename.endswith('.zip') or content[:4] == b'PK\x03\x04'
    is_json = filename.endswith('.json') or (content[:1] == b'{' and content.strip().endswith(b'}'))
    if not is_zip and (not is_json):
        raise HTTPException(status_code=400, detail='无法识别的备份文件格式')
    pre_restore_info = await _create_pre_restore_backup(db)
    if is_zip:
        result = await _restore_from_zip(content, db)
        result['pre_restore_backup'] = pre_restore_info
        total_rows = 0
        try:
            zf_manifest = zipfile.ZipFile(io.BytesIO(content))
            if 'manifest.json' in zf_manifest.namelist():
                m = json.loads(zf_manifest.read('manifest.json'))
                total_rows = sum(td.get('rows', 0) for td in m.get('tables', {}).values())
        except (zipfile.BadZipFile, json.JSONDecodeError, OSError):
            pass
        verification_ok = result.get('verification', {}).get('overall_pass', True)
        return {'success': verification_ok, 'format': 'zip', 'results': result, 'total_inserted': total_rows, 'restored_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
    try:
        backup_data = json.loads(content)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail='备份文件格式无效（非 ZIP 亦非有效 JSON）') from None
    if 'tables' not in backup_data:
        raise HTTPException(status_code=400, detail='JSON 备份文件缺少 tables 字段')
    lock_acquired = False
    try:
        lock_result = await db.execute(text('SELECT pg_try_advisory_lock(:lock_id)'), {'lock_id': RESTORE_LOCK_ID})
        if not lock_result.scalar():
            raise HTTPException(status_code=409, detail='另一个恢复操作正在执行中，请稍后重试')
        lock_acquired = True
    except HTTPException:
        raise
    except (RuntimeError, OSError):
        logger.warning('获取恢复锁失败，继续执行恢复操作')
    try:
        result = await _restore_legacy_json(backup_data, db)
    finally:
        if lock_acquired:
            try:
                await db.execute(text('SELECT pg_advisory_unlock(:lock_id)'), {'lock_id': RESTORE_LOCK_ID})
            except (RuntimeError, OSError, SQLAlchemyError):
                logger.warning('释放恢复锁失败')
    verification_ok = result.get('verification', {}).get('overall_pass', True)
    return {'success': verification_ok, 'format': 'json', 'total_inserted': result['total_inserted'], 'results': result['results'], 'errors': result['errors'], 'pre_restore_backup': pre_restore_info, 'restored_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

@router.post('/validate')
async def validate_backup(file: UploadFile=File(...), user: User=Depends(require_permission('backup_manage'))):
    """验证备份文件，不执行恢复，仅返回摘要信息"""
    filename = file.filename or ''
    ext = os.path.splitext(filename)[1].lower()
    if ext not in ('.zip', '.json', '.gz'):
        raise HTTPException(status_code=400, detail=f'不支持的文件类型: {ext}，仅支持 .zip / .json')
    try:
        content = await file.read()
        if len(content) > MAX_BACKUP_FILE_SIZE:
            raise HTTPException(status_code=400, detail=f'备份文件超过大小限制({MAX_BACKUP_FILE_SIZE // 1024 // 1024}MB)')
    except HTTPException:
        raise
    except (OSError, ValueError) as e:
        raise HTTPException(status_code=400, detail=f'读取文件失败: {e}') from e
    filename = file.filename or ''
    is_zip = filename.endswith('.zip') or content[:4] == b'PK\x03\x04'
    if is_zip:
        try:
            zf = zipfile.ZipFile(io.BytesIO(content))
        except zipfile.BadZipFile:
            raise HTTPException(status_code=400, detail='无效的 ZIP 文件') from None
        if 'manifest.json' not in zf.namelist():
            raise HTTPException(status_code=400, detail='ZIP 备份缺少 manifest.json')
        manifest = json.loads(zf.read('manifest.json'))
        names = zf.namelist()
        checksums_ok = True
        checksum_errors = []
        stored_checksums = manifest.get('checksums', {})
        for db_file in ['database/dump.sql.gz', 'database/dump.json']:
            if stored_checksums.get(db_file):
                actual = _sha256_bytes(zf.read(db_file))
                if actual != stored_checksums[db_file]:
                    checksums_ok = False
                    checksum_errors.append(f'{db_file} 校验和不匹配')
        summary = {'format': 'zip', 'version': manifest.get('version'), 'exported_at': manifest.get('exported_at'), 'exported_by': manifest.get('exported_by'), 'remark': manifest.get('remark', ''), 'table_count': manifest.get('table_count'), 'total_rows': manifest.get('total_rows'), 'includes': manifest.get('includes', {}), 'checksums_ok': checksums_ok, 'checksum_errors': checksum_errors, 'zip_contents': {'has_database': 'database/dump.sql.gz' in names or 'database/dump.json' in names, 'db_format': 'sql' if 'database/dump.sql.gz' in names else 'json' if 'database/dump.json' in names else 'none', 'has_filestore': any(n.startswith('filestore/') for n in names), 'has_config': any(n.startswith('config/') for n in names), 'has_redis': 'redis/dump.rdb' in names, 'has_meilisearch': any(n.startswith('meilisearch/') for n in names), 'filestore_count': sum(1 for n in names if n.startswith('filestore/') and (not n.endswith('/'))), 'config_files': [n for n in names if n.startswith('config/') and (not n.endswith('/'))]}}
        return {'success': True, 'summary': summary}
    try:
        backup_data = json.loads(content)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail='备份文件格式无效') from None
    if 'tables' not in backup_data:
        raise HTTPException(status_code=400, detail='JSON 备份文件缺少 tables 字段')
    from fastapi_app.shared_models import Base
    existing_tables = {str(t.name) for t in Base.metadata.sorted_tables}
    summary = {'format': 'json', 'version': backup_data.get('version'), 'exported_at': backup_data.get('exported_at'), 'exported_by': backup_data.get('exported_by'), 'remark': backup_data.get('remark', ''), 'table_count': len(backup_data['tables']), 'total_rows': sum(t.get('count', len(t.get('rows', []))) for t in backup_data['tables'].values()), 'checksums_ok': None, 'tables': []}
    for table_name, table_data in backup_data['tables'].items():
        row_count = table_data.get('count', len(table_data.get('rows', [])))
        summary['tables'].append({'name': table_name, 'rows': row_count, 'exists': table_name in existing_tables, 'has_error': 'error' in table_data})
    return {'success': True, 'summary': summary}

@router.post('/save')
async def save_backup_to_server(remark: str='', user: User=Depends(require_permission('backup_manage')), db: AsyncSession=Depends(get_async_db)):
    """一键备份到服务器默认路径（ZIP 格式）"""
    _ensure_backup_dir()
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    try:
        zip_bytes, manifest = await _execute_backup_to_zip(user, remark, db)
    except (OSError, ValueError, SQLAlchemyError) as e:
        logger.error(f'服务端备份失败: {e}\n{traceback.format_exc()}')
        raise HTTPException(status_code=500, detail=f'备份失败: {e}') from e
    filename = f'erp_backup_{timestamp}.zip'
    filepath = BACKUP_DIR / filename
    filepath.write_bytes(zip_bytes)
    return {'success': True, 'format': 'zip', 'filename': filename, 'size': manifest.get('zip_size', len(zip_bytes)), 'table_count': manifest.get('table_count', 0), 'total_rows': manifest.get('total_rows', 0), 'exported_at': manifest.get('exported_at'), 'exported_by': manifest.get('exported_by'), 'includes': manifest.get('includes', {}), 'remark': remark}

@router.get('/list')
async def list_server_backups(user: User=Depends(require_permission('backup_manage'))):
    """列出服务器默认路径上的所有备份文件"""
    backups = []
    if BACKUP_DIR.exists():
        for f in sorted(BACKUP_DIR.iterdir(), reverse=True):
            if not f.is_file():
                continue
            if not ((f.name.startswith('erp_backup_') or f.name.startswith('erp_incremental_')) and (f.name.endswith('.zip') or f.name.endswith('.json'))):
                continue
            entry: dict = {'filename': f.name, 'size': f.stat().st_size}
            if f.name.endswith('.zip'):
                try:
                    with zipfile.ZipFile(f, 'r') as zf:
                        if 'manifest.json' in zf.namelist():
                            manifest = json.loads(zf.read('manifest.json'))
                            entry.update({'format': manifest.get('type', 'zip'), 'exported_at': manifest.get('exported_at', ''), 'exported_by': manifest.get('exported_by', ''), 'remark': manifest.get('remark', ''), 'table_count': manifest.get('table_count', 0), 'total_rows': manifest.get('total_rows', 0), 'includes': manifest.get('includes', {}), 'base_timestamp': manifest.get('base_timestamp', '')})
                except (OSError, zipfile.BadZipFile, ValueError) as e:
                    logger.warning(f'读取 ZIP 备份 {f.name} 失败: {e}')
                    entry['error'] = str(e)
            elif f.name.endswith('.json'):
                try:
                    data = json.loads(f.read_text(encoding='utf-8'))
                    entry.update({'format': 'json', 'exported_at': data.get('exported_at', ''), 'exported_by': data.get('exported_by', ''), 'remark': data.get('remark', ''), 'table_count': len(data.get('tables', {})), 'total_rows': sum(t.get('count', len(t.get('rows', []))) for t in data.get('tables', {}).values())})
                except (OSError, json.JSONDecodeError, ValueError) as e:
                    logger.warning(f'读取 JSON 备份 {f.name} 失败: {e}')
                    entry['error'] = str(e)
            backups.append(entry)
    return {'success': True, 'backups': backups, 'total': len(backups)}

@router.post('/restore-by-name/{filename}')
async def restore_server_backup(filename: str, confirm: bool=Query(False), user: User=Depends(require_permission('backup_manage')), db: AsyncSession=Depends(get_async_db)):
    """从服务器默认路径恢复指定备份文件"""
    if not confirm:
        raise HTTPException(status_code=400, detail='恢复操作需要二次确认，请传入 confirm=true')
    safe_name = Path(filename).name
    if safe_name != filename:
        raise HTTPException(status_code=400, detail='无效的文件名')
    filepath = BACKUP_DIR / safe_name
    if not filepath.exists():
        raise HTTPException(status_code=404, detail='备份文件不存在')
    try:
        content = filepath.read_bytes()
    except (OSError, ValueError) as e:
        raise HTTPException(status_code=400, detail=f'读取备份文件失败: {e}') from e
    is_zip = safe_name.endswith('.zip') or content[:4] == b'PK\x03\x04'
    if is_zip:
        result = await _restore_from_zip(content, db)
        total_rows = 0
        try:
            zf_manifest = zipfile.ZipFile(io.BytesIO(content))
            if 'manifest.json' in zf_manifest.namelist():
                m = json.loads(zf_manifest.read('manifest.json'))
                total_rows = sum(td.get('rows', 0) for td in m.get('tables', {}).values())
        except (zipfile.BadZipFile, json.JSONDecodeError, OSError):
            pass
        verification_ok = result.get('verification', {}).get('overall_pass', True)
        return {'success': verification_ok, 'format': 'zip', 'filename': safe_name, 'results': result, 'total_inserted': total_rows, 'restored_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
    try:
        backup_data = json.loads(content)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail='备份文件格式无效') from None
    if 'tables' not in backup_data:
        raise HTTPException(status_code=400, detail='JSON 备份文件缺少 tables 字段')
    lock_acquired = False
    try:
        lock_result = await db.execute(text('SELECT pg_try_advisory_lock(:lock_id)'), {'lock_id': RESTORE_LOCK_ID})
        if not lock_result.scalar():
            raise HTTPException(status_code=409, detail='另一个恢复操作正在执行中，请稍后重试')
        lock_acquired = True
    except HTTPException:
        raise
    except (RuntimeError, OSError):
        logger.warning('获取恢复锁失败，继续执行恢复操作')
    try:
        result = await _restore_legacy_json(backup_data, db)
    finally:
        if lock_acquired:
            try:
                await db.execute(text('SELECT pg_advisory_unlock(:lock_id)'), {'lock_id': RESTORE_LOCK_ID})
            except (RuntimeError, OSError, SQLAlchemyError):
                logger.warning('释放恢复锁失败')
    verification_ok = result.get('verification', {}).get('overall_pass', True)
    return {'success': verification_ok, 'format': 'json', 'filename': safe_name, 'total_inserted': result['total_inserted'], 'results': result['results'], 'errors': result['errors'], 'restored_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

@router.delete('/delete-by-name/{filename}')
async def delete_server_backup(filename: str, user: User=Depends(require_permission('backup_manage'))):
    """删除服务器默认路径上的指定备份文件"""
    safe_name = Path(filename).name
    if safe_name != filename:
        raise HTTPException(status_code=400, detail='无效的文件名')
    filepath = BACKUP_DIR / safe_name
    if not filepath.exists():
        raise HTTPException(status_code=404, detail='备份文件不存在')
    try:
        filepath.unlink()
    except (OSError, ValueError) as e:
        raise HTTPException(status_code=500, detail=f'删除备份文件失败: {e}') from e
    return {'success': True, 'deleted': safe_name}

@router.get('/status')
async def backup_status(user: User=Depends(require_permission('backup_manage'))):
    """获取备份系统状态概览

    返回最近一次全量备份及备份目录统计信息。
    """
    last_full: dict | None = None
    total_backups = 0
    total_size = 0
    if BACKUP_DIR.exists():
        for f in sorted(BACKUP_DIR.iterdir(), reverse=True):
            if not f.is_file() or not (f.name.endswith('.zip') or f.name.endswith('.json')):
                continue
            total_backups += 1
            total_size += f.stat().st_size
            if last_full:
                continue
            try:
                if f.name.endswith('.zip'):
                    with zipfile.ZipFile(f, 'r') as zf:
                        if 'manifest.json' in zf.namelist():
                            mf = json.loads(zf.read('manifest.json'))
                            if mf.get('type') == 'full':
                                last_full = {'filename': f.name, 'size': f.stat().st_size, 'exported_at': mf.get('exported_at', ''), 'exported_by': mf.get('exported_by', ''), 'remark': mf.get('remark', ''), 'type': 'full', 'table_count': mf.get('table_count', 0), 'total_rows': mf.get('total_rows', 0)}
            except (json.JSONDecodeError, OSError, ValueError) as e:
                logger.warning(f'解析备份清单失败: {e}')
                continue
    return {'success': True, 'backup_dir': str(BACKUP_DIR), 'total_backups': total_backups, 'total_size_bytes': total_size, 'last_full_backup': last_full, 'checksum_tables': sorted(_get_checksum_tables()), 'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

@router.post('/save-incremental')
async def save_incremental_backup(remark: str = '', since: str = Query(''), user: User = Depends(require_permission('backup_manage')), db: AsyncSession = Depends(get_async_db)):
    _ensure_backup_dir()
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    from fastapi_app.shared_models import Base
    incremental_tables = {}
    total_rows = 0
    effective_since = since or await _find_last_backup_timestamp() or ''
    for table in Base.metadata.sorted_tables:
        tname = str(table.name)
        try:
            serialized_rows = await _query_table_rows(tname, db, effective_since or None)
            if serialized_rows:
                columns = list(serialized_rows[0].keys())
                incremental_tables[tname] = {'columns': columns, 'rows': serialized_rows, 'count': len(serialized_rows)}
                total_rows += len(serialized_rows)
        except (SQLAlchemyError, ValueError, OSError) as e:
            logger.warning(f'增量备份表 {tname} 失败: {e}')
    if not incremental_tables:
        return {'success': True, 'filename': None, 'message': '无变更数据需要备份', 'total_rows': 0}
    with tempfile.TemporaryDirectory(prefix='erp_inc_') as tmpdir:
        tmpdir_path = Path(tmpdir)
        json_path = tmpdir_path / 'database' / 'dump.json'
        json_path.parent.mkdir(parents=True, exist_ok=True)
        backup_data = {
            'version': BACKUP_FORMAT_VERSION,
            'type': 'incremental',
            'exported_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'exported_by': user.username if hasattr(user, 'username') else str(user.id),
            'remark': remark,
            'base_timestamp': effective_since,
            'table_count': len(incremental_tables),
            'total_rows': total_rows,
            'tables': incremental_tables,
        }
        json_path.write_bytes(json.dumps(backup_data, ensure_ascii=False, indent=2).encode('utf-8'))
        zip_path = tmpdir_path / 'backup.zip'
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED, compresslevel=3) as zf:
            zf.write(json_path, 'database/dump.json')
            manifest = {
                'version': BACKUP_FORMAT_VERSION,
                'type': 'incremental',
                'app_version': '2.0',
                'exported_at': backup_data['exported_at'],
                'exported_by': backup_data['exported_by'],
                'remark': remark,
                'base_timestamp': effective_since,
                'table_count': len(incremental_tables),
                'total_rows': total_rows,
                'includes': {},
                'checksums': {'database/dump.json': _sha256_file(json_path)},
            }
            zf.writestr('manifest.json', json.dumps(manifest, ensure_ascii=False, indent=2).encode('utf-8'))
        zip_bytes = zip_path.read_bytes()
    filename = f'erp_incremental_{timestamp}.zip'
    filepath = BACKUP_DIR / filename
    filepath.write_bytes(zip_bytes)
    return {'success': True, 'filename': filename, 'size': len(zip_bytes), 'format': 'incremental', 'table_count': len(incremental_tables), 'total_rows': total_rows, 'exported_at': backup_data['exported_at'], 'base_timestamp': effective_since, 'remark': remark}

@router.post('/restore-incremental/{filename}')
async def restore_incremental_backup(filename: str, confirm: bool = Query(False), user: User = Depends(require_permission('backup_manage')), db: AsyncSession = Depends(get_async_db)):
    if not confirm:
        raise HTTPException(status_code=400, detail='恢复操作需要二次确认，请传入 confirm=true')
    safe_name = Path(filename).name
    if safe_name != filename:
        raise HTTPException(status_code=400, detail='无效的文件名')
    filepath = BACKUP_DIR / safe_name
    if not filepath.exists():
        raise HTTPException(status_code=404, detail='备份文件不存在')
    try:
        content = filepath.read_bytes()
    except OSError as e:
        raise HTTPException(status_code=400, detail=f'读取备份文件失败: {e}') from e
    is_zip = safe_name.endswith('.zip') or content[:4] == b'PK\x03\x04'
    if not is_zip:
        raise HTTPException(status_code=400, detail='增量备份文件必须是 ZIP 格式')
    try:
        zf = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile:
        raise HTTPException(status_code=400, detail='无效的 ZIP 文件') from None
    if 'manifest.json' not in zf.namelist():
        raise HTTPException(status_code=400, detail='增量备份缺少 manifest.json')
    manifest = json.loads(zf.read('manifest.json'))
    if manifest.get('type') != 'incremental':
        raise HTTPException(status_code=400, detail='该备份不是增量备份，请使用全量恢复')
    if 'database/dump.json' not in zf.namelist():
        raise HTTPException(status_code=400, detail='增量备份中无数据库数据')
    try:
        backup_data = json.loads(zf.read('database/dump.json'))
    except (json.JSONDecodeError, OSError) as e:
        raise HTTPException(status_code=400, detail=f'读取增量备份数据失败: {e}') from e
    from fastapi_app.shared_models import Base
    table_map = {str(t.name): t for t in Base.metadata.sorted_tables}
    total_upserted = 0
    results = {}
    errors = []
    pre_restore_info = await _create_pre_restore_backup(db)
    lock_acquired = False
    try:
        lock_result = await db.execute(text('SELECT pg_try_advisory_lock(:lock_id)'), {'lock_id': RESTORE_LOCK_ID})
        if not lock_result.scalar():
            raise HTTPException(status_code=409, detail='另一个恢复操作正在执行中，请稍后重试')
        lock_acquired = True
        try:
            await db.execute(text("SET session_replication_role = 'replica'"))
        except (SQLAlchemyError, OSError) as e:
            logger.warning(f'禁用外键约束失败: {e}')
        for tname, table_data in backup_data.get('tables', {}).items():
            if tname not in table_map:
                continue
            table = table_map[tname]
            columns = table_data.get('columns', [])
            rows = table_data.get('rows', [])
            type_map = _build_column_type_map(table)
            pk_cols = [c.name for c in table.primary_key.columns]
            table_col_names = {c.name for c in table.columns}
            BATCH_SIZE = 500
            upserted = 0
            batch_errors = []
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
                            deserialized = _deserialize_value(raw_val, col_type) if col_type else raw_val
                            params[f'{c}__row{idx}'] = deserialized
                        update_cols = [c for c in valid_cols if c not in pk_cols]
                        if pk_cols and update_cols:
                            update_str = ', '.join(f'"{c}" = EXCLUDED."{c}"' for c in update_cols)
                            await db.execute(text(f'INSERT INTO "{tname}" ({col_str}) VALUES ({val_str}) ON CONFLICT ({", ".join(pk_cols)}) DO UPDATE SET {update_str}'), params)
                        else:
                            await db.execute(text(f'INSERT INTO "{tname}" ({col_str}) VALUES ({val_str}) ON CONFLICT DO NOTHING'), params)
                        upserted += 1
                    await nested.commit()
                except (SQLAlchemyError, ValueError, TypeError) as e:
                    await nested.rollback()
                    batch_errors.append(f'批次 {batch_start // BATCH_SIZE + 1}: {e}')
                    logger.warning(f'增量恢复表 {tname} 批次 {batch_start // BATCH_SIZE + 1} 失败: {e}')
            if batch_errors:
                results[tname] = {'status': 'partial', 'upserted': upserted, 'batch_errors': batch_errors}
                errors.append(f'{tname}: {len(batch_errors)} 个批次失败')
            else:
                results[tname] = {'status': 'ok', 'upserted': upserted}
            total_upserted += upserted
        try:
            await db.execute(text("SET session_replication_role = 'origin'"))
        except (SQLAlchemyError, OSError) as e:
            logger.warning(f'重新启用外键约束失败: {e}')
        await db.commit()
        try:
            from fastapi_app.core.cache import CacheDomain, invalidate_related_caches
            await invalidate_related_caches(CacheDomain.ALL)
        except (RuntimeError, OSError, ValueError) as e:
            logger.warning(f'增量恢复后缓存清除失败: {e}')
        try:
            from fastapi_app.core.purchase_cache import invalidate_purchase_caches
            invalidate_purchase_caches()
        except (RuntimeError, OSError, ValueError) as e:
            logger.warning(f'增量恢复后采购缓存清除失败: {e}')
    except HTTPException:
        try:
            await db.rollback()
        except (OSError, SQLAlchemyError):
            logger.warning('HTTP异常后回滚失败')
        raise
    except (SQLAlchemyError, ValueError, OSError) as e:
        try:
            await db.rollback()
        except (OSError, SQLAlchemyError):
            logger.warning('恢复异常后回滚失败')
        raise HTTPException(status_code=500, detail=f'增量恢复过程中出错: {e}') from e
    finally:
        if lock_acquired:
            try:
                await db.execute(text('SELECT pg_advisory_unlock(:lock_id)'), {'lock_id': RESTORE_LOCK_ID})
            except (OSError, ValueError, SQLAlchemyError):
                logger.warning('释放增量恢复锁失败')
    return {'success': True, 'format': 'incremental', 'filename': safe_name, 'total_upserted': total_upserted, 'results': results, 'errors': errors, 'pre_restore_backup': pre_restore_info, 'restored_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

@router.post('/integrity-check')
async def run_integrity_check(user: User = Depends(require_permission('backup_manage'))):
    from fastapi_app.tasks.backup_tasks import _do_integrity_check
    result = await _do_integrity_check()
    return result


@router.get('/progress/{task_id}')
async def get_restore_progress(task_id: str, user: User = Depends(require_permission('backup_manage'))):
    from fastapi_app.core.restore_progress import get_progress as _get_progress
    progress = await _get_progress(task_id)
    if progress is None:
        raise HTTPException(status_code=404, detail='任务不存在或已过期')
    return {'success': True, **progress}


@router.post('/async-import')
async def async_import_backup(file: UploadFile = File(...), confirm: bool = False, user: User = Depends(require_permission('backup_manage'))):
    if not confirm:
        raise HTTPException(status_code=400, detail='恢复操作需要二次确认，请传入 confirm=true')
    filename = file.filename or ''
    ext = os.path.splitext(filename)[1].lower()
    if ext not in ('.zip', '.json', '.gz'):
        raise HTTPException(status_code=400, detail=f'不支持的文件类型: {ext}，仅支持 .zip / .json')
    try:
        content = await file.read()
        if len(content) > MAX_BACKUP_FILE_SIZE:
            raise HTTPException(status_code=400, detail=f'备份文件超过大小限制({MAX_BACKUP_FILE_SIZE // 1024 // 1024}MB)')
    except HTTPException:
        raise
    except (OSError, ValueError) as e:
        raise HTTPException(status_code=400, detail=f'读取文件失败: {e}') from e
    if not content:
        raise HTTPException(status_code=400, detail='备份文件内容为空')
    is_zip = filename.endswith('.zip') or content[:4] == b'PK\x03\x04'
    is_json = filename.endswith('.json') or (content[:1] == b'{' and content.strip().endswith(b'}'))
    if not is_zip and (not is_json):
        raise HTTPException(status_code=400, detail='无法识别的备份文件格式')

    from fastapi_app.core.restore_progress import generate_task_id, create_progress
    task_id = generate_task_id()
    await create_progress(task_id, 'file_import')

    import asyncio
    asyncio.create_task(_run_async_file_restore(task_id, content, is_zip, filename))

    return {'success': True, 'task_id': task_id, 'message': '恢复任务已启动'}


@router.post('/async-restore-by-name/{filename}')
async def async_restore_server_backup(filename: str, confirm: bool = Query(False), user: User = Depends(require_permission('backup_manage'))):
    if not confirm:
        raise HTTPException(status_code=400, detail='恢复操作需要二次确认，请传入 confirm=true')
    safe_name = Path(filename).name
    if safe_name != filename:
        raise HTTPException(status_code=400, detail='无效的文件名')
    filepath = BACKUP_DIR / safe_name
    if not filepath.exists():
        raise HTTPException(status_code=404, detail='备份文件不存在')
    try:
        content = filepath.read_bytes()
    except (OSError, ValueError) as e:
        raise HTTPException(status_code=400, detail=f'读取备份文件失败: {e}') from e

    from fastapi_app.core.restore_progress import generate_task_id, create_progress
    task_id = generate_task_id()
    await create_progress(task_id, 'server_restore')

    is_zip = safe_name.endswith('.zip') or content[:4] == b'PK\x03\x04'

    import asyncio
    asyncio.create_task(_run_async_file_restore(task_id, content, is_zip, safe_name))

    return {'success': True, 'task_id': task_id, 'message': '恢复任务已启动'}


async def _run_async_file_restore(task_id: str, content: bytes, is_zip: bool, filename: str):
    from fastapi_app.core.restore_progress import (
        update_progress, complete_progress, fail_progress,
    )

    try:
        await update_progress(task_id, 'pre_backup', detail='准备恢复')
        pre_restore_info = None

        async with get_async_db_context() as db:
            try:
                from fastapi_app.core.restore_progress import _get_redis
                from fastapi_app.shared_models import User as UserModel
                dummy_user = UserModel()
                dummy_user.username = 'system'
                dummy_user.id = 0

                await update_progress(task_id, 'pre_backup', 0.0, '创建安全备份')
                pre_result = await _create_pre_restore_backup(db)
                pre_restore_info = pre_result
                await update_progress(task_id, 'pre_backup', 1.0, '安全备份完成')

                await update_progress(task_id, 'acquire_lock', 0.0, '获取恢复锁')
                lock_acquired = False
                try:
                    lock_result = await db.execute(text('SELECT pg_try_advisory_lock(:lock_id)'), {'lock_id': RESTORE_LOCK_ID})
                    if not lock_result.scalar():
                        await fail_progress(task_id, '另一个恢复操作正在执行中，请稍后重试')
                        return
                    lock_acquired = True
                except (RuntimeError, OSError):
                    logger.warning('获取恢复锁失败，继续执行恢复操作')
                await update_progress(task_id, 'acquire_lock', 1.0, '已获取锁')

                await update_progress(task_id, 'read_backup', 0.0, '读取备份文件')
                await update_progress(task_id, 'read_backup', 1.0, '备份文件已读取')

                if is_zip:
                    result = await _restore_from_zip_with_progress(content, db, task_id)
                else:
                    try:
                        backup_data = json.loads(content)
                    except json.JSONDecodeError:
                        await fail_progress(task_id, '备份文件格式无效（非 ZIP 亦非有效 JSON）')
                        return
                    if 'tables' not in backup_data:
                        await fail_progress(task_id, 'JSON 备份文件缺少 tables 字段')
                        return
                    result = await _restore_legacy_json_with_progress(backup_data, db, task_id)

                result['pre_restore_backup'] = pre_restore_info
                result['restored_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                result['filename'] = filename
                result['format'] = 'zip' if is_zip else 'json'
                if is_zip:
                    manifest_tables = result.get('_manifest_tables', {})
                    total_rows = sum(td.get('rows', 0) for td in manifest_tables.values()) if manifest_tables else 0
                    result['total_inserted'] = total_rows
                    result.pop('_manifest_tables', None)

                db_status = result.get('database', {}).get('status', '')
                verification_ok = result.get('verification', {}).get('overall_pass', True)
                restore_failed = db_status == 'error'
                verification_failed = not verification_ok

                if restore_failed and pre_restore_info and pre_restore_info.get('success'):
                    logger.info(f'数据库恢复失败(status={db_status})，尝试从安全备份回滚...')
                    try:
                        rollback_path = Path(pre_restore_info['filepath'])
                        if rollback_path.exists():
                            rollback_bytes = rollback_path.read_bytes()
                            from fastapi_app.core.database import _AsyncSessionLocal
                            if _AsyncSessionLocal is not None:
                                rollback_db = _AsyncSessionLocal()
                                try:
                                    await _restore_database_via_psql_from_bytes(rollback_bytes, rollback_db)
                                    result['rollback'] = {'success': True, 'from': pre_restore_info['filename']}
                                    logger.info('从安全备份回滚成功')
                                finally:
                                    await rollback_db.close()
                    except Exception as rb_err:
                        logger.error(f'从安全备份回滚失败: {rb_err}')
                        result['rollback'] = {'success': False, 'error': str(rb_err)}
                elif restore_failed:
                    if not pre_restore_info:
                        logger.warning('数据库恢复失败，但无安全备份信息，跳过回滚')
                    elif not pre_restore_info.get('success'):
                        logger.warning(f'数据库恢复失败，安全备份创建失败({pre_restore_info.get("error", "未知")})，跳过回滚')

                if restore_failed:
                    error_msg = result.get('database', {}).get('error') or result.get('database', {}).get('message') or '数据库恢复失败'
                    await fail_progress(task_id, f'数据库恢复失败: {error_msg}')
                elif verification_failed:
                    l1_summary = result.get('verification', {}).get('l1_row_count', {}).get('summary', '')
                    l2_summary = result.get('verification', {}).get('l2_fingerprint', {}).get('summary', '')
                    result['_verification_failed'] = True
                    verify_err = f'数据验证未通过: {l1_summary}'
                    if l2_summary:
                        verify_err += f'; {l2_summary}'
                    await fail_progress(task_id, verify_err)
                else:
                    await complete_progress(task_id, result)

            except HTTPException as e:
                await fail_progress(task_id, e.detail)
            except (RuntimeError, OSError, ValueError, SQLAlchemyError) as e:
                if pre_restore_info and pre_restore_info.get('success'):
                    logger.info('异步恢复失败，尝试从安全备份回滚...')
                await fail_progress(task_id, str(e))
            finally:
                if lock_acquired:
                    try:
                        from fastapi_app.core.database import _AsyncSessionLocal
                        if _AsyncSessionLocal is not None:
                            lock_db = _AsyncSessionLocal()
                            try:
                                await lock_db.execute(text('SELECT pg_advisory_unlock(:lock_id)'), {'lock_id': RESTORE_LOCK_ID})
                            except (RuntimeError, OSError, SQLAlchemyError):
                                logger.warning('在新会话中释放恢复锁失败')
                            finally:
                                await lock_db.close()
                        else:
                            await db.execute(text('SELECT pg_advisory_unlock(:lock_id)'), {'lock_id': RESTORE_LOCK_ID})
                    except (RuntimeError, OSError, SQLAlchemyError):
                        logger.warning('异步恢复后释放锁失败')
    except (RuntimeError, OSError, ValueError, SQLAlchemyError) as e:
        logger.error(f'异步恢复任务异常: {e}')
        await fail_progress(task_id, str(e))


async def _restore_from_zip_with_progress(zip_bytes: bytes, db: AsyncSession, task_id: str) -> dict:
    from fastapi_app.core.restore_progress import update_progress

    try:
        zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except zipfile.BadZipFile:
        raise HTTPException(status_code=400, detail='无效的 ZIP 备份文件') from None
    if 'manifest.json' not in zf.namelist():
        raise HTTPException(status_code=400, detail='备份文件缺少 manifest.json')
    manifest = json.loads(zf.read('manifest.json'))
    manifest_tables = manifest.get('tables', {})
    results = {'version': manifest.get('version'), 'exported_at': manifest.get('exported_at'), 'exported_by': manifest.get('exported_by'), 'remark': manifest.get('remark', ''), 'database': {}, 'filestore': {}, 'config': {}, 'redis': {}, 'meilisearch': {}, 'errors': [], 'warnings': [], '_manifest_tables': manifest_tables}
    stored_checksums = manifest.get('checksums', {})
    for db_file in ('database/dump.sql.gz', 'database/dump.json'):
        if stored_checksums.get(db_file):
            actual = _sha256_bytes(zf.read(db_file))
            if actual != stored_checksums[db_file]:
                results['warnings'].append(f'{db_file} 校验和不匹配，备份文件可能已损坏')

    psql_restored = False
    psql_attempted = False
    try:
        if 'database/dump.sql.gz' in zf.namelist():
            psql_attempted = True
            await update_progress(task_id, 'restore_db', 0.0, '通过 psql 恢复数据库')
            db_result = await _restore_database_via_psql(zf, db, task_id)
            results['database'] = db_result
            if db_result.get('status') == 'error':
                raise RuntimeError(f"数据库恢复失败: {db_result.get('error') or db_result.get('message', '未知错误')}")
            if db_result.get('status') in ('ok', 'partial'):
                psql_restored = True
            await update_progress(task_id, 'restore_db', 1.0, '数据库恢复完成')
        elif 'database/dump.json' in zf.namelist():
            await update_progress(task_id, 'restore_db', 0.0, '通过 JSON 恢复数据库')
            db_result = await _restore_database_from_json(zf, db)
            results['database'] = db_result
            if db_result.get('status') == 'error':
                raise RuntimeError(f"数据库恢复失败: {db_result.get('error') or db_result.get('message', '未知错误')}")
            await update_progress(task_id, 'restore_db', 1.0, '数据库恢复完成')
        else:
            results['warnings'].append('备份文件中无数据库导出')
            await update_progress(task_id, 'restore_db', 1.0, '无数据库数据')

        if any(n.startswith('filestore/') for n in zf.namelist()):
            await update_progress(task_id, 'restore_filestore', 0.0, '恢复附件文件')
            fs_result = _restore_filestore(zf)
            results['filestore'] = fs_result
            await update_progress(task_id, 'restore_filestore', 1.0, f'已恢复 {fs_result.get("restored", 0)} 个附件')
        else:
            results['warnings'].append('备份文件中无附件数据')
            await update_progress(task_id, 'restore_filestore', 1.0, '无附件数据')

        if any(n.startswith('config/') for n in zf.namelist()):
            await update_progress(task_id, 'restore_config', 0.0, '恢复配置文件')
            cfg_result = _restore_config(zf)
            results['config'] = cfg_result
            await update_progress(task_id, 'restore_config', 1.0, f'已恢复 {len(cfg_result.get("restored", []))} 个配置')
        else:
            await update_progress(task_id, 'restore_config', 1.0, '无配置数据')

        if 'redis/dump.rdb' in zf.namelist():
            await update_progress(task_id, 'restore_redis', 0.0, '恢复 Redis 数据')
            redis_result = _restore_redis_rdb(zf)
            results['redis'] = redis_result
            await update_progress(task_id, 'restore_redis', 1.0, 'Redis 恢复完成')
        else:
            await update_progress(task_id, 'restore_redis', 1.0, '无 Redis 数据')

        if any(n.startswith('meilisearch/') for n in zf.namelist()):
            await update_progress(task_id, 'restore_meilisearch', 0.0, '恢复搜索索引')
            meili_result = _restore_meilisearch(zf)
            results['meilisearch'] = meili_result
            await update_progress(task_id, 'restore_meilisearch', 1.0, '搜索索引恢复完成')
        else:
            await update_progress(task_id, 'restore_meilisearch', 1.0, '无搜索索引数据')

        if psql_restored or psql_attempted:
            await update_progress(task_id, 'rebuild_pool', 0.0, '重建数据库连接池')
            await _dispose_and_reinit_pool()
            await update_progress(task_id, 'rebuild_pool', 1.0, '连接池已重建')
        else:
            await db.commit()

        try:
            from fastapi_app.core.cache import CacheDomain, invalidate_related_caches
            await invalidate_related_caches(CacheDomain.ALL)
        except (OSError, ValueError) as e:
            logger.warning(f'恢复后缓存清除失败: {e}')
        try:
            from fastapi_app.core.purchase_cache import invalidate_purchase_caches
            invalidate_purchase_caches()
        except (OSError, ValueError) as e:
            logger.warning(f'恢复后采购缓存清除失败: {e}')

        await update_progress(task_id, 'verify', 0.0, '数据完整性验证中')
        verify_db = None
        if psql_restored:
            from fastapi_app.core.database import _AsyncSessionLocal
            if _AsyncSessionLocal is not None:
                verify_db = _AsyncSessionLocal()
        try:
            target_db = verify_db or db
            verification = await _verify_restore(target_db, manifest.get('tables', {}), manifest.get('fingerprints'))
            results['verification'] = verification
            if not verification.get('overall_pass', True):
                results['_verification_failed'] = True
                logger.warning(f'恢复后验证未通过: {verification.get("l1_row_count", {}).get("summary", "")} ; {verification.get("l2_fingerprint", {}).get("summary", "")}')
            await update_progress(task_id, 'verify', 1.0, '验证完成' if verification.get('overall_pass', True) else '验证未通过')
        except (SQLAlchemyError, ValueError, OSError) as e:
            logger.warning(f'恢复后验证失败: {e}')
            results['verification'] = {'overall_pass': False, 'error': str(e)}
            await update_progress(task_id, 'verify', 1.0, '验证完成（有异常）')
        finally:
            if verify_db is not None:
                try:
                    await verify_db.close()
                except (OSError, ValueError, SQLAlchemyError):
                    logger.warning('关闭验证数据库会话失败')
    except HTTPException:
        if not psql_attempted:
            try:
                await db.rollback()
            except (OSError, SQLAlchemyError):
                logger.warning('HTTP异常后回滚失败')
        raise
    except (RuntimeError, OSError, ValueError) as e:
        if not psql_attempted:
            try:
                await db.rollback()
            except (OSError, SQLAlchemyError):
                logger.warning('恢复异常后回滚失败')
        raise HTTPException(status_code=500, detail=f'恢复过程中出错: {e}') from e
    finally:
        if psql_attempted:
            try:
                await db.close()
            except (OSError, SQLAlchemyError):
                logger.warning('psql后关闭数据库会话失败')
    return results


async def _restore_legacy_json_with_progress(backup_data: dict, db: AsyncSession, task_id: str) -> dict:
    from fastapi_app.core.restore_progress import update_progress
    from fastapi_app.shared_models import Base

    results = {}
    total_inserted = 0
    errors = []
    replication_role_set = False
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

        await update_progress(task_id, 'restore_db', 0.0, '清空现有数据')
        for table in reversed(Base.metadata.sorted_tables):
            table_name = str(table.name)
            if table_name not in backup_data.get('tables', {}):
                continue
            nested = await db.begin_nested()
            try:
                await db.execute(text(f'DELETE FROM "{table_name}"'))
                await nested.commit()
            except (SQLAlchemyError, ValueError, OSError) as e:
                await nested.rollback()
                logger.warning(f'清空表 {table_name} 失败（外键约束）: {e}')

        total_tables = sum(1 for t in Base.metadata.sorted_tables if str(t.name) in backup_data.get('tables', {}))
        processed_tables = 0

        for table in Base.metadata.sorted_tables:
            table_name = str(table.name)
            if table_name not in backup_data.get('tables', {}):
                continue
            table_data = backup_data['tables'][table_name]
            columns = table_data.get('columns', [])
            rows = table_data.get('rows', [])
            table_col_names = {c.name for c in table.columns}
            type_map = _build_column_type_map(table)
            BATCH_SIZE = 500
            inserted = 0
            batch_errors = []
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
                            deserialized = _deserialize_value(raw_val, col_type) if col_type else raw_val
                            params[f'{c}__row{idx}'] = deserialized
                        pk_cols = [c.name for c in table.primary_key.columns]
                        update_cols = [c for c in valid_cols if c not in pk_cols]
                        if pk_cols and update_cols:
                            update_str = ', '.join(f'"{c}" = EXCLUDED."{c}"' for c in update_cols)
                            await db.execute(text(f'INSERT INTO "{table_name}" ({col_str}) VALUES ({val_str}) ON CONFLICT ({", ".join(f"{c}" for c in pk_cols)}) DO UPDATE SET {update_str}'), params)
                        else:
                            await db.execute(text(f'INSERT INTO "{table_name}" ({col_str}) VALUES ({val_str}) ON CONFLICT DO NOTHING'), params)
                        inserted += 1
                    await nested.commit()
                except (SQLAlchemyError, ValueError, TypeError) as e:
                    await nested.rollback()
                    batch_errors.append(f'批次 {batch_start // BATCH_SIZE + 1}: {e}')
                    logger.warning(f'恢复表 {table_name} 批次 {batch_start // BATCH_SIZE + 1} 失败: {e}')
            if batch_errors:
                results[table_name] = {'status': 'partial', 'inserted': inserted, 'batch_errors': batch_errors}
                errors.append(f'{table_name}: {len(batch_errors)} 个批次失败')
            else:
                results[table_name] = {'status': 'ok', 'inserted': inserted}
            total_inserted += inserted
            processed_tables += 1
            sub = processed_tables / total_tables if total_tables > 0 else 1.0
            await update_progress(task_id, 'restore_db', sub, f'已恢复 {processed_tables}/{total_tables} 表')

        await db.commit()
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

        await update_progress(task_id, 'rebuild_pool', 1.0, 'JSON恢复无需重建连接池')
        await update_progress(task_id, 'restore_filestore', 1.0, 'JSON备份无附件')
        await update_progress(task_id, 'restore_config', 1.0, 'JSON备份无配置')
        await update_progress(task_id, 'restore_redis', 1.0, 'JSON备份无Redis')
        await update_progress(task_id, 'restore_meilisearch', 1.0, 'JSON备份无搜索索引')

        await update_progress(task_id, 'verify', 0.0, '数据完整性验证中')
        try:
            manifest_tables = {tname: {'rows': td.get('count', len(td.get('rows', [])))} for tname, td in backup_data.get('tables', {}).items()}
            from fastapi_app.core.database import _AsyncSessionLocal
            verify_db = None
            if _AsyncSessionLocal is not None:
                verify_db = _AsyncSessionLocal()
            try:
                verification = await _verify_restore(verify_db or db, manifest_tables)
            finally:
                if verify_db is not None:
                    try:
                        await verify_db.close()
                    except (OSError, ValueError, SQLAlchemyError):
                        pass
            if not verification.get('overall_pass', True):
                logger.warning(f'恢复后验证未通过: {verification.get("l1_row_count", {}).get("summary", "")}')
            await update_progress(task_id, 'verify', 1.0, '验证完成' if verification.get('overall_pass', True) else '验证未通过')
        except (SQLAlchemyError, ValueError, OSError) as e:
            logger.warning(f'恢复后验证失败: {e}')
            verification = {'overall_pass': False, 'error': str(e)}
            await update_progress(task_id, 'verify', 1.0, '验证完成（有异常）')
    except HTTPException:
        await db.rollback()
        raise
    except (SQLAlchemyError, ValueError, OSError) as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f'恢复过程中出错: {e}') from e
    result_dict = {'total_inserted': total_inserted, 'database': {'status': 'ok' if not errors else 'partial'}, 'results': results, 'errors': errors, 'verification': verification}
    if not verification.get('overall_pass', True):
        result_dict['_verification_failed'] = True
    return result_dict
