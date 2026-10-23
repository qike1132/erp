"""备份记录与状态。"""
from __future__ import annotations

import asyncio
import contextlib
import io
import json
import logging
import shutil
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from ._constants import (
    _MAX_PRE_RESTORE_BACKUPS,
    BACKUP_DIR,
    PRE_RESTORE_DIR,
)
from .crypto import sha256_bytes, sha256_file
from .exceptions import BackupFileError

logger = logging.getLogger(__name__)

# 模块级记录写入失败计数器（P1+P2）：每累计 3 次失败发送一次告警，避免告警风暴
_record_write_fail_count: int = 0

# 后台告警任务强引用集合：asyncio 对 Task 仅持弱引用，不保存引用会被 GC 中途回收（官方文档警告）
_background_tasks: set[asyncio.Task] = set()

# 正式备份文件命名约定：m5_fix_verify_*/erp_m3drill_* 等演练/测试件不计入统计与列表
_BACKUP_NAME_PREFIXES = ('erp_backup_', 'erp_incremental_', 'erp_auto_')
_BACKUP_FILE_SUFFIXES = ('.zip', '.json', '.zip.enc')

# 文件名时间戳格式：'YYYYMMDD_HHMMSS'（解析见 verify/query_service._parse_timestamp_from_filename）


def _is_backup_file(f: Path) -> bool:  # log-context: internal helper 无请求上下文
    """是否为正式备份文件(按命名约定排除演练/测试临时件)"""
    return (
        f.is_file()
        and f.name.startswith(_BACKUP_NAME_PREFIXES)
        and f.name.endswith(_BACKUP_FILE_SUFFIXES)
    )


def ensure_backup_dir():  # log-context: internal helper 无请求上下文
    """确保备份目录存在"""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)


def ensure_pre_restore_dir():  # log-context: internal helper 无请求上下文
    """确保恢复前安全备份目录存在"""
    PRE_RESTORE_DIR.mkdir(parents=True, exist_ok=True)


def write_backup_meta_file(filepath, manifest: dict, *, record_type: str = 'full'):  # log-context: internal helper 无请求上下文
    """为备份文件写入 .meta sidecar（P0-4 落地）。

    - created_at 与 _backup_created_time 的读取约定对齐（'%Y-%m-%d %H:%M:%S'），
      文件被复制/移动后保留策略不再依赖不可靠的 mtime；
    - 加密备份（.zip.enc）无法直接读 manifest，列表/状态展示依赖本 sidecar；
    - 写入失败仅告警，不阻塞备份主流程。
    """
    try:
        from fastapi_app.core.backup_encryption import create_meta_file
        fp = Path(filepath)
        meta = {
            # 本地 naive：_read_backup_timestamp 用 strptime 解析并与本地保留期比较，
            # 改 UTC 会让存量 sidecar 解析失败/保留期偏移；刻意保持。
            'created_at': manifest.get('exported_at') or datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            # 增量基准（snapshot 一致性起点）随 sidecar 落盘：加密包读不到 manifest，
            # _read_backup_timestamp 对 .enc 只能查这里。缺了它加密路径回退 created_at，
            # baseline 缺口修复对生产默认的加密备份无效。
            'baseline_at': manifest.get('baseline_at'),
            'filename': fp.name,
            'size': fp.stat().st_size,
            'type': manifest.get('type', record_type),
            'encrypted': bool(manifest.get('encrypted', False)),
            'format_version': manifest.get('version'),
            'table_count': manifest.get('table_count'),
            'total_rows': manifest.get('total_rows'),
            # S4：完整性自述随 sidecar 落盘。加密备份读不到 manifest，
            # 列表/补录/判状态只能靠这里，缺了它加密备份永远判 success。
            'failed_tables': manifest.get('failed_tables') or [],
            'coverage': manifest.get('coverage'),
            'exported_by': manifest.get('exported_by'),
            'remark': manifest.get('remark', ''),
            'checksum': sha256_file(fp),
        }
        meta_path = fp.parent / (fp.name + '.meta')
        meta_path.write_bytes(create_meta_file(meta))
        return meta_path
    except (OSError, ValueError, AttributeError, TypeError) as e:
        logger.warning(f'写入备份 .meta 失败（不阻塞主流程）: {e}')
        return None


