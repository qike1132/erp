"""恢复相关编排：从 ZIP 恢复、非依赖组件并行恢复、恢复锁管理。

P1-3(2026-08-23)：restore_from_zip 的还原内核切换为 DatabaseRestoreOrchestrator
（六边形接线），解密/校验和/策略选择/组件恢复/连接池重建/缓存失效/四层验证
不再于本模块重复实现。本模块保留：
- restore_non_dependent_components（内核组件适配器复用）
- 无数据库导出的组件-only 轻量路径（旧语义兼容）
- RestoreOutcome → 既有结果字典契约的映射
- Redis 分布式还原锁（fail-closed，端点层持有）
"""
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
from .exceptions import RestoreError
from .filestore import restore_config, restore_filestore
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


class _KernelProgressReporter:
    """内核 RestorePhase → 既有 Redis 进度阶段名的映射（P1-3 接线）。"""

    _PHASE_MAP = {
        'pre_restore_backup': 'pre_backup',
        'decrypt_archive': 'read_backup',
        'restore_database': 'restore_db',
        # 内核只有一个聚合组件阶段，映射到 10 阶段的首个子段（55%-90% 区间起推）
        'restore_components': 'restore_filestore',
        'rebuild_pool': 'rebuild_pool',
        'verify': 'verify',
    }

    def __init__(self, task_id: str) -> None:
        self._task_id = task_id

    async def report(self, phase, sub: float, detail: str = '') -> None:
        from fastapi_app.core.backup_progress import update_progress
        name = getattr(phase, 'value', phase)
        mapped = self._PHASE_MAP.get(str(name))
        if not mapped:
            return
        try:
            await update_progress(self._task_id, mapped, sub, detail)
        except Exception as e:  # broad-except: 进度上报失败不影响还原主流程
            logger.warning(f'内核进度上报失败: {e}')


async def restore_from_zip(
    zip_bytes: bytes,
    db: AsyncSession,
    decrypt_password: str | bytearray | None = None,
    task_id: str | None = None,
    confirm_sensitive: bool = False,
) -> dict:
    """从 ZIP 备份恢复全部数据（P1-3 起内核为 DatabaseRestoreOrchestrator）。

    - 端点层负责 Redis 还原锁与 pre-restore 安全备份，故内核的锁/安全备份
      注入 no-op 适配器（见 adapters.NoOp*）；
    - 明文 ZIP 且无数据库导出（组件-only 包）走保留的轻量路径；
      加密组件-only 包由内核按"未找到数据库导出"报错（当前产线不产出该形态）；
    - 返回字典保持旧契约（endpoints/前端依赖的键不变）。

    行为变化（有意为之）：manifest 中数据库文件的 checksum 不匹配时由
    "告警后继续"改为 fail-fast 报错——对校验和损坏的备份继续还原，
    等价于把半损坏数据静默写库。
    """
    async def _prog(phase: str, sub: float = 0.0, detail: str = ''):
        if task_id:
            from fastapi_app.core.backup_progress import update_progress
            await update_progress(task_id, phase, sub, detail)

    # 组件-only 包：明文 ZIP 且无 db dump → 保留轻量路径（含 confirm_sensitive 透传）
    try:
        probe = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except zipfile.BadZipFile:
        probe = None
    if probe is not None:
        names = probe.namelist()
        if 'database/dump.sql.gz' not in names and 'database/dump.json' not in names:
            return await _restore_components_only(probe, db, _prog, confirm_sensitive)
        probe.close()

    from .adapters import (
        ExistingCacheInvalidatorAdapter,
        ExistingComponentRestoreAdapter,
        ExistingEngineLifecycleAdapter,
        ExistingRestoreVerifierAdapter,
        NoOpAdvisoryLockAdapter,
        NoOpSafetyBackupAdapter,
    )
    from .orchestrator import DatabaseRestoreOrchestrator, StrategySelector
    from .strategies import JsonRestoreStrategy, PsqlRestoreStrategy

    orchestrator = DatabaseRestoreOrchestrator(
        lock=NoOpAdvisoryLockAdapter(),
        safety_backup_provider=NoOpSafetyBackupAdapter(),
        strategy_selector=StrategySelector(PsqlRestoreStrategy(), JsonRestoreStrategy()),
        engine_lifecycle=ExistingEngineLifecycleAdapter(),
        component_restore=ExistingComponentRestoreAdapter(),
        cache_invalidator=ExistingCacheInvalidatorAdapter(),
        verifier=ExistingRestoreVerifierAdapter(),
    )
    outcome = await orchestrator.restore(
        zip_bytes,
        decrypt_password=decrypt_password,
        confirm_sensitive=confirm_sensitive,
        reporter=_KernelProgressReporter(task_id) if task_id else None,
    )

    if outcome.database.status == 'error':
        raise RestoreError(f"数据库恢复失败: {outcome.database.message or outcome.message}")
    if outcome.status.value == 'error':
        raise RestoreError(outcome.message or '恢复过程中出错')

    manifest_dict = outcome.manifest or {}
    raw_db = outcome.database.details.get('raw') or {
        'status': outcome.database.status, 'message': outcome.database.message,
    }
    verification = {
        'overall_pass': outcome.verification.overall_pass,
        'l0_global_checksum': outcome.verification.l0_global_checksum,
        'l1_row_count': outcome.verification.l1_row_count,
        'l2_fingerprint': outcome.verification.l2_fingerprint,
        'l3_id_sampling': outcome.verification.l3_id_sampling,
        # extras 含 verify_restore 的其余层级（如 l4_ddl），避免接线丢层
        **outcome.verification.extras,
    }
    if outcome.verification.error:
        verification['error'] = outcome.verification.error
    results = {
        'version': manifest_dict.get('version'),
        'exported_at': manifest_dict.get('exported_at'),
        'exported_by': manifest_dict.get('exported_by'),
        'remark': manifest_dict.get('remark', ''),
        'database': raw_db,
        'filestore': dict(outcome.components.filestore),
        'config': dict(outcome.components.config),
        'redis': dict(outcome.components.redis),
        'meilisearch': dict(outcome.components.meilisearch),
        'errors': [*outcome.errors, *outcome.components.errors],
        'warnings': list(outcome.warnings),
        'verification': verification,
        '_manifest_tables': manifest_dict.get('tables', {}),
    }
    if not outcome.verification.overall_pass:
        results['_verification_failed'] = True
    return results


