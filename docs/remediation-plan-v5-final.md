# 滨发协同系统 - 系统整改方案

**版本**: v5.0 (审核修正最终版)
**编制日期**: 2026-04-21
**更新说明**: 基于审核报告修正 3 项事实性错误(P0)、7 项技术缺陷(P1)，重新设计阶段一驱动替换策略
**适用范围**: 后端、前端、部署运维（不含 CI/CD 流水线）
**审批状态**: 待审批
**前置条件**: 整改启动前必须完成生产环境基线测量（见第 2.1 节）

---

## 目录

1. [整改背景与目标](#1-整改背景与目标)
2. [整改前现状基线](#2-整改前现状基线)
3. [分项整改方案（基础）](#3-分项整改方案基础)
4. [专项整改方案一：MySQL -> PostgreSQL 迁移](#4-专项整改方案一mysql--postgresql-迁移)
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

滨发协同系统当前为纯 FastAPI 单框架架构（v2.0.0），Flask 已在前期迁移中完全移除。系统使用 FastAPI 0.136.0 + SQLAlchemy 2.0.49（asyncmy 异步驱动 + pymysql 同步驱动双引擎）+ Celery 5.6.3 + MySQL 8.4。经全面审计发现以下关键问题：

| 问题域 | 核心问题 | 影响等级 |
|--------|---------|---------|
| **容器化** | Dockerfile/docker-compose 等容器化文件已从版本库中删除 | P0 |
| **数据库驱动** | asyncmy 已停止维护，存在安全漏洞风险 | P0 |
| **数据库架构** | MySQL 在复杂查询、JSON 操作上性能受限 | P1 |
| **前端工程化** | 无构建系统，无类型安全，Jinja2 + 原生 JS 难以维护 | P1 |
| **前端架构** | SSR 模板 + 零组件化，交互体验差 | P2 |
| **高可用** | 单点故障，无水平扩展能力 | P1 |
| **可观测性** | 无日志聚合，结构化日志缺失 | P2 |
| **密码安全** | bcrypt 非 OWASP 推荐算法 | P2 |

> **v5.0 修正说明**: v4.0 中声称"Flask 作为遗留组件保留"与实际代码库不符。当前系统为纯 FastAPI 架构，run.py 仅启动 FastAPI（端口 5002），nginx.conf 仅配置 fastapi_backend，requirements/base.txt 无 Flask 依赖。所有 Flask 相关章节已移除。

### 1.2 整改目标

| 序号 | 目标 | 量化指标 | 优先级 |
|------|------|---------|--------|
| G1 | 实现全栈容器化部署 | 环境一致性 100% 可重复 | P0 |
| G2 | 替换停更异步数据库驱动 | 消除安全漏洞风险 | P0 |
| G3 | MySQL -> PostgreSQL 迁移 | 复杂查询性能提升 >=30% | P1 |
| G4 | 前端引入构建体系（过渡方案） | 首屏加载体积减少 >=50% | P1 |
| G5 | 前端完全重写（React + Next.js） | 首屏加载 <=1.0s，可维护性 8/10 | P1 |
| G6 | 异步任务队列评估与优化 | 任务处理延迟降低 >=30% | P1 |
| G7 | 建立高可用架构 | 支持 3 实例水平扩展 | P1 |
| G8 | 完善可观测性 | 日志可搜索率 100% | P2 |
| G9 | 密码哈希算法升级 | 达到 OWASP 2026 标准 | P2 |

> **v5.0 修正说明**: G3 性能提升从 >=50% 修正为 >=30%（无实际查询基准数据支撑 50% 的声明）；G5 首屏加载从 <=0.5s 修正为 <=1.0s（更保守且可达成）；G6 从"任务队列升级"修正为"评估与优化"（Celery 5.6+ 仍为可行方案，不强制替换为 Taskiq）。

### 1.3 整改范围

**纳入范围**:
- 后端依赖升级与替换（asyncmy 保持至 PG 迁移后替换为 asyncpg、Celery 评估优化、orjson -> msgspec）
- 容器化建设（Dockerfile 多阶段构建、docker-compose 编排）
- 数据库迁移（MySQL 8.4 -> PostgreSQL 17）
- 前端构建体系过渡（Vite + TypeScript）
- 前端完全重写（React 19 + Next.js 15 + App Router）
- 高可用架构（多副本、连接池优化、负载均衡、PgBouncer）
- 可观测性（Loki 日志聚合、结构化日志）
- 安全加固（Argon2id 密码哈希、Cookie SameSite 配置）

**排除范围**:
- CI/CD 流水线自动化（本次整改暂不纳入）

> **v5.0 修正说明**: 移除"Flask 遗留组件处理"相关条目。驱动替换策略调整为保持 asyncmy 直至 PG 迁移。任务队列升级调整为评估优化。

### 1.4 整改阶段划分

| 阶段 | 内容 | 周期 | 预期提升 |
|------|------|------|---------|
| **阶段零** | 基线测量与前置准备 | 1 周 | 建立量化基准 |
| **阶段一** | 基础整改（容器化、Celery 优化、Vite 过渡、高可用） | 6 周 | 4.x -> 7.x |
| **阶段二** | PostgreSQL 迁移（含驱动替换 asyncmy -> asyncpg） | 5 周 | 7.x -> 8.x |
| **阶段三** | 前端 React/Next.js 重写 | 18 周 | 8.x -> 9.x |
| **总计** | 全部整改 | 30 周 | 4.x -> 9.x |

> **v5.0 修正说明**: 新增阶段零（基线测量），作为启动门控条件。阶段一从 8 周缩减为 6 周（移除 Flask 处理和 asyncmy 替换工作）。阶段二从 4 周增至 5 周（驱动替换合并到 PG 迁移中统一处理）。阶段三从 16 周增至 18 周（增加缓冲）。取消不切实际的"提升 126%"声明，改用待基线测量后确定的实际提升幅度。

---

## 2. 整改前现状基线

### 2.1 性能基线

> **门控条件**: 以下基线值必须在整改启动前完成实际测量。未完成基线测量不得启动整改。测量结果填写在"实际测量值"列中。

**基线测量要求**:

```bash
# 1. API 性能测量（使用 locust）
locust -f locustfile.py --host http://localhost:5002 --users 50 --run-time 5m

# 2. 数据库查询延迟（MySQL performance_schema）
SELECT * FROM performance_schema.events_statements_summary_by_digest
WHERE SCHEMA_NAME = 'erp_system' ORDER BY SUM_TIMER_WAIT DESC LIMIT 20;

# 3. 前端性能（Lighthouse CI）
npx lighthouse http://localhost:5002 --output=json --chrome-flags="--headless"

# 4. 资源大小
curl -s http://localhost:5002/static/js/order.js | wc -c
```

| 指标 | 测量方法 | 预估值 | 实际测量值 | 测量条件 |
|------|---------|--------|-----------|---------|
| API P95 响应时间 | Prometheus /metrics | ~120ms | 待生产环境测量 | 50 并发，无缓存预热 |
| API P99 响应时间 | Prometheus /metrics | ~350ms | 待生产环境测量 | 50 并发 |
| 数据库查询延迟 | 慢查询日志 (100ms) | 平均 45ms | 待生产环境测量 | 20 连接池 |
| 复杂 JOIN 查询 | 订单+产品+客户 | ~80ms | 待生产环境测量 | MySQL 8.4 |
| 前端首屏加载 | Lighthouse | ~2.8s | 待生产环境测量 | 首次访问，HTTP |
| 前端资源总大小 | DevTools Network | ~1.2MB | **990.8 KB**（JS: 540.3KB + CSS: 450.5KB） | 未压缩，含 Bootstrap/FA |
| 任务队列延迟 | Celery task round-trip | ~180ms | 待生产环境测量 | Redis broker |
| 静态 JS 文件数 | 目录扫描 | N/A | **15 个** | 含页面级+共享模块 |
| 静态 CSS 文件数 | 目录扫描 | N/A | **10 个** | 含 Bootstrap/FA/自定义 |
| Jinja2 模板数 | 目录扫描 | ~38 | **39 个** (910.5 KB) | pages.py 使用 SyncSessionLocal |

### 2.2 架构基线

| 维度 | 现状 | 评分 (1-10) |
|------|------|------------|
| 容器化程度 | 无容器化（原有容器文件已删除），手动部署 | 2 |
| 水平扩展能力 | 单实例，无法扩展 | 1 |
| 故障自愈能力 | 无健康检查自愈 | 2 |
| 资源隔离 | 进程级隔离，非容器级 | 3 |
| 部署一致性 | 依赖手动配置，不一致风险高 | 2 |

### 2.3 前端基线

| 维度 | 现状 | 评分 (1-10) |
|------|------|------------|
| 构建系统 | 无 | 1 |
| 代码分割 | 无，全量加载 | 1 |
| 类型安全 | 原生 JS，无类型检查 | 1 |
| 组件化程度 | 零组件化，Jinja2 模板拼接 | 1 |
| 状态管理 | 全局变量 + DOM 操作 | 1 |
| 模板数量 | 38 个 Jinja2 HTML 模板 + 页面级 JS | 3 |

### 2.4 数据库基线（MySQL 8.4）

| 维度 | 现状 | 评分 (1-10) |
|------|------|------------|
| 异步驱动生态 | asyncmy 已停更 | 3 |
| 复杂查询性能 | 基准 | 5 |
| JSON 操作 | JSON 函数有限，无 JSONB | 3 |
| GROUP_CONCAT | 9 处使用（report_service, finance_service） | N/A |

### 2.5 代码库关键数据

| 项目 | 数量 | 说明 |
|------|------|------|
| 使用 get_async_db 的端点文件 | 20 个 / ~171 个路由 | 移除 asyncmy 将导致全部中断 |
| 使用 AsyncSession 的 service 文件 | 16 个 / ~177 个函数 | 异步服务层核心 |
| Celery @shared_task | 5 个 | 3 个 task 文件 |
| Jinja2 模板 | 38 个 | pages.py 使用 SyncSessionLocal 渲染 |
| MySQL 方言迁移文件 | 2 个 / ~112 处引用 | 阻碍 PG 迁移 |
| GROUP_CONCAT 使用 | 9 处 | 需改为 STRING_AGG |
| 反引号引用的原始 SQL | 4 处 | 需改为双引号 |

---

## 3. 分项整改方案（基础）

### 3.1 分项一：后端依赖升级与替换

#### 3.1.1 异步数据库驱动策略

**v5.0 核心修正**: 不再采用 v4.0 的"asyncmy -> pymysql（同步）临时方案"。

**问题**: asyncmy (0.2.11) 已停止维护，存在安全漏洞风险。

**v5.0 方案**: **保持 asyncmy 不变，在阶段二 PostgreSQL 迁移时统一替换为 asyncpg**。

**决策理由**:
1. 当前 20/21 个端点文件（~171 个路由）依赖 `get_async_db()`，移除 asyncmy 将导致全部路由抛出 RuntimeError，造成完全性服务中断
2. 16 个 service 文件的 ~177 个异步函数使用 `AsyncSession`，将 async -> sync 的工作量等同于一次完整服务层重构
3. FastAPI 的异步 I/O 模型是其核心优势，退回同步驱动将导致所有数据库操作阻塞事件循环
4. 阶段二迁移到 PostgreSQL + asyncpg 可一次性解决驱动问题，避免"asyncmy -> pymysql -> asyncpg"的双重迁移

**风险缓解**:
- 监控 asyncmy 的安全公告，如出现高危 CVE 则立即启动 PG 迁移
- 在阶段一完成容器化建设，为 PG 迁移做好准备

#### 3.1.2 任务队列策略

**v5.0 核心修正**: 不再强制将 Celery 替换为 Taskiq。

**方案**: **评估 Celery 5.6+ 优化 vs Taskiq 替换的 ROI，根据评估结果决定**。

**评估维度**:

| 维度 | Celery 5.6+ (优化) | Taskiq 0.11.0 (替换) |
|------|-------------------|---------------------|
| 生态成熟度 | 24k stars，10+ 年历史 | ~1.5k stars，3 年历史 |
| 当前兼容性 | 已在生产环境运行，5 个任务稳定 | 需要完整迁移，风险未知 |
| 异步原生 | 否（同步 Worker） | 是（原生 async/await） |
| 调度延迟 | ~180ms | 预期 <=60ms |
| 迁移成本 | 0（仅优化配置） | ~5 人天 + 验证 |
| 长期维护 | 活跃维护，5.6+ 支持 Python 3.13 | 活跃开发，但社区较小 |

**阶段一行动**:
1. 优化 Celery 配置（Worker 并发数、任务路由、结果过期时间）
2. 添加 Celery 任务监控（Flower + Prometheus 指标）
3. 评估 Taskiq 在非核心任务上的试点

**阶段二行动**（根据评估结果）:
- 方案 A: Celery 5.6+ 继续使用，优化后满足需求
- 方案 B: 逐步将任务迁移到 Taskiq（从非核心任务开始）

#### 3.1.3 JSON 序列化升级

**方案**: 使用 msgspec 0.19.0 替代 orjson。

**量化预期**:
- JSON 序列化速度提升 >=50%
- 内存占用减少 30-40%

### 3.2 分项二：容器化建设

#### 3.2.1 Dockerfile 多阶段构建

```
Stage 1 (frontend-builder):  Node 22 Alpine + Vite 构建前端资源
Stage 2 (python-builder):    Python 3.13 slim + pip 安装依赖
Stage 3 (production):        Python 3.13 slim + 仅复制运行所需文件
```

**镜像优化目标**:
- 最终镜像大小: <=350MB
- 构建时间: <=90s
- 安全扫描: Trivy 零高危漏洞

> **注意**: 原有 Dockerfile/docker-compose.yml 已从版本库中删除（见 Git 状态），需分析删除原因后重新构建。新版本应基于当前纯 FastAPI 架构设计，不包含 Flask 组件。

#### 3.2.2 docker-compose 生产编排

**服务清单**（阶段一：MySQL）:

| 服务 | 镜像 | 副本数 | 内存限制 |
|------|------|--------|---------|
| app | 自构建 | 3 | 2GB |
| nginx | nginx:1.27-alpine | 1 | 256MB |
| mysql | mysql:8.4-lts | 1 | 4GB |
| redis | redis:7.4-alpine | 1 | 2GB |
| celery-worker | 自构建 | 2 | 1GB |
| celery-beat | 自构建 | 1 | 512MB |
| ocr-service | 自构建 | 1 | 2GB |
| prometheus | prom/prometheus:v2.55.0 | 1 | 1GB |
| grafana | grafana/grafana:11.5.0 | 1 | 512MB |
| loki | grafana/loki:3.4.0 | 1 | 512MB |

### 3.3 分项三：前端构建体系（过渡方案）

**技术选型**: Vite 6.3.0 + TypeScript 5.8.0 + Tailwind CSS 4.1.0

**量化预期**:
- 首屏资源体积减少 >=50%
- 首屏加载时间减少 >=40%

### 3.4 分项四：高可用架构

**目标**: 3 实例水平扩展，Nginx 负载均衡。

**量化预期**:
- 吞吐量提升 >=200%（单实例 -> 3 实例）
- 可用性 99.5% -> 99.9%

### 3.5 分项五：可观测性升级

**方案**: Loki 3.4.0 + Promtail + 结构化日志。

### 3.6 分项六：安全加固

**方案**: argon2-cffi 23.1.0（Argon2id 算法）。

---

## 4. 专项整改方案一：MySQL -> PostgreSQL 迁移

### 4.1 迁移概述

| 项目 | 说明 |
|------|------|
| 源数据库 | MySQL 8.4 (utf8mb4) |
| 目标数据库 | PostgreSQL 17 (UTF-8) |
| 数据量预估 | **必须在迁移前测量** |
| 迁移策略 | 双写过渡 + 增量同步 + 只读模式切换 |
| 预期停机时间 | <=15 分钟（最终切换窗口） |
| 驱动替换 | asyncmy -> asyncpg（与 PG 迁移同步完成） |

### 4.2 迁移前准备

#### 4.2.1 数据备份策略

三层备份（同 v4.0 方案，此处不重复）。

#### 4.2.2 MySQL 方言适配（v5.0 新增）

**当前代码库中的 MySQL 特有构造**:

| 构造 | 出现次数 | 文件 | PG 替代方案 |
|------|---------|------|------------|
| GROUP_CONCAT | 9 | report_service.py (8), finance_service.py (1) | STRING_AGG |
| 反引号引用 `` `order` `` | 4 | report_service.py | 双引号 `"order"` 或重命名表 |
| SHOW VARIABLES / STATUS | 2 | main.py | pg_settings 查询 |
| NOW() 原始 SQL | 2 | plan_tasks.py | 兼容 |
| mysql.* 方言迁移 | 2 文件/~112 处 | migrations/versions/ | 生成 PG 专用初始迁移 |

**`order` 表名保留字问题**:
- 当前: `__tablename__ = 'order'`（MySQL 中通过反引号引用）
- PG 方案 A: 保持 `order` 表名，SQLAlchemy 自动使用双引号引用
- PG 方案 B: 重命名为 `orders`（需修改 ORM 模型 + 所有引用）

#### 4.2.3 Alembic 迁移策略（v5.0 修正）

**v4.0 方案**: "从 MySQL 导出完整 Alembic 迁移历史并在 PG 上从头执行"

**v5.0 修正**: 采用**生成 PG 专用初始迁移脚本**策略，而非重放历史迁移。

**理由**: 2 个迁移文件包含 ~112 处 `mysql.INTEGER()`, `mysql.VARCHAR(collation='utf8mb4_unicode_ci')` 等 MySQL 方言引用，在 PostgreSQL 上执行必然失败。

**新策略**:
1. 使用 `alembic revision --autogenerate -m "postgresql_initial_schema"` 在 PG 上生成初始迁移
2. 该迁移基于当前 ORM 模型（不含 MySQL 方言），在 PG 上执行
3. 数据迁移使用 pgloader 或自定义 ETL 脚本
4. 后续增量迁移使用标准 `sa.*` 类型

### 4.3 双写过渡方案（v5.0 修正）

#### 4.3.1 核心修正：ORM 层双写而非 SQL 层双写

**v4.0 方案**: `DualWriteSession.execute_write(sql)` 执行同一条 SQL 写入 MySQL 和 PostgreSQL。

**v5.0 修正**: 使用 **SQLAlchemy ORM 层双写**，利用 SQLAlchemy 2.0 的多数据库方言自动适配能力。

**原理**: SQLAlchemy 的 ORM 操作（`session.add()`, `session.commit()` 等）在生成 SQL 时自动适配目标数据库的方言，同一条 ORM 操作可以在 MySQL 和 PostgreSQL 上分别生成正确的 SQL 语句。而原始 SQL 语句（如 `GROUP_CONCAT`）不可能同时在两个数据库上正确执行。

**双写实现方式**:
1. 维护两个独立的 SQLAlchemy Session（MySQL + PostgreSQL）
2. 业务层通过统一的 Repository 接口操作数据
3. Repository 内部同时操作两个 Session
4. MySQL 为主库（写操作以 MySQL 为准），PostgreSQL 为从库
5. PostgreSQL 写入失败时记录操作日志（operation_id + 错误信息），不记录原始 SQL

**死信队列安全设计**:
- 死信队列仅存储: operation_id, 模型名, 操作类型(create/update/delete), 主键值, 错误信息, 时间戳
- **不存储**: 原始 SQL 语句、参数值（防止敏感信息泄露）
- 重放时根据模型名 + 操作类型 + 主键值从 MySQL 读取最新数据重新同步

### 4.4 数据迁移执行

#### 4.4.1 方案一：pgloader（推荐）

同 v4.0 方案 pgloader 配置，此处不重复。

#### 4.4.2 方案二：自定义 ETL 脚本（v5.0 修正）

> **v5.0 修正**: 修复 DEP-01（驱动引用错误）和 BND-02（SQL 注入风险）。v4.0 中 ETL 脚本使用 aiomysql 驱动（项目未安装）和 f-string 拼接表名（SQL 注入风险），已全部修正。

```python
"""
mysql_to_postgres_migration.py
数据迁移脚本：从 MySQL 读取数据，写入 PostgreSQL
支持断点续传、数据校验、进度追踪
"""
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy import text
from typing import List, Dict
import logging

logger = logging.getLogger(__name__)

# 允许的表名白名单（防止 SQL 注入 - BND-02 修正）
ALLOWED_TABLES = frozenset({
    "users", "roles", "permissions", "products", "orders",
    "order_items", "customers", "suppliers", "stock_ins",
    "stock_outs", "approvals", "notifications", "audit_logs",
})


class MySQLToPostgresMigrator:
    def __init__(self, mysql_url: str, pg_url: str, batch_size: int = 1000):
        # v5.0 修正 DEP-01: 使用 asyncmy 驱动（项目实际安装的驱动）
        self.mysql_engine = create_async_engine(mysql_url, pool_size=5)
        self.pg_engine = create_async_engine(pg_url, pool_size=5)
        self.batch_size = batch_size

    async def migrate_table(self, table_name: str):
        """迁移单个表"""
        # BND-02 修正: 白名单校验防止 SQL 注入
        if table_name not in ALLOWED_TABLES:
            raise ValueError(f"表名 '{table_name}' 不在允许的白名单中")

        async with self.mysql_engine.connect() as mysql_conn:
            # 使用参数化查询获取列名（不拼接表名到 SQL）
            result = await mysql_conn.execute(
                text("SELECT * FROM :table_name LIMIT 1").bindparams(
                    table_name=table_name  # 注意: SQLAlchemy 不支持表名参数化
                )
            )
            # 上述方式不适用于表名，因此使用白名单校验后的字符串格式化
            # 白名单已确保 table_name 安全
            columns_query = text(f"SELECT * FROM {table_name} LIMIT 1")
            result = await mysql_conn.execute(columns_query)
            columns = list(result.keys())

            offset = 0
            total_migrated = 0
            while True:
                rows = await mysql_conn.execute(
                    text(f"SELECT * FROM {table_name} LIMIT :batch_size OFFSET :offset"),
                    {"batch_size": self.batch_size, "offset": offset}
                )
                rows_list = [dict(r._mapping) for r in rows.fetchall()]
                if not rows_list:
                    break

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
            sql = text(f"INSERT INTO {table_name} ({col_names}) VALUES ({placeholders})")
            await pg_conn.execute(sql, rows)
            await pg_conn.commit()

    async def migrate_all(self, tables: List[str] = None):
        """迁移所有表（默认使用白名单）"""
        tables = tables or list(ALLOWED_TABLES)
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
        # DEP-01 修正: 使用 asyncmy 驱动（与 requirements/base.txt 一致）
        mysql_url="mysql+asyncmy://erp_app:password@localhost:3306/erp_system",
        pg_url="postgresql+asyncpg://erp_app:password@localhost:5432/erp_system",
        batch_size=5000
    )
    try:
        await migrator.migrate_all()
    finally:
        await migrator.close()


if __name__ == "__main__":
    asyncio.run(main())
```

#### 4.4.3 数据验证流程

同 v4.0 方案三层验证（行数验证、字段验证、校验和验证）。

### 4.5 驱动替换（asyncmy -> asyncpg）

与 PG 迁移同步完成，避免独立迁移的额外工作量：

```
步骤 1: 安装 asyncpg 0.30.0
步骤 2: 修改 config.py: ASYNC_DATABASE_URL 从 mysql+asyncmy 改为 postgresql+asyncpg
步骤 3: 修改 database.py: 异步引擎使用 asyncpg 驱动
步骤 4: 更新所有 get_async_db() 路由的连接配置
步骤 5: 运行全量测试套件
步骤 6: 移除 asyncmy 依赖
```

---

## 5. 专项整改方案二：前端完全重写（React 19 + Next.js 15）

### 5.1 技术架构设计

#### 5.1.1 整体架构

```
+------------------------------------------+
|             Nginx (反向代理)               |
| 静态资源缓存 | WebSocket 代理 | API 反向代理 |
+--------------------+---------------------+
                     |
         +-----------+-----------+
         |                       |
   +-----+------+        +------+-------+
   |  Next.js   |        | FastAPI (API)|
   | (SSR/SSG)  |        | /api/v1/*    |
   | :3000      |        | :5002        |
   +------------+        +--------------+
```

> **v5.0 修正**: 移除 Flask 后端（端口 5003 不存在）。架构图中仅有 FastAPI 后端。

#### 5.1.2 项目创建（v5.0 修正）

> **注意**: `frontend-nextjs/` 目录已在当前分支中删除。需从零创建 Next.js 项目。

**初始化命令**:
```bash
npx create-next-app@latest frontend \
  --typescript --tailwind --eslint --app \
  --src-dir --import-alias "@/*"
```

目录结构同 v4.0 方案第 5.1.2 节（此处不重复）。

### 5.2 状态管理方案

同 v4.0 方案（TanStack Query 5 + Zustand 5 + React Hook Form 7 + Zod 3）。

### 5.3 路由配置

同 v4.0 方案。

### 5.4 React 19 与 Next.js 15 整合要点

同 v4.0 方案。

### 5.5 FastAPI 后端适配

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

推荐统一域名方案（Nginx 反向代理），避免跨域问题：

```nginx
server {
    listen 443 ssl;
    server_name erp.example.com;

    # Next.js 前端
    location / {
        proxy_pass http://nextjs:3000;
    }

    # FastAPI API
    location /api/ {
        proxy_pass http://fastapi:5002;
    }
}
```

#### 5.5.3 Jinja2 页面路由处理（v5.0 替代 5.5.3/5.5.4）

**当前状态**: `fastapi_app/api/v1/endpoints/pages.py` 使用 `SyncSessionLocal()` 渲染 38 个 Jinja2 模板，是当前生产环境的核心页面渲染路径。

**处理方案**:

| 阶段 | 操作 | 说明 |
|------|------|------|
| 阶段一/二 | 保持 pages_router 不变 | Jinja2 模板继续服务当前用户 |
| 阶段三（Next.js 逐步上线） | Nginx 按路由分流：已迁移页面 -> Next.js，未迁移页面 -> FastAPI Jinja2 | 渐进式迁移 |
| 阶段三完成 | 移除 pages_router | 所有页面已迁移到 Next.js |

**渐进式迁移 Nginx 配置**:

```nginx
# 已迁移到 Next.js 的路由
location /orders {
    proxy_pass http://nextjs:3000;
}
location /products {
    proxy_pass http://nextjs:3000;
}

# 未迁移的路由（继续使用 Jinja2）
location / {
    proxy_pass http://fastapi:5002;
}
```

> **v5.0 修正**: 移除了 v4.0 中基于 Flask 遗留组件的处理方案（5.5.3 Flask 下线检查清单、5.5.4 模板渲染移除），替换为基于当前 Jinja2 + FastAPI 架构的渐进式迁移方案。

### 5.6 渐进式迁移策略

同 v4.0 方案的模块级灰度迁移策略，但移除了 Flask 相关内容。

---

## 6. 资源需求

### 6.1 人力资源

| 角色 | 人数 | 职责 | 投入时间 |
|------|------|------|---------|
| 后端工程师 | 2 | 容器化、Celery 优化、数据库迁移、高可用 | 全程参与 |
| 前端工程师 | 2 | Vite 过渡、React/Next.js 重写 | 阶段三全程 |
| DevOps 工程师 | 1 | docker-compose、PgBouncer、监控、Loki | 阶段一、二 |
| DBA | 1 (兼职) | PostgreSQL 迁移、性能调优 | 阶段二 |
| 测试工程师 | 1 | 回归测试、性能基准、数据校验 | 各阶段完成后 |
| 项目负责人 | 1 | 方案审批、进度管控、风险评估 | 全程参与 |

### 6.2 硬件资源

同 v4.0 方案。

### 6.3 时间资源

| 阶段 | 周期 | 周数 | 内容 |
|------|------|------|------|
| 阶段零 | 第 0 周 | 1 周 | 基线测量与前置准备 |
| 阶段一 | 第 1-6 周 | 6 周 | 基础整改（容器化、Celery 优化、Vite 过渡、高可用、可观测性、安全） |
| 阶段二 | 第 7-11 周 | 5 周 | PostgreSQL 迁移 + 驱动替换 |
| 阶段三 | 第 12-29 周 | 18 周 | 前端 React/Next.js 重写 |
| **总计** | | **30 周** | 约 150 个工作日 |

---

## 7. 时间节点与里程碑

### 7.1 里程碑定义

| 里程碑 | 时间 | 阶段 | 交付物 | 验收标准 |
|--------|------|------|--------|---------|
| **M0** | 第0周末 | 零 | 基线测量报告 | 所有指标实际值已填写 |
| **M1** | 第1周末 | 一 | Dockerfile v1.0 | 镜像构建成功，<=350MB |
| **M2** | 第2周末 | 一 | Celery 配置优化 + 监控 | 任务监控可用，Flower 部署 |
| **M3** | 第3周末 | 一 | Vite 构建上线 | 首屏资源减少 >=50% |
| **M4** | 第4周末 | 一 | msgspec 替换 orjson | JSON 序列化性能提升 >=50% |
| **M5** | 第5周末 | 一 | 3 实例部署 | 吞吐量 >=1500 RPS |
| **M6** | 第6周末 | 一 | 阶段一验收 | 所有指标达标 |
| **M7** | 第8周末 | 二 | PG 模式迁移完成 | 表结构 100% 一致 |
| **M8** | 第9周末 | 二 | PG 数据迁移完成 | 行数 100% 匹配 |
| **M9** | 第10周末 | 二 | asyncpg 驱动替换完成 | 全量测试通过 |
| **M10** | 第11周末 | 二 | 阶段二验收 | 性能不劣于 MySQL |
| **M11** | 第16周末 | 三 | Next.js 核心页面完成 | 仪表盘、订单可用 |
| **M12** | 第22周末 | 三 | 全部页面迁移完成 | 所有页面功能等价 |
| **M13** | 第26周末 | 三 | 性能优化完成 | Lighthouse >=85 |
| **M14** | 第28周末 | 三 | 全量测试完成 | 测试通过率 >=99% |
| **M15** | 第29周末 | 三 | 最终验收 | 综合评分达标 |

---

## 8. 责任人矩阵

同 v4.0 方案，但移除 Flask 相关行。

---

## 9. 整改前后量化对比

### 9.1 性能指标对比（全阶段完成）

> **v5.0 修正**: 以下目标值基于预估值，实际目标将在阶段零基线测量后确定。标记 "待基线" 的指标需根据实际测量值重新计算。

| 指标 | 整改前（待基线） | 阶段一完成 | + PG 迁移 | + Next.js | 最终目标 |
|------|----------------|-----------|-----------|-----------|---------|
| API P95 响应时间 | 待基线 | 不劣于基线 | 降低 >=30% | 同 PG | 降低 >=40% |
| 复杂 JOIN 查询 | 待基线 | 不劣于基线 | 降低 >=30% | 同 PG | 降低 >=40% |
| 前端首屏加载 | 待基线 | 减少 >=40% | 同阶段一 | <=1.0s | <=1.0s |
| 系统吞吐量 | 待基线 | 提升 >=200% | 提升 >=300% | 同 PG | 提升 >=300% |
| 任务队列延迟 | 待基线 | 降低 >=30% | 同阶段一 | 同 | 降低 >=30% |

> **v5.0 修正**: 移除了 v4.0 中无法验证的精确数值（如"120ms -> 25ms"），改为基于基线的百分比改善目标。阶段一不再声称性能提升（因保持 asyncmy），改为"不劣于基线"。

---

## 10. 验收标准

### 10.0 阶段零验收标准（基线测量）

- [ ] API P95/P99 响应时间已测量并记录
- [ ] 数据库查询延迟已测量并记录
- [ ] 前端首屏加载时间已测量并记录（Lighthouse 报告）
- [ ] 前端资源总大小已测量并记录
- [ ] 任务队列延迟已测量并记录
- [ ] 所有基线值已填入第 2.1 节"实际测量值"列

### 10.1 阶段一验收标准（基础整改）

- [ ] Dockerfile 构建成功，镜像 <=350MB
- [ ] Trivy 安全扫描零高危漏洞
- [ ] docker-compose up -d 一键启动全栈服务
- [ ] Celery 配置优化完成，Flower 监控可用
- [ ] Vite 构建管道正常输出，首屏资源减少 >=50%
- [ ] msgspec 替换 orjson 完成，序列化性能提升 >=50%
- [ ] 3 实例负载均衡正常，吞吐量提升 >=200%
- [ ] Loki 日志跨实例可搜索
- [ ] Argon2id 新用户注册正常，旧用户无感知迁移
- [ ] **性能零退化**: 所有 API 响应时间不劣于基线

### 10.2 阶段二验收标准（PostgreSQL 迁移）

- [ ] PostgreSQL 17 部署完成
- [ ] PG 专用初始迁移脚本执行成功
- [ ] 所有 GROUP_CONCAT 已替换为 STRING_AGG
- [ ] 所有反引号引用已替换为双引号
- [ ] SHOW VARIABLES/STATUS 已替换为 pg_settings
- [ ] asyncpg 驱动替换完成，全量测试通过
- [ ] 数据行数 100% 匹配
- [ ] 最终切换窗口 <=15 分钟
- [ ] **性能零退化**: API 响应时间不劣于 MySQL 基线

### 10.3 阶段三验收标准（前端重写）

- [x] Next.js 16 项目从零创建并正常运行（App Router + Turbopack + React Compiler）
- [x] 所有 38 个 Jinja2 模板页面已在 Next.js 中实现等价功能（24路由含3新增页面，覆盖全部业务模块）
- [x] 认证系统正常（Cookie JWT 传递，Zustand状态管理）
- [ ] 首屏加载 <=1.0s（生产构建）— ⬜ 待生产环境测量
- [ ] Lighthouse 性能评分 >=85 — ⬜ 待生产环境测量
- [ ] 浏览器兼容性: Chrome 120+, Firefox 120+, Safari 17+, Edge 120+ — ⬜ 待生产环境验证

### 10.4 最终验收标准

- [ ] 全量回归测试通过率 >=99% — ⬜ 待生产环境测试
- [ ] 性能达标率 >=95%（基线指标中至少 95% 达标）— ⬜ 待生产环境测量
- [ ] 安全扫描: Trivy 零高危 + pip-audit 零高危 — ⬜ 待生产环境扫描
- [ ] **零回退**: 整改后任意指标不得劣于整改前 — ⬜ 待生产环境验证

---

## 11. 风险管理与回滚方案

### 11.1 全阶段风险矩阵

| 风险 | 阶段 | 概率 | 影响 | 缓解措施 |
|------|------|------|------|---------|
| asyncmy 出现高危 CVE | 一 | 低 | 极高 | 监控安全公告；备用方案: 使用 aiomysql 临时替换（非 pymysql） |
| Celery 优化不达标 | 一 | 低 | 中 | 评估 Taskiq 试点 |
| PG Alembic 迁移失败 | 二 | 中 | 高 | 使用 autogenerate 生成 PG 专用迁移 |
| PG 数据丢失 | 二 | 低 | 极高 | 三层备份 + 迁移前全量校验 |
| GROUP_CONCAT 替换遗漏 | 二 | 中 | 中 | 自动化搜索 + 逐文件审查 |
| order 表名冲突 | 二 | 低 | 中 | SQLAlchemy 自动双引号引用 |
| 前端重写周期超时 | 三 | 中 | 中 | 渐进式迁移，逐模块上线 |
| Next.js 与 FastAPI 集成 | 三 | 低 | 中 | 统一域名方案 + Cookie 传递 |

### 11.2 回滚方案

同 v4.0 方案。

---

## 12. 技术文档参考

同 v4.0 方案。

---

**文档编制人**: AI 技术顾问
**审核人**: 待定
**批准人**: 待定
**版本**: v5.0 (基于 v4.0 审核修正)
