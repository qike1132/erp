"""领域事件/ARQ 死信巡检任务（M-C，2026-10-25 审计）。

``logs/domain_events_deadletter.jsonl`` 与 Redis DLQ（``arq:dead_letter``）此前
只增不消费——H-1 出货同步断流 3 天无人发现的直接后果（408 条错误日志只落本地
文件，CRITICAL「需人工介入」也只是日志行）。本任务每日巡检一次并接入
``alert_service``：一旦 owner 配置了邮件/Webhook（``BACKUP_ALERT_*_ENABLED``），
死信与任务失败即自动外推，不再依赖人翻日志。

分级：
- handler 级死信（stage=handler/handler_cross_process）> 0 → critical 告警。
  2026-10-22 型 ImportError 静默吞单即此类，必须人工介入/重放；
- ARQ DLQ 非空 → warning 告警。终态失败已由 on_job_end 逐条告警，这里是
  兜底提示「DLQ 有残留未处理」；
- 广播死信（无 stage 字段）只计数不打扰：多为 Redis 重启窗口，量大时用
  CLI 工具 ``scripts/inspect_deadletter.py`` 看全量明细再决定是否重放。
"""
from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi_app.core.logger import logger

#: 与 core/domain_events.py 的死信落点同口径（repo 根 / logs）
DEADLETTER_FILENAME = 'domain_events_deadletter.jsonl'

#: Redis 死信队列键（与 core/arq_callbacks.py DLQ_KEY 同口径）
ARQ_DLQ_KEY = 'arq:dead_letter'

HANDLER_STAGES = ('handler', 'handler_cross_process')


def default_deadletter_path() -> Path:
    return Path(__file__).resolve().parents[2] / 'logs' / DEADLETTER_FILENAME


def summarize_deadletter(path: Path, since: datetime) -> dict:
    """扫描死信文件，返回 ``since`` 之后的分级计数与 handler 样本。

    坏行跳过（不因单行损坏让巡检崩溃），与 CLI 工具同一容错口径。
    """
    handler_records: list[dict] = []
    broadcast_count = 0
    total = 0
    if not path.exists():
        return {'total': 0, 'handler_count': 0, 'broadcast_count': 0, 'handler_samples': []}
    with open(path, encoding='utf-8') as f:
        for raw in f:
            stripped = raw.strip()
            if not stripped:
                continue
            try:
                rec = json.loads(stripped)
            except json.JSONDecodeError:
                continue
            total += 1
            try:
                ts = datetime.fromisoformat(str(rec.get('ts', '')))
            except ValueError:
                continue
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=UTC)
            if ts < since:
                continue
            stage = str(rec.get('stage', '') or '')
            if stage in HANDLER_STAGES:
                handler_records.append(rec)
            else:
                broadcast_count += 1
    return {
        'total': total,
        'handler_count': len(handler_records),
        'broadcast_count': broadcast_count,
        'handler_samples': handler_records[:5],
    }


async def _redis_dlq_length() -> int:
    """ARQ 死信队列长度；Redis 不可用时报 0 并由调用方日志留痕。"""
    from fastapi_app.core.redis_wrapper import safe_get

    entries = await safe_get(ARQ_DLQ_KEY, [], context='死信巡检')
    return len(entries) if isinstance(entries, list) else 0


def _sample_desc(records: list[dict]) -> str:
    parts = []
    for rec in records[:3]:
        parts.append(
            f"{rec.get('ts', '?')} {rec.get('stage')} {rec.get('handler', '?')}: "
            f"{str(rec.get('error'))[:100]}"
        )
    return ' | '.join(parts)


async def run_deadletter_patrol(now: datetime | None = None) -> dict:
    """执行一次巡检，返回结果摘要；发现需人工介入的死信即发告警。"""
    now = now or datetime.now(UTC)
    since = now - timedelta(hours=24)
    summary = await asyncio.to_thread(
        summarize_deadletter, default_deadletter_path(), since
    )
    dlq_len = await _redis_dlq_length()
    result = {**summary, 'arq_dlq_len': dlq_len}

    from fastapi_app.services.backup.metrics.alert_service import alert_service

    if summary['handler_count'] > 0:
        logger.error(
            '死信巡检：发现 %d 条 handler 级死信（近24h）：%s',
            summary['handler_count'], _sample_desc(summary['handler_samples']),
        )
        await alert_service.send_alert(
            task_name='deadletter-patrol',
            error=(
                f"近24h新增 {summary['handler_count']} 条 handler 级死信，"
                f'数据链路受损需人工介入/重放：{_sample_desc(summary["handler_samples"])}'
            ),
            task_type='deadletter_patrol',
            severity='critical',
            additional_info={k: result[k] for k in ('handler_count', 'broadcast_count', 'arq_dlq_len')},
        )
    elif dlq_len > 0:
        logger.warning('死信巡检：ARQ DLQ 残留 %d 条未处理', dlq_len)
        await alert_service.send_alert(
            task_name='deadletter-patrol',
            error=f'ARQ 死信队列残留 {dlq_len} 条终态失败任务未处理（详见 arq:dead_letter）',
            task_type='deadletter_patrol',
            severity='warning',
            additional_info={'arq_dlq_len': dlq_len},
        )
    else:
        logger.info(
            '死信巡检：无 handler 死信、DLQ 为空（近24h广播死信 %d 条，累计 %d 条）',
            summary['broadcast_count'], summary['total'],
        )
    return result


async def inspect_deadletter_task(ctx: dict) -> dict:
    """ARQ 每日巡检入口（cron：每日 06:30）。"""
    result = await run_deadletter_patrol()
    return {'success': True, **result}
