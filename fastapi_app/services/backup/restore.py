"""恢复相关编排：从 ZIP 恢复、非依赖组件并行恢复、恢复锁管理。"""
from __future__ import annotations

import asyncio
import io
import json
import logging
import zipfile

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from ._constants import _RESTORE_LOCK_KEY, _RESTORE_LOCK_TTL
from .cache_restore import restore_meilisearch, restore_redis_rdb
from .crypto import sha256_bytes
from .dump import restore_database_via_psql
from .exceptions import RestoreError
from .filestore import restore_config, restore_filestore
from .json_backup import restore_database_from_json
from .verify import verify_restore

logger = logging.getLogger(__name__)


async def restore_non_dependent_components(
    zf: zipfile.ZipFile,
    confirm_sensitive: bool = False,
) -> dict:
    """并行恢复非依赖组件（文件存储、配置文件、Redis、MeiliSearch）"""
    results = {
        'filestore': {},
        'config': {},
        'redis': {},
        'meilisearch': {},
        'errors': [],
    }

    tasks = []

    if any(n.startswith('filestore/') for n in zf.namelist()):
        tasks.append(('filestore', asyncio.to_thread(restore_filestore, zf)))

    if any(n.startswith('config/') for n in zf.namelist()):
        tasks.append(('config', asyncio.to_thread(restore_config, zf, confirm_sensitive)))

    if 'redis/dump.rdb' in zf.namelist():
        tasks.append(('redis', restore_redis_rdb(zf)))

    if any(n.startswith('meilisearch/') for n in zf.namelist()):
        tasks.append(('meilisearch', restore_meilisearch(zf)))

    if tasks:
        logger.info(f"开始并行恢复 {len(tasks)} 个非依赖组件")
        try:
            async_tasks = []
            sync_tasks = []

            for component_name, task in tasks:
                if asyncio.iscoroutine(task):
                    async_tasks.append((component_name, task))
                else:
                    sync_tasks.append((component_name, task))

            if async_tasks:
                async_results = await asyncio.gather(
                    *[task for _, task in async_tasks],
                    return_exceptions=True
                )
                for (component_name, _), result in zip(async_tasks, async_results, strict=False):
                    if isinstance(result, Exception):
                        results[component_name] = {'status': 'error', 'error': str(result)}
                        results['errors'].append(f'{component_name}: {result}')
                        logger.error(f"恢复 {component_name} 失败: {result}")
                    else:
                        results[component_name] = result

            if sync_tasks:
                loop = asyncio.get_event_loop()
                sync_results = await asyncio.gather(
                    *[loop.run_in_executor(None, lambda t=t: t[1]) for t in sync_tasks],
                    return_exceptions=True
                )
                for (component_name, _), result in zip(sync_tasks, sync_results, strict=False):
                    if isinstance(result, Exception):
                        results[component_name] = {'status': 'error', 'error': str(result)}
                        results['errors'].append(f'{component_name}: {result}')
                        logger.error(f"恢复 {component_name} 失败: {result}")
                    else:
                        results[component_name] = result

            logger.info("非依赖组件并行恢复完成")

        except Exception as e:  # broad-except: 备份/恢复容错，防止局部异常导致整体流程中断
            logger.error(f"并行恢复失败: {e}")
            results['errors'].append(f'并行恢复失败: {e}')

    return results