def _read_backup_meta(f: Path) -> dict | None:  # log-context: internal helper 无请求上下文
    """读取备份文件的 .meta sidecar，不存在或损坏时返回 None。"""
    meta_path = f.parent / (f.name + '.meta')
    if not meta_path.exists():
        return None
    try:
        return json.loads(meta_path.read_text(encoding='utf-8'))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None


# ---------------------------------------------------------------------------
# 备份完整性判据（S4）
#
# 背景：历史上 backup_record.status 只反映「进程有没有抛异常」——
# 增量备份里某张表查询失败被吞掉、全量备份的 table_count 只是「数到的表数」，
# 于是缺表的备份照样记 success，事后无法区分「完整」与「当时没人报错」。
# 这里把「产物自述的覆盖情况」收敛成单一判据，所有写记录的地方都必须用它。
# ---------------------------------------------------------------------------
STATUS_SUCCESS = 'success'
STATUS_PARTIAL = 'partial'
STATUS_UNKNOWN = 'unknown'
STATUS_RUNNING = 'running'
STATUS_FAILED = 'failed'

# remark 里最多列出多少张问题表，避免异常时 remark 被表名刷爆
_MAX_REPORTED_TABLES = 10


def _collect_problem_tables(info: dict | None) -> list[str]:
    """收集产物自述的「缺失/失败」表名，去重并保持出现顺序。"""
    if not isinstance(info, dict):
        return []
    problems: list[str] = []

    def _extend(value) -> None:
        if not value:
            return
        if isinstance(value, str):
            items: list = [value]
        elif isinstance(value, dict):
            items = list(value.keys())
        elif isinstance(value, (list, tuple, set, frozenset)):
            items = list(value)
        else:
            return
        for item in items:
            name = str(item).strip()
            if name and name not in problems:
                problems.append(name)

    for key in ('failed_tables', 'missing_tables', 'error_tables'):
        _extend(info.get(key))
    coverage = info.get('coverage')
    if isinstance(coverage, dict):
        for key in ('failed_tables', 'missing_tables', 'count_failed_tables'):
            _extend(coverage.get(key))
    # 行级/批次级错误（如 json_backup 的 batch_errors）的键就是表名
    batch_errors = info.get('batch_errors')
    if isinstance(batch_errors, dict):
        _extend(list(batch_errors.keys()))
    return problems


def evaluate_backup_completeness(info: dict | None) -> tuple[str, str]:
    """由备份产物描述推导 (status, 问题说明) 二元组。

    - 产物自述有缺失/失败表，或 coverage.complete 为 False → ('partial', 说明)
    - 其余情况 → ('success', '')

    本函数只做「产物自述」判定：没有自述信息的旧产物仍判 success，无法凭空
    推断内容完整性（那类情况见 sync_backup_records 的 unknown 分支）。
    """
    problems = _collect_problem_tables(info)
    incomplete = bool(problems)
    coverage = info.get('coverage') if isinstance(info, dict) else None
    if isinstance(coverage, dict) and coverage.get('complete') is False:
        incomplete = True
    if not incomplete:
        return STATUS_SUCCESS, ''
    if problems:
        shown = problems[:_MAX_REPORTED_TABLES]
        detail = f'缺失/失败表: {", ".join(shown)}'
        if len(problems) > len(shown):
            detail += f' 等 {len(problems)} 张'
    else:
        detail = '覆盖度自检未通过（详见 manifest.coverage）'
    return STATUS_PARTIAL, detail


def compose_remark(base: str | None, detail: str) -> str:
    """把问题说明追加到 remark 上（空说明则原样返回）。"""
    text_base = (base or '').strip()
    if not detail:
        return text_base
    return f'{text_base}；{detail}' if text_base else detail


