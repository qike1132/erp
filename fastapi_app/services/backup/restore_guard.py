"""恢复中断标记（P0-5，2026-10-24 审计；B2 fail-closed 收口 2026-10-26）。

问题：`restore_database_via_psql` 的破坏性动作（DROP DATABASE）在导入之前提交，
数据写回是后一次独立的单事务 psql 导入。两次提交之间进程被杀/服务重启，数据库会
停在「已建空壳」，且没有任何组件知道该回滚。

本模块只做两件低风险的事（不改恢复语义、不自动还原）：
1. 在 DROP 之前落一个标记文件（库名 / 时间 / task_id / 当时的 pre_restore 快照名）；
2. 启动与 readiness 检查时若标记仍在（或不可读），明确报「需要人工恢复」。

为什么不做「启动自动回滚」：自动还原会再次 DROP 数据库，且在服务启动路径上做整库
还原会把「启动慢」变成「启动即长时间不可用」，风险高于收益。标记 + 告警 + 明确指引
是这一步能给的最小可靠改进；临时库 + RENAME 的原子切换方案需要真实库演练后再上。

B2（2026-10-26 上线前检查）三处 fail-open 收口：
* 写标记失败原先只 warning，随后照样 DROP —— 现在抛 ``RestoreMarkerError``，
  调用方必须在 DROP 之前中止（无保护的破坏性操作不允许发生）。
* 清除原先在通用 finally 中无条件执行 —— 现在只有确认导入成功且校验通过才清除；
  失败保留并把失败阶段写回标记，供下次启动与 readiness 使用。
* 读取原先 I/O 失败返回 None，把「未知」折叠成「无中断」—— 现在三态
  （absent / present / unknown），unknown 与 present 一样让 readiness 失败，
  但**不阻断进程启动**，以保留 `/api/v1/backup/restore*` 这条受控恢复通道。
"""
from __future__ import annotations

import contextlib
import json
import logging
import os
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi_app.services.backup._constants import BACKUP_DIR, PRE_RESTORE_DIR

logger = logging.getLogger(__name__)

MARKER_NAME = '.restore_in_progress.json'

#: 标记文件的三态。unknown 与 present 一样需要人工确认，不得折叠成「无中断」。
MARKER_ABSENT = 'absent'
MARKER_PRESENT = 'present'
MARKER_UNKNOWN = 'unknown'

# readiness 会高频轮询本模块，异常态日志按 5 分钟节流，避免日志洪泛掩盖其它信号。
_STATE_WARN_INTERVAL = 300.0
_last_state_warn_at = 0.0


def _warn_state(message: str, *args: Any) -> None:
    global _last_state_warn_at
    now = time.monotonic()
    if now - _last_state_warn_at < _STATE_WARN_INTERVAL:
        return
    _last_state_warn_at = now
    logger.error(message, *args)


class RestoreMarkerError(RuntimeError):
    """恢复中断标记无法可靠落盘（调用方必须在 DROP 之前中止）。"""


def marker_path() -> Path:
    """标记文件路径（放在备份根目录，与 pre_restore/ 同级，便于运维一眼看到）。"""
    return Path(BACKUP_DIR) / MARKER_NAME