async def restore_from_zip(
    zip_bytes: bytes,
    db: AsyncSession,
    decrypt_password: str | bytearray | None = None,
    task_id: str | None = None,
) -> dict:
    """从 ZIP 备份恢复全部数据。"""
    async def _prog(phase: str, sub: float = 0.0, detail: str = ''):
        if task_id:
            from fastapi_app.core.backup_progress import update_progress
            await update_progress(task_id, phase, sub, detail)

    try:
        zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except zipfile.BadZipFile:
        if decrypt_password:
            from fastapi_app.core.backup_encryption import BackupFileError as EncFileError
            from fastapi_app.core.backup_encryption import decrypt_backup
            try:
                zip_bytes = decrypt_backup(zip_bytes, decrypt_password)
                zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
            except EncFileError as e:
                raise RestoreError(f'解密失败: {e}') from e
        else:
            try:
                if zip_bytes[:4] != b'PK\x03\x04':
                    raise RestoreError('备份文件已加密，需要提供解密密码')
            except (RestoreError, IndexError, TypeError):
                raise RestoreError('无效的 ZIP 备份文件或加密文件需要密码') from None

    if 'manifest.json' not in zf.namelist():
        raise RestoreError('备份文件缺少 manifest.json')

    manifest = json.loads(zf.read('manifest.json'))

    if manifest.get('encrypted'):
        if not decrypt_password:
            raise RestoreError('备份文件已加密，需要提供解密密码')
        if zip_bytes[:4] == b'PK\x03\x04':
            pass
        else:
            from fastapi_app.core.backup_encryption import BackupFileError as EncFileError
            from fastapi_app.core.backup_encryption import decrypt_backup
            try:
                zip_bytes = decrypt_backup(zip_bytes, decrypt_password)
                zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
                manifest = json.loads(zf.read('manifest.json'))
            except EncFileError as e:
                raise RestoreError(f'解密失败: {e}') from e
    manifest_tables = manifest.get('tables', {})
    results = {
        'version': manifest.get('version'),
        'exported_at': manifest.get('exported_at'),
        'exported_by': manifest.get('exported_by'),
        'remark': manifest.get('remark', ''),
        'database': {}, 'filestore': {}, 'config': {}, 'redis': {}, 'meilisearch': {},
        'errors': [], 'warnings': [], '_manifest_tables': manifest_tables,
    }

    stored_checksums = manifest.get('checksums', {})
    for db_file in ('database/dump.sql.gz', 'database/dump.json'):
        if stored_checksums.get(db_file):
            actual = sha256_bytes(zf.read(db_file))  # REV-14
            if actual != stored_checksums[db_file]:
                results['warnings'].append(f'{db_file} 校验和不匹配，备份文件可能已损坏')

    psql_restored = False
    psql_attempted = False
    try:
        if 'database/dump.sql.gz' in zf.namelist():
            psql_attempted = True
            await _prog('restore_db', 0.0, '通过 psql 恢复数据库')
            db_result = await restore_database_via_psql(zf, db, task_id)
            results['database'] = db_result
            if db_result.get('status') == 'error':
                raise RuntimeError(f"数据库恢复失败: {db_result.get('error') or db_result.get('message', '未知错误')}")
            if db_result.get('status') in ('ok', 'partial'):
                psql_restored = True
            await _prog('restore_db', 1.0, '数据库恢复完成')
        elif 'database/dump.json' in zf.namelist():
            await _prog('restore_db', 0.0, '通过 JSON 恢复数据库')
            db_result = await restore_database_from_json(zf, db, task_id)
            results['database'] = db_result
            if db_result.get('status') == 'error':
                raise RuntimeError(f"数据库恢复失败: {db_result.get('error') or db_result.get('message', '未知错误')}")
            await _prog('restore_db', 1.0, '数据库恢复完成')
        else:
            results['warnings'].append('备份文件中无数据库导出')
            await _prog('restore_db', 1.0, '无数据库数据')

        await _prog('restore_components', 0.0, '开始并行恢复非依赖组件')

        has_filestore = any(n.startswith('filestore/') for n in zf.namelist())
        has_config = any(n.startswith('config/') for n in zf.namelist())
        has_redis = 'redis/dump.rdb' in zf.namelist()
        has_meilisearch = any(n.startswith('meilisearch/') for n in zf.namelist())

        if has_filestore or has_config or has_redis or has_meilisearch:
            components_result = await restore_non_dependent_components(zf, confirm_sensitive=False)

            if 'filestore' in components_result:
                results['filestore'] = components_result['filestore']
                if has_filestore:
                    await _prog('restore_components', 0.25, f'文件存储恢复完成: {components_result["filestore"].get("restored", 0)} 个文件')
                else:
                    results['warnings'].append('备份文件中无附件数据')

            if 'config' in components_result:
                results['config'] = components_result['config']
                if has_config:
                    await _prog('restore_components', 0.5, f'配置文件恢复完成: {len(components_result["config"].get("restored", []))} 个文件')
                else:
                    await _prog('restore_components', 0.5, '无配置数据')

            if 'redis' in components_result:
                results['redis'] = components_result['redis']
                if has_redis:
                    await _prog('restore_components', 0.75, 'Redis 恢复完成')
                else:
                    await _prog('restore_components', 0.75, '无 Redis 数据')

            if 'meilisearch' in components_result:
                results['meilisearch'] = components_result['meilisearch']
                if has_meilisearch:
                    await _prog('restore_components', 1.0, '搜索索引恢复完成')
                else:
                    await _prog('restore_components', 1.0, '无搜索索引数据')

            if 'errors' in components_result:
                results['errors'].extend(components_result['errors'])
        else:
            await _prog('restore_components', 1.0, '无非依赖组件需要恢复')

        if psql_restored or psql_attempted:
            await _prog('rebuild_pool', 0.0, '重建数据库连接池')
            from fastapi_app.core.database import rebuild_pool  # REV-25
            await rebuild_pool()
            await _prog('rebuild_pool', 1.0, '连接池已重建')
        else:
            await db.commit()  # manual-tx: try/except 内显式事务控制

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

        await _prog('verify', 0.0, '数据完整性验证中')
        verify_db = None
        if psql_restored:
            from fastapi_app.core.database import _AsyncSessionLocal
            if _AsyncSessionLocal is not None:
                verify_db = _AsyncSessionLocal()
        try:
            target_db = verify_db or db
            verification = await verify_restore(
                target_db,
                manifest.get('tables', {}),
                manifest.get('fingerprints'),
                manifest.get('schema_snapshot'),
            )
            results['verification'] = verification
            if not verification.get('overall_pass', True):
                results['_verification_failed'] = True
                logger.warning(
                    f'恢复后验证未通过: {verification.get("l1_row_count", {}).get("summary", "")} ; '
                    f'{verification.get("l2_fingerprint", {}).get("summary", "")}'
                )
            await _prog('verify', 1.0, '验证完成' if verification.get('overall_pass', True) else '验证未通过')
        except (SQLAlchemyError, ValueError, OSError) as e:
            logger.warning(f'恢复后验证失败: {e}')
            results['verification'] = {'overall_pass': False, 'error': str(e)}
            await _prog('verify', 1.0, '验证完成（有异常）')
        finally:
            if verify_db is not None:
                try:
                    await verify_db.close()
                except (OSError, ValueError, SQLAlchemyError):
                    logger.warning('关闭验证数据库会话失败')
    except RestoreError:
        raise
    except (RuntimeError, OSError, ValueError) as e:
        if not psql_attempted:
            try:
                await db.rollback()  # manual-tx: try/except 内显式事务控制
            except (OSError, SQLAlchemyError):
                logger.warning('恢复异常后回滚失败')
        raise RestoreError(f'恢复过程中出错: {e}') from e
    finally:
        if psql_attempted:
            try:
                await db.close()
            except (OSError, SQLAlchemyError):
                logger.warning('psql后关闭数据库会话失败')

    return results


