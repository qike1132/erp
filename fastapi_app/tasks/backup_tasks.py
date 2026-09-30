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
import asyncio
import logging
from datetime import UTC, datetime

from fastapi_app.core.backup_progress import (
    complete_progress,
    create_progress,
    fail_progress,
    generate_task_id,
    update_progress,
)

logger = logging.getLogger(__name__)

# ARQ 重试上限（对应 Celery max_retries=2 → 总尝试 3 次）
_MAX_TRIES = 3


async def manual_full_backup_task(
    ctx, *, task_id: str | None = None, remark: str = '', encrypt: bool = True,
    tables: list[str] | None = None,
    exclude_tables: list[str] | None = None,
):
    """手动全量备份（ARQ 异步任务，M1 新增；P1-2 起支持表级范围）。

    由 POST /api/v1/backup/full 入队触发；写 Redis 进度(8 阶段)，
    完成后落 backup_record(trigger_type='manual', encrypted 反映实际加密)。
    任务名在 WorkerSettings.functions 注册，与自动备份共用 _do_auto_backup 骨架。

    注意:task_id 由入口端点生成并传入(与前端 POST /full 返回的 task_id 一致),
    任务不再自行生成,否则前端轮询 GET /progress/{task_id} 将取不到进度。

    H3: 加密密码不作为任务参数入队（ARQ 参数会被序列化进 Redis 队列明文可见），
    入口端点将其写入一次性短 TTL 侧信道键，此处按 task_id 原子取走。
    """
    task_id = task_id or generate_task_id()
    await create_progress(task_id, operation_type='full', progress_type='backup')
    job_try = ctx.get('job_try', 1)
    start_time = datetime.now()
    operator = 'manual_user'

    try:
        await update_progress(task_id, 'init', 0.1, '开始全量备份')
        from fastapi_app.core.backup_progress import get_task_password
        from fastapi_app.core.database import get_async_db_context
        from fastapi_app.services import backup as backup_service
        from fastapi_app.shared_models import User as UserModel

        backup_service.ensure_backup_dir()
        # 读取入口端点预置的密码（短 TTL 键，重试期间仍可读，到期自动回收）
        password = await get_task_password(task_id)

        async with get_async_db_context() as db:
            dummy_user = UserModel()
            dummy_user.username = operator
            dummy_user.id = 0

            # 加密 fail-safe:与端点 _resolve_encryption 一致——
            # 请求加密但未配置任何密码(参数/头/环境变量)时,降级为不加密,禁止随机密钥回退
            if not encrypt:
                effective_password = None
            else:
                effective_password = password or backup_service.BACKUP_ENCRYPTION_PASSWORD or None
                if not effective_password:
                    logger.warning(
                        '请求加密全量备份但未配置密码（参数/环境变量均无），本次备份将以未加密形式保存'
                    )
            await update_progress(task_id, 'export_db', 0.1, '导出数据库')

            async def _svc_progress(phase: str, sub: float, detail: str):
                # P2-2: 服务层 8 阶段进度透传到 Redis（此前任务只报 3 个阶段）
                await update_progress(task_id, phase, sub, detail)

            zip_bytes, manifest = await backup_service.create_full_backup(
                db, dummy_user, remark or '手动全量备份',
                encrypt_password=effective_password,
                encrypt=bool(effective_password),
                tables=tables,
                exclude_tables=exclude_tables,
                progress_cb=_svc_progress,
            )
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            # P0-1: 加密备份扩展名带 .enc；P0-4: 同步写 .meta sidecar
            filename = (
                f'erp_backup_{timestamp}.zip.enc' if manifest.get('encrypted')
                else f'erp_backup_{timestamp}.zip'
            )
            filepath = backup_service.BACKUP_DIR / filename

            await update_progress(task_id, 'write_file', 0.5, f'写入 {filename}')
            # H5: 大文件写盘为阻塞 IO，移入线程池避免卡住事件循环
            await asyncio.to_thread(filepath.write_bytes, zip_bytes)
            backup_service.write_backup_meta_file(filepath, manifest, record_type='full')

            # 写入 BackupRecord
            # S4：状态由产物自述推导（缺表/覆盖度不足 → partial），不再默认成功
            full_status, full_detail = backup_service.evaluate_backup_completeness(manifest)
            await backup_service.write_backup_record(
                db, record_type='full', trigger_type='manual',
                filename=filename, size=len(zip_bytes),
                table_count=manifest.get('table_count'),
                total_rows=manifest.get('total_rows'),
                operator=operator,
                remark=backup_service.compose_remark(remark or '手动全量备份', full_detail),
                status=full_status,
                encrypted=manifest.get('encrypted', False),
                manifest_summary={
                    'checksums': manifest.get('checksums'),
                    'schema_snapshot': manifest.get('schema_snapshot'),
                    'coverage': manifest.get('coverage'),
                },
            )

        result = {
            'status': 'ok' if full_status == backup_service.STATUS_SUCCESS else 'partial',
            'backup_status': full_status,
            'type': 'full', 'filename': filename,
            'size': len(zip_bytes),
            'table_count': manifest.get('table_count'),
            'total_rows': manifest.get('total_rows'),
            'failed_tables': manifest.get('failed_tables') or [],
        }
        await complete_progress(task_id, result=result)
        logger.info(f'手动全量备份完成: {filename}')
        return result

    except Exception as e:  # defensive: background task must log/alert failure instead of propagating
        error_msg = f'手动全量备份失败: {e}'
        logger.error(error_msg)
        await fail_progress(task_id, error=str(e))
        await _send_backup_alert(
            task_name='manual_full_backup',
            error=error_msg,
            task_type='backup',
            severity='error',
            additional_info={
                'start_time': start_time.isoformat(),
                'end_time': datetime.now().isoformat(),
                'retry_count': job_try - 1,
                'exception_type': type(e).__name__,
            },
        )
        if job_try < _MAX_TRIES:
            raise e
        return {'status': 'error', 'error': str(e)}


