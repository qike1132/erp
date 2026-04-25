# Taskiq vs Celery 评估报告

**评估日期**: 2026-04-21
**评估目的**: 决定是否将 Celery 5.6.3 替换为 Taskiq 0.11.0
**当前状态**: Celery 5.6.3 生产运行稳定，5 个 @shared_task，3 个队列

---

## 1. 评估结论：保留 Celery，暂不替换 Taskiq

**理由**:
1. Celery 5.6+ 已配置 JSON 序列化、任务路由、Worker 生命周期管理，满足当前 5 个任务的需求
2. Taskiq 社区规模（~1.5k stars）远小于 Celery（24k stars），生产验证不足
3. 迁移成本约 5 人天，但当前任务量（5 个）无法充分体现 Taskiq 的 async 原生优势
4. Celery 已添加 Flower 监控 + Prometheus 指标导出，可观测性满足需求

## 2. 量化对比

| 维度 | Celery 5.6+ (优化后) | Taskiq 0.11.0 |
|------|---------------------|---------------|
| 生态成熟度 | 24k stars, 10+ 年 | ~1.5k stars, 3 年 |
| 当前兼容性 | 生产运行，5 任务稳定 | 需完整迁移 |
| 异步原生 | 否（同步 Worker） | 是（原生 async/await） |
| 调度延迟 | ~180ms | 预期 <=60ms |
| 迁移成本 | 0 | ~5 人天 |
| 监控生态 | Flower + celery-exporter | 内置 Prometheus 中间件 |
| Redis Broker | 成熟支持 | 支持 |
| 定时调度 | Celery Beat（已配置） | Taskiq Scheduler |

## 3. 保留 Taskiq 作为阶段二选项

如果阶段二（PG 迁移后）出现以下任一条件，重新评估 Taskiq:
- Celery Worker 内存泄漏（当前配置 max_memory_per_child=300MB 缓解）
- 任务延迟需求 < 60ms
- 任务数量增长到 20+，需要更细粒度的 async 资源管理
- Celery 与 asyncpg 集成出现问题

## 4. 阶段一 Celery 优化措施（已实施）

- Worker 并发: prefetch_multiplier=1, max_tasks_per_child=1000, max_memory_per_child=300MB
- 任务路由: batch / reports / celery 三个显式队列
- 事件监控: task_send_sent_event + worker_send_task_events
- Redis Broker: visibility_timeout=7200, max_connections=20
- 监控部署: Flower (5555端口) + celery-exporter (9808端口, Prometheus)
