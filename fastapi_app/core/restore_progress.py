import json
import logging
import uuid
from datetime import datetime

logger = logging.getLogger(__name__)

PROGRESS_KEY_PREFIX = "erp:restore_progress:"
PROGRESS_TTL = 3600

_phases = [
    ("pre_backup", "创建恢复前安全备份", 0, 5),
    ("acquire_lock", "获取恢复锁", 5, 10),
    ("read_backup", "读取并验证备份文件", 10, 15),
    ("restore_db", "恢复数据库", 15, 55),
    ("restore_filestore", "恢复附件文件", 55, 70),
    ("restore_config", "恢复配置文件", 70, 80),
    ("restore_redis", "恢复 Redis 数据", 80, 85),
    ("restore_meilisearch", "恢复搜索索引", 85, 90),
    ("rebuild_pool", "重建连接池", 90, 93),
    ("verify", "数据完整性验证", 93, 100),
]

_phase_map = {name: (label, start, end) for name, label, start, end in _phases}


def generate_task_id() -> str:
    return uuid.uuid4().hex[:16]


async def _get_redis():
    try:
        from fastapi_app.services.notification_service import _get_async_redis_client
        client = await _get_async_redis_client()
        return client
    except (ImportError, OSError, RuntimeError):
        pass
    from fastapi_app.core.redis_wrapper import get_client
    return get_client()


async def create_progress(task_id: str, restore_type: str = "full") -> None:
    client = await _get_redis()
    if client is None:
        logger.warning("Redis 不可用，进度追踪将仅记录日志")
        return
    data = {
        "task_id": task_id,
        "status": "pending",
        "progress": 0,
        "phase": "init",
        "phase_label": "初始化",
        "restore_type": restore_type,
        "started_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "completed_at": None,
        "result": None,
        "error": None,
    }
    key = f"{PROGRESS_KEY_PREFIX}{task_id}"
    await client.set(key, json.dumps(data, ensure_ascii=False), ex=PROGRESS_TTL)


async def update_progress(task_id: str, phase: str, sub_progress: float = 0.0, detail: str = "") -> None:
    if phase not in _phase_map:
        logger.warning(f"未知进度阶段: {phase}")
        return
    label, start, end = _phase_map[phase]
    progress = start + (end - start) * min(max(sub_progress, 0.0), 1.0)
    progress = round(min(progress, 100.0), 1)
    phase_label = label
    if detail:
        phase_label = f"{label} - {detail}"

    client = await _get_redis()
    if client is None:
        logger.info(f"[恢复进度] {task_id}: {progress}% - {phase_label}")
        return
    key = f"{PROGRESS_KEY_PREFIX}{task_id}"
    raw = await client.get(key)
    if raw is None:
        return
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return
    data["status"] = "running"
    data["progress"] = progress
    data["phase"] = phase
    data["phase_label"] = phase_label
    await client.set(key, json.dumps(data, ensure_ascii=False), ex=PROGRESS_TTL)


async def complete_progress(task_id: str, result: dict | None = None, status: str = 'completed') -> None:
    client = await _get_redis()
    if client is None:
        logger.info(f"[恢复进度] {task_id}: 100% - 已完成")
        return
    key = f"{PROGRESS_KEY_PREFIX}{task_id}"
    raw = await client.get(key)
    if raw is None:
        return
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return
    data["status"] = status
    data["progress"] = 100
    data["phase"] = status
    if status == 'completed_with_warnings':
        data["phase_label"] = "恢复完成（验证未通过）"
    else:
        data["phase_label"] = "恢复完成"
    data["completed_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    data["result"] = result
    await client.set(key, json.dumps(data, ensure_ascii=False), ex=PROGRESS_TTL)


async def fail_progress(task_id: str, error: str) -> None:
    client = await _get_redis()
    if client is None:
        logger.error(f"[恢复进度] {task_id}: 失败 - {error}")
        return
    key = f"{PROGRESS_KEY_PREFIX}{task_id}"
    raw = await client.get(key)
    if raw is None:
        return
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return
    # 如果任务已经完成（例如 psql 恢复成功但 session 失效导致后续异常），
    # 不要覆盖完成状态，仅记录警告
    if data.get("status") in ('completed', 'completed_with_warnings', 'failed'):
        logger.warning(f"[恢复进度] {task_id}: 任务已结束(status={data.get('status')})，忽略后续失败信号: {error}")
        return
    data["status"] = "failed"
    data["phase"] = "failed"
    data["phase_label"] = f"恢复失败: {error[:100]}"
    data["error"] = error
    data["completed_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    await client.set(key, json.dumps(data, ensure_ascii=False), ex=PROGRESS_TTL)


async def get_progress(task_id: str) -> dict | None:
    client = await _get_redis()
    if client is None:
        return None
    key = f"{PROGRESS_KEY_PREFIX}{task_id}"
    raw = await client.get(key)
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return None


async def cleanup_progress(task_id: str) -> None:
    client = await _get_redis()
    if client is None:
        return
    key = f"{PROGRESS_KEY_PREFIX}{task_id}"
    await client.delete(key)