async def write_backup_record(
    db: AsyncSession,
    *,
    record_type: str,
    trigger_type: str = 'manual',
    filename: str | None = None,
    size: int | None = None,
    table_count: int | None = None,
    total_rows: int | None = None,
    operator: str | None = None,
    remark: str | None = None,
    # status 必填（S4）：默认 'success' 会让「忘了传」与「真的完整」无法区分
    status: str,
    error_message: str | None = None,
    duration_seconds: float | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    parent_record_id: int | None = None,
    manifest_summary: dict | None = None,
    schedule_id: int | None = None,
    encrypted: bool | None = None,
) -> None:
    """写入备份操作记录到 BackupRecord 表。

    status 为必填（S4）：不允许「不传就成功」。取值见 STATUS_* 常量，
    由 evaluate_backup_completeness() 从备份产物（manifest / .meta /
    incremental 返回值）推导；失败路径显式传 STATUS_FAILED。
    """
    try:
        from fastapi_app.shared_models.backup_record import BackupRecord
        record = BackupRecord(
            type=record_type, trigger_type=trigger_type, filename=filename,
            size=size, table_count=table_count, total_rows=total_rows,
            operator=operator, remark=remark, status=status,
            error_message=error_message, duration_seconds=duration_seconds,
            ip_address=ip_address, user_agent=user_agent,
            parent_record_id=parent_record_id,
            manifest_summary=manifest_summary,
            schedule_id=schedule_id,
            encrypted=encrypted,
        )
        db.add(record)
        await db.flush()
    except (SQLAlchemyError, OSError) as e:
        global _record_write_fail_count
        _record_write_fail_count += 1
        logger.warning(f'写入备份记录失败（不阻塞主流程）: {e}')
        # 每累计3次失败发送一次告警，避免告警风暴
        if _record_write_fail_count % 3 == 0:
            # 告警失败不影响主流程
            with contextlib.suppress(Exception):
                from fastapi_app.services.backup.metrics.alert_service import alert_service
                # 尝试获取事件循环，有则发送告警，无则跳过（同步上下文无法 await）
                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    loop = None
                if loop:
                    # 保留强引用，避免告警任务被 GC 中途回收（asyncio 仅持弱引用）
                    _task = loop.create_task(alert_service.send_alert(
                        task_name='backup_record_write',
                        error=f'备份记录写入已连续失败 {_record_write_fail_count} 次: {e}',
                        task_type='backup',
                        severity='error',
                    ))
                    _background_tasks.add(_task)
                    _task.add_done_callback(_background_tasks.discard)


