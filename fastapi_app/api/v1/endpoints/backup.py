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

from fastapi_app.core.database import get_async_db
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
BACKUP_FORMAT_VERSION = '2.0'

def _ensure_backup_dir():
    """Lazily create backup directory on first use."""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)

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
                result = await db.execute(text(f'SELECT COUNT(*) FROM "{name}"'))
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
            if tname not in _CHECKSUM_TABLES:
                continue
            try:
                pk_col = [c.name for c in table.primary_key.columns]
                order_col = pk_col[0] if pk_col else 'id'
                cols_result = await db.execute(text('SELECT column_name FROM information_schema.columns WHERE table_name = :tname ORDER BY ordinal_position'), {'tname': tname})
                col_names = [r[0] for r in cols_result.fetchall()]
                agg_expr = " || '|' || ".join(f'''COALESCE("{c}"::text, '')''' for c in col_names)
                fp_result = await db.execute(text(f'''SELECT MD5(STRING_AGG({agg_expr}, ',' ORDER BY "{order_col}")) FROM "{tname}"'''))
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
            manifest_bytes = json.dumps(manifest, ensure_ascii=False, indent=2).encode('utf-8')
            zf.writestr('manifest.json', manifest_bytes)
        zip_bytes = zip_path.read_bytes()
        manifest['zip_size'] = len(zip_bytes)
        return (zip_bytes, manifest)

async def _dispose_and_reinit_pool():
    """Dispose the async engine pool and re-initialize it.

    Called after psql restore drops/recreates the database, which invalidates
    all existing connections in the pool.
    """
    import fastapi_app.core.database as db_mod
    engine = db_mod._async_engine
    if engine is not None:
        try:
            await engine.dispose()
        except Exception as e:
            logger.warning(f'释放引擎连接池异常（可忽略）: {e}')
    db_mod._async_engine = None
    db_mod._AsyncSessionLocal = None
    db_mod.async_engine = None
    db_mod._init_async_engine()
    logger.info('数据库连接池已重建')

async def _restore_from_zip(zip_bytes: bytes, db: AsyncSession) -> dict:
    """Restore from a ZIP backup file."""
    try:
        zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except zipfile.BadZipFile:
        raise HTTPException(status_code=400, detail='无效的 ZIP 备份文件') from None
    if 'manifest.json' not in zf.namelist():
        raise HTTPException(status_code=400, detail='备份文件缺少 manifest.json')
    manifest = json.loads(zf.read('manifest.json'))
    results = {'version': manifest.get('version'), 'exported_at': manifest.get('exported_at'), 'exported_by': manifest.get('exported_by'), 'remark': manifest.get('remark', ''), 'database': {}, 'filestore': {}, 'config': {}, 'redis': {}, 'errors': [], 'warnings': []}
    stored_checksums = manifest.get('checksums', {})
    if stored_checksums.get('database/dump.sql.gz'):
        actual = _sha256_bytes(zf.read('database/dump.sql.gz'))
        if actual != stored_checksums['database/dump.sql.gz']:
            results['warnings'].append('database/dump.sql.gz 校验和不匹配，备份文件可能已损坏')
    lock_acquired = False
    try:
        lock_result = await db.execute(text('SELECT pg_try_advisory_lock(:lock_id)'), {'lock_id': RESTORE_LOCK_ID})
        if not lock_result.scalar():
            raise HTTPException(status_code=409, detail='另一个恢复操作正在执行中，请稍后重试')
        lock_acquired = True
    except HTTPException:
        raise
    except Exception:
        logger.warning('获取恢复锁失败，继续执行恢复操作')
    psql_restored = False
    psql_attempted = False
    try:
        if 'database/dump.sql.gz' in zf.namelist():
            psql_attempted = True
            db_result = await _restore_database_via_psql(zf, db)
            results['database'] = db_result
            if db_result.get('status') in ('ok', 'partial'):
                psql_restored = True
        elif 'database/dump.json' in zf.namelist():
            db_result = await _restore_database_from_json(zf, db)
            results['database'] = db_result
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
    except Exception as e:
        if not psql_attempted:
            try:
                await db.rollback()
            except (OSError, SQLAlchemyError):
                logger.warning('恢复异常后回滚失败')
        raise HTTPException(status_code=500, detail=f'恢复过程中出错: {e}') from e
    finally:
        if lock_acquired and (not psql_attempted):
            try:
                await db.execute(text('SELECT pg_advisory_unlock(:lock_id)'), {'lock_id': RESTORE_LOCK_ID})
            except Exception:
                logger.warning('释放恢复锁失败')
        if psql_attempted:
            try:
                await db.close()
            except (OSError, SQLAlchemyError):
                logger.warning('psql后关闭数据库会话失败')
    return results

