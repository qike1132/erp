"""
通用编号生成器（统一异步/同步实现）

核心特性：
- 内存计数器缓存当日最大编号，避免每次查库
- 定期清理过期计数器，防止内存泄漏
- 数据库 FOR UPDATE 行锁确保跨进程安全
- 已初始化的计数器直接使用内存值，无需再查库

使用方式：
  from fastapi_app.core.number_generator import generate_number_async, generate_number_sync
"""
import asyncio
import contextlib
import logging
import threading
from datetime import datetime

from sqlalchemy import func, select

logger = logging.getLogger(__name__)


class _BaseNumberGenerator:
    """编号生成器共享逻辑（计数器管理 + 编号格式化）"""

    def __init__(self):
        self._counters: dict[str, int] = {}
        self._initialized: dict[str, bool] = {}
        self._last_cleanup_date: str | None = None

    def _cleanup_old_entries(self):
        """清理非当日的计数器条目，防止内存泄漏"""
        today_str = datetime.now().strftime('%Y%m%d')
        if self._last_cleanup_date == today_str and len(self._counters) < 500:
            return
        expired_keys = [k for k in self._counters if not k.endswith(today_str)]
        for k in expired_keys:
            self._counters.pop(k, None)
            self._initialized.pop(k, None)
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

        DB 查询在锁外执行，减少锁持有时间；
        FOR UPDATE 行锁确保数据库层面的并发安全。

        Returns:
            str: 格式为 PREFIX-YYYYMMDD-XXXX
        """
        today = datetime.now()
        date_str = today.strftime('%Y%m%d')

        result = session.execute(
            select(model)
            .where(func.date(getattr(model, date_field)) == today.date())
            .order_by(getattr(model, number_field).desc())
            .limit(1)
            .with_for_update()
        )
        record = result.scalar_one_or_none()

        db_max = self._parse_max_number(getattr(record, number_field)) if record else 0

        with self._lock:
            self._cleanup_old_entries()
            counter_key = f"{prefix}:{date_str}"
            current_seq = max(db_max, self._counters.get(counter_key, 0)) + 1
            self._counters[counter_key] = current_seq
            self._initialized[counter_key] = True

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
        已初始化的计数器直接使用内存值，无需再查库。

        Returns:
            str: 格式为 PREFIX-YYYYMMDD-XXXX
        """
        today = datetime.now()
        date_str = today.strftime('%Y%m%d')

        async with self._lock:
            self._cleanup_old_entries()

            counter_key = f"{prefix}:{date_str}"
            if self._initialized.get(counter_key):
                db_max = self._counters.get(counter_key, 0)
            else:
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
            self._initialized[counter_key] = True

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
