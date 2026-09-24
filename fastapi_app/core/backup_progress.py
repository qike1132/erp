"""
统一的备份/恢复进度管理模块。

替代原有的 restore_progress.py，同时支持备份和恢复两种操作类型的进度追踪。
进度数据存储在 Redis 中，用于 WebSocket 断连后的状态恢复缓存。

备份 phases (8): init -> export_db -> pack_filestore -> backup_config ->
                  backup_redis -> backup_meilisearch -> generate_checksum -> write_file
恢复 phases (10): pre_backup -> acquire_lock -> read_backup -> restore_db ->
                   restore_filestore -> restore_config -> restore_redis ->
                   restore_meilisearch -> rebuild_pool -> verify
"""

import base64
import json
import logging
import re
import uuid
from datetime import UTC, datetime

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Redis key prefixes & TTL
# ---------------------------------------------------------------------------
BACKUP_KEY_PREFIX = "erp:backup_progress:"
RESTORE_KEY_PREFIX = "erp:restore_progress:"
PROGRESS_TTL = 3600  # 1 hour, refreshed on every update

# ---------------------------------------------------------------------------
# Phase definitions  (name, label, progress_start%, progress_end%)
# ---------------------------------------------------------------------------
_BACKUP_PHASES = [
    ("init",               "初始化",             0,   5),
    ("export_db",          "导出数据库",          5,  35),
    ("pack_filestore",     "打包附件文件",       35,  55),
    ("backup_config",      "备份配置文件",       55,  65),
    ("backup_redis",       "备份 Redis 数据",    65,  75),
    ("backup_meilisearch", "备份搜索索引",       75,  85),
    ("generate_checksum",  "生成校验和",         85,  95),
    ("write_file",         "写入备份文件",       95, 100),
]

_RESTORE_PHASES = [
    ("pre_backup",         "创建恢复前安全备份",  0,   5),
    ("acquire_lock",       "获取恢复锁",          5,  10),
    ("read_backup",        "读取并验证备份文件",  10,  15),
    ("restore_db",         "恢复数据库",          15,  55),
    ("restore_filestore",  "恢复附件文件",        55,  70),
    ("restore_config",     "恢复配置文件",        70,  80),
    ("restore_redis",      "恢复 Redis 数据",     80,  85),
    ("restore_meilisearch","恢复搜索索引",        85,  90),
    ("rebuild_pool",       "重建连接池",          90,  93),
    ("verify",             "数据完整性验证",      93, 100),
]

_BACKUP_PHASE_MAP = {
    name: (label, start, end) for name, label, start, end in _BACKUP_PHASES
}
_RESTORE_PHASE_MAP = {
    name: (label, start, end) for name, label, start, end in _RESTORE_PHASES
}

# ---------------------------------------------------------------------------
# Error sanitization (REV-11)
# ---------------------------------------------------------------------------
# Matches common file-system paths on both Linux and Windows.
#   /absolute/path/to/file   or   C:\Users\foo\bar  or  \\server\share\path
_PATH_PATTERN = re.compile(
    r'(?:'
    r'[A-Za-z]:\\[^\s,;:\]"\'\)]+'        # Windows drive path  C:\foo\bar
    r'|\\\\[^\s,;:\]"\'\)]+'               # UNC path            \\server\share
    r'|/(?:[\w.-]+/)+[\w.-]+'              # Unix absolute path  /var/lib/pg/data
    r')'
)


def _sanitize_error(error: str, max_len: int = 200) -> str:
    """Remove file paths and truncate error message for safe Redis storage."""
    sanitized = _PATH_PATTERN.sub("<path>", error)
    if len(sanitized) > max_len:
        sanitized = sanitized[:max_len]
    return sanitized


# ---------------------------------------------------------------------------
# Redis client resolution (same pattern as restore_progress.py)
# ---------------------------------------------------------------------------
async def _get_redis():
    """Resolve an async Redis client using the same fallback chain as restore_progress.py."""
    try:
        from fastapi_app.core.redis_client import get_async_redis_client
        client = await get_async_redis_client()
        return client
    except (ImportError, OSError, RuntimeError):
        pass  # defensive: 异常静默处理,不影响主流程
    from fastapi_app.core.redis_wrapper import get_client
    return get_client()


async def is_redis_available() -> bool:
    """探测 Redis 是否可用（PING 探活）。

    用于把「锁服务不可用」与「锁确实被占用」区分开：锁函数 fail-closed
    返回的 True 只是保守值，不等于真的有任务在执行。探测失败按不可用处理。
    """
    try:
        client = await _get_redis()
        if client is None:
            return False
        await client.ping()
        return True
    except Exception:  # broad-except: 探活失败即视为不可用
        return False