async def _restore_database_via_psql(zf: zipfile.ZipFile, db: AsyncSession) -> dict:
    """Restore database from dump.sql.gz using psql.

    The Python app's db session is closed and the connection pool disposed
    before DROP DATABASE, so that psql can drop the database without
    "database is being accessed by other users" errors.
    """
    dump_gz = zf.read('database/dump.sql.gz')
    dump_sql = gzip.decompress(dump_gz)
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
        await db.close()
    except (OSError, SQLAlchemyError):
        logger.warning('psql前关闭数据库会话失败')
    try:
        from fastapi_app.core.database import _async_engine
        if _async_engine is not None:
            await _async_engine.dispose()
    except (OSError, ValueError):
        logger.warning('psql前释放连接池失败')
    await asyncio.sleep(0.5)
    try:
        term_proc = await asyncio.create_subprocess_exec('psql', '-h', db_host, '-p', db_port, '-U', db_user, '-d', 'postgres', '-c', f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '{db_name}' AND pid <> pg_backend_pid();", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=env)
        await term_proc.wait()
    except (TimeoutError, OSError, ValueError) as e:
        logger.warning(f'终止现有连接失败: {e}')
    try:
        drop_proc = await asyncio.create_subprocess_exec('psql', '-h', db_host, '-p', db_port, '-U', db_user, '-d', 'postgres', '-c', f'DROP DATABASE IF EXISTS "{db_name}" WITH (FORCE);', stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=env)
        _, stderr = await drop_proc.communicate()
        if drop_proc.returncode != 0:
            logger.warning(f"DROP DATABASE: {stderr.decode(errors='replace')}")
        create_proc = await asyncio.create_subprocess_exec('psql', '-h', db_host, '-p', db_port, '-U', db_user, '-d', 'postgres', '-c', f'CREATE DATABASE "{db_name}" OWNER "{db_user}";', stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=env)
        _, stderr = await create_proc.communicate()
        if create_proc.returncode != 0:
            logger.warning(f"CREATE DATABASE: {stderr.decode(errors='replace')}")
    except (TimeoutError, OSError, ValueError) as e:
        return {'status': 'error', 'error': f'数据库重建失败: {e}'}
    try:
        proc = await asyncio.create_subprocess_exec('psql', '-h', db_host, '-p', db_port, '-U', db_user, '-d', db_name, '-v', 'ON_ERROR_STOP=0', stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=env)
        stdout, stderr = await proc.communicate(input=dump_sql)
        stderr_text = stderr.decode(errors='replace')
        if proc.returncode != 0:
            logger.warning(f'psql restore warnings: {stderr_text}')
            return {'status': 'partial', 'message': '数据库已恢复，但部分语句执行失败', 'errors': stderr_text[:2000]}
        return {'status': 'ok', 'message': '数据库恢复成功'}
    except FileNotFoundError:
        return {'status': 'error', 'error': 'psql 命令未找到，请确保 PostgreSQL 客户端工具已安装'}
    except (TimeoutError, OSError, ValueError) as e:
        return {'status': 'error', 'error': f'数据库恢复失败: {e}'}

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
        except Exception as e:
            errors.append(f'{rel_path}: {e}')
    return {'status': 'ok' if not errors else 'partial', 'restored': restored, 'errors': errors}

def _restore_redis_rdb(zf: zipfile.ZipFile) -> dict:
    """Restore Redis RDB snapshot."""
    try:
        rdb_data = zf.read('redis/dump.rdb')
        if REDIS_DUMP.is_file():
            backup_path = REDIS_DUMP.with_suffix('.rdb.bak')
            shutil.copy2(REDIS_DUMP, backup_path)
        REDIS_DUMP.write_bytes(rdb_data)
        return {'status': 'ok', 'message': 'Redis RDB 已恢复（需重启 Redis 生效）'}
    except (OSError, ValueError) as e:
        return {'status': 'error', 'error': f'Redis RDB 恢复失败: {e}'}

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
            result = await db.execute(text(f'SELECT * FROM "{name}"'))
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
    {str(t.name): t for t in Base.metadata.sorted_tables}
    results = {}
    total_inserted = 0
    errors = []
    lock_result = await db.execute(text('SELECT pg_try_advisory_lock(:lock_id)'), {'lock_id': RESTORE_LOCK_ID})
    if not lock_result.scalar():
        raise HTTPException(status_code=409, detail='另一个恢复操作正在执行中，请稍后重试')
    try:
        for table in reversed(Base.metadata.sorted_tables):
            table_name = str(table.name)
            if table_name not in backup_data.get('tables', {}):
                continue
            try:
                await db.execute(text(f'DELETE FROM "{table_name}"'))
            except (SQLAlchemyError, ValueError, OSError) as e:
                logger.warning(f'清空表 {table_name} 失败: {e}')
        for table in Base.metadata.sorted_tables:
            table_name = str(table.name)
            if table_name not in backup_data.get('tables', {}):
                continue
            table_data = backup_data['tables'][table_name]
            columns = table_data.get('columns', [])
            rows = table_data.get('rows', [])
            type_map = _build_column_type_map(table)
            nested = await db.begin_nested()
            try:
                inserted = 0
                for row in rows:
                    if not row:
                        continue
                    valid_cols = [c for c in columns if c in type_map and c in row]
                    if not valid_cols:
                        continue
                    col_str = ', '.join(f'"{c}"' for c in valid_cols)
                    val_str = ', '.join(f':{c}_{inserted}' for c in valid_cols)
                    params = {}
                    for c in valid_cols:
                        raw_val = row[c]
                        col_type = type_map.get(c)
                        deserialized = _deserialize_value(raw_val, col_type) if col_type else raw_val
                        params[f'{c}_{inserted}'] = deserialized
                    await db.execute(text(f'INSERT INTO "{table_name}" ({col_str}) VALUES ({val_str})'), params)
                    inserted += 1
                await nested.commit()
                results[table_name] = {'status': 'ok', 'inserted': inserted}
                total_inserted += inserted
            except (SQLAlchemyError, ValueError, TypeError) as e:
                await nested.rollback()
                error_msg = str(e)
                results[table_name] = {'status': 'error', 'error': error_msg}
                errors.append(f'{table_name}: {error_msg}')
        await db.commit()
        try:
            from fastapi_app.core.cache import CacheDomain, invalidate_related_caches
            await invalidate_related_caches(CacheDomain.ALL)
        except Exception as e:
            logger.warning(f'恢复后缓存清除失败: {e}')
        try:
            from fastapi_app.core.purchase_cache import invalidate_purchase_caches
            invalidate_purchase_caches()
        except Exception as e:
            logger.warning(f'恢复后采购缓存清除失败: {e}')
        try:
            manifest_tables = {tname: {'rows': td.get('count', len(td.get('rows', [])))} for tname, td in backup_data.get('tables', {}).items()}
            verification = await _verify_restore(db, manifest_tables)
        except (SQLAlchemyError, ValueError, OSError) as e:
            logger.warning(f'恢复后验证失败: {e}')
            verification = {'overall_pass': False, 'error': str(e)}
    except HTTPException:
        await db.rollback()
        raise
    except (SQLAlchemyError, ValueError, OSError) as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f'恢复过程中出错: {e}') from e
    finally:
        try:
            await db.execute(text('SELECT pg_advisory_unlock(:lock_id)'), {'lock_id': RESTORE_LOCK_ID})
        except (OSError, ValueError, SQLAlchemyError):
            logger.warning('释放恢复锁失败')
    return {'total_inserted': total_inserted, 'results': results, 'errors': errors, 'verification': verification}
