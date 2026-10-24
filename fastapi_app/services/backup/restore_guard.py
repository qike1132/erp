"""恢复中断标记（P0-5，2026-10-24 审计）。

问题：`restore_database_via_psql` 的破坏性动作（DROP DATABASE）在导入之前提交，
数据写回是后一次独立的单事务 psql 导入。两次提交之间进程被杀/服务重启，数据库会
停在「已建空壳」，且没有任何组件知道该回滚。

本模块只做两件低风险的事（不改恢复语义、不自动还原）：
1. 在 DROP 之前落一个标记文件（库名 / 时间 / task_id / 当时的 pre_restore 快照名）；
2. 启动时若标记仍在，打 CRITICAL 并给出可执行的人工回滚指引。

为什么不做「启动自动回滚」：自动还原会再次 DROP 数据库，且在服务启动路径上做整库
还原会把「启动慢」变成「启动即长时间不可用」，风险高于收益。标记 + 告警 + 明确指引
是这一步能给的最小可靠改进；临时库 + RENAME 的原子切换方案需要真实库演练后再上。
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi_app.services.backup._constants import BACKUP_DIR, PRE_RESTORE_DIR

logger = logging.getLogger(__name__)

MARKER_NAME = '.restore_in_progress.json'


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


def mark_restore_started(db_name: str, task_id: str | None = None) -> None:
    """在 DROP DATABASE 之前落标记。任何失败都只告警，不阻断恢复本身。"""
    payload: dict[str, Any] = {
        'started_at': datetime.now(UTC).isoformat(),
        'db_name': db_name,
        'task_id': task_id,
        'latest_pre_restore': _latest_pre_restore(),
        'hint': (
            '若本文件在服务启动后仍存在，说明上一次还原在 DROP 之后、导入完成之前中断，'
            '数据库可能是空壳。人工回滚：POST /api/v1/backup/restore-by-name/<latest_pre_restore>?confirm=true，'
            '或 psql 直接导入该 pre_restore 包内的 database/dump.sql.gz。'
        ),
    }
    try:
        target = marker_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix='.restore_marker_', dir=str(target.parent))
        with os.fdopen(fd, 'w', encoding='utf-8') as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, target)
    except OSError as e:
        logger.warning('写恢复中断标记失败（不影响还原）: %s', e)


def mark_restore_finished() -> None:
    """导入结束（无论成败）后清除标记。"""
    try:
        marker_path().unlink(missing_ok=True)
    except OSError as e:
        logger.warning('清除恢复中断标记失败: %s', e)


def read_marker() -> dict[str, Any] | None:
    try:
        raw = marker_path().read_text(encoding='utf-8')
    except (OSError, UnicodeDecodeError):
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {'raw': raw, 'parse_error': True}
    return data if isinstance(data, dict) else None


def check_interrupted_restore() -> dict[str, Any] | None:
    """启动时调用：发现残留标记则打 CRITICAL 并返回内容。不抛异常、不阻断启动。"""
    data = read_marker()
    if not data:
        return None
    logger.critical(
        '检测到未完成的数据库还原（%s）：库名=%s 开始于=%s 回滚点=%s。'
        '数据库可能停在「已建空壳」，请立即核对业务表行数并按 %s 回滚。',
        marker_path(), data.get('db_name'), data.get('started_at'),
        data.get('latest_pre_restore'), data.get('hint'),
    )
    return data
