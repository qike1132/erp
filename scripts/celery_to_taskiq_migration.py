"""
Celery 积压任务迁移脚本
整改: 将 Celery 积压任务迁移到 Taskiq，确保任务零丢失
"""
import asyncio
import json
import logging
from datetime import datetime
from typing import Dict, List, Any

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class CeleryTaskMigrator:
    """Celery 任务迁移器"""
    
    def __init__(self, celery_app, taskiq_broker):
        self.celery_app = celery_app
        self.taskiq_broker = taskiq_broker
        self.migrated_count = 0
        self.failed_count = 0
    
    async def inspect_queues(self) -> Dict[str, Any]:
        """检查 Celery 队列状态"""
        inspect = self.celery_app.control.inspect()
        
        queues = {
            "active": inspect.active() or {},
            "scheduled": inspect.scheduled() or {},
            "reserved": inspect.reserved() or {},
            "revoked": inspect.revoked() or {},
        }
        
        total_tasks = 0
        for queue_type, workers in queues.items():
            count = sum(len(tasks) for tasks in workers.values())
            total_tasks += count
            logger.info(f"{queue_type}: {count} 个任务")
        
        logger.info(f"总计待迁移任务: {total_tasks}")
        return queues
    
    async def migrate_task(self, task_data: Dict[str, Any]) -> bool:
        """迁移单个任务到 Taskiq"""
        try:
            task_name = task_data.get("task", "")
            args = task_data.get("args", [])
            kwargs = task_data.get("kwargs", {})
            
            # 发送到 Taskiq
            await self.taskiq_broker.send_task(
                task_name=task_name,
                args=args,
                kwargs=kwargs,
            )
            
            self.migrated_count += 1
            logger.info(f"任务迁移成功: {task_name}")
            return True
            
        except Exception as e:
            self.failed_count += 1
            logger.error(f"任务迁移失败: {e}")
            return False
    
    async def migrate_all(self) -> Dict[str, int]:
        """迁移所有积压任务"""
        logger.info("开始 Celery 任务迁移...")
        
        queues = await self.inspect_queues()
        
        # 迁移 scheduled 任务
        for worker, tasks in queues["scheduled"].items():
            for task in tasks:
                await self.migrate_task(task["request"])
        
        # 迁移 reserved 任务
        for worker, tasks in queues["reserved"].items():
            for task in tasks:
                await self.migrate_task(task)
        
        # 注意: active 任务正在执行，等待完成而非迁移
        logger.info("active 任务正在执行，等待自然完成...")
        
        result = {
            "migrated": self.migrated_count,
            "failed": self.failed_count,
            "total": self.migrated_count + self.failed_count,
        }
        
        logger.info(f"迁移完成: {result}")
        return result
    
    async def wait_for_active_tasks(self, timeout: int = 600) -> bool:
        """等待活跃任务完成"""
        logger.info(f"等待活跃任务完成（超时: {timeout}秒）...")
        
        start_time = datetime.now()
        while True:
            inspect = self.celery_app.control.inspect()
            active = inspect.active() or {}
            active_count = sum(len(tasks) for tasks in active.values())
            
            if active_count == 0:
                logger.info("所有活跃任务已完成")
                return True
            
            elapsed = (datetime.now() - start_time).total_seconds()
            if elapsed > timeout:
                logger.warning(f"等待超时，仍有 {active_count} 个活跃任务")
                return False
            
            logger.info(f"等待中... 剩余 {active_count} 个活跃任务")
            await asyncio.sleep(10)


async def main():
    """主函数"""
    from celery import Celery
    from fastapi_app.core.taskiq_broker import broker
    
    # 初始化 Celery
    celery_app = Celery("erp_tasks")
    celery_app.config_from_object("celeryconfig")
    
    # 创建迁移器
    migrator = CeleryTaskMigrator(celery_app, broker)
    
    # 步骤1: 等待活跃任务完成
    await migrator.wait_for_active_tasks(timeout=600)
    
    # 步骤2: 迁移积压任务
    result = await migrator.migrate_all()
    
    # 步骤3: 输出报告
    report = {
        "timestamp": datetime.now().isoformat(),
        "result": result,
        "status": "success" if result["failed"] == 0 else "partial",
    }
    
    with open("migration_report.json", "w") as f:
        json.dump(report, f, indent=2)
    
    logger.info(f"迁移报告已保存: migration_report.json")
    return report


if __name__ == "__main__":
    asyncio.run(main())