def list_backup_files() -> list[dict]:  # log-context: internal helper 无请求上下文
    """列出服务器上的所有备份文件。

    返回条目同时携带 ``filename`` 与 ``mtime`` 两个字段：

    - ``filename`` 是对外序列化契约键 —— ``GET /backup/list`` 原样透传该条目，
      ``sync_backup_records`` 与 ``verify.query_service`` 也按此键消费，不可更名；
    - ``mtime`` 供校验/统计侧判定"最近备份时间"使用，语义与
      ``cleanup_old_backups`` 内部扫描保持同名同义。

    历史上漏发 ``mtime``（且校验侧按不存在的 ``name`` 取值）会让健康检查
    把"最近备份时间"算成 1970-01-01，凭空报出"超过24小时"告警。
    """
    backups = []
    if BACKUP_DIR.exists():
        for f in sorted(BACKUP_DIR.iterdir(), reverse=True):
            if not _is_backup_file(f):
                continue
            try:
                stat = f.stat()
            except OSError as e:
                # 保留策略可能在扫描期间删除文件，属良性竞态：跳过而非让整个列表失败
                logger.warning(f'跳过无法读取元信息的备份文件 {f.name}: {e}')
                continue
            entry: dict = {'filename': f.name, 'mtime': stat.st_mtime, 'size': stat.st_size}
            if f.name.endswith('.zip'):
                try:
                    with zipfile.ZipFile(f, 'r') as zf:
                        if 'manifest.json' in zf.namelist():
                            manifest = json.loads(zf.read('manifest.json'))
                            entry.update({
                                'format': manifest.get('type', 'zip'),
                                'exported_at': manifest.get('exported_at', ''),
                                'exported_by': manifest.get('exported_by', ''),
                                'remark': manifest.get('remark', ''),
                                'table_count': manifest.get('table_count', 0),
                                'total_rows': manifest.get('total_rows', 0),
                                'includes': manifest.get('includes', {}),
                                'base_timestamp': manifest.get('base_timestamp', ''),
                                'encrypted': manifest.get('encrypted', False),
                                # S4：完整性自述透传，供 sync 补录时判定真实状态
                                'failed_tables': manifest.get('failed_tables') or [],
                                'coverage': manifest.get('coverage'),
                            })
                except (OSError, zipfile.BadZipFile, ValueError) as e:
                    logger.warning(f'读取 ZIP 备份 {f.name} 失败: {e}')
                    entry['error'] = str(e)
            elif f.name.endswith('.zip.enc'):
                # 加密备份无法直接读 manifest，展示信息来自 .meta sidecar（P0-4）
                entry.update({'format': 'zip', 'encrypted': True})
                if meta := _read_backup_meta(f):
                    entry.update({
                        'type': meta.get('type', 'full'),
                        'exported_at': meta.get('created_at', ''),
                        'exported_by': meta.get('exported_by', ''),
                        'remark': meta.get('remark', ''),
                        'table_count': meta.get('table_count', 0),
                        'total_rows': meta.get('total_rows', 0),
                        'failed_tables': meta.get('failed_tables') or [],
                        'coverage': meta.get('coverage'),
                    })
            elif f.name.endswith('.json'):
                try:
                    data = json.loads(f.read_text(encoding='utf-8'))
                    entry.update({
                        'format': 'json',
                        'exported_at': data.get('exported_at', ''),
                        'exported_by': data.get('exported_by', ''),
                        'remark': data.get('remark', ''),
                        'table_count': len(data.get('tables', {})),
                        'total_rows': sum(t.get('count', len(t.get('rows', []))) for t in data.get('tables', {}).values()),
                        'failed_tables': data.get('failed_tables') or [],
                        'coverage': data.get('coverage'),
                    })
                except (OSError, json.JSONDecodeError, ValueError) as e:
                    logger.warning(f'读取 JSON 备份 {f.name} 失败: {e}')
                    entry['error'] = str(e)
            backups.append(entry)
    return backups


def get_backup_status() -> dict:  # log-context: internal helper 无请求上下文
    """获取备份系统状态概览"""
    from .verify import get_checksum_tables
    last_full: dict | None = None
    total_backups = 0
    total_size = 0
    if BACKUP_DIR.exists():
        # 按 mtime 取最近：文件名字典序会把 erp_auto_* 排到 erp_backup_* 之前，
        # 导致"上次备份"选中错误文件；同时只统计正式备份件，演练件不计入
        backup_files = sorted(
            (f for f in BACKUP_DIR.iterdir() if _is_backup_file(f)),
            key=lambda f: f.stat().st_mtime,
            reverse=True,
        )
        for f in backup_files:
            total_backups += 1
            total_size += f.stat().st_size
            if last_full:
                continue
            try:
                if f.name.endswith('.zip.enc'):
                    # 加密备份从 .meta sidecar 取类型与时间（P0-4）
                    meta = _read_backup_meta(f) or {}
                    if meta.get('type') == 'full' or (not meta and f.name.startswith('erp_backup_')):
                        last_full = {
                            'filename': f.name, 'size': f.stat().st_size,
                            'created_at': meta.get('created_at', ''),
                            'exported_at': meta.get('created_at', ''),
                            'exported_by': meta.get('exported_by', ''),
                            'remark': meta.get('remark', ''), 'type': 'full',
                            'table_count': meta.get('table_count', 0),
                            'total_rows': meta.get('total_rows', 0),
                            'encrypted': True,
                        }
                elif f.name.endswith('.zip'):
                    with zipfile.ZipFile(f, 'r') as zf:
                        if 'manifest.json' in zf.namelist():
                            mf = json.loads(zf.read('manifest.json'))
                            if mf.get('type') == 'full':
                                last_full = {
                                    'filename': f.name, 'size': f.stat().st_size,
                                    'created_at': datetime.fromtimestamp(
                                        f.stat().st_mtime).strftime('%Y-%m-%d %H:%M:%S'),
                                    'exported_at': mf.get('exported_at', ''),
                                    'exported_by': mf.get('exported_by', ''),
                                    'remark': mf.get('remark', ''), 'type': 'full',
                                    'table_count': mf.get('table_count', 0),
                                    'total_rows': mf.get('total_rows', 0),
                                }
            except (json.JSONDecodeError, OSError, ValueError) as e:
                logger.warning(f'解析备份清单失败: {e}')
                continue
    try:
        du = shutil.disk_usage(str(BACKUP_DIR))
        disk_usage_percent = round(du.used / du.total * 100, 1)
    except OSError:
        disk_usage_percent = None
    return {
        'success': True, 'backup_dir': str(BACKUP_DIR),
        'total_backups': total_backups, 'total_size_bytes': total_size,
        'last_full_backup': last_full,
        'disk_usage_percent': disk_usage_percent,
        'checksum_tables': sorted(get_checksum_tables()),
        # 状态 payload 只供展示/接口消费，用 aware UTC ISO（不参与解析/保留期比较）
        'timestamp': datetime.now(UTC).isoformat(),
    }


