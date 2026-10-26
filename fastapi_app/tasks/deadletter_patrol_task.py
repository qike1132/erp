"""领域事件/ARQ 死信巡检任务（M-C，2026-10-25 审计）。

``logs/domain_events_deadletter.jsonl`` 与 Redis DLQ（``arq:dead_letter``）此前
只增不消费——H-1 出货同步断流 3 天无人发现的直接后果（408 条错误日志只落本地
文件，CRITICAL「需人工介入」也只是日志行）。本任务每日巡检一次并接入
``alert_service``：一旦 owner 配置了邮件/Webhook（``BACKUP_ALERT_*_ENABLED``），
死信与任务失败即自动外推，不再依赖人翻日志。

分级（M1/M3/M4，2026-10-25 上线前检查修订）：
- handler 级死信（stage=handler/handler_cross_process）> 0 → critical 告警。
  2026-10-22 型 ImportError 静默吞单即此类，必须人工介入/重放；
  外发文本只含 handler/event_type 等结构化字段，**不含异常原文**（M4：
  截断不等于脱敏，详情在受保护的内部日志与死信文件里）；
- ARQ DLQ 非空 → critical 告警（M3：原 warning 受 failure_threshold=3 约束，
  首两次日检不外发，残留可能长期静默；critical 首次即外发）；
- Redis DLQ 状态不可知（client 缺失/连接失败）→ critical 告警 + 任务记失败
  （M1：unknown 洗成「空队列」是假健康，必须显式失败）；
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


async def _redis_dlq_length() -> int | None:
    """ARQ 死信队列长度；Redis 不可用时返回 None（状态不可知，M1）。

    必须用 ``safe_llen_ex``——``arq:dead_letter`` 是 List（``safe_lpush`` 写入），
    用 GET 读会 WRONGTYPE 且被底层缓存层吞成 None，恒报 0（评审 H-1）。
    三态版：None = 查不出来（client 缺失/连接失败），与「真实空队列」严格区分，
    调用方按显式失败处理，不得当 0 用。
    """
    from fastapi_app.core.redis_wrapper import safe_llen_ex

    return await safe_llen_ex(ARQ_DLQ_KEY, context='死信巡检')


def _sample_desc(records: list[dict]) -> str:
    parts = []
    for rec in records[:3]:
        parts.append(
            f"{rec.get('ts', '?')} {rec.get('stage')} {rec.get('handler', '?')}: "
            f"{str(rec.get('error'))[:100]}"
        )
    return ' | '.join(parts)


async def run_deadletter_patrol(now: datetime | None = None) -> dict:
    """执行一次巡检，返回结果摘要；发现需人工介入的死信即发告警。

    返回 dict 含 ``dlq_status``：'ok'（Redis 可用）/ 'unknown'（查不出来）。
    unknown 时调用方（inspect_deadletter_task）将任务记为失败。
    """
    now = now or datetime.now(UTC)
    since = now - timedelta(hours=24)
    summary = await asyncio.to_thread(
        summarize_deadletter, default_deadletter_path(), since
    )
    dlq_len = await _redis_dlq_length()
    dlq_status = 'unknown' if dlq_len is None else 'ok'
    result = {**summary, 'arq_dlq_len': dlq_len, 'dlq_status': dlq_status}

    from fastapi_app.services.backup.metrics.alert_service import alert_service

    if summary['handler_count'] > 0:
        # 内部日志保留样本原文（受保护日志，含 error 字段）供排查；
        # 外发告警只给结构化字段（M4：异常原文可能携带参数/标识等敏感片段）。
        logger.error(
            '死信巡检：发现 %d 条 handler 级死信（近24h）：%s',
            summary['handler_count'], _sample_desc(summary['handler_samples']),
        )
        handlers = sorted({str(r.get('handler', '?')) for r in summary['handler_samples']})
        await alert_service.send_alert(
            task_name='deadletter-patrol',
            error=(
                f"近24h新增 {summary['handler_count']} 条 handler 级死信，"
                f'数据链路受损需人工介入/重放。涉及 handler: {", ".join(handlers)}。'
                f'明细见 logs/{DEADLETTER_FILENAME} 与内部日志'
            ),
            task_type='deadletter_patrol',
            severity='critical',
            additional_info={k: result[k] for k in ('handler_count', 'broadcast_count', 'arq_dlq_len')},
        )
    elif dlq_len is None:
        # M1：unknown ≠ 空队列。Redis 状态不可知时巡检结论无效，必须 critical
        # 外发（critical 恒通知，不依赖失败计数），并由任务层记失败。
        logger.error('死信巡检：Redis DLQ 状态不可知（client 缺失或连接失败），本轮巡检结论无效')
        await alert_service.send_alert(
            task_name='deadletter-patrol',
            error='死信巡检无法读取 Redis DLQ（连接失败或客户端不可用）——'
                  '残留死信可能正在静默累积，请检查 erp-redis/erp-redis-broker 服务',
            task_type='deadletter_patrol',
            severity='critical',
            additional_info={'arq_dlq_len': None, 'dlq_status': 'unknown'},
        )
    elif dlq_len > 0:
        # M3：升 critical。warning 走通用失败计数（threshold=3），每日一跑的
        # 巡检头两次不外发——残留死信可静默一周以上。critical 首次即外发。
        logger.warning('死信巡检：ARQ DLQ 残留 %d 条未处理', dlq_len)
        await alert_service.send_alert(
            task_name='deadletter-patrol',
            error=f'ARQ 死信队列残留 {dlq_len} 条终态失败任务未处理（详见 arq:dead_letter）',
            task_type='deadletter_patrol',
            severity='critical',
            additional_info={'arq_dlq_len': dlq_len},
        )
    else:
        logger.info(
            '死信巡检：无 handler 死信、DLQ 为空（近24h广播死信 %d 条，累计 %d 条）',
            summary['broadcast_count'], summary['total'],
        )
    return result


async def inspect_deadletter_task(ctx: dict) -> dict:
    """ARQ 每日巡检入口（cron：每日 06:30）。

    Redis DLQ 状态不可知时按失败收尾（``status='error'`` → _tracked_job 记
    failed → on_job_end 失败链 critical 告警；M1：巡检自身失败必须可见）。
    """
    result = await run_deadletter_patrol()
    if result.get('dlq_status') == 'unknown':
        return {
            'status': 'error',
            'success': False,
            'error': 'Redis DLQ 状态不可知，本轮巡检结论无效',
            **result,
        }
    return {'success': True, **result}
