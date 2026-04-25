# 滨发协同系统 - 系统整改方案

> **已废弃**: 本文档(v4.0)经审核发现 3 项事实性错误(P0)、7 项技术缺陷(P1)，已被 [`remediation-plan-v5-final.md`](remediation-plan-v5-final.md) 替代。请参阅 [`audit-report-remediation-plan.md`](audit-report-remediation-plan.md) 了解完整审核发现。v5.0 的核心修正：(1) 移除所有 Flask 遗留组件相关章节（Flask 已从代码库中完全移除）；(2) 驱动替换策略改为保持 asyncmy 直至 PG 迁移（原方案 asyncmy->pymysql 将导致 171 个异步路由完全中断）；(3) 双写方案改为 ORM 层双写（原方案 SQL 层双写在 MySQL/PG 方言不兼容时必然失败）。

**版本**: v4.0 (已废弃 - 请使用 v5.0)
**编制日期**: 2026-04-21
**更新说明**: 基于全面评估报告，整合 12 项改进建议（P0: 3 项，P1: 5 项，P2: 4 项）
**适用范围**: 后端、前端、部署运维（不含 CI/CD 流水线）
**审批状态**: 待审批

---

## 目录

1. [整改背景与目标](#1-整改背景与目标)
2. [整改前现状基线](#2-整改前现状基线)
3. [分项整改方案（基础）](#3-分项整改方案基础)
4. [专项整改方案一：MySQL → PostgreSQL 迁移](#4-专项整改方案一mysql--postgresql-迁移)
5. [专项整改方案二：前端完全重写（React 19 + Next.js 15）](#5-专项整改方案二前端完全重写react-19--nextjs-15)
6. [资源需求](#6-资源需求)
7. [时间节点与里程碑](#7-时间节点与里程碑)
8. [责任人矩阵](#8-责任人矩阵)
9. [整改前后量化对比](#9-整改前后量化对比)
10. [验收标准](#10-验收标准)
11. [风险管理与回滚方案](#11-风险管理与回滚方案)
12. [技术文档参考](#12-技术文档参考)

---

## 1. 整改背景与目标

### 1.1 整改背景

滨发协同系统当前已完成从 Flask 向 FastAPI 的迁移规划，FastAPI 作为主 API 框架（0.136.0），Flask 作为遗留组件保留。在技术栈全面升级的目标下，经全面审计发现以下关键问题：

| 问题域 | 核心问题 | 影响等级 |
|--------|---------|---------|
| **容器化** | 无 Dockerfile、无 docker-compose | 🔴 P0 |
| **数据库驱动** | asyncmy 已停止维护 | 🔴 P0 |
| **数据库架构** | MySQL 在复杂查询、JSON 操作上性能受限 | 🟠 P1 |
| **任务队列** | Celery 与 FastAPI 异步生态不匹配 | 🟠 P1 |
| **前端工程化** | 无构建系统，无类型安全，Jinja2 + 原生 JS 难以维护 | 🟠 P1 |
| **前端架构** | SSR 模板 + 零组件化，交互体验差 | 🟡 P2 |
| **高可用** | 单点故障，无水平扩展能力 | 🟠 P1 |
| **可观测性** | 无日志聚合，结构化日志缺失 | 🟡 P2 |
| **密码安全** | bcrypt 非 OWASP 推荐算法 | 🟡 P2 |

### 1.2 整改目标

| 序号 | 目标 | 量化指标 | 优先级 |
|------|------|---------|--------|
| G1 | 实现全栈容器化部署 | 环境一致性 100% 可重复 | P0 |
| G2 | 替换停更异步数据库驱动 | 消除安全漏洞风险 | P0 |
| G3 | MySQL → PostgreSQL 迁移 | 复杂查询性能提升 ≥50% | P1 |
| G4 | 前端引入构建体系（过渡方案） | 首屏加载体积减少 ≥60% | P1 |
| G5 | 前端完全重写（React + Next.js） | 首屏加载 ≤0.5s，可维护性 9/10 | P1 |
| G6 | 异步任务队列升级 | 任务处理延迟降低 ≥50% | P1 |
| G7 | 建立高可用架构 | 支持 3 实例水平扩展 | P1 |
| G8 | 完善可观测性 | 日志可搜索率 100% | P2 |
| G9 | 密码哈希算法升级 | 达到 OWASP 2026 标准 | P2 |

### 1.3 整改范围

**纳入范围**:
- ✅ 后端依赖升级与替换（asyncmy → pymysql → asyncpg、Celery → Taskiq、orjson → msgspec）
- ✅ 容器化建设（Dockerfile 多阶段构建、docker-compose 编排）
- ✅ 数据库迁移（MySQL 8.4 → PostgreSQL 17）
- ✅ 前端构建体系过渡（Vite + TypeScript）
- ✅ 前端完全重写（React 19 + Next.js 15 + App Router）
- ✅ 高可用架构（多副本、连接池优化、负载均衡、PgBouncer）
- ✅ 可观测性（Loki 日志聚合、结构化日志）
- ✅ 安全加固（Argon2id 密码哈希、Cookie SameSite 配置）
- ✅ Flask 遗留组件处理（run.py 双进程模式解耦）
- ✅ OCR 服务容器化（RapidOCR + RapidTable）

**排除范围**:
- ❌ CI/CD 流水线自动化（本次整改暂不纳入）

### 1.4 整改阶段划分

| 阶段 | 内容 | 周期 | 综合评分提升 |
|------|------|------|------------|
| **阶段一** | 基础整改（容器化、依赖升级、Vite 过渡、高可用） | 8 周 | 4.2 → 8.6 (+105%) |
| **阶段二** | PostgreSQL 迁移 | 4 周 | 8.6 → 9.0 (+5%) |
| **阶段三** | 前端 React/Next.js 重写 | 16 周 | 9.0 → 9.5 (+6%) |
| **总计** | 全部整改 | 28 周 | 4.2 → 9.5 (+126%) |

> **时间线调整说明**: 阶段三从 10 周延长至 16 周（+60%），原因：
> 1. ERP 系统包含 7+ 业务模块（订单、产品、库存、审批、财务、设置、通知），每个模块平均需 2 周
> 2. 需保留 2 周缓冲用于 Bug 修复、性能优化和跨浏览器兼容性处理
> 3. 团队 React/Next.js 学习曲线需 1-2 周适应期
> 4. 如时间紧迫，可采用"渐进式迁移"策略（见 5.7 节）

---

## 2. 整改前现状基线

### 2.1 性能基线

> **重要**: 以下基线值为预估/经验值，整改前必须在生产环境进行**实际测量**，以确保证据链完整。

**基线测量要求**:

```bash
# 1. API 性能测量（使用 k6 或 locust）
k6 run --vus 50 --duration 5m api_benchmark.js

# 2. 数据库查询延迟（使用 pg_stat_statements / performance_schema）
# MySQL: SELECT * FROM performance_schema.events_statements_summary_by_digest
# PostgreSQL: SELECT * FROM pg_stat_statements

# 3. 前端性能（使用 Lighthouse CI）
npx lighthouse-ci --url http://localhost:5003 --runs 5

# 4. 资源大小（使用 curl + wc）
curl -s http://localhost:5003/ | wc -c
curl -s http://localhost:5003/static/js/order.js | wc -c
```

| 指标 | 测量方法 | 当前值（预估） | 实际测量值（整改前填写） | 测量条件 |
|------|---------|--------------|------------------------|---------|
| API P95 响应时间 | Prometheus /metrics | ~120ms | ______ | 50 并发，无缓存预热 |
| API P99 响应时间 | Prometheus /metrics | ~350ms | ______ | 50 并发 |
| 数据库查询延迟 | 慢查询日志 (100ms) | 平均 45ms | ______ | 20 连接池 |
| 复杂 JOIN 查询 | 订单+产品+客户 | ~80ms | ______ | MySQL 8.4 |
| JSON 序列化延迟 | orjson dumps | ~8ms/10KB | ______ | 标准数据对象 |
| 前端首屏加载 | Network Timing API | ~2.8s | ______ | 首次访问，HTTP |
| 前端资源总大小 | DevTools Network | ~1.2MB | ______ | 含全部 Bootstrap/FA |
| 页面交互响应 | DOM 操作延迟 | ~200ms | ______ | 原生 JS |
| WebSocket 连接数 | notification_service | ~200 并发 | ______ | 单实例 |
| 健康检查延迟 | /api/health | ~15ms | ______ | 带 DB + Redis 检查 |
| 任务队列延迟 | Celery task round-trip | ~180ms | ______ | Redis broker |
| 启动时间 | 进程启动到就绪 | ~3.5s | ______ | 含连接池预热 |

### 2.2 架构基线

| 维度 | 现状 | 评分 (1-10) |
|------|------|------------|
| 容器化程度 | 无容器化，手动部署 | 2 |
| 水平扩展能力 | 单实例，无法扩展 | 1 |
| 故障自愈能力 | 无健康检查自愈 | 2 |
| 资源隔离 | 进程级隔离，非容器级 | 3 |
| 部署一致性 | 依赖手动配置，不一致风险高 | 2 |
| 环境可复制性 | 需人工安装依赖，无法一键复现 | 2 |

### 2.3 可观测性基线

| 维度 | 现状 | 评分 (1-10) |
|------|------|------------|
| 指标采集 | Prometheus + 自定义指标 | 7 |
| 日志采集 | 本地文件，无集中化 | 3 |
| 日志搜索 | 手动 SSH 到服务器 grep | 2 |
| 链路追踪 | 无 | 1 |
| 告警配置 | Prometheus AlertManager (未配置) | 3 |
| 仪表盘 | Grafana (基础) | 5 |

### 2.4 安全基线

| 维度 | 现状 | 评分 (1-10) |
|------|------|------------|
| 密码哈希 | bcrypt (cost=12) | 6 |
| CSRF 保护 | starlette-csrf (已启用) | 9 |
| 输入验证 | Pydantic v2 + bleach | 8 |
| Host Header 防护 | TrustedHostMiddleware | 8 |
| 速率限制 | SlowAPI 60/minute | 7 |
| 依赖安全 | pip-audit 扫描 | 6 |
| 数据加密 | HTTPS (生产) / HTTP (开发) | 5 |

### 2.5 前端基线

| 维度 | 现状 | 评分 (1-10) |
|------|------|------------|
| 构建系统 | 无 | 1 |
| 代码分割 | 无，全量加载 | 1 |
| 类型安全 | 原生 JS，无类型检查 | 1 |
| 组件化程度 | 零组件化，模板拼接 | 1 |
| 状态管理 | 全局变量 + DOM 操作 | 1 |
| 路由系统 | 服务端路由 (Jinja2) | 3 |
| 资源优化 | 未压缩，未 Tree Shaking | 3 |
| 开发体验 | 手动刷新，无 HMR | 2 |
| 依赖管理 | 无 package.json | 1 |

### 2.6 数据库基线（MySQL 8.4）

| 维度 | 现状 | 评分 (1-10) |
|------|------|------------|
| 复杂查询性能 | 基准 | 5 |
| JOIN 性能 | 嵌套循环，无哈希 JOIN | 4 |
| 并发写入 | 表锁/行锁竞争 | 5 |
| JSON 操作 | JSON 函数有限，无 JSONB | 3 |
| 全文搜索 | 需额外配置 | 4 |
| 高级特性 | 无物化视图、无部分索引 | 3 |
| 异步驱动生态 | asyncmy 已停更 | 3 |
| 连接池效率 | 中等 | 5 |

---

## 3. 分项整改方案（基础）

### 3.1 分项一：后端依赖升级与替换

#### 3.1.1 异步数据库驱动替换

**问题**: asyncmy (0.2.11) 已停止维护，存在安全漏洞风险。

**方案**: 由于阶段二将迁移到 PostgreSQL，驱动将替换为 **asyncpg 0.30.0**（阶段二实施）。

**阶段一过渡方案**: 使用 **pymysql 1.1.1+** 作为临时替代（同步驱动，避免 aiomysql 的双重迁移浪费）。

> **决策理由**: aiomysql 与 asyncmy 均为 MySQL 异步驱动，阶段二迁移到 PostgreSQL 后两者都会被替换为 asyncpg。使用 pymysql 可避免"asyncmy → aiomysql → asyncpg"的双重迁移，减少工作量。

**实施步骤**:

```
步骤 1: 安装 pymysql 最新版
步骤 2: 修改 DATABASE_URL 驱动前缀: mysql+asyncmy → mysql+pymysql
步骤 3: FastAPI 端使用同步会话（阶段一临时方案）
步骤 4: 验证连接池行为一致性
步骤 5: 运行全量测试套件
```

**量化预期**:
- 安全性：消除停更驱动漏洞风险（100% 消除）
- 工作量：减少 50%（避免 aiomysql 的适配工作）
- 性能：略有下降（同步 vs 异步），但阶段二即迁移到 PostgreSQL + asyncpg

#### 3.1.2 任务队列升级

**方案**: 使用 **Taskiq 0.11.0** 替代 Celery。

**实施步骤**:

```
步骤 1: 安装 taskiq[redis] + taskiq-scheduler
步骤 2: 定义 Taskiq broker 替代 Celery app
步骤 3: 迁移 @celery.task 装饰器为 @broker.task
步骤 4: 迁移 Celery Beat 定时任务为 Taskiq scheduler
步骤 5: 验证所有后台任务正常运行
```

**Celery 积压任务迁移策略**:

```python
# celery_to_taskiq_migration.py - 积压任务迁移脚本
import asyncio
from celery.task.control import inspect
from taskiq import BrokerMessage

async def migrate_celery_backlog(taskiq_broker):
    """
    迁移 Celery 积压任务到 Taskiq
    在切换期间运行，确保无任务丢失
    """
    i = inspect()
    
    # 获取所有队列中的积压任务
    scheduled = i.scheduled() or {}
    active = i.active() or {}
    reserved = i.reserved() or {}
    
    total_migrated = 0
    
    for worker, tasks in scheduled.items():
        for task in tasks:
            # 转换为 Taskiq 消息格式
            message = BrokerMessage(
                task_name=task["request"]["task"],
                labels={},
                args=task["request"]["args"],
                kwargs=task["request"]["kwargs"],
            )
            await taskiq_broker.enqueue(message)
            total_migrated += 1
    
    # 等待活跃任务完成
    for worker, tasks in active.items():
        print(f"等待 {worker} 上的 {len(tasks)} 个活跃任务完成...")
        # 实际实现需要轮询等待
    
    print(f"已迁移 {total_migrated} 个积压任务到 Taskiq")
    return total_migrated
```

**迁移时序**:

| 阶段 | 操作 | 说明 |
|------|------|------|
| 1 | 停止 Celery Beat（定时任务调度） | 防止新定时任务产生 |
| 2 | 等待活跃任务完成（或设置超时） | 最多等待 10 分钟 |
| 3 | 迁移积压任务到 Taskiq | 使用上述脚本 |
| 4 | 启动 Taskiq Worker | 开始处理新任务 |
| 5 | 启动 Taskiq Scheduler | 恢复定时任务 |
| 6 | 停止 Celery Worker | 完全下线 Celery |

**量化预期**:
- 任务调度延迟：180ms → ≤60ms（降低 ≥67%）
- Worker 内存占用：减少 20-30%
- 任务零丢失：100% 迁移积压任务

#### 3.1.3 JSON 序列化升级

**方案**: 使用 **msgspec 0.19.0** 替代 orjson。

**量化预期**:
- JSON 序列化速度：8ms → ≤3ms/10KB（提升 ≥62%）
- 内存占用：减少 40-50%

### 3.2 分项二：容器化建设

#### 3.2.1 Dockerfile 多阶段构建

```
Stage 1 (frontend-builder):  Node 22 Alpine + Vite 构建前端资源
Stage 2 (python-builder):    Python 3.13 slim + pip 安装依赖
Stage 3 (production):        Python 3.13 slim + 仅复制运行所需文件
```

**镜像优化目标**:
- 最终镜像大小: ≤350MB
- 构建时间: ≤90s
- 安全扫描: Trivy 零高危漏洞

#### 3.2.2 docker-compose 生产编排

**服务清单**（阶段一：MySQL）:

| 服务 | 镜像 | 副本数 | 内存限制 |
|------|------|--------|---------|
| app | 自构建 | 3 | 2GB |
| nginx | nginx:1.27-alpine | 1 | 256MB |
| mysql | mysql:8.4-lts | 1 | 4GB |
| redis | redis:7.4-alpine | 1 | 2GB |
| taskiq-worker | 自构建 | 2 | 1GB |
| ocr-service | 自构建 | 1 | 2GB |
| prometheus | prom/prometheus:v2.55.0 | 1 | 1GB |
| grafana | grafana/grafana:11.5.0 | 1 | 512MB |
| loki | grafana/loki:3.4.0 | 1 | 512MB |

**OCR 服务容器化说明**:
- RapidOCR + RapidTable 作为独立服务运行
- 通过 gRPC/HTTP API 与主应用通信
- 支持水平扩展（CPU 密集型，可根据负载增加副本）
- 模型文件挂载为只读卷，避免重复下载

### 3.3 分项三：前端构建体系（过渡方案）

**技术选型**: Vite 6.3.0 + TypeScript 5.8.0 + Tailwind CSS 4.1.0

**量化预期**:
- 首屏资源体积: 1.2MB → ≤400KB（减少 ≥67%）
- 首屏加载时间: 2.8s → ≤1.2s（减少 ≥57%）

### 3.4 分项四：高可用架构

**目标**: 3 实例水平扩展，Nginx 负载均衡。

**量化预期**:
- 吞吐量: ~500 RPS → ≥1500 RPS（提升 ≥200%）
- 可用性: 99.5% → 99.99%

### 3.5 分项五：可观测性升级

**方案**: Loki 3.4.0 + Promtail + 结构化日志。

**量化预期**:
- 日志搜索效率: ~5min → ≤10s（提升 ≥97%）
- 故障定位时间: ~30min → ≤5min（减少 ≥83%）

### 3.6 分项六：安全加固

**方案**: argon2-cffi 23.1.0（Argon2id 算法）。

**量化预期**:
- 抗 GPU 攻击: 提升 10x
- 安全评分: 6/10 → 9/10

---

## 4. 专项整改方案一：MySQL → PostgreSQL 迁移

### 4.1 迁移概述

| 项目 | 说明 |
|------|------|
| 源数据库 | MySQL 8.4 (utf8mb4) |
| 目标数据库 | PostgreSQL 17 (UTF-8) |
| 数据量预估 | **必须在迁移前测量**（见 4.1.1 节） |
| 迁移策略 | 双写过渡 + 增量同步 + 只读模式切换 |
| 预期停机时间 | ≤15 分钟（最终切换窗口） |
| ORM 框架 | SQLAlchemy 2.0（天然支持多数据库） |

#### 4.1.1 数据量评估要求（前置条件）

**迁移前必须完成的数据量测量**:

```sql
-- 测量各表数据量
SELECT 
    table_name,
    table_rows,
    ROUND(data_length / 1024 / 1024, 2) AS data_size_mb,
    ROUND(index_length / 1024 / 1024, 2) AS index_size_mb
FROM information_schema.tables
WHERE table_schema = 'erp_system'
ORDER BY data_length DESC;

-- 测量总数据量
SELECT 
    ROUND(SUM(data_length) / 1024 / 1024 / 1024, 2) AS total_data_gb,
    ROUND(SUM(index_length) / 1024 / 1024 / 1024, 2) AS total_index_gb,
    SUM(table_rows) AS total_rows
FROM information_schema.tables
WHERE table_schema = 'erp_system';
```

**数据量评估标准**:

| 数据规模 | 总数据量 | 迁移工具选择 | 预估迁移时间 |
|---------|---------|------------|------------|
| 小型 | < 10GB | pgloader（推荐） | 1-2 小时 |
| 中型 | 10-100GB | pgloader + 并行 ETL | 4-8 小时 |
| 大型 | 100-500GB | 自定义 ETL + 分批迁移 | 1-2 天 |
| 超大型 | > 500GB | 专业迁移服务 + 逻辑复制 | 3-7 天 |

**决策影响**:
- 数据量 < 50GB：可采用简单双写过渡
- 数据量 > 50GB：需采用逻辑复制（MySQL binlog → PostgreSQL）或分表迁移
- 数据量 > 200GB：建议采用专业工具（如 AWS DMS、Debezium）或分阶段迁移

### 4.2 迁移前准备

#### 4.2.1 数据备份策略

**三层备份**:

| 层级 | 方式 | 保留期 | 恢复时间 |
|------|------|--------|---------|
| 逻辑备份 | `mysqldump --single-transaction` | 永久 | ~30min |
| 物理备份 | Percona XtraBackup 热备 | 7 天 | ~10min |
| 二进制日志 | mysqlbinlog 增量备份 | 30 天 | 按需恢复 |

**备份脚本**:

```bash
#!/bin/bash
# full_backup.sh - 全量逻辑备份
BACKUP_DIR="/backup/mysql/$(date +%Y%m%d_%H%M%S)"
mkdir -p "$BACKUP_DIR"

# 逻辑备份
mysqldump \
  --single-transaction \
  --routines \
  --triggers \
  --events \
  --hex-blob \
  --set-gtid-purged=OFF \
  --result-file="$BACKUP_DIR/erp_full.sql" \
  erp_system

# 物理备份（Percona XtraBackup）
xtrabackup --backup \
  --target-dir="$BACKUP_DIR/xtrabackup" \
  --user=root \
  --password="$MYSQL_ROOT_PASSWORD"

# 记录备份完成位点
mysql -e "SHOW MASTER STATUS\G" > "$BACKUP_DIR/binlog_position.txt"

echo "备份完成: $BACKUP_DIR"
```

**备份验证**:

```bash
# 在测试环境恢复备份，验证完整性
mysql -e "CREATE DATABASE erp_restore"
mysql erp_restore < /backup/mysql/latest/erp_full.sql

# 数据一致性检查
python scripts/verify_backup.py --source erp_system --target erp_restore
```

#### 4.2.2 模式差异分析与转换

**MySQL → PostgreSQL 类型映射**:

| MySQL 类型 | PostgreSQL 类型 | 注意事项 |
|-----------|----------------|---------|
| INT | INTEGER | 兼容 |
| BIGINT | BIGINT | 兼容 |
| TINYINT(1) | BOOLEAN 或 SMALLINT | 布尔字段需转换 |
| VARCHAR(n) | VARCHAR(n) | 兼容 |
| TEXT | TEXT | 兼容 |
| DATETIME | TIMESTAMP | 注意时区处理 |
| TIMESTAMP | TIMESTAMPTZ | PG 推荐带时区 |
| DECIMAL(m,n) | NUMERIC(m,n) | 语义相同 |
| FLOAT | DOUBLE PRECISION | PG 无单精度 FLOAT |
| JSON | JSONB | JSONB 性能更优，支持索引 |
| ENUM | ENUM 类型或 CHECK 约束 | PG ENUM 需提前注册 |
| BLOB | BYTEA | 二进制数据 |
| TINYTEXT | TEXT | PG 无 TEXT 长度限制 |

**SQL 方言差异**:

| 特性 | MySQL | PostgreSQL | 转换规则 |
|------|-------|-----------|---------|
| 自增主键 | `AUTO_INCREMENT` | `GENERATED ALWAYS AS IDENTITY` | Alembic 自动处理 |
| 引号 | 反引号 `` `table` `` | 双引号 `"table"` | SQLAlchemy 自动处理 |
| LIMIT | `LIMIT n OFFSET m` | `LIMIT n OFFSET m` | 兼容 |
| IFNULL | `IFNULL(a, b)` | `COALESCE(a, b)` | 需替换 |
| NOW() | `NOW()` | `NOW()` / `CURRENT_TIMESTAMP` | 兼容 |
| 字符串拼接 | `CONCAT(a, b)` | `a \|\| b` | 需替换 |
| 正则 | `REGEXP` | `~` / `~*` | 需替换 |
| GROUP BY | 宽松 | 严格 | 需确保所有非聚合列在 GROUP BY 中 |

#### 4.2.3 Alembic 迁移策略

由于项目已使用 Alembic 管理数据库迁移，迁移策略为：

```
步骤 1: 从 MySQL 导出完整 Alembic 迁移历史
步骤 2: 在 PostgreSQL 上从头执行所有 Alembic 迁移
步骤 3: 验证模式一致性（表结构、索引、约束）
步骤 4: 迁移数据（使用 pgloader 或自定义 ETL 脚本）
步骤 5: 验证数据一致性
```

**Alembic 配置切换**:

```python
# alembic.ini (PostgreSQL)
sqlalchemy.url = postgresql+asyncpg://erp_app:password@localhost:5432/erp_system
```

### 4.3 数据迁移执行

#### 4.3.1 方案一：pgloader（推荐，自动化程度高）

```bash
# 安装 pgloader
apt-get install pgloader

# 创建迁移配置
cat > mysql_to_pg.load << 'EOF'
LOAD DATABASE
  FROM mysql://erp_app:password@localhost:3306/erp_system
  INTO postgresql://erp_app:password@localhost:5432/erp_system

WITH include drop, create tables, create indexes, reset sequences

SET work_mem to '128MB', maintenance_work_mem to '256MB'

CAST type datetime to timestamptz drop default drop not null using zero-dates-to-nulls,
     type tinyint when (= precision 1) to boolean drop drop,
     type bigint when (= precision 20) to bigint drop drop,
     type json to jsonb using json-to-jsonb

BEFORE LOAD DO
  $$ CREATE SCHEMA IF NOT EXISTS public; $$;
EOF

# 执行迁移
pgloader mysql_to_pg.load
```

#### 4.3.2 方案二：自定义 ETL 脚本（可控性强）

```python
"""
mysql_to_postgres_migration.py
数据迁移脚本：从 MySQL 读取数据，写入 PostgreSQL
支持断点续传、数据校验、进度追踪
"""
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy import text, select, MetaData, Table
from typing import List, Dict, Any
import logging

logger = logging.getLogger(__name__)

class MySQLToPostgresMigrator:
    def __init__(self, mysql_url: str, pg_url: str, batch_size: int = 1000):
        self.mysql_engine = create_async_engine(mysql_url, pool_size=5)
        self.pg_engine = create_async_engine(pg_url, pool_size=5)
        self.batch_size = batch_size
        self.metadata = MetaData()

    async def migrate_table(self, table_name: str):
        """迁移单个表"""
        async with self.mysql_engine.connect() as mysql_conn:
            # 读取表结构
            result = await mysql_conn.execute(
                text(f"SELECT * FROM {table_name} LIMIT 1")
            )
            columns = list(result.keys())

            # 分批读取
            offset = 0
            total_migrated = 0
            while True:
                rows = await mysql_conn.execute(
                    text(f"SELECT * FROM {table_name} LIMIT {self.batch_size} OFFSET {offset}")
                )
                rows_list = [dict(r._mapping) for r in rows.fetchall()]
                if not rows_list:
                    break

                # 写入 PostgreSQL
                await self._insert_batch(table_name, columns, rows_list)
                total_migrated += len(rows_list)
                offset += self.batch_size
                logger.info(f"{table_name}: 已迁移 {total_migrated} 条")

        logger.info(f"表 {table_name} 迁移完成，共 {total_migrated} 条")

    async def _insert_batch(self, table_name: str, columns: List[str], rows: List[Dict]):
        """批量插入到 PostgreSQL"""
        if not rows:
            return
        async with self.pg_engine.connect() as pg_conn:
            col_names = ", ".join(columns)
            placeholders = ", ".join([f":{c}" for c in columns])
            sql = f"INSERT INTO {table_name} ({col_names}) VALUES ({placeholders})"
            await pg_conn.execute(text(sql), rows)
            await pg_conn.commit()

    async def migrate_all(self, tables: List[str]):
        """迁移所有表"""
        for table in tables:
            try:
                await self.migrate_table(table)
            except Exception as e:
                logger.error(f"表 {table} 迁移失败: {e}")
                raise

    async def close(self):
        await self.mysql_engine.dispose()
        await self.pg_engine.dispose()


async def main():
    migrator = MySQLToPostgresMigrator(
        mysql_url="mysql+aiomysql://erp_app:password@localhost:3306/erp_system",
        pg_url="postgresql+asyncpg://erp_app:password@localhost:5432/erp_system",
        batch_size=5000
    )
    try:
        await migrator.migrate_all([
            "users", "roles", "permissions", "products", "orders",
            "order_items", "customers", "suppliers", "stock_ins",
            "stock_outs", "approvals", "notifications", "audit_logs"
        ])
    finally:
        await migrator.close()


if __name__ == "__main__":
    asyncio.run(main())
```

#### 4.3.3 数据验证流程

**三层验证**:

| 验证层级 | 方法 | 预期结果 |
|---------|------|---------|
| 行数验证 | `SELECT COUNT(*)` 对比 | 源 = 目标（100% 匹配） |
| 字段验证 | 随机抽样 1000 条，逐字段比对 | 差异率 < 0.01% |
| 校验和验证 | `CHECKSUM TABLE` / `md5()` | 哈希值匹配 |

**验证脚本**:

```python
"""verify_migration.py - 数据迁移验证"""
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

async def verify_row_counts(mysql_engine, pg_engine, tables):
    """验证行数一致性"""
    results = {}
    for table in tables:
        mysql_count = await mysql_engine.execute(text(f"SELECT COUNT(*) FROM {table}"))
        pg_count = await pg_engine.execute(text(f"SELECT COUNT(*) FROM {table}"))
        m = mysql_count.scalar()
        p = pg_count.scalar()
        match = "✓" if m == p else "✗"
        results[table] = {"mysql": m, "pg": p, "match": match}
        if m != p:
            print(f"[FAIL] {table}: MySQL={m}, PG={p}")
        else:
            print(f"[OK]   {table}: {m} rows")
    return results

async def verify_sample_data(mysql_engine, pg_engine, table, columns, sample_size=1000):
    """随机抽样数据比对"""
    mysql_rows = await mysql_engine.execute(
        text(f"SELECT {','.join(columns)} FROM {table} ORDER BY RAND() LIMIT {sample_size}")
    )
    pg_rows = await pg_engine.execute(
        text(f"SELECT {','.join(columns)} FROM {table} ORDER BY RANDOM() LIMIT {sample_size}")
    )
    # 注意：随机排序不同，需按主键匹配
    # 实际验证需按主键 JOIN 比对
    pass
```

### 4.4 双写过渡方案

为确保零停机，采用双写过渡策略：

```
Phase 1 (第1-2天): MySQL 为主，PostgreSQL 只读同步
Phase 2 (第3-5天): 双写模式（写 MySQL + 写 PostgreSQL，以 MySQL 为准）
Phase 3 (第6-7天): PostgreSQL 为主，MySQL 只读回退
Phase 4 (第8天): 切换完成，关闭 MySQL 写入
```

#### 4.4.1 迁移期间只读模式方案

**切换窗口期间的只读模式实现**:

```python
# readonly_middleware.py - 迁移期间只读模式中间件
from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
import logging

logger = logging.getLogger(__name__)

class ReadOnlyMiddleware(BaseHTTPMiddleware):
    """
    迁移期间只读模式中间件
    - GET/HEAD 请求正常通过
    - POST/PUT/DELETE 请求返回 503 Service Unavailable
    """
    
    def __init__(self, app, enabled: bool = False, whitelist_paths: list = None):
        super().__init__(app)
        self.enabled = enabled
        self.whitelist_paths = whitelist_paths or ['/api/health', '/api/readiness']
    
    async def dispatch(self, request: Request, call_next):
        if not self.enabled:
            return await call_next(request)
        
        # 白名单路径跳过检查
        if any(request.url.path.startswith(path) for path in self.whitelist_paths):
            return await call_next(request)
        
        # 只读模式：只允许读操作
        if request.method in ['POST', 'PUT', 'DELETE', 'PATCH']:
            logger.warning(f"只读模式拦截: {request.method} {request.url.path}")
            raise HTTPException(
                status_code=503,
                detail={
                    "message": "系统正在维护中，暂不接受写入操作",
                    "retry_after": 900,  # 15 分钟后重试
                    "maintenance_window": "2026-XX-XX 02:00-02:15"
                }
            )
        
        return await call_next(request)


# 在 main.py 中启用（切换窗口期间）
# app.add_middleware(ReadOnlyMiddleware, enabled=True)
```

**前端只读模式提示**:

```typescript
// lib/api/client.ts - 只读模式拦截器
apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 503) {
      const data = error.response.data;
      toast.error(`系统维护中: ${data.message}，预计 ${data.retry_after} 秒后恢复`);
      // 禁用所有提交按钮
      document.body.classList.add('maintenance-mode');
    }
    return Promise.reject(error);
  }
);
```

**切换窗口操作流程**:

| 时间 | 操作 | 预计耗时 | 回滚点 |
|------|------|---------|--------|
| T+0min | 启用只读模式（中间件 + 前端提示） | 30s | 可随时关闭只读模式 |
| T+2min | 等待活跃写入完成（连接池排空） | 2min | - |
| T+4min | 执行最终增量同步（MySQL → PG） | 5min | 如失败，关闭只读模式恢复 |
| T+9min | 验证数据一致性（行数 + 校验和） | 3min | 如不一致，回滚 |
| T+12min | 切换 DATABASE_URL 到 PostgreSQL | 1min | - |
| T+13min | 重启应用实例（滚动重启） | 2min | - |
| T+15min | 关闭只读模式，验证写入功能 | 1min | - |
| **总计** | | **≤15min** | **4 个回滚点** |

**双写中间件实现**:

```python
"""dual_write_db.py - 双写数据库中间件"""
from sqlalchemy.ext.asyncio import AsyncSession
from contextlib import asynccontextmanager
import logging

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
            # 实际生产环境可能需要根据业务决定是否需要中断

    async def execute_read(self, sql, params=None, prefer_pg: bool = True):
        """读取：优先从 PostgreSQL 读取"""
        source = self.pg if prefer_pg else self.mysql
        return await source.execute(sql, params or {})
    
    async def _send_alert(self, operation_id: str, error: Exception):
        """发送告警通知（可集成企业微信/钉钉/邮件）"""
        alert_msg = f"【双写异常】操作ID: {operation_id}, 错误: {error}"
        logger.critical(alert_msg)
        # TODO: 集成实际告警通道
        # await send_wechat_alert(alert_msg)


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
```

### 4.5 SQLAlchemy 模型适配

项目使用 SQLAlchemy 2.0，天然支持多数据库。需调整项：

```python
# fastapi_app/core/config.py - 数据库 URL 更新
class Settings(BaseSettings):
    # PostgreSQL 配置
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        "postgresql+psycopg://erp_app:password@localhost:5432/erp_system"
    )
    ASYNC_DATABASE_URL: str = os.getenv(
        "ASYNC_DATABASE_URL",
        "postgresql+asyncpg://erp_app:password@localhost:5432/erp_system"
    )
```

**模型需调整项**:

| 模型属性 | MySQL 特有 | PostgreSQL 兼容 |
|---------|-----------|----------------|
| 引擎指定 | `__table_args__ = {'mysql_engine': 'InnoDB'}` | 移除或替换 |
| 自增主键 | `Column(Integer, primary_key=True, autoincrement=True)` | `Mapped[int] = mapped_column(primary_key=True)` |
| JSON 字段 | `Column(JSON)` | `Column(JSONB)` 推荐 |
| 索引类型 | `mysql_using='hash'` | 移除 |

### 4.6 PostgreSQL 专属优化

#### 4.6.1 连接池配置（PgBouncer）

```ini
# pgbouncer.ini - 完整配置
[databases]
erp_system = host=localhost port=5432 dbname=erp_system

[pgbouncer]
listen_port = 6432
listen_addr = 0.0.0.0
auth_type = md5
auth_file = /etc/pgbouncer/users.txt

# 连接池模式
pool_mode = transaction

# 客户端连接限制
max_client_conn = 500
default_pool_size = 25
min_pool_size = 10
reserve_pool_size = 5
reserve_pool_timeout = 3

# 服务端连接限制
max_db_connections = 100
max_user_connections = 100

# 连接生命周期（新增关键参数）
server_idle_timeout = 600        ; 空闲连接 10 分钟后关闭
server_lifetime = 3600           ; 连接最长存活 1 小时
server_connect_timeout = 15      ; 连接超时 15 秒
server_login_retry = 15          ; 登录重试间隔 15 秒

# 客户端超时
client_idle_timeout = 0          ; 不禁用客户端空闲超时
client_login_timeout = 60        ; 客户端登录超时 60 秒

# 健康检查
server_check_delay = 30          ; 健康检查间隔 30 秒
server_check_query = "SELECT 1"  ; 健康检查 SQL

# 日志配置
log_connections = 1
log_disconnections = 1
log_pooler_errors = 1
stats_period = 60

# 管理接口
admin_users = pgbouncer_admin
stats_users = pgbouncer_stats
```

**关键参数说明**:

| 参数 | 原配置 | 完整配置 | 说明 |
|------|--------|---------|------|
| server_idle_timeout | 缺失 | 600 | 防止空闲连接占用资源 |
| server_lifetime | 缺失 | 3600 | 定期回收连接，防止内存泄漏 |
| max_db_connections | 缺失 | 100 | 限制到 PostgreSQL 的总连接数 |
| server_check_delay | 缺失 | 30 | 定期检测后端健康状态 |

**连接数计算**:
```
总连接数 = app 实例数 × 每个实例连接池大小
         = 3 × 25 = 75（在 max_db_connections=100 范围内）

保留连接 = reserve_pool_size = 5（突发流量缓冲）
```

**docker-compose 集成**:

```yaml
  pgbouncer:
    image: edoburu/pgbouncer:1.23.0
    ports:
      - "6432:6432"
    volumes:
      - ./config/pgbouncer.ini:/etc/pgbouncer/pgbouncer.ini:ro
      - ./config/pgbouncer_users.txt:/etc/pgbouncer/users.txt:ro
    depends_on:
      - postgres
    networks:
      - backend
```

#### 4.6.2 索引优化

利用 PostgreSQL 高级索引特性：

```sql
-- GIN 索引（全文搜索）
CREATE INDEX idx_products_search ON products USING GIN(to_tsvector('chinese', name || ' ' || description));

-- 部分索引（仅索引未删除记录）
CREATE INDEX idx_orders_active ON orders(created_at) WHERE is_deleted = false;

-- 表达式索引
CREATE INDEX idx_users_lower_email ON users(LOWER(email));

-- 覆盖索引（Index-Only Scan）
CREATE INDEX idx_orders_covering ON orders(customer_id, status) INCLUDE (total_amount, created_at);
```

### 4.7 迁移风险评估

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|---------|
| 数据丢失 | 低 | 极高 | 三层备份 + 迁移前全量校验 |
| 类型转换错误 | 中 | 高 | 逐表类型映射验证 |
| SQL 方言不兼容 | 中 | 中 | Alembic 迁移测试 + 自动化测试覆盖 |
| 性能退化 | 低 | 高 | 迁移后基准测试对比 |
| 切换窗口超时 | 低 | 高 | 预演切换流程，准备回滚方案 |
| ORM 兼容问题 | 低 | 中 | SQLAlchemy 2.0 多数据库测试 |

---

## 5. 专项整改方案二：前端完全重写（React 19 + Next.js 15）

### 5.1 技术架构设计

#### 5.1.1 整体架构

```
┌─────────────────────────────────────────────────────────┐
│                    Nginx (反向代理)                      │
│  静态资源缓存 │ WebSocket 代理 │ API 反向代理            │
└────────────┬────────────────────────────────────────────┘
             │
    ┌────────┴────────┐
    │                 │
┌───▼──────┐  ┌──────▼──────────┐
│ Next.js  │  │  FastAPI (API)  │
│ (SSR/SSG)│  │  /api/v1/*      │
│ :3000    │  │  :5002          │
└──────────┘  └─────────────────┘
     │
┌────▼─────┐
│ 浏览器端  │
│ React SPA│
└──────────┘
```

**渲染策略**:

| 页面类型 | 渲染方式 | 理由 |
|---------|---------|------|
| 登录页 | SSG + CSR | 静态为主，交互简单 |
| 仪表盘 | SSR + 流式渲染 | 实时数据，首屏优先 |
| 订单列表 | SSR + ISR | 数据频繁更新，需缓存 |
| 订单详情 | SSR | 单页面，实时数据 |
| 审批流 | SSR + CSR | 复杂交互表单 |
| 库存管理 | SSR | 大量表格数据 |
| 设置页 | SSG | 纯静态 |

#### 5.1.2 目录结构

```
frontend/
├── src/
│   ├── app/                          # Next.js App Router
│   │   ├── layout.tsx                # 根布局（全局 Providers）
│   │   ├── page.tsx                  # 首页（仪表盘）
│   │   ├── login/
│   │   │   └── page.tsx              # 登录页
│   │   ├── orders/
│   │   │   ├── page.tsx              # 订单列表
│   │   │   ├── [id]/
│   │   │   │   └── page.tsx          # 订单详情
│   │   │   └── new/
│   │   │       └── page.tsx          # 新建订单
│   │   ├── products/
│   │   │   ├── page.tsx              # 产品列表
│   │   │   └── [id]/
│   │   │       └── page.tsx          # 产品详情
│   │   ├── stock/
│   │   │   ├── ins/page.tsx          # 入库管理
│   │   │   └── outs/page.tsx         # 出库管理
│   │   ├── approval/
│   │   │   ├── page.tsx              # 审批列表
│   │   │   └── [id]/page.tsx         # 审批详情
│   │   ├── finance/
│   │   │   └── page.tsx              # 财务管理
│   │   ├── settings/
│   │   │   └── page.tsx              # 系统设置
│   │   └── api/                      # Next.js API Routes（可选）
│   │       └── proxy/
│   │           └── route.ts          # BFF 层（代理 FastAPI）
│   │
│   ├── components/                   # 组件库
│   │   ├── ui/                       # 基础 UI 组件（shadcn/ui）
│   │   │   ├── button.tsx
│   │   │   ├── dialog.tsx
│   │   │   ├── table.tsx
│   │   │   ├── form.tsx
│   │   │   ├── dropdown-menu.tsx
│   │   │   └── ...
│   │   ├── layout/                   # 布局组件
│   │   │   ├── sidebar.tsx           # 侧边栏导航
│   │   │   ├── header.tsx            # 顶部栏
│   │   │   └── main-layout.tsx       # 主布局
│   │   ├── orders/                   # 业务组件
│   │   │   ├── order-table.tsx
│   │   │   ├── order-form.tsx
│   │   │   └── order-status-badge.tsx
│   │   ├── products/
│   │   ├── stock/
│   │   ├── approval/
│   │   └── common/                   # 通用组件
│   │       ├── data-table.tsx        # 通用数据表格
│   │       ├── search-filter.tsx     # 搜索筛选
│   │       ├── pagination.tsx        # 分页
│   │       └── loading-skeleton.tsx  # 加载骨架屏
│   │
│   ├── lib/                          # 工具库
│   │   ├── api/                      # API 客户端
│   │   │   ├── client.ts             # fetch 封装
│   │   │   ├── orders.ts             # 订单 API
│   │   │   ├── products.ts           # 产品 API
│   │   │   └── types.ts              # API 类型定义
│   │   ├── auth.ts                   # 认证工具
│   │   ├── utils.ts                  # 通用工具函数
│   │   └── validators.ts             # 数据验证（Zod）
│   │
│   ├── hooks/                        # 自定义 Hooks
│   │   ├── use-auth.ts               # 认证状态
│   │   ├── use-debounce.ts           # 防抖
│   │   ├── use-query-params.ts       # 查询参数
│   │   └── use-websocket.ts          # WebSocket 通知
│   │
│   ├── stores/                       # 全局状态（Zustand）
│   │   ├── auth-store.ts             # 认证状态
│   │   ├── ui-store.ts               # UI 状态（侧边栏、主题）
│   │   └── notification-store.ts     # 通知状态
│   │
│   ├── providers/                    # Context Providers
│   │   ├── auth-provider.tsx         # 认证 Provider
│   │   ├── theme-provider.tsx        # 主题 Provider
│   │   └── query-provider.tsx        # React Query Provider
│   │
│   └── styles/                       # 样式
│       ├── globals.css               # 全局样式（Tailwind）
│       └── variables.css             # CSS 变量（主题色）
│
├── public/                           # 静态资源
│   ├── images/
│   └── fonts/
│
├── next.config.ts                    # Next.js 配置
├── tailwind.config.ts                # Tailwind CSS 配置
├── tsconfig.json                     # TypeScript 配置
├── package.json
└── middleware.ts                     # Next.js 中间件（认证守卫）
```

### 5.2 状态管理方案

#### 5.2.1 技术选型

| 状态类型 | 方案 | 理由 |
|---------|------|------|
| 服务端状态 | **TanStack Query 5** | 缓存、重试、乐观更新 |
| 全局 UI 状态 | **Zustand 5** | 轻量、无样板代码 |
| 表单状态 | **React Hook Form 7** | 性能优、验证集成 |
| 表单验证 | **Zod 3** | 类型安全、与 RHF 集成 |

#### 5.2.2 状态管理实现

**Zustand - UI 状态**:

```typescript
// stores/ui-store.ts
import { create } from 'zustand'
import { persist } from 'zustand/middleware'

interface UiState {
  sidebarOpen: boolean
  theme: 'light' | 'dark' | 'system'
  setSidebarOpen: (open: boolean) => void
  setTheme: (theme: 'light' | 'dark' | 'system') => void
  toggleSidebar: () => void
}

export const useUiStore = create<UiState>()(
  persist(
    (set) => ({
      sidebarOpen: true,
      theme: 'system',
      setSidebarOpen: (open) => set({ sidebarOpen: open }),
      setTheme: (theme) => set({ theme }),
      toggleSidebar: () => set((state) => ({ sidebarOpen: !state.sidebarOpen })),
    }),
    { name: 'ui-storage' }
  )
)
```

**TanStack Query - 服务端状态**:

```typescript
// lib/api/orders.ts
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { apiClient } from './client'
import type { Order, OrderListParams, OrderCreateData } from './types'

export const orderKeys = {
  all: ['orders'] as const,
  lists: () => [...orderKeys.all, 'list'] as const,
  list: (params: OrderListParams) => [...orderKeys.lists(), params] as const,
  details: () => [...orderKeys.all, 'detail'] as const,
  detail: (id: number) => [...orderKeys.details(), id] as const,
}

export function useOrders(params: OrderListParams) {
  return useQuery({
    queryKey: orderKeys.list(params),
    queryFn: () => apiClient.getOrders(params),
    staleTime: 30_000, // 30s 内不重新请求
  })
}

export function useOrder(id: number) {
  return useQuery({
    queryKey: orderKeys.detail(id),
    queryFn: () => apiClient.getOrder(id),
    staleTime: 10_000,
  })
}

export function useCreateOrder() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (data: OrderCreateData) => apiClient.createOrder(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: orderKeys.lists() })
    },
  })
}
```

**认证状态**:

```typescript
// stores/auth-store.ts
import { create } from 'zustand'
import type { User } from '@/lib/api/types'

interface AuthState {
  user: User | null
  isAuthenticated: boolean
  isLoading: boolean
  setUser: (user: User | null) => void
  logout: () => void
}

export const useAuthStore = create<AuthState>()((set) => ({
  user: null,
  isAuthenticated: false,
  isLoading: true,
  setUser: (user) => set({ user, isAuthenticated: !!user, isLoading: false }),
  logout: () => set({ user: null, isAuthenticated: false, isLoading: false }),
}))
```

### 5.3 路由配置

#### 5.3.1 App Router 路由结构

Next.js 15 使用文件系统路由，无需额外配置：

```
/app                    → /
/app/login              → /login
/app/orders             → /orders
/app/orders/[id]        → /orders/:id
/app/orders/new         → /orders/new
/app/products           → /products
/app/products/[id]      → /products/:id
/app/stock/ins          → /stock/ins
/app/stock/outs         → /stock/outs
/app/approval           → /approval
/app/approval/[id]      → /approval/:id
/app/finance            → /finance
/app/settings           → /settings
```

#### 5.3.2 路由守卫（中间件）

```typescript
// middleware.ts
import { NextResponse } from 'next/server'
import type { NextRequest } from 'next/server'

const protectedPaths = [
  '/orders',
  '/products',
  '/stock',
  '/approval',
  '/finance',
  '/settings',
]

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl
  const token = request.cookies.get('access_token')?.value

  const isProtected = protectedPaths.some(
    (path) => pathname === path || pathname.startsWith(`${path}/`)
  )

  if (isProtected && !token) {
    const loginUrl = new URL('/login', request.url)
    loginUrl.searchParams.set('callbackUrl', pathname)
    return NextResponse.redirect(loginUrl)
  }

  if (pathname === '/login' && token) {
    return NextResponse.redirect(new URL('/', request.url))
  }

  return NextResponse.next()
}

export const config = {
  matcher: ['/((?!api|_next/static|_next/image|favicon.ico).*)'],
}
```

### 5.4 React 19 与 Next.js 15 整合要点

#### 5.4.1 React 19 特性利用

| 特性 | 应用场景 | 收益 |
|------|---------|------|
| **Server Actions** | 表单提交（审批、订单创建） | 无需 API 路由，直接服务端函数调用 |
| **use() Hook** | 数据获取、Context 消费 | 简化 Suspense 集成 |
| **useOptimistic** | 乐观更新（审批状态切换） | 即时 UI 反馈，无感知延迟 |
| **useFormStatus** | 表单提交状态 | 替代手动管理 loading 状态 |
| **useActionState** | 服务端表单验证 | 简化错误处理流程 |
| **Document Metadata** | 动态 SEO 标题/描述 | 替代 next/head，更简洁 |

**Server Actions 示例**:

```typescript
// app/orders/actions.ts
'use server'

import { revalidatePath } from 'next/cache'
import { redirect } from 'next/navigation'
import { apiClient } from '@/lib/api/client'
import type { OrderCreateData } from '@/lib/api/types'

export async function createOrder(prevState: any, formData: FormData) {
  const data: OrderCreateData = {
    customer_id: Number(formData.get('customer_id')),
    product_id: Number(formData.get('product_id')),
    quantity: Number(formData.get('quantity')),
    remarks: formData.get('remarks') as string,
  }

  try {
    await apiClient.createOrder(data)
    revalidatePath('/orders')
    redirect('/orders')
  } catch (error) {
    return { error: '订单创建失败，请重试' }
  }
}
```

**useActionState 集成**:

```typescript
// app/orders/new/page.tsx
import { useActionState } from 'react'
import { createOrder } from './actions'

export default function NewOrderPage() {
  const [state, formAction, isPending] = useActionState(createOrder, null)

  return (
    <form action={formAction}>
      {/* 表单字段 */}
      <button type="submit" disabled={isPending}>
        {isPending ? '提交中...' : '创建订单'}
      </button>
      {state?.error && <p className="text-red-500">{state.error}</p>}
    </form>
  )
}
```

#### 5.4.2 Next.js 15 特性利用

| 特性 | 应用场景 | 收益 |
|------|---------|------|
| **App Router** | 全局路由架构 | 嵌套布局、并行路由 |
| **Partial Prerendering** | 仪表盘（静态框架 + 动态数据） | 首屏瞬时加载 |
| **Turbopack** | 开发模式 HMR | 编译速度 ↑ 700% |
| **Server Components** | 数据获取页面 | 零客户端 JS |
| **After API** | 异步后台操作 | 无需等待响应即可返回 |

**Partial Prerendering 示例**:

```typescript
// app/dashboard/page.tsx
import { Suspense } from 'react'
import { DashboardSkeleton } from '@/components/common/loading-skeleton'
import { OrderStats } from '@/components/dashboard/order-stats'
import { StockAlerts } from '@/components/dashboard/stock-alerts'

export default function DashboardPage() {
  return (
    <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
      {/* 静态部分立即渲染 */}
      <div className="md:col-span-2">
        <h1>仪表盘</h1>
      </div>

      {/* 动态部分流式加载 */}
      <Suspense fallback={<DashboardSkeleton />}>
        <OrderStats />
      </Suspense>
      <Suspense fallback={<DashboardSkeleton />}>
        <StockAlerts />
      </Suspense>
    </div>
  )
}
```

### 5.5 FastAPI 后端适配

前端迁移到 Next.js 后，FastAPI 需调整：

#### 5.5.1 CORS 配置更新

```python
# fastapi_app/main.py
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",      # Next.js 开发服务器
        "https://erp.example.com",    # 生产域名
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
    allow_headers=["Authorization", "Content-Type", "X-CSRFToken", "X-Requested-With"],
)
```

#### 5.5.2 Cookie SameSite 跨域认证配置

**问题**: Next.js（端口 3000 或独立域名）与 FastAPI（端口 5002）跨域时，Cookie 的 `SameSite` 策略可能导致认证失败。

**解决方案**:

```python
# fastapi_app/core/auth.py - Cookie 配置
from fastapi import Response
import os

ENV = os.getenv("ENV", "development")

# Cookie 安全配置
cookie_config = {
    "key": "access_token",
    "httponly": True,
    "secure": ENV == "production",  # 生产环境必须 HTTPS
    "samesite": "none" if ENV == "production" else "lax",  # 跨域需要 'none'
    "max_age": 3600 * 24,  # 24 小时
}

def set_auth_cookie(response: Response, token: str):
    """设置认证 Cookie（支持跨域）"""
    response.set_cookie(
        value=token,
        **cookie_config
    )

# 注意: samesite='none' 必须配合 secure=True（HTTPS）
# 开发环境使用 samesite='lax'，生产环境使用 samesite='none' + HTTPS
```

**Nginx 反向代理配置（统一域名方案，推荐）**:

```nginx
# 统一域名方案：避免跨域问题
server {
    listen 443 ssl;
    server_name erp.example.com;

    # Next.js 前端
    location / {
        proxy_pass http://nextjs:3000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    # FastAPI API
    location /api/ {
        proxy_pass http://fastapi:5002;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

**统一域名方案优势**:
- 无跨域问题：前端和 API 同域名，Cookie 自然传递
- 更安全：无需 `SameSite=None`，可使用 `SameSite=Lax`
- 更简单：无需 CORS 预检请求

#### 5.5.3 Flask 遗留组件处理计划

**现状**: 当前系统通过 `run.py` 同时启动 Flask（端口 5003）和 FastAPI（端口 5002），Flask 作为遗留组件保留。

**处理方案**:

```
阶段一（并行运行）: 
  - Flask 继续运行（端口 5003），处理遗留页面
  - FastAPI（端口 5002）处理 API 请求
  - Nginx 路由分流：/api/ → FastAPI，其他 → Flask

阶段三（前端重写完成后）:
  - Next.js 接管所有前端页面
  - Flask 页面路由逐步下线
  - 最终移除 Flask 进程，仅保留 FastAPI
```

**Flask 下线检查清单**:

- [ ] 确认所有 Jinja2 模板页面已在 Next.js 中实现
- [ ] 确认所有 Flask Blueprint 路由已有 FastAPI 等价实现
- [ ] 确认 Flask 专属中间件已迁移到 FastAPI
- [ ] 确认 Flask 会话（session）已迁移到 JWT/Cookie
- [ ] 更新 `run.py`，移除 Flask 进程启动逻辑
- [ ] 更新 docker-compose，移除 Flask 端口映射
- [ ] 更新 Nginx 配置，移除 Flask 反向代理
- [ ] 清理 `app/` 目录（Flask 代码）或标记为 deprecated

**风险提示**:
- Flask 下线必须在 Next.js 前端完全上线后进行
- 下线前需进行全量回归测试
- 建议保留 Flask 代码 1-2 个版本周期，以便紧急回滚

#### 5.5.4 模板渲染移除（可选）

如果前端完全迁移到 Next.js，可移除 FastAPI 中的 Jinja2 页面路由：

```python
# 移除这些行（fastapi_app/main.py）
# from fastapi_app.api.v1.endpoints.pages import router as pages_router
# app.include_router(pages_router, tags=["页面"])
```

### 5.6 渐进式迁移策略（可选）

如 16 周时间线仍无法满足业务需求，可采用**渐进式迁移**策略：

**策略：模块级灰度迁移**

```
第1阶段（并行运行）: Next.js 独立部署，通过 Nginx 路由按模块分流
  - /orders/*  → Next.js（新）
  - /products/* → Jinja2（旧）
  - 其他路径   → Jinja2（旧）

第2阶段（逐个切换）: 每 2 周切换一个模块
  - 第1-2周: 订单模块（风险最低，业务最熟悉）
  - 第3-4周: 产品模块
  - 第5-6周: 库存模块
  - 第7-8周: 审批模块
  - 第9-10周: 财务模块
  - 第11-12周: 仪表盘 + 设置

第3阶段（完全切换）: 所有模块迁移完成，下线 Jinja2
```

**优势**:
- 风险分散：单个模块问题不影响全局
- 业务连续：可随时回退到旧页面
- 用户反馈：早期模块的用户反馈可指导后续开发

**劣势**:
- 维护成本：新旧系统并行运行期间维护工作量 ×2
- 用户体验：页面间跳转可能有风格不一致
- 数据状态：跨模块状态共享需额外处理

### 5.7 迁移风险评估

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|---------|
| React 学习曲线 | 中 | 中 | 分阶段培训 + 代码审查 + 预留 1 周学习期 |
| 状态管理复杂度 | 中 | 中 | 严格分层（Zustand 管 UI，Query 管服务端） |
| SSR 性能不如预期 | 低 | 高 | 性能基准预测试，必要时降级 CSR |
| 与 FastAPI 集成问题 | 低 | 中 | CORS 配置 + 认证 Cookie 跨域传递 |
| SEO 影响 | 低 | 中 | SSR 保证 SEO，SSG 页面预渲染 |
| 旧页面迁移遗漏 | 低 | 中 | 迁移清单 + 逐项验收 |
| 跨浏览器兼容性 | 中 | 中 | 预留 1 周专门处理兼容性 |
| 移动端适配 | 中 | 低 | Tailwind 响应式 + 移动端测试 |

---

## 6. 资源需求

### 6.1 人力资源

| 角色 | 人数 | 职责 | 投入时间 |
|------|------|------|---------|
| 后端工程师 | 2 | 依赖升级、容器化、数据库迁移、高可用 | 全程参与 |
| 前端工程师 | 2 | Vite 过渡、React/Next.js 完全重写 | 阶段三全程 |
| DevOps 工程师 | 1 | docker-compose、PgBouncer、监控、Loki | 阶段一、二 |
| DBA | 1 (兼职) | PostgreSQL 迁移、性能调优 | 阶段二 |
| 测试工程师 | 1 | 回归测试、性能基准、数据校验 | 各阶段完成后 |
| 项目负责人 | 1 | 方案审批、进度管控、风险评估 | 全程参与 |

### 6.2 硬件资源（全阶段完成）

| 资源 | 整改前 | 整改后（含 PG + Next.js） | 增量 |
|------|--------|-------------------------|------|
| CPU 核心 | 4 核 | 16 核（3 实例 + PG + Next.js + 监控） | +12 核 |
| 内存 | 8GB | 32GB | +24GB |
| 存储 | 50GB | 150GB（日志 + PG WAL + 构建缓存） | +100GB |
| 网络带宽 | 100Mbps | 1Gbps | 建议升级 |

### 6.3 软件资源

| 软件 | 版本 | 许可证 | 费用 |
|------|------|--------|------|
| Python | 3.13.7 | PSF | 免费 |
| PostgreSQL | 17 | PostgreSQL License | 免费 |
| Redis | 7.4 | BSD | 免费 |
| Next.js | 15.3 | MIT | 免费 |
| React | 19.0 | MIT | 免费 |
| PgBouncer | 1.23.0 | BSD | 免费 |
| Grafana | 11.5.0 | AGPL | 免费 |
| Prometheus | 2.55.0 | Apache 2.0 | 免费 |
| Loki | 3.4.0 | AGPL | 免费 |
| Nginx | 1.27-alpine | BSD | 免费 |

**总软件成本**: 0 元（全开源方案）

### 6.4 时间资源

| 阶段 | 周期 | 周数 | 内容 |
|------|------|------|------|
| 阶段一 | 第 1-8 周 | 8 周 | 基础整改（容器化、依赖、Vite 过渡、高可用、可观测性、安全） |
| 阶段二 | 第 9-12 周 | 4 周 | PostgreSQL 迁移 |
| 阶段三 | 第 13-28 周 | 16 周 | 前端 React/Next.js 完全重写 |
| **总计** | | **28 周** | 约 140 个工作日 |

---

## 7. 时间节点与里程碑

### 7.1 总体时间线

```
第1周    第4周    第8周    第12周   第16周   第20周   第24周   第28周
├────────┼────────┼────────┼────────┼────────┼────────┼────────┤
│ 阶段一 │ 阶段二  │ 阶段三（前端重写 - 16周）                      │ 集成  │
│ 基础整改│ PG迁移 │                                                │ 验收  │
├────────┴────────┴────────┴────────┴────────┴────────┴────────┤
│  M1-M7    │  M8-M10  │  M11-M12 │  M13-M15 │  M16   │  M17   │
```

### 7.2 里程碑定义

| 里程碑 | 时间 | 阶段 | 交付物 | 验收标准 |
|--------|------|------|--------|---------|
| **M1** | 第1周末 | 一 | Dockerfile v1.0 | 镜像构建成功，≤350MB |
| **M2** | 第2周末 | 一 | aiomysql 替换 | 全量测试通过 |
| **M3** | 第3周末 | 一 | Vite 构建上线 | 首屏 ≤1.5s |
| **M4** | 第4周末 | 一 | Taskiq 替代 Celery | 后台任务正常 |
| **M5** | 第5周末 | 一 | 3 实例部署 | 吞吐量 ≥1500 RPS |
| **M6** | 第6周末 | 一 | Loki 日志聚合 | 跨实例可搜索 |
| **M7** | 第7周末 | 一 | Argon2id 迁移 | 存量用户无感知 |
| **M8** | 第8周末 | 一 | 阶段一验收 | 所有指标达标 |
| **M9** | 第10周末 | 二 | PG 模式迁移完成 | 表结构 100% 一致 |
| **M10** | 第11周末 | 二 | PG 数据迁移完成 | 行数 100% 匹配 |
| **M11** | 第12周末 | 二 | 阶段二验收 | 性能不劣于 MySQL |
| **M12** | 第16周末 | 三 | Next.js 核心页面完成 | 仪表盘、订单、审批可用 |
| **M13** | 第20周末 | 三 | 全部页面迁移完成 | 所有页面功能等价 |
| **M14** | 第24周末 | 三 | 性能优化完成 | Lighthouse ≥90, 首屏 ≤0.5s |
| **M15** | 第26周末 | 三 | 全量测试完成 | 测试报告，Bug 修复率 ≥95% |
| **M16** | 第27周末 | 三 | 生产部署完成 | 部署文档，灰度发布 |
| **M17** | 第28周末 | 三 | 全量最终验收 | 综合评分 ≥9.5 |

### 7.3 阶段三（前端重写）详细计划

| 周 | 任务 | 交付物 |
|----|------|--------|
| 第13周 | 项目初始化 + 技术选型验证 + 团队培训 | Next.js 项目脚手架 |
| 第14周 | 布局组件 + 认证系统 + 主题系统 | Sidebar、Header、登录、Dark Mode |
| 第15周 | 仪表盘模块（SSR + 流式渲染） | 仪表盘、数据可视化 |
| 第16周 | 订单模块（列表/详情/创建/编辑） | 订单完整 CRUD |
| 第17周 | 产品模块 + 库存入库管理 | 产品管理、入库流程 |
| 第18周 | 库存出库 + 审批流模块 | 出库管理、审批工作流 |
| 第19周 | 财务模块 + 系统设置 | 财务报表、设置页面 |
| 第20周 | 通知模块 + 全局功能（搜索/筛选/分页/导出） | 实时通知、全局交互 |
| 第21周 | 文件上传/下载 + 数据导出（Excel/PDF） | 文件处理功能 |
| 第22周 | 跨浏览器兼容性 + 移动端适配 | 兼容性测试报告 |
| 第23周 | 性能优化（代码分割、图片优化、缓存策略） | Lighthouse ≥90 |
| 第24周 | 安全审计 + 无障碍访问优化 | 安全扫描通过 |
| 第25周 | 全量功能测试 + Bug 修复 | 测试报告 |
| 第26周 | 集成测试 + 用户验收测试（UAT） | UAT 报告 |
| 第27周 | 生产环境部署 + 灰度发布 | 部署文档、监控配置 |
| 第28周 | 最终验收 + 文档归档 | 验收报告、运维手册 |

---

## 8. 责任人矩阵

### 8.1 RACI 矩阵（全阶段）

| 任务 | 后端 | 前端 | DevOps | DBA | 测试 | 负责人 |
|------|------|------|--------|-----|------|--------|
| Dockerfile 构建 | C | - | R | - | I | A |
| docker-compose 编排 | C | - | R | C | I | A |
| asyncmy → pymysql | R | - | C | - | C | A |
| Celery → Taskiq | R | - | C | - | C | A |
| Vite 构建引入 | C | R | C | - | C | A |
| MySQL → PG 模式 | C | - | C | R | - | A |
| MySQL → PG 数据 | C | - | C | R | C | A |
| PgBouncer 配置 | C | - | R | C | - | A |
| React 架构设计 | C | R | - | - | I | A |
| Next.js 页面开发 | I | R | - | - | C | A |
| 状态管理实现 | I | R | - | - | C | A |
| Server Actions | R | R | - | - | C | A |
| 3 实例部署 | C | - | R | - | C | A |
| Loki 日志聚合 | C | - | R | - | I | A |
| Argon2id 迁移 | R | - | I | - | C | A |
| 性能基准测试 | C | C | C | C | R | A |
| 安全审计 | C | C | R | - | C | A |
| 最终验收 | C | C | C | C | C | R+A |

---

## 9. 整改前后量化对比

### 9.1 性能指标对比（全阶段完成）

| 指标 | 整改前 | 阶段一完成 | + PG 迁移 | + Next.js | **最终目标** |
|------|--------|-----------|-----------|-----------|------------|
| API P95 响应时间 | 120ms | ≤60ms | **≤30ms** | ≤30ms | **≤25ms** |
| API P99 响应时间 | 350ms | ≤150ms | **≤80ms** | ≤80ms | **≤60ms** |
| 数据库查询延迟 | 45ms | ≤25ms | **≤15ms** | ≤15ms | **≤10ms** |
| 复杂 JOIN 查询 | 80ms | 80ms | **≤30ms** | ≤30ms | **≤20ms** |
| JSON 查询性能 | 基准 | 基准 | **快 5x** | 快 5x | **快 5x** |
| JSON 序列化延迟 | 8ms | ≤3ms | ≤3ms | ≤3ms | **≤2ms** |
| 前端首屏加载 | 2.8s | ≤1.2s | ≤1.2s | **≤0.5s** | **≤0.4s** |
| 前端资源总大小 | 1.2MB | ≤400KB | ≤400KB | **≤150KB** | **≤120KB** |
| 页面交互响应 | 200ms | 150ms | 150ms | **≤50ms** | **≤30ms** |
| 系统吞吐量 | 500 RPS | 1500 RPS | **2000 RPS** | 2000 RPS | **≥3000 RPS** |
| 任务队列延迟 | 180ms | ≤60ms | ≤60ms | ≤60ms | **≤50ms** |
| 启动时间 | 3.5s | ≤2.0s | ≤2.0s | ≤2.0s | **≤1.5s** |
| WebSocket 并发 | 200 | ≥500 | ≥500 | ≥500 | **≥800** |

### 9.2 架构指标对比

| 指标 | 整改前 | 阶段一 | + PG | + Next.js | **最终** |
|------|--------|--------|------|-----------|---------|
| 容器化程度 | 2/10 | 10/10 | 10/10 | 10/10 | **10/10** |
| 水平扩展能力 | 1/10 | 9/10 | 9/10 | 9/10 | **9/10** |
| 数据库性能 | 5/10 | 5/10 | **9/10** | 9/10 | **9/10** |
| 前端可维护性 | 1/10 | 5/10 | 5/10 | **9/10** | **9.5/10** |
| 前端性能 | 1/10 | 5/10 | 5/10 | **9/10** | **9.5/10** |
| 故障自愈 | 2/10 | 8/10 | 8/10 | 8/10 | **8/10** |

### 9.3 综合评分对比

| 维度 | 整改前 | 阶段一 | + PG | + Next.js | **最终** |
|------|--------|--------|------|-----------|---------|
| 性能 | 5.8/10 | 8.5/10 | 9.2/10 | 9.5/10 | **9.6/10** |
| 架构 | 2.2/10 | 9.2/10 | 9.5/10 | 9.5/10 | **9.5/10** |
| 可观测性 | 3.5/10 | 7.8/10 | 7.8/10 | 7.8/10 | **7.8/10** |
| 安全 | 6.3/10 | 8.7/10 | 8.7/10 | 8.7/10 | **8.7/10** |
| 运维效率 | 3.0/10 | 8.7/10 | 9.0/10 | 9.0/10 | **9.0/10** |
| **综合均分** | **4.2/10** | **8.6/10** | **9.0/10** | **9.3/10** | **9.5/10** |

**总体提升**: 4.2 → 9.5，提升 **126%**

### 9.4 ROI 分析（投资回报）

| 整改项 | 投入成本（人天） | 预期收益 | ROI（年化） | 回收周期 |
|--------|----------------|---------|------------|---------|
| 容器化部署 | 10 | 部署效率 ↑80%，环境一致性 100% | 300% | 2 个月 |
| 数据库迁移（PG） | 20 | 查询性能 ↑50%，维护成本 ↓30% | 250% | 3 个月 |
| 前端重写（Next.js） | 80 | 用户体验 ↑，开发效率 ↑60% | 180% | 6 个月 |
| 任务队列升级 | 5 | 延迟 ↓67%，资源占用 ↓25% | 400% | 1 个月 |
| 高可用架构 | 8 | 可用性 99.5%→99.99%，故障恢复 ↓90% | 500% | 1 个月 |
| 可观测性 | 5 | 故障定位时间 ↓83%，运维效率 ↑ | 350% | 1.5 个月 |
| 安全加固 | 3 | 合规达标，数据泄露风险 ↓95% | 无法量化（避免损失） | 即时 |
| **总计** | **131** | **综合评分 4.2→9.5** | **~220%** | **~4 个月** |

**成本构成**:
- 人力成本：131 人天 × 2000 元/人天 = 26.2 万元
- 硬件成本：+24GB 内存 +100GB 存储 ≈ 2 万元
- **总投入**：约 28.2 万元

**收益估算（年化）**:
- 运维效率提升：节省 2 人月/年 × 1.5 万 = 18 万/年
- 故障损失减少：减少停机 10 小时/年 × 5 万/小时 = 50 万/年
- 开发效率提升：新功能上线速度 ↑50%，竞争优势无法量化
- **总收益**：约 68 万/年（保守估计）

---

## 10. 验收标准

### 10.1 阶段一验收标准（基础整改）

- [ ] Dockerfile 构建成功，镜像 ≤350MB
- [ ] Trivy 安全扫描零高危漏洞
- [ ] docker-compose up -d 一键启动全栈服务
- [ ] aiomysql 替代 asyncmy 完成，全量测试通过率 100%
- [ ] Vite 构建管道正常输出，首屏资源 ≤400KB
- [ ] Taskiq 替代 Celery 完成，任务延迟 ≤60ms
- [ ] 3 实例负载均衡正常，吞吐量 ≥1500 RPS
- [ ] Loki 日志跨实例可搜索
- [ ] Argon2id 新用户注册正常，旧用户无感知迁移
- [ ] API P95 ≤60ms，P99 ≤150ms

### 10.2 阶段二验收标准（PostgreSQL 迁移）

- [ ] PostgreSQL 17 部署完成，健康检查通过
- [ ] 所有表结构 100% 迁移（表数、列数、类型一致）
- [ ] 所有索引迁移完成（索引数一致）
- [ ] 所有约束迁移完成（主键、外键、唯一、CHECK）
- [ ] 数据行数 100% 匹配（逐表 COUNT 验证）
- [ ] 数据校验和验证通过（随机抽样 1000 条/表）
- [ ] 复杂查询性能 ≥ MySQL（不劣于原性能）
- [ ] 所有 API 端点功能正常（回归测试通过率 ≥99%）
- [ ] PgBouncer 连接池正常（transaction 模式，max_client_conn=500）
- [ ] 最终切换窗口 ≤15 分钟

### 10.3 阶段三验收标准（前端 React/Next.js 重写）

- [ ] Next.js 15 项目正常启动（开发模式 HMR <50ms）
- [ ] 所有页面渲染正常（无 SSR 错误）
- [ ] 认证系统正常（登录、登出、Cookie 传递）
- [ ] 路由守卫正常（未登录自动跳转）
- [ ] 仪表盘 SSR + 流式渲染正常
- [ ] 订单模块 CRUD 功能完整
- [ ] 产品、库存、审批、财务模块功能完整
- [ ] 实时通知 WebSocket 正常
- [ ] 首屏加载 ≤0.5s（生产构建）
- [ ] 首屏资源 ≤150KB（gzip 压缩后）
- [ ] Lighthouse 性能评分 ≥90
- [ ] Lighthouse 可访问性评分 ≥90
- [ ] Lighthouse SEO 评分 ≥90
- [ ] 浏览器兼容性：Chrome 120+、Firefox 120+、Safari 17+、Edge 120+

### 10.4 最终验收标准

**全量回归测试通过率**: ≥99%

**性能达标率**: ≥95%（9.1 节中 13 项性能指标至少 12 项达标）

**安全扫描通过率**: Trivy 零高危、pip-audit 零高危、npm audit 零高危

**零回退**: 整改后任意指标不得劣于整改前

**综合评分**: ≥9.5/10

---

## 11. 风险管理与回滚方案

### 11.1 全阶段风险矩阵

| 风险 | 阶段 | 概率 | 影响 | 缓解措施 | 应急方案 |
|------|------|------|------|---------|---------|
| aiomysql 性能不达标 | 一 | 低 | 高 | 性能基准预测试 | 回退至 asyncmy |
| Taskiq 兼容性 | 一 | 中 | 中 | 逐步迁移 | 保留 Celery |
| PG 数据丢失 | 二 | 低 | 极高 | 三层备份 | 从备份恢复 MySQL |
| PG 类型转换错误 | 二 | 中 | 高 | 逐表验证 | 修复后重迁移 |
| PG 性能退化 | 二 | 低 | 高 | 迁移后基准测试 | 优化查询/索引 |
| React 学习曲线 | 三 | 中 | 中 | 分阶段培训 | 延长周期 |
| SSR 性能不及预期 | 三 | 低 | 高 | 预测试 | 降级 CSR |
| 前端与 FastAPI 集成 | 三 | 低 | 中 | CORS + Cookie 配置 | BFF 代理层 |
| 容器内存超限 | 全 | 低 | 中 | 资源限制 + 告警 | 调整限制 |
| 数据库连接耗尽 | 全 | 低 | 高 | 连接池 + 监控 | 调整 pool_size |
| Loki 磁盘占满 | 全 | 中 | 中 | 日志保留策略 | 清理 + 扩容 |

### 11.2 回滚方案

#### PostgreSQL 迁移回滚

| 步骤 | 操作 | 时间 |
|------|------|------|
| 1 | 停止 FastAPI 应用 | 1min |
| 2 | 切换 DATABASE_URL 回 MySQL | 1min |
| 3 | 重启 FastAPI 连接 MySQL | 2min |
| 4 | 验证功能正常 | 5min |
| 5 | 恢复 MySQL 增量数据（如有双写期间新数据） | 10min |
| **总计** | | **≤20min** |

#### 前端重写回滚

| 步骤 | 操作 | 时间 |
|------|------|------|
| 1 | Nginx 路由切回 Jinja2 模板 | 2min |
| 2 | 停止 Next.js 服务 | 1min |
| 3 | 验证旧前端功能正常 | 5min |
| **总计** | | **≤10min** |

### 11.3 监控与告警（全阶段）

| 告警 | 条件 | 响应 |
|------|------|------|
| API 错误率 > 1% | 5 分钟内 HTTP 5xx > 1% | 立即暂停变更 |
| P95 延迟 > 200ms | 5 分钟内 P95 > 200ms | 调查原因，必要时回滚 |
| DB 连接数 > 80% | 连接数 > max × 0.8 | 调整连接池配置 |
| 内存使用 > 90% | 容器内存 > 限制 × 0.9 | 增加限制或排查泄漏 |
| 磁盘使用 > 85% | 磁盘空间 < 15% | 清理日志 + 扩容 |
| PG 复制延迟 > 5s | wal_sender 延迟 | 检查网络/IO |
| Next.js SSR 错误率 > 5% | 5 分钟内 SSR 失败 > 5% | 检查数据接口 |

---

## 12. 技术文档参考

### 12.1 后端与数据库

| 技术 | 文档链接 | 用途 |
|------|---------|------|
| FastAPI | https://fastapi.tiangolo.com/ | Web 框架官方文档 |
| SQLAlchemy 2.0 | https://docs.sqlalchemy.org/en/20/ | ORM 框架文档 |
| asyncpg | https://magicstack.github.io/asyncpg/current/ | PostgreSQL 异步驱动 |
| Alembic | https://alembic.sqlalchemy.org/ | 数据库迁移工具 |
| PostgreSQL 17 | https://www.postgresql.org/docs/17/ | 数据库官方文档 |
| PgBouncer | https://www.pgbouncer.org/ | 连接池中间件 |
| pgloader | https://pgloader.io/ | MySQL → PG 迁移工具 |
| Taskiq | https://taskiq-python.github.io/ | 异步任务队列 |
| msgspec | https://jcristharif.com/msgspec/ | 高性能序列化库 |

### 12.2 前端

| 技术 | 文档链接 | 用途 |
|------|---------|------|
| Next.js 15 | https://nextjs.org/docs | React 框架官方文档 |
| React 19 | https://react.dev/ | React 官方文档 |
| React Server Components | https://nextjs.org/docs/app/building-your-application/rendering/server-components | 服务端组件指南 |
| TanStack Query | https://tanstack.com/query/latest | 服务端状态管理 |
| Zustand | https://zustand.docs.pmnd.rs/ | 轻量状态管理 |
| React Hook Form | https://react-hook-form.com/ | 表单管理 |
| Zod | https://zod.dev/ | TypeScript 数据验证 |
| Tailwind CSS | https://tailwindcss.com/docs | 实用优先 CSS |
| shadcn/ui | https://ui.shadcn.com/ | 可访问性优先组件库 |
| Turbopack | https://turbo.build/pack | Next.js 构建引擎 |

### 12.3 DevOps 与运维

| 技术 | 文档链接 | 用途 |
|------|---------|------|
| Docker | https://docs.docker.com/ | 容器化官方文档 |
| Docker Compose | https://docs.docker.com/compose/ | 容器编排 |
| Nginx | https://nginx.org/en/docs/ | 反向代理配置 |
| Prometheus | https://prometheus.io/docs/ | 指标采集 |
| Grafana | https://grafana.com/docs/ | 可视化仪表盘 |
| Loki | https://grafana.com/docs/loki/latest/ | 日志聚合 |
| Trivy | https://trivy.dev/latest/ | 容器安全扫描 |
| Argon2 | https://github.com/P-H-C/phc-winner-argon2 | 密码哈希算法 |

---

## 附录 A：术语表

| 术语 | 解释 |
|------|------|
| P0/P1/P2 | 优先级等级：P0 紧急、P1 高、P2 中 |
| RPS | Requests Per Second（每秒请求数） |
| P95/P99 | 第 95/99 百分位响应时间 |
| HMR | Hot Module Replacement（热模块替换） |
| Tree Shaking | 未使用代码裁剪 |
| SSR | Server-Side Rendering（服务端渲染） |
| SSG | Static Site Generation（静态站点生成） |
| CSR | Client-Side Rendering（客户端渲染） |
| ISR | Incremental Static Regeneration（增量静态再生） |
| RSC | React Server Components（React 服务端组件） |
| BFF | Backend For Frontend（前端专属后端） |
| RACI | Responsible, Accountable, Consulted, Informed |
| WAL | Write-Ahead Logging（预写式日志） |
| JSONB | PostgreSQL 二进制 JSON 类型 |
| Trivy | 容器安全扫描工具 |
| Argon2id | OWASP 推荐的密码哈希算法 |

---

## 附录 B：整改前后文件变更清单（全阶段）

| 文件 | 变更类型 | 阶段 | 说明 |
|------|---------|------|------|
| `requirements/base.txt` | 修改 | 一 | 替换 asyncmy→pymysql→asyncpg，移除 celery，添加 taskiq、msgspec、argon2-cffi |
| `Dockerfile` | 新增 | 一 | 多阶段构建文件 |
| `docker-compose.yml` | 新增 | 一 | 全栈服务编排（含 PG、PgBouncer） |
| `.dockerignore` | 新增 | 一 | Docker 构建排除文件 |
| `fastapi_app/core/config.py` | 修改 | 一→二 | 数据库 URL 从 mysql→postgresql |
| `fastapi_app/core/database.py` | 修改 | 二 | 异步引擎切换 asyncpg |
| `fastapi_app/core/logger.py` | 修改 | 一 | 添加 JSON 格式化 Handler |
| `config/nginx.conf` | 修改 | 一 | upstream 多 server + Next.js 反向代理 |
| `config/prometheus.yml` | 修改 | 一 | 更新目标地址 |
| `config/pgbouncer.ini` | 新增 | 二 | PgBouncer 连接池配置 |
| `config/loki-config.yaml` | 新增 | 一 | Loki 配置 |
| `alembic.ini` | 修改 | 二 | sqlalchemy.url 切换为 PostgreSQL |
| `frontend/package.json` | 新增 | 三 | Next.js + React 依赖 |
| `frontend/next.config.ts` | 新增 | 三 | Next.js 配置 |
| `frontend/tailwind.config.ts` | 新增 | 三 | Tailwind CSS 配置 |
| `frontend/tsconfig.json` | 新增 | 三 | TypeScript 配置 |
| `frontend/src/app/` | 新增 | 三 | Next.js App Router 页面 |
| `frontend/src/components/` | 新增 | 三 | React 组件库 |
| `frontend/src/lib/api/` | 新增 | 三 | API 客户端 + 类型定义 |
| `frontend/src/stores/` | 新增 | 三 | Zustand 状态管理 |
| `frontend/middleware.ts` | 新增 | 三 | Next.js 认证守卫 |
| `templates/` | 废弃 | 三 | Jinja2 模板（被 Next.js 替代） |
| `static/js/` | 废弃 | 三 | 原生 JS 文件（被 TypeScript 替代） |

---

## 附录 C：数据库迁移检查清单

### C.1 迁移前检查

- [ ] 全量逻辑备份完成（mysqldump）
- [ ] 物理备份完成（XtraBackup）
- [ ] 二进制日志位点已记录
- [ ] 备份恢复验证通过（测试环境）
- [ ] 模式差异分析完成
- [ ] 类型映射表已确认
- [ ] pgloader 配置已编写并测试
- [ ] ETL 脚本已编写并测试
- [ ] 回滚方案已演练

### C.2 迁移中检查

- [ ] PostgreSQL 17 部署完成
- [ ] Alembic 迁移在 PG 上执行成功
- [ ] 数据迁移完成（pgloader 或 ETL）
- [ ] 行数验证通过（100% 匹配）
- [ ] 索引验证通过
- [ ] 约束验证通过
- [ ] 序列（SEQUENCE）已同步
- [ ] 视图已重建

### C.3 迁移后检查

- [ ] 数据抽样校验通过（1000 条/表）
- [ ] API 回归测试通过率 ≥99%
- [ ] 性能基准测试通过（不劣于 MySQL）
- [ ] PgBouncer 连接池正常
- [ ] 双写过渡期间数据一致性验证
- [ ] MySQL 已设置为只读（过渡期）
- [ ] 最终切换完成，MySQL 下线

---

## 附录 D：前端迁移检查清单

### D.1 初始化检查

- [ ] Next.js 15 项目创建完成
- [ ] TypeScript 配置完成
- [ ] Tailwind CSS 配置完成
- [ ] shadcn/ui 初始化完成
- [ ] TanStack Query 配置完成
- [ ] Zustand 配置完成
- [ ] 认证系统（Cookie JWT）集成完成
- [ ] CORS 配置确认（FastAPI ↔ Next.js）

### D.2 页面迁移检查

- [ ] 登录页完成
- [ ] 仪表盘完成（SSR + 流式渲染）
- [ ] 订单列表/详情/创建完成
- [ ] 产品管理完成
- [ ] 库存管理（出入库）完成
- [ ] 审批流完成
- [ ] 财务管理完成
- [ ] 系统设置完成
- [ ] 实时通知（WebSocket）完成

### D.3 功能完整性检查

- [ ] 搜索与筛选功能正常
- [ ] 分页功能正常
- [ ] 表单验证正常（Zod + RHF）
- [ ] 文件上传/下载正常
- [ ] 数据导出（Excel）正常
- [ ] 侧边栏导航正常
- [ ] 用户信息展示正常
- [ ] 退出登录正常

### D.4 性能检查

- [ ] Lighthouse 性能 ≥90
- [ ] Lighthouse 可访问性 ≥90
- [ ] Lighthouse SEO ≥90
- [ ] 首屏加载 ≤0.5s
- [ ] 首屏资源 ≤150KB（gzip）
- [ ] HMR <50ms
- [ ] 生产构建无警告

---

**文档编制人**: AI 技术顾问
**审核人**: 待定
**批准人**: 待定
**下次评审日期**: 待定
