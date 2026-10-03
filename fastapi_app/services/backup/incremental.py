"""增量备份/WAL。"""
from __future__ import annotations

import contextlib
import json
import logging
import tempfile
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from ._constants import (
    BACKUP_DIR,
    BACKUP_FORMAT_VERSION,
    RESTORE_LOCK_ID,
)
from .crypto import get_backup_encryption_password, is_encryption_enabled, sha256_file
from .exceptions import BackupError, BackupLockError, BinaryLogError, RestoreError
from .json_backup import build_column_type_map, deserialize_value
from .records import ensure_backup_dir
from .snapshot import create_binary_log_backup, get_postgres_wal_info
from .verify import find_last_backup_timestamp, query_table_rows, quote_table

logger = logging.getLogger(__name__)


async def create_incremental_backup(
    db: AsyncSession,
    user,
    remark: str = '',
    since: str = '',
    encrypt_password: str | bytearray | None = None,
    encrypt: bool | None = None,
) -> dict:
    """执行增量备份

    如果提供 encrypt_password 或配置了环境变量，则使用 AES-256-GCM 加密备份。
    encrypt 参数(M1 新增;P0-1 统一 fail-safe 语义,不再有随机密钥回退):
    - None(默认):encrypt_password 或环境变量,均无则不加密+告警
    - True:必须提供密码(参数/环境变量),否则抛错
    - False:强制不加密(即使有环境变量)——手动任务 fail-safe 用
    """
    ensure_backup_dir()
    # B4 修复：增量备份与还原互斥（与全量备份入口一致）
    from .restore import is_restore_in_progress
    if await is_restore_in_progress():
        raise BackupLockError('还原操作正在执行中，请等待还原完成后再备份')

    # 第八轮审计：增量备份与全量备份互斥 —— 取同一个 DB advisory lock(BACKUP_LOCK_ID)，
    # 防两者并发写 BACKUP_DIR / 同秒文件名互相覆盖。
    from .orchestration.core import acquire_backup_lock, release_backup_lock
    if not await acquire_backup_lock(db):
        raise BackupLockError('另一个备份操作正在执行中，请稍后重试')
    try:
        timestamp = datetime.now(UTC).strftime('%Y%m%d_%H%M%S')
        from fastapi_app.shared_models import Base
        incremental_tables = {}
        total_rows = 0
        failed_tables: list[str] = []
        effective_since = since or await find_last_backup_timestamp() or ''
        for table in Base.metadata.sorted_tables:
            tname = str(table.name)
            try:
                serialized_rows = await query_table_rows(tname, db, effective_since or None)
                if serialized_rows:
                    columns = list(serialized_rows[0].keys())
                    incremental_tables[tname] = {'columns': columns, 'rows': serialized_rows, 'count': len(serialized_rows)}
                    total_rows += len(serialized_rows)
            except (SQLAlchemyError, ValueError, OSError) as e:
                # 这里吞掉异常会让备份「成功」但静默缺表 —— 2026-09-30 之前
                # approval_request / approval_log 正是这样长期漏备的。故记 ERROR 并登记表名，
                # 让调用方与 manifest 都能看到"哪些表没进备份"。
                # S4：失败后必须回滚。PostgreSQL 的事务一旦出错就进入 aborted 状态，
                # 不 rollback 的话后面每一张表都会抛 InFailedSQLTransactionError，
                # 一张表出问题会连锁成「整份增量备份全空」（实测见 _qa_tmp/s4_cascade_probe.py）。
                with contextlib.suppress(SQLAlchemyError):
                    await db.rollback()  # manual-tx: 单表失败后恢复事务，避免连锁失败
                logger.error(f'增量备份表 {tname} 失败: {e}')
                failed_tables.append(tname)

        if not incremental_tables:
            # 区分「真的没有变更」与「每张表都失败了」：后者若报 success=True 且 filename=None，
            # 两个调用方（backup_tasks 手动/自动）都只判 filename → 会把它当成"本次无变更"，
            # **不写记录、无告警、上报 ok**，把系统性故障伪装成正常。
            if failed_tables:
                return {
                    'success': False, 'filename': None,
                    'message': f'增量备份失败：{len(failed_tables)} 张表全部导出失败',
                    'total_rows': 0, 'failed_tables': failed_tables,
                }
            return {
                'success': True, 'filename': None, 'message': '无变更数据需要备份',
                'total_rows': 0, 'failed_tables': failed_tables,
            }

        with tempfile.TemporaryDirectory(prefix='erp_inc_') as tmpdir:
            tmpdir_path = Path(tmpdir)
            json_path = tmpdir_path / 'database' / 'dump.json'
            json_path.parent.mkdir(parents=True, exist_ok=True)
            backup_data = {
                'version': BACKUP_FORMAT_VERSION, 'type': 'incremental',
                'exported_at': datetime.now(UTC).strftime('%Y-%m-%d %H:%M:%S'),
                'exported_by': user.username if hasattr(user, 'username') else str(user.id),
                'remark': remark, 'base_timestamp': effective_since,
                'table_count': len(incremental_tables), 'total_rows': total_rows,
                'failed_tables': failed_tables,
                'tables': incremental_tables,
            }
            json_path.write_bytes(json.dumps(backup_data, ensure_ascii=False, indent=2).encode('utf-8'))
            zip_path = tmpdir_path / 'backup.zip'
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED, compresslevel=3) as zf:
                zf.write(json_path, 'database/dump.json')
                manifest = {
                    'version': BACKUP_FORMAT_VERSION, 'type': 'incremental', 'app_version': '2.0',
                    'exported_at': backup_data['exported_at'],
                    'exported_by': backup_data['exported_by'],
                    'remark': remark, 'base_timestamp': effective_since,
                    'table_count': len(incremental_tables), 'total_rows': total_rows,
                    'failed_tables': failed_tables,
                    'includes': {},
                    'checksums': {'database/dump.json': sha256_file(json_path)},  # REV-14
                }
                zf.writestr('manifest.json', json.dumps(manifest, ensure_ascii=False, indent=2).encode('utf-8'))
            zip_bytes = zip_path.read_bytes()

            # P0-1 统一加密语义：与 create_full_backup 一致，无随机密钥回退
            if encrypt is True and not (encrypt_password or get_backup_encryption_password()):
                raise BackupError('请求加密增量备份但未配置密码（encrypt_password 参数 / BACKUP_ENCRYPTION_PASSWORD 环境变量均未提供）')
            if encrypt is False:
                encryption_password = None
            else:
                encryption_password = encrypt_password or get_backup_encryption_password()
                if encrypt is None and not encryption_password:
                    # 红线#4（第八轮审计）：加密已启用却拿不到密码 → fail-closed（同 create_full_backup）。
                    if is_encryption_enabled():
                        raise BackupError(
                            '备份加密已启用（BACKUP_ENCRYPTION_ENABLED=true）但未配置可用的密码，'
                            '拒绝产出不加密增量备份'
                        )
                    logger.warning("增量备份未显式指定 encrypt，且无可用密码，本次备份不加密")
            encrypted = False
            if encryption_password:
                # ITER-1 T3：新写增量备份统一走分块格式（chunked-v1），旧格式仍可读。
                from fastapi_app.core.backup_encryption import encrypt_backup_auto
                try:
                    encrypted_bytes, meta_dict = encrypt_backup_auto(zip_bytes, encryption_password)
                    # 更新 manifest 以标记加密
                    manifest['encrypted'] = True
                    manifest['encryption'] = meta_dict
                    if encrypt_password:
                        logger.info("使用用户提供的密码进行增量备份加密")
                    else:
                        logger.info("使用环境变量配置的密钥进行增量备份加密")
                    zip_bytes = encrypted_bytes
                    encrypted = True
                except Exception as e:  # broad-except: 备份/恢复容错，防止局部异常导致整体流程中断
                    logger.error(f"增量备份加密失败: {e}")
                    raise BackupError(f"增量备份加密失败: {e}") from e

        # P0-1: 加密备份落盘扩展名带 .enc；P0-4: 同步写 .meta sidecar
        filename = f'erp_incremental_{timestamp}.zip.enc' if encrypted else f'erp_incremental_{timestamp}.zip'
        filepath = BACKUP_DIR / filename
        filepath.write_bytes(zip_bytes)
        from .records import write_backup_meta_file
        write_backup_meta_file(filepath, manifest, record_type='incremental')
        return {
            'success': True, 'filename': filename, 'size': len(zip_bytes),
            'format': 'incremental', 'table_count': len(incremental_tables),
            'total_rows': total_rows, 'exported_at': backup_data['exported_at'],
            'base_timestamp': effective_since, 'remark': remark,
            'encrypted': encrypted, 'failed_tables': failed_tables,
        }
    finally:
        await release_backup_lock(db)