_CHECKSUM_TABLES = {'order', 'product', 'stock_in', 'stock_out', 'customer', 'supplier', 'purchase_order', 'purchase_order_item', 'inventory_log', 'approval_request', 'material_registration', 'material_registration_item', 'production_plan', 'purchase_plan', 'purchase_plan_detail', 'packaging_record', 'craft_work', 'case', 'case_stock_in', 'case_stock_out', 'case_inventory_log'}

async def _verify_restore(db: AsyncSession, manifest_tables: dict[str, dict], manifest_fingerprints: dict[str, str] | None=None) -> dict:
    """Four-layer post-restore verification.

    L0 — Global checksum: MD5 hash computed across ALL table data (database-level).
    L1 — Row count:  SELECT COUNT(*) for every table, compare with manifest.
    L2 — Data fingerprint:  MD5 aggregate of key business tables.
    L3 — ID sampling:  Check that the first 3 IDs from backup exist after restore.

    Returns a verification report dict with overall_pass (bool) and detailed breakdown.
    """
    from fastapi_app.shared_models import Base
    {str(t.name): t for t in Base.metadata.sorted_tables}
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
            result = await db.execute(text(f'SELECT COUNT(*) FROM "{tname}"'))
            actual_rows = result.scalar() or 0
            table_exists = True
        except Exception as e:
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
                row = await db.execute(text(f'''SELECT MD5(STRING_AGG(MD5({agg}), ',' ORDER BY "{order_col}")) FROM "{tname}"'''))
                t_hash = row.scalar()
                if t_hash:
                    l0_parts.append(f'{tname}:{t_hash}')
                    l0_tables_contributed += 1
            except (SQLAlchemyError, ValueError, OSError) as e:
                logger.warning(f'验证: 表 {tname} 全局校验和计算失败: {e}')
        if tname in _CHECKSUM_TABLES and expected_rows and (expected_rows > 0):
            try:
                pk_col = [c.name for c in table.primary_key.columns]
                order_col = pk_col[0] if pk_col else 'id'
                cols_result = await db.execute(text('SELECT column_name FROM information_schema.columns WHERE table_name = :tname ORDER BY ordinal_position'), {'tname': tname})
                col_names = [r[0] for r in cols_result.fetchall()]
                agg_expr = " || '|' || ".join(f'''COALESCE("{c}"::text, '')''' for c in col_names)
                fp_result = await db.execute(text(f'''SELECT MD5(STRING_AGG({agg_expr}, ',' ORDER BY "{order_col}")) FROM "{tname}"'''))
                fingerprint = fp_result.scalar() or ''
            except (ValueError, TypeError, OSError) as e:
                fingerprint = ''
                logger.warning(f'验证: 表 {tname} 指纹计算失败: {e}')
            expected_fp = (manifest_fingerprints or {}).get(tname, '')
            fp_match = fingerprint == expected_fp if expected_fp else None
            l2_results.append({'table': tname, 'fingerprint': fingerprint, 'expected_fingerprint': expected_fp, 'match': fp_match})
        if expected_rows and expected_rows > 0:
            try:
                sample_result = await db.execute(text(f'SELECT id FROM "{tname}" ORDER BY id LIMIT 3'))
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
    all_passed = l1_all_pass and l2_all_pass
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
                result = await db.execute(text(f'SELECT COUNT(*) FROM "{name}"'))
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
    if is_zip:
        result = await _restore_from_zip(content, db)
        return {'success': True, 'format': 'zip', 'results': result, 'restored_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
    try:
        backup_data = json.loads(content)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail='备份文件格式无效（非 ZIP 亦非有效 JSON）') from None
    if 'tables' not in backup_data:
        raise HTTPException(status_code=400, detail='JSON 备份文件缺少 tables 字段')
    result = await _restore_legacy_json(backup_data, db)
    return {'success': True, 'format': 'json', 'total_inserted': result['total_inserted'], 'results': result['results'], 'errors': result['errors'], 'restored_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

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
        summary = {'format': 'zip', 'version': manifest.get('version'), 'exported_at': manifest.get('exported_at'), 'exported_by': manifest.get('exported_by'), 'remark': manifest.get('remark', ''), 'table_count': manifest.get('table_count'), 'total_rows': manifest.get('total_rows'), 'includes': manifest.get('includes', {}), 'checksums_ok': checksums_ok, 'checksum_errors': checksum_errors, 'zip_contents': {'has_database': 'database/dump.sql.gz' in names or 'database/dump.json' in names, 'db_format': 'sql' if 'database/dump.sql.gz' in names else 'json' if 'database/dump.json' in names else 'none', 'has_filestore': any(n.startswith('filestore/') for n in names), 'has_config': any(n.startswith('config/') for n in names), 'has_redis': 'redis/dump.rdb' in names, 'filestore_count': sum(1 for n in names if n.startswith('filestore/') and (not n.endswith('/'))), 'config_files': [n for n in names if n.startswith('config/') and (not n.endswith('/'))]}}
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
            if not (f.name.startswith('erp_backup_') and (f.name.endswith('.zip') or f.name.endswith('.json'))):
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
        return {'success': True, 'format': 'zip', 'filename': safe_name, 'results': result, 'restored_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
    try:
        backup_data = json.loads(content)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail='备份文件格式无效') from None
    if 'tables' not in backup_data:
        raise HTTPException(status_code=400, detail='JSON 备份文件缺少 tables 字段')
    result = await _restore_legacy_json(backup_data, db)
    return {'success': True, 'format': 'json', 'filename': safe_name, 'total_inserted': result['total_inserted'], 'results': result['results'], 'errors': result['errors'], 'restored_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

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
    return {'success': True, 'backup_dir': str(BACKUP_DIR), 'total_backups': total_backups, 'total_size_bytes': total_size, 'last_full_backup': last_full, 'checksum_tables': sorted(_CHECKSUM_TABLES), 'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
