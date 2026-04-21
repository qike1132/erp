"""
双写数据库中间件（带重试和死信队列）
整改: MySQL → PostgreSQL 迁移期间使用
"""
import asyncio
import json
import uuid
import logging
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from typing import Optional

logger = logging.getLogger(__name__)


class DualWriteSession:
    """双写数据库会话管理器（带重试和死信队列）"""

    def __init__(self, mysql_session: AsyncSession, pg_session: AsyncSession, redis_client=None):
        self.mysql = mysql_session
        self.pg = pg_session
        self.redis = redis_client
        self.max_retries = 3
        self.retry_delay = 1  # 秒

    async def execute_write(self, sql, params=None, operation_id: str = None):
        """双写：先写 MySQL，再写 PostgreSQL（带重试机制）"""
        operation_id = operation_id or str(uuid.uuid4())
        
        # 步骤1: 写入 MySQL（主库）
        try:
            await self.mysql.execute(sql, params or {})
            await self.mysql.commit()
            logger.info(f"[{operation_id}] MySQL 写入成功")
        except Exception as e:
            await self.mysql.rollback()
            logger.error(f"[{operation_id}] MySQL 写入失败: {e}")
            raise  # MySQL 失败必须抛出，这是主库

        # 步骤2: 写入 PostgreSQL（从库，带重试）
        pg_success = False
        last_error = None
        
        for attempt in range(1, self.max_retries + 1):
            try:
                await self.pg.execute(sql, params or {})
                await self.pg.commit()
                pg_success = True
                logger.info(f"[{operation_id}] PostgreSQL 写入成功（尝试 {attempt}）")
                break
            except Exception as e:
                await self.pg.rollback()
                last_error = e
                logger.warning(f"[{operation_id}] PostgreSQL 写入失败（尝试 {attempt}/{self.max_retries}）: {e}")
                if attempt < self.max_retries:
                    await asyncio.sleep(self.retry_delay * attempt)  # 指数退避

        # 步骤3: 处理 PG 写入失败（死信队列）
        if not pg_success:
            error_msg = f"[{operation_id}] PostgreSQL 写入最终失败: {last_error}"
            logger.error(error_msg)
            
            # 写入死信队列（Redis）
            if self.redis:
                dead_letter = {
                    "operation_id": operation_id,
                    "sql": str(sql),
                    "params": params,
                    "error": str(last_error),
                    "timestamp": datetime.utcnow().isoformat(),
                    "retry_count": self.max_retries
                }
                await self.redis.lpush("pg_dead_letter_queue", json.dumps(dead_letter))
                logger.info(f"[{operation_id}] 已写入死信队列")
            
            # 发送告警通知
            await self._send_alert(operation_id, last_error)
            
            # 不抛出异常，允许业务继续（但记录不一致状态）

    async def execute_read(self, sql, params=None, prefer_pg: bool = True):
        """读取：优先从 PostgreSQL 读取"""
        source = self.pg if prefer_pg else self.mysql
        return await source.execute(sql, params or {})
    
    async def _send_alert(self, operation_id: str, error: Exception):
        """发送告警通知（可集成企业微信/钉钉/邮件）"""
        alert_msg = f"【双写异常】操作ID: {operation_id}, 错误: {error}"
        logger.critical(alert_msg)
        # TODO: 集成实际告警通道


class DeadLetterReplayer:
    """死信队列重放器（用于修复数据不一致）"""
    
    def __init__(self, pg_engine, redis_client):
        self.pg_engine = pg_engine
        self.redis = redis_client
    
    async def replay_dead_letters(self, batch_size: int = 100):
        """重放死信队列中的操作"""
        replayed = 0
        failed = 0
        
        for _ in range(batch_size):
            item = await self.redis.rpop("pg_dead_letter_queue")
            if not item:
                break
            
            data = json.loads(item)
            try:
                async with self.pg_engine.connect() as conn:
                    await conn.execute(text(data["sql"]), data["params"])
                    await conn.commit()
                    replayed += 1
                    logger.info(f"死信重放成功: {data['operation_id']}")
            except Exception as e:
                failed += 1
                # 重新放入队列尾部（带重试次数检查）
                data["retry_count"] = data.get("retry_count", 0) + 1
                if data["retry_count"] < 5:
                    await self.redis.lpush("pg_dead_letter_queue", json.dumps(data))
                else:
                    await self.redis.lpush("pg_dead_letter_failed", json.dumps(data))
                    logger.error(f"死信重放最终失败: {data['operation_id']}")
        
        return {"replayed": replayed, "failed": failed}
