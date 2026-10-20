"""ARQ 任务队列配置（替代 Celery）。

ARQ 是原生 async 任务队列，与 FastAPI async 架构一致，
消除 Celery 同步任务与 async 事件循环的割裂。

- Worker 启动：`arq fastapi_app.core.arq_app.WorkerSettings`
- Web 进程入队：`await get_arq_pool().enqueue_job(func_name, *args)`
- 定时任务：cron_jobs（内置于 worker，无需独立 beat 进程）
"""
import asyncio
import contextlib
import logging
import os
from functools import wraps
from typing import ClassVar

from arq import Retry, create_pool, cron
from arq.connections import RedisSettings
from arq.constants import default_queue_name, health_check_key_suffix

from fastapi_app.core.arq_callbacks import on_job_end, on_job_start
from fastapi_app.core.config import settings
from fastapi_app.services.inventory_reconcile import is_enabled

logger = logging.getLogger(__name__)

# 队列名称（保持与 Celery 一致的路由语义，供 _queue_name 使用）
QUEUE_BATCH = 'io.batch'
QUEUE_REPORTS = 'io.reports'
QUEUE_BACKUP = 'io.backup'
QUEUE_PLAN = 'io.plan'

# Redis 配置（独立 broker 实例，与缓存实例隔离）
# 优先使用 REDIS_BROKER_URL；未配置时回退到通用 REDIS_HOST/PORT/DB
def _build_redis_settings() -> RedisSettings:
    broker_url = getattr(settings, 'REDIS_BROKER_URL', '') or os.getenv('REDIS_BROKER_URL', '')
    if broker_url:
        return RedisSettings.from_dsn(broker_url)
    redis_pwd = settings.REDIS_PASSWORD or None
    return RedisSettings(
        host=settings.REDIS_HOST,
        port=settings.REDIS_PORT,
        password=redis_pwd,
        database=settings.REDIS_DB or 0,
    )


redis_settings = _build_redis_settings()


# ---------------------------------------------------------------------------
# 任务重放幂等与批提交（P1-7）
# ---------------------------------------------------------------------------
# 背景：ARQ 的 ``max_tries=3`` 会**重放**失败任务（``ctx['job_try']`` 递增，``job_id`` 不变）。
# 重放会重做已经提交的写入：批量导入重复建单/重复加减库存，调度轮询重复入队并重复回写状态。
# 端点侧的幂等键（``api/v1/endpoints/purchase_center/order_routes.py:113`` 的 ``X-Idempotency-Key``
# 透传给 ``services/purchase_order_generate.py:374``）靠业务表的唯一约束 ``uq_po_pending_dedup``
# 兜底；ARQ 任务既没有 HTTP 头，其写入（导入行、调度状态）也没有可用的唯一约束，故这里用
# **Redis 集合**承担同一角色：每个 job 一个集合，成员是业务主键。
IDEMPOTENCY_KEY_PREFIX = 'arq:idem'
IDEMPOTENCY_TTL_SECONDS = 24 * 3600
IDEMPOTENCY_NAMESPACE_BATCH_IMPORT = 'batch-import'
IDEMPOTENCY_NAMESPACE_SCHEDULE_POLLER = 'backup-schedule-poller'

# 每批提交的条数（P1-7）：把「循环内逐条 commit」改为每 N 条一批提交。
# 200 是吞吐与「重放代价」的折中：批越大则重放时要重做的工作越少，但单批失败
# （行级异常触发的回滚）丢掉的已提交进度也越多。
DEFAULT_COMMIT_BATCH_SIZE = 200


class InMemoryIdempotencyStore:
    """进程内幂等集合：没有 Redis（单进程/降级）时的兜底。

    只挡得住**同一进程内**的重放（ARQ 重试通常就发生在同一个 worker 进程里），跨进程与
    跨重启不保证——那种场景请用 :class:`RedisIdempotencyStore`。``ttl`` 在这里无意义
    （随进程消亡），保留只为与 Redis 版签名一致。
    """

    def __init__(self) -> None:
        self._sets: dict[str, set[str]] = {}

    async def load(self, key: str) -> set[str]:
        return set(self._sets.get(key, ()))

    async def add(self, key: str, members, ttl: int) -> None:
        self._sets.setdefault(key, set()).update(members)

    def clear(self) -> None:
        self._sets.clear()