async def create_wal_incremental_backup(
    db: AsyncSession,
    user,
    remark: str = '',
    start_lsn: str | None = None,
    encrypt_password: str | bytearray | None = None,
) -> dict:
    """创建基于 WAL 的二进制日志增量备份

    使用 PostgreSQL 的 WAL (Write-Ahead Logging) 进行增量备份。
    需要 PostgreSQL 配置了 WAL 归档。

    ⚠️ 当前不可用（P0-10，2026-09-12）。
    本函数依赖 `create_binary_log_backup`，而后者尚未实现（无 pg_basebackup /
    pg_receivewal 集成），现已改为显式抛 `BinaryLogError`。该异常会从下方调用点
    直接向外传播，因此本函数调用时必然失败，不会产出「假备份」记录。
    真正的增量备份请走 `create_incremental_backup`。

    Args:
        db: 数据库会话
        user: 用户信息
        remark: 备份备注
        start_lsn: 起始 LSN，如果为 None 则从最近的全量备份时间点开始
        encrypt_password: 加密密码，如果为 None 则使用环境变量配置

    Returns:
        包含备份信息的字典

    Raises:
        BinaryLogError: 依赖的 WAL 二进制日志备份功能尚未实现
    """
    ensure_backup_dir()

    # 获取当前 LSN
    wal_info = await get_postgres_wal_info(db)
    current_lsn = wal_info.get('current_lsn')
    if not current_lsn:
        raise BinaryLogError("无法获取当前 LSN")

    # 如果没有提供起始 LSN，尝试从最近的全量备份获取
    if not start_lsn:
        # 查找最近的全量备份
        latest_full_backup = None
        if BACKUP_DIR.exists():
            for f in sorted(BACKUP_DIR.iterdir(), reverse=True):
                if f.is_file() and f.name.startswith('erp_backup_') and f.name.endswith('.zip'):
                    try:
                        with zipfile.ZipFile(f, 'r') as zf:
                            if 'manifest.json' in zf.namelist():
                                manifest = json.loads(zf.read('manifest.json'))
                                if manifest.get('type') == 'full':
                                    latest_full_backup = {
                                        'filename': f.name,
                                        'exported_at': manifest.get('exported_at'),
                                        'lsn': manifest.get('lsn')  # 全量备份可能包含 LSN
                                    }
                                    break
                    except (OSError, zipfile.BadZipFile, ValueError):
                        continue

        if latest_full_backup and latest_full_backup.get('lsn'):
            start_lsn = latest_full_backup['lsn']
            logger.info(f"使用最近全量备份的 LSN: {start_lsn}")
        else:
            # 如果没有找到全量备份的 LSN，使用当前 LSN（相当于全量备份）
            start_lsn = current_lsn
            logger.warning("未找到最近全量备份的 LSN，使用当前 LSN")

    timestamp = datetime.now(UTC).strftime('%Y%m%d_%H%M%S')

    # 创建 WAL 备份
    wal_backup_result = await create_binary_log_backup(
        db=db,
        start_lsn=start_lsn,
        output_dir=BACKUP_DIR / 'wal_incremental'
    )

    # 创建备份元数据
    backup_info = {
        'version': BACKUP_FORMAT_VERSION,
        'type': 'wal_incremental',
        'app_version': '2.0',
        'exported_at': datetime.now(UTC).strftime('%Y-%m-%d %H:%M:%S'),
        'exported_by': user.username if hasattr(user, 'username') else str(user.id),
        'remark': remark,
        'start_lsn': start_lsn,
        'end_lsn': current_lsn,
        'wal_info': wal_info,
        'backup_files': wal_backup_result.get('backup_file'),
    }

    # 保存元数据文件（先在内存中处理，避免明文落盘）
    metadata_filename = f'erp_wal_incremental_{timestamp}.json'
    metadata_path = BACKUP_DIR / metadata_filename
    metadata_content = json.dumps(backup_info, indent=2, ensure_ascii=False).encode('utf-8')

    # 可选加密
    effective_encryption_password = encrypt_password or get_backup_encryption_password()
    if not effective_encryption_password and is_encryption_enabled():
        # 红线#4（第八轮审计）：加密已启用却拿不到密码 → fail-closed，不静默产明文。
        raise BackupError(
            'WAL 增量备份：加密已启用（BACKUP_ENCRYPTION_ENABLED=true）但未配置密码，'
            '拒绝产出不加密备份'
        )
    if effective_encryption_password:
        from fastapi_app.core.backup_encryption import encrypt_backup_auto
        try:
            encrypted_bytes, meta_dict = encrypt_backup_auto(metadata_content, effective_encryption_password)
            metadata_path.write_bytes(encrypted_bytes)

            # 更新备份信息（仅记录在日志中，不覆盖加密后的文件）
            backup_info['encrypted'] = True
            backup_info['encryption'] = meta_dict

            # 记录加密信息（P0-1: get_backup_encryption_password 已无随机回退，
            # 能走到这里密码必然来自入参或环境变量）
            if encrypt_password:
                logger.info("使用用户提供的密码进行 WAL 增量备份加密")
            else:
                logger.info("使用环境变量配置的密钥进行 WAL 增量备份加密")

            # 注意：不再重新写入明文 JSON，避免覆盖加密数据
            # 加密后的元数据信息记录在 backup_info 字典中返回给调用方

        except Exception as e:  # broad-except: 备份/恢复容错，防止局部异常导致整体流程中断
            logger.error(f"WAL 增量备份加密失败: {e}")
            raise BackupError(f"WAL 增量备份加密失败: {e}") from e
    else:
        metadata_path.write_bytes(metadata_content)

    return {
        'success': True,
        'filename': metadata_filename,
        'size': metadata_path.stat().st_size,
        'format': 'wal_incremental',
        'start_lsn': start_lsn,
        'end_lsn': current_lsn,
        'exported_at': backup_info['exported_at'],
        'remark': remark,
        'encrypted': effective_encryption_password is not None,
        'wal_backup_result': wal_backup_result,
    }


