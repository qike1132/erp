"""
备份相关 Celery 定时任务

调用 backup_service 层函数，不再直接 import endpoint 模块。
"""
import asyncio
import logging
from datetime import datetime

from celery import shared_task

logger = logging.getLogger(__name__)


def _run_async(coro):
    """在 Celery worker 中运行异步代码"""
    try:
        return asyncio.run(coro)
    except RuntimeError:
        # 如果已有事件循环，使用 new_event_loop
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()


@shared_task(name='auto_daily_backup_task', queue='batch', time_limit=1800, soft_time_limit=1500)
def auto_daily_backup_task():
    """每日自动全量备份"""
    logger.info('开始执行每日自动全量备份...')
    try:
        result = _run_async(_do_auto_backup('daily'))
        logger.info(f'每日自动备份完成: {result}')
        return result
    except Exception as e:
        logger.error(f'每日自动备份失败: {e}')
        return {'status': 'error', 'error': str(e)}


@shared_task(name='auto_incremental_backup_task', queue='batch', time_limit=600)
def auto_incremental_backup_task():
    """自动增量备份"""
    logger.info('开始执行自动增量备份...')
    try:
        result = _run_async(_do_auto_backup('incremental'))
        logger.info(f'自动增量备份完成: {result}')
        return result
    except Exception as e:
        logger.error(f'自动增量备份失败: {e}')
        return {'status': 'error', 'error': str(e)}


@shared_task(name='backup_integrity_check_task', queue='batch', time_limit=600)
def backup_integrity_check_task():
    """备份完整性巡检"""
    logger.info('开始执行备份完整性巡检...')
    try:
        result = _run_async(_do_integrity_check())
        if result.get('failed', 0) > 0:
            logger.warning(f'备份完整性巡检发现 {result["failed"]} 个问题: {result.get("details", [])}')
        else:
            logger.info('备份完整性巡检通过')
        return result
    except Exception as e:
        logger.error(f'备份完整性巡检失败: {e}')
        return {'status': 'error', 'error': str(e)}


@shared_task(name='backup_cleanup_task', queue='batch', time_limit=300)
def backup_cleanup_task():
    """备份清理任务（保留策略）"""
    logger.info('开始执行备份清理...')
    try:
        from fastapi_app.services.backup_service import cleanup_old_backups
        result = cleanup_old_backups()
        logger.info(f'备份清理完成: 删除 {result["deleted_count"]} 个，保留 {result["kept_count"]} 个')
        return result
    except Exception as e:
        logger.error(f'备份清理失败: {e}')
        return {'status': 'error', 'error': str(e)}


async def _do_auto_backup(backup_type: str) -> dict:
    """执行自动备份（全量或增量）"""
    from fastapi_app.core.database import get_async_db_context
    from fastapi_app.shared_models import User as UserModel
    from fastapi_app.services import backup_service

    backup_service.ensure_backup_dir()

    async with get_async_db_context() as db:
        dummy_user = UserModel()
        dummy_user.username = 'system_auto'
        dummy_user.id = 0

        if backup_type == 'daily':
            zip_bytes, manifest = await backup_service.create_full_backup(db, dummy_user, '每日自动全量备份')
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f'erp_auto_daily_{timestamp}.zip'
            filepath = backup_service.BACKUP_DIR / filename
            filepath.write_bytes(zip_bytes)

            # 写入 BackupRecord
            await backup_service.write_backup_record(
                db, record_type='full', trigger_type='auto',
                filename=filename, size=len(zip_bytes),
                table_count=manifest.get('table_count'),
                total_rows=manifest.get('total_rows'),
                operator='system_auto', remark='每日自动全量备份',
            )
            return {
                'status': 'ok', 'type': 'daily', 'filename': filename,
                'size': len(zip_bytes),
                'table_count': manifest.get('table_count'),
                'total_rows': manifest.get('total_rows'),
            }
        else:
            result = await backup_service.create_incremental_backup(db, dummy_user, '自动增量备份')
            if result.get('filename'):
                await backup_service.write_backup_record(
                    db, record_type='incremental', trigger_type='auto',
                    filename=result['filename'], size=result.get('size'),
                    table_count=result.get('table_count'),
                    total_rows=result.get('total_rows'),
                    operator='system_auto', remark='自动增量备份',
                )
            return {'status': 'ok', 'type': 'incremental', 'result': result}


async def _do_integrity_check() -> dict:
    """执行备份完整性巡检"""
    import hashlib
    import json
    import zipfile
    from fastapi_app.services import backup_service

    results = {
        'checked_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'total': 0, 'passed': 0, 'failed': 0, 'details': [],
    }

    if not backup_service.BACKUP_DIR.exists():
        results['details'].append('备份目录不存在')
        results['failed'] += 1
        return results

    backup_files = sorted(
        [f for f in backup_service.BACKUP_DIR.iterdir()
         if f.is_file() and (f.name.startswith('erp_backup_') or f.name.startswith('erp_auto_') or f.name.startswith('erp_incremental_'))
         and f.name.endswith('.zip')],
        key=lambda f: f.stat().st_mtime, reverse=True
    )
    if not backup_files:
        results['details'].append('无备份文件')
        results['failed'] += 1
        return results

    latest = backup_files[0]
    results['latest_backup'] = latest.name
    results['latest_backup_size'] = latest.stat().st_size
    mtime = datetime.fromtimestamp(latest.stat().st_mtime)
    age_hours = (datetime.now() - mtime).total_seconds() / 3600
    if age_hours > 48:
        results['details'].append(f'最新备份已超过 {age_hours:.1f} 小时（阈值: 48小时）')
        results['failed'] += 1
    else:
        results['passed'] += 1

    try:
        with zipfile.ZipFile(latest, 'r') as zf:
            if 'manifest.json' not in zf.namelist():
                results['details'].append(f'{latest.name}: 缺少 manifest.json')
                results['failed'] += 1
            else:
                manifest = json.loads(zf.read('manifest.json'))
                checksums = manifest.get('checksums', {})
                for arc_name, expected_hash in checksums.items():
                    if arc_name in zf.namelist():
                        actual = hashlib.sha256(zf.read(arc_name)).hexdigest()
                        if actual != expected_hash:
                            results['details'].append(f'{latest.name}: {arc_name} SHA256 不匹配')
                            results['failed'] += 1
                        else:
                            results['passed'] += 1
                    else:
                        results['details'].append(f'{latest.name}: {arc_name} 文件缺失')
                        results['failed'] += 1
                if manifest.get('total_rows', 0) == 0:
                    results['details'].append(f'{latest.name}: 备份行数为 0')
                    results['failed'] += 1
    except (zipfile.BadZipFile, OSError, json.JSONDecodeError) as e:
        results['details'].append(f'{latest.name}: ZIP 文件损坏 ({e})')
        results['failed'] += 1

    results['total'] = results['passed'] + results['failed']
    return results