_IN_MEMORY_IDEMPOTENCY = InMemoryIdempotencyStore()


def in_memory_idempotency_store() -> InMemoryIdempotencyStore:
    """取进程内兜底存储（单测用：便于断言与跨用例清理）。"""
    return _IN_MEMORY_IDEMPOTENCY


class RedisIdempotencyStore:
    """Redis 集合幂等存储：``SADD`` 成员 + ``EXPIRE`` 整键。

    读写失败一律**降级放行并记 WARNING**（fail-open）：宁可重放时多写一次，也不能因为
    broker 抖动把用户的数据静默丢掉（fail-closed 会丢行）。
    """

    def __init__(self, redis) -> None:
        self._redis = redis

    async def load(self, key: str) -> set[str]:
        try:
            raw = await self._redis.smembers(key)
        except Exception as e:  # broad-except: 幂等后端故障降级为「本批不去重」，绝不中断任务
            logger.warning('幂等集合读取失败，本次重放不去重 key=%s: %s', key, e)
            return set()
        return {m.decode('utf-8') if isinstance(m, (bytes, bytearray)) else str(m) for m in (raw or ())}

    async def add(self, key: str, members, ttl: int) -> None:
        items = [str(m) for m in members]
        if not items:
            return
        try:
            await self._redis.sadd(key, *items)
            await self._redis.expire(key, ttl)
        except Exception as e:  # broad-except: 同上，写失败只影响「下次重放」的去重能力
            logger.warning('幂等集合写入失败，重放可能重复处理 key=%s: %s', key, e)


class JobIdempotency:
    """单个 ARQ job 的重放幂等闸门（键 = ``job_id``，成员 = 业务主键）。

    用法::

        idem = job_idempotency(ctx, namespace=IDEMPOTENCY_NAMESPACE_BATCH_IMPORT)
        done = await idem.load()          # 本 job 已经**提交成功**的业务主键
        ...                               # 逐条处理，命中的键跳过
        await idem.mark(committed_keys)   # 只在提交成功之后登记
    """

    def __init__(self, store, *, job_id: str, namespace: str, ttl: int = IDEMPOTENCY_TTL_SECONDS) -> None:
        self._store = store
        self.job_id = job_id
        self.namespace = namespace
        self.ttl = ttl

    @property
    def key(self) -> str:
        return f'{IDEMPOTENCY_KEY_PREFIX}:{self.namespace}:{self.job_id}'

    async def load(self) -> set[str]:
        return await self._store.load(self.key)

    async def mark(self, members) -> None:
        await self._store.add(self.key, members, self.ttl)


def job_idempotency(ctx, *, namespace: str) -> JobIdempotency:
    """按 ARQ ``ctx`` 构造幂等闸门。

    ``ctx['redis']`` 由 worker 注入（``arq/worker.py:361`` 的 ``self.ctx['redis'] = self.pool``），
    ``ctx['job_id']`` 在重试之间保持不变（``arq/worker.py:576-582`` 组装 job_ctx），因此
    (job_id, 业务主键) 正好表达「这个任务已经处理过哪些业务对象」。没有 Redis 时退回进程内存储。
    """
    data = ctx if isinstance(ctx, dict) else {}
    redis = data.get('redis')
    store = RedisIdempotencyStore(redis) if redis is not None else _IN_MEMORY_IDEMPOTENCY
    return JobIdempotency(store, job_id=str(data.get('job_id') or 'anonymous'), namespace=namespace)


