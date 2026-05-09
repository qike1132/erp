import asyncio
import hashlib
import json
import logging
import zipfile
from datetime import datetime
from pathlib import Path

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(name='auto_daily_backup_task', queue='batch', time_limit=1800)
def auto_daily_backup_task():
    logger.info('开始执行每日自动全量备份...')
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(_do_auto_backup('daily'))
        loop.close()
        logger.info(f'每日自动备份完成: {result}')
        return result
    except Exception as e:
        logger.error(f'每日自动备份失败: {e}')
        return {'status': 'error', 'error': str(e)}


@shared_task(name='auto_incremental_backup_task', queue='batch', time_limit=600)
def auto_incremental_backup_task():
    logger.info('开始执行自动增量备份...')
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(_do_auto_backup('incremental'))
        loop.close()
        logger.info(f'自动增量备份完成: {result}')
        return result
    except Exception as e:
        logger.error(f'自动增量备份失败: {e}')
        return {'status': 'error', 'error': str(e)}


@shared_task(name='backup_integrity_check_task', queue='batch', time_limit=600)
def backup_integrity_check_task():
    logger.info('开始执行备份完整性巡检...')
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(_do_integrity_check())
        loop.close()
        if result.get('failed', 0) > 0:
            logger.warning(f'备份完整性巡检发现 {result["failed"]} 个问题: {result.get("details", [])}')
        else:
            logger.info('备份完整性巡检通过')
        return result
    except Exception as e:
        logger.error(f'备份完整性巡检失败: {e}')
        return {'status': 'error', 'error': str(e)}


async def _do_auto_backup(backup_type: str) -> dict:
    from fastapi_app.core.database import get_async_db_context
    from fastapi_app.shared_models import User as UserModel
    from fastapi_app.api.v1.endpoints.backup import (
        BACKUP_DIR,
        _ensure_backup_dir,
        _execute_backup_to_zip,
    )
    _ensure_backup_dir()
    async with get_async_db_context() as db:
        if backup_type == 'daily':
            dummy_user = UserModel()
            dummy_user.username = 'system_auto'
            dummy_user.id = 0
            zip_bytes, manifest = await _execute_backup_to_zip(dummy_user, '每日自动全量备份', db)
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f'erp_auto_daily_{timestamp}.zip'
            filepath = BACKUP_DIR / filename
            filepath.write_bytes(zip_bytes)
            return {'status': 'ok', 'type': 'daily', 'filename': filename, 'size': len(zip_bytes), 'table_count': manifest.get('table_count'), 'total_rows': manifest.get('total_rows')}
        else:
            from fastapi_app.api.v1.endpoints.backup import _query_table_rows, _find_last_backup_timestamp, _TIMESTAMP_CANDIDATES, BACKUP_FORMAT_VERSION, _sha256_file
            from fastapi_app.shared_models import Base
            effective_since = await _find_last_backup_timestamp() or ''
            incremental_tables = {}
            total_rows = 0
            for table in Base.metadata.sorted_tables:
                tname = str(table.name)
                try:
                    serialized_rows = await _query_table_rows(tname, db, effective_since or None)
                    if serialized_rows:
                        columns = list(serialized_rows[0].keys())
                        incremental_tables[tname] = {'columns': columns, 'rows': serialized_rows, 'count': len(serialized_rows)}
                        total_rows += len(serialized_rows)
                except Exception as e:
                    logger.warning(f'自动增量备份表 {tname} 失败: {e}')
            if not incremental_tables:
                return {'status': 'ok', 'type': 'incremental', 'message': '无变更数据'}
            import tempfile
            from pathlib import Path
            import zipfile
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            with tempfile.TemporaryDirectory(prefix='erp_auto_inc_') as tmpdir:
                tmpdir_path = Path(tmpdir)
                json_path = tmpdir_path / 'database' / 'dump.json'
                json_path.parent.mkdir(parents=True, exist_ok=True)
                backup_data = {
                    'version': BACKUP_FORMAT_VERSION,
                    'type': 'incremental',
                    'exported_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'exported_by': 'system_auto',
                    'remark': '自动增量备份',
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
                        'exported_by': 'system_auto',
                        'remark': '自动增量备份',
                        'base_timestamp': effective_since,
                        'table_count': len(incremental_tables),
                        'total_rows': total_rows,
                        'includes': {},
                        'checksums': {'database/dump.json': _sha256_file(json_path)},
                    }
                    zf.writestr('manifest.json', json.dumps(manifest, ensure_ascii=False, indent=2).encode('utf-8'))
                zip_bytes = zip_path.read_bytes()
            filename = f'erp_auto_incremental_{timestamp}.zip'
            filepath = BACKUP_DIR / filename
            filepath.write_bytes(zip_bytes)
            result = {'success': True, 'filename': filename, 'size': len(zip_bytes), 'table_count': len(incremental_tables), 'total_rows': total_rows}
            return {'status': 'ok', 'type': 'incremental', 'result': result}


async def _do_integrity_check() -> dict:
    from fastapi_app.api.v1.endpoints.backup import BACKUP_DIR
    results = {'checked_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'), 'total': 0, 'passed': 0, 'failed': 0, 'details': []}
    if not BACKUP_DIR.exists():
        results['details'].append('备份目录不存在')
        results['failed'] += 1
        return results
    backup_files = sorted(
        [f for f in BACKUP_DIR.iterdir() if f.is_file() and (f.name.startswith('erp_backup_') or f.name.startswith('erp_auto_') or f.name.startswith('erp_incremental_')) and f.name.endswith('.zip')],
        key=lambda f: f.stat().st_mtime,
        reverse=True
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