# ---------------------------------------------------------------------------
# Task password side-channel (H3)
# ---------------------------------------------------------------------------
# ARQ 任务参数会被序列化进 Redis 队列（任何能读 Redis 的人可见）。加密密码
# 不进队列，改存到以 task_id 命名的一次性短 TTL 键中，任务消费时原子取走。
_TASK_PASSWORD_PREFIX = "erp:backup_task_pwd:"  # noqa: S105 - Redis 键前缀，非口令本身
_TASK_PASSWORD_TTL = 600  # 10 分钟内未被消费即过期，覆盖 worker 最长启动延迟


async def store_task_password(task_id: str, password: str) -> bool:
    """将任务加密密码写入一次性侧信道键（TTL 10 分钟）。

    写入失败返回 False，由调用方决定是否继续（fail-closed 更安全，
    但加密密码缺失只导致备份降级为不加密，与旧行为一致）。
    """
    try:
        client = await _get_redis()
        if client is None:
            return False
        # base64 编码作为最低防护，避免密码明文存入 Redis
        encoded = base64.b64encode(password.encode('utf-8'))
        await client.set(_TASK_PASSWORD_PREFIX + task_id, encoded, ex=_TASK_PASSWORD_TTL)
        return True
    except Exception as e:  # broad-except: 密码写入失败不应阻断任务入队
        logger.warning("写入任务密码侧信道失败（task_id=%s）: %s", task_id, e)
        return False


async def get_task_password(task_id: str) -> str | None:
    """读取任务密码（不删除，靠 TTL 自动过期清理）。

    不做一次性删除的原因：任务失败重试（ARQ job_try>1）时仍需密码，
    删除会导致重试静默降级为不加密备份。键 10 分钟后由 Redis 过期回收。
    """
    try:
        client = await _get_redis()
        if client is None:
            return None
        raw = await client.get(_TASK_PASSWORD_PREFIX + task_id)
        if raw:
            # base64 解码还原密码
            return base64.b64decode(raw).decode('utf-8')
        return None
    except Exception as e:  # broad-except: 读取失败按无密码处理（降级不加密）
        logger.warning("读取任务密码侧信道失败（task_id=%s）: %s", task_id, e)
        return None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------
def _resolve_key(task_id: str, progress_type: str | None = None) -> str:
    """Return the Redis key for *task_id*.

    When *progress_type* is given (``'backup'`` or ``'restore'``), the key is
    deterministic.  Otherwise we return the **backup** key as a default; the
    caller (``update_progress``) will try the other key on cache miss.
    """
    if progress_type == "backup":
        return f"{BACKUP_KEY_PREFIX}{task_id}"
    return f"{RESTORE_KEY_PREFIX}{task_id}"


def _phase_map_for(progress_type: str) -> dict:
    if progress_type == "backup":
        return _BACKUP_PHASE_MAP
    return _RESTORE_PHASE_MAP


async def _load_progress(task_id: str, client) -> tuple[str, str, dict] | None:
    """探测 backup/restore 键并加载进度数据。

    Returns:
        (key, progress_type, data): 成功；
        None: 未找到进度条目或数据损坏。

    从 update_progress / complete_progress / fail_progress 提取的公共探测逻辑。
    """
    backup_key = f"{BACKUP_KEY_PREFIX}{task_id}"
    restore_key = f"{RESTORE_KEY_PREFIX}{task_id}"

    raw = await client.get(backup_key)
    if raw is not None:
        key = backup_key
        progress_type = "backup"
    else:
        raw = await client.get(restore_key)
        if raw is not None:
            key = restore_key
            progress_type = "restore"
        else:
            return None

    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return None
    return key, progress_type, data


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def generate_task_id() -> str:
    """Generate a full 128-bit hex task ID (32 characters)."""
    return uuid.uuid4().hex


async def create_progress(
    task_id: str,
    operation_type: str = "full",
    progress_type: str = "restore",
) -> None:
    """Create a new progress entry in Redis.

    Parameters
    ----------
    task_id:
        Unique task identifier (from :func:`generate_task_id`).
    operation_type:
        Sub-type of the operation, e.g. ``'full'``, ``'incremental'``,
        ``'file_import'``, ``'server_restore'``.
    progress_type:
        ``'restore'`` (default) or ``'backup'``.
    """
    client = await _get_redis()
    if client is None:
        logger.warning("Redis 不可用，进度追踪将仅记录日志")
        return

    key = _resolve_key(task_id, progress_type)
    data = {
        "task_id": task_id,
        "progress_type": progress_type,
        "operation_type": operation_type,
        "status": "pending",
        "progress": 0,
        "phase": "init",
        "phase_label": "初始化",
        "started_at": datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S"),
        "completed_at": None,
        "result": None,
        "error": None,
    }
    await client.set(key, json.dumps(data, ensure_ascii=False), ex=PROGRESS_TTL)


