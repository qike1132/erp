"""
备份相关 ARQ 定时任务

调用 backup_service 层函数，不再直接 import endpoint 模块。
改进功能：
1. 备份失败自动告警机制
2. 健康检查监控
3. 备份策略管理
4. 性能监控指标收集
5. 智能清理优化
6. 灾难恢复测试

ARQ 任务为原生 async，原先在 Celery 同步 worker 中用 _run_async 包装的协程，
现在直接 await。重试由 ARQ max_tries 控制（job_try < 3 时 raise 触发重试）。
"""
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

# ARQ 重试上限（对应 Celery max_retries=2 → 总尝试 3 次）
_MAX_TRIES = 3


async def _send_backup_alert(task_name: str, error: str, task_type: str = 'backup', severity: str = 'error', additional_info: dict = None):
    """发送备份告警"""
    try:
        from fastapi_app.services.backup_alert_service import alert_service
        await alert_service.send_alert(
            task_name=task_name,
            error=error,
            task_type=task_type,
            severity=severity,
            additional_info=additional_info
        )
    except Exception as e:  # defensive: alert logging must not crash the caller
        logger.error(f'发送备份告警失败: {e}')


async def _collect_backup_metrics(backup_type: str, start_time: datetime, end_time: datetime,
                                 backup_size: int, success: bool, error_message: str = None,
                                 additional_metrics: dict = None):
    """收集备份性能指标"""
    try:
        from fastapi_app.services.backup_metrics_service import metrics_service
        await metrics_service.collect_backup_metrics(
            backup_type=backup_type,
            start_time=start_time,
            end_time=end_time,
            backup_size=backup_size,
            success=success,
            error_message=error_message,
            additional_metrics=additional_metrics
        )
    except Exception as e:  # defensive: metrics collection must not crash the caller
        logger.error(f'收集备份指标失败: {e}')


async def auto_daily_backup_task(ctx):
    """每日自动全量备份（带告警和监控）"""
    job_try = ctx.get('job_try', 1)
    logger.info('开始执行每日自动全量备份...')
    start_time = datetime.now()

    try:
        # 使用指数退避重试机制
        from fastapi_app.services.backup_alert_service import alert_service
        success, result = await alert_service.retry_with_backoff(
            _do_auto_backup_with_metrics,
            'daily',
            task_name='auto_daily_backup'
        )

        if success:
            logger.info(f'每日自动备份完成: {result}')

            # 发送成功通知（如果配置了）
            import os
            if os.environ.get('BACKUP_NOTIFY_SUCCESS', 'false').lower() == 'true':
                await _send_backup_alert(
                    task_name='auto_daily_backup',
                    error=f'每日自动备份成功: {result.get("filename", "未知文件")}',
                    task_type='backup',
                    severity='info',
                    additional_info=result
                )

            return result
        else:
            error_msg = f'每日自动备份失败: {str(result)}'
            logger.error(error_msg)

            # 发送失败告警
            await _send_backup_alert(
                task_name='auto_daily_backup',
                error=error_msg,
                task_type='backup',
                severity='error',
                additional_info={
                    'start_time': start_time.isoformat(),
                    'end_time': datetime.now().isoformat(),
                    'retry_count': job_try - 1
                }
            )

            if job_try < _MAX_TRIES:
                raise result if isinstance(result, BaseException) else RuntimeError(str(result))
            return {'status': 'error', 'error': str(result)}

    except Exception as e:  # defensive: background task must log/alert failure instead of propagating
        error_msg = f'每日自动备份失败: {e}'
        logger.error(error_msg)

        # 发送异常告警
        await _send_backup_alert(
            task_name='auto_daily_backup',
            error=error_msg,
            task_type='backup',
            severity='error',
            additional_info={
                'start_time': start_time.isoformat(),
                'end_time': datetime.now().isoformat(),
                'retry_count': job_try - 1,
                'exception_type': type(e).__name__
            }
        )

        if job_try < _MAX_TRIES:
            raise e
        return {'status': 'error', 'error': str(e)}