async def _restore_components_only(
    zf: zipfile.ZipFile,
    db: AsyncSession,
    _prog,
    confirm_sensitive: bool,
) -> dict:
    """无数据库导出的组件包：仅并行还原非依赖组件（保留旧语义）。"""
    if 'manifest.json' not in zf.namelist():
        raise RestoreError('备份文件缺少 manifest.json')
    manifest = json.loads(zf.read('manifest.json'))
    results = {
        'version': manifest.get('version'),
        'exported_at': manifest.get('exported_at'),
        'exported_by': manifest.get('exported_by'),
        'remark': manifest.get('remark', ''),
        'database': {}, 'filestore': {}, 'config': {}, 'redis': {}, 'meilisearch': {},
        'errors': [], 'warnings': ['备份文件中无数据库导出'],
        '_manifest_tables': manifest.get('tables', {}),
    }
    await _prog('restore_db', 1.0, '无数据库数据')

    components_result = await restore_non_dependent_components(zf, confirm_sensitive=confirm_sensitive)
    for key in ('filestore', 'config', 'redis', 'meilisearch'):
        if key in components_result:
            results[key] = components_result[key]
    if 'errors' in components_result:
        results['errors'].extend(components_result['errors'])
    await _prog('restore_components', 1.0, '组件恢复完成')

    await db.commit()  # manual-tx: 组件还原后提交
    try:
        from fastapi_app.core.cache import CacheDomain, invalidate_related_caches
        await invalidate_related_caches(CacheDomain.ALL)
    except (OSError, ValueError) as e:
        logger.warning(f'恢复后缓存清除失败: {e}')

    await _prog('verify', 0.0, '数据完整性验证中')
    try:
        verification = await verify_restore(
            db, manifest.get('tables', {}), manifest.get('fingerprints'),
        )
        results['verification'] = verification
        if not verification.get('overall_pass', True):
            results['_verification_failed'] = True
    except (SQLAlchemyError, ValueError, OSError) as e:
        logger.warning(f'恢复后验证失败: {e}')
        results['verification'] = {'overall_pass': False, 'error': str(e)}
    await _prog('verify', 1.0, '验证完成')
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
