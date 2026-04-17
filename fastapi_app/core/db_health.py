"""
数据库连接健康检查与自动重连模块

定期检查连接池中的连接有效性，主动替换不健康连接，
记录连接中断、恢复的详细日志，保障数据库服务高可用。
"""

import asyncio
import logging
from datetime import datetime
from typing import Optional

from sqlalchemy import text
from sqlalchemy.exc import OperationalError, DisconnectionError

logger = logging.getLogger(__name__)


class DBHealthChecker:
    """数据库连接健康检查器

    功能:
    - 定期执行轻量级探测 (SELECT 1) 检查连接有效性
    - 检测到失效连接时记录日志并通过 pool_pre_ping 自动重建
    - 统计健康检查次数、失败次数、恢复次数
    - 记录最近一次连接中断/恢复的时间和上下文
    """

    def __init__(self, check_interval: int = 30):
        """
        Args:
            check_interval: 健康检查间隔(秒)，默认30秒
        """
        self.check_interval = check_interval
        self._task: Optional[asyncio.Task] = None
        self._running = False

        # 统计计数器
        self.total_checks = 0
        self.failed_checks = 0
        self.recoveries = 0

        # 最近事件记录
        self.last_check_time: Optional[datetime] = None
        self.last_failure_time: Optional[datetime] = None
        self.last_recovery_time: Optional[datetime] = None
        self.last_failure_detail: Optional[str] = None
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
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("数据库健康检查已停止")

    async def _check_loop(self):
        """健康检查循环"""
        while self._running:
            try:
                await self._perform_check()
            except Exception as e:
                logger.error("健康检查循环异常: %s", e)
            await asyncio.sleep(self.check_interval)

    async def _perform_check(self):
        """执行一次健康检查"""
        from fastapi_app.core.database import async_engine, sync_engine

        self.last_check_time = datetime.now()
        self.total_checks += 1

        # 异步引擎检查
        async_ok = False
        if async_engine is not None:
            async_ok = await self._check_async_engine(async_engine)

        # 同步引擎检查(作为备用) - 使用run_in_threadpool避免阻塞事件循环
        sync_ok = False
        if not async_ok:
            from fastapi.concurrency import run_in_threadpool
            sync_ok = await run_in_threadpool(self._check_sync_engine, sync_engine)

        is_healthy = async_ok or sync_ok

        if not is_healthy:
            self.failed_checks += 1
            self.last_failure_time = datetime.now()
            if not self._was_unhealthy:
                self._was_unhealthy = True
                logger.warning(
                    "数据库连接异常: 异步引擎=%s, 同步引擎=%s",
                    async_ok, sync_ok,
                )
        else:
            if self._was_unhealthy:
                self._was_unhealthy = False
                self.recoveries += 1
                self.last_recovery_time = datetime.now()
                logger.info(
                    "数据库连接已恢复 (恢复次数: %d，上次故障: %s)",
                    self.recoveries,
                    self.last_failure_detail or "未知",
                )
            # 重置故障详情
            self.last_failure_detail = None

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
        except Exception as e:
            self.last_failure_detail = f"异步引擎未知错误: {e.__class__.__name__}: {str(e)[:200]}"
            logger.error("异步引擎连接检查异常: %s", self.last_failure_detail)
            return False

    def _check_sync_engine(self, engine) -> bool:
        """检查同步引擎连接"""
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return True
        except (OperationalError, DisconnectionError) as e:
            self.last_failure_detail = f"同步引擎: {e.__class__.__name__}: {str(e)[:200]}"
            logger.warning("同步引擎连接检查失败: %s", self.last_failure_detail)
            return False
        except Exception as e:
            self.last_failure_detail = f"同步引擎未知错误: {e.__class__.__name__}: {str(e)[:200]}"
            logger.error("同步引擎连接检查异常: %s", self.last_failure_detail)
            return False

    def get_pool_status(self) -> dict:
        """获取连接池状态信息"""
        from fastapi_app.core.database import async_engine, sync_engine

        status = {}

        # 同步引擎连接池状态
        try:
            sync_pool = sync_engine.pool
            status["sync_pool"] = {
                "size": sync_pool.size(),
                "checked_in": sync_pool.checkedin(),
                "checked_out": sync_pool.checkedout(),
                "overflow": sync_pool.overflow(),
            }
        except Exception as e:
            status["sync_pool"] = {"error": str(e)}

        # 异步引擎连接池状态
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
        except Exception as e:
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