class CommitBatcher:
    """按批提交（P1-7）：每 ``batch_size`` 条 commit 一次，收尾只提交未落盘的部分。

    语义：``commits == ceil(条数 / batch_size)``（即 ≤ 批次数 + 1），不再逐条 commit。
    ``after_commit`` 钩子只在**提交成功之后**执行——幂等标记必须与写入同批推进，否则被回滚
    掉的批次会被误标成「已处理」，重放时就真的丢数据了。
    """

    def __init__(self, db, *, batch_size: int = DEFAULT_COMMIT_BATCH_SIZE, after_commit=None) -> None:
        if batch_size < 1:
            raise ValueError('batch_size 必须 >= 1')
        self._db = db
        self.batch_size = batch_size
        self._after_commit = after_commit
        self.pending = 0
        self.commits = 0

    def reset(self) -> None:
        """丢弃未提交批的计数（回滚之后调用）。"""
        self.pending = 0

    async def tick(self) -> bool:
        """登记一条已暂存的写入；满一批则提交并返回 True。"""
        self.pending += 1
        if self.pending < self.batch_size:
            return False
        await self._commit()
        return True

    async def flush(self) -> bool:
        """收尾提交：没有未提交内容时**不提交**（保证 commits == 批次数）。"""
        if self.pending <= 0:
            return False
        await self._commit()
        return True

    async def _commit(self) -> None:
        await self._db.commit()
        self.commits += 1
        self.pending = 0
        if self._after_commit is not None:
            await self._after_commit()


# 任务注册：ARQ 通过 functions 列表注册，按函数 __name__ 派发
from fastapi_app.tasks.backup_tasks import (
    apply_backup_policy_task,
    auto_daily_backup_task,
    backup_cleanup_task,
    backup_health_check_task,
    backup_integrity_check_task,
    backup_metrics_report_task,
    disaster_recovery_test_task,
    manual_full_backup_task,
    scheduler_poller,
)
from fastapi_app.tasks.batch_tasks import (
    batch_import_orders_task,
    batch_import_stockins_task,
)
from fastapi_app.tasks.inventory_reconcile_task import (
    inventory_reconcile_cron_entry,
    inventory_reconcile_task,
)
from fastapi_app.tasks.maintenance_tasks import (
    ensure_readonly_grants_task,
    maintain_logs_task,
    refresh_dashboard_mv_task,
)
from fastapi_app.tasks.numbering_audit_task import numbering_audit_task
from fastapi_app.tasks.plan_tasks import (
    batch_import_plans_task,
    sync_shipment_records_task,
)
from fastapi_app.tasks.replica_lag_task import replica_lag_task
from fastapi_app.tasks.report_tasks import export_report_task