async def _do_auto_backup_with_metrics(backup_type: str):
    """执行自动备份并收集指标"""
    start_time = datetime.now()

    try:
        result = await _do_auto_backup(backup_type)
        end_time = datetime.now()

        # 收集性能指标
        backup_size = result.get('size', 0)
        await _collect_backup_metrics(
            backup_type=backup_type,
            start_time=start_time,
            end_time=end_time,
            backup_size=backup_size,
            success=True,
            additional_metrics={
                'filename': result.get('filename'),
                'table_count': result.get('table_count'),
                'total_rows': result.get('total_rows')
            }
        )

        return result
    except Exception as e:  # defensive: collect failure metrics before re-raising
        end_time = datetime.now()

        # 收集失败指标
        await _collect_backup_metrics(
            backup_type=backup_type,
            start_time=start_time,
            end_time=end_time,
            backup_size=0,
            success=False,
            error_message=str(e)
        )

        raise e


async def auto_incremental_backup_task(ctx):
    """自动增量备份（带告警和监控）"""
    job_try = ctx.get('job_try', 1)
    logger.info('开始执行自动增量备份...')
    start_time = datetime.now()

    try:
        # 使用指数退避重试机制
        from fastapi_app.services.backup_alert_service import alert_service
        success, result = await alert_service.retry_with_backoff(
            _do_auto_backup_with_metrics,
            'incremental',
            task_name='auto_incremental_backup'
        )

        if success:
            logger.info(f'自动增量备份完成: {result}')

            # 发送成功通知（如果配置了）
            import os
            if os.environ.get('BACKUP_NOTIFY_SUCCESS', 'false').lower() == 'true':
                await _send_backup_alert(
                    task_name='auto_incremental_backup',
                    error=f'自动增量备份成功: {result.get("filename", "未知文件")}',
                    task_type='backup',
                    severity='info',
                    additional_info=result
                )

            return result
        else:
            error_msg = f'自动增量备份失败: {str(result)}'
            logger.error(error_msg)

            # 发送失败告警
            await _send_backup_alert(
                task_name='auto_incremental_backup',
                error=error_msg,
                task_type='backup',
                severity='error',
                additional_info={
                    'start_time': start_time.isoformat(),
                    'end_time': datetime.now().isoformat(),
                    'retry_count': job_try - 1
                }
            )

            if job_try < _MAX_TRIES:
                raise result if isinstance(result, BaseException) else RuntimeError(str(result))
            return {'status': 'error', 'error': str(result)}

    except Exception as e:  # defensive: background task must log/alert failure instead of propagating
        error_msg = f'自动增量备份失败: {e}'
        logger.error(error_msg)

        # 发送异常告警
        await _send_backup_alert(
            task_name='auto_incremental_backup',
            error=error_msg,
            task_type='backup',
            severity='error',
            additional_info={
                'start_time': start_time.isoformat(),
                'end_time': datetime.now().isoformat(),
                'retry_count': job_try - 1,
                'exception_type': type(e).__name__
            }
        )

        if job_try < _MAX_TRIES:
            raise e
        return {'status': 'error', 'error': str(e)}


async def backup_integrity_check_task(ctx):
    """备份完整性巡检（带告警）"""
    job_try = ctx.get('job_try', 1)
    logger.info('开始执行备份完整性巡检...')
    start_time = datetime.now()

    try:
        result = await _do_integrity_check()

        if result.get('failed', 0) > 0:
            warning_msg = f'备份完整性巡检发现 {result["failed"]} 个问题: {result.get("details", [])}'
            logger.warning(warning_msg)

            # 发送警告告警
            await _send_backup_alert(
                task_name='backup_integrity_check',
                error=warning_msg,
                task_type='integrity_check',
                severity='warning',
                additional_info=result
            )
        else:
            logger.info('备份完整性巡检通过')

        return result
    except Exception as e:  # defensive: background task must log/alert failure instead of propagating
        error_msg = f'备份完整性巡检失败: {e}'
        logger.error(error_msg)

        # 发送错误告警
        await _send_backup_alert(
            task_name='backup_integrity_check',
            error=error_msg,
            task_type='integrity_check',
            severity='warning',
            additional_info={
                'start_time': start_time.isoformat(),
                'end_time': datetime.now().isoformat()
            }
        )

        if job_try < _MAX_TRIES:
            raise e
        return {'status': 'error', 'error': str(e)}


