"""
数据库连接健康检查与自动重连模块 - 全异步模式

定期检查连接池中的连接有效性，主动替换不健康连接。
"""

import asyncio
import contextlib
import logging
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.exc import DisconnectionError, OperationalError

logger = logging.getLogger(__name__)


class DBHealthChecker:
    """数据库连接健康检查器 - 全异步模式"""

    def __init__(self, check_interval: int = 30):
        self.check_interval = check_interval
        self._task: asyncio.Task | None = None
        self._running = False

        # 统计计数器
        self.total_checks = 0
        self.failed_checks = 0
        self.recoveries = 0

        # 最近事件记录
        self.last_check_time: datetime | None = None
        self.last_failure_time: datetime | None = None
        self.last_recovery_time: datetime | None = None
        self.last_failure_detail: str | None = None
        self._was_unhealthy = False

    async def start(self):
        """启动后台健康检查任务"""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._check_loop())
        logger.info(
            "数据库健康检查已启动，间隔 %d 秒",
            self.check_interval,
        )

    async def stop(self):
        """停止后台健康检查任务"""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        logger.info("数据库健康检查已停止")

    async def _check_loop(self):
        """健康检查循环"""
        while self._running:
            try:
                await self._perform_check()
            except (OperationalError, DisconnectionError) as e:
                logger.error("健康检查循环异常: %s", e)
            await asyncio.sleep(self.check_interval)

    async def _perform_check(self):
        """执行一次健康检查"""
        from fastapi_app.core.database import async_engine

        self.last_check_time = datetime.now()
        self.total_checks += 1

        is_healthy = False
        if async_engine is not None:
            is_healthy = await self._check_async_engine(async_engine)
            self._update_pool_metrics(async_engine)

        if not is_healthy:
            self.failed_checks += 1
            self.last_failure_time = datetime.now()
            if not self._was_unhealthy:
                self._was_unhealthy = True
                logger.warning("数据库连接异常")
        else:
            if self._was_unhealthy:
                self._was_unhealthy = False
                self.recoveries += 1
                self.last_recovery_time = datetime.now()
                logger.info(
                    "数据库连接已恢复 (恢复次数: %d)",
                    self.recoveries,
                )
            self.last_failure_detail = None

    def _update_pool_metrics(self, engine):
        """更新连接池 Prometheus 指标"""
        try:
            from fastapi_app.core.metrics import (
                DB_POOL_SIZE, DB_POOL_CHECKED_OUT,
                DB_POOL_OVERFLOW, DB_POOL_CHECKEDIN,
            )
            pool = engine.pool
            DB_POOL_SIZE.labels(pool='async_main').set(pool.size())
            DB_POOL_CHECKED_OUT.labels(pool='async_main').set(pool.checkedout())
            DB_POOL_OVERFLOW.labels(pool='async_main').set(pool.overflow())
            DB_POOL_CHECKEDIN.labels(pool='async_main').set(pool.checkedin())

            from fastapi_app.core.database import _read_engine
            if _read_engine is not None:
                rpool = _read_engine.pool
                DB_POOL_SIZE.labels(pool='async_read').set(rpool.size())
                DB_POOL_CHECKED_OUT.labels(pool='async_read').set(rpool.checkedout())
                DB_POOL_OVERFLOW.labels(pool='async_read').set(rpool.overflow())
                DB_POOL_CHECKEDIN.labels(pool='async_read').set(rpool.checkedin())
        except Exception:
            pass

    async def _check_async_engine(self, engine) -> bool:
        """检查异步引擎连接"""
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            return True
        except (OperationalError, DisconnectionError) as e:
            self.last_failure_detail = f"异步引擎: {e.__class__.__name__}: {str(e)[:200]}"
            logger.warning("异步引擎连接检查失败: %s", self.last_failure_detail)
            return False

    def get_pool_status(self) -> dict:
        """获取连接池状态信息"""
        from fastapi_app.core.database import async_engine

        status = {}

        try:
            if async_engine is not None:
                async_pool = async_engine.pool
                status["async_pool"] = {
                    "size": async_pool.size(),
                    "checked_in": async_pool.checkedin(),
                    "checked_out": async_pool.checkedout(),
                    "overflow": async_pool.overflow(),
                }
            else:
                status["async_pool"] = {"status": "not_initialized"}
        except (OperationalError, DisconnectionError) as e:
            status["async_pool"] = {"error": str(e)}

        return status

    def get_stats(self) -> dict:
        """获取健康检查统计数据"""
        return {
            "total_checks": self.total_checks,
            "failed_checks": self.failed_checks,
            "recoveries": self.recoveries,
            "last_check_time": self.last_check_time.isoformat() if self.last_check_time else None,
            "last_failure_time": self.last_failure_time.isoformat() if self.last_failure_time else None,
            "last_recovery_time": self.last_recovery_time.isoformat() if self.last_recovery_time else None,
            "last_failure_detail": self.last_failure_detail,
            "is_healthy": not self._was_unhealthy,
            "check_interval": self.check_interval,
        }


# 全局单例
db_health_checker = DBHealthChecker(check_interval=30)