# ---------------------------------------------------------------------------
# 定时任务（替代 Celery beat_schedule）
# ---------------------------------------------------------------------------
# cron_schedules 同时供 worker（派生 cron_jobs）与 backup 端点（列出/触发）使用，
# 避免两处维护。ARQ 的 cron() 支持 hour/minute 为 int 或 set。
# max_tries=3 对应 Celery max_retries=2（总尝试次数 = 重试次数 + 1）。
cron_schedules = [
    {
        'name': 'sync-shipment-daily',
        'func': sync_shipment_records_task,
        'cron': {'hour': 1, 'minute': 0},
        'schedule': '1:00',
    },
    {
        # M2: 备份 4 项定时（完整性巡检/全量/增量/清理）已迁入 backup_schedule 表，
        # 由下方 scheduler_poller 每 5 分钟扫描调度执行，保持 02:00/06-22/03:00/04:00 等价。
        'name': 'backup-schedule-poller',
        'func': scheduler_poller,
        'cron': {'minute': set(range(0, 60, 5))},
        'schedule': 'every 5m',
        'timeout': 300,
    },
    {
        # 原 Celery beat: 300.0（每 5 分钟）。ARQ cron 不支持步进值，用 minute 集合表达。
        'name': 'refresh-dashboard-mv',
        'func': refresh_dashboard_mv_task,
        'cron': {'minute': set(range(0, 60, 5))},
        'schedule': 'every 5m',
    },
    {
        # 只读副本授权对账：数据库恢复会清空 erp_readonly 授权（只读接口 500），
        # 此处周期自愈兜底（与恢复完成即自愈双保险）。10 分钟一次，幂等低开销。
        'name': 'readonly-grants-reconcile',
        'func': ensure_readonly_grants_task,
        'cron': {'minute': set(range(0, 60, 10))},
        'schedule': 'every 10m',
    },
    {
        # 日志维护：按共享策略（config/log_policy.json）轮转超限日志 + 保留清理。
        # 与桌面壳、prod_runner 读同一份策略、调同一套实现；这里是每日兜底。
        'name': 'log-maintenance',
        'func': maintain_logs_task,
        'cron': {'hour': 4, 'minute': 30},
        'schedule': '4:30',
        'timeout': 120,
    },
    {
        # 编号不变量巡检：counter_behind（数据号 > 水位）与格式违规落库，
        # 供只读端点拉取。正向跳号是正常语义，不报警。10 分钟一次，幂等低开销。
        'name': 'numbering_audit',
        'func': numbering_audit_task,
        'cron': {'minute': set(range(0, 60, 10))},
        'schedule': 'every 10m',
        'timeout': 60,
    },
    {
        # 只读副本延迟巡检（OPT-16 收编）：同机热备 5433 若断流，读流量会
        # 无声读到旧数据。每 10 分钟采集 replay lag，超 5 分钟告警；连接失败
        # 按 ERROR 记录但不抛错（避免 max_tries 耗尽后监控静默失效）。
        'name': 'replica-lag-check',
        'func': replica_lag_task,
        'cron': {'minute': set(range(0, 60, 10))},
        'schedule': 'every 10m',
        'timeout': 60,
    },
]

# 库存只读对账（P1-1）：**默认不注册** cron —— 先按需手动触发观察报告口径与聚合
# 开销；确认后把 INVENTORY_RECONCILE_ENABLED 置真，即每日 03:30 自动对账。
if is_enabled():
    cron_schedules.append(inventory_reconcile_cron_entry())

# ARQ 0.28 只有 on_job_start/on_job_end，没有 on_job_failed；任务边界负责记录成败。
MAX_TRIES = 3


def _tracked_job(func, max_tries: int = MAX_TRIES):
    """把任务成败写进 ctx，供 on_job_end 分流（ARQ 0.28 无失败钩子）。"""
    @wraps(func)
    async def tracked(ctx, *args, **kwargs):
        ctx['_job_function'] = func.__name__
        ctx['_max_tries'] = max_tries
        ctx['_job_args'] = args
        ctx['_job_kwargs'] = kwargs
        try:
            result = await func(ctx, *args, **kwargs)
        except Retry as exc:
            # Retry 是「稍后重放」的控制流；只有最后一跳才是终态失败。
            if int(ctx.get('job_try', 1)) >= max_tries:
                ctx['_job_outcome'] = 'failed'
                ctx['_job_exception'] = exc
            else:
                ctx['_job_outcome'] = 'retrying'
            raise
        except asyncio.CancelledError:
            # 取消可能是 worker 停机的重放路径，交给 ARQ 的 retry/abort 语义收尾。
            ctx['_job_outcome'] = 'retrying'
            raise
        except Exception as exc:  # defensive: 任务体任意异常都要记录成败后原样抛出，交由 ARQ 收尾
            ctx['_job_outcome'] = 'failed'
            ctx['_job_exception'] = exc
            raise
        else:
            ctx['_job_outcome'] = 'success'
            return result

    return tracked


cron_jobs = [
    cron(_tracked_job(s['func'], MAX_TRIES), max_tries=MAX_TRIES, timeout=s.get('timeout'), **s['cron'])  # type: ignore[arg-type]
    for s in cron_schedules
]