def _latest_pre_restore() -> str | None:
    try:
        files = sorted(
            (p for p in Path(PRE_RESTORE_DIR).glob('pre_restore_*') if p.is_file()),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        return files[0].name if files else None
    except OSError:
        return None


def _atomic_write_json(payload: dict[str, Any], target: Path) -> None:
    """同目录临时文件 + fsync + os.replace：要么旧内容，要么新内容，不会半截。"""
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.restore_marker_', dir=str(target.parent))
    try:
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as fh:
                json.dump(payload, fh, ensure_ascii=False, indent=2)
                fh.flush()
                os.fsync(fh.fileno())
        except BaseException:
            # fdopen 失败时 fd 未托管，显式关闭避免句柄泄漏
            with contextlib.suppress(OSError):
                os.close(fd)
            raise
        os.replace(tmp, target)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def mark_restore_started(db_name: str, task_id: str | None = None) -> Path:
    """在 DROP DATABASE 之前落标记，并回读校验。

    失败即抛 ``RestoreMarkerError`` —— 调用方必须先中止恢复。历史行为是「写失败只
    warning，然后照样 DROP」，等于破坏性操作完全没有中断保护。
    """
    payload: dict[str, Any] = {
        'started_at': datetime.now(UTC).isoformat(),
        'db_name': db_name,
        'task_id': task_id,
        'latest_pre_restore': _latest_pre_restore(),
        'stage': 'drop_pending',
        'hint': (
            '若本文件在服务启动后仍存在，说明上一次还原在 DROP 之后、导入完成之前中断，'
            '数据库可能是空壳。人工回滚：POST /api/v1/backup/restore-by-name/<latest_pre_restore>?confirm=true，'
            '或 psql 直接导入该 pre_restore 包内的 database/dump.sql.gz。'
        ),
    }
    target = marker_path()
    try:
        _atomic_write_json(payload, target)
    except OSError as e:
        raise RestoreMarkerError(f'恢复中断标记无法落盘（{target}）：{e}') from e

    # 回读校验：写"成功"但内容读不出来，和没写是一样的。
    state, data = read_marker_state()
    if state != MARKER_PRESENT or not data or data.get('started_at') != payload['started_at']:
        raise RestoreMarkerError(
            f'恢复中断标记回读校验失败（{target}，state={state}）——拒绝在无保护的情况下重建数据库'
        )
    return target


def mark_restore_finished(*, success: bool, failure_stage: str | None = None) -> bool:
    """还原结束：**只有确认成功**才清除标记；失败保留并写回失败阶段。

    返回是否达到预期状态（成功即已清除；失败即标记仍在）。调用方不必据此改变
    恢复返回值，但必须让失败阶段可见（日志 + 下次启动 / readiness）。
    """
    target = marker_path()
    if success:
        try:
            target.unlink(missing_ok=True)
        except OSError as e:
            logger.error('还原已成功但清除标记失败（下次启动会误报中断）: %s', e)
            return False
        return True

    state, data = read_marker_state()
    if state == MARKER_ABSENT:
        logger.error(
            '还原失败（阶段=%s）但标记文件已不存在：中断保护缺失，请人工核对数据库完整性',
            failure_stage or 'unknown',
        )
        return False
    payload = dict(data or {})
    payload['failed_at'] = datetime.now(UTC).isoformat()
    payload['failed_stage'] = failure_stage or 'unknown'
    try:
        _atomic_write_json(payload, target)
    except OSError as e:
        logger.error('还原失败（阶段=%s）且更新标记失败，保留原标记: %s',
                     failure_stage or 'unknown', e)
        return False
    logger.error('还原失败（阶段=%s），已保留恢复中断标记供下次启动告警: %s',
                 failure_stage or 'unknown', target)
    return True


def read_marker_state() -> tuple[str, dict[str, Any] | None]:
    """读取标记的三态结果 ``(state, payload)``。

    * ``absent``  —— 文件确实不存在（唯一可以判定「没有中断中的还原」的情况）；
    * ``present`` —— 文件存在（含 JSON 损坏：损坏本身就是需要人工处理的异常态）；
    * ``unknown`` —— 存在性/可读性无法确认（I/O、编码、权限），**不得**当作无中断。
    """
    target = marker_path()
    try:
        raw = target.read_text(encoding='utf-8')
    except FileNotFoundError:
        return MARKER_ABSENT, None
    except (OSError, UnicodeDecodeError) as e:
        _warn_state('恢复中断标记不可读（状态未知，按「有中断」处理）: %s', e)
        return MARKER_UNKNOWN, None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        _warn_state('恢复中断标记 JSON 损坏，按「有中断」处理: %s', target)
        return MARKER_PRESENT, {'raw': raw[:500], 'parse_error': True}
    if not isinstance(data, dict):
        return MARKER_PRESENT, {'raw': raw[:500], 'parse_error': True}
    return MARKER_PRESENT, data


def check_interrupted_restore() -> dict[str, Any]:
    """启动时调用：残留/不可读标记打 CRITICAL 并返回结构化状态。不抛异常。

    刻意不在这里 ``raise`` 阻断启动：进程起不来就再也没有受控恢复入口。业务流量
    的拦截交给 readiness（见 ``restore_readiness``），恢复端点保持可用。
    """
    state, data = read_marker_state()
    if state == MARKER_ABSENT:
        return {'state': state, 'recovery_required': False}

    if state == MARKER_UNKNOWN:
        logger.critical(
            '无法确认上次数据库还原是否完成（标记 %s 不可读）。数据库可能是空壳，'
            '业务 readiness 将保持失败；请先核对 %s 与库内业务表行数。',
            marker_path(), marker_path(),
        )
        return {'state': state, 'recovery_required': True, 'reason': 'marker_unreadable'}

    logger.critical(
        '检测到未完成的数据库还原（%s）：库名=%s 开始于=%s 失败阶段=%s 回滚点=%s。'
        '数据库可能停在「已建空壳」，请立即核对业务表行数并按 %s 回滚。',
        marker_path(), data.get('db_name'), data.get('started_at'),
        data.get('failed_stage'), data.get('latest_pre_restore'), data.get('hint'),
    )
    return {'state': state, 'recovery_required': True, 'marker': data}


def restore_readiness() -> dict[str, Any]:
    """正常业务 readiness 判据：残留或不可读标记都必须让 readiness 失败。

    只影响 readiness，不影响进程存活与恢复端点 —— 「数据库可能是空壳」时继续给
    业务流量开门，比暂时不可用更危险；而锁死恢复入口则会让运维无从清除标记。
    """
    state, data = read_marker_state()
    if state == MARKER_ABSENT:
        return {'ok': True, 'state': state}
    data = data or {}
    return {
        'ok': False,
        'state': state,
        'db_name': data.get('db_name'),
        'started_at': data.get('started_at'),
        'failed_stage': data.get('failed_stage'),
        'latest_pre_restore': data.get('latest_pre_restore'),
        'hint': data.get('hint'),
    }