async def manual_incremental_backup_task(ctx, *, task_id: str | None = None, remark: str = '', since: str = ''):
    """手动增量备份（ARQ 异步任务，M1 新增）。

    由 POST /api/v1/backup/incremental 入队触发；写 Redis 进度，
    完成后落 backup_record(trigger_type='manual', record_type='incremental')。

    注意:task_id 由入口端点生成并传入(与前端 POST /incremental 返回的 task_id 一致)。
    """
    task_id = task_id or generate_task_id()
    await create_progress(task_id, operation_type='incremental', progress_type='backup')
    job_try = ctx.get('job_try', 1)
    start_time = datetime.now()
    operator = 'manual_user'

    try:
        await update_progress(task_id, 'init', 0.1, '开始增量备份')
        from fastapi_app.core.database import get_async_db_context
        from fastapi_app.services import backup as backup_service
        from fastapi_app.shared_models import User as UserModel

        backup_service.ensure_backup_dir()

        async with get_async_db_context() as db:
            dummy_user = UserModel()
            dummy_user.username = operator
            dummy_user.id = 0

            await update_progress(task_id, 'export_db', 0.2, '扫描增量变更')
            result = await backup_service.create_incremental_backup(
                db, dummy_user, remark or '手动增量备份', since,
                encrypt=False,  # 手动增量不隐式加密(fail-safe,避免随机密钥)
            )

            # S4：增量缺表信号由 create_incremental_backup 的 failed_tables 承载，
            # 过去该信号被丢弃，导致「静默漏表」的备份照样记 success。
            inc_status, inc_detail = backup_service.STATUS_SUCCESS, ''
            if result.get('filename'):
                await update_progress(task_id, 'write_file', 0.9, f'写入 {result["filename"]}')
                inc_status, inc_detail = backup_service.evaluate_backup_completeness(result)
                await backup_service.write_backup_record(
                    db, record_type='incremental', trigger_type='manual',
                    filename=result['filename'], size=result.get('size'),
                    table_count=result.get('table_count'),
                    total_rows=result.get('total_rows'),
                    operator=operator,
                    remark=backup_service.compose_remark(remark or '手动增量备份', inc_detail),
                    status=inc_status,
                    encrypted=result.get('encrypted', False),
                    manifest_summary={
                        'base_timestamp': result.get('base_timestamp'),
                        'checksums': result.get('checksums'),
                        'failed_tables': result.get('failed_tables') or [],
                    },
                )
            else:
                logger.info('手动增量备份: 无变更数据')

        result_out = {
            'status': 'ok' if inc_status == backup_service.STATUS_SUCCESS else 'partial',
            'backup_status': inc_status,
            'type': 'incremental',
            'result': result,
            'failed_tables': result.get('failed_tables') or [],
        }
        await complete_progress(task_id, result=result_out)
        logger.info(f'手动增量备份完成: {result}')
        return result_out

    except Exception as e:  # defensive: background task must log/alert failure instead of propagating
        error_msg = f'手动增量备份失败: {e}'
        logger.error(error_msg)
        await fail_progress(task_id, error=str(e))
        await _send_backup_alert(
            task_name='manual_incremental_backup',
            error=error_msg,
            task_type='backup',
            severity='error',
            additional_info={
                'start_time': start_time.isoformat(),
                'end_time': datetime.now().isoformat(),
                'retry_count': job_try - 1,
                'exception_type': type(e).__name__,
            },
        )
        if job_try < _MAX_TRIES:
            raise e
        return {'status': 'error', 'error': str(e)}