def validate_backup_file(content: bytes, filename: str) -> dict:  # log-context: internal helper 无请求上下文
    """验证备份文件，不执行恢复，仅返回摘要信息"""
    is_zip = filename.endswith('.zip') or content[:4] == b'PK\x03\x04'
    if is_zip:
        try:
            zf = zipfile.ZipFile(io.BytesIO(content))
        except zipfile.BadZipFile:
            raise BackupFileError('无效的 ZIP 文件') from None
        if 'manifest.json' not in zf.namelist():
            raise BackupFileError('ZIP 备份缺少 manifest.json')
        manifest = json.loads(zf.read('manifest.json'))
        names = zf.namelist()
        checksums_ok = True
        checksum_errors = []
        stored_checksums = manifest.get('checksums', {})
        for db_file in ['database/dump.sql.gz', 'database/dump.json']:
            if stored_checksums.get(db_file):
                actual = sha256_bytes(zf.read(db_file))  # REV-14
                if actual != stored_checksums[db_file]:
                    checksums_ok = False
                    checksum_errors.append(f'{db_file} 校验和不匹配')
        return {
            'format': 'zip', 'version': manifest.get('version'),
            'exported_at': manifest.get('exported_at'),
            'exported_by': manifest.get('exported_by'),
            'remark': manifest.get('remark', ''),
            'table_count': manifest.get('table_count'),
            'total_rows': manifest.get('total_rows'),
            'includes': manifest.get('includes', {}),
            'checksums_ok': checksums_ok, 'checksum_errors': checksum_errors,
            'zip_contents': {
                'has_database': 'database/dump.sql.gz' in names or 'database/dump.json' in names,
                'db_format': 'sql' if 'database/dump.sql.gz' in names else 'json' if 'database/dump.json' in names else 'none',
                'has_filestore': any(n.startswith('filestore/') for n in names),
                'has_config': any(n.startswith('config/') for n in names),
                'has_redis': 'redis/dump.rdb' in names,
                'has_meilisearch': any(n.startswith('meilisearch/') for n in names),
                'filestore_count': sum(1 for n in names if n.startswith('filestore/') and not n.endswith('/')),
                'config_files': [n for n in names if n.startswith('config/') and not n.endswith('/')],
            },
        }
    # JSON format
    try:
        backup_data = json.loads(content)
    except json.JSONDecodeError:
        raise BackupFileError('备份文件格式无效（非 ZIP 亦非有效 JSON）') from None
    if 'tables' not in backup_data:
        raise BackupFileError('JSON 备份文件缺少 tables 字段')
    from fastapi_app.shared_models import Base
    existing_tables = {str(t.name) for t in Base.metadata.sorted_tables}
    summary = {
        'format': 'json', 'version': backup_data.get('version'),
        'exported_at': backup_data.get('exported_at'),
        'exported_by': backup_data.get('exported_by'),
        'remark': backup_data.get('remark', ''),
        'table_count': len(backup_data['tables']),
        'total_rows': sum(t.get('count', len(t.get('rows', []))) for t in backup_data['tables'].values()),
        'checksums_ok': None, 'tables': [],
    }
    for table_name, table_data in backup_data['tables'].items():
        row_count = table_data.get('count', len(table_data.get('rows', [])))
        summary['tables'].append({
            'name': table_name, 'rows': row_count,
            'exists': table_name in existing_tables,
            'has_error': 'error' in table_data,
        })
    return summary