async def backup_cleanup_task(ctx):
    """备份清理任务（智能清理）"""
    job_try = ctx.get('job_try', 1)
    logger.info('开始执行备份智能清理...')
    start_time = datetime.now()

    try:
        from fastapi_app.services.backup_cleanup_service import cleanup_service
        result = await cleanup_service.smart_cleanup()

        if result.get('success'):
            deleted_count = result.get('cleanup_result', {}).get('deleted_count', 0)
            kept_count = result.get('summary', {}).get('kept_files', 0)
            logger.info(f'备份智能清理完成: 删除 {deleted_count} 个文件，保留 {kept_count} 个文件')

            # 如果有文件被删除，发送通知
            if deleted_count > 0:
                await _send_backup_alert(
                    task_name='backup_cleanup',
                    error=f'备份清理完成，删除 {deleted_count} 个文件，保留 {kept_count} 个文件',
                    task_type='cleanup',
                    severity='info',
                    additional_info=result
                )
        else:
            error_msg = f'备份智能清理失败: {result.get("error", "未知错误")}'
            logger.error(error_msg)

            # 发送错误告警
            await _send_backup_alert(
                task_name='backup_cleanup',
                error=error_msg,
                task_type='cleanup',
                severity='error',
                additional_info={
                    'start_time': start_time.isoformat(),
                    'end_time': datetime.now().isoformat()
                }
            )

        return result
    except Exception as e:  # defensive: background task must log/alert failure instead of propagating
        error_msg = f'备份智能清理失败: {e}'
        logger.error(error_msg)

        # 发送异常告警
        await _send_backup_alert(
            task_name='backup_cleanup',
            error=error_msg,
            task_type='cleanup',
            severity='error',
            additional_info={
                'start_time': start_time.isoformat(),
                'end_time': datetime.now().isoformat()
            }
        )

        if job_try < _MAX_TRIES:
            raise e
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
         and (f.name.endswith('.zip') or f.name.endswith('.zip.enc'))],
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

    # 加密备份无法直接校验内容，仅检查文件存在和大小
    if latest.name.endswith('.enc'):
        if latest.stat().st_size < 100:
            results['details'].append(f'{latest.name}: 加密备份文件过小，可能损坏')
            results['failed'] += 1
        else:
            results['passed'] += 1
            results['details'].append(f'{latest.name}: 加密备份，内容校验需解密后进行')
    else:
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


async def backup_health_check_task(ctx):
    """备份健康检查任务"""
    job_try = ctx.get('job_try', 1)
    logger.info('开始执行备份健康检查...')
    start_time = datetime.now()

    try:
        from fastapi_app.services.backup_health_check_service import health_check_service
        result = await health_check_service.perform_health_check()

        if result.get('overall_status') != 'healthy':
            issues = result.get('issues', [])
            warning_msg = f'备份健康检查发现问题: {issues}'
            logger.warning(warning_msg)

            # 发送警告告警
            severity = 'error' if result.get('overall_status') == 'error' else 'warning'
            await _send_backup_alert(
                task_name='backup_health_check',
                error=warning_msg,
                task_type='health_check',
                severity=severity,
                additional_info=result
            )
        else:
            logger.info(f'备份健康检查完成: {result.get("overall_status")}')

        return result
    except Exception as e:  # defensive: background task must log/alert failure instead of propagating
        error_msg = f'备份健康检查失败: {e}'
        logger.error(error_msg)

        # 发送错误告警
        await _send_backup_alert(
            task_name='backup_health_check',
            error=error_msg,
            task_type='health_check',
            severity='error',
            additional_info={
                'start_time': start_time.isoformat(),
                'end_time': datetime.now().isoformat()
            }
        )

        if job_try < _MAX_TRIES:
            raise e
        return {'status': 'error', 'error': str(e)}


