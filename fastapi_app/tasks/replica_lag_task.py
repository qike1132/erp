"""只读副本延迟巡检（ARQ cron，OPT-16 收编项）。

背景：主机上有同机热备副本（postgresql-replica，5433，应用读流量已接入
ASYNC_DATABASE_REPLICA_URL）。副本若悄悄断流，报表/列表的读流量会一直读到
越来越旧的数据而无任何告警——本任务周期采集 ``now() - pg_last_xact_replay_timestamp()``
并按阈值打日志（warning 级别，接入既有日志维护/告警链路）。

行为约定：
- 主库空闲时段副本按 restartpoint 节奏回放，lag 出现分钟级波动属正常
  （实测空闲库 30-60s）；超 5 分钟才告警。
- 主库完全无写入时 ``pg_last_xact_replay_timestamp()`` 可能返回 NULL
  （从未回放过事务），视作正常跳过，不误报。
- 连接失败（副本进程挂掉）按 ERROR 记录——这是比 lag 超阈更严重的信号，
  但 ARQ 任务本身不抛错退出（下一轮 cron 继续探测，避免 max_tries 耗尽
  后任务被丢弃而监控静默失效）。

复制槽（primary_slot_name）未配置的原因与主库侧操作步骤见
docs/analysis/09_postgresql_replica_investigation_2026-10-01.md §3.1。
"""
import logging

from fastapi_app.core.config import settings

logger = logging.getLogger(__name__)

#: 延迟告警阈值（秒）
REPLICA_LAG_WARN_SECONDS = 300


async def replica_lag_task(ctx: dict) -> dict:
    """采集只读副本回放延迟，超阈值告警。返回供 ARQ 健康统计的结果摘要。"""
    from urllib.parse import unquote, urlparse

    import asyncpg

    url = settings.ASYNC_DATABASE_REPLICA_URL
    if not url:
        logger.info("未配置只读副本（ASYNC_DATABASE_REPLICA_URL 为空），跳过延迟巡检")
        return {'skipped': 'no-replica-url'}

    # 复用重定向后的副本 URL：把 asyncpg 驱动 URL 解析为连接参数
    parsed = urlparse(url.replace('postgresql+asyncpg://', 'postgresql://'))
    dbname = parsed.path.lstrip('/')
    try:
        conn = await asyncpg.connect(
            host=parsed.hostname or '127.0.0.1',
            port=parsed.port or 5433,
            user=parsed.username,
            password=unquote(parsed.password or ''),
            database=dbname,
            timeout=8,
            statement_cache_size=0,
        )
    except (OSError, ConnectionError) as e:
        logger.error("只读副本无法连接（复制可能已断流）: %s", e)
        return {'ok': False, 'error': 'connect-failed'}

    try:
        await conn.execute("SET statement_timeout='8s'")
        in_recovery = await conn.fetchval('SELECT pg_is_in_recovery()')
        if not in_recovery:
            # 连上的不是副本（URL 配错指向主库）——配置错误，不报 lag
            logger.warning("ASYNC_DATABASE_REPLICA_URL 指向的不是热备实例，请检查配置")
            return {'ok': False, 'error': 'not-in-recovery'}
        lag = await conn.fetchval('SELECT now() - pg_last_xact_replay_timestamp()')
    finally:
        await conn.close()

    if lag is None:
        # 主库从未产生可回放事务（新库）——正常
        return {'ok': True, 'lag_seconds': None}

    lag_seconds = lag.total_seconds()
    if lag_seconds > REPLICA_LAG_WARN_SECONDS:
        logger.warning(
            "只读副本回放延迟超阈值: %.0fs（阈值 %ds）——读流量可能读到过期数据，请检查主库 WAL 与复制状态",
            lag_seconds, REPLICA_LAG_WARN_SECONDS,
        )
    else:
        logger.info("只读副本回放延迟正常: %.0fs", lag_seconds)
    return {'ok': True, 'lag_seconds': round(lag_seconds, 1)}