async def _send_backup_alert(task_name: str, error: str, task_type: str = 'backup', severity: str = 'error', additional_info: dict | None = None):
    """发送备份告警"""
    try:
        from fastapi_app.services.backup.metrics.alert_service import alert_service
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
                                 backup_size: int, success: bool, error_message: str | None = None,
                                 additional_metrics: dict | None = None):
    """收集备份性能指标"""
    try:
        from fastapi_app.services.backup.metrics.service import metrics_service
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


async def scheduler_poller(ctx):
    """扫描 backup_schedule 表，把到期任务入队（M2）。

    每 5 分钟由 ARQ cron 触发；命中「enabled 且 cron 匹配当前分钟且未在本小时窗口
    执行过」的调度，按 task_type 映射到 auto_* 任务函数入队并更新 last_run_at/status。
    幂等：last_run_at 按小时窗口判断；跨进程唯一性由目标任务内部既有 advisory lock 兜底。
    """
    try:
        from fastapi_app.core.arq_app import get_arq_pool
        from fastapi_app.core.database import get_async_db_context
        from fastapi_app.core.schedule_status import schedule_job_id
        from fastapi_app.services.backup import schedule_service

        now = datetime.now()
        async with get_async_db_context() as db:
            due = await schedule_service.due_schedules(db, now)
            if not due:
                return
            pool = await get_arq_pool()
            for sch in due:
                func_name = schedule_service.TASK_TYPE_TO_FUNC.get(sch.task_type)
                if not func_name:
                    logger.warning('调度任务 id=%s 类型 %s 无映射任务函数，跳过', sch.id, sch.task_type)
                    continue
                # 带上可解析的 job id：任务结束/失败的 ARQ 回调据此把 last_status 落成
                # 终态（否则它会永远停在 'running'）；同时借 ARQ 的同名 job 去重拿到原子
                # 版本的「本小时窗口只跑一次」。
                job = await pool.enqueue_job(func_name, _job_id=schedule_job_id(sch.id, now))
                if job is None:
                    logger.info('调度任务已在本小时窗口入队，跳过重复入队 schedule_id=%s', sch.id)
                    continue
                # last_run_at 写入 aware UTC：避免 naive 本地时间写 timestamptz 列读回后时区错位
                sch.last_run_at = datetime.now(UTC)
                sch.last_status = 'running'
                await db.commit()
                logger.info('调度入队 schedule_id=%s name=%s -> %s', sch.id, sch.name, func_name)
    except Exception as e:  # defensive: 调度轮询不得中断 worker
        logger.error('调度轮询失败: %s', e)