class WorkerSettings:
    """ARQ Worker 配置（`arq fastapi_app.core.arq_app.WorkerSettings`）。"""

    async def on_startup(ctx) -> None:  # noqa: N805 - ARQ 约定为类内静态钩子（无 self）
        """Worker 启动钩子：初始化共享 Redis 缓存管理器 + 编号水位对账（spec §5）。

        ARQ worker 是**独立进程**（NSSM 服务 erp-arq），不受 FastAPI lifespan 约束。
        若此处不对账，部署窗口内 worker 会抢在 web 进程对账提交前处理已入队的批量
        导入任务：``allocate_sequence`` 返回 ``seed_last+1``，与历史路径产生、从未
        经过 ``numbering_counter`` 的数据行重号 → ``IntegrityError``（不在 batch_tasks
        捕获的 ``(ValueError, TypeError, OSError)`` 元组内）→ 任务失败；配合
        ``max_tries=3`` 还可能被丢弃。

        对账是 advisory-locked（``number_lock_key('NUMBERING_RECONCILE', 'startup')``
        经 ``acquire_advisory_lock_async``）且幂等（GREATEST 只升不降，``raised`` 只计
        真实抬升），故 web/worker 双进程执行安全 —— 不新增锁。失败**不阻断**启动
        （刻意与 lifespan 一致），但记 ERROR 以便失败可见、不静默留窗。
        """
        # 初始化共享 Redis 缓存管理器（与 API lifespan 同源）。2026-10-11 前 worker
        # 从不初始化它 → redis_wrapper 的所有路径静默降级、safe_lpush 写不进死信队列。
        try:
            from fastapi_app.core.redis_wrapper import init_redis_cache_manager
            await init_redis_cache_manager()
        except Exception as e:  # defensive: Redis 初始化失败不得阻断 worker 启动
            logger.error('worker Redis 缓存初始化失败（不影响启动）: %s', e)

        try:
            from fastapi_app.core.database import require_async_session_local
            from fastapi_app.services.numbering_reconcile import reconcile_numbering_counters
            async with require_async_session_local()() as recon_db:
                result = await reconcile_numbering_counters(recon_db)
                await recon_db.commit()  # reconcile 不自行提交；事务边界归调用方
            if result['raised'] or result['inserted']:
                logger.info(
                    '编号水位对账(worker): 抬升 %d 行, 补插 %d 行',
                    result['raised'], result['inserted'],
                )
        except Exception as e:  # defensive: 对账失败不得阻断 worker 启动
            logger.error('编号水位启动对账失败（不影响启动）: %s', e, exc_info=True)

    functions: ClassVar[list] = [
        _tracked_job(f, MAX_TRIES)
        for f in (
            batch_import_orders_task,
            batch_import_stockins_task,
            scheduler_poller,
            auto_daily_backup_task,
            manual_full_backup_task,
            backup_integrity_check_task,
            backup_cleanup_task,
            backup_health_check_task,
            apply_backup_policy_task,
            disaster_recovery_test_task,
            backup_metrics_report_task,
            export_report_task,
            sync_shipment_records_task,
            batch_import_plans_task,
            refresh_dashboard_mv_task,
            ensure_readonly_grants_task,
            numbering_audit_task,
            inventory_reconcile_task,
        )
    ]
    cron_jobs = cron_jobs
    redis_settings = redis_settings
    # 哨兵键刷新周期（秒）：默认 3600 意味着 worker 硬崩溃后最长 1 小时仍误报在线，
    # 显式缩短到 60s（TTL = interval + 1s，见 check_worker_health）。
    health_check_interval = 60
    max_jobs = 10
    job_timeout = 1800
    max_tries = MAX_TRIES
    on_job_start = on_job_start
    on_job_end = on_job_end


# ---------------------------------------------------------------------------
# Web 进程入队辅助（FastAPI 端点调用）
# ---------------------------------------------------------------------------
_arq_pool = None
_pool_lock = asyncio.Lock()


async def get_arq_pool():
    """获取共享 ARQ Redis 连接池，用于在 Web 进程中入队任务。

    连接池在首次调用时创建并复用，避免每次入队都新建连接。
    使用 asyncio.Lock + 双重检查防止并发首次调用创建多个连接池。
    """
    global _arq_pool
    if _arq_pool is None:
        async with _pool_lock:
            if _arq_pool is None:
                _arq_pool = await create_pool(redis_settings)
    return _arq_pool


