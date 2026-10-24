"""高层编排 + 锁管理。"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from .._constants import (
    _CHECKSUM_EXCLUDE_TABLES,
    BACKUP_FORMAT_VERSION,
    BACKUP_LOCK_ID,
    BACKUP_OPERATION_TIMEOUT,
    MEILI_HOST,
    MEILI_MASTER_KEY,
    PRE_RESTORE_DIR,
    REDIS_DUMP,
    UPLOADS_DIR,
    _backup_in_progress,
    config_files_to_package,
)
from ..crypto import sha256_file
from ..dump import run_pg_dump
from ..exceptions import (
    BackupError,
    BackupLockError,
    DatabaseSnapshotError,
)
from ..filestore import should_exclude_file
from ..json_backup import execute_legacy_backup_to_bytes
from ..records import cleanup_pre_restore_backups, ensure_pre_restore_dir
from ..snapshot import get_postgres_snapshot
from ..verify import get_checksum_tables, quote_table

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


def resolve_backup_table_scope(
    tables: list[str] | None,
    exclude_tables: list[str] | None,
) -> tuple[set[str] | None, set[str] | None]:
    """校验并归一化表级备份范围（P1-2，对标 Frappe include/exclude doctypes）。

    返回 (include_set | None, exclude_set | None)；非法组合或未知表名抛 BackupError。
    """
    if tables and exclude_tables:
        raise BackupError('tables 与 exclude_tables 不能同时指定')
    if not tables and not exclude_tables:
        return None, None
    from fastapi_app.shared_models import Base
    known = {str(t.name) for t in Base.metadata.sorted_tables}
    if tables:
        unknown = sorted(set(tables) - known)
        if unknown:
            raise BackupError(f'未知的表名: {", ".join(unknown)}（仅允许 ORM 已定义的表）')
        return set(tables), None
    unknown = sorted(set(exclude_tables or []) - known)
    if unknown:
        raise BackupError(f'未知的表名: {", ".join(unknown)}（仅允许 ORM 已定义的表）')
    return None, set(exclude_tables or [])


def pack_config_files(zf: zipfile.ZipFile, include_sensitive_config: bool) -> tuple[list[str], list[str]]:
    """把配置清单写进备份包，返回 (已打包的归档名, 被排除的归档名)。

    归档名取自 _constants.config_files_to_package()，**自带命名空间**（config/ 或
    root/）。P0-2 修复：此前这里无条件拼 'config/'，把运行时 .env 打成
    config/root/.env —— 还原时命中 config/ 前缀，落到 CONFIG_DIR/root/.env 幽灵
    目录，而项目根的 .env 永远不被还原；该条目名也不在敏感白名单里，明文还原可
    绕过 confirm_sensitive 闸门。

    include_sensitive_config：本次备份是否加密。True 才打包敏感配置（jwt 私钥、
    运行时 .env）；明文包一律排除，并记入被排除清单（manifest.includes.config_files_excluded）。
    """
    added: list[str] = []
    excluded: list[str] = []
    for file_path, archive_path in config_files_to_package():
        if not file_path.is_file():
            continue
        if should_exclude_file(file_path, archive_path, include_sensitive_config):
            excluded.append(archive_path)
            logger.info(f"排除配置文件: {archive_path}")
        else:
            zf.write(file_path, archive_path)
            added.append(archive_path)
    return added, excluded


def record_config_includes(
    manifest: dict,
    config_files_added: list[str],
    config_files_excluded: list[str],
    include_sensitive_config: bool,
) -> None:
    """把配置打包结果写进 manifest['includes']（被排除项必须留痕）。

    明文包不带敏感配置（含 root/.env），只在 manifest 里留 config_files_excluded ——
    这是事后审计「这次备份到底缺了什么」的唯一依据，也是还原前的提示来源。
    """
    manifest['includes']['config_files'] = config_files_added
    if config_files_excluded:
        manifest['includes']['config_files_excluded'] = config_files_excluded
    manifest['includes']['sensitive_config_included'] = include_sensitive_config


async def create_full_backup(
    db: AsyncSession,
    user,
    remark: str,
    encrypt_password: str | bytearray | None = None,
    use_snapshot: bool = True,
    encrypt: bool | None = None,
    tables: list[str] | None = None,
    exclude_tables: list[str] | None = None,
    progress_cb=None,
    skip_restore_check: bool = False,
) -> tuple[bytes, dict]:
    """执行全量备份并返回 (zip_bytes, manifest_dict)。

    tables / exclude_tables（P1-2）：表级备份范围，二选一；
    指定后固定走 JSON 路径（还原时按表 upsert，不整库重建）。
    progress_cb（P2-2）：可选异步回调 (phase, sub, detail)，用于任务层上报
    8 阶段进度（导出/附件/配置/Redis/索引/校验和）。
    skip_restore_check：True 时跳过「还原进行中」互斥检查。仅用于恢复前
    安全备份（create_pre_restore_backup）——该场景下还原锁已由调用方持有，
    若再走 is_restore_in_progress() 检查会必然抛错、导致安全备份静默失败。
    """
    if _backup_in_progress.locked():
        raise BackupLockError('已有备份任务正在执行中，请稍后重试')

    # B4 修复：备份与还原互斥——还原期间拒绝启动备份。全量 psql 还原会
    # pg_terminate_backend 杀掉正在运行的 pg_dump；反向场景下还原中表的
    # DROP/重建也会让备份产出部分表缺失的损坏包。
    # 例外：恢复前安全备份必须在还原锁已持有的前提下执行，故跳过此检查。
    if not skip_restore_check:
        from ..restore import is_restore_in_progress
        if await is_restore_in_progress():
            raise BackupLockError('还原操作正在执行中，请等待还原完成后再备份')

    db_lock_acquired = await acquire_backup_lock(db)
    if not db_lock_acquired:
        raise BackupLockError('其他进程正在执行备份，请稍后重试')

    async with _backup_in_progress:
        try:
            return await asyncio.wait_for(
                _do_create_full_backup(
                    db, user, remark, encrypt_password, use_snapshot, encrypt,
                    tables=tables, exclude_tables=exclude_tables,
                    progress_cb=progress_cb,
                ),
                timeout=BACKUP_OPERATION_TIMEOUT,
            )
        except TimeoutError as e:
            logger.error('备份操作超时（%s秒）', BACKUP_OPERATION_TIMEOUT)
            raise BackupError(f'备份超时（>{BACKUP_OPERATION_TIMEOUT}s），已强制取消') from e
        finally:
            await release_backup_lock(db)

async def _export_database(db, user, remark, tmpdir_path: Path, snapshot_id,
                           partial: bool, tables, exclude_tables, progress_cb):
    """导出数据库：pg_dump 优先，不可用/表级备份时回退 JSON。

    返回 (dump_info, pg_dump_available, dump_path)。表级备份固定走 JSON 路径：
    还原时按表 upsert（psql 路径会整库重建，与表级语义冲突）。
    """
    dump_path = tmpdir_path / 'database' / 'dump.sql.gz'
    dump_info: dict = {}
    pg_dump_available = False
    if partial:
        json_path = tmpdir_path / 'database'
        json_path.mkdir(parents=True, exist_ok=True)
        json_bytes = await execute_legacy_backup_to_bytes(
            user, remark, db, tables=tables, exclude_tables=exclude_tables,
        )
        (json_path / 'dump.json').write_bytes(json_bytes)
        dump_info = {
            'pg_version': '', 'db_name': os.getenv('DB_NAME', 'erp_system'),
            'dump_size': len(json_bytes), 'duration_seconds': 0, 'format': 'json',
        }
    else:
        try:
            dump_info = await run_pg_dump(dump_path, snapshot_id)
            pg_dump_available = True
        except (TimeoutError, OSError, RuntimeError) as e:
            logger.warning(f'pg_dump 不可用，使用 JSON 格式备份数据库: {e}')
            # AUD-03（2026-10-24 审计）：JSON 降级必须告警——降级包不含 schema、
            # 无法在空库/新机恢复，若状态仍 success 则灾难恢复能力静默失效
            # （触发条件真实存在：pg_dump 版本不匹配/工具丢失）。
            try:
                from fastapi_app.services.backup.metrics.alert_service import alert_service
                await alert_service.send_alert(
                    task_name='pg_dump_unavailable',
                    error=f'pg_dump 不可用，本次备份降级为 JSON 格式'
                          f'（不含 schema，无法在空库恢复）：{e}',
                    task_type='backup', severity='warning',
                    additional_info={'snapshot_id': snapshot_id},
                )
            except Exception:  # defensive: 告警通道故障不得中断备份本身
                logger.warning('降级告警发送失败（不影响备份继续）', exc_info=True)
            json_path = tmpdir_path / 'database'
            json_path.mkdir(parents=True, exist_ok=True)
            json_bytes = await execute_legacy_backup_to_bytes(user, remark, db)
            (json_path / 'dump.json').write_bytes(json_bytes)
            dump_info = {
                'pg_version': '', 'db_name': os.getenv('DB_NAME', 'erp_system'),
                'dump_size': len(json_bytes), 'duration_seconds': 0, 'format': 'json',
            }
    if progress_cb:
        await progress_cb('export_db', 1.0, '数据库导出完成')
    return dump_info, pg_dump_available, dump_path


_LARGE_TABLE_ESTIMATE_THRESHOLD = 100_000


async def _count_tables(db: AsyncSession, table_names: list[str],
                        existing_tables: set[str]) -> dict[str, int]:
    """大表用 pg_class.reltuples 估算，小表精确 COUNT；失败记 -1。库中无表直接 -1。"""
    estimates: dict[str, int] = {}
    if table_names:
        try:
            rows = await db.execute(
                text(
                    "SELECT c.relname, c.reltuples::bigint FROM pg_class c "
                    "JOIN pg_namespace n ON n.oid = c.relnamespace "
                    "WHERE n.nspname = 'public' AND c.relkind = 'r' "
                    "AND c.relname = ANY(:names)"
                ),
                {"names": table_names},
            )
            estimates = {r[0]: max(0, int(r[1])) for r in rows.all()}
        except (OSError, ValueError, SQLAlchemyError):
            estimates = {}

    async def _count_table(tname: str) -> tuple[str, int]:
        if tname not in existing_tables:
            return tname, -1
        # reltuples 是统计信息估算值（可能滞后），只用于大表避免长事务 COUNT
        if estimates.get(tname, 0) >= _LARGE_TABLE_ESTIMATE_THRESHOLD:
            return tname, estimates[tname]
        nested = await db.begin_nested()
        try:
            qtname = quote_table(tname)
            result = await db.execute(text(f'SELECT COUNT(*) FROM {qtname}'))  # nosec B608 — qtname 经 quote_table 白名单校验
            await nested.commit()  # manual-tx: savepoint 嵌套事务管理
            return tname, result.scalar() or 0
        except (OSError, ValueError, SQLAlchemyError):
            await nested.rollback()  # manual-tx: savepoint 嵌套事务管理
            return tname, -1

    count_results = []
    for n in table_names:
        count_results.append(await _count_table(n))
    return dict(count_results)


def _build_coverage(existing_tables: set[str], table_names: list[str],
                    table_stats: dict[str, int], pg_dump_available: bool,
                    partial: bool) -> dict:
    """S4 覆盖度自检：区分两类缺口（见下方注释）。

    - count_failed_tables：表在库中、但 COUNT(*) 失败（savepoint 已回滚）→
      既没证实内容也没证实行数，属于真实缺口，参与 complete。
    - unbacked_tables：库中存在、本次产物不会包含的表。pg_dump 路径会整库导出，
      只有 JSON 降级路径（只遍历模型表）才会真的漏。这类表是已知的范围限制
      （库中未纳入 ORM 的非业务表），只记录并告警，不参与 complete——否则每天
      自动全量都判 partial，健康检查与合规报告会被永久噪声淹没，反而掩盖真正的缺口。
    """
    count_failed_tables = sorted(
        n for n, rows in table_stats.items() if rows < 0 and n in existing_tables
    )
    unbacked_tables: list[str] = []
    if not pg_dump_available and not partial:
        unbacked_tables = sorted(
            existing_tables - set(table_stats) - _CHECKSUM_EXCLUDE_TABLES
        )
        if unbacked_tables:
            logger.warning(
                'JSON 降级备份未覆盖 %d 张非模型表（pg_dump 不可用）: %s',
                len(unbacked_tables),
                ', '.join(unbacked_tables[:10]),
            )
    return {
        'db_table_count': len(existing_tables),
        'scope_table_count': len(table_names),
        'backup_table_count': len(table_stats),
        'count_failed_tables': count_failed_tables,
        'unbacked_tables': unbacked_tables,
        'complete': not count_failed_tables,
    }


async def _collect_fingerprints(db: AsyncSession, table_names: list[str],
                                existing_tables: set[str]) -> dict[str, str]:
    """L2 数据指纹：关键业务表 MD5 聚合（savepoint 隔离，单表失败记空串）。"""
    from fastapi_app.shared_models import Base

    fingerprints: dict[str, str] = {}
    scope_name_set = set(table_names)
    for table in Base.metadata.sorted_tables:
        tname = str(table.name)
        if tname not in scope_name_set:
            continue
        if tname not in get_checksum_tables():
            continue
        if tname not in existing_tables:
            # 模型存在但库中尚无表(待迁移):发一条 SELECT 会因列集合为空拼出病态 SQL,
            # 且错误会中止整个会话事务,连带后续指纹/schema 采集全灭 → 直接跳过
            continue
        try:
            async with db.begin_nested():  # savepoint: 单表失败只回滚该表,不影响整笔事务
                qtname = quote_table(tname)  # REV-08
                pk_col = [c.name for c in table.primary_key.columns]
                order_col = pk_col[0] if pk_col else 'id'
                cols_result = await db.execute(  # batch-loop: 逐表备份/恢复,无法批量
                    text('SELECT column_name FROM information_schema.columns WHERE table_name = :tname ORDER BY ordinal_position'),
                    {'tname': tname}
                )
                col_names = [r[0] for r in cols_result.fetchall()]
                agg_expr = " || '|' || ".join(f'''COALESCE("{c}"::text, '')''' for c in col_names)  # sql-safe: escape_like/绑定参数/常量片段
                fp_result = await db.execute(text(  # batch-loop: 逐表备份/恢复,无法批量
                    f'''SELECT MD5(STRING_AGG({agg_expr}, ',' ORDER BY "{order_col}")) FROM {qtname}'''  # nosec B608 — qtname 经 quote_table 白名单校验
                ))
                fingerprints[tname] = fp_result.scalar() or ''
        except (SQLAlchemyError, ValueError, OSError) as e:
            logger.warning(f'计算表 {tname} 指纹失败: {e}')
            fingerprints[tname] = ''
    return fingerprints


async def _collect_schema_snapshot(db: AsyncSession) -> dict[str, list[dict]]:
    """M3: 采集表结构快照，供还原后 L4 DDL 比对（失败时置空并跳过比对）。"""
    snapshot_schema: dict[str, list[dict]] = {}
    try:
        from fastapi_app.services.backup.verify.core import build_schema_snapshot
        async with db.begin_nested():  # savepoint: schema 采集失败不影响整笔事务
            snapshot_schema = await build_schema_snapshot(db)
    except Exception as e:  # broad-except: 备份容错，快照失败不影响备份主体
        logger.warning(f'采集表结构快照失败，schema_snapshot 置空: {e}')
    return snapshot_schema


def _build_manifest(user, remark: str, partial: bool, include_set, exclude_set,
                    dump_info: dict, baseline_at: str, table_stats: dict[str, int],
                    count_failed_tables: list[str], coverage: dict,
                    checksums: dict, fingerprints: dict,
                    snapshot_schema: dict[str, list[dict]]) -> dict:
    """组装 manifest.json（自述 + 覆盖度 + 校验和 + 指纹 + schema 快照）。"""
    manifest = {
        'version': BACKUP_FORMAT_VERSION, 'type': 'partial' if partial else 'full', 'app_version': '2.0',
        'pg_version': dump_info.get('pg_version', ''),
        'db_name': dump_info.get('db_name', ''),
        'exported_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        # 一致性起点：pg_export_snapshot 获取时刻。增量备份应以它（而非滞后的
        # exported_at）为 since 基准，否则 snapshot 起点到 exported_at 之间的改动
        # 既不在全量、也不在增量，永久丢失。无快照路径留空，增量回退 exported_at。
        'baseline_at': baseline_at,
        'exported_by': user.username if hasattr(user, 'username') else str(user.id),
        'remark': remark,
        'table_count': len(table_stats),
        # S4：完整性自述。failed_tables 供 evaluate_backup_completeness 判 partial，
        # coverage 供人工/巡检核对「库里有几张、产物里几张、差在哪」。
        'failed_tables': count_failed_tables,
        'coverage': coverage,
        # AUD-03：产物自述 dump 格式。JSON 降级包不含 schema、无法空库恢复，
        # evaluate_backup_completeness 据此判 partial（而非静默 success）。
        'dump_format': dump_info.get('format', 'sql'),
        'total_rows': sum(v for v in table_stats.values() if v >= 0),
        'dump_size': dump_info.get('dump_size', 0),
        'dump_duration_seconds': dump_info.get('duration_seconds', 0),
        'snapshot_id': dump_info.get('snapshot_id'),
        'tables': {k: {'rows': v} for k, v in table_stats.items()},
        'includes': {}, 'checksums': checksums, 'fingerprints': fingerprints,
        'schema_snapshot': snapshot_schema,
    }
    if partial:
        manifest['tables_scope'] = {
            'include': sorted(include_set) if include_set else None,
            'exclude': sorted(exclude_set) if exclude_set else None,
        }
    return manifest


def _resolve_encryption_password(encrypt, encrypt_password):
    """P0-1 加密决策单点化：服务层只认显式入参 + 环境变量，绝不生成随机密钥。

    决策须前置到打包之前：敏感配置（jwt 私钥 / .env.production）仅在加密备份中
    打包，需在写 zip 前确定本次是否加密。
    - encrypt=False / None（未显式要求加密）：环境变量有密码则加密，否则明文+告警
    - encrypt=True：必须有密码（入参或环境变量），否则直接报错（宁可失败不可造出打不开的备份）
    总开关优先：BACKUP_ENCRYPTION_ENABLED=false 时忽略调用方的 encrypt 意图，一律明文。
    前端手动备份硬编码 encrypt=true，若不让开关短路，运维改环境变量将完全无效。
    """
    from ..crypto import resolve_encryption_decision

    # Z05-R5：决策收敛到 crypto.resolve_encryption_decision；服务层不容忍
    # 「encrypt=True 却无密码」的降级（宁可失败不可产出打不开的备份）。
    _, effective = resolve_encryption_decision(
        encrypt, encrypt_password, degrade_when_missing=False,
    )
    return effective


async def _export_meilisearch(zf, manifest: dict) -> None:
    """导出 MeiliSearch 索引与设置（失败可忽略，不影响备份主体）。"""
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
    except Exception as e:  # broad-except: 备份/恢复容错，防止局部异常导致整体流程中断
        logger.warning('MeiliSearch 索引导出失败（可忽略）: %s', e)


def _write_filestore(zf: zipfile.ZipFile, uploads_dir: Path) -> int:
    """同步写入附件目录（由 asyncio.to_thread 调用）。返回文件数。"""
    file_count = 0
    for fp in sorted(uploads_dir.rglob('*')):
        if fp.is_file():
            zf.write(fp, f'filestore/{fp.relative_to(uploads_dir)}')
            file_count += 1
    return file_count


async def _write_to_zip_async(zf: zipfile.ZipFile, path: Path, arcname: str) -> None:
    """大文件（dump.sql.gz / RDB）压缩写 ZIP 也是 CPU 密集操作，下沉线程池。"""
    await asyncio.to_thread(zf.write, path, arcname)


async def _pack_backup_zip(zip_path: Path, tmpdir_path: Path, pg_dump_available: bool,
                           dump_path: Path, manifest: dict, include_sensitive_config: bool,
                           progress_cb) -> None:
    """打包 ZIP：数据库导出 + 附件 + 配置 + Redis RDB + MeiliSearch + manifest。"""
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED, compresslevel=3) as zf:
        if pg_dump_available and dump_path.is_file():
            await _write_to_zip_async(zf, dump_path, 'database/dump.sql.gz')
        elif (tmpdir_path / 'database' / 'dump.json').is_file():
            await _write_to_zip_async(
                zf, tmpdir_path / 'database' / 'dump.json', 'database/dump.json'
            )

        if UPLOADS_DIR.is_dir():
            # 全量附件压缩是 CPU 密集操作，下沉线程池；进度回调留在事件循环侧
            file_count = await asyncio.to_thread(_write_filestore, zf, UPLOADS_DIR)
            manifest['includes']['filestore_count'] = file_count
            if progress_cb:
                await progress_cb('pack_filestore', 1.0, f'附件 {file_count} 个')

        # 清单唯一来源：_constants.config_files_to_package()（H-3，2026-09-29），
        # 归档名自带 config/ 或 root/ 命名空间（P0-2）——打包侧不再拼前缀。
        # 现役 JWT 密钥按 settings 推导（随轮换自动跟进）+ 运行时 .env（归档为
        # root/.env）；**退役**的 private.pem/public.pem 不再随包分发 —— 它们是
        # 已泄漏的历史密钥，随包走等于继续扩散。
        config_files_added, config_files_excluded = pack_config_files(zf, include_sensitive_config)
        record_config_includes(
            manifest, config_files_added, config_files_excluded, include_sensitive_config
        )
        if progress_cb:
            await progress_cb('backup_config', 1.0, f'配置 {len(config_files_added)} 个')

        if REDIS_DUMP.is_file():
            await _write_to_zip_async(zf, REDIS_DUMP, 'redis/dump.rdb')
            manifest['includes']['redis_rdb'] = True
            if progress_cb:
                await progress_cb('backup_redis', 1.0, 'Redis RDB 已打包')

        await _export_meilisearch(zf, manifest)
        if progress_cb:
            await progress_cb('backup_meilisearch', 1.0, '搜索索引处理完成')

        manifest_bytes = json.dumps(manifest, ensure_ascii=False, indent=2).encode('utf-8')
        zf.writestr('manifest.json', manifest_bytes)


def _encrypt_backup(zip_bytes: bytes, effective_encryption_password,
                    manifest: dict, encrypt_password) -> tuple[bytes, dict]:
    """加密决策已在打包前完成（见 _resolve_encryption_password），此处只执行。"""
    # ITER-1 T3：新写备份统一走分块格式（chunked-v1），旧格式仍可读。
    # 回退开关 BACKUP_ENCRYPTION_CHUNKED=false，无需回滚代码。
    from fastapi_app.core.backup_encryption import encrypt_backup_auto
    try:
        encrypted_bytes, meta_dict = encrypt_backup_auto(zip_bytes, effective_encryption_password)
        manifest['encrypted'] = True
        manifest['encryption'] = meta_dict
        if encrypt_password:
            logger.info("使用用户提供的密码进行备份加密")
        else:
            logger.info("使用环境变量配置的密钥进行备份加密")
        return encrypted_bytes, manifest
    except Exception as e:  # broad-except: 备份/恢复容错，防止局部异常导致整体流程中断
        logger.error(f"备份加密失败: {e}")
        raise BackupError(f"备份加密失败: {e}") from e


async def _encrypt_backup_async(zip_bytes: bytes, effective_encryption_password,
                                manifest: dict, encrypt_password) -> tuple[bytes, dict]:
    """PBKDF2 + AES-GCM 是 CPU 密集操作，必须下沉线程池。"""
    return await asyncio.to_thread(
        _encrypt_backup, zip_bytes, effective_encryption_password, manifest, encrypt_password
    )


async def _do_create_full_backup(
    db: AsyncSession,
    user,
    remark: str,
    encrypt_password: str | bytearray | None,
    use_snapshot: bool,
    encrypt: bool | None = None,
    tables: list[str] | None = None,
    exclude_tables: list[str] | None = None,
    progress_cb=None,
) -> tuple[bytes, dict]:
    """create_full_backup 的实际实现，由锁和超时控制包裹。

    2026-10-11（复核 P2-14⑤）拆分：原 273 行，现只保留编排顺序，
    导出/统计/指纹/schema/清单/加密决策/打包/加密执行各自成单元（均 ≤80 行）。
    """
    include_set, exclude_set = resolve_backup_table_scope(tables, exclude_tables)
    partial = include_set is not None or exclude_set is not None

    snapshot_id = None
    baseline_at = ''  # 备份一致性起点（第八轮落地）：增量备份以此为基准，消除 exported_at 滞后缺口
    if use_snapshot:
        try:
            snapshot_id = await get_postgres_snapshot(db)
            baseline_at = datetime.now(UTC).strftime('%Y-%m-%d %H:%M:%S')
            logger.info(f"获取数据库快照成功: {snapshot_id} (baseline_at={baseline_at})")
        except DatabaseSnapshotError as e:
            logger.warning(f"无法获取数据库快照，继续无快照备份: {e}")

    with tempfile.TemporaryDirectory(prefix='erp_backup_') as tmpdir:
        tmpdir_path = Path(tmpdir)
        dump_info, pg_dump_available, dump_path = await _export_database(
            db, user, remark, tmpdir_path, snapshot_id, partial, tables, exclude_tables, progress_cb,
        )

        from fastapi_app.shared_models import Base

        table_names = [str(t.name) for t in Base.metadata.sorted_tables]
        if include_set is not None:
            table_names = [n for n in table_names if n in include_set]
        if exclude_set is not None:
            table_names = [n for n in table_names if n not in exclude_set]

        existing_result = await db.execute(
            text("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")
        )
        existing_tables = {r[0] for r in existing_result.fetchall()}

        table_stats = await _count_tables(db, table_names, existing_tables)
        coverage = _build_coverage(existing_tables, table_names, table_stats, pg_dump_available, partial)
        count_failed_tables = coverage['count_failed_tables']

        checksums = {}
        db_dump_name = 'database/dump.sql.gz' if pg_dump_available else 'database/dump.json'
        db_dump_file = dump_path if pg_dump_available else tmpdir_path / 'database' / 'dump.json'
        if db_dump_file.is_file():
            checksums[db_dump_name] = await asyncio.to_thread(sha256_file, db_dump_file)  # REV-14

        fingerprints = await _collect_fingerprints(db, table_names, existing_tables)
        snapshot_schema = await _collect_schema_snapshot(db)
        manifest = _build_manifest(
            user, remark, partial, include_set, exclude_set, dump_info, baseline_at,
            table_stats, count_failed_tables, coverage, checksums, fingerprints, snapshot_schema,
        )

        zip_path = tmpdir_path / 'backup.zip'
        effective_encryption_password = _resolve_encryption_password(encrypt, encrypt_password)
        # 敏感配置随加密包分发：密钥泄露风险与备份加密绑定，明文包始终排除
        include_sensitive_config = bool(effective_encryption_password)

        await _pack_backup_zip(
            zip_path, tmpdir_path, pg_dump_available, dump_path, manifest,
            include_sensitive_config, progress_cb,
        )

        # Z05-R10：GB 级备份同步读取会阻塞事件循环，下沉线程池
        zip_bytes = await asyncio.to_thread(zip_path.read_bytes)
        manifest['zip_size'] = len(zip_bytes)
        if progress_cb:
            await progress_cb('generate_checksum', 1.0, '校验和已生成')

        if effective_encryption_password:
            return await _encrypt_backup_async(
                zip_bytes, effective_encryption_password, manifest, encrypt_password
            )

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


async def create_pre_restore_backup(db: AsyncSession, skip_restore_check: bool = False) -> dict:
    """创建恢复前安全备份。

    skip_restore_check：异步还原路径在「已持有还原锁」的前提下调用本函数，若
    仍走 is_restore_in_progress() 检查会必然抛 BackupLockError、导致安全备份
    静默失败。该场景须传 True。同步还原路径在获取还原锁之前调用，应保持默认
    False 以保留「还原进行中拒绝备份」的互斥保护。
    """
    ensure_pre_restore_dir()
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    try:
        from fastapi_app.shared_models import User as UserModel
        dummy_user = UserModel()
        dummy_user.username = 'system'
        dummy_user.id = 0
        # P1（2026-10-24）：安全备份不再硬编码 encrypt=False。
        # 原实现绕过加密总开关，加密部署下每次还原（含失败的那次）都会在
        # pre_restore/ 落一份明文整库（含全部附件），且该目录不在保留期扫描内，
        # 最多 5 份长期驻留。encrypt=None 表示继承 is_encryption_enabled()，
        # 与手动/自动全量同口径；口令丢失时回滚点不可用属可接受取舍（加密是红线）。
        zip_bytes, _manifest = await create_full_backup(
            db, dummy_user, '恢复前自动安全备份',
            encrypt=None, skip_restore_check=skip_restore_check,
        )
        # 加密产物用 .zip.enc 命名，避免运维在灾难现场拿 unzip 打不开而误判文件损坏
        # （恢复侧按内容头识别加密，不依赖后缀）。
        _encrypted = bool(_manifest.get('encrypted'))
        filename = f'pre_restore_{timestamp}.zip.enc' if _encrypted else f'pre_restore_{timestamp}.zip'
        filepath = PRE_RESTORE_DIR / filename
        filepath.write_bytes(zip_bytes)
        cleanup_pre_restore_backups()
        return {'success': True, 'filename': filename, 'filepath': str(filepath), 'size': len(zip_bytes), 'encrypted': _encrypted}
    except Exception as e:  # broad-except: 备份/恢复容错，防止局部异常导致整体流程中断
        logger.warning(f'创建恢复前安全备份失败（不阻塞恢复）: {e}')
        return {'success': False, 'error': str(e)}
