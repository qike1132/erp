"""OCR 导入进度管理（Redis 存储，跨 worker 可见）

2026-10-17 审计 AUD-03：原实现把进度放在模块级 dict，4 个 uvicorn worker 各一份——
轮询请求被分到非创建 worker 时查不到任务，端点静默新建一个全 0 进度，
前端永远「处理中 0%」。现改为 Redis 存储（TTL 1h），Redis 不可用时由
core.redis_wrapper 安全降级，并保留进程内字典兜底（单 worker/开发环境可用）。

接口为 async：调用方（端点与 OCR 导入链路）均已处于异步上下文。
"""
import logging
import uuid

from fastapi_app.core.redis_wrapper import safe_get, safe_set

logger = logging.getLogger(__name__)

_KEY_PREFIX = 'erp:ocr_progress:'
_PROGRESS_TTL = 3600

# Redis 不可用时的进程内降级（保留给单 worker / 开发环境）
_progress_store: dict[str, dict] = {}


def _key(task_id: str) -> str:
    return f'{_KEY_PREFIX}{task_id}'


async def _write(task_id: str, data: dict) -> None:
    ok = await safe_set(_key(task_id), data, timeout=_PROGRESS_TTL, context='OCR 进度')
    if not ok:
        _progress_store[task_id] = data


async def create_progress() -> str:
    task_id = uuid.uuid4().hex
    await _write(task_id, {'status': 'pending', 'percent': 0, 'message': '等待处理...', 'filename': ''})
    return task_id


# Redis 读取失败（非 miss）时返回的哨兵：端点据此返回「进行中」而非终态 not_found，
# 避免一次 Redis 抖动让长批量被前端判死。
_UNAVAILABLE: dict = {'status': 'pending', 'percent': 0, 'message': '进度暂不可用，正在重试'}


async def get_progress(task_id: str) -> dict | None:
    """返回进度字典；确认不存在/已过期返回 None（端点据此返回 not_found 终态）。"""
    data = await safe_get(_key(task_id), fallback=_UNAVAILABLE)
    if data is _UNAVAILABLE:
        # Redis 读取异常：先看进程内降级存储，再返回非终态占位。
        # 返回副本：调用方可能 update()，不能污染共享哨兵
        return _progress_store.get(task_id) or dict(_UNAVAILABLE)
    if isinstance(data, dict):
        return data
    return _progress_store.get(task_id)


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