async def restore_incremental(
    db: AsyncSession,
    zip_bytes: bytes,
    filename: str,
) -> dict:
    """从增量备份恢复"""
    import io
    try:
        zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except zipfile.BadZipFile:
        raise RestoreError('无效的 ZIP 文件') from None
    if 'manifest.json' not in zf.namelist():
        raise RestoreError('增量备份缺少 manifest.json')
    manifest = json.loads(zf.read('manifest.json'))
    if manifest.get('type') != 'incremental':
        raise RestoreError('该备份不是增量备份，请使用全量恢复')
    if 'database/dump.json' not in zf.namelist():
        raise RestoreError('增量备份中无数据库数据')
    try:
        backup_data = json.loads(zf.read('database/dump.json'))
    except (json.JSONDecodeError, OSError) as e:
        raise RestoreError(f'读取增量备份数据失败: {e}') from e

    from fastapi_app.shared_models import Base

    from .orchestration import create_pre_restore_backup
    table_map = {str(t.name): t for t in Base.metadata.sorted_tables}
    total_upserted = 0
    results = {}
    errors = []

    pre_restore_info = await create_pre_restore_backup(db, skip_restore_check=True)
    lock_acquired = False
    try:
        lock_result = await db.execute(text('SELECT pg_try_advisory_lock(:lock_id)'), {'lock_id': RESTORE_LOCK_ID})
        if not lock_result.scalar():
            raise BackupLockError('另一个恢复操作正在执行中，请稍后重试')  # REV-06
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
            type_map = build_column_type_map(table)
            pk_cols = [c.name for c in table.primary_key.columns]
            table_col_names = {c.name for c in table.columns}
            qtname = quote_table(tname)  # REV-08
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
                            deserialized = deserialize_value(raw_val, col_type) if col_type else raw_val
                            params[f'{c}__row{idx}'] = deserialized
                        update_cols = [c for c in valid_cols if c not in pk_cols]
                        if pk_cols and update_cols:
                            update_str = ', '.join(f'"{c}" = EXCLUDED."{c}"' for c in update_cols)
                            await db.execute(text(  # batch-loop: 逐表备份/恢复,无法批量
                                f'INSERT INTO {qtname} ({col_str}) VALUES ({val_str}) ON CONFLICT ({", ".join(pk_cols)}) DO UPDATE SET {update_str}'  # nosec B608 — qtname 经 quote_table 白名单校验
                            ), params)
                        else:
                            await db.execute(text(  # batch-loop: 逐表备份/恢复,无法批量
                                f'INSERT INTO {qtname} ({col_str}) VALUES ({val_str}) ON CONFLICT DO NOTHING'  # nosec B608 — qtname 经 quote_table 白名单校验
                            ), params)
                        upserted += 1
                    await nested.commit()  # manual-tx: savepoint 嵌套事务管理
                except (SQLAlchemyError, ValueError, TypeError) as e:
                    await nested.rollback()  # manual-tx: savepoint 嵌套事务管理
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
        await db.commit()  # manual-tx: try/except 内显式事务控制
        try:
            from fastapi_app.core.cache import CacheDomain, invalidate_related_caches
            await invalidate_related_caches(CacheDomain.ALL)
        except (RuntimeError, OSError, ValueError) as e:
            logger.warning(f'增量恢复后缓存清除失败: {e}')
        try:
            from fastapi_app.core.purchase_cache import invalidate_purchase_caches
            # invalidate_purchase_caches 是 async def，必须 await；
            # 漏 await 会让协程被丢弃 → 恢复后采购缓存**永不失效**（读到陈旧数据）。
            await invalidate_purchase_caches()
        except (RuntimeError, OSError, ValueError) as e:
            logger.warning(f'增量恢复后采购缓存清除失败: {e}')
    except BackupLockError:
        raise
    except (SQLAlchemyError, ValueError, OSError) as e:
        try:
            await db.rollback()  # manual-tx: try/except 内显式事务控制
        except (OSError, SQLAlchemyError):
            logger.warning('恢复异常后回滚失败')
        raise RestoreError(f'增量恢复过程中出错: {e}') from e
    finally:
        if lock_acquired:
            try:
                await db.execute(text('SELECT pg_advisory_unlock(:lock_id)'), {'lock_id': RESTORE_LOCK_ID})
            except (OSError, ValueError, SQLAlchemyError):
                logger.warning('释放增量恢复锁失败')

    return {
        'success': True, 'format': 'incremental', 'filename': filename,
        'total_upserted': total_upserted, 'results': results, 'errors': errors,
        'pre_restore_backup': pre_restore_info,
        'restored_at': datetime.now(UTC).strftime('%Y-%m-%d %H:%M:%S'),
    }