# 健康探测超时上限（秒）：broker 假死（TCP 可连不回包）时，探测须在该时长内返回
_HEALTH_PROBE_TIMEOUT = 2.0


def _health_check_key(pool) -> str:
    """返回 ARQ 健康哨兵键：queue_name + ':health-check'。

    优先取连接池自身的 default_queue_name（与 enqueue_job 实际入队的队列一致），
    取不到时回退到 arq 的模块级默认值。
    """
    queue_name = getattr(pool, 'default_queue_name', None) or default_queue_name
    return queue_name + health_check_key_suffix


async def check_worker_health() -> tuple[bool, str]:
    """检测 ARQ Worker 是否在线（入队前预检）。

    通过读取 ARQ 官方健康检查哨兵键（queue_name + ':health-check'）判定：
    Worker 存活期间按 health_check_interval 周期刷新该键
    （TTL = health_check_interval + 1s），正常退出时主动删除，
    进程硬崩溃后键在 TTL 内自然过期。

    ⚠️ arq 0.28 的 ``ArqRedis`` **没有** ``health()`` 方法；哨兵键是唯一官方
    可用的探测手段（arq CLI 的 ``--check`` 走的也是同一个键）。曾因误用
    ``pool.health()`` 导致所有手动备份被 503 误拦截，勿再改回。

    Returns:
        (is_healthy, message):
        - (True, 'ARQ Worker 在线（<心跳详情>）')
        - (False, 'ARQ Worker 未运行，请启动 erp-arq 服务')
        - (False, 'ARQ Worker 健康探测超时/失败: ...')  探测自身异常时的降级返回
    """
    try:
        pool = await get_arq_pool()
        value = await asyncio.wait_for(
            pool.get(_health_check_key(pool)),
            timeout=_HEALTH_PROBE_TIMEOUT,
        )
        if value:
            detail = value.decode('utf-8', 'replace') if isinstance(value, bytes) else str(value)
            return True, f'ARQ Worker 在线（{detail}）'
        return False, 'ARQ Worker 未运行，请启动 erp-arq 服务'
    except TimeoutError:
        logger.warning('ARQ Worker 健康探测超时(>%ss)，broker 疑似不可达', _HEALTH_PROBE_TIMEOUT)
        return False, f'ARQ Worker 健康探测超时（>{_HEALTH_PROBE_TIMEOUT:g}s），请检查 erp-redis-broker 服务'
    except Exception as e:  # broad-except: 健康探测自身不得抛出，任何异常都须转成"不健康"返回值
        logger.warning('ARQ Worker 健康检测失败: %s', e)
        return False, f'ARQ Worker 健康检测失败: {type(e).__name__}'


async def probe_worker_health_isolated(timeout: float = 1.0) -> bool:
    """健康端点专用：用**短命连接池**判定 ARQ worker 是否在线，绝不触碰全局池。

    为什么必须隔离：``get_arq_pool()`` 的池在首次调用时创建，并**绑定当时的事件循环**
    后被长期缓存。``/api/health`` 被高频调用、也可能在不同事件循环下被调用（测试、
    多 loop 场景），复用绑定在已关闭 loop 上的连接会抛
    ``Event loop is closed`` / ``'NoneType' object has no attribute 'send'``，
    污染整条健康探测链路。探测只是一次 GET，短命连接的代价由 /api/health 的
    10s 缓存兜住。
    """
    pool = None
    try:
        pool = await create_pool(redis_settings)
        value = await asyncio.wait_for(pool.get(_health_check_key(pool)), timeout=timeout)
        return bool(value)
    except Exception as e:  # broad-except: 探测自身不得抛出，任何异常一律按"不在线"处理
        logger.debug('ARQ 隔离探针失败(按不在线处理): %s', e)
        return False
    finally:
        if pool is not None:
            with contextlib.suppress(Exception):
                await pool.aclose()