def delete_backup_file(filename: str) -> str:  # log-context: internal helper 无请求上下文
    """删除服务器上的指定备份文件"""
    safe_name = Path(filename).name
    if safe_name != filename:
        raise BackupFileError('无效的文件名')
    filepath = BACKUP_DIR / safe_name
    if not filepath.exists():
        raise BackupFileError('备份文件不存在')
    try:
        filepath.unlink()
    except (OSError, ValueError) as e:
        raise BackupFileError(f'删除备份文件失败: {e}') from e
    # 同步清理伴随文件（.meta + .record）。2026-10-17 审计 P2-16：此前只删 .meta，
    # 单文件删除会留下 .record 永久残留；复用批量清理路径的同一实现。
    _delete_backup_sidecars(filepath)
    return safe_name


def cleanup_pre_restore_backups():  # log-context: internal helper 无请求上下文
    """清理旧的恢复前安全备份（保留最近 5 个）"""
    if not PRE_RESTORE_DIR.exists():
        return
    backups = sorted(
        [f for f in PRE_RESTORE_DIR.iterdir() if f.is_file() and f.name.startswith('pre_restore_') and f.name.endswith('.zip')],
        key=lambda f: f.name, reverse=True
    )
    for old_backup in backups[_MAX_PRE_RESTORE_BACKUPS:]:
        try:
            old_backup.unlink()
            logger.info(f'已清理旧安全备份: {old_backup.name}')
        except OSError as e:
            logger.warning(f'清理旧安全备份失败: {old_backup.name}: {e}')


def _backup_created_time(f: Path) -> datetime:  # log-context: internal helper 无请求上下文
    """获取备份文件的真实创建时间。

    优先读取伴随的 ``.meta`` 文件中的 ``created_at``（加密备份的 mtime 可能被刷新，
    导致按文件系统 mtime 判定保留期不准）；无 meta 时回退到文件系统 mtime。

    ``created_at`` 的来源是 manifest 的 ``exported_at``（见本模块 :83），两种备份口径不同：

      · **全量** —— ``orchestration/core.py`` 的 ``datetime.now()``，**本地 naive**；
      · **历史增量** —— 增量模块已删除，不再产出；历史增量包曾用 ``datetime.now(UTC)``。
        现行备份只有全量口径，下面的 UTC 偏差说明仅用于解释存量文件。

    本函数按 naive 本地时间解析，于是：

      · 全量包两侧同为本地时间，**无偏差**（旧注释称"全量也差 8 小时"不成立）；
      · 增量包把 UTC 墙面时刻当本地解析，本机 UTC+8 下算出的「年龄」**多算 8 小时**，
        即比真实时间**提前约 8 小时**删除 —— 方向是提前删，**不是**旧注释写的
        「更晚删（fail-safe）」。范围也有限（8 小时 vs 30 天窗口），但方向必须说对。
    要根治应统一时区：写入一律 UTC，读取也按 UTC 解析后再比。
    """
    meta_path = f.parent / (f.name + '.meta')
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding='utf-8'))
            created_at = meta.get('created_at')
            if created_at:
                return datetime.strptime(created_at, '%Y-%m-%d %H:%M:%S')
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            pass  # defensive: 异常静默处理,不影响主流程
    return datetime.fromtimestamp(f.stat().st_mtime)


