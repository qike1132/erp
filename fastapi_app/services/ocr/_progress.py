"""OCR 导入进度管理（Redis 存储，跨 worker 可见）

2026-10-17 审计 AUD-03：原实现把进度放在模块级 dict，4 个 uvicorn worker 各一份——
轮询请求被分到非创建 worker 时查不到任务，端点静默新建一个全 0 进度，
前端永远「处理中 0%」。现改为 Redis 存储（TTL 1h），Redis 不可用时由
core.redis_wrapper 安全降级，并保留进程内字典兜底（单 worker/开发环境可用）。

2026-10-18 OCR 评审：进程内兜底字典补齐了 TTL。此前它没有任何过期机制，
而 `get_progress` 在「Redis 正常但 key 不存在」时也会回退查它 —— 于是一条
早已过期（Redis 侧 TTL 1h 已过）的任务会从这个字典里读到**永不消失**的旧进度，
端点永远不返回 not_found 终态，前端无限轮询。
"""
import logging
import time
import uuid

from fastapi_app.core.redis_wrapper import safe_get, safe_set

logger = logging.getLogger(__name__)

_KEY_PREFIX = 'erp:ocr_progress:'
_PROGRESS_TTL = 3600

# Redis 不可用时的进程内降级（保留给单 worker / 开发环境）。
# 值为 (data, expires_at_monotonic)：与 Redis 侧同一 TTL，过期即视为不存在，
# 否则「永不消失的旧进度」会让前端轮询不到终态。
_progress_store: dict[str, tuple[dict, float]] = {}


def _key(task_id: str) -> str:
    return f'{_KEY_PREFIX}{task_id}'


def _store_get(task_id: str) -> dict | None:
    """读进程内兜底；过期条目顺手删除并返回 None（无 TTL 的字典会永远返回旧值）。"""
    entry = _progress_store.get(task_id)
    if entry is None:
        return None
    data, expires_at = entry
    if time.monotonic() > expires_at:
        _progress_store.pop(task_id, None)
        return None
    return data


def _store_put(task_id: str, data: dict) -> None:
    _progress_store[task_id] = (data, time.monotonic() + _PROGRESS_TTL)


async def _write(task_id: str, data: dict) -> None:
    ok = await safe_set(_key(task_id), data, timeout=_PROGRESS_TTL, context='OCR 进度')
    if not ok:
        _store_put(task_id, data)


async def create_progress() -> str:
    task_id = uuid.uuid4().hex
    await _write(task_id, {'status': 'pending', 'percent': 0, 'message': '等待处理...', 'filename': ''})
    return task_id


# Redis 读取失败（非 miss）时返回的哨兵：端点据此返回「进行中」而非终态 not_found，
# 避免一次 Redis 抖动让长批量被前端判死。
_UNAVAILABLE: dict = {'status': 'pending', 'percent': 0, 'message': '进度暂不可用，正在重试'}


async def get_progress(task_id: str) -> dict | None:
    """返回进度字典；确认不存在/已过期返回 None（端点据此返回 not_found 终态）。

    三种情况必须分开（2026-10-18 OCR 评审）：

    1. **miss** —— Redis 正常但 key 不存在。`redis_cache.get()` 对不存在的 key
       返回 `None`，而 `safe_get` 的 `fallback` 参数**只在抛
       INFRA_EXCEPTIONS（连接类错误）时**才生效，miss 不走 fallback。所以
       `data is None` 唯一地表示「真的没有这条进度」→ 必须返回 None 让端点
       报 not_found。
       旧代码在这里回退查进程内字典：Redis 已恢复而该任务在 Redis 侧早已被
       TTL 清掉时，会从这个**无 TTL**的字典里挖出永不消失的旧进度，
       前端永远等不到终态。
    2. **读失败** —— Redis 抖动/不可用，`safe_get` 返回 `_UNAVAILABLE` 哨兵。
       这时才看进程内兜底（单 worker 场景它是最新的），再退回非终态占位，
       避免一次抖动把长批量判死。
    3. **有值** —— 直接返回。
    """
    data = await safe_get(_key(task_id), fallback=_UNAVAILABLE)
    if data is _UNAVAILABLE:
        # Redis 读取异常：先看进程内降级存储，再返回非终态占位。
        # 返回副本：调用方可能 update()，不能污染共享哨兵
        return _store_get(task_id) or dict(_UNAVAILABLE)
    if isinstance(data, dict):
        return data
    # Redis 正常且 key 不存在：任务已过期/从未创建，不再回退进程内字典
    return None


async def _update_progress(task_id: str, **kwargs) -> None:
    """更新进度；未知 task_id 自动初始化（上传端点可能先于 create-task 被调用）。"""
    current = await get_progress(task_id)
    if current is None:
        current = {'status': 'pending', 'percent': 0, 'message': '', 'filename': ''}
    else:
        current = dict(current)
    if kwargs.get('status') != 'error' and 'percent' in kwargs:
        kwargs['percent'] = max(kwargs['percent'], current.get('percent', 0))
    current.update(kwargs)
    await _write(task_id, current)