async def auto_daily_backup_task(ctx):
    """每日自动全量备份（带告警和监控）"""
    job_try = ctx.get('job_try', 1)
    logger.info('开始执行每日自动全量备份...')
    start_time = datetime.now()

    try:
        # 使用指数退避重试机制
        from fastapi_app.services.backup.metrics.alert_service import alert_service
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
            error_msg = f'每日自动备份失败: {result!s}'
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
        from fastapi_app.services.backup.metrics.alert_service import alert_service
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
            error_msg = f'自动增量备份失败: {result!s}'
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
        from fastapi_app.services.backup.cleanup.service import cleanup_service
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
    from fastapi_app.services import backup as backup_service
    from fastapi_app.shared_models import User as UserModel

    backup_service.ensure_backup_dir()

    async with get_async_db_context() as db:
        dummy_user = UserModel()
        dummy_user.username = 'system_auto'
        dummy_user.id = 0

        if backup_type == 'daily':
            # P0-1: 自动备份加密决策显式化——仅环境变量配置了密码才加密，
            # 绝不随机回退（旧路径在无密码时会用一次性随机密钥，产出不可还原备份）
            auto_password = backup_service.BACKUP_ENCRYPTION_PASSWORD or None
            if not auto_password:
                logger.info('自动全量备份未配置 BACKUP_ENCRYPTION_PASSWORD，本次备份不加密')
            zip_bytes, manifest = await backup_service.create_full_backup(
                db, dummy_user, '每日自动全量备份',
                encrypt_password=auto_password,
                encrypt=bool(auto_password),
            )
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = (
                f'erp_auto_daily_{timestamp}.zip.enc' if manifest.get('encrypted')
                else f'erp_auto_daily_{timestamp}.zip'
            )
            filepath = backup_service.BACKUP_DIR / filename
            # H5: 大文件写盘为阻塞 IO，移入线程池避免卡住事件循环
            await asyncio.to_thread(filepath.write_bytes, zip_bytes)
            backup_service.write_backup_meta_file(filepath, manifest, record_type='full')

            # 写入 BackupRecord
            # S4：状态由产物自述推导，不再无条件 'success'
            auto_status, auto_detail = backup_service.evaluate_backup_completeness(manifest)
            await backup_service.write_backup_record(
                db, record_type='full', trigger_type='auto',
                filename=filename, size=len(zip_bytes),
                table_count=manifest.get('table_count'),
                total_rows=manifest.get('total_rows'),
                operator='system_auto',
                remark=backup_service.compose_remark('每日自动全量备份', auto_detail),
                status=auto_status,
                encrypted=manifest.get('encrypted', False),
            )
            return {
                'status': 'ok' if auto_status == backup_service.STATUS_SUCCESS else 'partial',
                'backup_status': auto_status,
                'type': 'daily', 'filename': filename,
                'size': len(zip_bytes),
                'table_count': manifest.get('table_count'),
                'total_rows': manifest.get('total_rows'),
                'failed_tables': manifest.get('failed_tables') or [],
            }
        else:
            result = await backup_service.create_incremental_backup(db, dummy_user, '自动增量备份')
            # S4：增量缺表（failed_tables）必须落到记录状态上
            inc_status, inc_detail = backup_service.STATUS_SUCCESS, ''
            if result.get('filename'):
                inc_status, inc_detail = backup_service.evaluate_backup_completeness(result)
                await backup_service.write_backup_record(
                    db, record_type='incremental', trigger_type='auto',
                    filename=result['filename'], size=result.get('size'),
                    table_count=result.get('table_count'),
                    total_rows=result.get('total_rows'),
                    operator='system_auto',
                    remark=backup_service.compose_remark('自动增量备份', inc_detail),
                    status=inc_status,
                )
            return {
                'status': 'ok' if inc_status == backup_service.STATUS_SUCCESS else 'partial',
                'backup_status': inc_status,
                'type': 'incremental',
                'result': result,
                'failed_tables': result.get('failed_tables') or [],
            }


async def _do_integrity_check() -> dict:
    """执行备份完整性巡检"""
    import hashlib
    import json
    import zipfile

    from fastapi_app.services import backup as backup_service

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
        from fastapi_app.services.backup.verify.health_check_service import health_check_service
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
        from fastapi_app.services.backup.orchestration.policy_service import policy_service
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
        from fastapi_app.services.backup.orchestration.recovery_test_service import recovery_test_service
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
        from fastapi_app.services.backup.metrics.service import metrics_service
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