def _delete_backup_sidecars(filepath: Path, errors: list[str] | None = None) -> list[str]:
    """删除备份文件的伴随文件（.meta 元数据与 .record 记录）。

    历史实现只删 .meta（且只在主文件删除成功后顺序执行），导致「删了 .enc 但
    .zip.enc.meta / .record 永久残留」。这里统一两个伴随后缀，且对每个后缀单独
    容错 —— 一个伴随文件删除失败不影响另一个，也不影响主文件已删除的事实。

    F-05（P1-residual）：删除失败不再只是 warning —— 以 ERROR 记日志，并在调用方
    传入 errors 聚合器时把失败项写进清理结果（cleanup_old_backups() 的 errors），
    使此前「伴随文件残留只留在日志里」的静默部分失败变成可观测结果。
    errors 缺省 None 时返回值语义与旧版完全一致（成功删除名列表），既有调用方
    不传聚合器即维持原行为。

    Args:
        filepath: 主备份文件路径；伴随文件名为 filepath.name + '.meta' / '.record'。
        errors: 可选失败聚合列表；传入时以
            '伴随文件清理失败 <伴随文件名>: <异常>' 追加失败项。

    Returns: 成功删除的伴随文件名列表
    """
    removed = []
    for suffix in ('.meta', '.record'):
        sidecar = filepath.parent / (filepath.name + suffix)
        try:
            if sidecar.exists():
                sidecar.unlink()
                removed.append(sidecar.name)
        except OSError as e:
            logger.error(f'清理备份伴随文件失败: {sidecar.name}: {e}')
            if errors is not None:
                errors.append(f'伴随文件清理失败 {sidecar.name}: {e}')
    return removed