async def apply_backup_policy_task(ctx):
    """应用备份策略任务"""
    job_try = ctx.get('job_try', 1)
    logger.info('开始应用备份策略...')
    start_time = datetime.now()

    try:
        from fastapi_app.services.backup_policy_service import policy_service
        result = await policy_service.apply_backup_policy()

        if result.get('success'):
            logger.info(f'备份策略应用成功: {result.get("message")}')

            # 发送成功通知
            await _send_backup_alert(
                task_name='apply_backup_policy',
                error=f'备份策略应用成功: {result.get("message")}',
                task_type='policy',
                severity='info',
                additional_info=result
            )
        else:
            error_msg = f'备份策略应用失败: {result.get("error")}'
            logger.error(error_msg)

            # 发送错误告警
            await _send_backup_alert(
                task_name='apply_backup_policy',
                error=error_msg,
                task_type='policy',
                severity='error',
                additional_info={
                    'start_time': start_time.isoformat(),
                    'end_time': datetime.now().isoformat()
                }
            )

        return result
    except Exception as e:  # defensive: background task must log/alert failure instead of propagating
        error_msg = f'应用备份策略失败: {e}'
        logger.error(error_msg)

        # 发送异常告警
        await _send_backup_alert(
            task_name='apply_backup_policy',
            error=error_msg,
            task_type='policy',
            severity='error',
            additional_info={
                'start_time': start_time.isoformat(),
                'end_time': datetime.now().isoformat()
            }
        )

        if job_try < _MAX_TRIES:
            raise e
        return {'status': 'error', 'error': str(e)}


async def disaster_recovery_test_task(ctx):
    """灾难恢复测试任务"""
    job_try = ctx.get('job_try', 1)
    logger.info('开始执行灾难恢复测试...')
    start_time = datetime.now()

    try:
        from fastapi_app.services.backup_recovery_test_service import recovery_test_service
        result = await recovery_test_service.perform_recovery_test()

        if result.get('overall_success'):
            logger.info(f'灾难恢复测试成功: {result.get("summary", {})}')

            # 发送成功通知
            await _send_backup_alert(
                task_name='disaster_recovery_test',
                error=f'灾难恢复测试成功: 测试ID {result.get("test_id", "未知")}',
                task_type='recovery_test',
                severity='info',
                additional_info=result
            )
        else:
            error_msg = f'灾难恢复测试失败: {result.get("error", "未知错误")}'
            logger.error(error_msg)

            # 发送错误告警
            await _send_backup_alert(
                task_name='disaster_recovery_test',
                error=error_msg,
                task_type='recovery_test',
                severity='error',
                additional_info={
                    'start_time': start_time.isoformat(),
                    'end_time': datetime.now().isoformat(),
                    'test_id': result.get('test_id', '未知')
                }
            )

        return result
    except Exception as e:  # defensive: background task must log/alert failure instead of propagating
        error_msg = f'灾难恢复测试失败: {e}'
        logger.error(error_msg)

        # 发送错误告警
        await _send_backup_alert(
            task_name='disaster_recovery_test',
            error=error_msg,
            task_type='recovery_test',
            severity='error',
            additional_info={
                'start_time': start_time.isoformat(),
                'end_time': datetime.now().isoformat()
            }
        )

        if job_try < _MAX_TRIES:
            raise e
        return {'status': 'error', 'error': str(e)}


async def backup_metrics_report_task(ctx):
    """备份性能指标报告任务"""
    job_try = ctx.get('job_try', 1)
    logger.info('开始生成备份性能指标报告...')
    start_time = datetime.now()

    try:
        from fastapi_app.services.backup_metrics_service import metrics_service
        result = await metrics_service.export_metrics_report(days=7, format='json')

        if 'error' not in result:
            logger.info('备份性能指标报告生成成功')

            # 检查性能告警
            alerts = await metrics_service.get_performance_alerts()
            if alerts:
                for alert in alerts:
                    await _send_backup_alert(
                        task_name='backup_metrics',
                        error=alert['message'],
                        task_type='metrics',
                        severity=alert['severity'],
                        additional_info=alert
                    )
        else:
            error_msg = f'备份性能指标报告生成失败: {result.get("error")}'
            logger.error(error_msg)

            # 发送错误告警
            await _send_backup_alert(
                task_name='backup_metrics_report',
                error=error_msg,
                task_type='metrics',
                severity='error',
                additional_info={
                    'start_time': start_time.isoformat(),
                    'end_time': datetime.now().isoformat()
                }
            )

        return result
    except Exception as e:  # defensive: background task must log/alert failure instead of propagating
        error_msg = f'备份性能指标报告生成失败: {e}'
        logger.error(error_msg)

        # 发送告警
        await _send_backup_alert(
            task_name='backup_metrics_report',
            error=error_msg,
            task_type='metrics',
            severity='warning',
            additional_info={
                'start_time': start_time.isoformat(),
                'end_time': datetime.now().isoformat()
            }
        )

        if job_try < _MAX_TRIES:
            raise e
        return {'status': 'error', 'error': str(e)}
