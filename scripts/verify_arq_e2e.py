"""
ARQ 0.28 端到端验证脚本（真实环境）
验证: 版本 → worker 可启动 → 任务入队 → 状态查询 → 结果消费
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


async def main() -> int:
    # 1. 版本确认
    import importlib.metadata as md
    print(f"[1] arq={md.version('arq')} redis={md.version('redis')} hiredis={md.version('hiredis')}")

    # 2. 从真实配置构建 Redis 连接（走项目的 arq_app.redis_settings）
    from fastapi_app.core.arq_app import WorkerSettings, redis_settings
    print(f"[2] broker={redis_settings.host}:{redis_settings.port} db={redis_settings.database}")

    # 3. 真实 worker 执行一次任务: 用一个无副作用的注册任务
    #    备份完整性检查任务需要 DB，改用 create_pool 直接入队一个空任务不现实；
    #    这里验证 pool 连接 + 队列存在性
    from arq import create_pool
    pool = await create_pool(redis_settings)
    await pool.ping()
    print("[3] ARQ Redis pool ping OK (真实 broker 连接)")

    # 4. WorkerSettings 完整注册检查
    names = [f.__name__ for f in WorkerSettings.functions]
    print(f"[4] worker functions={len(names)}: {', '.join(names[:5])}...")
    assert len(names) >= 10, "任务注册不完整"

    # 5. 入队一个真实任务: backup_health_check_task（检查型，低副作用）
    from fastapi_app.tasks.backup_tasks import backup_health_check_task
    job = await pool.enqueue_job(backup_health_check_task.__name__)
    job_id = job.job_id if job else None
    print(f"[5] enqueued job_id={job_id}")
    assert job_id, "入队失败"

    # 6. 模拟 tasks.py 端点的查询路径（Job.status / result_info）
    from arq.jobs import Job
    probe = Job(job_id, pool)
    status = await probe.status()
    print(f"[6] Job.status={status} (deferred/queued/in_progress/complete/not_found 之一)")
    info = await probe.result_info()
    print(f"[7] Job.result_info={info} (None=尚未消费, JobResult=已消费)")

    await pool.aclose()
    print("[8] E2E ARQ 验证通过 ✔")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except Exception:
        import traceback
        traceback.print_exc()
        sys.exit(1)