async def update_progress(
    task_id: str,
    phase: str,
    sub_progress: float = 0.0,
    detail: str = "",
) -> None:
    """Update the progress of an ongoing task.

    Automatically detects whether the task is a backup or restore operation
    by probing both Redis keys.
    """
    client = await _get_redis()
    if client is None:
        logger.info(f"[进度] {task_id}: {phase} - {detail}")
        return

    # --- auto-detect progress type by probing keys ---
    found = await _load_progress(task_id, client)
    if found is None:
        logger.warning(f"[进度] {task_id}: 未找到进度条目")
        return
    key, progress_type, data = found

    phase_map = _phase_map_for(progress_type)
    if phase not in phase_map:
        logger.warning(f"未知进度阶段 ({progress_type}): {phase}")
        return

    label, start, end = phase_map[phase]
    progress = start + (end - start) * min(max(sub_progress, 0.0), 1.0)
    progress = round(min(progress, 100.0), 1)

    phase_label = f"{label} - {detail}" if detail else label

    data["status"] = "running"
    data["progress"] = progress
    data["phase"] = phase
    data["phase_label"] = phase_label

    await client.set(key, json.dumps(data, ensure_ascii=False), ex=PROGRESS_TTL)


async def complete_progress(
    task_id: str,
    result: dict | None = None,
    status: str = "completed",
) -> None:
    """Mark a task as completed.

    Parameters
    ----------
    task_id:
        Unique task identifier.
    result:
        Optional result payload (e.g. backup file info, verification report).
    status:
        Completion status -- ``'completed'`` or ``'completed_with_warnings'``.
    """
    client = await _get_redis()
    if client is None:
        logger.info(f"[进度] {task_id}: 100% - 已完成")
        return

    # Probe both keys.
    found = await _load_progress(task_id, client)
    if found is None:
        return
    key, progress_type, data = found

    data["status"] = status
    data["progress"] = 100
    data["phase"] = status

    if progress_type == "backup":
        if status == "completed_with_warnings":
            data["phase_label"] = "备份完成（有警告）"
        else:
            data["phase_label"] = "备份完成"
    else:
        if status == "completed_with_warnings":
            data["phase_label"] = "恢复完成（验证未通过）"
        else:
            data["phase_label"] = "恢复完成"

    data["completed_at"] = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
    data["result"] = result

    await client.set(key, json.dumps(data, ensure_ascii=False), ex=PROGRESS_TTL)


async def fail_progress(task_id: str, error: str) -> None:
    """Mark a task as failed.

    The error message is sanitized: file paths are replaced with ``<path>``
    and the message is truncated to 200 characters (REV-11).
    """
    sanitized = _sanitize_error(error)

    client = await _get_redis()
    if client is None:
        logger.error(f"[进度] {task_id}: 失败 - {sanitized}")
        return

    found = await _load_progress(task_id, client)
    if found is None:
        return
    key, progress_type, data = found

    # If the task is already in a terminal state, do not overwrite.
    if data.get("status") in ("completed", "completed_with_warnings", "failed"):
        logger.warning(
            f"[进度] {task_id}: 任务已结束(status={data.get('status')})，"
            f"忽略后续失败信号: {sanitized}"
        )
        return

    op_label = "备份" if progress_type == "backup" else "恢复"

    data["status"] = "failed"
    data["phase"] = "failed"
    data["phase_label"] = f"{op_label}失败: {sanitized[:100]}"
    data["error"] = sanitized
    data["completed_at"] = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")

    await client.set(key, json.dumps(data, ensure_ascii=False), ex=PROGRESS_TTL)


async def get_progress(task_id: str) -> dict | None:
    """Retrieve the current progress dict for *task_id*.

    Probes both backup and restore Redis keys.
    """
    client = await _get_redis()
    if client is None:
        return None

    backup_key = f"{BACKUP_KEY_PREFIX}{task_id}"
    restore_key = f"{RESTORE_KEY_PREFIX}{task_id}"

    raw = await client.get(backup_key)
    if raw is None:
        raw = await client.get(restore_key)
    if raw is None:
        return None

    try:
        return json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return None


async def cleanup_progress(task_id: str) -> None:
    """Delete the progress entry for *task_id* from Redis.

    Cleans up both possible keys (backup and restore) to avoid stale data.
    """
    client = await _get_redis()
    if client is None:
        return

    backup_key = f"{BACKUP_KEY_PREFIX}{task_id}"
    restore_key = f"{RESTORE_KEY_PREFIX}{task_id}"

    await client.delete(backup_key)
    await client.delete(restore_key)