async def acquire_restore_lock(task_id: str) -> bool:
    """尝试获取恢复锁（Redis 分布式锁，支持多 worker）

    fail-closed（M3）:Redis 不可用时返回 False，拒绝还原执行——高危域不允许在
    无法确认锁的情况下放行，避免两个还原在 4 worker 间并发覆盖数据。
    """
    try:
        from fastapi_app.core.backup_progress import _get_redis
        client = await _get_redis()
        if client is None:
            logger.warning('Redis 不可用，拒绝获取恢复锁（fail-closed）')
            return False
        result = await client.set(
            _RESTORE_LOCK_KEY, task_id,
            nx=True, ex=_RESTORE_LOCK_TTL
        )
        return result is not None
    except Exception as e:  # broad-except: 备份/恢复容错，防止局部异常导致整体流程中断
        logger.warning(f'获取恢复锁失败: {e}（fail-closed，拒绝还原）')
        return False


async def release_restore_lock():
    """释放恢复锁"""
    try:
        from fastapi_app.core.backup_progress import _get_redis
        client = await _get_redis()
        if client is not None:
            await client.delete(_RESTORE_LOCK_KEY)
    except Exception as e:  # broad-except: 备份/恢复容错，防止局部异常导致整体流程中断
        logger.warning(f'释放恢复锁失败: {e}')


async def is_restore_in_progress() -> bool:
    """检查是否有恢复任务正在执行（fail-closed:Redis 不可用时保守视为有任务）"""
    try:
        from fastapi_app.core.backup_progress import _get_redis
        client = await _get_redis()
        if client is None:
            logger.warning('Redis 不可用，is_restore_in_progress 保守返回 True（fail-closed）')
            return True
        return await client.exists(_RESTORE_LOCK_KEY) > 0
    except Exception as e:  # broad-except: 备份/恢复容错，防止局部异常导致整体流程中断
        logger.warning(f'检查恢复锁失败: {e}（fail-closed，视为有任务）')
        return True