async def sync_backup_records() -> dict:
    """启动时同步文件系统与数据库备份记录（双向）。

    - 补录：文件存在但 DB 无记录 → 根据 manifest/.meta 补写 BackupRecord
    - 清理孤立：DB 有记录但文件不存在 → 删除记录
    - 修正僵尸：status='running' 但文件已存在且进程已结束 → 更新为 'unknown'
      （文件存在不等于内容完整；S4 起不再把中断的备份洗成 success）

    幂等保证：多次运行结果一致（已存在的记录跳过，已删除的孤立不再出现，
    已修正的僵尸状态不再为 running）。

    Returns:
        dict: {'backfilled': N, 'orphaned': N, 'zombie_fixed': N, 'errors': [...]}
    """
    # 延迟导入避免循环依赖
    from sqlalchemy import delete as sa_delete
    from sqlalchemy import select

    from fastapi_app.core.database import get_async_db_context
    from fastapi_app.services.backup.verify.query_service import (
        _infer_trigger_type_from_filename,
        _infer_type_from_filename,
        _parse_exported_at,
        _parse_timestamp_from_filename,
    )
    from fastapi_app.shared_models.backup_record import BackupRecord

    result: dict = {'backfilled': 0, 'orphaned': 0, 'zombie_fixed': 0, 'errors': []}

    # 1. 扫描文件系统所有备份文件
    try:
        fs_files = list_backup_files()
    except Exception as e:  # defensive: 文件系统扫描失败不阻塞同步
        result['errors'].append(f'list_backup_files 失败: {e}')
        return result

    fs_filenames = {f['filename'] for f in fs_files if f.get('filename')}

    # 2. 自建数据库会话执行双向同步
    try:
        async with get_async_db_context() as db:
            # 查询所有 BackupRecord，构建 filename → record 映射
            try:
                rows = (await db.execute(select(BackupRecord))).scalars().all()
            except Exception as e:  # defensive: 启动同步容错，失败不得阻断应用启动
                logger.error('备份记录同步：查询 BackupRecord 失败: %s', e, exc_info=True)
                result['errors'].append(f'查询 BackupRecord 失败: {e}')
                return result

            record_by_filename: dict[str, object] = {}
            for r in rows:
                if r.filename:
                    record_by_filename[r.filename] = r

            # 2a. 补录：文件存在但 DB 无记录
            for fs_entry in fs_files:
                fname = fs_entry.get('filename')
                if not fname or fname in record_by_filename:
                    continue
                try:
                    # 推断备份类型：优先用 .meta 中的 type，其次文件名推断
                    record_type = fs_entry.get('type') or _infer_type_from_filename(fname)
                    trigger_type = _infer_trigger_type_from_filename(fname)
                    # 解析创建时间：优先 exported_at，其次文件名时间戳
                    created_at = _parse_exported_at(fs_entry.get('exported_at'))
                    if created_at is None:
                        created_at = _parse_timestamp_from_filename(fname)
                    # S4：不再无条件记 success。产物自述缺失表/覆盖度不足 → partial，
                    # 并把缺失表名写进 remark，避免「文件在就算成功」。
                    sync_status, sync_detail = evaluate_backup_completeness(fs_entry)
                    record = BackupRecord(
                        type=record_type,
                        trigger_type=trigger_type,
                        filename=fname,
                        size=fs_entry.get('size'),
                        table_count=fs_entry.get('table_count'),
                        total_rows=fs_entry.get('total_rows'),
                        operator=fs_entry.get('exported_by') or 'system_sync',
                        remark=compose_remark(fs_entry.get('remark', ''), sync_detail),
                        status=sync_status,
                        encrypted=fs_entry.get('encrypted', False),
                        created_at=created_at,
                    )
                    db.add(record)
                    await db.flush()
                    await db.commit()  # 每条补录成功后立即提交，避免后续失败回滚已成功记录
                    result['backfilled'] += 1
                except Exception as e:  # defensive: 单条失败不阻塞后续同步
                    logger.warning('备份记录同步：补录 %s 失败: %s', fname, e)
                    result['errors'].append(f'补录 {fname} 失败: {e}')
                    with contextlib.suppress(Exception):  # defensive: rollback 失败不阻塞后续同步
                        await db.rollback()

            # 2b. 清理孤立：DB 有记录但文件不存在
            for r in rows:
                if r.filename and r.filename not in fs_filenames:
                    try:
                        await db.execute(sa_delete(BackupRecord).where(BackupRecord.id == r.id))
                        await db.commit()  # 每条删除成功后立即提交，避免后续失败回滚已成功记录
                        result['orphaned'] += 1
                    except Exception as e:  # defensive: 单条失败不阻塞后续同步
                        logger.warning('备份记录同步：清理孤立记录 %s 失败: %s', r.filename, e)
                        result['errors'].append(f'清理孤立记录 {r.filename} 失败: {e}')
                        with contextlib.suppress(Exception):  # defensive: rollback 失败不阻塞后续同步
                            await db.rollback()

            # 2c. 修正僵尸：status='running' 且对应文件存在 → 更新为 'unknown'
            #     文件存在只证明「进程写下过这个文件」，不证明内容完整（可能半截）。
            #     旧实现直接判 success，等于把「中断的备份」洗成「成功」，
            #     故改记 unknown 并在 remark 标注推断来源，待人工/校验流程确认。
            for r in rows:
                if r.status == 'running' and r.filename and r.filename in fs_filenames:
                    try:
                        r.status = STATUS_UNKNOWN
                        r.remark = compose_remark(
                            r.remark, '文件存在但内容完整性未经校验（启动同步推断）'
                        )
                        await db.flush()
                        await db.commit()  # 每条修正成功后立即提交，避免后续失败回滚已成功记录
                        result['zombie_fixed'] += 1
                    except Exception as e:  # defensive: 单条失败不阻塞后续同步
                        logger.warning('备份记录同步：修正僵尸记录 %s 失败: %s', r.filename, e)
                        result['errors'].append(f'修正僵尸记录 {r.filename} 失败: {e}')
                        with contextlib.suppress(Exception):  # defensive: rollback 失败不阻塞后续同步
                            await db.rollback()
    except Exception as e:  # defensive: 启动同步容错，失败不得阻断应用启动
        logger.error('备份记录同步：同步过程异常: %s', e, exc_info=True)
        result['errors'].append(f'同步过程异常: {e}')

    return result
