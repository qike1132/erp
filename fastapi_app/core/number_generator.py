"""
通用编号生成器（统一异步/同步实现）

核心特性：
- 内存计数器缓存当日最大编号，避免每次查库
- 定期清理过期计数器，防止内存泄漏
- 数据库 FOR UPDATE 行锁确保跨进程安全
- 已初始化的计数器直接使用内存值，无需再查库

与 fastapi_app.services.numbering 的区别：
- 本模块：提供同步 + 异步双实现；使用本地时间；使用调用方会话执行 FOR UPDATE，
  锁随调用方事务提交才释放。适用于短事务场景。
- services/numbering：仅异步；使用 UTC 时间；使用独立短事务执行 FOR UPDATE 后立即
  提交，避免长事务持锁。适用于批量操作等长事务场景，并提供业务专用 helper
  （generate_order_number 等）。

两者未合并的原因：datetime 时区与 FOR UPDATE 事务边界行为不同，直接合并会改变
运行时行为。如需统一，须先对齐时区与事务策略。

使用方式：
  from fastapi_app.core.number_generator import generate_number_async, generate_number_sync
"""
import asyncio
import contextlib
import hashlib
import logging
import threading
from datetime import datetime

from sqlalchemy import func, select

logger = logging.getLogger(__name__)


def _number_lock_key(prefix: str, date_str: str) -> int:
    """为(prefix, date_str)生成64位PostgreSQL advisory lock key。"""
    raw = f"{prefix}:{date_str}".encode("utf-8")
    # 取md5前15位十六进制，保证在PostgreSQL bigint范围内
    hex_key = hashlib.md5(raw).hexdigest()[:15]
    return int(hex_key, 16)


def _acquire_advisory_lock(session, lock_key: int) -> None:
    """同步：获取PostgreSQL事务级advisory lock；非PG环境则忽略。"""
    try:
        session.execute(select(func.pg_advisory_xact_lock(lock_key)))
    except Exception:  # defensive: 非PG或测试环境可降级为无advisory lock
        logger.debug("advisory lock 获取失败（同步），降级为无锁模式", exc_info=True)


async def _acquire_advisory_lock_async(db, lock_key: int) -> None:
    """异步：获取PostgreSQL事务级advisory lock；非PG环境则忽略。"""
    try:
        await db.execute(select(func.pg_advisory_xact_lock(lock_key)))
    except Exception:  # defensive: 非PG或测试环境可降级为无advisory lock
        logger.debug("advisory lock 获取失败（异步），降级为无锁模式", exc_info=True)


class _BaseNumberGenerator:
    """编号生成器共享逻辑（计数器管理 + 编号格式化）"""

    def __init__(self):
        self._counters: dict[str, int] = {}
        self._last_cleanup_date: str | None = None

    def _cleanup_old_entries(self):
        """清理非当日的计数器条目，防止内存泄漏"""
        today_str = datetime.now().strftime('%Y%m%d')
        if self._last_cleanup_date == today_str and len(self._counters) < 500:
            return
        expired_keys = [k for k in self._counters if not k.endswith(today_str)]
        for k in expired_keys:
            self._counters.pop(k, None)
        self._last_cleanup_date = today_str

    @staticmethod
    def _parse_max_number(last_number: str) -> int:
        """解析编号中的序号部分"""
        with contextlib.suppress(ValueError, IndexError):
            return int(last_number.split('-')[-1])
        return 0

    @staticmethod
    def _format_number(prefix: str, date_str: str, seq: int) -> str:
        """格式化编号：PREFIX-YYYYMMDD-XXXX"""
        return f"{prefix}-{date_str}-{str(seq).zfill(4)}"


class SyncNumberGenerator(_BaseNumberGenerator):
    """同步编号生成器（使用 threading.Lock）"""

    def __init__(self):
        super().__init__()
        self._lock = threading.Lock()

    def generate(self, prefix: str, model, date_field: str,
                 number_field: str, session) -> str:
        """
        同步生成编号（跨进程安全）

        DB FOR UPDATE 查询与计数器更新均在锁内完成，避免锁外读取后、
        其他线程/进程已提交新编号导致的序号重复。

        Returns:
            str: 格式为 PREFIX-YYYYMMDD-XXXX
        """
        today = datetime.now()
        date_str = today.strftime('%Y%m%d')

        with self._lock:
            self._cleanup_old_entries()
            counter_key = f"{prefix}:{date_str}"
            lock_key = _number_lock_key(prefix, date_str)

            # 数据库 advisory lock 确保跨进程互斥; FOR UPDATE 只能锁已存在行, 空表时无法阻止并发
            _acquire_advisory_lock(session, lock_key)

            result = session.execute(
                select(model)
                .where(func.date(getattr(model, date_field)) == today.date())
                .order_by(getattr(model, number_field).desc())
                .limit(1)
                .with_for_update()
            )
            record = result.scalar_one_or_none()
            db_max = self._parse_max_number(getattr(record, number_field)) if record else 0

            current_seq = max(db_max, self._counters.get(counter_key, 0)) + 1
            self._counters[counter_key] = current_seq

        return self._format_number(prefix, date_str, current_seq)


class AsyncNumberGenerator(_BaseNumberGenerator):
    """异步编号生成器（使用 asyncio.Lock）"""

    def __init__(self):
        super().__init__()
        self._lock = asyncio.Lock()

    async def generate(self, prefix: str, model, date_field: str,
                       number_field: str, db) -> str:
        """
        异步生成编号（跨进程安全）

        协程内用 asyncio.Lock 保证同进程内串行；
        每次均通过 FOR UPDATE 查询数据库获取当前最大序号，避免跨进程缓存导致重复。

        Returns:
            str: 格式为 PREFIX-YYYYMMDD-XXXX
        """
        today = datetime.now()
        date_str = today.strftime('%Y%m%d')

        async with self._lock:
            self._cleanup_old_entries()

            counter_key = f"{prefix}:{date_str}"
            lock_key = _number_lock_key(prefix, date_str)

            # 数据库 advisory lock 确保跨进程互斥; FOR UPDATE 只能锁已存在行, 空表时无法阻止并发
            await _acquire_advisory_lock_async(db, lock_key)

            result = await db.execute(
                select(model)
                .where(func.date(getattr(model, date_field)) == today.date())
                .order_by(getattr(model, number_field).desc())
                .limit(1)
                .with_for_update()
            )
            record = result.scalar_one_or_none()
            db_max = self._parse_max_number(getattr(record, number_field)) if record else 0

            current_seq = max(db_max, self._counters.get(counter_key, 0)) + 1
            self._counters[counter_key] = current_seq

            return self._format_number(prefix, date_str, current_seq)


# 全局单例
_sync_generator = SyncNumberGenerator()
_async_generator = AsyncNumberGenerator()


def generate_number_sync(prefix: str, model, date_field: str,
                         number_field: str, session) -> str:
    """同步编号生成接口"""
    return _sync_generator.generate(prefix, model, date_field, number_field, session)


async def generate_number_async(prefix: str, model, date_field: str,
                                number_field: str, db) -> str:
    """异步编号生成接口"""
    return await _async_generator.generate(prefix, model, date_field, number_field, db)
